import copy
import json
from pathlib import Path

import pytest

import ommm
from ommm import Amplifier, WriteError
from ommm.state import state
from ommm.testing import FakeCommander

VCLAMP = ommm.EXAMPLES / "fake" / "vclamp.json"

# The "before" snapshot of a break-in trial (V-Clamp at 500 MΩ): the telegraph's
# secondary fields are stale (index 0, 0.5 V/nA, the primary's); the API says Vm
GLITCHED = json.loads((Path(__file__).parent / "data" / "vclamp_stale_secondary_telegraph.json").read_text())

# The same snapshot with the secondary fields the telegraph sent earlier that day (index 11, 10 V/V)
CONSISTENT = copy.deepcopy(GLITCHED)
CONSISTENT["telegraph"] |= {
    "uRawOutSignal": 11,
    "dRawScaleFactor": 10.0,
    "uRawScaleFactorUnits": 0,
    "RawOutSignalName": "Membrane Potential",
    "RawScaleFactorUnitsName": "VOLTS_PER_VOLT",
}

VCLAMP_500M = {
    "mode": "V-Clamp",
    "feedback_resistor": 500e6,
    "primary": {
        "signal": "Membrane Current", "api_name": "VC_MEMBCURRENT", "gain": 2, "scale": 500e6, "units": "V/A", "lpf": 2000,
        "trusted": True,
    },
    "secondary": {
        "signal": "Membrane Potential", "api_name": "VC_MEMBPOTENTIAL", "gain": 5, "scale": 10, "units": "V/V", "lpf": 10000,
        "trusted": True,
    },
    "ext_cmd_sensitivity": 0.02,
    "ext_cmd_units": "V/V",
    "membrane_capacitance": 0,
    "blocking": [],
    "problems": [],
    "warnings": [],
}


def edited(readings: dict | None = None, telegraph: dict | None = None, base: dict = CONSISTENT) -> dict:
    snapshot = copy.deepcopy(base)
    snapshot["readings"] |= readings or {}
    snapshot["telegraph"] |= telegraph or {}
    return snapshot


def iclamp(resistor_index: int, gain: float = 1, sens: float = 4e-10) -> dict:
    """CONSISTENT switched to I-Clamp with Vm primary and Im secondary."""
    resistor_gohm = {0: 0.05, 1: 0.5, 2: 5}[resistor_index]
    return edited(
        {
            "Mode": 1, "ModeName": "ICLAMP", "FeedbackResistorIC1": resistor_index,
            "PrimarySignal": 7, "PrimarySignalName": "IC_MEMBPOTENTIAL", "PrimarySignalGain": gain,
            "SecondarySignal": 8, "SecondarySignalName": "IC_MEMBCURRENT", "SecondarySignalGain": gain,
            "PrimarySignalLPF": 24000.0,
        },
        {
            "uOperatingMode": 1, "OperatingModeName": "ICLAMP", "dExtCmdSens": sens,
            "uScaledOutSignal": 20, "ScaledOutSignalName": "Membrane Potential",
            "dScaleFactor": 10.0, "uScaleFactorUnits": 0, "ScaleFactorUnitsName": "VOLTS_PER_VOLT",
            "dAlpha": gain, "dLPFCutoff": 24000.0,
            "uRawOutSignal": 31, "RawOutSignalName": "Membrane Current",
            "dRawScaleFactor": resistor_gohm, "uRawScaleFactorUnits": 6, "RawScaleFactorUnitsName": "VOLTS_PER_NANOAMP",
            "dSecondaryAlpha": gain,
        },
    )


def test_consistent_snapshot():
    assert state(CONSISTENT) == VCLAMP_500M


def test_stale_secondary_telegraph_is_a_warning_and_the_table_scales_it():
    found = state(GLITCHED)
    (warning,) = found["warnings"]
    assert warning.startswith("secondary signal: API VC_MEMBPOTENTIAL is telegraph index 11, but the telegraph sent index 0")
    assert found["secondary"] == VCLAMP_500M["secondary"]  # the table scales it; the telegraph only warns
    assert found["primary"] == VCLAMP_500M["primary"]
    assert (found["blocking"], found["problems"]) == ([], [])


def test_the_other_mode_tab_showing_is_blocking():
    # in V-Clamp with Commander's I-Clamp 1 tab showing, the API read that tab
    found = state(edited({
        "PrimarySignal": 7, "PrimarySignalName": "IC_MEMBPOTENTIAL",
        "SecondarySignal": 14, "SecondarySignalName": "IC_AUXILIARY2",
        "PrimarySignalLPF": 24000.0, "SecondarySignalGain": 2.0,
    }))
    (blocking,) = found["blocking"]
    assert blocking.startswith("tab: Commander is showing the I-Clamp tab while the amplifier is in V-Clamp")
    assert blocking.endswith("click the V-Clamp tab in Commander and read again")
    assert found["mode"] == "V-Clamp"


def test_api_and_telegraph_mode_mismatch_is_blocking():
    found = state(edited(telegraph={"uOperatingMode": 1, "OperatingModeName": "ICLAMP"}))
    assert "mode: API 0, telegraph 1" in found["blocking"]
    assert found["mode"] == "I-Clamp"  # the telegraph's, the packet the sensitivity came from
    assert found["feedback_resistor"] == 5e9  # FeedbackResistorIC1, chosen by the telegraph mode


@pytest.mark.parametrize("resistor_index, resistor, sens", [(1, 500e6, 4e-10), (2, 5e9, 2e-10)])
@pytest.mark.parametrize("gain", [1, 2])
def test_iclamp(resistor_index, resistor, sens, gain):
    found = state(iclamp(resistor_index, gain, sens))
    assert found == {
        "mode": "I-Clamp",
        "feedback_resistor": resistor,
        "primary": {
            "signal": "Membrane Potential", "api_name": "IC_MEMBPOTENTIAL", "gain": gain, "scale": 10, "units": "V/V", "lpf": 24000,
            "trusted": True,
        },
        "secondary": {
            "signal": "Membrane Current", "api_name": "IC_MEMBCURRENT", "gain": gain, "scale": resistor, "units": "V/A", "lpf": 10000,
            "trusted": True,
        },
        "ext_cmd_sensitivity": sens,
        "ext_cmd_units": "A/V",
        "membrane_capacitance": 0,
        "blocking": [],
        "problems": [],
        "warnings": [],
    }


def test_50_mohm_in_both_modes():
    vclamp = state(edited({"FeedbackResistorVC1": 0}, {"dScaleFactor": 0.05}))
    assert (vclamp["feedback_resistor"], vclamp["primary"]["scale"], vclamp["primary"]["units"]) == (50e6, 50e6, "V/A")
    assert vclamp["problems"] == []

    iclamp_state = state(iclamp(0, sens=4e-9))
    assert (iclamp_state["feedback_resistor"], iclamp_state["secondary"]["scale"]) == (50e6, 50e6)
    assert (iclamp_state["ext_cmd_sensitivity"], iclamp_state["ext_cmd_units"]) == (4e-9, "A/V")
    assert iclamp_state["problems"] == []


def test_50_gohm_in_vclamp():
    # Commander showing Rf 50 GΩ, telegraph 0.05 V/pA (units index 7)
    found = state(edited({"FeedbackResistorVC1": 3}, {"dScaleFactor": 0.05, "uScaleFactorUnits": 7}))
    assert (found["feedback_resistor"], found["primary"]["scale"], found["primary"]["trusted"]) == (50e9, 50e9, True)
    assert found["problems"] == []


def test_auxiliary_secondary_has_no_scale_but_is_not_a_scaling_problem():
    # on a 700B: VC secondary Auxiliary 2 with nothing on the aux input -> telegraph 44
    snapshot = edited(
        {"SecondarySignal": 6, "SecondarySignalName": "VC_AUXILIARY2"},
        {"uRawOutSignal": 44, "RawOutSignalName": None, "dRawScaleFactor": 0.0},
    )
    found = state(snapshot)
    assert found["secondary"] == {
        "signal": "Auxiliary 2", "api_name": "VC_AUXILIARY2", "gain": 5, "scale": None, "units": None, "lpf": 10000,
        "trusted": False,
    }
    assert (found["problems"], found["warnings"]) == ([], [])  # the pairing is the caller's to check


def test_iclamp_command_current_secondary_scales_with_the_resistor():
    snapshot = iclamp(2, gain=2, sens=2e-10)
    snapshot["readings"] |= {"SecondarySignal": 9, "SecondarySignalName": "IC_CMDCURRENT"}
    found = state(snapshot)
    assert found["secondary"] == {
        "signal": "Command Current", "api_name": "IC_CMDCURRENT", "gain": 2, "scale": 5e9, "units": "V/A", "lpf": 10000,
        "trusted": True,
    }
    assert found["problems"] == []
    # no telegraph index is known for a Command Current secondary, so only the table scales it
    assert found["warnings"] == [
        "secondary signal: no telegraph index is known for IC_CMDCURRENT, so its secondary scale and units are not checked"
    ]


# the other rows of the scale table, with the telegraph scale a 700B gave for each (External Command
# Current at 40 pA/V): an external command's is 1 / the external command sensitivity
@pytest.mark.parametrize("mode, sens, api_id, api_name, telegraph_index, telegraph_scale, units_index, scale, units", [
    ("V-Clamp", 0.02, 2, "VC_PIPPOTENTIAL", 2, 1.0, 0, 1, "V/V"),
    ("V-Clamp", 0.02, 3, "VC_100XACMEMBPOTENTIAL", 3, 100.0, 0, 100, "V/V"),
    ("V-Clamp", 0.02, 4, "VC_EXTCMDPOTENTIAL", 4, 50.0, 0, 50, "V/V"),  # 20 mV/V
    ("I-Clamp", 2e-10, 11, "IC_EXTCMDCURRENT", 24, 5.0, 6, 5e9, "V/A"),  # 200 pA/V at 5 GΩ, the feedback resistor's
    ("I-Clamp", 4e-11, 11, "IC_EXTCMDCURRENT", 24, 25.0, 6, 2.5e10, "V/A"),  # 40 pA/V at 5 GΩ
    ("I-Clamp", 4e-11, 9, "IC_CMDCURRENT", 22, 5.0, 6, 5e9, "V/A"),
])
def test_other_primary_signals_scale_from_the_table(mode, sens, api_id, api_name, telegraph_index, telegraph_scale, units_index, scale, units):
    snapshot = iclamp(2, sens=sens) if mode == "I-Clamp" else edited(telegraph={"dExtCmdSens": sens})
    snapshot["readings"] |= {"PrimarySignal": api_id, "PrimarySignalName": api_name}
    snapshot["telegraph"] |= {"uScaledOutSignal": telegraph_index, "dScaleFactor": telegraph_scale, "uScaleFactorUnits": units_index}
    found = state(snapshot)
    assert (found["primary"]["api_name"], found["primary"]["scale"], found["primary"]["units"]) == (api_name, scale, units)
    assert found["primary"]["trusted"]
    assert (found["problems"], found["warnings"]) == ([], [])


def test_unrecognised_feedback_resistor_index_is_blocking():
    found = state(edited({"FeedbackResistorVC1": 4}))
    assert found["blocking"] == ["feedback resistor: FeedbackResistorVC1 = 4 is not a range index (0..3)"]
    assert found["feedback_resistor"] is None
    assert (found["primary"]["scale"], found["primary"]["units"], found["primary"]["trusted"]) == (None, None, False)
    assert found["secondary"]["trusted"]


@pytest.mark.parametrize("key", ["ModeName", "PrimarySignalName", "SecondarySignalName"])
def test_a_name_the_header_could_not_resolve_is_blocking(key):
    # commander.py writes readings[...Name] = None when the ID matches no header constant
    assert state(edited({key: None}))["blocking"] == [f"incomplete snapshot: no {key}"]


@pytest.mark.parametrize("telegraph", [None, []])  # [] is a null written back by MATLAB's jsonencode
def test_no_telegraph_is_blocking_and_the_mode_comes_from_the_api(telegraph):
    # as in Commander's Demo mode: the mode and feedback resistor are the API's, the rest unknown
    snapshot = edited()
    snapshot["telegraph"] = telegraph
    found = state(snapshot)
    assert found["blocking"] == ["incomplete snapshot: no telegraph"]
    assert (found["mode"], found["feedback_resistor"]) == ("V-Clamp", 500e6)
    assert (found["ext_cmd_sensitivity"], found["membrane_capacitance"]) == (None, None)
    assert found["primary"] == {
        "signal": "Membrane Current", "api_name": "VC_MEMBCURRENT", "gain": None, "scale": 500e6, "units": "V/A", "lpf": None,
        "trusted": True,
    }
    assert (found["secondary"]["scale"], found["secondary"]["units"], found["secondary"]["trusted"]) == (10, "V/V", True)


@pytest.mark.parametrize("telegraph", [None, []])
def test_no_telegraph_in_a_saved_file_blocks_through_the_fake_too(tmp_path, telegraph):
    timeout = "no telegraph from Commander for headstage 1 within 1 s"
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(json.loads(VCLAMP.read_text()) | {"telegraph": telegraph, "errors": {"telegraph": timeout}}))
    fake = FakeCommander(path)
    served = fake.snapshot()
    assert (served["telegraph"], served["errors"]) == (None, {"telegraph": timeout})
    assert state(served)["blocking"] == ["incomplete snapshot: no telegraph"]
    with pytest.raises(WriteError, match="^the mode cannot be checked: no telegraph from Commander for headstage 1 within 1 s$"):
        Amplifier(log_dir=tmp_path, commander=fake).set("Holding", -10, "mV")


def test_a_dict_with_matlab_empties_serves_as_its_python_twin():
    def served(snapshot: dict) -> dict:
        taken = FakeCommander(snapshot).snapshot()
        return {key: taken[key] for key in ("readings", "telegraph", "not_applicable", "errors")}

    python = json.loads(VCLAMP.read_text()) | {"telegraph": None, "errors": {}, "not_applicable": {}}
    matlab = python | {"telegraph": [], "errors": [], "not_applicable": []}  # json.load of a file jsonencode wrote
    assert served(matlab) == served(python)


def test_without_telegraph_or_mode_reading_the_feedback_resistor_is_unknown():
    snapshot = edited()
    snapshot["telegraph"] = None
    readings = {key: value for key, value in snapshot["readings"].items() if key not in ("Mode", "ModeName")}
    found = state(snapshot | {"readings": readings})
    assert found["blocking"] == ["incomplete snapshot: no telegraph, ModeName"]
    assert (found["mode"], found["feedback_resistor"]) == (None, None)


def test_missing_mode_name_is_blocking_and_the_rest_stands():
    snapshot = edited()
    readings = {key: value for key, value in snapshot["readings"].items() if key not in ("Mode", "ModeName")}
    found = state(snapshot | {"readings": readings})
    assert found["blocking"] == ["incomplete snapshot: no ModeName"]
    assert found | {"blocking": []} == VCLAMP_500M


def test_gain_disagreement_makes_that_output_untrusted():
    found = state(edited(telegraph={"dAlpha": 5.0}))
    assert found["problems"] == ["primary gain: API 2, telegraph 5"]
    assert (found["primary"]["gain"], found["primary"]["scale"], found["primary"]["trusted"]) == (5, 500e6, False)
    assert found["secondary"]["trusted"]


def test_table_and_telegraph_scale_mismatch_makes_that_output_untrusted():
    found = state(edited(telegraph={"dRawScaleFactor": 20.0}))
    assert found["problems"] == ["secondary scale: table 10 V/V, telegraph 20 V/V (units index 0)"]
    assert (found["secondary"]["scale"], found["secondary"]["trusted"]) == (10, False)
    assert found["primary"]["trusted"]


def test_sensitivity_zero_in_vclamp_is_a_problem():
    found = state(edited(telegraph={"dExtCmdSens": 0.0}))
    assert found["problems"] == ["external command sensitivity: 0 (off) in V-Clamp, so an external command does nothing"]
    assert (found["ext_cmd_sensitivity"], found["ext_cmd_units"]) == (0, "V/V")


def test_an_external_command_signal_with_the_sensitivity_off_has_no_scale():
    snapshot = edited({"PrimarySignal": 4, "PrimarySignalName": "VC_EXTCMDPOTENTIAL"}, {"dExtCmdSens": 0.0})
    found = state(snapshot)
    assert (found["primary"]["scale"], found["primary"]["trusted"]) == (None, False)
    assert "primary signal: VC_EXTCMDPOTENTIAL scales by the external command sensitivity, which is 0 (off)" in found["problems"]


def test_i_equals_0():
    snapshot = iclamp(2, gain=2, sens=0.0)
    snapshot["readings"] |= {"Mode": 2, "ModeName": "ICLAMPZERO"}
    snapshot["telegraph"] |= {"uOperatingMode": 2, "OperatingModeName": "ICLAMPZERO"}
    found = state(snapshot)
    assert found["mode"] == "I = 0"
    assert (found["ext_cmd_sensitivity"], found["ext_cmd_units"]) == (0, None)
    assert (found["primary"]["units"], found["secondary"]["units"], found["feedback_resistor"]) == ("V/V", "V/A", 5e9)
    assert (found["blocking"], found["problems"], found["warnings"]) == ([], [], [])


def test_enabled_settings_and_low_pass_disagreements_are_warnings():
    snapshot = edited(
        {
            "HoldingEnable": True,
            "Holding": -0.032,
            "LeakSubEnable": True,
            "ModeSwitchEnable": True,
            "TestSignalEnable": True,
            "MeterResistEnable": True,
            "RsCompEnable": True,
        },
        {"dSecondaryLPFCutoff": 100000.0},
    )
    found = state(snapshot)
    assert found["warnings"] == [
        "secondary low-pass: API 10000, telegraph 100000",
        "Leak Subtraction is on (LeakSubEnable)",
        "Holding is on (HoldingEnable)",
        "Mode Switching is on (ModeSwitchEnable)",
        "Seal Test is on (TestSignalEnable)",
        "Resistance Meter is on, and its pulses add to the command (MeterResistEnable)",
        "Rs Compensation is on, and the Secondary Output's Membrane Potential includes its commands (RsCompEnable)",
    ]
    assert found["secondary"]["lpf"] == 100000
    assert found["problems"] == []


@pytest.mark.parametrize("mode, mode_name, warned", [
    (1, "ICLAMP", [
        "Output Zero is on (OutputZeroEnable)",
        "Holding is on (HoldingEnable)",
        "Tuning is on (TestSignalEnable)",  # by the mode's name for it
        "Slow Current Injection is on (SlowCurrentInjEnable)",
        "Resistance Meter is on, and its pulses add to the command (MeterResistEnable)",
    ]),
    (2, "ICLAMPZERO", ["Output Zero is on (OutputZeroEnable)"]),  # no Holding, Tuning, Slow Current Injection or Resistance meter
])
def test_a_checkbox_is_a_warning_only_in_a_mode_that_has_it(mode, mode_name, warned):
    # I = 0 shares the I-Clamp tab's readings, not its checkboxes
    snapshot = iclamp(2)
    on = ["HoldingEnable", "TestSignalEnable", "SlowCurrentInjEnable", "MeterResistEnable", "OutputZeroEnable"]
    snapshot["readings"] |= {"Mode": mode, "ModeName": mode_name} | dict.fromkeys(on, True)
    snapshot["telegraph"] |= {"uOperatingMode": mode, "OperatingModeName": mode_name}
    assert state(snapshot)["warnings"] == warned
