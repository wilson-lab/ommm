"""ommm.Amplifier: one headstage of the one MultiClamp 700B, read and set by Commander's labels, with explicit units.

    amp = ommm.Amplifier()                    # headstage 1; Amplifier(2); Amplifier(fake=ommm.EXAMPLES / "fake/vclamp.json")
    amp.get("Holding", "mV")                  # -60.0
    amp.set("Holding", -60, "mV")             # -> Write; WriteError when it is refused or does not take
    amp.plan("Holding", -60, "mV")            # the same checks; sends nothing
    amp.enable("Seal Test", True)             # a checkbox, by its name on Commander's window
    amp.press("Auto Bridge Balance")          # a button
    amp.set_mode("I-Clamp")                   # through I = 0
    amp.load_config("my.mcc", changes=[("Feedback Resistor", 500, "MΩ", "V-Clamp")])  # the plan; confirmed=True does it

Commander is the only copy of its settings: each call reads what it needs first, every write is read back and logged
(ommm.log), and nothing is retried or rolled back, but for a load_config start that did not apply its file, which gets
one more. docs/writes.md has the rules every write follows.
"""

import math
import numbers
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import ommm
from ommm import log, mcc
from ommm.checks import CHECKED, disagreements
from ommm.commander import Commander, CommanderError, NotApplicable, shortest_float32
from ommm.commander import changes as snapshot_changes
from ommm.process import (
    EXE,
    PROCESS,
    launch_commander,
    others_running,
    quit_commander,
    wait_for_api,
)
from ommm.sdk import install_dir
from ommm.settings import (
    ALSO_CHANGES,
    CHECKBOXES,
    FEEDBACK_RESISTORS,
    HEADSTAGES,
    I0,
    IC,
    IC_FEEDBACK_RESISTORS,
    MODES,
    SETTINGS,
    TAU_X20_RANGES,
    VC,
    WHOLE_CELL_RESISTORS,
    Setting,
    checkbox,
    checkbox_label,
    checkbox_modes,
    checkbox_name,
    checkbox_names,
    checkboxes_named,
    feedback_resistor,
    find,
    known_unit,
    mode_name,
    signal_id,
    signal_name,
    tab_for,
    to_api,
    units_wanted,
)
from ommm.state import state
from ommm.summary import rf

LOG_DIR = Path.home() / "ommm-logs"
MSGTIMEOUT = 6005  # MCCMSG_ERROR_MSGTIMEOUT
MODE_IDS = {name: mode for mode, name in MODES.items()}
PACKET_BYTES = 256  # the telegraph packet ommm decodes, version 7 and later, per MultiClampBroadcastMsg.hpp
RECONNECT_S, RECONNECT_EVERY_S = 30, 2
LOAD = "Load Configuration"  # Commander's name for loading a .mcc file
# after the API answers, before load_config checks: reads 4 s after it showed each file's feedback resistors
LOAD_CONFIG_SETTLE_S = 5
# a start that did not apply the file is followed by one more: Commander started without its file in 4 of 92 loads on
# the rig; the one second start tried skipped it too, and the next load took (docs/quirks.md, Closing and starting
# Commander)
LOAD_CONFIG_STARTS = 2


def load_config_checks(headstage: int) -> dict[str, tuple[str, str, str]]:
    """What a whole file must hold for a headstage, and load_config checks after a load, by its getter: (section, key,
    name)."""
    key, tabs = find("Feedback Resistor").mcc_key, mcc.tab_sections(headstage)
    return {
        "Mode": (mcc.channel(headstage), mcc.MODE_KEY, "the mode"),
        feedback_resistor(VC, headstage): (tabs[VC], key, "Feedback Resistor (V-Clamp)"),
        feedback_resistor(IC, headstage): (tabs[IC], key, "Feedback Resistor (I-Clamp)"),
    }


# I-Clamp External Command Sensitivity at INPUT_GAIN=1, as seen on a 700B
EXT_CMD_FOLLOWS = ("I-Clamp External Command Sensitivity follows the I-Clamp feedback resistor (40 pA/V at 5 GΩ, 400 pA/V "
                   "at 500 MΩ): every DAQ current command scales with it.")
MAX_STEPS = 1000
EXT_ON = ('Mode Switching is on, so the mode follows the MODE input: turn it off first: enable("Mode Switching", on) '
          "with on false")
# never pressed, on Commander or the fake: its confirm dialog may block every later call (a guess: not tried)
RESET = ("Reset to Program Defaults: press it in Commander's window; ommm does not, since its confirm dialog would block "
         "every call until clicked")
# each tab's feedback resistors, by index; I = 0 shares I-Clamp's tab
OFFERED = {VC: FEEDBACK_RESISTORS, IC: {i: ohms for i, ohms in FEEDBACK_RESISTORS.items() if ohms in IC_FEEDBACK_RESISTORS}}
# each headstage's two meters by name, as GetMeterValue's index: the potential (or resistance), then the current
METERS = {1: {"metervalue1": 0, "metervalue2": 1}, 2: {"metervalue3": 2, "metervalue4": 3}}
METER_UNITS = {"voltage": "mV", "current": "pA", "resistance": "MΩ"}  # the first a meter's refusal suggests
# never both on in I-Clamp in Commander's window; the API turns both on
EXCLUSIVE = {"HoldingEnable": "SlowCurrentInjEnable", "SlowCurrentInjEnable": "HoldingEnable"}
SAFE = ("NeutralizationEnable", "RsCompEnable", "TestSignalEnable", "MeterResistEnable")  # what make_safe turns off
# after a button times out, wait its longest documented duration before reading; the others, with none documented,
# the DLL's 3 s once more
TIMED_OUT_WAIT_S = {"Zap": 0.05, "Buzz": 0.5, "Pulse": 0.5}
KILLED = {"RsCompPrediction", "RsCompCorrection", "NeutralizationCap"}  # what the Oscillation Killer lowers
HINTS = {  # why Commander may keep another value than the one sent
    "PipetteOffset": "Commander holds Pipette Offset within ±100 mV of the level the last Auto Pipette Offset found",
    "Holding": "in V-Clamp, Holding plus the level the last Auto Pipette Offset found stays within ±1000 mV",
    "RsCompCorrection": "with the link beside it on, Correction follows Prediction, and the API cannot change the link",
    "PrimarySignalLPF": "the cutoffs depend on the filter type (Options > General), which the API cannot read",
    # values Commander keeps on its own list, which ommm does not have
    "PulseDuration": "Commander keeps one of its steps from 0.1 to 500 ms (right-click the field in Commander to see them)",
    "BuzzDuration": "Commander keeps one of its steps from 50 µs to 500 ms (right-click the field in Commander to see them)",
}
# Auto Pipette Offset changes the other tab too, which the API reads only in that tab's mode: pressed in V-Clamp, the
# I-Clamp offset, and its Slow Current Injection level by a few µV; in I-Clamp, the V-Clamp offset on a model cell,
# V-Clamp's Holding with nothing attached; I = 0 as I-Clamp, whose tab it shares, is a guess: not tried
OTHER_TAB = {
    VC: "it also moved the I-Clamp tab's Pipette Offset, and its Slow Current Injection level by a few µV, which ommm "
        "reads in I-Clamp",
    IC: "it also changes the V-Clamp tab's Pipette Offset, or with nothing attached its Holding, which ommm reads in V-Clamp",
}


@dataclass(frozen=True)
class Write:
    """One write, planned or sent. Values are the API's: SI, with Rs Compensation in percent, gains as plain numbers,
    checkboxes as True or False, the mode and output signals as ids; user_value and unit are as given. `depends` holds
    what the write was checked against, re-read before each step. before, target and after are the value of what
    `stem` names, after as read back; a button has none, and leaves all three None. `steps` holds only what was sent.
    `also` holds every other change, {name: [before, after]}, readings and telegraph fields side by side: for a Set,
    the other readings it changes (a Primary Output signal's own gain and filters, Output Zero with the gain, Cp Slow
    Tau with Tau x20, Correction with Prediction, the mode with Mode Switching); for a button, set_mode and
    load_config, the rest of what a snapshot shows changed. outcome: planned; ok; adjusted (Commander stored it on its
    step, within the row's resolution); mismatch (it read back another value); refused (nothing sent); unknown (sent, and
    Commander did not answer in time, no telegraph came to check it, or an interrupt such as Ctrl+C stopped its checks);
    error (Commander refused the call). t: when the first Set or button was sent; each log line has its own. For
    load_config, `before`, `target` and `after` hold the mode and both feedback resistors, as the API reads them: now,
    in the file, and after the load."""

    label: str
    stem: str | None = None
    mode: str | None = None
    user_value: object = None
    unit: str | None = None
    before: object = None
    target: object = None
    steps: tuple = ()
    depends: dict = field(default_factory=dict)
    after: object = None
    also: dict = field(default_factory=dict)
    outcome: str = "planned"
    reason: str | None = None
    t: str = ""


class WriteError(RuntimeError):
    """A write that was refused or did not take; `write` holds what was read, sent and read back, and why."""

    def __init__(self, write: Write):
        # a refusal is its reason alone; the other outcomes keep the label and outcome, as they follow a send
        super().__init__(write.reason if write.outcome == "refused" else f"{write.label}: {write.outcome}: {write.reason}")
        self.write = write


class Refusal(Exception):
    """Why a write cannot go; it becomes a refused Write and never leaves the Amplifier. `code` is Commander's error
    code when a failed call is why, for the log."""

    def __init__(self, reason: str, code: int | None = None):
        super().__init__(reason)
        self.code = code


def now() -> str:
    return datetime.now().astimezone().isoformat()


def in_unit(row: Setting, mode: str, value: float, unit: str) -> float:
    """An API value in the caller's unit, with the panel's sign, as the shortest decimal Commander's float32 holds."""
    return shortest_float32(value / to_api(row, mode, 1, unit)) + 0.0  # + 0.0 turns the negated sign's -0.0 into 0


def shown(row: Setting, mode: str, value: float, unit: str | None = None) -> str:
    unit = unit or row.unit[mode]
    return f"{in_unit(row, mode, value, unit):g} {unit}"


def no_unit(label: str, unit: str | None):
    if unit is not None:
        raise ValueError(f"{label} takes no unit, not {unit}")


def use_enable(label: str, name: str) -> str:
    """A checkbox given to set or press: the refusal, in words that read right in Python and MATLAB."""
    return f'{label} is a checkbox: turn it on or off with enable("{name}", on)'


def not_in_mode(row: Setting, mode: str) -> str:
    """The refusal for a row the mode lacks; a row that shares its stem with one in the mode names that one (Seal
    Test Amplitude in I-Clamp: Tuning Amplitude)."""
    refusal = f"{row.label} is not in {mode}: Commander has it in {', '.join(row.modes)}"
    try:
        here = find(row.stem, mode)
    except ValueError:  # neither row of the stem is in the mode
        return refusal
    return f"{refusal}; in {mode} it is {here.label}" if here is not row and mode in here.modes else refusal


def how_to_set(row: Setting, mode: str) -> str:
    """The call that changes a value, in words that read right in Python and MATLAB: set with the row's unit, and
    enable where the row has a checkbox in the mode; set_mode for the mode, load_config for the feedback resistor.
    A row the mode lacks gets set's refusal instead."""
    if mode not in row.modes:
        return not_in_mode(row, mode)
    if row.stem == "Mode":
        return 'set_mode("I-Clamp")'
    if row.route == "mcc":
        return "load_config with a .mcc file, which restarts Commander (docs/mcc.md)"
    if row.kind == "enum":
        call = f'set("{row.label}", "Membrane Current")'
    else:
        call = f'set("{row.label}", value, "{row.unit[mode]}")'
    name = checkbox_name(row, mode)
    return f'{call}, or enable("{name}", on)' if name else call


def no_checkbox(name: str, mode: str) -> str:
    """enable()'s refusal for a name with no checkbox in the mode, checked in this order: another mode's checkbox, a
    button, a value, else find's did-you-mean. Where it names no call to make, it lists the names enable takes."""
    offered = f"; in {mode}, enable takes {', '.join(checkbox_names(mode))}"
    if elsewhere := checkboxes_named(name):
        label = elsewhere[0][0] if len(elsewhere) == 1 else name
        modes = " and ".join(checkbox_modes(name))
        here = next((other for other, stem, other_modes in CHECKBOXES if stem == elsewhere[0][1] and mode in other_modes), None)
        if here:
            return f"{label} is a checkbox in {modes}; in {mode} it is {here}"
        return f"{label} is a checkbox in {modes}, not in {mode}" + offered
    try:
        row = find(name, mode)
    except ValueError as error:
        return f"{error}{offered}"
    if mode not in row.modes:
        return not_in_mode(row, mode)
    if row.kind == "action":
        return f'{row.label} is a button: press("{row.label}")'
    return f"{row.label} is a value: {how_to_set(row, mode)}"


def checkbox_refusal(name: str, mode: str) -> str:
    """set's and press's refusal for a checkbox's name: enable with its name in the mode, or enable's own refusal
    where the mode has no such checkbox."""
    if mode not in checkbox_modes(name):
        return no_checkbox(name, mode)
    label = checkbox(name, mode)[0]
    return use_enable(label, label)


def unwritable(folder: Path) -> str | None:
    """Why the log could not be written in `folder`, None if it could; leaves nothing behind, as the first line makes
    the folder."""
    existing = next((path for path in (folder, *folder.parents) if path.exists()), None)
    if existing is None:  # an unmapped drive or an offline share
        return f"{folder.anchor or folder} does not exist"
    if not existing.is_dir():
        return f"{existing} is a file"
    # what the first line makes there, a file in the folder or the folder, made and removed: on Windows os.access says
    # every folder is writable whatever its permissions, and C:\ lets an account make a folder but not a file
    probe = existing / f".ommm-probe-{os.urandom(4).hex()}"
    try:
        if existing == folder:
            probe.touch(exist_ok=False)
            probe.unlink()
        else:
            probe.mkdir()
            probe.rmdir()
    except OSError:
        return f"{existing} is not writable"
    return None


def a_number(value) -> bool:
    """A finite real number, not True or False: what a value, step= and expect= must be."""
    return isinstance(value, numbers.Real) and not isinstance(value, bool) and math.isfinite(value)


def merged(also: dict, more: dict) -> dict:
    """Two `also`s as one, each reading from its first value before to its last after; unchanged ones dropped."""
    joined = also | {stem: [also.get(stem, change)[0], change[1]] for stem, change in more.items()}
    return {stem: change for stem, change in joined.items() if change[0] != change[1]}


def flat(diff: dict, drop=()) -> dict:
    """A snapshot diff's readings and telegraph as one `also`, {name: [before, after]}, leaving out the names in `drop`."""
    return {name: change for section in diff.values() for name, change in section.items() if name not in drop}


def loaded(target: dict, before: dict, after: dict) -> dict:
    """A load's after, the mode and feedback resistors read back (None for one the snapshot could not read), and its
    also, every other change."""
    return {"after": {stem: after["readings"].get(stem) for stem in target}, "also": flat(snapshot_changes(before, after), drop=target)}


def not_offered(tab: str, value: str) -> str:
    return f"Feedback Resistor in {tab} is one of {', '.join(map(rf, OFFERED[tab].values()))}, not {value}"


def slug(text: str) -> str:
    """Words and numbers of a label or a shown value, lower case, joined by -: "Feedback Resistor" → feedback-resistor,
    "500 MΩ" → 500-mohm; for a file name."""
    return "-".join(re.findall(r"[a-z0-9]+", text.lower().replace("ω", "ohm")))


def shown_loaded(stem: str, value) -> str:
    """A value load_config checks, as Commander shows it: the mode by name, a feedback resistor in Ω."""
    return MODES.get(value, str(value)) if stem == "Mode" else rf(FEEDBACK_RESISTORS.get(value))


def described(stem: str, value, mode: str, headstage: int, unit: str | None = None) -> tuple[str, str]:
    """A reading a write was checked against, in Commander's words: (its name, its value), the mode by name, a
    checkbox on or off, an output signal by name, a value in `unit` or the row's."""
    checks = load_config_checks(headstage)
    if stem in checks:
        return checks[stem][2], shown_loaded(stem, value)
    if isinstance(value, bool):
        return checkbox_label(stem, mode) or stem, "on" if value else "off"
    row = find(stem, mode)
    if row.kind == "enum":
        return row.label, signal_name(row, value)
    if row.kind == "float" and mode in row.unit and isinstance(value, float):
        return row.label, shown(row, mode, value, unit)
    return row.label, repr(value)


def holding_left_on(before: dict, after: dict) -> str | None:
    """What to say, in Commander's words, when Holding was on before a restart and Commander shows it off after, in
    V-Clamp or I-Clamp (I = 0 applies no Holding). Restarted with no file and nothing written since, Commander comes back
    with Holding off at its level while the amplifier keeps holding the command; after load_config, which starts it with
    a file and selects the output signals again, Commander comes back with Holding off at the file's level, 0 mV, and
    the amplifier follows it. Turning Holding on again is the caller's call, not ommm's."""
    was, now = before["readings"], after["readings"]
    if not (was.get("HoldingEnable") and now.get("HoldingEnable") is False and now.get("Mode") == was.get("Mode")):
        return None
    mode = MODES[was["Mode"]]
    row = find("Holding", mode)
    if mode not in row.modes:
        return None
    held, shows = shown(row, mode, was["Holding"]), shown(row, mode, now["Holding"])
    if shows == held:
        return f"Holding was on at {held} before the restart; Commander now shows it off: turn it on again"
    return (f"Holding was on at {held} before the restart; Commander came back with it off at {shows}: set Holding to "
            f"{held}, then turn it on")


def compare(value, after, resolution: float) -> str:
    """A readback's outcome: ok, adjusted (within the row's resolution) or mismatch."""
    if after == value or (isinstance(value, float) and after == shortest_float32(value)):
        return "ok"
    if isinstance(value, float) and isinstance(after, float) and abs(after - value) <= resolution:
        return "adjusted"
    return "mismatch"


def unapplied(target: dict, held: dict, after: dict, headstage: int) -> list[str]:
    """What Commander shows after a start that is not as the file holds it, in Commander's words: the mode and both
    feedback resistors (load_config's target), then the values mcc.READ_BACK names on the tab the active mode shows
    (`held`: mcc.values of the file; `after`: a snapshot)."""
    readings, checks = after["readings"], load_config_checks(headstage)
    found = [f"{checks[stem][2]}: the file sets {shown_loaded(stem, value)}, Commander has {shown_loaded(stem, readings.get(stem))}"
             for stem, value in target.items() if readings.get(stem) != value]
    if readings.get("Mode") not in MODES:
        return found
    tab = tab_for(MODES[readings["Mode"]])
    section = mcc.tab_sections(headstage)[tab]
    for stem, key in mcc.READ_BACK[tab].items():
        if (section, key) not in held or stem not in readings:
            continue
        value, seen = mcc.parsed(held[(section, key)]), readings[stem]
        if isinstance(value, bool):
            if seen != value:
                found.append(f"{checkbox_label(stem, tab)} ({tab}): the file sets it {'on' if value else 'off'}, Commander "
                             f"has it {'on' if seen else 'off'}")
        elif compare(value, seen, (row := find(stem, tab)).resolution.get(tab, 0.0)) == "mismatch":
            found.append(f"{row.label} ({tab}): the file sets {shown(row, tab, value)}, Commander has {shown(row, tab, seen)}")
    return found


class Amplifier:
    """One headstage of the one MultiClamp 700B Commander runs, 1 or 2 (found and selected at connect), read and set
    through Commander as its own controls are. Every write goes to an append-only log, `<log_dir>/<serial>.jsonl` for
    headstage 1 and `<serial>_headstage2.jsonl` for headstage 2, a relative log_dir taken from the working folder when
    the Amplifier is made. Without a log_dir, the log goes to OMMM_LOG_DIR, an absolute folder, or else ~/ommm-logs; on
    a fake, to a new temporary folder, made by its first line. `fake` serves a saved snapshot instead of Commander
    (ommm's fake, ommm.testing.FakeCommander), `other_tab` the snapshot of its other tab; amp.fake keeps that snapshot,
    its file made absolute, as MATLAB's a.fake, and is None without fake=, as on Commander. `commander` is for what
    fake= cannot say: a FakeCommander made with other_headstage=, another handle on one (fake.handle(2)) or a handle
    already open; its headstage must be the Amplifier's. A log folder ommm could not make or write to is refused here,
    before any write reaches the amplifier without its log line."""

    def __init__(self, headstage: int = 1, *, log_dir: str | Path | None = None, fake: str | Path | dict | None = None,
                 other_tab: str | Path | dict | None = None, commander: Commander | None = None):
        if fake is not None and commander is not None:
            raise ValueError("give fake= (a snapshot) or commander=, not both")
        if other_tab is not None and fake is None:
            raise ValueError("other_tab= is the fake's other tab: give fake= too")
        if fake is not None:
            commander = ommm.testing.FakeCommander(fake, other_tab, headstage=headstage)
        elif commander is None:
            commander = Commander(headstage=headstage)
        elif headstage != commander.channel:
            raise ValueError(f"the commander given is on headstage {commander.channel}, not {headstage!r}: pass "
                             f"headstage={commander.channel}")
        self.commander = commander
        self.fake = Path(fake).resolve() if isinstance(fake, str | Path) else fake
        on_fake = isinstance(commander.dll, ommm.testing.fake.FakeDLL)
        # what closes and starts Commander: the fake's FakeProcess, or Commander's program through Windows
        self.process = commander.dll.process if on_fake else PROCESS
        # _log_dir_from: what chose the folder, as a refusal of it names it, so its remedy is one that works there
        if log_dir:
            log_dir, self._log_dir_from = Path(log_dir).expanduser(), "log_dir"
        elif on_fake:  # never a real amplifier's log, nor OMMM_LOG_DIR: its snapshot may be your rig's
            log_dir = Path(tempfile.gettempdir()) / f"ommm-fake-{os.urandom(4).hex()}"
            self._log_dir_from = "the fake's log folder"
        else:
            named = os.environ.get("OMMM_LOG_DIR")
            log_dir = Path(named or LOG_DIR).expanduser()
            self._log_dir_from = "OMMM_LOG_DIR" if named else "the default log folder"
            if not log_dir.is_absolute():  # one log for every program, whatever its working folder
                raise ValueError(f"OMMM_LOG_DIR must be an absolute folder, such as C:\\ommm-logs, not {log_dir}: each "
                                 "program would take it from its own working folder")
        # one log, wherever a later chdir (MATLAB's cd) goes, and the same path when MATLAB passes it back on a reconnect
        self.log_dir = log_dir.resolve()
        if reason := unwritable(self.log_dir):
            remedy = {  # another log_dir would split the log every program shares through OMMM_LOG_DIR
                "OMMM_LOG_DIR": "make it writable for this account, or set OMMM_LOG_DIR to a folder every program's "
                                "account can write to",
                "the default log folder": "set OMMM_LOG_DIR to a folder ommm can write to, or give log_dir (LogDir= in "
                                          "MATLAB) one",
            }.get(self._log_dir_from, "give log_dir (LogDir= in MATLAB) a folder ommm can write to")
            raise ValueError(f"{self._log_dir_from} {self.log_dir} cannot hold the write log ({reason}): {remedy}")
        if on_fake:  # a FakeProcess made after this one would go unused: it refuses
            self.process.held = True

    @property
    def headstage(self) -> int:
        """1 or 2; the full record (model, serial, ...) is snapshot()["headstage"]."""
        return self.commander.channel

    @property
    def serial(self) -> str:
        return self.commander.headstage.serial

    @property
    def gui(self):
        """On the fake, the person at this headstage's panel in Commander's window (FakeCommander.gui_for): show_tab,
        mode, set, enable. It works whichever Commander is running, as the window does, through load_config and
        reconnect()."""
        if not isinstance(self.process, ommm.testing.FakeProcess):
            raise AttributeError("only an Amplifier on the fake (fake=FILE) has a gui: on Commander, use its window")
        return self.process.fake.gui_for(self.headstage)

    @property
    def log_path(self) -> Path:
        name = f"{self.serial}.jsonl" if self.headstage == 1 else f"{self.serial}_headstage{self.headstage}.jsonl"
        return self.log_dir / name

    # reads

    def get(self, label: str, unit: str | None = None):
        """One control by Commander's label, in the unit given: get("Holding", "mV") is -60.0 in V-Clamp, where
        get("Holding", "pA") is refused. The mode comes as its name ("V-Clamp"), an output signal as Commander's name
        for it ("Membrane Current"), and a checkbox as True or False, by the name enable takes (get("Seal Test")) or its
        API name; a label is matched first, so "Holding" is the value. The meters: MeterValue1, the potential, or the
        resistance while the Resistance meter is on; MeterValue2, the current, which raises NotApplicable in V-Clamp
        while Irms Meter is on, since the meter then shows the RMS current noise; on headstage 2, MeterValue3 and 4.
        Reads the active mode's tab, which it brings to the front first."""
        c = self.commander
        c.show_active_tab()
        mode = MODES[c.get("Mode")]
        meters = METERS[self.headstage]
        if label.lower() in meters:
            return self._meter(meters[label.lower()], unit, mode)
        if other := next((n for n in HEADSTAGES if label.lower() in METERS[n]), None):
            potential, current = (f"MeterValue{index + 1}" for index in meters.values())
            raise ValueError(f"{label} is headstage {other}'s meter; headstage {self.headstage}'s are {potential}, the "
                             f"potential, and {current}, the current")
        try:
            row = find(label, mode)
        except ValueError:
            modes = checkbox_modes(label)
            if not modes:
                raise
            if mode not in modes:
                raise NotApplicable("get", None, f"{label} is not in {mode}: Commander has it in {', '.join(modes)}") from None
            no_unit(label, unit)
            return c.get(checkbox(label, mode)[1])
        if row.kind == "action":
            raise ValueError(f'{row.label} is a button, with nothing to read: press("{row.label}")')
        if row.route == "mcc":
            index = c.get(feedback_resistor(mode, self.headstage))
            return in_unit(row, mode, FEEDBACK_RESISTORS[index], unit)
        if mode not in row.modes:
            raise NotApplicable("get", None, not_in_mode(row, mode))
        value = c.get(row.stem)
        if row.kind == "float":
            try:
                return in_unit(row, mode, value, unit)
            except ValueError as error:
                if unit is None and checkbox_name(row, mode) == row.label:  # Holding: the value; its checkbox by its API name
                    raise ValueError(f'{error}; its checkbox is get("{row.enable}")') from None
                raise
        no_unit(row.label, unit)
        if row.stem == "Mode":
            return MODES[value]
        return signal_name(row, value) if row.kind == "enum" else value

    def _meter(self, index: int, unit: str | None, mode: str) -> float:
        """A meter's reading, whose meaning changes about 0.5 s after the Resistance or Irms checkbox does: a read just
        after either goes off can still give what the meter showed with it on."""
        if index % 2 == 0:  # the potential's
            try:
                shows = "resistance" if self.commander.get("MeterResistEnable") else "voltage"
            except NotApplicable:
                shows = "voltage"
        else:
            shows = "current"
            try:
                irms = mode == VC and self.commander.get("MeterIrmsEnable")  # Irms is V-Clamp's alone
            except NotApplicable:
                irms = False
            if irms:
                raise NotApplicable("get", None, f"MeterValue{index + 1} shows the RMS current noise, not the current, "
                                    'while Irms Meter is on: turn it off, enable("Irms Meter", on) with on false, and '
                                    "read about 0.5 s later")
        found = known_unit(unit)
        if found is None or found[0] != shows:
            raise ValueError(f"MeterValue{index + 1} shows {shows} now: {units_wanted(shows, METER_UNITS[shows], unit)}")
        return shortest_float32(self.commander.get("MeterValue", index) / found[1])

    def snapshot(self) -> dict:
        """Every reading, SI, with one telegraph packet and ommm's provenance (Commander.snapshot), from the active
        mode's tab, which it brings to the front first."""
        return self.commander.snapshot()

    def writes_since(self, mark: int = 0) -> tuple[list[dict], int]:
        """The log's lines from every process after byte offset `mark`, and the next mark: ommm.log.writes_since."""
        return log.writes_since(self.log_path, mark)

    # writes

    def plan(self, label: str, value, unit: str | None = None, *, step=None, expect=None) -> Write:
        """What set() with these arguments would do, from fresh reads: a Write whose outcome is planned, its reason the
        question in the caller's unit ("Holding 0 mV → -40 mV (V-Clamp)"), or refused, with why. Sends nothing and logs
        nothing; set() keeps the same reason, so its Write and log line show the change."""
        return self._plan(label, value, unit, step, expect)[0]

    def _plan(self, label: str, value, unit: str | None, step, expect) -> tuple[Write, int | None]:
        """plan()'s Write, and the error code of the failed call that refused it, for set()'s log line."""
        fields = {"label": label, "user_value": value, "unit": unit}
        try:
            self._check_set(fields, step, expect)
        except Refusal as refusal:
            return Write(**fields | {"outcome": "refused", "reason": str(refusal)}, t=now()), refusal.code
        return Write(**fields, t=now()), None

    def set(self, label: str, value, unit: str | None = None, *, step=None, expect=None) -> Write:
        """Set a value by Commander's label, in a unit that suits the active mode: set("Holding", -60, "mV"); an output
        signal by Commander's name for it: set("Primary Output", "Membrane Current"). Checks it first (plan), sends it
        in one go as Commander does when you type it, reads it back and logs it.

        step=5 moves a value in steps of 5 in the call's unit, each re-checked, sent and read back, stopping at the
        first that does not take. expect=-50 refuses unless Commander still shows -50 in the call's unit, the value a
        dialog showed. Every number takes a unit (a gain's is x), so a step or expect is never without one; an output
        signal takes no step, and its expect is a signal's name. Returns the Write, ok or adjusted; raises WriteError
        for any other outcome, logged too."""
        write, code = self._plan(label, value, unit, step, expect)
        if write.outcome == "refused":
            raise self._failed(write, code)
        self._refresh_if_stale()
        row = find(write.label, write.mode)
        last, adjusted, also, t = write.before, False, {}, None
        for i, target in enumerate(write.steps):
            step = replace(write, before=last)
            if i and (changed := self._changed_since(write, last)):  # after the earlier steps were sent
                sent = self._logged(replace(step, target=target, outcome="refused", reason=str(changed), t=now()), changed.code)
            else:
                sent = self._send(step, target, row.resolution.get(write.mode, 0.0), row.stem in CHECKED)
                also = merged(also, sent.also)
            t = t or sent.t  # the first step's, as logged
            if sent.outcome not in ("ok", "adjusted"):
                if i:
                    confirmed = shown(row, write.mode, last, write.unit)
                    where = f"step {i + 1} of {len(write.steps)}; the last confirmed {confirmed}"
                    sent = replace(sent, reason=f"{sent.reason} ({where})")
                raise WriteError(replace(sent, before=write.before, also=also, t=t))
            last, adjusted = sent.after, adjusted or sent.outcome == "adjusted"
        return replace(write, after=last, also=also, outcome="adjusted" if adjusted else "ok", t=t)

    def enable(self, name: str, on: bool) -> Write:
        """Turn a checkbox on or off by its name on Commander's window (docs/coming-from-commander.md): enable("Seal
        Test", True), enable("Holding", False), enable("Mode Switching", False). Turning a checkbox on checks every
        value it applies against its range first (Holding, Seal Test, Neutralization and Rs Compensation apply theirs
        at once); Holding and Slow Current Injection are never both on in I-Clamp; Whole Cell needs a feedback resistor
        of 50 or 500 MΩ. Mode Switching is read first and sent only to change it, since each Set flips it. Raises
        WriteError unless it took."""
        fields = {"label": name, "user_value": on}
        try:
            depends = self._preflight(ext_ok=True)
            mode = fields["mode"] = MODES[depends["Mode"]]
            try:
                label, stem = checkbox(name, mode)
            except ValueError:
                raise Refusal(no_checkbox(name, mode)) from None
            fields |= {"label": label, "stem": stem, "depends": depends}
            if not isinstance(on, bool):
                raise Refusal(f"{label} is on or off: True or False, not {on!r}")
            fields["target"] = on
            if depends["ModeSwitchEnable"] and not (stem == "ModeSwitchEnable" and not on):
                raise Refusal(EXT_ON)
            if stem not in depends:
                depends[stem] = self._read(stem)
            fields["before"] = depends[stem]
            if on:
                self._check_turning_on(label, stem, mode, depends)
        except Refusal as refusal:
            raise self._failed(Write(**fields | {"outcome": "refused", "reason": str(refusal)}, t=now()), refusal.code) from None
        write = Write(**fields, steps=(on,), t=now())
        if stem == "ModeSwitchEnable" and write.before == on:
            return replace(write, steps=(), after=on, outcome="ok", reason="already so: nothing sent, since each Set flips it")
        self._refresh_if_stale()
        sent = self._send(write, on)
        if sent.outcome != "ok":
            raise WriteError(sent)
        return sent

    def press(self, name: str) -> Write:
        """Press one of Commander's buttons by its name: press("Zap"), press("Auto Bridge Balance"). Its parameters are
        settings, set first: set("Zap Duration", 0.5, "ms"). The Write's `also` is what a snapshot shows changed,
        the button's result; Auto Pipette Offset also changes the other tab, seen when that mode is read.
        Raises WriteError unless Commander took it; after a timeout it waits the button's longest duration, then
        reads, and never presses again. An interrupt from the press on (Ctrl+C) is logged first, unknown, then raised."""
        fields = {"label": name}
        try:
            depends = self._preflight()
            mode = fields["mode"] = MODES[depends["Mode"]]
            row = self._row(name, mode)
            fields |= {"label": row.label, "stem": row.stem, "depends": depends}
            if row.kind == "bool":
                raise Refusal(checkbox_refusal(row.label, mode))
            if mode not in row.modes:
                raise Refusal(not_in_mode(row, mode))
            if row.kind != "action":
                raise Refusal(f"{row.label} is a value, not a button: {how_to_set(row, mode)}")
            if row.stem == "Reset":
                raise Refusal(RESET)
            if row.stem == "AutoWholeCellComp":
                self._check_whole_cell(depends)
        except Refusal as refusal:
            raise self._failed(Write(**fields | {"outcome": "refused", "reason": str(refusal)}, t=now()), refusal.code) from None
        self._refresh_if_stale()
        try:
            before, t = self.commander.snapshot(), now()
        except CommanderError as error:
            raise self._failed(Write(**fields | {"outcome": "refused", "reason": f"no snapshot before it: {error}"}, t=now()),
                               error.code) from None
        outcome, reason, code, also = "ok", None, None, {}
        try:
            try:
                self.commander._call(row.stem)
            except CommanderError as error:
                code = error.code
                if code == MSGTIMEOUT:
                    outcome, reason = "unknown", "Commander did not answer in time, so it may or may not have run; not pressed again"
                    time.sleep(TIMED_OUT_WAIT_S.get(row.label, 3.0))
                else:
                    outcome, reason = "error", str(error)
            try:
                also = flat(snapshot_changes(before, self.commander.snapshot()))
            except CommanderError as error:
                if outcome == "ok":
                    outcome, reason, code = "unknown", f"pressed, but the snapshot after it failed: {error}", error.code
        except BaseException as error:  # Ctrl+C once the button may have run: its line first, and never pressed again
            stopped = f"interrupted ({type(error).__name__}) before the snapshot after it"
            reason = f"{reason}; {stopped}" if reason else f"pressed, then {stopped}, so what it did is not known; not pressed again"
            self._logged(Write(**fields, outcome="error" if outcome == "error" else "unknown", reason=reason, t=t), code)
            raise
        if outcome == "ok" and row.stem == "AutoPipetteOffset":
            reason = OTHER_TAB[tab_for(mode)]
        write = self._logged(Write(**fields, also=also, outcome=outcome, reason=reason, t=t), code)
        if outcome != "ok":
            raise WriteError(write)
        return write

    def set_mode(self, mode: str) -> Write:
        """Change the mode as Commander's buttons do: between V-Clamp and I-Clamp always through I = 0, each SetMode
        read back from the API and the telegraph as soon as it returns, which shows the new mode at once, and logged.
        Then refreshes the new mode's output signals in the telegraph if they are stale.
        Returns one Write: `after` is the mode id read back last, `steps` the SetModes sent, and `also` what else a
        snapshot shows changed, the new mode's tab included; nothing is sent when already there. Raises WriteError at the first SetMode that does not take, which may
        leave I = 0. The new mode's Holding is the caller's to set."""
        fields = {"label": "Mode", "stem": "Mode", "user_value": mode}
        try:
            try:
                target = mode_name(mode)
            except ValueError as error:
                raise Refusal(str(error)) from None
            depends = self._preflight()
        except Refusal as refusal:
            raise self._failed(Write(**fields | {"outcome": "refused", "reason": str(refusal)}, t=now()), refusal.code) from None
        current = MODES[depends["Mode"]]
        path = [I0, target] if {current, target} == {VC, IC} else [target] if target != current else []
        fields |= {"mode": current, "before": depends["Mode"], "target": MODE_IDS[target],
                   "steps": tuple(MODE_IDS[m] for m in path), "depends": depends}
        if not path:
            return Write(**fields, after=depends["Mode"], outcome="ok", reason=f"already in {target}: nothing sent", t=now())
        try:
            before = self.commander.snapshot()
        except CommanderError as error:
            raise self._failed(Write(**fields | {"outcome": "refused", "reason": f"no snapshot before it: {error}"}, t=now()),
                               error.code) from None
        last, t = depends["Mode"], None
        for i, step in enumerate(path):
            write = Write(**fields | {"mode": MODES[last], "before": last}, t=now())
            if i and (changed := self._changed_since(write, last)):
                raise self._failed(replace(write, target=MODE_IDS[step], outcome="refused", reason=str(changed)), changed.code)
            sent = self._send(write, MODE_IDS[step], telegraph=True)
            if sent.outcome != "ok":
                raise WriteError(sent)
            last, t = sent.after, t or sent.t  # the first SetMode's t, as logged
        self._refresh_if_stale()
        try:
            also = flat(snapshot_changes(before, self.commander.snapshot()), drop={"Mode"})
        except CommanderError as error:  # the mode was read back; only the report of the rest is missing
            return Write(**fields, after=last, outcome="ok", reason=f"in {target}, but the snapshot after it failed: {error}", t=t)
        return Write(**fields, after=last, also=also, outcome="ok", t=t)

    def make_safe(self) -> list[Write]:
        """Turn off, where the active mode has them, Pipette Capacitance Neutralization, Rs Compensation, Seal Test
        (Tuning in I-Clamp) and the Resistance meter; each is read first and sent only if on. It turns nothing on,
        steps no Holding and needs no telegraph; Mode Switching must be off. Returns the writes it sent."""
        try:
            depends = self._preflight(telegraph=False)
        except Refusal as refusal:
            raise self._failed(Write(label="make_safe", outcome="refused", reason=str(refusal), t=now()), refusal.code) from None
        mode, writes = MODES[depends["Mode"]], []
        for stem in SAFE:
            row = next((row for row in SETTINGS if stem in (row.enable, row.stem) and mode in row.modes), None)
            if row is None:
                continue
            write = Write(label=checkbox_name(row, mode), stem=stem, mode=mode, user_value=False, target=False,
                          steps=(False,), depends=depends, t=now())
            done = f" (after turning off {', '.join(sent.label for sent in writes)})" if writes else ""
            try:
                before = self._read(stem)
            except Refusal as refusal:
                raise self._failed(replace(write, outcome="refused", reason=f"{refusal}{done}"), refusal.code) from None
            if not before:
                continue
            sent = self._send(replace(write, before=before), False)
            if sent.outcome != "ok":
                raise WriteError(replace(sent, reason=f"{sent.reason}{done}"))
            writes.append(sent)
        return writes

    def load_config(self, path, *, changes=(), confirmed=False, release_other_headstage=False) -> Write:
        """Close Commander and start it again with a .mcc settings file: the route to what the API cannot set, such
        as the feedback resistor (docs/mcc.md). `path` is a whole file Commander saved (Save Configuration, F5);
        `changes` patch Options-page settings in a copy of it, one line each, as (label, value, unit, mode):
        [("Feedback Resistor", 500, "MΩ", "V-Clamp")]. The file sets every value it holds, the mode, Holding,
        compensation, the output signals and the Options pages included: set what the API reaches after, with set()
        and enable().

        Without confirmed=True it returns the plan, a Write whose `reason` says what will change, and
        sends, writes and logs nothing. With it, Commander is gone for about 15 s and every handle on it dies: this
        Amplifier takes the new one, and other programs, MATLAB included, call reconnect(). Commander sometimes starts
        without applying the file: when the mode, a feedback resistor or another value the file sets (mcc.READ_BACK)
        is not as the file holds it, ommm logs that start as a mismatch, closes Commander and starts it with the file
        once more, about 15 s longer. Returns the Write: `after` the mode and feedback resistors read back, `also` what
        else a snapshot shows changed; raises WriteError when
        refused, when Commander does not close, start or answer, or when those values or the telegraph still disagree
        with the file after the last start. With Holding on,
        the plan says Commander comes back with it off; when Holding was on before and Commander shows it off after, the
        load's reason says so and how to hold the old level again. ommm never turns Holding on by itself.

        The restart reaches both headstages, and the file holds settings for each: the plan says what the other headstage
        is doing, and refuses while it holds a level unless release_other_headstage=True. Both flags are True or False,
        nothing else. The file must hold
        this headstage's settings."""
        fields = {"label": LOAD, "user_value": str(path)}
        try:
            for name, flag in {"confirmed": confirmed, "release_other_headstage": release_other_headstage}.items():
                if not isinstance(flag, bool):
                    raise Refusal(f"{name} is True or False, not {flag!r}")
            plan, text, copy = self._plan_load_config(fields, Path(path), changes, release_other_headstage)
        except Refusal as refusal:
            write = Write(**fields | {"outcome": "refused", "reason": str(refusal)}, t=now())
            if confirmed is not False:  # a confirmed=1 meant to load: it fails as loudly as confirmed=True
                raise self._failed(write, refusal.code) from None
            return write
        return self._load_config(plan, text, copy) if confirmed else plan

    def reconnect(self):
        """A new handle after Commander was closed or restarted, when the old one fails with 6002: waits for
        Commander's window, then takes a new handle, as load_config does, and closes the old one, trying every 2 s for
        up to 30 s. Reads only. After a restart Commander may show Holding off while the amplifier still holds the last
        command (docs/quirks.md): if Holding was on, turn it on, enable("Holding", True), as your first write after
        reconnect(). Any other write, set included, may make the amplifier follow the unchecked box, and the output-signal
        re-select ommm sends before the first write after a start has not been measured for this."""
        deadline = time.monotonic() + RECONNECT_S
        while True:
            try:
                if self.commander.dll.commander_pid() is None:
                    raise CommanderError("reconnect", None, "Commander is not running in this desktop session")
                commander = self.process.connect(self.headstage)
                self.commander.close()
                self.commander = commander
                return
            except CommanderError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(RECONNECT_EVERY_S)

    def close(self):
        self.commander.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # the checks

    def _preflight(self, ext_ok: bool = False, telegraph: bool = True) -> dict:
        """What every write starts with, from fresh reads: Commander's window, the active mode's tab brought to the
        front, the mode, Mode Switching off, and the telegraph agreeing on the mode. The readings, or Refusal."""
        if self.commander.dll.commander_pid() is None:
            raise Refusal("Commander is not running in this desktop session: start it, then reconnect()")
        try:
            self.commander.show_active_tab()
        except CommanderError as error:
            raise Refusal(str(error), error.code) from None
        depends = {"Mode": self._read("Mode"), "ModeSwitchEnable": self._read("ModeSwitchEnable")}
        if depends["ModeSwitchEnable"] and not ext_ok:
            raise Refusal(EXT_ON)
        if telegraph and (told := self._packet()["uOperatingMode"]) != depends["Mode"]:
            raise Refusal(f"Commander's API says {MODES[depends['Mode']]} and its telegraph {MODES.get(told, told)}: try again")
        return depends

    def _check_set(self, fields: dict, step, expect):
        """plan()'s checks; fills `fields` in as it reads, and raises Refusal at the first that fails."""
        depends = self._preflight()
        mode = fields["mode"] = MODES[depends["Mode"]]
        row = self._row(fields["label"], mode)
        fields |= {"label": row.label, "stem": row.stem, "depends": depends}
        if row.kind == "bool":
            raise Refusal(checkbox_refusal(row.label, mode))
        if mode not in row.modes:
            raise Refusal(not_in_mode(row, mode))
        if row.kind == "action":
            raise Refusal(f'{row.label} is a button: press("{row.label}")')
        if row.stem == "Mode":
            raise Refusal('the mode changes with set_mode("I-Clamp"), which goes through I = 0')
        if row.route == "mcc":
            value = fields["user_value"]
            change = ", ".join(map(str, (row.label, f"{value:g}" if a_number(value) else value, fields["unit"], mode)))
            raise Refusal(f"{row.label} changes only by restarting Commander with a .mcc file: load_config with the file "
                          f"and the change ({change}) shows what will change; confirmed, it makes it (docs/mcc.md)")
        if row.enable == "WholeCellCompEnable":
            self._check_whole_cell(depends)
        before = fields["before"] = depends[row.stem] = self._read(row.stem)
        if row.kind == "enum":
            if fields["unit"] is not None or step is not None:
                raise Refusal(f'{row.label} takes a signal by its name alone: set("{row.label}", "Membrane Current")')
            if expect is not None and not isinstance(expect, str):
                raise Refusal(f'the expected value of {row.label} is a signal\'s name, such as "Membrane Current"')
            target = self._signal(row, mode, fields["user_value"])
            if expect is not None and self._signal(row, mode, expect) != before:
                raise Refusal(f"Commander no longer shows {expect}: it shows {signal_name(row, before)}")
            fields |= {"target": target, "steps": (target,),
                       "reason": f"{row.label} {signal_name(row, before)} → {signal_name(row, target)} ({mode})"}
            return
        for name, given in (("the step", step), ("the expected value", expect)):
            if given is not None and not a_number(given):
                raise Refusal(f"{name} is a number in the call's unit, not {given!r}")
        unit = fields["unit"]
        target = fields["target"] = self._checked(row, mode, fields["user_value"], unit, depends)
        if expect is not None:
            seen = self._api(row, mode, expect, unit, prefix="the expected value: ")
            if abs(seen - before) > row.resolution.get(mode, 0.0) + 1e-6 * abs(seen):
                raise Refusal(f"Commander no longer shows {expect:g} {unit} for {row.label}: it shows {shown(row, mode, before, unit)}")
        fields["steps"] = self._steps(row, mode, before, target, step, unit)
        fields["reason"] = f"{row.label} {shown(row, mode, before, unit)} → {shown(row, mode, target, unit)} ({mode})"
        # stored while its checkbox is off, applied once it is on: seen for Holding, documented for Seal Test,
        # Neutralization and Rs Compensation, a guess for the rest
        if row.enable:
            depends[row.enable] = self._read(row.enable)
            if not depends[row.enable]:
                fields["reason"] += f"; {checkbox_name(row, mode)} is off: the value applies once it is on"

    def _checked(self, row: Setting, mode: str, value, unit: str | None, depends: dict) -> float:
        """The API value for the caller's: a number, in a unit of the row's kind, one of Commander's values where it
        offers a list (never snapped), within the vendor's range."""
        if not a_number(value):
            raise Refusal(f"{row.label} takes a number, not {value!r}")
        target = self._api(row, mode, value, unit)
        if row.choices:
            match = [choice for choice in row.choices if math.isclose(choice, target, rel_tol=1e-6)]
            if not match:
                below = [shown(row, mode, choice, unit) for choice in sorted(row.choices) if choice < target]
                above = [shown(row, mode, choice, unit) for choice in sorted(row.choices) if choice > target]
                if below and above:
                    hint = f"the values either side: {below[-1]} and {above[0]}"
                else:
                    hint = f"the smallest: {above[0]}" if above else f"the largest: {below[-1]}"
                raise Refusal(f"{row.label} is one of Commander's values, not {value:g} {unit}; {hint}")
            return match[0]
        low, high = self._limits(row, mode, depends)
        if not low - 1e-9 * abs(low) <= target <= high + 1e-9 * abs(high):
            raise Refusal(f"{row.label} in {mode} is {shown(row, mode, low, unit)} to {shown(row, mode, high, unit)}, so not {value:g} {unit}")
        return shortest_float32(target)  # Commander keeps float32: the same value, without the unit's tail

    def _limits(self, row: Setting, mode: str, depends: dict) -> tuple[float, float]:
        """The vendor's range in the mode, SI: in I-Clamp ± rf_limit_v over the feedback resistor, in V-Clamp the
        row's range at the feedback resistor where it has one, Cp Slow Tau's by Tau x20 and Output Zero's by the
        Primary Output gain. Adds what it read to depends."""
        low, high = row.limits.get(mode, (-math.inf, math.inf))
        if row.rf_limit_v and mode == IC:
            stem = feedback_resistor(IC, self.headstage)
            depends[stem] = index = self._read(stem)
            bound = row.rf_limit_v / FEEDBACK_RESISTORS[index]
            low, high = max(low, -bound), min(high, bound)
        if row.rf_limits and mode == VC:
            stem = feedback_resistor(VC, self.headstage)
            depends[stem] = index = self._read(stem)
            low, high = row.rf_limits.get(FEEDBACK_RESISTORS[index], (low, high))
        if row.stem == "SlowCompTau":
            depends["SlowCompTauX20Enable"] = x20 = self._read("SlowCompTauX20Enable")
            low, high = TAU_X20_RANGES[x20]
        if row.stem == "OutputZeroAmplitude":  # ±2900 mV below a gain of 10, ±290 mV from 10
            depends["PrimarySignalGain"] = gain = self._read("PrimarySignalGain")
            low, high = (-2.9, 2.9) if gain < 10 else (-0.29, 0.29)
        return low, high

    def _steps(self, row: Setting, mode: str, before: float, target: float, step, unit: str) -> tuple:
        """The values set() sends: the target, or with step= steps of that size in `unit` from `before`, then the target."""
        if step is None:
            return (target,)
        if row.kind != "float" or row.choices:
            raise Refusal(f"{row.label} is one of Commander's values: it takes no step")
        size = abs(self._api(row, mode, step, unit, prefix="the step: "))
        if not size:
            raise Refusal("the step needs to be larger than 0")
        count = math.ceil(abs(target - before) / size - 1e-9)
        if count > MAX_STEPS:
            raise Refusal(f"steps of that size would take {count}, more than {MAX_STEPS}: take a larger step")
        direction = math.copysign(size, target - before)
        return tuple(shortest_float32(before + direction * k) for k in range(1, count)) + (target,)

    def _check_turning_on(self, label: str, stem: str, mode: str, depends: dict):
        """enable(..., True)'s checks: Whole Cell's feedback resistor, Holding against Slow Current Injection, and the
        values a checkbox applies at once against their ranges."""
        if stem == "WholeCellCompEnable":
            self._check_whole_cell(depends)
        other = EXCLUSIVE.get(stem)
        if mode == IC and other:
            depends[other] = self._read(other)
            if depends[other]:
                other_label = checkbox(other, mode)[0]
                raise Refusal(f"{label} and {other_label} are never both on in I-Clamp: turn {other_label} off first")
        for row in SETTINGS:
            if row.enable == stem and mode in row.modes and row.kind == "float":
                depends[row.stem] = value = self._read(row.stem)
                low, high = self._limits(row, mode, depends)
                step = row.resolution.get(mode, 0.0)  # a stored value sits on Commander's steps: 0.4 MΩ is 0.399947 MΩ
                if not low - step - 1e-9 * abs(low) <= value <= high + step + 1e-9 * abs(high):
                    raise Refusal(f"turning {label} on applies {row.label}, {shown(row, mode, value)}, at once, and that is "
                                  f"outside {shown(row, mode, low)} to {shown(row, mode, high)}: set it first")

    def _plan_load_config(self, fields: dict, path: Path, changes, release_other_headstage: bool) -> tuple[Write, str, Path]:
        """load_config's checks and plan, from fresh reads, the text Commander will load and the copy it loads it from;
        Refusal at the first check that fails."""
        depends = self._preflight()
        fields |= {"mode": MODES[depends["Mode"]], "depends": depends}
        process = self.process
        if why := others_running(process):
            raise Refusal(why)
        if not process.program_found():
            raise Refusal(f"{EXE} is not in {install_dir()}, where ommm starts Commander again after closing it: set "
                          "OMMM_SDK_DIR to Commander's install folder")
        try:
            text = mcc.read(path)
        except OSError as error:
            raise Refusal(f"cannot read {path}: {error.strerror or error}") from None
        if text.startswith(mcc.SYNTHETIC) and not isinstance(process, ommm.testing.FakeProcess):
            raise Refusal(f"{path.name} is a test file, not one Commander saved (its first line says so): ommm loads it only "
                          "on the fake; load a file Commander saved (Save Configuration, F5)")
        n = self.headstage
        other_n = next(h for h in HEADSTAGES if h != n)
        checks = load_config_checks(n)
        held = mcc.values(text)
        if not any(section == mcc.FIRST for section, _ in held):
            raise Refusal(f"{path.name} is not a settings file Commander saved: load one saved with Save Configuration "
                          "(F5)")
        if not any(section.startswith(mcc.channel(n)) for section, _ in held):
            raise Refusal(f"{path.name} holds no settings for headstage {n}: load a file Commander saved with headstage {n} "
                          "connected (Save Configuration, F5)")
        if missing := [name for section, key, name in checks.values() if (section, key) not in held]:
            raise Refusal(f"{path.name} is not a whole settings file: it does not set {', '.join(missing)}, and "
                          "Commander refused a partial file with a dialog that blocked it until clicked: load a whole file Commander "
                          "saved (Save Configuration, F5)")
        if not isinstance(changes, tuple | list) or not all(isinstance(c, tuple | list) and len(c) == 4 for c in changes):
            raise Refusal(f'changes is a list of (label, value, unit, mode), such as [("Feedback Resistor", 500, "MΩ", '
                          f'"V-Clamp")]; not {changes!r}')
        tabs = mcc.tab_sections(n)
        slugs = []  # the copy's name says what each change set, so a copy of vclamp_5gohm.mcc that sets 500 MΩ is not called 5gohm
        for change in changes:
            section, key, index = self._mcc_change(change)
            text = mcc.patched(text, section, key, index)  # every key a change patches is in load_config_checks
            tab = "vc" if section == tabs[VC] else "ic"
            slugs.append(f"{tab}-{slug(change[0])}-{slug(rf(FEEDBACK_RESISTORS[int(index)]))}")
        held = mcc.values(text)
        target = {}
        for stem, (section, key, _) in checks.items():
            try:
                target[stem] = int(held[(section, key)])
            except ValueError:
                raise Refusal(f"{path.name}: {mcc.PREFIX}{key}={held[(section, key)]} in [{section}] is not a number") from None
        if target["Mode"] not in MODES:
            raise Refusal(f"{path.name}: {mcc.PREFIX}{mcc.MODE_KEY}={target['Mode']} in [{mcc.channel(n)}] is not a mode: "
                          "0 is V-Clamp, 1 I-Clamp, 2 I = 0")
        for tab in (VC, IC):
            if (index := target[feedback_resistor(tab, n)]) not in OFFERED[tab]:
                given = rf(FEEDBACK_RESISTORS[index]) if index in FEEDBACK_RESISTORS else f"index {index}"
                raise Refusal(f"{path.name}: {not_offered(tab, given)}")
        before = {stem: depends["Mode"] if stem == "Mode" else self._read(stem) for stem in checks}
        if {before["Mode"], target["Mode"]} == {MODE_IDS[VC], MODE_IDS[IC]}:
            raise Refusal(f"the file starts Commander in {MODES[target['Mode']]}; ommm goes between V-Clamp and I-Clamp "
                          'through I = 0: set_mode("I = 0") first, then load')
        try:
            other = self.commander.other_headstage("Mode", "HoldingEnable", "Holding")
        except CommanderError as error:
            raise Refusal(f"could not read headstage {other_n}, which the restart reaches too: {error}", error.code) from None
        holding = find("Holding")
        other_mode = other and MODES.get(other["Mode"])
        other_holds = other_mode in holding.modes and other["HoldingEnable"]
        if other_holds and not release_other_headstage:
            raise Refusal(f"headstage {other_n} holds {shown(holding, other_mode, other['Holding'])} in {other_mode}: the load "
                          "restarts Commander for both headstages, and both come back with Holding off, releasing a held "
                          f"cell. Turn headstage {other_n}'s Holding off first, or "
                          "pass release_other_headstage=True (ReleaseOtherHeadstage=true in MATLAB)")
        name = f"{datetime.now():%Y%m%dT%H%M%S}_{path.stem.replace(' ', '_')}{''.join('_' + s for s in slugs)}{path.suffix}"
        copy = (self.log_dir / "mcc" / name).resolve()
        if " " in str(copy):
            remedy = {  # as for a log folder ommm cannot write to, in __init__
                "OMMM_LOG_DIR": "set OMMM_LOG_DIR to a folder without one, for every program that logs there",
                "the default log folder": "set OMMM_LOG_DIR to a folder without one, or give log_dir (LogDir= in MATLAB) one",
            }.get(self._log_dir_from, "give log_dir (LogDir= in MATLAB) a folder without one")
            raise Refusal(f"ommm starts Commander with a copy of the file in {copy.parent}, in {self._log_dir_from} "
                          f"{self.log_dir}, and Commander cannot take a path with a space: {remedy}")
        what = [f"{checks[stem][2]} {shown_loaded(stem, before[stem])} → {shown_loaded(stem, value)}"
                for stem, value in target.items() if value != before[stem]]
        what += [f"{checks[stem][2]} stays {shown_loaded(stem, value)}" for stem, value in target.items() if value == before[stem]]
        reason = (f"Headstage {n}: " if other else "") + "; ".join(what) + "."
        if target[feedback_resistor(IC, n)] != before[feedback_resistor(IC, n)]:
            reason += " " + EXT_CMD_FOLLOWS
        mode = fields["mode"]
        if mode in holding.modes and self._read("HoldingEnable"):  # it comes back off (holding_left_on)
            level = shown(holding, mode, self._read("Holding"))
            reason += (f" Holding is on at {level} now; Commander comes back with it off, at the file's level: after the load, "
                       f"set Holding to {level}, then turn it on.")
        if other_holds:
            level = shown(holding, other_mode, other["Holding"])
            reason += (f" Headstage {other_n} holds {level} in {other_mode} now; the restart reaches it too, and it comes back "
                       f"with Holding off: check it after.")
        elif other:
            reason += f" Headstage {other_n} is in {other_mode}, Holding off; the restart reaches it too."
        if other and (mcc.channel(other_n), mcc.MODE_KEY) not in held:
            reason += f" The file holds no settings for headstage {other_n}: check it after the load."
        reason += (f" Commander closes and starts again with {copy}, about 15 s without Commander; every handle on it dies. "
                   "The file also sets everything else it holds: Holding, compensation and the output signals (set those "
                   "after with set and enable) and the Options pages (only another file changes those).")
        return Write(**fields, before=before, target=target, reason=reason, t=now()), text, copy

    def _mcc_change(self, change) -> tuple[str, str, str]:
        """One of load_config's changes as (section, key, value as the file writes it). Only the Feedback Resistor:
        50 MΩ to 50 GΩ in V-Clamp, no 50 GΩ in I-Clamp and I = 0, whose tab is I-Clamp's."""
        label, value, unit, mode = change
        try:
            mode = mode_name(mode)
        except ValueError as error:
            raise Refusal(f"the change {tuple(change)!r}: {error}") from None
        try:
            row = find(label, mode)
        except ValueError as error:  # find's nearest label kept; its page of every label is not where Options settings are
            known = str(error).partition(" Every label")[0]
            raise Refusal(f"{known} load_config changes only the Feedback Resistor: set other Options-page settings "
                          "in Commander's Options dialog and save the file (docs/mcc.md#an-options-page-setting)") from None
        if row.route != "mcc":
            raise Refusal(f"{row.label} is set through the API, not in the file: load the file, then set it")
        if not a_number(value):
            raise Refusal(f"{row.label} takes a number, not {value!r}")
        ohms, tab = self._api(row, mode, value, unit), tab_for(mode)
        index = next((i for i, choice in OFFERED[tab].items() if math.isclose(choice, ohms, rel_tol=1e-6)), None)
        if index is None:
            raise Refusal(not_offered(tab, f"{value:g} {unit}"))
        return mcc.tab_sections(self.headstage)[tab], row.mcc_key, str(index)

    def _load_config(self, plan: Write, text: str, copy: Path) -> Write:
        """load_config's execution: snapshot, the copy written, a start with it (_start), snapshot, the check against
        the file; a start that left any of what `unapplied` reads not as the file holds it is logged as a mismatch and
        followed by one more. A log line per phase of each start."""
        t = now()
        try:
            before = self.commander.snapshot()
        except CommanderError as error:
            raise self._failed(replace(plan, outcome="refused", reason=f"no snapshot before it: {error}", t=t), error.code) from None
        copy.parent.mkdir(parents=True, exist_ok=True)
        mcc.write(copy, text)
        held, pids, skipped = mcc.values(text), [], ""
        for start in range(1, LOAD_CONFIG_STARTS + 1):
            old, new, problems = self._start(plan, copy, t)
            pids = (pids or [old]) + [new]
            reason = (f"Commander restarted with {copy} (process {' → '.join(map(str, pids))}): every handle on it from "
                      "before died, and this Amplifier took a new one; other programs, MATLAB included, reconnect()")
            if skipped:
                reason += f"; process {pids[1]} started without the file ({skipped}), so ommm closed it and started it again"
            try:
                after = self.commander.snapshot()
            except CommanderError as error:
                raise self._failed(replace(plan, outcome="unknown", reason=f"{reason}; no snapshot after it: {error}", t=t)) from None
            differences = unapplied(plan.target, held, after, self.headstage)
            if not differences or start == LOAD_CONFIG_STARTS:
                break
            skipped = "; ".join(differences)
            self._logged(replace(plan, **loaded(plan.target, before, after), outcome="mismatch",
                                 reason=f"Commander (process {new}) started without {copy.name}: {skipped}; closing it to "
                                        "start it with the file once more", t=now()))
        if note := holding_left_on(before, after):
            reason += f"; {note}"
        report = state(after)
        problems += differences + report["blocking"] + report["problems"]
        write = self._logged(replace(plan, **loaded(plan.target, before, after), outcome="mismatch" if problems else "ok",
                                     reason=reason + "".join(f"; {problem}" for problem in problems), t=t))
        if problems:
            raise WriteError(write)
        return write

    def _start(self, plan: Write, copy: Path, t: str) -> tuple[int, int, list[str]]:
        """One close and start with the copy: quit, launch, wait for the API, the new handle taken, and 5 s later the
        output signals selected again. Commander's process before and after, and what went wrong selecting the
        signals; WriteError when Commander does not close, start or answer."""
        process = self.process
        try:
            old = quit_commander(process, self.headstage)
        except CommanderError as error:
            raise self._failed(replace(plan, outcome="error", reason=f"Commander was not closed: {error}", t=t)) from None
        self._logged(replace(plan, outcome="ok", reason=f"closed Commander (process {old}) to load {copy}", t=now()))
        try:
            new = launch_commander(copy, process)
        except (CommanderError, OSError, ValueError) as error:
            reason = f"Commander is closed and did not start: {error}; start it from its icon, then reconnect()"
            raise self._failed(replace(plan, outcome="error", reason=reason, t=t)) from None
        started = time.monotonic()
        self._logged(replace(plan, outcome="ok", reason=f"started Commander (process {new}) with {copy}", t=now()))
        try:
            commander = wait_for_api(process, self.headstage)
        except CommanderError as error:
            reason = (f"Commander started with {copy.name} (process {new}) and did not answer within {ommm.process.API_S} s: "
                      "a dialog in its window may be waiting for a person, as for a file it refuses. Answer it, then "
                      f"reconnect() ({error})")
            raise self._failed(replace(plan, outcome="unknown", reason=reason, t=t)) from None
        self.commander.close()
        self.commander = commander
        self._logged(replace(plan, outcome="ok", reason=f"Commander (process {new}) answered {time.monotonic() - started:.1f} s after it started", t=now()))
        time.sleep(LOAD_CONFIG_SETTLE_S)
        problems = []
        # always: after a start the telegraph's secondary output was stale 5 s after the API answered in two of five
        # restarts
        try:
            signals = {stem: commander.get(stem) for stem in ("Mode", "PrimarySignal", "SecondarySignal")}
            self._reselect_signals(signals, f"refresh_signals: Commander started with {copy.name}")
        except (CommanderError, WriteError) as error:
            problems.append(f"the output signals were not selected again: {error}")
        return old, new, problems

    def _check_whole_cell(self, depends: dict):
        """Commander's window greys Whole Cell, its values and its Auto out at 5 and 50 GΩ; ommm refuses them there too."""
        stem = feedback_resistor(VC, self.headstage)
        depends[stem] = index = self._read(stem)
        if FEEDBACK_RESISTORS[index] not in WHOLE_CELL_RESISTORS:
            raise Refusal(f"Commander's window greys Whole Cell out at a feedback resistor of {rf(FEEDBACK_RESISTORS[index])}: "
                          "it needs 50 or 500 MΩ, which load_config sets (docs/mcc.md)")

    def _changed_since(self, write: Write, last) -> Refusal | None:
        """Why the next step must not go: Commander no longer shows what the write was checked against, or `last`
        for the write's own control (a click in Commander's window, another program)."""
        try:
            self.commander.show_active_tab()
            for key, planned in write.depends.items():
                expected = last if key == write.stem else planned
                if (seen := self.commander.get(key)) != expected:
                    unit = write.unit if key == write.stem else None
                    name, was = described(key, expected, write.mode, self.headstage, unit)
                    _, shows = described(key, seen, write.mode, self.headstage, unit)
                    return Refusal(f"Commander changed since the write was checked: {name} was {was}, now {shows}")
        except CommanderError as error:
            return Refusal(f"could not read Commander: {error}", error.code)
        return None

    def _read(self, stem: str):
        """A reading the checks need; a missing one refuses."""
        try:
            return self.commander.get(stem)
        except CommanderError as error:
            raise Refusal(f"could not read {stem}: {error}", error.code) from None

    def _row(self, label: str, mode: str) -> Setting:
        try:
            return find(label, mode)
        except ValueError as error:
            raise Refusal(checkbox_refusal(label, mode) if checkbox_modes(label) else str(error)) from None

    def _api(self, row: Setting, mode: str, value, unit, prefix: str = "") -> float:
        try:
            return to_api(row, mode, value, unit)
        except ValueError as error:
            raise Refusal(f"{prefix}{error}") from None

    def _signal(self, row: Setting, mode: str, name) -> int:
        try:
            return signal_id(row, mode, name)
        except ValueError as error:
            raise Refusal(str(error)) from None

    def _packet(self) -> dict:
        """One telegraph packet; none, or one of another size, refuses."""
        try:
            packet = self.commander.telegraph.read(self.serial, self.headstage)
        except TimeoutError as error:
            raise Refusal(f"the mode cannot be checked: {error}") from None
        except ValueError:  # the telegraph names a headstage by its serial as a number
            raise Refusal("the mode cannot be checked: no telegraph for a non-numeric (Demo mode) serial") from None
        if packet.get("uStructSize") != PACKET_BYTES:
            raise Refusal(f"a telegraph packet of {packet.get('uStructSize')} bytes; ommm decodes {PACKET_BYTES}-byte ones")
        return packet

    # sending and logging

    def _send(self, write: Write, value, resolution: float = 0.0, telegraph: bool = False) -> Write:
        """One Set<stem>(value), read back at once (no Set tried needed time to settle) and logged; with
        `telegraph`, also checked against a telegraph packet, and unknown when none comes. What else the Set changes
        (settings.ALSO_CHANGES) is read before and after it, into `also`. An interrupt from the Set on (Ctrl+C) is
        logged first, unknown, with what was read back by then, then raised; the Set is never sent again."""
        try:
            others = {stem: self._read(stem) for stem in ALSO_CHANGES.get(write.stem, ()) if write.mode in find(stem).modes}
        except Refusal as refusal:
            return self._logged(replace(write, target=value, outcome="refused", reason=str(refusal), t=now()), refusal.code)
        write, read = replace(write, target=value, t=now()), {}
        try:
            write, code, checks = self._set_and_read(write, others, resolution, telegraph, read)
        except BaseException as error:  # Ctrl+C once the Set may have landed: its line first
            stopped = f"interrupted ({type(error).__name__})"
            if read:
                reason = f"read back, then {stopped} before its checks were done; not sent again"
            else:
                reason = f"sent, then {stopped} before the readback, so it may or may not have changed; not sent again"
            self._logged(replace(write, **read, outcome="unknown", reason=reason))
            raise
        return self._logged(write, code, checks)

    def _set_and_read(self, write: Write, others: dict, resolution: float, telegraph: bool,
                      read: dict) -> tuple[Write, int | None, list | None]:
        """_send's Set of write.target, its readback and checks: the Write to log, its error code and telegraph checks.
        `read` takes the readback, as `after` and `also`, as it comes, for a line an interrupt leaves."""
        value = write.target
        try:
            self.commander._set(write.stem, value)
        except CommanderError as error:
            if error.code == MSGTIMEOUT:
                reason = "Commander did not answer in time, so it may or may not have changed; not sent again"
                return replace(write, outcome="unknown", reason=reason), error.code, None
            return replace(write, outcome="error", reason=str(error)), error.code, None
        try:
            read["after"] = after = self.commander.get(write.stem)
            read["also"] = also = {stem: [before, seen] for stem, before in others.items() if (seen := self.commander.get(stem)) != before}
        except NotApplicable as error:
            return replace(write, outcome="mismatch", reason=f"the readback does not apply: {error}"), None, None
        except CommanderError as error:
            return replace(write, outcome="unknown", reason=f"sent, but the readback failed: {error}"), error.code, None
        outcome, reason, checks = compare(value, after, resolution), write.reason, None
        if outcome == "mismatch":
            reason = self._why(write, value, after)
        elif telegraph:
            try:
                checks = disagreements({write.stem: after}, self.commander.telegraph.read(self.serial, self.headstage))
            except TimeoutError as error:
                outcome, reason = "unknown", f"read back as sent, but no telegraph came to check it: {error}"
            if checks:
                outcome, reason = "mismatch", "the telegraph disagrees: " + "; ".join(checks)
        elif "Mode" in also:  # Mode Switching on or off: the mode follows the MODE input, which floats
            reason = f"the mode is now {MODES[also['Mode'][1]]} (the MODE input)"
        return replace(write, after=after, also=also, outcome=outcome, reason=reason), None, checks

    def _why(self, write: Write, value, after) -> str:
        """A mismatch's reason, in the caller's unit where there is one."""
        def text(api_value):
            if write.unit and isinstance(api_value, float):
                return shown(find(write.label, write.mode), write.mode, api_value, write.unit)
            return repr(api_value)

        reason = f"Commander kept {text(after)}, not {text(value)}"
        if write.stem in KILLED and isinstance(after, float) and abs(after) < abs(value):
            try:
                if self.commander.get("OscKillerEnable"):
                    return reason + ": Commander lowered it (oscillation killer)"
            except CommanderError:
                pass
        if write.stem in HINTS and not (write.stem == "Holding" and write.mode != VC):
            reason += f": {HINTS[write.stem]}"
        return reason

    def _refresh_if_stale(self):
        """Select both output signals again when the telegraph's disagree with the API's: they are stale from
        Commander's start until each mode's signals are set, and Clampex scales by them. Raises
        WriteError unless both are ok."""
        c = self.commander
        try:
            readings = {stem: c.get(stem) for stem in ("Mode", "ModeSwitchEnable", "PrimarySignal", "SecondarySignal")}
            packet = self._packet()
        except (CommanderError, Refusal):  # the write's own reads say why
            return
        if readings["ModeSwitchEnable"]:
            return
        for stem, prefix in (("PrimarySignal", "PRI_SIGNAL_"), ("SecondarySignal", "SEC_SIGNAL_")):
            readings[stem + "Name"] = c.constant_name(prefix, readings[stem])
        stale = [entry for entry in disagreements(readings, packet) if entry.partition(":")[0] in ("primary signal", "secondary signal")]
        if stale:
            self._reselect_signals(readings, "refresh_signals: " + "; ".join(stale))

    def _reselect_signals(self, readings: dict, reason: str):
        """Select both output signals again as Commander shows them (`readings`: the mode and both signals), each a
        logged write read back, so the telegraph reports them. Raises WriteError unless both are ok."""
        for stem in ("PrimarySignal", "SecondarySignal"):
            row, value = find(stem), readings[stem]
            write = Write(label=row.label, stem=stem, mode=MODES[readings["Mode"]], user_value=signal_name(row, value),
                          before=value, steps=(value,), reason=reason, t=now())
            sent = self._send(write, value)
            if sent.outcome != "ok":
                raise WriteError(replace(sent, reason=f"{sent.reason} ({reason})"))

    def _failed(self, write: Write, error_code: int | None = None) -> WriteError:
        self._logged(write, error_code)
        return WriteError(write)

    def _logged(self, write: Write, error_code: int | None = None, telegraph_checks: list | None = None) -> Write:
        """Append the write's line to the log (ommm.log, schema 2); the write."""
        program = Path(sys.argv[0]).name if getattr(sys, "argv", None) and sys.argv[0] else None
        log.append(self.log_path, {
            "schema": log.SCHEMA,
            "t": write.t,
            "process": {"pid": os.getpid(), "program": program},
            "commander": {"pid": self.commander.dll.commander_pid()},
            "serial": self.serial,
            "headstage": self.headstage,
            "label": write.label,
            "stem": write.stem,
            "mode": write.mode,
            "before": write.before,
            "target": write.target,
            "unit": write.unit,
            "user_value": write.user_value,
            "after": write.after,
            "also": write.also,
            "outcome": write.outcome,
            "reason": write.reason,
            "error_code": error_code,
            "telegraph_checks": telegraph_checks,
            "ommm": {key: value for key, value in ommm.provenance().items() if key != "git_error"},
        })
        return write
