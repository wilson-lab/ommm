"""check_amplifier.py's harness: the start check, the record, and the put-back.

run() refuses unless told what is on the headstage, nothing or a model cell with its switch's position, which the
record's header keeps, and unless Commander is in the start state (V-Clamp active, its tab shown, Mode Switching off).
The put-back (put_back) writes through Commander's raw, private _set() and _call() and logs each write as one JSON
line in DIR/writes.jsonl; run() saves one JSON in DIR (--log-dir): a header, both tabs' snapshots at start and end,
every step taken and seen, and whatever was left changed.

The GUI helpers drive Commander's main window only: the mode tabs, the Mode Switching checkbox and the Pipette Offset
padlocks on the tab shown.
"""

import argparse
import ctypes
import json
import math
import sys
import time
import traceback
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import ommm
from ommm.commander import Commander, CommanderError, NotApplicable, changes
from ommm.settings import MODES, TABS, tab_for

VCLAMP, ICLAMP, ICLAMPZERO = MODES  # the MCCMSG_MODE_* ids
MSGTIMEOUT = 6005  # MCCMSG_ERROR_MSGTIMEOUT: Commander did not answer within the DLL's timeout
SIGNALS = ("PrimarySignal", "SecondarySignal")  # put back first: a signal change brings other values with it (P10)
APART = ("Mode", "ModeSwitchEnable", *SIGNALS, "PipetteOffset")  # put_back writes these on their own
SCALED = {"SlowCompTauX20Enable": "SlowCompTau", "PrimarySignalGain": "OutputZeroAmplitude"}  # writing the first
# rescales the second's reading: Tau x20 multiplies Cp Slow's Tau by 20 (P20), Output Zero scales with the gain (P10)
SETTLE_S = 0.3  # for a Set to show in a read
MODE_SETTLE_S = 1.0
MODEL_CELL = ("BATH", "PATCH", "CELL")  # the model cell's switch positions

TAB_CONTROL, EXT = 12320, 2225  # control ids on Commander's main window
# Pipette Offset's padlock and Auto on each tab, from Commander's control list
OFFSET_LOCK = {"V-Clamp": (1202, 1203), "I-Clamp": (1302, 1303)}
TCM_GETCURSEL, WM_LBUTTONDOWN, WM_LBUTTONUP, BM_CLICK, BM_GETCHECK = 0x130B, 0x0201, 0x0202, 0x00F5, 0x00F0

if sys.platform == "win32":
    sys.path.insert(0, str(Path(__file__).parents[1]))  # scripts/
    import screenshot_commander as screen

    user32 = screen.user32
    ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    for func, restype, argtypes in [
        (user32.EnumChildWindows, wintypes.BOOL, [wintypes.HWND, ENUM_PROC, wintypes.LPARAM]),
        (user32.GetDlgCtrlID, ctypes.c_int, [wintypes.HWND]),
        (user32.SendMessageW, wintypes.LPARAM, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
        (user32.PostMessageW, wintypes.BOOL, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
        (user32.IsWindow, wintypes.BOOL, [wintypes.HWND]),
        (user32.IsWindowEnabled, wintypes.BOOL, [wintypes.HWND]),
    ]:
        func.restype, func.argtypes = restype, argtypes


def ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


def wait_for(condition, timeout_s: float) -> bool:
    """Poll condition() every 0.1 s until it holds (True) or timeout_s has passed (False)."""
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


def looks(returned: float, look, at_s: tuple[float, ...]) -> list[dict]:
    """look() at each time in at_s, in seconds after `returned` (a perf_counter time), each with the ms it ran at."""
    seen = []
    for at in at_s:
        time.sleep(max(0.0, returned + at - time.perf_counter()))
        seen.append({"ms": ms(time.perf_counter() - returned), **look()})
    return seen


def main_window() -> int:
    return next(hwnd for hwnd in screen.commander_windows() if screen.title(hwnd).startswith("MultiClamp 700B"))


def children(window: int) -> list[int]:
    found = []
    user32.EnumChildWindows(window, ENUM_PROC(lambda hwnd, _: found.append(hwnd) or True), 0)
    return found


def control(key: int | str, window: int | None = None) -> int:
    """A visible control in a Commander window (the main one unless given), the shown tab's included, by id
    or by its text ("Holding:"; "&" ignored): a tab's controls may have other ids on the other tab."""
    for hwnd in children(window or main_window()):
        if user32.IsWindowVisible(hwnd) and key in (user32.GetDlgCtrlID(hwnd), screen.title(hwnd).replace("&", "")):
            return hwnd
    raise LookupError(f"no visible control {key!r} in Commander's window {screen.title(window or main_window())!r}")


def shown_tab() -> int:
    return user32.SendMessageW(control(TAB_CONTROL), TCM_GETCURSEL, 0, 0)


tab_x = {}  # where each tab was hit, so later clicks go straight there


def show_tab(tab: int):
    """Click Commander's V-Clamp (0) or I-Clamp (1) tab, as a person would; the mode stays."""
    if shown_tab() == tab:
        return
    tabs = control(TAB_CONTROL)
    tried_first = [tab_x[tab]] if tab in tab_x else []
    for x in tried_first + list(range(10, 300, 10)):  # tab widths can't be read from another process
        user32.PostMessageW(tabs, WM_LBUTTONDOWN, 1, (8 << 16) | x)
        user32.PostMessageW(tabs, WM_LBUTTONUP, 0, (8 << 16) | x)
        time.sleep(0.3)
        if shown_tab() == tab:
            tab_x[tab] = x
            time.sleep(0.5)  # let the page draw before it is read
            return
    raise RuntimeError(f"could not show Commander's tab {tab}")


def snapshot_of_tab_shown(c) -> dict:
    """A snapshot of the tab Commander shows, which need not be the active mode's: the put-back reads each tab in turn."""
    return c.snapshot(show_active_tab=False)


def on_each_tab(look) -> dict:
    """{tab: look()} with each of Commander's tabs shown in turn, in the current mode; the tab shown before
    is shown again. Reads follow the tab shown."""
    shown, found = shown_tab(), {}
    for tab, name in enumerate(TABS):
        show_tab(tab)
        found[name] = look()
    show_tab(shown)
    return found


def is_checked(key: int | str) -> bool:
    return user32.SendMessageW(control(key), BM_GETCHECK, 0, 0) == 1


def screenshot(path: Path, window: int | None = None):
    width, height, rgb = screen.capture(window or main_window())
    screen.write_png(path, width, height, rgb)


def is_open(window: int) -> bool:
    return bool(user32.IsWindow(window) and user32.IsWindowVisible(window))


def log_line(probe: str, *, stem: str, mode: int, before, target, after, error: CommanderError | None) -> dict:
    """One raw write, with the write log's key names (schema 1). An action (an Auto, ...) has the action's
    name as `stem` and no target: before and after are the readings it changes."""
    return {
        "schema": 1,
        "t": datetime.now().astimezone().isoformat(),
        "probe": probe,
        "stem": stem,
        "mode": mode,
        "before": before,
        "target": target,
        "after": after,
        "outcome": "error" if error else "ok" if target is None or after == target else "mismatch",
        "error_code": error.code if error else None,
        "reason": str(error) if error else None,
        "ommm": {key: value for key, value in ommm.provenance().items() if key != "git_error"},
    }


def log_write(path: Path, line: dict):
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(line) + "\n")


def header(probe: str, question: str, snapshot: dict, setup: str) -> dict:
    """What a record starts with: the run's name (`probe`), when, what was on the headstage (setup()), and which
    Commander, API and ommm."""
    packet = snapshot["telegraph"] or {}
    return {
        "probe": probe,
        "question": question,
        "time": snapshot["time"],
        "setup": setup,
        "commander": packet.get("szAppVersion"),
        "firmware": packet.get("szFirmwareVersion"),
        "dsp": packet.get("szDSPVersion"),
        "api_version": snapshot["api_version"],
        "ommm": snapshot["ommm"],
    }


class Probe:
    """One run: the Commander handle, what was on the headstage (setup()), what it wrote and what it saw."""

    def __init__(self, probe: str, question: str, commander, log_dir: Path, setup: str):
        self.id, self.question, self.c, self.log_dir, self.setup = probe, question, commander, log_dir, setup
        self.log_path = log_dir / "writes.jsonl"
        self.steps = []
        self.start = self.end = self.left_changed = self.error = None

    def read(self, stem: str, *args):
        """Get<stem>, or "not applicable (code)" where Commander hands back its code as the value."""
        try:
            return self.c.get(stem, *args)
        except NotApplicable as error:
            return f"not applicable ({error.code})"

    def reads(self, *stems: str) -> dict:
        return {stem: self.read(stem) for stem in stems}

    def write(self, stem: str, value, settle: float = SETTLE_S) -> dict:
        """Set<stem>(value) through the raw API, read before and after; a refusal is an answer, so it is
        recorded, not raised, unless Commander stopped answering."""
        mode, before = self.c.get("Mode"), self.read(stem)
        error, called = None, time.perf_counter()
        try:
            self.c._set(stem, value)
        except CommanderError as caught:
            error = caught
        returned = time.perf_counter()
        time.sleep(settle)
        line = log_line(self.id, stem=stem, mode=mode, before=before, target=value, after=self.read(stem), error=error)
        log_write(self.log_path, line)
        self.steps.append({"write": line, "set_ms": ms(returned - called)})
        print(f"  set {stem} {value!r}: {before!r} -> {line['after']!r} {line['outcome']} {line['reason'] or ''}", flush=True)
        if error and error.code == MSGTIMEOUT:
            raise error
        return line

    def press(self, action: str, watched: tuple[str, ...], at_s: tuple[float, ...] = (0, 0.1, 0.5, 1, 2, 5)) -> dict:
        """Call <action> (an Auto, ...) through the raw API, timed, and read `watched` before it and at each
        time in at_s after it returned: an Auto that blocks until done shows its result at 0 s. A refusal or
        a timeout is an answer, recorded, not raised; a window it leaves open stops the run. The step's `changed`
        holds, per tab, every reading and telegraph field that differs after the last look (an Auto can change
        the other tab too, P16); finish() puts them back."""
        mode, before, windows = self.c.get("Mode"), self.reads(*watched), set(screen.commander_windows())
        tabs = on_each_tab(lambda: snapshot_of_tab_shown(self.c))
        error, called = None, time.perf_counter()
        try:
            self.c._call(action)
        except CommanderError as caught:
            error = caught
        returned = time.perf_counter()
        step = {"press": action, "call_ms": ms(returned - called), "error": str(error) if error else None}
        self.steps.append(step)
        print(f"  {action}: {step['call_ms']} ms {step['error'] or ''}", flush=True)
        try:
            self.stop_if_window_left(windows, action)
        except RuntimeError:
            log_write(self.log_path, log_line(self.id, stem=action, mode=mode, before=before, target=None, after=None, error=error))
            raise
        if error and error.code == MSGTIMEOUT:
            step["answers_again_after_s"] = self.wait_for_answer()
        step["looks"] = looks(returned, lambda: self.reads(*watched), at_s)
        after = on_each_tab(lambda: snapshot_of_tab_shown(self.c))
        step["changed"] = {name: diff for name in TABS if (diff := changes(tabs[name], after[name]))}
        step["write"] = log_line(self.id, stem=action, mode=mode, before=before, target=None, after=self.reads(*watched), error=error)
        log_write(self.log_path, step["write"])
        return step

    def stop_if_window_left(self, before: set[int], what: str):
        """Stop the run if `what` left a Commander window open for 10 s (an error box, say), since only a
        person may close it; its screenshot is kept."""
        new = set(screen.commander_windows()) - before
        if new and not wait_for(lambda: not any(is_open(window) for window in new), 10):
            shots = {screen.title(window): self.screenshot("window_left_open", window) for window in new if is_open(window)}
            raise RuntimeError(f"{what} left Commander's {shots} open: only a person may close it")

    def wait_for_answer(self, limit_s: float = 60) -> float:
        """Seconds until Commander answers a Get again after a timeout, e.g. while an Auto still runs."""
        start = time.perf_counter()
        while True:
            try:
                self.c.get("Mode")
                return round(time.perf_counter() - start, 1)
            except CommanderError as error:
                if error.code != MSGTIMEOUT or time.perf_counter() - start > limit_s:
                    raise

    def note(self, what: str, **seen) -> dict:
        """A step: what was done or looked at, with the mode, the tab shown and what was seen."""
        step = {"t": datetime.now().astimezone().isoformat(), "note": what, "mode": self.c.get("Mode"), "tab": shown_tab(), **seen}
        self.steps.append(step)
        print(what, json.dumps({key: value for key, value in step.items() if key not in ("t", "note")}, default=str), flush=True)
        return step

    def screenshot(self, name: str, window: int | None = None) -> str:
        path = self.log_dir / f"{self.id.lower()}_{datetime.now():%H%M%S}_{name}.png"
        screenshot(path, window)
        return path.name

    def set_mode(self, mode: int):
        """Change mode the way Commander's buttons allow: V-Clamp <-> I-Clamp through I = 0."""
        current = self.c.get("Mode")
        if current == mode:
            return
        if {current, mode} == {VCLAMP, ICLAMP}:
            self.write("Mode", ICLAMPZERO, MODE_SETTLE_S)
        self.write("Mode", mode, MODE_SETTLE_S)

    def put_back_pipette_offsets(self, targets: dict[str, float]):
        """Set each tab's Pipette Offset ({"V-Clamp": V, "I-Clamp": V}) that differs, in its own mode, pressing Auto
        Pipette Offset in V-Clamp until every target is in reach. A Set is held within 100 mV of the last Auto's
        level, per Commander's Help; with nothing attached that level wanders from Auto to Auto (+55 mV, then
        -125 mV in P06), and an Auto in V-Clamp sets both tabs' levels while one in I-Clamp changes neither (P16).
        At most 10 Autos; harmless with nothing attached or a model cell.
        Ends in the mode it started in, with its tab shown."""
        now = on_each_tab(lambda: self.reads("PipetteOffset"))
        if all(now[name]["PipetteOffset"] == target for name, target in targets.items()):
            return
        mode = self.c.get("Mode")
        for _ in range(10):
            reached = True
            for name, target in targets.items():
                self.set_mode(VCLAMP if name == "V-Clamp" else ICLAMP)
                show_tab(TABS.index(name))
                reached &= math.isclose(self.write("PipetteOffset", target)["after"], target, abs_tol=1e-4)
            if reached:
                self.set_mode(mode)
                show_tab(TABS.index(tab_for(MODES[mode])))
                return
            self.set_mode(VCLAMP)
            show_tab(TABS.index("V-Clamp"))
            self.press("AutoPipetteOffset", ("PipetteOffset",), at_s=(0,))
        raise RuntimeError(f"Pipette Offsets {targets} (V) out of reach after 10 Auto Pipette Offsets: set them by hand")

    def unlock_pipette_offset(self):
        """Auto Pipette Offset locks the padlock beside its Auto button and greys the Auto out, per Commander's Help;
        it is open in the start state. On each tab, click a locked one open, and say if it stays shut."""
        shown = shown_tab()
        for tab, name in enumerate(TABS):
            show_tab(tab)
            padlock, auto = OFFSET_LOCK[name]
            try:
                locked = not user32.IsWindowEnabled(control(auto))
                if locked:  # posted: a click that opened a dialog would not return
                    windows = set(screen.commander_windows())
                    user32.PostMessageW(control(padlock), BM_CLICK, 0, 0)
                    time.sleep(1)
                    self.stop_if_window_left(windows, "clicking the Pipette Offset padlock")
                still = not user32.IsWindowEnabled(control(auto))
                what = "still locked: click it open by hand" if still else "clicked open" if locked else "open"
            except LookupError as error:
                what = f"{error}: check it by hand"
            self.note(f"Pipette Offset padlock, {name} tab: {what}", screenshot=self.screenshot(f"padlock_{tab}"))
        show_tab(shown)

    def finish(self):
        """Put Commander back to the start state if any reading or telegraph field differs from it, click the
        padlock open after an Auto Pipette Offset, and record what is left changed."""
        if any(changes(self.start[name], now) for name, now in on_each_tab(lambda: snapshot_of_tab_shown(self.c)).items()):
            put_back(self, self.start, VCLAMP)
        elif any(step.get("press") == "AutoPipetteOffset" for step in self.steps):
            self.unlock_pipette_offset()
        show_tab(TABS.index("V-Clamp"))
        self.end = on_each_tab(lambda: snapshot_of_tab_shown(self.c))
        self.left_changed = {name: diff for name in TABS if (diff := changes(self.start[name], self.end[name]))}
        self.note("end", screenshot=self.screenshot("end"))

    def save(self) -> Path:
        record = {
            "header": header(self.id, self.question, self.start["V-Clamp"], self.setup),
            "steps": self.steps,
            "left_changed": self.left_changed,
            "error": self.error,
            "start": self.start,
            "end": self.end,
        }
        path = self.log_dir / f"{self.id.lower()}_{datetime.now():%Y%m%dT%H%M%S}.json"
        path.write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
        return path


def writes(target: dict, current: dict, settable: set[str]) -> list[tuple[str, object]]:
    """The writes, APART aside, that take one tab's readings from current to target, in an order that works
    from any state: Tau x20 first; enables going off; values, the Primary Output gain first; then enables
    going on. A value SCALED by an earlier write is written after it even if it agreed before. So no value is
    stepped with its enable on, and Holding and Slow Current Injection, which the API lets be on together
    (P13), are never both on along the way."""
    def rank(stem: str) -> int:
        if stem == "SlowCompTauX20Enable":
            return 0
        if stem.endswith("Enable"):
            return 4 if target[stem] else 1
        return 2 if stem == "PrimarySignalGain" else 3

    differ = [stem for stem in target if stem in settable and stem not in APART and current.get(stem) != target[stem]]
    for stem, scaled in SCALED.items():
        if stem in differ and scaled in target and scaled in settable and scaled not in differ:
            differ.append(scaled)
    return [(stem, target[stem]) for stem in sorted(differ, key=rank)]


def put_back(p: Probe, targets: dict[str, dict], mode: int):
    """Put Commander back to a snapshot per tab ({"V-Clamp": snapshot, "I-Clamp": snapshot}) from any state,
    ending in `mode` with its tab shown. Ext off first: with it on SetMode is ignored, and one Set turns it off,
    whatever it toggles (P07). Then each tab, in that tab's mode with the tab shown, so this does not depend on
    where a Set with the other tab shown lands (P01), the mode's own tab last: both output signals, always
    (a signal Set also refreshes the telegraph), then writes(). Then both Pipette Offsets together, since
    reaching one can take an Auto that moves both; the mode; and the padlock an Auto locked, clicked open
    last (a Set works locked, P06). The feedback resistor has no setter, so a difference there stays."""
    if p.read("ModeSwitchEnable"):
        p.write("ModeSwitchEnable", False, MODE_SETTLE_S)
    settable = {name[3:] for name in p.c.functions if name.startswith("Set")}
    for tab in sorted(targets, key=lambda tab: tab == tab_for(MODES[mode])):
        target = targets[tab]["readings"]
        p.set_mode(VCLAMP if tab == "V-Clamp" else ICLAMP)
        show_tab(TABS.index(tab))
        for stem in SIGNALS:
            p.write(stem, target[stem])
        for stem, value in writes(target, snapshot_of_tab_shown(p.c)["readings"], settable):
            p.write(stem, value)
    p.put_back_pipette_offsets({tab: target["readings"]["PipetteOffset"] for tab, target in targets.items()})
    p.set_mode(mode)
    p.unlock_pipette_offset()
    show_tab(TABS.index(tab_for(MODES[mode])))


def parser(description: str) -> argparse.ArgumentParser:
    """The options the check takes: what is on the headstage, and --log-dir."""
    cli = argparse.ArgumentParser(description=description)
    attached = cli.add_mutually_exclusive_group()
    attached.add_argument("--no-cell-attached", action="store_true", help="confirm nothing is attached to the headstage")
    attached.add_argument("--model-cell", type=str.upper, choices=MODEL_CELL, metavar="POSITION",
                          help="confirm a model cell is on the headstage, its switch at BATH, PATCH or CELL")
    cli.add_argument("--log-dir", type=Path, default=Path.home() / "ommm-logs" / f"check_{datetime.now():%Y%m%d}")
    return cli


def setup(args: argparse.Namespace, script: str) -> str:
    """What is on the headstage, as the record's header keeps it, from the command line; exits without it, since the
    check changes settings and the record must not guess."""
    if args.model_cell:
        return f"amplifier on, a model cell on the headstage, its switch at {args.model_cell} (--model-cell {args.model_cell})"
    if args.no_cell_attached:
        return "amplifier on, nothing attached to the headstage (--no-cell-attached)"
    sys.exit(f"{script}: say what is on the headstage: --no-cell-attached, or --model-cell BATH, PATCH or CELL")


def run(probe: str, question: str, body) -> Path:
    """Check Commander is in the start state, run body(p), put Commander back (finish), save the record; its path."""
    question = " ".join(question.split())
    sys.stdout.reconfigure(encoding="utf-8")  # questions hold Ω, which a cp1252 stdout lacks
    args = parser(question).parse_args()
    attached = setup(args, probe)
    args.log_dir.mkdir(parents=True, exist_ok=True)

    with Commander() as c:
        found = {"Mode": c.get("Mode"), "tab": shown_tab(), "Ext": is_checked(EXT), "ModeSwitchEnable": c.get("ModeSwitchEnable")}
        if found != {"Mode": VCLAMP, "tab": TABS.index("V-Clamp"), "Ext": False, "ModeSwitchEnable": False}:
            sys.exit(f"{probe}: start with V-Clamp active, its tab shown and Mode Switching off; found {found}")
        p = Probe(probe, question, c, args.log_dir, attached)
        print(f"{probe}: {question}\n  {attached}", flush=True)
        p.start = on_each_tab(lambda: snapshot_of_tab_shown(c))
        try:
            body(p)
        except Exception:  # put Commander back whatever happened, and keep the record
            p.error = traceback.format_exc()
        try:
            p.finish()
        except Exception:
            p.error = (p.error or "") + traceback.format_exc()
        path = p.save()
    print(f"{probe}: record {path}\n  left changed (meters aside): {json.dumps(p.left_changed)}", flush=True)
    if p.error:
        sys.exit(p.error)
    return path
