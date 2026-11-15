"""Commander's controls as one table, and the one place for its modes, tabs and output signals.

Each row of SETTINGS is a setting (a value you set and read back) or an action (a button), named as Commander
names it, with its MCCMSG stem, the modes it applies in, its unit per mode, the vendor's limits and choices, and
how finely Commander stores it. ommm.Amplifier's reads, writes and readback and the docs' control page come from it.
Clampwise (GPL-3) inspired the table: ideas only, no code.

The comment that closes each row says where its facts come from, for developers. Every row's calls are in
AxMultiClampMsg.h (API 1.0.0.9), "the header", and AxMultiClampMsg.pdf, "the PDF"; "the manual" is the MultiClamp
700B Theory and Operation manual, "help" Commander's help (with the page where its name differs from the label), and
"TestBed" the SDK's MCCMSG_TestBed sample. "Seen on a 700B" is with Commander 2.2.2.2 and nothing attached, "on the
model cell" a PATCH-1U model cell at CELL; the probe records in tests/data/rig/ hold most of it. A guess says so.
"""

import difflib
import unicodedata
from dataclasses import dataclass, field

# Commander's modes by MCCMSG_MODE_* id
MODES = {0: "V-Clamp", 1: "I-Clamp", 2: "I = 0"}
VC, IC, I0 = MODES.values()
ALL_MODES = (VC, IC, I0)

# Commander's two mode tabs, left to right: the index is Commander's tab number
TABS = ("V-Clamp", "I-Clamp")
# the prefix of each tab's output signals in the header's names (VC_MEMBCURRENT)
SIGNAL_PREFIX = {"V-Clamp": "VC_", "I-Clamp": "IC_"}


BUTTON_MODES = {"vc": VC, "ic": IC, "i=0": I0}  # Commander's mode buttons, as their labels read


def mode_name(name: str) -> str:
    """A mode's name as MODES spells it ("I-Clamp") or as Commander's button reads ("IC"), in any case;
    anything else is refused."""
    modes = {mode.lower(): mode for mode in ALL_MODES} | BUTTON_MODES
    if str(name).lower() not in modes:
        raise ValueError(f"{name!r} is not a mode: use 'V-Clamp', 'I-Clamp' or 'I = 0', or the buttons' 'VC', 'IC' or 'I=0'")
    return modes[str(name).lower()]


def tab_for(mode: str) -> str:
    """The tab a mode's settings live on, the mode in any case: I = 0 shares the I-Clamp tab."""
    return "V-Clamp" if mode_name(mode) == "V-Clamp" else "I-Clamp"


# the 700B's two headstages, the API's channels
HEADSTAGES = (1, 2)


def feedback_resistor(mode: str, headstage: int) -> str:
    """The API name that reads a mode's feedback resistor index on a headstage: FeedbackResistorVC1 to
    FeedbackResistorIC2, by its tab (I = 0 reads I-Clamp's). It names its headstage, whichever is selected."""
    return f"FeedbackResistor{'VC' if tab_for(mode) == 'V-Clamp' else 'IC'}{headstage}"


# ohms, by the index FeedbackResistorVC1/IC1 (VC2/IC2 on headstage 2) read and a .mcc file holds
FEEDBACK_RESISTORS = {0: 50e6, 1: 500e6, 2: 5e9, 3: 50e9}
IC_FEEDBACK_RESISTORS = (50e6, 500e6, 5e9)  # I-Clamp has no 50 GΩ
# Commander's window offers Whole Cell, its checkbox, values and Auto, only at 50 and 500 MΩ; the API takes it at
# 5 GΩ too (seen on a 700B)
WHOLE_CELL_RESISTORS = (50e6, 500e6)
# Cp Slow Tau's range, SI, with Tau x20 off and on
TAU_X20_RANGES = {False: (10e-6, 200e-6), True: (200e-6, 4000e-6)}
# Seal Test and Tuning frequencies, Hz: each read back as sent, and 3, 7, 15, 30, 70, 150, 300 and 700 Hz were kept as
# the one whose period is nearest; probably no others, as those snaps leave room for few (docs/quirks.md, Seal Test
# and Tuning frequency are set as a period)
TEST_SIGNAL_HZ = (2.0, 5.0, 10.0, 20.0, 50.0, 60.0, 100.0, 200.0, 500.0, 1000.0)

# Output signals by MCCMSG_PRI_SIGNAL_* and MCCMSG_SEC_SIGNAL_* id, the header's names without that prefix. The two
# I-Clamp lists differ; secondary 9 (IC_CMDCURRENT) is the 700A's, so not here.
PRIMARY_SIGNALS = {
    0: "VC_MEMBCURRENT", 1: "VC_MEMBPOTENTIAL", 2: "VC_PIPPOTENTIAL", 3: "VC_100XACMEMBPOTENTIAL",
    4: "VC_EXTCMDPOTENTIAL", 5: "VC_AUXILIARY1", 6: "VC_AUXILIARY2",
    7: "IC_MEMBPOTENTIAL", 8: "IC_MEMBCURRENT", 9: "IC_CMDCURRENT", 10: "IC_100XACMEMBPOTENTIAL",
    11: "IC_EXTCMDCURRENT", 12: "IC_AUXILIARY1", 13: "IC_AUXILIARY2",
}
SECONDARY_SIGNALS = {
    0: "VC_MEMBCURRENT", 1: "VC_MEMBPOTENTIAL", 2: "VC_PIPPOTENTIAL", 3: "VC_100XACMEMBPOTENTIAL",
    4: "VC_EXTCMDPOTENTIAL", 5: "VC_AUXILIARY1", 6: "VC_AUXILIARY2",
    7: "IC_MEMBPOTENTIAL", 8: "IC_MEMBCURRENT", 10: "IC_PIPPOTENTIAL", 11: "IC_100XACMEMBPOTENTIAL",
    12: "IC_EXTCMDCURRENT", 13: "IC_AUXILIARY1", 14: "IC_AUXILIARY2",
}

# Commander's words for a signal, by its header name without the tab prefix
SIGNAL_NAMES = {
    "MEMBCURRENT": "Membrane Current",
    "MEMBPOTENTIAL": "Membrane Potential",
    "PIPPOTENTIAL": "Pipette Potential",
    "100XACMEMBPOTENTIAL": "100x AC Membrane Potential",
    "EXTCMDPOTENTIAL": "External Command Potential",
    "EXTCMDCURRENT": "External Command Current",
    "CMDCURRENT": "Command Current",
    "AUXILIARY1": "Auxiliary 1",
    "AUXILIARY2": "Auxiliary 2",
}
AUXILIARY_SIGNALS = {"AUXILIARY1", "AUXILIARY2"}  # whatever is on the rear-panel auxiliary inputs

# kept per Primary Output signal, swapped in with it; the Secondary Output gain is not (docs/quirks.md, A Primary
# Output signal brings back its own settings)
PER_SIGNAL = ("PrimarySignalGain", "PrimarySignalLPF", "PrimarySignalHPF", "ScopeSignalLPF", "OutputZeroAmplitude", "LeakSubResist")
# what a Set changes besides its own reading, all seen on a 700B: the signal's own values, Output Zero's API value
# with the gain, Cp Slow's Tau with Tau x20, Correction with Prediction while the Rs link is on, and the mode with
# Mode Switching, which follows the floating mode input
ALSO_CHANGES = {
    "PrimarySignal": PER_SIGNAL,
    "PrimarySignalGain": ("OutputZeroAmplitude",),
    "SlowCompTauX20Enable": ("SlowCompTau",),
    "RsCompPrediction": ("RsCompCorrection",),
    "ModeSwitchEnable": ("Mode",),
}

# API signal id -> the telegraph's signal index (AXMCD_OUT_*), as seen on a 700B, each signal set in turn. Auxiliary
# signals are not sent by these: the telegraph sends AXMCD_OUT_V_AUX1 ... NOTCONNECTED_AUX (40-45) instead.
PRIMARY_TO_TELEGRAPH = {**{api: api for api in range(7)}, **{api: api + 13 for api in range(7, 14)}}
SECONDARY_TO_TELEGRAPH = {
    **{api: api + 10 for api in range(7)},
    7: 30, 8: 31, 10: 32, 11: 33, 12: 34, 13: 35, 14: 36,
}
AUXILIARY_TELEGRAPH = range(40, 46)

# Primary Output lowpass cutoffs (Hz) for each filter type, from the manual. Most tell the type apart
# (2, 10 and 20 kHz exist only for Bessel), which the API cannot read. 100 kHz is Bypass for both.
PRIMARY_CUTOFFS = {
    "bessel": {
        2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 40, 60, 80, 100, 120, 140, 160, 180, 200, 220, 240, 260,
        280, 300, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800, 3000, 4000, 6000, 8000,
        10000, 12000, 14000, 16000, 18000, 20000, 22000, 24000, 26000, 28000, 30000,
    },
    "butterworth": {
        3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 390,
        420, 450, 600, 900, 1200, 1500, 1800, 2100, 2400, 2700, 3000, 3300, 3600, 3900, 4200, 4500, 6000, 9000, 12000,
        15000, 18000, 21000, 24000, 27000, 30000, 33000, 36000, 39000, 42000, 45000,
    },
}
BYPASS_HZ = 1e5  # a lowpass filter's Bypass, as the API and the telegraph give it (MCTG_LPF_BYPASS)

# unit -> (dimension, SI factor): the one unit table, one key per spelling. Greek and ASCII spellings both work, and
# known_unit takes each Greek one however it was typed
UNITS = {
    "V": ("voltage", 1), "mV": ("voltage", 1e-3),
    "A": ("current", 1), "nA": ("current", 1e-9), "pA": ("current", 1e-12),
    "F": ("capacitance", 1), "pF": ("capacitance", 1e-12),
    "Ohm": ("resistance", 1), "MOhm": ("resistance", 1e6), "GOhm": ("resistance", 1e9),
    "s": ("time", 1), "ms": ("time", 1e-3), "us": ("time", 1e-6),
    "Hz": ("frequency", 1), "kHz": ("frequency", 1e3),
    "%": ("percent", 1), "x": ("gain", 1),
}
UNITS |= {"Ω": UNITS["Ohm"], "MΩ": UNITS["MOhm"], "GΩ": UNITS["GOhm"], "µs": UNITS["us"], "×": UNITS["x"]}
SPELLED = {unicodedata.normalize("NFKC", name): name for name in UNITS}  # each key by its NFKC form


def known_unit(name) -> tuple[str, float] | None:
    """A unit's (dimension, SI factor), None for one ommm does not know. Looked up by its NFKC form, so the ohm sign
    (U+2126, as Windows' Character Map gives it) is Ω and the Greek mu (U+03BC) the micro sign µ."""
    if not isinstance(name, str):
        return None
    return UNITS.get(SPELLED.get(unicodedata.normalize("NFKC", name)))


def units_wanted(kind: str, first: str, given) -> str:
    """What to say for a unit given that is not of the kind: "give a unit: MΩ or GΩ", or "MOhm or GOhm, not Mohm".
    The units are `first`'s, then the kind's other prefixed ones, each spelled in the script of the unit given (ASCII
    for ASCII), else in `first`'s."""
    ascii = given.isascii() if isinstance(given, str) else first.isascii()
    spelled = {}  # factor -> its spelling
    for name, (dimension, factor) in UNITS.items():
        if dimension == kind and (factor not in spelled or name.isascii() == ascii):
            spelled[factor] = name
    first_factor = UNITS[first][1]
    others = [name for factor, name in spelled.items() if factor not in (1, first_factor)]
    units = " or ".join([spelled[first_factor], *others])
    return f"give a unit: {units}" if given is None else f"{units}, not {given}"


@dataclass(frozen=True)
class Setting:
    """One of Commander's controls. Per-mode fields are keyed by mode name; values are SI, except where the API is
    not: Rs Compensation's percentages and the gains. `modes` are where Commander applies it: the vendor's modes, a
    Set or Auto in another refused with 6004, and I = 0 where its tab leaves the control enabled."""

    label: str  # Commander's name for it, e.g. "Rs Compensation Correction"
    stem: str  # the MCCMSG stem: Get<stem> and Set<stem>, or an action's function
    kind: str  # "float", "bool" or "enum", as the API types it (double, BOOL, UINT), or "action"
    modes: tuple[str, ...]
    unit: dict[str, str] = field(default_factory=dict)  # per mode, the unit Commander shows, a key of UNITS
    limits: dict[str, tuple[float, float]] = field(default_factory=dict)  # per mode, SI: the vendor's range
    choices: tuple = ()  # the values Commander offers: SI values, or for an enum the header's constant names
    # per mode, SI: how far from the value sent Commander may store it; the largest difference the probes saw,
    # rounded up, else the vendor's step; none known: any difference counts
    resolution: dict[str, float] = field(default_factory=dict)
    sign: dict[str, int] = field(default_factory=dict)  # per mode, -1 where the API's value is the panel's negated
    enable: str | None = None  # the stem of its checkbox, e.g. "HoldingEnable"
    telegraph: str | None = None  # the telegraph field that carries it
    rf_limit_v: float | None = None  # I-Clamp range: ± this many volts / the feedback resistor
    # per V-Clamp feedback resistor (ohms), SI: the vendor's range there, where it differs from `limits`
    rf_limits: dict[float, tuple[float, float]] = field(default_factory=dict)
    route: str = "api"  # "api", or "mcc": changed only by restarting Commander with a .mcc file
    mcc_key: str = ""  # its key in each tab's section of a .mcc file (ommm.mcc), after AXMCD_FIELD_
    note: str = ""  # what it does, in plain words, for the docs


def every_mode(value) -> dict:
    return dict.fromkeys(ALL_MODES, value)


SETTINGS: tuple[Setting, ...] = (
    # the top of the window
    Setting(
        "Mode", "Mode", "enum", ALL_MODES,
        choices=("MODE_VCLAMP", "MODE_ICLAMP", "MODE_ICLAMPZERO"), telegraph="uOperatingMode",
        note="V-Clamp, I-Clamp or I = 0. ommm's set_mode goes between V-Clamp and I-Clamp only through I = 0.",
        # the header; shown at once, seen on a 700B and on the model cell
    ),
    Setting(
        "Mode Switching", "ModeSwitchEnable", "bool", ALL_MODES,
        note="The checkbox above the tabs, beside the mode buttons: on, the mode follows the MODE input on the front "
        "panel, or a Vm threshold set in Options > Auto, and the mode buttons grey out. Each Set toggles it, whatever "
        "the value sent.",
        # help (External Control, Options > Auto); each Set toggles it, seen on a 700B
    ),
    Setting(
        "Resistance Meter", "MeterResistEnable", "bool", (VC, IC),
        note="The Resistance checkbox: the first meter shows resistance, from pulses added to the command, instead of "
        "the potential. Its reading changes meaning about 0.5 s after the Set.",
        # the manual; the meters seen on a 700B
    ),
    Setting(
        "Irms Meter", "MeterIrmsEnable", "bool", (VC,),
        note="The Irms checkbox: the second meter shows the RMS current noise instead of the current.",
        # refused in I-Clamp, seen on a 700B
    ),
    # both tabs' top rows
    Setting(
        "Holding", "Holding", "float", (VC, IC),
        unit={VC: "mV", IC: "pA"}, limits={VC: (-1.0, 1.0)}, resolution={VC: 4e-4, IC: 7e-13},
        enable="HoldingEnable", rf_limit_v=1.0,
        note="The holding level, applied at once while its checkbox is on. It adds to any holding level the "
        "acquisition program sends. In V-Clamp, Holding plus the level the last Auto Pipette Offset found stays "
        "within ±1000 mV, so near the ends the range is narrower. In I-Clamp it cannot be on together with Slow "
        "Current Injection. A value set with the checkbox off is kept, and applied when the checkbox goes on.",
        # the PDF types it BOOL, the header's double is right; the manual: ±1000 mV in 30 µV steps, I-Clamp ±1 V/Rf in
        # 0.7 pA steps at 50 MΩ (about 100 times finer at 5 GΩ), the I-Clamp resolution; help; seen on a 700B:
        # 12.3456 mV read 11.995 mV, the range narrowed by the Auto's level, and a Set taken with its checkbox off
    ),
    Setting(
        "Seal Test Amplitude", "TestSignalAmplitude", "float", (VC,),
        unit={VC: "mV"}, limits={VC: (-1.0, 1.0)}, resolution={VC: 3.2e-5}, enable="TestSignalEnable",
        note="Square pulses on the command while Seal Test is on, to watch a seal form. Seal Test sends a Sync Output.",
        # the manual, help; on the model cell 10 mV read 9.99687 mV and 2 mV 2.00564 mV, steps of 31.3 µV
    ),
    Setting(
        "Seal Test Frequency", "TestSignalFrequency", "float", (VC,),
        unit={VC: "Hz"}, choices=TEST_SIGNAL_HZ, enable="TestSignalEnable",
        note="Seal Test's pulse rate: 2, 5, 10, 20, 50, 60, 100, 200, 500 or 1000 Hz.",
        # the PDF (Hz), the manual, help (2-1000 Hz in steps); on the model cell the setter takes the period in s, the
        # getter reads Hz, and the steps
    ),
    Setting(
        "Tuning Amplitude", "TestSignalAmplitude", "float", (IC,),
        unit={IC: "pA"}, resolution={IC: 3.2e-12}, enable="TestSignalEnable", rf_limit_v=10.0,
        note="A square current while Tuning is on, the I-Clamp twin of Seal Test, used to set Pipette Capacitance "
        "Neutralization. Tuning sends a Sync Output.",
        # the manual (±10 V/Rf), help; on the model cell 10 pA read 10.0282 pA at 5 GΩ, steps of 31.3 fA; the 3.2 pA at
        # 50 MΩ is a guess: the steps scale with the range
    ),
    Setting(
        "Tuning Frequency", "TestSignalFrequency", "float", (IC,),
        unit={IC: "Hz"}, choices=TEST_SIGNAL_HZ, enable="TestSignalEnable",
        note="Tuning's rate: 2, 5, 10, 20, 50, 60, 100, 200, 500 or 1000 Hz.",
        # the PDF (Hz), the manual, help (2-1000 Hz in steps); on the model cell the setter takes the period in s, the
        # getter reads Hz, and the steps
    ),
    Setting(
        "Pipette Offset", "PipetteOffset", "float", ALL_MODES,
        unit=every_mode("mV"), resolution={VC: 3e-5, IC: 7e-7, I0: 7e-7}, sign={IC: -1, I0: -1},
        note="Zeroes the pipette's junction potential in the bath; set it before the seal. One offset per tab, I = 0 "
        "sharing I-Clamp's, each held within ±100 mV of the level the last Auto Pipette Offset found, which nothing reads.",
        # help: ±100 mV around the Auto's level, 30 µV steps in V-Clamp; seen on a 700B: one per tab, the API's I-Clamp
        # value the panel's negated, held near the Auto's level, and 10 mV read 9.99938 mV in I-Clamp
    ),
    Setting(
        "Slow Current Injection Level", "SlowCurrentInjLevel", "float", (IC,),
        unit={IC: "mV"}, limits={IC: (-1.0, 1.0)}, resolution={IC: 9e-6}, enable="SlowCurrentInjEnable",
        note="The membrane potential that slow current injection keeps the cell at. It cannot be on together with "
        "Holding. Its ±1000 mV range is from the SDK's sample program.",
        # help; limits from the TestBed's spinner, not tried; seen on a 700B: -51 mV read -50.991 mV
    ),
    Setting(
        "Slow Current Injection Settling Time", "SlowCurrentInjSettlingTime", "float", (IC,),
        unit={IC: "ms"}, enable="SlowCurrentInjEnable",
        note="How fast slow current injection follows: the time to 99 % when the load equals the feedback resistor.",
        # help
    ),
    # the V-Clamp tab
    Setting(
        "Cp Fast Capacitance", "FastCompCap", "float", (VC,),
        unit={VC: "pF"}, limits={VC: (0.0, 36e-12)}, rf_limits={50e9: (0.0, 12e-12)},
        note="Fast pipette capacitance compensation, always on: there is no checkbox. 0-12 pF at 50 GΩ. Too much rings.",
        # the manual, help (Ce Fast)
    ),
    Setting(
        "Cp Fast Tau", "FastCompTau", "float", (VC,),
        unit={VC: "µs"}, limits={VC: (0.5e-6, 1.8e-6)}, resolution={VC: 6e-9},
        note="The time constant of the fast capacitance compensation.",
        # the manual, help (Ce Fast); seen on a 700B: 1.5 µs read 1.4941 µs
    ),
    Setting(
        "Cp Slow Capacitance", "SlowCompCap", "float", (VC,),
        unit={VC: "pF"}, limits={VC: (0.0, 3e-12)}, resolution={VC: 4.8e-14}, rf_limits={50e9: (0.0, 1e-12)},
        note="Slow pipette capacitance compensation, always on: there is no checkbox. 0-1 pF at 50 GΩ.",
        # the manual, help (Ce Slow); on the model cell 0.5 pF read 0.476191 pF, steps of 3/63 pF
    ),
    Setting(
        "Cp Slow Tau", "SlowCompTau", "float", (VC,),
        unit={VC: "µs"}, limits={VC: (10e-6, 4000e-6)}, resolution={VC: 3e-6},
        note="The slow compensation's time constant: 10-200 µs, or 200-4000 µs with Cp Slow Tau x20 on; ommm "
        "checks it against the range the checkbox gives.",
        # the manual, help (Ce Slow); seen on a 700B with Tau x20 off: 100 µs read 102.56 µs
    ),
    Setting(
        "Cp Slow Tau x20", "SlowCompTauX20Enable", "bool", (VC,),
        note="The Tau x20 checkbox: Cp Slow Tau's range times 20, and turning it on multiplies the Tau by 20. Auto Cp "
        "Slow sets it when it needs to.",
        # help (Ce Slow); turning it on multiplies the Tau read by 20, seen on a 700B
    ),
    Setting(
        "Whole Cell Cm", "WholeCellCompCap", "float", (VC,),
        unit={VC: "pF"}, limits={VC: (1e-12, 1000e-12)}, resolution={VC: 2e-15},
        rf_limits={50e6: (2.5e-12, 1000e-12), 500e6: (1e-12, 100e-12)},
        enable="WholeCellCompEnable", telegraph="dMembraneCap",
        note="The membrane capacitance Whole Cell compensates while its checkbox is on: 1-100 pF at 500 MΩ, "
        "2.5-1000 pF at 50 MΩ. Commander's window offers Whole Cell, its values too, only at those two feedback "
        "resistors, and ommm refuses it at the others. The telegraph sends 0 while Whole Cell is off.",
        # the manual, help; seen on a 700B: greyed out in the window at 5 GΩ yet turned on by the API there, telegraphed
        # as 0 while off, and 10 pF read 10.0011 pF
    ),
    Setting(
        "Whole Cell Rs", "WholeCellCompResist", "float", (VC,),
        unit={VC: "MΩ"}, limits={VC: (1e5, 1e9)}, resolution={VC: 7e3},
        rf_limits={50e6: (1e5, 1e8), 500e6: (4e5, 1e9)},
        enable="WholeCellCompEnable", telegraph="dSeriesResistance",
        note="The series resistance Whole Cell compensation assumes, which Rs Compensation works from: "
        "0.4-1000 MΩ at 500 MΩ, 0.1-100 MΩ at 50 MΩ.",
        # the manual, help; seen on a 700B: greyed out at 5 GΩ, and 10 MΩ read 10.0066 MΩ
    ),
    Setting(
        "Rs Compensation Bandwidth", "RsCompBandwidth", "float", (VC,),
        unit={VC: "kHz"}, limits={VC: (320.0, 16e3)}, resolution={VC: 40.0}, enable="RsCompEnable",
        note="The lowpass cutoff of the Rs Compensation signal.",
        # the PDF (Hz), the manual, help (kHz); seen on a 700B: 5 kHz read 4.9686 kHz
    ),
    Setting(
        "Rs Compensation Prediction", "RsCompPrediction", "float", (VC,),
        unit={VC: "%"}, limits={VC: (0.0, 100.0)}, enable="RsCompEnable",
        note="Adds a transient to the command so the membrane follows it despite the series resistance; needs Whole "
        "Cell on. Open loop, but it saturates if pushed too far. The 0-100 % range is ommm's own, assumed for a "
        "percentage.",
        # the PDF (%), help (Resistance Compensation); 0-100 % a guess for a percentage
    ),
    Setting(
        "Rs Compensation Correction", "RsCompCorrection", "float", (VC,),
        unit={VC: "%"}, limits={VC: (0.0, 100.0)}, enable="RsCompEnable",
        note="Positive feedback against the series resistance's voltage error. Too much oscillates and can kill the "
        "cell. With the link button beside it on, it follows Prediction; the API cannot change the link. The 0-100 % "
        "range is ommm's own, assumed for a percentage.",
        # the PDF (%), help (Resistance Compensation); 0-100 % a guess for a percentage; follows Prediction, seen on a
        # 700B and on the model cell
    ),
    Setting(
        "Disable/Reduce if Oscillation Detected", "OscKillerEnable", "bool", (VC, IC),
        note="The Oscillation Killer, one checkbox per tab: on, Commander turns off or lowers Rs Compensation "
        "(V-Clamp, by 10 %) or Pipette Capacitance Neutralization (I-Clamp, by 1 pF) when it detects oscillation. "
        "Options > Auto chooses off or lower.",
        # help (Resistance Compensation, Pipette Capacitance)
    ),
    Setting(
        "Leak Subtraction", "LeakSubResist", "float", (VC,),
        unit={VC: "MΩ"}, enable="LeakSubEnable",
        note="Subtracts the leak through the seal resistance given from Membrane Current while its checkbox is on; "
        "for patches, not whole cell. Kept per Primary Output signal.",
        # help; kept per primary signal, seen on a 700B
    ),
    Setting(
        "Zap Duration", "ZapDuration", "float", (VC,),
        unit={VC: "ms"}, choices=(25e-6, 50e-6, 1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2),
        note="How long Zap lasts; too long may harm the seal.",
        # help (25 µs to 50 ms), the TestBed's list; snapped to the list, seen on a 700B
    ),
    # the I-Clamp tab
    Setting(
        "Pipette Capacitance Neutralization", "NeutralizationCap", "float", (IC,),
        unit={IC: "pF"}, enable="NeutralizationEnable",
        note="Partly cancels the pipette's capacitance while its checkbox is on. Too much oscillates and can kill the "
        "cell: start at 0 pF.",
        # help (Pipette Capacitance)
    ),
    Setting(
        "Bridge Balance", "BridgeBalResist", "float", (IC,),
        unit={IC: "MΩ"}, resolution={IC: 3e5}, enable="BridgeBalEnable",
        note="Subtracts the electrode's voltage drop from Membrane Potential, for the electrode resistance given, while "
        "its checkbox is on; set Pipette Capacitance Neutralization first.",
        # help; seen on a 700B: refused in V-Clamp, and 10 MΩ read 9.768 MΩ at 5 GΩ
    ),
    Setting(
        "Buzz Duration", "BuzzDuration", "float", (IC, I0),
        unit={IC: "ms", I0: "ms"}, limits={IC: (5e-5, 0.5), I0: (5e-5, 0.5)},
        note="How long Buzz lasts, one of Commander's steps from 50 µs to 500 ms (ommm checks the range, not the "
        "steps); too long can kill small cells.",
        # the manual, help
    ),
    # both tabs' outputs
    Setting(
        "Primary Output", "PrimarySignal", "enum", ALL_MODES,
        choices=tuple("PRI_SIGNAL_" + name for name in PRIMARY_SIGNALS.values()), telegraph="uScaledOutSignal",
        note="The signal on the PRIMARY output, from the shown tab's list. Choosing one brings back that signal's own "
        "gain, filters, Output Zero and Leak Subtraction.",
        # help (Conditioned Output); the per-signal values seen on a 700B
    ),
    Setting(
        "Primary Output Gain", "PrimarySignalGain", "float", ALL_MODES,
        unit=every_mode("x"), choices=(1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0),
        telegraph="dAlpha",
        note="Gain after the filters, on the PRIMARY output.",
        # the manual, help; snapped to the list, seen on a 700B
    ),
    Setting(
        "Primary Output Lowpass Filter", "PrimarySignalLPF", "float", ALL_MODES,
        unit=every_mode("kHz"),
        choices=(*(float(hz) for hz in sorted(PRIMARY_CUTOFFS["bessel"] | PRIMARY_CUTOFFS["butterworth"])), BYPASS_HZ),
        telegraph="dLPFCutoff",
        note="The four-pole lowpass cutoff, or Bypass (100 kHz). The cutoffs depend on the filter type, Bessel or "
        "Butterworth (Options > General), which the API cannot read: ommm takes a cutoff from either list, and "
        "Commander keeps the nearest one the active type has.",
        # the manual, help; snapped to the Bessel list, a Butterworth-only 2.1 kHz included, seen on a 700B
    ),
    Setting(
        "AC (Highpass Filter)", "PrimarySignalHPF", "float", ALL_MODES,
        unit=every_mode("Hz"), choices=(0.0, 0.1, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0),
        note="Highpass filter on the Primary Output; 0 Hz is DC, the filter bypassed.",
        # the manual, help, the TestBed's list; 0 shows as DC, seen on a 700B
    ),
    Setting(
        "Scope Filter", "ScopeSignalLPF", "float", ALL_MODES,
        unit=every_mode("kHz"), choices=(0.0, 1e3, 3e3, 1e4),
        note="Extra lowpass filter on the SCOPE output only: 1, 3 or 10 kHz, or Bypass, for which ommm has no API "
        "value. A signal never given a Scope Filter reads 0, and Commander takes 0 back.",
        # the manual, help; seen on a 700B: a signal never given a Scope Filter reads 0, and a Set of 0 reads 0
    ),
    Setting(
        "Output Zero", "OutputZeroAmplitude", "float", ALL_MODES,
        unit=every_mode("mV"), limits=every_mode((-2.9, 2.9)), resolution=every_mode(4e-5), enable="OutputZeroEnable",
        note="A constant offset taken off the Primary Output while its checkbox is on: ±2900 mV at a Primary Output "
        "Gain below 10, ±290 mV from 10. The API's value reads 10 times larger below gain 10 than from 10. Kept per "
        "Primary Output signal.",
        # help; seen on a 700B: tenfold below gain 10, kept per primary signal, and 1 mV read 1.0038 mV at gain 10;
        # guesses: 10.038 mV below gain 10, the same step read tenfold, and V-Clamp's resolution in I-Clamp and I = 0
    ),
    Setting(
        "Secondary Output", "SecondarySignal", "enum", ALL_MODES,
        choices=tuple("SEC_SIGNAL_" + name for name in SECONDARY_SIGNALS.values()), telegraph="uRawOutSignal",
        note="The signal on the SECONDARY output, from the shown tab's list; I-Clamp's list differs from the Primary "
        "Output's.",
        # help (Raw Output)
    ),
    Setting(
        "Secondary Output Gain", "SecondarySignalGain", "float", ALL_MODES,
        unit=every_mode("x"), choices=(1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0), telegraph="dSecondaryAlpha",
        note="Gain after the filter, on the SECONDARY output. It stays when the Primary Output signal changes.",
        # the manual, help; stays when the primary signal changes, seen on a 700B
    ),
    Setting(
        "Secondary Output Lowpass Filter", "SecondarySignalLPF", "float", ALL_MODES,
        unit=every_mode("kHz"), choices=(1e4, BYPASS_HZ), telegraph="dSecondaryLPFCutoff",
        note="10 kHz single-pole Bessel, or Bypass (100 kHz), which Commander says filters at 30 kHz.",
        # the manual, help, the TestBed's list
    ),
    Setting(
        "Pulse Amplitude", "PulseAmplitude", "float", (VC, IC),
        unit={VC: "mV", IC: "pA"}, limits={VC: (-1.0, 1.0)}, rf_limit_v=10.0,
        note="The step that Pulse sends.",
        # the manual (±1 V; I-Clamp ±10 V/Rf), help
    ),
    Setting(
        "Pulse Duration", "PulseDuration", "float", (VC, IC),
        unit={VC: "ms", IC: "ms"}, limits={VC: (1e-4, 0.5), IC: (1e-4, 0.5)},
        note="How long Pulse lasts, one of Commander's steps from 0.1 to 500 ms (ommm checks the range, not the "
        "steps).",
        # the manual, help
    ),
    # not settable through the API
    Setting(
        "Feedback Resistor", "FeedbackResistor", "enum", ALL_MODES,
        unit=every_mode("MΩ"), choices=tuple(FEEDBACK_RESISTORS.values()), route="mcc", mcc_key="ELCTRD_HSTAGE_RST_RNG",
        note="The headstage's range, Rf, on Options > Gains, one per tab: 50 MΩ, 500 MΩ, 5 GΩ or, in V-Clamp only, "
        "50 GΩ. Read per tab as an index into these (FeedbackResistorVC1 and IC1, on headstage 2 VC2 and IC2); changed only by "
        "restarting Commander with a .mcc file, load_config, about 15 s without Commander (docs/mcc.md).",
        # the header (getters only), help (Options > Gains); the indexes and the .mcc key seen on a 700B
    ),
    # actions: Commander's buttons. Their parameters are the settings above, set first.
    Setting(
        "Zap", "Zap", "action", (VC,),
        note="A +1 V pulse for the Zap Duration, to break into the cell from a seal. Zap sends a Sync Output.",
        # the manual, help
    ),
    Setting(
        "Buzz", "Buzz", "action", (IC, I0),
        note="A strong 10 kHz current for the Buzz Duration, to help the pipette through the membrane or clear its "
        "tip; too long can kill small cells.",
        # the manual, help; offered in I = 0, seen on a 700B
    ),
    Setting(
        "Clear +", "ClearPlus", "action", (IC, I0),
        note="A large depolarizing current step, to clear a blocked pipette or help it into a cell.",
        # the manual, help (Clear); offered in I = 0, seen on a 700B
    ),
    Setting(
        "Clear -", "ClearMinus", "action", (IC, I0),
        note="A large hyperpolarizing current step, Clear + the other way.",
        # the manual, help (Clear); offered in I = 0, seen on a 700B
    ),
    Setting(
        "Pulse", "Pulse", "action", (VC, IC),
        note="One command step of the Pulse Amplitude, for the Pulse Duration. Pulse sends a Sync Output.",
        # help
    ),
    Setting(
        "Auto Pipette Offset", "AutoPipetteOffset", "action", ALL_MODES,
        note="Zeroes Pipette Offset in the bath and locks its padlock, which only a click in Commander opens. It also "
        "changes the other tab: pressed in V-Clamp the I-Clamp offset, in I-Clamp the V-Clamp offset (with nothing "
        "attached, V-Clamp's Holding).",
        # help; changes both tabs, seen on a 700B and on the model cell; blocks until done, 1.6-1.8 s on a 700B and
        # 1.55-1.63 s on the model cell
    ),
    Setting(
        "Auto Cp Fast", "AutoFastComp", "action", (VC,),
        note="Measures and sets Cp Fast Capacitance and Tau with test pulses, whose size is set in Options > Advanced.",
        # help (Ce Fast); blocks until done, 1.3-1.4 s on a 700B and 1.2-1.8 s on the model cell
    ),
    Setting(
        "Auto Cp Slow", "AutoSlowComp", "action", (VC,),
        note="Measures and sets Cp Slow Capacitance and Tau, and Tau x20 as needed, with test pulses.",
        # help (Ce Slow); 0.71-0.73 s on the model cell
    ),
    Setting(
        "Auto Whole Cell", "AutoWholeCellComp", "action", (VC,),
        note="Measures Whole Cell Cm and Rs and turns Whole Cell on. Commander's window offers it only at 50 and 500 "
        "MΩ, and ommm refuses it at the others.",
        # help; runs through the API at 5 GΩ, 0.88 s, seen on a 700B; on the model cell's 33 pF and 10 MΩ it found 57 pF
        # and 1.4 MΩ
    ),
    Setting(
        "Auto Output Zero", "AutoOutputZero", "action", ALL_MODES,
        note="Measures the Primary Output's offset for about 70 ms, sets Output Zero to it and turns it on.",
        # help; 0.21-0.25 s on a 700B, 0.20-0.24 s on the model cell
    ),
    Setting(
        "Auto Leak Subtraction", "AutoLeakSub", "action", (VC,),
        note="Measures the seal resistance, sets Leak Subtraction to it and turns it on.",
        # help; 2.2 s on the model cell
    ),
    Setting(
        "Auto Bridge Balance", "AutoBridgeBal", "action", (IC,),
        note="Measures the electrode resistance with a test pulse, sets Bridge Balance to it and turns it on. Fails if "
        "the load is over five times the feedback resistor.",
        # help; refused in V-Clamp, seen on a 700B; 0.63-0.66 s on the model cell
    ),
    Setting(
        "Reset to Program Defaults", "Reset", "action", ALL_MODES,
        note="Sets every control on both tabs back to Commander's defaults. ommm refuses it: press it in Commander's "
        "window, since its confirm dialog would block every call until clicked.",
        # help (Set to Factory Defaults); the dialog blocking the API is a guess from other projects, not tried
    ),
)

# The header's functions that are in no row, each with the reason
NOT_COVERED = (
    ("CheckAPIVersion", "setup: ommm.Amplifier() checks the DLL against its header"),
    ("CreateObject", "setup: ommm.Amplifier() makes its one handle, reconnect() a new one"),
    ("DestroyObject", "setup: Commander.close() frees it"),
    ("SetTimeOut", "setup: the wait for Commander's answer, 3 s, set once on each handle"),
    ("FindFirstMultiClamp", "setup: finds the headstage asked for (1 or 2) of the one 700B"),
    ("FindNextMultiClamp", "setup: finds the headstage asked for (1 or 2) of the one 700B"),
    ("SelectMultiClamp", "setup: selects the headstage, and brings its active mode's tab to the front"),
    ("BuildErrorText", "setup: Commander's words for an error code"),
    ("GetFeedbackResistorVC1", "read into headstage 1's snapshot, as the Feedback Resistor row's index in V-Clamp; no setter"),
    ("GetFeedbackResistorIC1", "read into headstage 1's snapshot, as the Feedback Resistor row's index in I-Clamp; no setter"),
    ("GetFeedbackResistorVC2", "read into headstage 2's snapshot, as the Feedback Resistor row's index in V-Clamp; no setter"),
    ("GetFeedbackResistorIC2", "read into headstage 2's snapshot, as the Feedback Resistor row's index in I-Clamp; no setter"),
    ("GetMeterValue", "the four meters, two per headstage: live readings in the snapshot, not a control"),
    ("QuickSelectButton", "not supported: it loads whatever .mcc file the button was given; ommm restarts Commander with one"),
    ("ToggleAlwaysOnTop", "Commander's window only, with no getter to tell its state"),
    ("ToggleResize", "Commander's window only, with no getter to tell its state"),
)

# Commander's checkboxes, as (the name on Commander's window, the API name, the modes it is in): enable() takes either
# name. TestSignalEnable is Seal Test in V-Clamp and Tuning in I-Clamp. A row with a checkbox names its API name in
# `enable`; a bool row is its own checkbox.
CHECKBOXES = (
    ("Mode Switching", "ModeSwitchEnable", ALL_MODES),
    ("Resistance Meter", "MeterResistEnable", (VC, IC)),
    ("Irms Meter", "MeterIrmsEnable", (VC,)),
    ("Holding", "HoldingEnable", (VC, IC)),
    ("Seal Test", "TestSignalEnable", (VC,)),
    ("Tuning", "TestSignalEnable", (IC,)),
    ("Slow Current Injection", "SlowCurrentInjEnable", (IC,)),
    ("Cp Slow Tau x20", "SlowCompTauX20Enable", (VC,)),
    ("Whole Cell", "WholeCellCompEnable", (VC,)),
    ("Rs Compensation", "RsCompEnable", (VC,)),
    ("Disable/Reduce if Oscillation Detected", "OscKillerEnable", (VC, IC)),
    ("Leak Subtraction", "LeakSubEnable", (VC,)),
    ("Pipette Capacitance Neutralization", "NeutralizationEnable", (IC,)),
    ("Bridge Balance", "BridgeBalEnable", (IC,)),
    ("Output Zero", "OutputZeroEnable", ALL_MODES),
)

# other names a call takes for a row or a checkbox, in any case: the window's own words beside a checkbox among them
ALIASES = {
    "Oscillation Killer": "Disable/Reduce if Oscillation Detected",
    "Ext": "Mode Switching",
    "Resistance": "Resistance Meter",
    "Irms": "Irms Meter",
    "Tau x20": "Cp Slow Tau x20",
}


def unaliased(name: str) -> str:
    """The name an alias stands for, in lower case; any other name in lower case."""
    aliases = {alias.lower(): label for alias, label in ALIASES.items()}
    return aliases.get(str(name).lower(), str(name)).lower()


def find(name: str, mode: str | None = None) -> Setting:
    """The row for Commander's label, an MCCMSG stem or an alias, in any case ("holding", "RsCompCorrection",
    "Ext"). The mode only picks between the rows that share a stem: TestSignalAmplitude is Seal Test Amplitude in
    V-Clamp and Tuning Amplitude in I-Clamp. Any other row comes back whatever the mode: check row.modes. A name
    close to a label, an alias or a checkbox's name is offered in the refusal."""
    key = unaliased(name)
    for row in SETTINGS:
        if row.label.lower() == key:
            return row
    rows = [row for row in SETTINGS if row.stem.lower() == key]
    if not rows:
        names = [row.label for row in SETTINGS] + list(ALIASES) + [label for label, _, _ in CHECKBOXES]
        labels = {label.lower(): label for label in names}
        close = difflib.get_close_matches(str(name).lower(), labels, n=1)
        hint = f": did you mean {labels[close[0]]!r}?" if close else "."
        raise ValueError(f"{name!r} is not a Commander control ommm knows{hint} Every label: docs/coming-from-commander.md")
    if len(rows) == 1:
        return rows[0]
    in_mode = [row for row in rows if mode in row.modes]
    if not in_mode:
        labels = " or ".join(repr(row.label) for row in rows)
        raise ValueError(f"{name} is {labels}: " + (f"neither is in {mode}" if mode else "give the mode"))
    return in_mode[0]


def checkboxes_named(name: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """The CHECKBOXES a name gives, by the window's name, the API name or an alias, in any case: two for
    TestSignalEnable, none for a name that is no checkbox's."""
    key = unaliased(name)
    return [entry for entry in CHECKBOXES if key in (entry[0].lower(), entry[1].lower())]


def checkbox(name: str, mode: str) -> tuple[str, str]:
    """A checkbox in a mode, as (its name on Commander's window, its API name), by either or an alias, in any case:
    "Seal Test", "Cp Slow Tau x20", "Ext", "TestSignalEnable"."""
    found = [(label, stem) for label, stem, modes in checkboxes_named(name) if mode in modes]
    if not found:
        raise ValueError(f"Commander's window has no {name} checkbox in {mode}")
    return found[0]


def checkbox_modes(name: str) -> list[str]:
    """The modes with a checkbox by this name on Commander's window or its API name; none for any other name."""
    return [mode for mode in ALL_MODES if any(mode in modes for _, _, modes in checkboxes_named(name))]


def checkbox_label(name: str, mode: str | None = None) -> str | None:
    """The window's name for a checkbox by either name: in the mode, else in the first mode that has it; None for any
    other name."""
    found = sorted(checkboxes_named(name), key=lambda entry: mode not in entry[2])
    return found[0][0] if found else None


def checkbox_name(row: Setting, mode: str) -> str | None:
    """The name enable() takes for a row's checkbox in a mode: a bool row's own label (Cp Slow Tau x20), else the
    checkbox its `enable` names (Seal Test Amplitude: Seal Test). None where the row has no checkbox in that mode."""
    if mode not in row.modes:
        return None
    return next((label for label, stem, modes in CHECKBOXES if stem == (row.enable or row.stem) and mode in modes), None)


def checkbox_names(mode: str) -> list[str]:
    """The names enable() takes in a mode, as the window shows them, in the table's order."""
    return [label for label, _, modes in CHECKBOXES if mode in modes]


def signal_id(row: Setting, mode: str, name: str) -> int:
    """An output signal's API id by Commander's name for it on the mode's tab, in any case: "Membrane Current"."""
    tab = tab_for(mode)
    signals = PRIMARY_SIGNALS if row.stem == "PrimarySignal" else SECONDARY_SIGNALS
    offered = {SIGNAL_NAMES[api.removeprefix(SIGNAL_PREFIX[tab])]: signal for signal, api in signals.items() if api.startswith(SIGNAL_PREFIX[tab])}
    found = {each.lower(): signal for each, signal in offered.items()}.get(str(name).lower())
    if found is None:
        raise ValueError(f"{row.label} on the {tab} tab is one of {', '.join(offered)}; not {name!r}")
    return found


def signal_name(row: Setting, signal: int) -> str:
    """Commander's name for an output signal's API id: 0 on the Primary Output is "Membrane Current"."""
    signals = PRIMARY_SIGNALS if row.stem == "PrimarySignal" else SECONDARY_SIGNALS
    return SIGNAL_NAMES[signals[signal][3:]]


def to_api(row: Setting, mode: str, value: float, unit: str) -> float:
    """A value in a unit (-60, "mV") as the API takes it for the row in that mode: SI, negated where the API's sign
    is the panel's opposite. A unit ommm does not know, or not of the row's kind (pA for a voltage), is refused with
    the units of that kind (units_wanted); no unit is asked for one."""
    expected = row.unit.get(mode)
    if not expected:
        raise ValueError(f"{row.label} takes no unit in {mode}")
    kind = UNITS[expected][0]
    found = known_unit(unit)
    if found is None or found[0] != kind:
        raise ValueError(f"{row.label} in {mode} is a {kind}: {units_wanted(kind, expected, unit)}")
    return float(value) * found[1] * row.sign.get(mode, 1)
