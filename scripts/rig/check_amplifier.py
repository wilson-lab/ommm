"""Check ommm.Amplifier against Commander, control by control, through the checked write path only.

CHANGES THE AMPLIFIER, and puts it back: run it with a model cell or nothing on the headstage, never a cell.

    uv run --locked python scripts/rig/check_amplifier.py --model-cell CELL [--log-dir DIR]
    uv run --locked python scripts/rig/check_amplifier.py --no-cell-attached [--log-dir DIR]

In V-Clamp, I = 0 and I-Clamp, each row of ommm's settings table that the mode has is read with get, set to one or
two values in range and back (each readback's outcome), then to a value out of its range or off its list, which ommm
must refuse without sending anything; once in a mode without it, it must be refused too. Every checkbox is turned
over and back (Whole Cell refused at 5 and 50 GΩ; Holding and Slow Current Injection never both on in I-Clamp).
set_mode goes V-Clamp, I = 0, I-Clamp, I = 0, V-Clamp, then to I-Clamp and back in one call each, timed. Each button
is pressed where Commander has it, with what a snapshot shows it changed, how long its call took and, after an Auto,
a screenshot; Reset to Program Defaults never. Then Ext on and off, make_safe, and the write log read back with
writes_since and trial_record. It starts from V-Clamp with its tab shown and Mode Switching off, puts Commander back
to the start (rig.py's put-back) and saves one JSON record in --log-dir; it exits 1 if a check did not go as expected.
"""

import json
import sys
import time
from collections import Counter
from ctypes import wintypes
from dataclasses import asdict

import ommm
from ommm import WriteError
from ommm.commander import STARTUP_WINDOW, CommanderError
from ommm.settings import I0, IC, SETTINGS, VC, WHOLE_CELL_RESISTORS, checkbox, checkbox_names, tab_for

import rig  # beside this script

# per row, or per tab where they differ: (unit, values in range, a value ommm must refuse: outside the vendor's range,
# or off Commander's list; None where ommm has neither). An output signal by Commander's name, the refused one from
# the other tab. Ranges at 5 GΩ; the lowpass cutoffs are on both filter types' lists.
VALUES = {
    "Holding": {VC: ("mV", (-10, 10), 1500), IC: ("pA", (-10, 10), 300)},  # I-Clamp: ±1 V / 5 GΩ, ±200 pA
    "Seal Test Amplitude": ("mV", (10, 2), 1500),
    "Seal Test Frequency": ("Hz", (50, 200), 7),
    "Tuning Amplitude": ("pA", (10, -10), 3000),  # ±10 V / 5 GΩ, ±2000 pA
    "Tuning Frequency": ("Hz", (50, 200), 7),
    "Pipette Offset": ("mV", (5, -5), None),  # ±100 mV around the last Auto's level, which nothing reads
    "Slow Current Injection Level": ("mV", (-60, -40), 1500),
    "Slow Current Injection Settling Time": ("ms", (1000, 200), None),
    "Cp Fast Capacitance": ("pF", (1, 2), 40),
    "Cp Fast Tau": ("µs", (1.5, 0.8), 2),
    "Cp Slow Capacitance": ("pF", (1, 0.5), 5),
    "Cp Slow Tau": ("µs", (100, 50), 300),  # Tau x20 off: 10-200 µs
    "Whole Cell Cm": ("pF", (20, 40), 2000),
    "Whole Cell Rs": ("MΩ", (10, 20), 2000),
    "Rs Compensation Bandwidth": ("kHz", (5, 2), 20),
    "Rs Compensation Prediction": ("%", (10, 20), 150),
    "Rs Compensation Correction": ("%", (10, 20), 150),
    "Leak Subtraction": ("MΩ", (500, 100), None),
    "Zap Duration": ("ms", (0.05, 0.1), 0.03),
    "Pipette Capacitance Neutralization": ("pF", (1, 2), None),
    "Bridge Balance": ("MΩ", (10, 20), None),
    "Buzz Duration": ("ms", (1, 10), 1000),
    "Primary Output": {VC: (None, ("Membrane Potential",), "Command Current"), IC: (None, ("Membrane Current",), "Pipette Potential")},
    "Primary Output Gain": ("x", (5, 10), 3),
    "Primary Output Lowpass Filter": ("kHz", (6, 30), 7),
    "AC (Highpass Filter)": ("Hz", (1, 10), 2),
    "Scope Filter": ("kHz", (3,), 5),
    "Output Zero": ("mV", (10, -10), 3000),  # ±2900 mV below a Primary Output gain of 10
    "Secondary Output": {VC: (None, ("Pipette Potential",), "Command Current"), IC: (None, ("Membrane Potential",), "External Command Potential")},
    "Secondary Output Gain": ("x", (10, 1), 3),
    "Secondary Output Lowpass Filter": ("kHz", (100,), 5),
    "Pulse Amplitude": {VC: ("mV", (10, -10), 1500), IC: ("pA", (50, -50), 3000)},
    "Pulse Duration": ("ms", (1, 10), 1000),
}
# what a value in range comes back as, where not ok or adjusted: Correction follows Prediction while the link beside
# it is on, which the API cannot change (P03, P05)
EXPECTED = {"Rs Compensation Correction": "mismatch"}
PRESSED = {  # where each button is pressed; Reset to Program Defaults never
    IC: ("Buzz", "Clear +", "Clear -", "Pulse", "Auto Bridge Balance"),
    VC: ("Pulse", "Zap", "Auto Output Zero", "Auto Leak Subtraction", "Auto Cp Fast", "Auto Cp Slow", "Auto Pipette Offset", "Auto Whole Cell"),
}
BUTTONS = {row.stem for row in SETTINGS if row.kind == "action"}
VALUE_ROWS = [row for row in SETTINGS if row.kind in ("float", "enum") and row.route == "api" and row.stem != "Mode"]


def values(label: str, mode: str) -> tuple:
    entry = VALUES[label]
    return entry[tab_for(mode)] if isinstance(entry, dict) else entry


def checkboxes(mode: str) -> list[str]:
    """The checkboxes on Commander's window in a mode, by the names enable() takes."""
    return sorted(checkbox_names(mode))


class Sending:
    """The DLL under the Amplifier: passes every call through and keeps each Set and button call, what ommm sent."""

    def __init__(self, dll):
        self.dll, self.sent = dll, []

    def __getattr__(self, name):
        return getattr(self.dll, name)

    def call(self, name: str, *args):
        if not (name.startswith("Set") or name in BUTTONS):
            return self.dll.call(name, *args)
        sent, start = {"call": name, "value": args[0] if args else None, "error": None}, time.perf_counter()
        try:
            return self.dll.call(name, *args)
        except CommanderError as error:
            sent["error"] = error.code
            raise
        finally:
            sent["ms"] = rig.ms(time.perf_counter() - start)
            self.sent.append(sent)


class Check:
    """One run: the record its steps go into, the Amplifier, and what went through the DLL."""

    def __init__(self, p: rig.Probe, amp: ommm.Amplifier, sending: Sending):
        self.p, self.amp, self.sending = p, amp, sending
        self.refused_elsewhere = set()  # rows, checkboxes and buttons already refused in a mode without them

    def do(self, check: str, want: str, call, *args, **kwargs) -> ommm.Write:
        """One call on the Amplifier, recorded as a step: its Write, what it sent and how long it took, and whether
        that is what `want` says: refused (and nothing sent), ok (ok or adjusted), or another outcome."""
        first, start = len(self.sending.sent), time.perf_counter()
        try:
            write = call(*args, **kwargs)
        except WriteError as error:
            write = error.write
        sent = self.sending.sent[first:]
        as_expected = write.outcome in (("ok", "adjusted") if want == "ok" else (want,)) and not (want == "refused" and sent)
        self.p.steps.append({"check": check, "want": want, "outcome": write.outcome, "as_expected": as_expected,
                             "ms": rig.ms(time.perf_counter() - start), "sent": sent, "write": asdict(write)})
        print(f"  {check}: {write.outcome}{f' ({write.reason})' if write.reason else ''}{'' if as_expected else '  << NOT AS EXPECTED'}", flush=True)
        return write

    def get(self, mode: str, label: str, unit: str | None = None):
        try:
            value, error = self.amp.get(label, unit), None
        except (ValueError, CommanderError) as caught:
            value, error = None, str(caught)
        self.p.steps.append({"check": f"{mode}: get {label}" + (f" in {unit}" if unit else ""), "value": value,
                             "error": error, "as_expected": error is None})
        print(f"  {mode}: get {label} {unit or ''}: {value!r} {error or ''}", flush=True)
        return value

    def set(self, mode: str, want: str, label: str, value, unit: str | None = None, **options) -> ommm.Write:
        shown = " ".join(str(part) for part in (value, unit) if part is not None)
        extra = "".join(f" {key}={option}" for key, option in options.items())
        return self.do(f"{mode}: set {label} {shown}{extra}", want, self.amp.set, label, value, unit, **options)

    def mode(self, mode: str, want: str = "ok"):
        self.do(f"set_mode {mode}", want, self.amp.set_mode, mode)

    def run(self):
        _, mark = self.amp.writes_since()
        start = self.amp.snapshot()
        self.whole_cell = self.amp.get("Feedback Resistor", "Ohm") in WHOLE_CELL_RESISTORS
        if sys.platform == "win32":
            self.startup_window()
        self.rules()
        for mode in (VC, I0, IC):
            if mode != VC:
                self.mode(mode)  # V-Clamp -> I = 0 -> I-Clamp
            self.section(mode)
        for mode in (I0, VC, IC, VC, VC):  # back through I = 0; then I-Clamp and back in one call each; then already there
            self.mode(mode)
        for name in PRESSED[VC]:
            self.press(VC, name)
        self.ext()
        self.make_safe()
        self.log(start, mark)

    def startup_window(self):
        """P18: Commander's hidden window, which every write looks for first, found by its title or by its class."""
        find = rig.user32.FindWindowW
        find.restype, find.argtypes = wintypes.HWND, [wintypes.LPCWSTR, wintypes.LPCWSTR]
        self.p.note(f"Commander's window {STARTUP_WINDOW!r}", by_title=bool(find(None, STARTUP_WINDOW)),
                    by_class=bool(find(STARTUP_WINDOW, None)))

    def rules(self):
        """What ommm refuses whatever the row, plan(), expect= and step=, in V-Clamp."""
        self.do("V-Clamp: plan Holding -10 mV", "planned", self.amp.plan, "Holding", -10, "mV")
        self.set(VC, "refused", "Holding", 10)
        self.set(VC, "refused", "Holding", 10, "pA")
        self.set(VC, "refused", "Holding", "ten", "mV")
        self.set(VC, "refused", "Holding", 5, "mV", expect=7)
        self.set(VC, "refused", "Mode", "I-Clamp")
        self.set(VC, "refused", "Feedback Resistor", 500, "MΩ")
        self.set(VC, "refused", "Zap", 1)
        self.set(VC, "refused", "Cp Slow Tau x20", True)
        self.do("V-Clamp: press Holding", "refused", self.amp.press, "Holding")
        self.do("V-Clamp: enable Holding 'yes'", "refused", self.amp.enable, "Holding", "yes")
        self.mode("Voltage Clamp", "refused")
        self.set(VC, "ok", "Holding", -20, "mV", step=5)
        self.set(VC, "ok", "Holding", 0, "mV", expect=-20)

    def section(self, mode: str):
        for label, unit in (("Mode", None), ("Feedback Resistor", "MΩ"), ("MeterValue1", "mV"), ("MeterValue2", "pA")):
            self.get(mode, label, unit)
        for row in VALUE_ROWS:
            if mode in row.modes:
                self.row(mode, row.label)
            elif row.label not in self.refused_elsewhere:
                self.refused_elsewhere.add(row.label)
                unit, (value, *_), _ = values(row.label, row.modes[0])
                self.set(mode, "refused", row.label, value, unit)
        shown = checkboxes(mode)
        for name in shown:
            if name != "Mode Switching":  # Ext: ext()
                self.turn_over(mode, name)
        for name in sorted({name for other in (VC, I0, IC) for name in checkboxes(other)} - set(shown) - self.refused_elsewhere):
            self.refused_elsewhere.add(name)
            self.do(f"{mode}: enable {name} True", "refused", self.amp.enable, name, True)
        for row in SETTINGS:
            if row.kind == "action" and mode not in row.modes and row.label not in self.refused_elsewhere:
                self.refused_elsewhere.add(row.label)
                self.do(f"{mode}: press {row.label}", "refused", self.amp.press, row.label)
        if mode == IC:
            self.never_both()
            for name in PRESSED[IC]:
                self.press(IC, name)

    def row(self, mode: str, label: str):
        """get, the values in range, back to the value found, and the refused one."""
        unit, in_range, refused = values(label, mode)
        found = self.get(mode, label, unit)
        want = EXPECTED.get(label, "ok")
        if label.startswith("Whole Cell") and not self.whole_cell:
            want = "refused"
        for value in in_range:
            self.set(mode, want, label, value, unit)
        self.set(mode, "refused" if want == "refused" else "ok", label, found, unit)
        if refused is not None:
            self.set(mode, "refused", label, refused, unit)

    def turn_over(self, mode: str, name: str):
        """A checkbox turned over and back; Whole Cell refused on where Commander's window greys it out."""
        stem = checkbox(name, mode)[1]
        found = self.get(mode, stem)
        for on in (not found, found):
            want = "refused" if on and stem == "WholeCellCompEnable" and not self.whole_cell else "ok"
            self.do(f"{mode}: enable {name} {on}", want, self.amp.enable, name, on)

    def never_both(self):
        """Holding and Slow Current Injection in I-Clamp: either one on refuses the other."""
        for first, second in (("Slow Current Injection", "Holding"), ("Holding", "Slow Current Injection")):
            self.do(f"I-Clamp: enable {first} True", "ok", self.amp.enable, first, True)
            self.do(f"I-Clamp: enable {second} True, with {first} on", "refused", self.amp.enable, second, True)
            self.do(f"I-Clamp: enable {first} False", "ok", self.amp.enable, first, False)

    def press(self, mode: str, name: str):
        """A button, and any window it leaves open stops the check (only a person may close it); an Auto's screenshot."""
        windows = set(rig.screen.commander_windows())
        want = "refused" if name == "Auto Whole Cell" and not self.whole_cell else "ok"
        write = self.do(f"{mode}: press {name}", want, self.amp.press, name)
        self.p.stop_if_window_left(windows, name)
        if name.startswith("Auto") and write.outcome != "refused":
            self.p.steps[-1]["screenshot"] = self.p.screenshot(name.lower().replace(" ", "_"))

    def ext(self):
        """Mode Switching (Ext.): off stays off, on and off again, a write refused while on; then back to V-Clamp,
        since the mode follows the MODE input while it is on (P07)."""
        self.do("V-Clamp: enable Ext False, already off", "ok", self.amp.enable, "Ext", False)
        self.do("V-Clamp: enable Ext True", "ok", self.amp.enable, "Ext", True)
        self.do("with Ext on: set Holding 0 mV", "refused", self.amp.set, "Holding", 0, "mV")
        self.do("with Ext on: enable Ext False", "ok", self.amp.enable, "Ext", False)
        self.mode(VC)

    def make_safe(self):
        for name in ("Seal Test", "Resistance Meter", "Rs Compensation"):
            self.do(f"V-Clamp: enable {name} True", "ok", self.amp.enable, name, True)
        for check, count in (("V-Clamp: make_safe", 3), ("V-Clamp: make_safe, nothing left on", 0)):
            first = len(self.sending.sent)
            try:
                writes, error = self.amp.make_safe(), None
            except WriteError as caught:
                writes, error = [caught.write], str(caught)
            as_expected = error is None and len(writes) == count
            self.p.steps.append({"check": check, "want": f"{count} turned off", "outcome": "error" if error else "ok",
                                 "as_expected": as_expected, "sent": self.sending.sent[first:], "writes": [asdict(w) for w in writes]})
            print(f"  {check}: {[w.label for w in writes]} {error or ''}{'' if as_expected else '  << NOT AS EXPECTED'}", flush=True)

    def log(self, start: dict, mark: int):
        """The log since the start, read back: a line for every Set and button sent and for every refusal, and in
        trial_record every change since the start snapshot from ommm, none from Commander's window."""
        lines, _ = self.amp.writes_since(mark)
        changed = ommm.trial_record(start, self.amp.snapshot(), lines)["changed"]
        gui = {key: entry for fields in changed.values() for key, entry in fields.items() if entry["source"] == "gui"}
        outcomes = Counter(line["outcome"] for line in lines)
        refused = sum(step.get("outcome") == "refused" for step in self.p.steps if "check" in step)
        provenance = {key: value for key, value in ommm.provenance().items() if key != "git_error"}
        found = {"lines": len(lines), "outcomes": dict(outcomes), "refused_checks": refused, "sent_calls": len(self.sending.sent),
                 "serials": sorted({line["serial"] for line in lines}), "ommm_as_running": all(line["ommm"] == provenance for line in lines),
                 "from_gui": gui}
        as_expected = (outcomes["refused"] == refused and len(lines) - outcomes["refused"] == len(self.sending.sent)
                       and found["serials"] == [self.amp.serial] and found["ommm_as_running"] and not gui)
        self.p.steps.append({"check": "the write log, by writes_since and trial_record", "as_expected": as_expected, **found})
        print(f"  the write log: {json.dumps(found, default=str)}{'' if as_expected else '  << NOT AS EXPECTED'}", flush=True)


def body(p: rig.Probe):
    sending = Sending(p.c.dll)
    p.c.dll = sending
    try:
        Check(p, ommm.Amplifier(log_dir=p.log_dir, commander=p.c), sending).run()
    finally:
        p.c.dll = sending.dll
    failed = [step["check"] for step in p.steps if step.get("as_expected") is False]
    print(f"{sum('check' in step for step in p.steps)} checks, {len(failed)} not as expected" + "".join(f"\n  {check}" for check in failed))


if __name__ == "__main__":
    record = rig.run("check_amplifier", __doc__.split("\n\n")[0], body)
    if any(step.get("as_expected") is False for step in json.loads(record.read_text(encoding="utf-8"))["steps"]):
        sys.exit(1)
