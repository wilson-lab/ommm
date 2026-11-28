"""A fake MultiClamp Commander: the ordinary ommm.commander.Commander on a FakeDLL and a FakeTelegraph made from saved
snapshots, so code that uses ommm runs without an amplifier, on any OS. Users make it as ommm.Amplifier(fake=FILE)
(MATLAB Fake=FILE) and click with amp.gui (docs/install-and-testing.md, The fake); the rest is for contributors.

    fake = FakeCommander("vclamp.json", other_tab="iclamp.json")  # or the snapshots' dicts
    fake.gui.set("Primary Output Gain", 7, "x")  # the person at Commander types 7; Commander snaps it to 5
    fake.get("PrimarySignalGain")                # 5.0, read as from Commander
    fake.gui.show_tab("I-Clamp")                 # ... clicks a tab
    fake.gui.enable("Holding", True)             # ... a checkbox, by its name on the window
    fake.dll.calls                               # every API call made since, as (name, *inputs)
    fake.dll.fail_at(2)                          # the second call from now times out (6005)
    fake.dll.interrupt_at(2)                     # the second call from now is done, then Ctrl+C lands
    amp = ommm.Amplifier(commander=fake)         # an Amplifier on a fake made by hand

    both = FakeCommander("vclamp.json", other_headstage="iclamp.json")  # headstage 2 from a snapshot of either
    both.handle(2)                               # a second handle, on headstage 2, as a second Amplifier takes
    both.gui_for(2).set("Holding", 20, "pA")     # the person at headstage 2's panel
    amp2 = ommm.Amplifier(2, commander=both.handle(2))

A state dict, not a cell simulator: `dll.values` holds what Commander hands back for each (tab, MCCMSG stem). Which
functions exist, which tab and modes each stem belongs to, its choices and limits all come from ommm.settings, so the
fake cannot drift from the table. It models what the rig probes showed; "a guess" in a comment marks what no probe
showed.

How it is held to Commander: tests/test_fake.py replays each rig record's writes and Autos (tests/data/rig/) on a fake
started from the record's start, and expects the readbacks Commander gave; it replays parity.json too, 20 raw Sets,
unchecked, with V-Clamp active, each read back on both tabs, and expects no difference beyond each row's resolution.
The differences left are named in the tests: the mode that Mode Switching leaves; V-Clamp Holding, 0.43 mV off
Commander's where the fake computes it, at the end of its range and after Auto Pipette Offset in I-Clamp; and Auto
Pipette Offset in I-Clamp with a model cell attached, where the fake does what Commander did with nothing attached.

Where it starts: where the first snapshot found Commander, with the tab it shows; served back unchanged, the snapshot's
readings, not_applicable, telegraph packet and state() are the file's. A snapshot taken with the other mode's tab shown
needs one of the active mode's tab beside it, since every snapshot brings that tab to the front first: alone it raises
ValueError. `other_tab`, a snapshot taken with the other tab shown, in any mode, gives only that tab's own values: the
mode, Mode Switching, the meters and the feedback resistors are the first snapshot's. Without it the other tab holds
placeholders, not Commander's defaults: 0, off, Bypass for a lowpass filter, or the nearest value Commander offers;
Membrane Current and Potential on the outputs.

What it models, and only this:

- Two tabs: Gets and Sets act on the tab shown, I = 0 sharing I-Clamp's; select(), SetMode (to the current mode too)
  and a mode button show the active mode's tab.
- A Set or Auto for a setting not on the tab shown fails with 6004 and changes nothing, and so does a meter's Set
  outside the active mode; a Set for the other tab's mode, with that tab shown, lands there; a getter that does not
  apply hands back 6004 as its value.
- Never an error for a value: an off-list one goes to the nearest choice (a tie upward; Primary Output lowpass from the
  Bessel list, the filter type as found), an out-of-range one to the end of the range; values are stored as float32.
  V-Clamp Holding's range is ±1 V less the V-Clamp Pipette Offset level, `dll.offset_levels`.
- Seal Test and Tuning frequency are set as a period, and Commander keeps the one of its ten frequencies whose period
  is nearest.
- Rs Compensation Correction follows Prediction, as Commander's does with the link between them on.
- Holding is taken with its checkbox off; Holding and Slow Current Injection can both be on in I-Clamp; Whole Cell and
  Auto Whole Cell work at 5 GΩ.
- Output Zero's API value reads 10 times larger below a Primary Output gain of 10, and gain, filters, Output Zero and
  Leak Subtraction are kept per Primary Output signal (one not chosen since the fake started takes the current one's);
  an output signal id not on the tab shown's list stores that tab's Membrane Potential; Tau x20 multiplies Cp Slow's
  Tau by 20.
- Pipette Offset: one per tab, the API's I-Clamp value the panel's negated (gui.set takes the panel's); a Set is held
  within ±100 mV of the last Auto's level; Auto Pipette Offset in V-Clamp sets both tabs' offsets and levels to
  `dll.found_offsets` and adds 15 µV to I-Clamp's Slow Current Injection level, which the amplifier moves by a few
  µV, and in I-Clamp adds V-Clamp's offset to V-Clamp's Holding, turns Holding on and takes the offset to 0 V, or as
  near as its level allows. The other Autos turn their checkbox on and measure nothing.
- Each Set of Mode Switching toggles it; with it on, SetMode changes nothing and the mode buttons are greyed out.
- The telegraph reports the active mode, whichever tab is shown; the mode, gains, lowpass filters and Whole Cell reach
  it, checkboxes do not. Its signal fields stay the snapshot's, in every mode, until that mode's output signals are
  set, as after a Commander start; a write's re-selection clears them. External Command Sensitivity in a mode the
  snapshot did not show is the 5 GΩ value, and an external command signal's scale is 1 / that sensitivity.
- FindNextMultiClamp ends the list with 6000; `dll.headstages` sets what is found, and with none FindFirstMultiClamp
  says 6000 too.
- Two headstages, each with its own state; SelectMultiClamp picks the one the Gets, Sets and buttons reach. The fake
  keeps the selection per handle; Commander keeps one for every handle and program, so there one handle's select
  moves another's calls. The feedback resistor getters and the meters name their headstage whichever is selected
  (VC2 and IC2, meters 3 and 4: headstage 2). A headstage no snapshot gave is not connected and not listed:
  SelectMultiClamp refuses it with 6002, as Commander does with headstage 2 unplugged, and its feedback resistor
  answers 6006 and its meters 0; listed anyway (`dll.headstages`), every other call on it fails with 6006 (a guess).
  FakeCommander(file, headstage=2) serves a snapshot as headstage 2's, whichever headstage it was taken on.
- Closing and starting Commander, under load_config and ommm.process's functions (process=): FakeProcess.

Not modelled: a cell; what the Autos measure; the meters; Commander's steps for continuous values, so a readback is the
value sent, as float32, where Commander's are coarse but uneven (12.3456 mV reads 11.995 mV); the mode that Mode
Switching leaves, which on Commander follows its floating mode input and cannot be predicted (the fake keeps the mode
while Mode Switching is on and after); the Oscillation Killer; modal dialogs; Reset to Program Defaults and Quick
Select (both raise NotImplementedError); a .mcc file's settings other than the mode, the feedback resistors and the
values load_config checks; why Commander sometimes skips a file.

The knobs a test turns are on the handle in use, `amp.commander.dll`:

    amp.commander.dll.calls                    # every API call on this handle, in order, as (name, *inputs)
    amp.commander.dll.fail_at(2)               # the second call from now times out (6005), once
    amp.commander.dll.interrupt_at(2)          # the second call from now is done, then raises KeyboardInterrupt, once
    amp.commander.dll.dead = True              # Commander gone: no window, every call fails with 6002, no telegraph
    amp.commander.dll.offset_levels["V-Clamp"] = -0.0286  # the level the last Auto Pipette Offset found
    amp.commander.dll.found_offsets["V-Clamp"] = -0.0286  # what the next Auto Pipette Offset in V-Clamp finds
    amp.commander.dll.headstages               # what FindFirst/FindNextMultiClamp list

offset_levels and found_offsets are 0 V, placeholders, unless a test sets them. A FakeCommander's own `dll` is the
handle in use only until load_config(..., confirmed=True) or reconnect() takes a new one: after that, calls, fail_at,
interrupt_at and dead on the old one change nothing, and nothing says so. The values Commander holds, offset_levels and
found_offsets carry over to the new handle; amp.gui follows it by itself.

gui.set and gui.enable take the labels and units of docs/coming-from-commander.md, or the API names. What Commander's
window does not offer they refuse with ValueError, changing nothing: a .mcc setting, a control not on the tab shown, a
wrong or missing unit, a signal not on the tab's list, an unknown tab or mode. A click is not an API call, so
dll.calls leaves it out.

load_config(..., confirmed=True) waits 5 s after Commander answers before it selects the output signals again, on the
fake too (ommm.amplifier.LOAD_CONFIG_SETTLE_S). A test sets it to 0:
monkeypatch.setattr(ommm.amplifier, "LOAD_CONFIG_SETTLE_S", 0).
"""

import copy
import ctypes
import math
import re
import struct
from contextlib import contextmanager
from pathlib import Path

import ommm
from ommm import mcc
from ommm.checks import tab_of
from ommm.commander import Commander, CommanderError, Headstage, to_ctype
from ommm.settings import (
    AUXILIARY_SIGNALS,
    BYPASS_HZ,
    CHECKBOXES,
    FEEDBACK_RESISTORS,
    HEADSTAGES,
    I0,
    IC,
    MODES,
    PER_SIGNAL,
    PRIMARY_CUTOFFS,
    PRIMARY_SIGNALS,
    PRIMARY_TO_TELEGRAPH,
    SECONDARY_SIGNALS,
    SECONDARY_TO_TELEGRAPH,
    SETTINGS,
    SIGNAL_NAMES,
    SIGNAL_PREFIX,
    TEST_SIGNAL_HZ,
    VC,
    checkboxes_named,
    feedback_resistor,
    find,
    mode_name,
    signal_id,
    tab_for,
    to_api,
)
from ommm.state import CURRENTS, EXT_COMMANDS, POTENTIALS

MODE_IDS = {name: mode for mode, name in MODES.items()}
TAB_MODES = {VC: (VC,), IC: (IC, I0)}  # the modes each tab's settings serve; I = 0 shares the I-Clamp tab

ERRORS = {6000: "NOERROR", 6001: "OUTOFMEMORY", 6002: "MCCNOTOPEN", 6003: "INVALIDDLLHANDLE", 6004: "INVALIDPARAMETER",
          6005: "MSGTIMEOUT", 6006: "MCCCOMMANDFAIL"}  # MCCMSG_ERROR_*
NOERROR, MCCNOTOPEN, INVALIDPARAMETER, MSGTIMEOUT, MCCCOMMANDFAIL = 6000, 6002, 6004, 6005, 6006
TEXTS = {INVALIDPARAMETER: "AXMCCMSG: Invalid parameter specified."}  # Commander's words

def failed(name: str, code: int, text: str) -> CommanderError:
    """A failed API call, worded as commander.DLL.call words Commander's."""
    return CommanderError(name, code, f"{name} failed: {text}")


# the header constants ommm uses, checked against the header in tests/test_fake.py
CONSTANTS = {
    **{"ERROR_" + name: code for code, name in ERRORS.items()},
    "HW_TYPE_MC700A": 0,
    "HW_TYPE_MC700B": 1,
    "SERIALNUM_SIZE": 16,
    **dict(zip(find("Mode").choices, MODES)),
    **{"PRI_SIGNAL_" + name: signal for signal, name in PRIMARY_SIGNALS.items()},
    **{"SEC_SIGNAL_" + name: signal for signal, name in SECONDARY_SIGNALS.items()},
    "SEC_SIGNAL_IC_CMDCURRENT": 9,  # in the header, though only the 700A has it
}

C_TYPES = {"float": "double", "bool": "BOOL", "enum": "UINT"}
SETUP_FUNCTIONS = {  # NOT_COVERED's functions, typed as the header types them
    "CheckAPIVersion": ("BOOL", ["LPCSTR"]),
    "CreateObject": ("HMCCMSG", ["int *"]),
    "DestroyObject": ("void", ["HMCCMSG"]),
    "SetTimeOut": ("BOOL", ["HMCCMSG", "UINT", "int *"]),
    "FindFirstMultiClamp": ("BOOL", ["HMCCMSG", "UINT *", "char *", "UINT", "UINT *", "UINT *", "UINT *", "int *"]),
    "FindNextMultiClamp": ("BOOL", ["HMCCMSG", "UINT *", "char *", "UINT", "UINT *", "UINT *", "UINT *", "int *"]),
    "SelectMultiClamp": ("BOOL", ["HMCCMSG", "UINT", "char *", "UINT", "UINT", "UINT", "int *"]),
    "BuildErrorText": ("BOOL", ["HMCCMSG", "int", "LPSTR", "UINT"]),
    **{f"GetFeedbackResistor{tab}": ("BOOL", ["HMCCMSG", "UINT *", "int *"]) for tab in ("VC1", "IC1", "VC2", "IC2")},
    "GetMeterValue": ("BOOL", ["HMCCMSG", "double *", "UINT", "int *"]),
    "QuickSelectButton": ("BOOL", ["HMCCMSG", "UINT", "int *"]),
    "ToggleAlwaysOnTop": ("BOOL", ["HMCCMSG", "int *"]),
    "ToggleResize": ("BOOL", ["HMCCMSG", "int *"]),
}


def header_functions() -> dict[str, tuple[str, list[str]]]:
    """The header's 121 functions as Commander's parse_header gives them, parameter names left out: a getter and a
    setter for every API row and its checkbox, one function per action, and NOT_COVERED's."""
    functions = {}
    for row in SETTINGS:
        if row.kind == "action":
            functions[row.stem] = ("BOOL", ["HMCCMSG", "int *"])
        elif row.route == "api":
            for stem, kind in [(row.stem, row.kind)] + ([(row.enable, "bool")] if row.enable else []):
                functions["Get" + stem] = ("BOOL", ["HMCCMSG", C_TYPES[kind] + " *", "int *"])
                functions["Set" + stem] = ("BOOL", ["HMCCMSG", C_TYPES[kind], "int *"])
    return functions | SETUP_FUNCTIONS


FUNCTIONS = header_functions()
STEMS = {stem for row in SETTINGS for stem in (row.stem, row.enable) if stem}  # actions', settings' and checkboxes'
ROWS = {stem: [row for row in SETTINGS if stem in (row.stem, row.enable)] for stem in STEMS}
ENABLES = {stem for _, stem, _ in CHECKBOXES}  # every checkbox's API name

# above the tabs, one for both: the mode, Mode Switching and the meters
GLOBAL = {"Mode", "ModeSwitchEnable", "MeterResistEnable", "MeterIrmsEnable"}
FILTER_TYPE = "bessel"  # Options > General, which the API cannot read: Bessel on both tabs, as found
RS_LINK = True  # the link beside Rs Compensation, which the API cannot read: on, judging by the panel
# the checkbox an Auto turns on, per Commander's Help; the fake measures nothing, so the values stay
AUTO_ENABLES = {"AutoOutputZero": "OutputZeroEnable", "AutoWholeCellComp": "WholeCellCompEnable",
                "AutoLeakSub": "LeakSubEnable", "AutoBridgeBal": "BridgeBalEnable"}
# a tab no snapshot showed: Membrane Current and Potential on the outputs, I-Clamp the other way round; placeholders
PLACEHOLDER_SIGNALS = {VC: {"PrimarySignal": 0, "SecondarySignal": 1}, IC: {"PrimarySignal": 7, "SecondarySignal": 8}}

# the telegraph's dExtCmdSens by mode (V/V, A/V) at 5 GΩ; an Options-page setting, unread by the API, its .mcc key not known
EXT_CMD_SENS = {0: 0.02, 1: 4e-11, 2: 0.0}
OUTPUT_FIELDS = {  # an output's signal fields in a telegraph packet, its API signal names and telegraph indexes
    "PrimarySignal": (("uScaledOutSignal", "ScaledOutSignalName", "dScaleFactor", "uScaleFactorUnits", "ScaleFactorUnitsName"),
                      PRIMARY_SIGNALS, PRIMARY_TO_TELEGRAPH),
    "SecondarySignal": (("uRawOutSignal", "RawOutSignalName", "dRawScaleFactor", "uRawScaleFactorUnits", "RawScaleFactorUnitsName"),
                        SECONDARY_SIGNALS, SECONDARY_TO_TELEGRAPH),
}
TELEGRAPH_NAMES = {  # the telegraph's long signal names, by index: MCTG_OUT_GLDR_LONG_NAMES
    index: SIGNAL_NAMES[signals[signal][3:]]
    for _, signals, indexes in OUTPUT_FIELDS.values()
    for signal, index in indexes.items()
}
UNIT_NAMES = {0: "VOLTS_PER_VOLT", 6: "VOLTS_PER_NANOAMP", 8: "NONE"}  # MCTG_UNITS_*
NOT_CONNECTED_AUX = 44  # AXMCD_OUT_NOTCONNECTED_AUX: nothing on the auxiliary inputs, a guess


def float32(value: float) -> float:
    """As Commander stores it: readbacks carry float32 tails."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def disguised(code: int, out_param: str) -> float | int:
    """What a getter that does not apply hands back as its value: the code, as a float32's bits for a double."""
    return struct.unpack("<f", struct.pack("<I", code))[0] if out_param.startswith("double") else code


def output_zero_scale(gain: float) -> int:
    """How much larger Output Zero's API value reads at a Primary Output gain: 10 below gain 10, where its range is
    ±2900 mV instead of ±290 mV."""
    return 10 if gain < 10 else 1


def nearest(value: float, choices) -> float:
    """Commander's choice for a value off its list; a tie goes up: 2.1 kHz is 2.2 kHz in Bessel."""
    return min(choices, key=lambda choice: (abs(choice - value), -choice))


def pointee(arg):
    """What ctypes.byref(x) points at, as Commander passes out-parameters."""
    return getattr(arg, "_obj", arg)


def snapshot_of(snapshot: str | Path | dict) -> dict:
    return ommm.without_matlab_empties(snapshot) if isinstance(snapshot, dict) else ommm.load_snapshot(snapshot)


def above_the_tabs(name: str) -> bool:
    """One for both tabs: the mode, Mode Switching, the meters and the feedback resistors."""
    return name in GLOBAL or name.startswith(("MeterValue", "FeedbackResistor"))


def tab_shown(readings: dict) -> str:
    """The tab a snapshot was taken with: by its output signals, else its mode's."""
    return tab_of(readings) or tab_for(MODES.get(readings.get("Mode"), VC))


def owner(name: str) -> int | None:
    """The headstage an API name reads whichever is selected: a feedback resistor's (VC2: headstage 2) or a meter's
    (MeterValue3 and 4: headstage 2); None for the rest, which read the selected headstage."""
    if match := re.fullmatch(r"FeedbackResistor(?:VC|IC)(\d)", name):
        return int(match.group(1))
    if match := re.fullmatch(r"MeterValue(\d)", name):
        return (int(match.group(1)) + 1) // 2
    return None


# the names that read the other headstage, swapped when a snapshot moves to it
SWAPPED = {f"FeedbackResistor{tab}{a}": f"FeedbackResistor{tab}{b}" for tab in ("VC", "IC") for a, b in ((1, 2), (2, 1))} | {
    "MeterValue1": "MeterValue3", "MeterValue2": "MeterValue4", "MeterValue3": "MeterValue1", "MeterValue4": "MeterValue2"}


def as_headstage(snapshot: dict, headstage: int) -> dict:
    """A snapshot as if taken on `headstage`: one taken on the other headstage gets its channel, the names of its
    feedback resistors and meters, and its telegraph's uChannelID moved; one taken there comes back as it is."""
    if headstage not in HEADSTAGES:
        raise ValueError(f"headstage is 1 or 2, the 700B's two, not {headstage!r}")
    if int(snapshot["headstage"]["channel"]) == headstage:
        return snapshot
    moved = copy.deepcopy(snapshot)
    moved["headstage"]["channel"] = headstage
    for section in ("readings", "not_applicable"):
        moved[section] = {SWAPPED.get(name, name): value for name, value in moved[section].items()}
    if isinstance(moved.get("telegraph"), dict):
        moved["telegraph"]["uChannelID"] = headstage
    return moved


class HeadstageState:
    """What Commander holds for one headstage: FakeDLL's per-headstage attributes, which reach the selected one's."""

    def __init__(self):
        self.values = {}
        self.shown = VC
        # outputs whose signal was set since the fake started: the telegraph's signal fields stay as the snapshot's
        # in every mode until that mode's signals are set
        self.signals_set = set()
        # what Auto Pipette Offset in V-Clamp sets each tab's offset, and the level it is held around, to (API sign):
        # 0 V, a placeholder (the rig found nonzero levels), unless a test sets one
        self.found_offsets = {VC: 0.0, IC: 0.0}
        # the level each tab's Pipette Offset is held around, which also narrows V-Clamp Holding's range; no API reads
        # it, so a test sets what the last Auto found (0 V before any Auto, a guess)
        self.offset_levels = {VC: 0.0, IC: 0.0}


def per_headstage(name: str) -> property:
    """A FakeDLL attribute that is the selected headstage's."""
    return property(lambda dll: getattr(dll.states[dll.selected], name),
                    lambda dll, value: setattr(dll.states[dll.selected], name, value))


class FakeDLL:
    """Commander's state behind the one call(name, *args) that ommm.commander.Commander sends everything through, as
    commander.DLL does. `values` maps (tab, stem) to what Commander hands back on the selected headstage: (None, stem)
    above the tabs, and (tab, stem, primary signal) for what is kept per Primary Output signal; `states` holds each
    headstage's. Knobs a test may turn: `fail_at`, `interrupt_at`, `dead`, `headstages`, `found_offsets`,
    `offset_levels`."""

    values = per_headstage("values")
    shown = per_headstage("shown")
    signals_set = per_headstage("signals_set")
    found_offsets = per_headstage("found_offsets")
    offset_levels = per_headstage("offset_levels")

    def __init__(self, snapshot: dict, other_tab: dict | None = None):
        self.functions, self.constants, self.api_version = FUNCTIONS, dict(CONSTANTS), snapshot["api_version"]
        self.headstages = []  # what FindFirst/FindNextMultiClamp list: one per headstage with a state
        self.states = {}  # headstage -> HeadstageState, shared by every handle
        self.selected = None  # the headstage SelectMultiClamp chose on this handle
        self.calls = []  # (name, *inputs) for every call, out-parameters left out
        self.failures = {}  # call number -> the error code it fails with
        self.interrupts = set()  # call numbers that raise KeyboardInterrupt once done
        # Commander gone: every call fails with 6002, as a handle from before a restart does; no telegraph comes, and
        # on the newest handle its window is gone too
        self.dead = False
        self.process = None  # the FakeProcess Commander runs in, made by FakeCommander: whether its window is there
        self.found = 0  # FindFirst/FindNextMultiClamp's place in `headstages`
        self.add_headstage(snapshot, other_tab)
        self.selected = self.headstages[0].channel

    def add_headstage(self, snapshot: dict, other_tab: dict | None = None):
        """A headstage's state from snapshots taken on it (as_headstage moves one taken on the other), on the same
        amplifier."""
        headstage = Headstage(**{key: value if key == "serial" else int(value) for key, value in snapshot["headstage"].items()})
        if headstage.channel in self.states:
            raise ValueError(f"the fake has headstage {headstage.channel} already")
        if self.headstages and headstage.serial != self.headstages[0].serial:
            raise ValueError(f"one amplifier: headstage {headstage.channel}'s snapshot is of {headstage.serial}, "
                             f"not {self.headstages[0].serial}")
        self.states[headstage.channel] = HeadstageState()
        self.headstages = sorted([*self.headstages, headstage], key=lambda h: h.channel)
        with self.selecting(headstage.channel):
            readings = snapshot["readings"]
            self.shown = tab_shown(readings)
            self.seed(self.shown, snapshot)
            other = IC if self.shown == VC else VC
            if other_tab is None and self.shown != self.active_tab:  # its every snapshot would read placeholders
                raise ValueError(f"this snapshot was taken with the {self.shown} tab shown in {self.mode_name}: give other_tab= "
                                 f"(MATLAB OtherTab=) a snapshot of the {self.active_tab} tab, or read it as saved with ommm.load_snapshot(file)")
            if other_tab is None:
                self.placeholders(other)
            elif tab_shown(other_tab["readings"]) == self.shown:
                raise ValueError(f"the other tab's snapshot is of the {self.shown} tab too: give one taken with the {other} tab shown")
            else:  # in any mode: a tab's values do not depend on it
                self.seed(other, other_tab, own_only=True)
        for prefix, key in (("MODE_", "Mode"), ("PRI_SIGNAL_", "PrimarySignal"), ("SEC_SIGNAL_", "SecondarySignal")):
            if key in readings and readings.get(key + "Name", "") is None:  # read with a header that has no name for it
                self.constants = {name: v for name, v in self.constants.items() if not (name.startswith(prefix) and v == readings[key])}

    @contextmanager
    def selecting(self, headstage: int):
        """One headstage's state for a moment, as its panel in the window and its telegraph see it; no API call."""
        before, self.selected = self.selected, headstage
        try:
            yield
        finally:
            self.selected = before

    def seed(self, tab: str, snapshot: dict, own_only: bool = False):
        """One tab's readings and not-applicable codes from a snapshot taken with that tab shown; with own_only, none
        of what is above the tabs (the mode, Mode Switching, the meters, the feedback resistors), which the main snapshot gives.
        What reads the other headstage is left to it."""
        readings = snapshot["readings"]
        if "PrimarySignal" in readings:  # first: it keys what is kept per signal
            self.values[(tab, "PrimarySignal")] = readings["PrimarySignal"]

        def own(name: str) -> bool:
            return owner(name) in (None, self.selected) and not (own_only and above_the_tabs(name))

        for name, saved in snapshot["not_applicable"].items():  # "INVALIDPARAMETER (6004)"
            if "Get" + name in self.functions and own(name):
                self.values[self.key(name, tab)] = disguised(int(re.search(r"\((\d+)\)$", saved).group(1)), self.functions["Get" + name][1][1])
        for name, value in readings.items():
            if ("Get" + name in self.functions or name.startswith("MeterValue")) and own(name):
                self.values[self.key(name, tab)] = value

    def placeholders(self, tab: str):
        """A tab no snapshot showed: off, 0, Bypass for a lowpass filter, or the nearest value Commander offers
        (placeholders, not Commander's defaults), and 6004 for what does not apply there."""
        self.values |= {(tab, stem): signal for stem, signal in PLACEHOLDER_SIGNALS[tab].items()}
        for stem, rows in ROWS.items():
            getter = self.functions.get("Get" + stem)
            if not getter or stem in GLOBAL or stem in PLACEHOLDER_SIGNALS[tab]:
                continue
            offered = [row for row in rows if set(row.modes) & set(TAB_MODES[tab])]
            if not offered:
                value = disguised(INVALIDPARAMETER, getter[1][1])
            elif stem != offered[0].stem or offered[0].kind == "bool":
                value = False
            elif BYPASS_HZ in offered[0].choices:
                value = BYPASS_HZ
            elif offered[0].choices:
                value = float32(nearest(0.0, offered[0].choices))
            else:
                low, high = offered[0].limits.get(tab, (0.0, 0.0))
                value = float32(min(max(0.0, low), high))
            self.values[self.key(stem, tab)] = value

    def key(self, name: str, tab: str | None = None) -> tuple:
        if above_the_tabs(name):
            return (None, name)
        tab = tab or self.shown
        if name in PER_SIGNAL:
            return (tab, name, self.values.get((tab, "PrimarySignal")))
        return (tab, name)

    @property
    def mode_name(self) -> str:
        return MODES.get(self.values.get((None, "Mode")), VC)

    @property
    def active_tab(self) -> str:
        return tab_for(self.mode_name)

    @property
    def tab_mode(self) -> str:
        """The mode the tab shown is in: the active one if it is its tab, else the tab's own."""
        return self.mode_name if self.active_tab == self.shown else self.shown

    def fail_at(self, k: int, code: int = MSGTIMEOUT):
        """The k-th call from now fails with `code` and changes nothing, once: 6005 is Commander not answering in time."""
        self.failures[len(self.calls) + k] = code

    def interrupt_at(self, k: int):
        """The k-th call from now does what it does, then raises KeyboardInterrupt, once: Ctrl+C landing as Python
        gets the call back, after the Set or button reached Commander (fail_at's call changes nothing)."""
        self.interrupts.add(len(self.calls) + k)

    def call(self, name: str, *args):
        """As commander.DLL.call: MCCMSG_<name>(handle, *args, &error), raising CommanderError on failure."""
        _, params = self.functions[name]  # a function the header lacks raises KeyError, as on Commander
        takes = params[params[0] == "HMCCMSG" : len(params) - (params[-1] == "int *")]
        if len(args) != len(takes):
            raise TypeError(f"{name} takes {len(takes)} argument(s) after the handle, {len(args)} given")  # as ctypes does
        self.calls.append((name, *(arg for arg, param in zip(args, takes) if "*" not in param)))
        code = MCCNOTOPEN if self.dead else self.failures.pop(len(self.calls), None)
        if code:
            raise failed(name, code, TEXTS.get(code, ERRORS[code]))
        connected = self.selected in self.states
        if name.startswith("Get"):
            out, value = pointee(args[0]), self.reading(name, *args[1:])
            out.value = float(value) if isinstance(out, ctypes.c_double) else int(value)
        elif name.startswith("Set") and name != "SetTimeOut":
            if not connected:
                raise failed(name, MCCCOMMANDFAIL, ERRORS[MCCCOMMANDFAIL])
            self.write(name[3:], to_ctype(takes[0])(args[0]).value)
        elif name in ("FindFirstMultiClamp", "FindNextMultiClamp"):
            self.find(name, *args)
        elif name == "SelectMultiClamp":
            if args[-1] not in [h.channel for h in self.headstages]:  # as Commander with headstage 2 unplugged
                raise failed(name, MCCNOTOPEN, ERRORS[MCCNOTOPEN])
            self.selected = args[-1]
            if self.selected in self.states:
                self.shown = self.active_tab  # selecting brings the active mode's tab to the front
        elif name in ROWS:
            if not connected:
                raise failed(name, MCCCOMMANDFAIL, ERRORS[MCCCOMMANDFAIL])
            self.press(name)
        elif name == "QuickSelectButton":
            raise NotImplementedError("the fake has no Quick Select: it loads a .mcc file")
        if len(self.calls) in self.interrupts:
            self.interrupts.remove(len(self.calls))
            raise KeyboardInterrupt

    def reading(self, getter: str, *meter: int):
        """What a getter hands back: from the headstage it names (a feedback resistor, a meter), else the selected one;
        a headstage that is not connected reads 0 on its meters and 6006 for the rest, as its value."""
        name = f"MeterValue{meter[0] + 1}" if meter else getter[3:]
        headstage = owner(name) or self.selected
        if headstage not in self.states:
            return 0.0 if meter else disguised(MCCCOMMANDFAIL, self.functions[getter][1][1])
        with self.selecting(headstage):
            return self.stored(getter, name)

    def stored(self, function: str, name: str):
        """What Commander holds for a stem on the tab shown; 6006 when the snapshot the fake started from lacked it."""
        key = self.key(name)
        if key not in self.values:
            raise failed(function, MCCCOMMANDFAIL, "not in the snapshot the fake started from")
        return self.values[key]

    def find(self, name: str, model, serial, size, com_port, device, channel):
        """The headstages one by one; FindNext fails with NOERROR at the end of the list."""
        self.found = 0 if name == "FindFirstMultiClamp" else self.found + 1
        if self.found >= len(self.headstages):
            raise failed(name, NOERROR, ERRORS[NOERROR])
        headstage = self.headstages[self.found]
        for arg, value in zip((model, com_port, device, channel), (headstage.model, headstage.com_port, headstage.device, headstage.channel)):
            pointee(arg).value = value
        serial.value = headstage.serial.encode()

    def set_mode(self, mode: int):
        """The mode, with its tab brought to the front at once."""
        self.values[(None, "Mode")] = mode
        self.shown = self.active_tab

    def write(self, stem: str, value):
        """One API Set<stem>."""
        if stem == "ModeSwitchEnable":  # each Set toggles it, whatever the value
            self.values[(None, stem)] = not self.values.get((None, stem))
        elif stem == "TestSignalFrequency":  # the setter takes the period, in s, and Commander keeps the step whose
            # period is nearest; the getter reads Hz
            self.store(stem, 1 / min((1 / hz for hz in TEST_SIGNAL_HZ), key=lambda period: abs(period - value)))
        elif stem == "Mode":
            if value not in MODES:
                raise failed("SetMode", INVALIDPARAMETER, TEXTS[INVALIDPARAMETER])  # a guess
            if not self.values.get((None, "ModeSwitchEnable")):  # ignored with Mode Switching on
                self.set_mode(value)
        else:
            self.store(stem, value)

    def offered(self, stem: str) -> list:
        """The rows for a stem that apply with the tab shown (above the tabs: in the active mode). A Set or action for
        any other fails with 6004 (for a meter seen only with Irms in I-Clamp); a Set for the other tab's mode, with
        that tab shown, lands there (an Auto there: a guess)."""
        modes = {self.mode_name} if stem in GLOBAL else set(TAB_MODES[self.shown])
        return [row for row in ROWS.get(stem, ()) if modes & set(row.modes)]

    def store(self, stem: str, value):
        """A value set on the tab shown, the active mode's or not, as Commander keeps it."""
        rows = self.offered(stem)
        if not rows:
            raise failed("Set" + stem, INVALIDPARAMETER, TEXTS[INVALIDPARAMETER])
        row, tab = rows[0], self.shown
        if stem in ENABLES:
            value = bool(value)
            if stem == "SlowCompTauX20Enable" and value != self.values[self.key(stem)]:  # Tau reads x20
                tau = self.key("SlowCompTau")
                self.values[tau] = float32(self.values[tau] * 20 if value else self.values[tau] / 20)
        elif row.kind == "enum":  # an output signal
            signals = PRIMARY_SIGNALS if stem == "PrimarySignal" else SECONDARY_SIGNALS
            if not signals.get(value, "").startswith(SIGNAL_PREFIX[tab]):  # one off the tab's list: its Membrane Potential
                # (seen on the I-Clamp tab; on the V-Clamp tab a guess)
                value = next(signal for signal, name in signals.items() if name == SIGNAL_PREFIX[tab] + "MEMBPOTENTIAL")
            if stem == "PrimarySignal":
                self.swap_signal(tab, value)
            self.signals_set.add((tab, stem))
        else:
            value = self.snapped(row, stem, float(value))
            if stem == "PrimarySignalGain" and (zero := self.key("OutputZeroAmplitude")) in self.values:  # Output Zero's
                # API value reads 10 times larger below gain 10
                gain = self.stored("Set" + stem, stem)
                self.values[zero] = float32(self.values[zero] * output_zero_scale(value) / output_zero_scale(gain))
            if RS_LINK and stem == "RsCompCorrection":  # follows Prediction
                value = self.values[self.key("RsCompPrediction")]
            if RS_LINK and stem == "RsCompPrediction":
                self.values[self.key("RsCompCorrection")] = value
        self.values[self.key(stem)] = value

    def snapped(self, row, stem: str, value: float) -> float:
        """Never an error: a value off the list goes to the nearest choice, one out of range to its end; then
        float32."""
        choices = (*PRIMARY_CUTOFFS[FILTER_TYPE], BYPASS_HZ) if stem == "PrimarySignalLPF" else row.choices
        if choices:
            return float32(nearest(value, choices))
        low, high = row.limits.get(self.tab_mode, (-math.inf, math.inf))
        resistor = FEEDBACK_RESISTORS.get(self.values.get((None, feedback_resistor(IC, self.selected))))
        if row.rf_limit_v and self.shown == IC and resistor:  # ± rf_limit_v / Rf, per the 700B manual; not tried
            low, high = max(low, -row.rf_limit_v / resistor), min(high, row.rf_limit_v / resistor)
        if stem == "PipetteOffset":  # held within ±100 mV of the last Auto's level
            level = self.offset_levels[self.shown]
            low, high = max(low, level - 0.1), min(high, level + 0.1)
        if stem == "Holding" and self.shown == VC:  # with that level, within ±1 V
            level = self.offset_levels[VC]
            low, high = max(low, low - level), min(high, high - level)
        return float32(min(max(value, low), high))

    def swap_signal(self, tab: str, signal: int):
        """A Primary Output signal brings its own gain, filters, Output Zero and Leak Subtraction; one not chosen since
        the fake started takes the current one's, a placeholder."""
        current = self.values.get((tab, "PrimarySignal"))
        for stem in PER_SIGNAL:
            if (tab, stem, current) in self.values:
                self.values.setdefault((tab, stem, signal), self.values[(tab, stem, current)])

    def press(self, action: str):
        """A button through the API; it blocks until done and changes only what is listed here."""
        if not self.offered(action):
            raise CommanderError(action, INVALIDPARAMETER, TEXTS[INVALIDPARAMETER])
        if action == "Reset":
            raise NotImplementedError("the fake does not know Commander's program defaults")
        if action == "AutoPipetteOffset" and self.shown == VC:  # both tabs' offsets and levels
            for tab, found in self.found_offsets.items():
                self.values[(tab, "PipetteOffset")] = self.offset_levels[tab] = float32(found)
            slow = (IC, "SlowCurrentInjLevel")  # the amplifier moves it a few µV
            self.values[slow] = float32(self.values[slow] + 15e-6)
        elif action == "AutoPipetteOffset":  # with nothing attached it adds V-Clamp's offset to V-Clamp's Holding,
            # turns Holding on and takes the offset to 0 V, or as near as its level allows; no I-Clamp reading changes
            offset, level = self.values[(VC, "PipetteOffset")], self.offset_levels[VC]
            self.values[(VC, "Holding")] = float32(self.values[(VC, "Holding")] + offset)
            self.values[(VC, "PipetteOffset")] = float32(min(max(0.0, level - 0.1), level + 0.1))
            self.values[(VC, "HoldingEnable")] = True
        elif action in AUTO_ENABLES:
            self.values[self.key(AUTO_ENABLES[action])] = True

    def close(self):
        pass

    def commander_pid(self) -> int | None:
        """As commander.DLL's, which finds Commander's window by its title, whatever the handle: the FakeProcess's;
        None once Commander is gone, closed or `dead` on the newest handle, as the window goes with Commander, until a
        launch starts it again."""
        if self.process.handles[-1].dead and not self.process.launched:
            return None
        return self.process.window_pid()


def signal_fields(output: str, signal: int, resistor: float | None, sensitivity: float) -> dict:
    """An output's signal fields in a telegraph packet: a current's scale is the feedback resistor in V/nA, a
    potential's fixed in V/V, an external command's 1 / the external command sensitivity (0 when it is off, a guess)."""
    fields, signals, indexes = OUTPUT_FIELDS[output]
    kind = signals[signal][3:]
    if kind in AUXILIARY_SIGNALS:
        index, scale, units = NOT_CONNECTED_AUX, 0.0, 8
    elif kind in EXT_COMMANDS:
        current = EXT_COMMANDS[kind] == "V/A"
        index, scale, units = indexes[signal], (1 / sensitivity if sensitivity else 0.0) * (1e-9 if current else 1), 6 if current else 0
    elif kind in CURRENTS:
        index, scale, units = indexes[signal], (resistor or 0.0) * 1e-9, 6
    else:
        index, scale, units = indexes[signal], float(POTENTIALS[kind]), 0
    return dict(zip(fields, (index, TELEGRAPH_NAMES.get(index), scale, units, UNIT_NAMES[units])))


class FakeTelegraph:
    """Commander's telegraph, read as ommm.telegraph.read reads it: per headstage, its snapshot's packet, each part of
    it made again from the fake's state once what that part shows has changed: the mode (with Ext Cmd Sensitivity),
    each output's gain and lowpass filter and Whole Cell's Cm and Rs. It always reports the active mode's values,
    whichever tab is shown. Each output's signal fields stay the snapshot's, in every mode, until that mode's signal is
    set. `packet` is the selected headstage's; add() gives another's."""

    def __init__(self, dll: FakeDLL, packet: dict | None, missing: str | None = None):
        self.dll, self.seeded, self.missing, self.basis = dll, {}, {}, {}
        self.add(dll.selected, packet, missing)

    def add(self, headstage: int, packet: dict | None, missing: str | None = None):
        """A headstage's packet from its snapshot, and the state it showed."""
        self.seeded[headstage] = packet
        self.missing[headstage] = missing or "no telegraph in the snapshot the fake started from"
        with self.dll.selecting(headstage):
            self.basis[headstage] = self.sources()

    def value(self, stem: str, tab: str | None = None):
        return self.dll.values.get(self.dll.key(stem, tab or self.dll.active_tab))

    def sources(self) -> dict[str, tuple]:
        return {
            "mode": (self.dll.mode_name,),
            "primary": (self.dll.active_tab, self.value("PrimarySignalGain"), self.value("PrimarySignalLPF")),
            "secondary": (self.dll.active_tab, self.value("SecondarySignalGain"), self.value("SecondarySignalLPF")),
            "whole cell": tuple(self.value(stem, VC) for stem in ("WholeCellCompEnable", "WholeCellCompCap", "WholeCellCompResist")),
        }

    def made(self, part: str, basis: tuple) -> dict:
        """A part of the packet, made from the state it shows."""
        if part == "mode":
            mode = MODE_IDS[basis[0]]
            return {"uOperatingMode": mode, "OperatingModeName": find("Mode").choices[mode][5:], "dExtCmdSens": EXT_CMD_SENS[mode]}
        if part == "whole cell":  # telegraphed as 0 while off
            enabled, cm, rs = basis
            return {"dMembraneCap": cm if enabled else 0.0, "dSeriesResistance": rs if enabled else 0.0}
        _, gain, lowpass = basis
        if part == "primary":
            return {"dAlpha": gain, "dLPFCutoff": lowpass}
        return {"dSecondaryAlpha": gain, "dSecondaryLPFCutoff": lowpass}

    def read(self, serial: str, channel: int, timeout_s: float = 1.0) -> dict:
        """One packet for the headstage, as ommm.telegraph.read returns it; TimeoutError when none would come."""
        serials = {headstage.serial for headstage in self.dll.headstages}
        if self.dll.dead or serial not in serials or channel not in self.seeded:
            raise TimeoutError(f"no telegraph from Commander for headstage {channel} within {timeout_s:g} s")
        if self.seeded[channel] is None:
            raise TimeoutError(self.missing[channel])
        with self.dll.selecting(channel):
            packet = dict(self.seeded[channel])
            for part, basis in self.sources().items():
                if basis != self.basis[channel][part]:
                    packet |= self.made(part, basis)
            tab = self.dll.active_tab
            resistor = FEEDBACK_RESISTORS.get(self.dll.values.get((None, feedback_resistor(tab, channel))))
            for output in OUTPUT_FIELDS:
                if (tab, output) in self.dll.signals_set:
                    packet |= signal_fields(output, self.value(output), resistor, packet["dExtCmdSens"])
        return packet


class Gui:
    """The person at one headstage's panel in Commander's window (the selected one's when made), in its words: a tab,
    a mode button, a value with its unit, an output signal by name, a checkbox by name. A click changes the state at
    once; the telegraph shows it only where Commander telegraphs it (the mode, outputs, Whole Cell); every checkbox
    shows at the next read. What the window does not offer is refused with ValueError, and nothing is sent."""

    def __init__(self, dll: FakeDLL, headstage: int | None = None):
        self.dll = dll
        self.headstage = dll.selected if headstage is None else headstage

    @contextmanager
    def panel(self):
        """This headstage's state, for one click."""
        if self.headstage not in self.dll.states:
            raise ValueError(f"headstage {self.headstage} is not connected: its panel offers nothing")
        with self.dll.selecting(self.headstage):
            yield self.dll

    def show_tab(self, mode: str):
        """Click a mode's tab, "V-Clamp" or "I-Clamp", in any case (I = 0 is on I-Clamp's); the mode stays."""
        with self.panel() as dll:
            dll.shown = tab_for(mode)

    def mode(self, mode: str):
        """Click a mode button, "V-Clamp", "I = 0" or "I-Clamp", in any case: its tab comes to the front. Greyed out
        while Mode Switching is on."""
        mode = mode_name(mode)
        with self.panel() as dll:
            if dll.values.get((None, "ModeSwitchEnable")):
                raise ValueError("Commander's mode buttons are greyed out while Mode Switching is on")
            dll.set_mode(MODE_IDS[mode])

    def set(self, name: str, value, unit: str | None = None):
        """Change a value on the tab shown, by Commander's label and in its unit, with the panel's sign ("Holding",
        -60, "mV"), or choose an output signal by Commander's name ("Primary Output", "Membrane Potential").
        Commander snaps and clips the value as it does a Set."""
        with self.panel() as dll:
            mode = dll.tab_mode
            row = find(name, mode)
            if row.stem == "Mode":
                raise ValueError("click a mode button instead: gui.mode(...)")
            if row.kind == "bool":
                raise ValueError(f'{row.label} is a checkbox: turn it on or off with gui.enable("{row.label}", on)')
            if row.route != "api":
                raise ValueError(f"{row.label} changes only by restarting Commander with a .mcc file")
            if mode not in row.modes:
                raise ValueError(f"Commander's window offers no {row.label} on the {dll.shown} tab in {mode}")
            dll.store(row.stem, signal_id(row, dll.shown, value) if row.kind == "enum" else to_api(row, mode, value, unit))

    def enable(self, name: str, on: bool):
        """Click a checkbox, by its name on Commander's window (settings.CHECKBOXES), its API name or an alias, in any
        case: "Holding", "Seal Test", "Cp Slow Tau x20", "Mode Switching", "HoldingEnable"."""
        with self.panel() as dll:
            # the tab shown's checkboxes, and above the tabs the active mode's
            stem = next((stem for _, stem, modes in checkboxes_named(name)
                         if (dll.mode_name if stem in GLOBAL else dll.tab_mode) in modes), None)
            if stem is None:
                raise ValueError(f"Commander's window offers no {name} checkbox on the {dll.shown} tab in {dll.tab_mode}")
            if stem == "ModeSwitchEnable":  # a click sets the checkbox; only the API toggles it
                dll.values[(None, stem)] = bool(on)
            else:
                dll.store(stem, bool(on))


class FakeCommander(Commander):
    """Commander without Commander, from saved snapshots (files `ommm --out snapshot.json` wrote, or their dicts):

        fake = FakeCommander(ommm.EXAMPLES / "fake/vclamp.json", other_tab=ommm.EXAMPLES / "fake/iclamp.json")
        fake.gui.set("Primary Output Gain", 7, "x")  # fake.get("PrimarySignalGain") then reads 5.0, as on Commander

    It models what the rig probes saw Commander 2.2.2.2 do with nothing attached: the two tabs, values snapped and
    clipped, the telegraph, the person at the window (`gui`) and injected failures (`dll`); closing and starting it again
    is its FakeProcess, `dll.process`. It does not model a cell, the meters, Commander's steps for continuous values or
    modal dialogs; the full lists are in this module's docstring.

    The snapshot is the headstage this handle selects: its own, or `headstage=2` (or 1) to serve one taken on the
    other headstage there. `other_headstage` (with `other_headstage_tab`, its other tab) connects the other headstage,
    from a snapshot taken on either; without it the other headstage is not connected. handle(2) is a second handle on
    the same Commander, as a second Amplifier takes, and gui_for(2) the person at headstage 2's panel."""

    def __init__(self, snapshot: str | Path | dict, other_tab: str | Path | dict | None = None, *, headstage: int | None = None,
                 other_headstage: str | Path | dict | None = None, other_headstage_tab: str | Path | dict | None = None):
        if other_headstage_tab is not None and other_headstage is None:
            raise ValueError("other_headstage_tab is the other headstage's other tab: give other_headstage too")
        snapshot = snapshot_of(snapshot)
        if headstage is None:
            headstage = int(snapshot["headstage"]["channel"])
        snapshot = as_headstage(snapshot, headstage)
        dll = FakeDLL(snapshot, other_tab and as_headstage(snapshot_of(other_tab), headstage))
        telegraph = FakeTelegraph(dll, snapshot["telegraph"], snapshot.get("errors", {}).get("telegraph"))
        if other_headstage is not None:
            other = next(n for n in HEADSTAGES if n != headstage)
            second = as_headstage(snapshot_of(other_headstage), other)
            dll.add_headstage(second, other_headstage_tab and as_headstage(snapshot_of(other_headstage_tab), other))
            telegraph.add(other, second["telegraph"], second.get("errors", {}).get("telegraph"))
        shown = dll.shown
        super().__init__(dll=dll, telegraph=telegraph, headstage=headstage)
        self.guis = {n: Gui(dll, n) for n in HEADSTAGES}
        self.gui = self.guis[headstage]
        self.gui.show_tab(shown)  # select() showed the active mode's tab: show the snapshot's again
        dll.calls.clear()
        FakeProcess(self)

    def gui_for(self, headstage: int) -> Gui:
        """The person at a headstage's panel in Commander's window; `gui` is this handle's headstage's."""
        return self.guis[headstage]

    def handle(self, headstage: int) -> Commander:
        """Another handle on this Commander, on `headstage`, as a second Amplifier takes one: its own calls and
        failures, the same state, and gone with Commander as every handle is. Amplifier(2, commander=fake.handle(2))."""
        return self.dll.process.connect(headstage, restart=False)


class FakeProcess:
    """Commander's program for a FakeCommander, which makes one (`fake.dll.process`); a test that needs `slow`,
    `prompt` or `skip` makes its own, FakeProcess(fake, slow=3), which replaces it. Make it before the Amplifier, which
    keeps the process it was made with, and before any fake.handle(n), which takes the process of its moment: after
    either, it is refused. load_config and ommm.process's functions
    (process=) take it: WM_CLOSE and a launch act at once, and Commander's state carries over, as through a clean close.
    Every handle from before the close fails with 6002, and wait_for_api gives a new one; `started` holds each
    launch's command line.

    A launch with a .mcc file sets the mode, the feedback resistors and what load_config compares after a load
    (mcc.READ_BACK) that the file holds, on each connected headstage it holds, and nothing else (Commander sets every
    value the file holds, which the fake does not model); a file without the [MC700_GLOBAL] section every
    Commander-saved file starts with is refused, and Commander never answers, as it waits for OK on "not a valid
    MultiClamp configuration file" (seen with a file holding one key; which files pass is a guess). The telegraph's
    signal fields are stale until set, as after some Commander starts, and V-Clamp's Holding comes back off, at its
    level with no file and at 0 V with one, where Commander comes back at the file's level, on both headstages
    (on headstage 2 the level, and a start with no file, are a guess). `slow`: how many of wait_for_api's tries fail
    with 6002 before the new Commander answers (on the amplifier: docs/quirks.md, Closing and starting Commander). `prompt`: a dialog that blocks the close,
    leaving Commander running after WM_CLOSE; no close on the rig has shown one. `skip`: how many of the next launches
    with a file start without applying it (without_file), as Commander sometimes did."""

    def __init__(self, fake: FakeCommander, slow: int = 0, prompt: bool = False, skip: int = 0):
        if fake.dll.process and (fake.dll.process.held or len(fake.dll.process.handles) > 1):
            raise ValueError("an Amplifier or another handle holds this fake's FakeProcess and would not use a new one: "
                             "make the FakeProcess before any Amplifier or fake.handle(n)")
        self.fake, self.slow, self.prompt, self.skip = fake, slow, prompt, skip
        self.held = False  # an Amplifier keeps it (Amplifier.process)
        self.pid, self.serial, self.starting, self.refused = 1000, None, 0, None
        self.launched = False  # started since the newest handle was taken
        self.started = []  # each launch's command line after MC700B.exe
        self.handles = [fake.dll]
        fake.dll.process = self

    def window_pid(self) -> int | None:
        return self.pid

    def pids(self) -> list[int]:
        return [self.pid] if self.pid else []

    def close_window(self, pid: int):
        if self.prompt:
            return
        self.pid = None
        for handle in self.handles:
            handle.dead = True

    def wait_exit(self, pid: int, timeout_s: float) -> bool:
        return self.pid != pid

    def program_found(self) -> bool:
        return True

    def start(self, args: list[str]) -> int:
        self.started.append(args)
        self.pid, self.starting, self.refused = 1000 + len(self.started), self.slow, None
        self.launched = True
        files = [Path(arg[2:]) for arg in args if arg.startswith("/C")]
        for state in self.fake.dll.states.values():  # shared by every handle
            state.signals_set.clear()
            # Commander comes back with V-Clamp Holding off: at its level with no file, at 0 V with one; I-Clamp's not
            # tried
            state.values[(VC, "HoldingEnable")] = False
            if files:
                state.values[(VC, "Holding")] = 0.0
        for path in files:
            if self.skip:
                self.skip -= 1
                self.without_file()
            else:
                self._load_config(path)
        return self.pid

    def without_file(self):
        """A start that did not apply its file, as a Commander start with a .mcc file sometimes does (docs/quirks.md):
        the settings Commander had before the close, but for Pulse 0 and 100 µs on both tabs and the I-Clamp Secondary
        Output Auxiliary 2, on each headstage (headstage 2's a guess)."""
        aux2 = next(signal for signal, name in SECONDARY_SIGNALS.items() if name == "IC_AUXILIARY2")
        for state in self.fake.dll.states.values():
            for tab in (VC, IC):
                state.values[(tab, "PulseAmplitude")], state.values[(tab, "PulseDuration")] = 0.0, float32(1e-4)
            state.values[(IC, "SecondarySignal")] = aux2

    def _load_config(self, path: Path):
        """The mode, the feedback resistor indexes and the values in mcc.READ_BACK a .mcc file holds, for each
        connected headstage; or the file refused."""
        held, dll = mcc.values(mcc.read(path)), self.fake.dll
        if not any(section == mcc.FIRST for section, _ in held):
            self.refused = path
            return
        key = find("Feedback Resistor").mcc_key
        for headstage in dll.states:
            with dll.selecting(headstage):
                for tab, section in mcc.tab_sections(headstage).items():
                    if (section, key) in held:
                        dll.values[(None, feedback_resistor(tab, headstage))] = int(held[(section, key)])
                    for stem, read_back in mcc.READ_BACK[tab].items():
                        if (section, read_back) in held:
                            value = mcc.parsed(held[(section, read_back)])
                            dll.values[(tab, stem)] = value if isinstance(value, bool) else float32(value)
                if (mcc.channel(headstage), mcc.MODE_KEY) in held:
                    dll.set_mode(int(held[(mcc.channel(headstage), mcc.MODE_KEY)]))

    def connect(self, headstage: int = 1, restart: bool = True) -> Commander:
        """A new handle, as Commander(headstage=...): on the fake's state, with calls of its own; 6002 while Commander is
        closed or still starting, and for good after a file it refused. `restart` False: a second handle beside the
        others (FakeCommander.handle), not the first after a start."""
        if self.pid is None or self.starting or self.refused:
            self.starting = max(0, self.starting - 1)
            raise CommanderError("FindFirstMultiClamp", MCCNOTOPEN, "Commander not found")
        dll = copy.copy(self.fake.dll)  # the same states, telegraph state and headstages
        dll.calls, dll.failures, dll.dead = [], {}, False
        telegraph = copy.copy(self.fake.telegraph)
        telegraph.dll = dll
        self.handles.append(dll)
        if restart:
            self.launched = False
            for gui in self.fake.guis.values():  # the person at the window works the Commander now running
                gui.dll = dll
        return Commander(dll=dll, telegraph=telegraph, headstage=headstage)
