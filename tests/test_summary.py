import json
import re
from pathlib import Path

import pytest

import ommm
from ommm.state import state
from ommm.summary import primary_filter, summary

DATA = Path(__file__).parent / "data"
FAKE = ommm.EXAMPLES / "fake"  # the snapshots and the test .mcc the package ships

# the shipped snapshot: V-Clamp at 500 MΩ, the telegraph's secondary fields stale (the primary's)
GLITCHED = json.loads((DATA / "vclamp_stale_secondary_telegraph.json").read_text())

# V-Clamp at 5 GΩ, nothing attached: P07 read each tab before it began
Q8_START = json.loads((DATA / "rig" / "2026-10-23" / "p07_ext_toggle.json").read_text(encoding="utf-8"))["start"]
VCLAMP_TAB_SHOWN, ICLAMP_TAB_SHOWN = Q8_START["V-Clamp"], Q8_START["I-Clamp"]

# I-Clamp (the values Commander showed)
ICLAMP = {
    "headstage": {"model": 1, "serial": "00123456", "channel": 1},
    "readings": {
        "Mode": 1,
        "ModeName": "ICLAMP",
        "FeedbackResistorVC1": 3,
        "FeedbackResistorIC1": 2,
        "HoldingEnable": False,
        "Holding": 0.0,
        "PrimarySignal": 7,
        "PrimarySignalName": "IC_MEMBPOTENTIAL",
        "PrimarySignalGain": 2.0,
        "SecondarySignal": 8,
        "SecondarySignalName": "IC_MEMBCURRENT",
        "SecondarySignalGain": 2.0,
        "PrimarySignalLPF": 24000.0,
        "SecondarySignalLPF": 10000.0,
        "PipetteOffset": 0.0,
        "BridgeBalEnable": True,
        "BridgeBalResist": 0.0,
        "NeutralizationEnable": True,
        "NeutralizationCap": -3.331e-28,
    },
    "telegraph": {
        "uOperatingMode": 1,
        "dExtCmdSens": 2e-10,
        "uScaledOutSignal": 20,
        "ScaledOutSignalName": "Membrane Potential",
        "dScaleFactor": 10.0,
        "uScaleFactorUnits": 0,
        "ScaleFactorUnitsName": "VOLTS_PER_VOLT",
        "dAlpha": 2.0,
        "dLPFCutoff": 24000.0,
        "uRawOutSignal": 31,
        "RawOutSignalName": "Membrane Current",
        "dRawScaleFactor": 5.0,
        "uRawScaleFactorUnits": 6,
        "RawScaleFactorUnitsName": "VOLTS_PER_NANOAMP",
        "dSecondaryAlpha": 2.0,
        "dSecondaryLPFCutoff": 10000.0,
        "dMembraneCap": 0.0,
    },
    "not_applicable": {},
    "errors": {},
}


def test_failed_mode_read_shows_the_error():
    readings = {key: value for key, value in ICLAMP["readings"].items() if key not in ("Mode", "ModeName")}
    snapshot = ICLAMP | {"readings": readings, "errors": {"Mode": "GetMode: Message timed out. (6005)"}}
    text = summary(snapshot)
    assert "!! Error" in text
    assert "GetMode: Message timed out. (6005)" in text


def row(text: str, label: str) -> str:
    """What the box prints after `label:`."""
    return re.search(rf"^= {re.escape(label)}: +(.*?) +=$", text, re.MULTILINE).group(1)


def labels(text: str) -> list[str]:
    return re.findall(r"^= ([^:\n]+):", text, re.MULTILINE)


def test_iclamp_box():
    text = summary(ICLAMP, {"lpf_type_i_clamp": "bessel"})
    assert row(text, "Feedback Resistor") == "5 GΩ"
    assert "200 pA/V" in text
    assert "20 mV/mV (gain 2)" in text
    assert "10 V/nA (gain 2)" in text
    assert "24 kHz Bessel (manually set)" in text  # 24 kHz exists for both types
    assert "10 kHz single-pole Bessel (fixed)" in text


def test_tiny_capacitance_prints_as_zero():
    assert "on (0 pF)" in summary(ICLAMP)


@pytest.mark.parametrize("example, offset, shown", [
    ("iclamp.json", 0.005, "-5 mV"),  # the window shows the API's I-Clamp Pipette Offset negated (P14)
    ("i0.json", 0.005, "-5 mV"),  # I = 0 uses I-Clamp's
    ("i0.json", 0.0, "0 mV"),
    ("vclamp.json", 0.005, "5 mV"),  # V-Clamp's sign is the window's
])
def test_pipette_offset_shows_the_windows_sign(example, offset, shown):
    snapshot = json.loads((FAKE / example).read_text(encoding="utf-8"))
    snapshot["readings"]["PipetteOffset"] = offset
    assert row(summary(snapshot), "Pipette Offset") == shown


def test_whole_cell_rounds_like_commander():
    assert VCLAMP_TAB_SHOWN["readings"]["WholeCellCompCap"] == 3.296323e-11
    assert row(summary(VCLAMP_TAB_SHOWN), "Whole Cell") == "off (32.96 pF, 0.4 MΩ)"


def rig_snapshots() -> list:
    """Every start and end snapshot in the probe records, with the tab shown when it was taken (a probe that stopped
    has no end)."""
    snapshots = []
    for path in sorted((DATA / "rig").glob("*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        for when in ("start", "end"):
            snapshots += [pytest.param(snapshot, tab, id=f"{path.stem}-{when}-{tab}") for tab, snapshot in (record[when] or {}).items()]
    return snapshots


@pytest.mark.parametrize("snapshot, tab", rig_snapshots())
def test_rig_snapshots_show_settings_only_from_the_active_mode_tab(snapshot, tab):
    text = summary(snapshot)
    assert row(text, "Mode") == "V-Clamp"  # every probe starts and ends in V-Clamp
    if tab == "V-Clamp":
        assert "!!" not in text
        assert labels(text) == [
            "Headstage", "Mode", "Feedback Resistor", "Holding", "External Command Sensitivity",
            "Primary Output", "Primary Units", "Primary Output Lowpass Filter",
            "Secondary Output", "Secondary Units", "Secondary Output Lowpass Filter",
            "Pipette Offset", "Cp Fast Capacitance", "Cp Slow Capacitance", "Whole Cell", "Rs Compensation",
        ]
    else:
        # the readings are the I-Clamp tab's: no setting rows, and the Blocking line says what to do
        assert labels(text)[:3] == ["Headstage", "Mode", "!! Blocking"]
        assert all(label.startswith("!!") for label in labels(text)[2:])
        assert row(text, "!! Blocking") == (
            "tab: Commander is showing the I-Clamp tab while the amplifier is in V-Clamp: "
            "click the V-Clamp tab in Commander and read again"
        )


def test_i0_with_the_vclamp_tab_shown_has_no_setting_rows():
    # P07 left I = 0 active with the V-Clamp tab shown but took no snapshot then, so this is its
    # V-Clamp tab readings with that mode, holding -60 mV on that tab
    readings = VCLAMP_TAB_SHOWN["readings"] | {"Mode": 2, "ModeName": "ICLAMPZERO", "Holding": -0.06, "HoldingEnable": True}
    telegraph = VCLAMP_TAB_SHOWN["telegraph"] | {"uOperatingMode": 2, "OperatingModeName": "ICLAMPZERO"}
    text = summary(VCLAMP_TAB_SHOWN | {"readings": readings, "telegraph": telegraph})
    assert row(text, "Mode") == "I = 0"
    assert labels(text)[:3] == ["Headstage", "Mode", "!! Blocking"]
    assert all(label.startswith("!!") for label in labels(text)[2:])
    assert row(text, "!! Blocking").endswith("in I = 0: click the I-Clamp tab in Commander and read again")


def test_i0_shows_and_warns_of_only_what_i0_has():
    # the I-Clamp tab's Holding on at -20 pA, in I = 0, which has no Holding, Bridge Balance or Pipette
    # Capacitance Neutralization (get() refuses each there); i0.json has the Neutralization on already
    snapshot = json.loads((FAKE / "i0.json").read_text(encoding="utf-8"))
    snapshot["readings"] |= {"HoldingEnable": True, "Holding": -2e-11}
    text = summary(snapshot)
    assert labels(text) == [
        "Headstage", "Mode", "Feedback Resistor", "External Command Sensitivity",
        "Primary Output", "Primary Units", "Primary Output Lowpass Filter",
        "Secondary Output", "Secondary Units", "Secondary Output Lowpass Filter",
        "Pipette Offset",
    ]
    assert state(snapshot)["warnings"] == []


@pytest.mark.parametrize("where, why", [
    ("not_applicable", "INVALIDPARAMETER (6004)"),
    ("errors", "GetBridgeBalEnable: Command failed. (6006)"),
])
def test_a_missing_reading_says_why_once(where, why):
    readings = {key: value for key, value in ICLAMP["readings"].items() if key != "BridgeBalEnable"}
    text = summary(ICLAMP | {"readings": readings, where: {"BridgeBalEnable": why}})
    assert row(text, "!! Not read") == f"BridgeBalEnable: {why}"
    assert text.count(why) == 1
    assert "Bridge Balance" not in text


def test_primary_filter_type_from_cutoff():
    assert primary_filter(2000, "bessel") == ("2 kHz Bessel (manually set, cutoff agrees)", None)
    assert primary_filter(2000, "butterworth")[1] == "entered butterworth, but 2 kHz is bessel-only"
    assert primary_filter(2100, None) == ("2.1 kHz Butterworth (from cutoff)", None)
    assert primary_filter(24000, "bessel") == ("24 kHz Bessel (manually set)", None)
    assert primary_filter(1e5, "bessel") == ("bypass", None)


def test_box_prints_blocking_and_problems_from_state():
    mismatch = ICLAMP | {"telegraph": ICLAMP["telegraph"] | {"uOperatingMode": 0, "dAlpha": 5.0}}
    text = summary(mismatch)
    assert "!! Blocking" in text
    assert "mode: API 1, telegraph 0" in text
    assert "!! Problem" in text
    assert "primary gain: API 2, telegraph 5" in text


def test_each_fault_prints_once_without_what_it_means():
    # the I-Clamp tab showing while in V-Clamp, so its gain and outputs are not the V-Clamp tab's
    text = summary(ICLAMP_TAB_SHOWN)
    assert text.count("I-Clamp tab") == 1
    assert text.count("secondary gain") == 1
    assert "!! Problem:  secondary gain: API 2, telegraph 5 " in text
    assert ", so " not in text  # the label says what a fault means


def test_untrusted_units_print_a_question_mark():
    text = summary(GLITCHED | {"telegraph": GLITCHED["telegraph"] | {"dAlpha": 5.0}})
    assert row(text, "Primary Units") == "? (gain 2)"
    assert re.search("^= !! Problem: +primary gain: API 2, telegraph 5 ", text, re.MULTILINE)


def test_no_telegraph_box_shows_the_mode_and_resistor_state_has():
    snapshot = GLITCHED | {"telegraph": None}
    found = state(snapshot)
    assert (found["mode"], found["feedback_resistor"]) == ("V-Clamp", 500e6)
    text = summary(snapshot)
    assert (row(text, "Mode"), row(text, "Feedback Resistor")) == ("V-Clamp", "500 MΩ")
    assert row(text, "Primary Units") == "1 V/nA (gain 2)"
    assert row(text, "!! Blocking") == "incomplete snapshot: no telegraph"


def test_filter_type_as_commander_spells_it():
    text = summary(GLITCHED, {"lpf_type_v_clamp": "Bessel"})
    assert row(text, "Primary Output Lowpass Filter") == "2 kHz Bessel (manually set, cutoff agrees)"
    assert "!! Filter Type" not in text


@pytest.mark.parametrize("manual, message", [
    ({"lpf_type_vclamp": "bessel"}, "manual: unknown key ['lpf_type_vclamp']; use ['lpf_type_v_clamp', 'lpf_type_i_clamp']"),
    ({"lpf_type_v_clamp": "besel"}, "manual: unknown filter type ['besel']; use ['bessel', 'butterworth']"),
])
def test_a_manual_entry_the_box_cannot_use_is_an_error(manual, message):
    # it would otherwise be ignored without a word
    with pytest.raises(ValueError, match=re.escape(message)):
        summary(GLITCHED, manual)
