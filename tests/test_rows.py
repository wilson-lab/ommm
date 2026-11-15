"""Every row of the settings table through ommm.Amplifier on the fake: each value set, read back and read again in its
unit, each checkbox turned on and off, each button pressed in every mode, in Commander's words; then the rules of
particular rows (docs/writes.md)."""

from pathlib import Path

import re

import pytest

import ommm
from ommm import Amplifier, WriteError, amplifier
from ommm.commander import CommanderError
from ommm.settings import ALL_MODES, IC, SETTINGS, VC, checkbox_name, find, to_api
from ommm.testing import FakeCommander

from conftest import after_each_set, logged, names, refused, sets

DATA = Path(__file__).parent / "data"
FAKE = ommm.EXAMPLES / "fake"  # the snapshots and the test .mcc the package ships
VCLAMP, ICLAMP, I0 = FAKE / "vclamp.json", FAKE / "iclamp.json", FAKE / "i0.json"  # all at 5 GΩ
FILES = {VC: (VCLAMP, ICLAMP), IC: (ICLAMP, VCLAMP), "I = 0": (I0, VCLAMP)}

# a value for each row, in its first mode's unit: inside the vendor's range, and not what the fixture holds
VALUES = {
    "Holding": (-60, "mV"),
    "Seal Test Amplitude": (10, "mV"),
    "Seal Test Frequency": (50, "Hz"),
    "Tuning Amplitude": (50, "pA"),
    "Tuning Frequency": (50, "Hz"),
    "Pipette Offset": (20, "mV"),
    "Slow Current Injection Level": (-60, "mV"),
    "Slow Current Injection Settling Time": (100, "ms"),
    "Cp Fast Capacitance": (2, "pF"),
    "Cp Fast Tau": (1.5, "µs"),
    "Cp Slow Capacitance": (0.5, "pF"),
    "Cp Slow Tau": (100, "µs"),
    "Whole Cell Cm": (33, "pF"),
    "Whole Cell Rs": (10, "MΩ"),
    "Rs Compensation Bandwidth": (5, "kHz"),
    "Rs Compensation Prediction": (40, "%"),
    "Leak Subtraction": (1000, "MΩ"),
    "Zap Duration": (0.5, "ms"),
    "Pipette Capacitance Neutralization": (2, "pF"),
    "Bridge Balance": (10, "MΩ"),
    "Buzz Duration": (10, "ms"),
    "Primary Output": ("Membrane Potential", None),
    "Primary Output Gain": (10, "x"),
    "Primary Output Lowpass Filter": (10, "kHz"),
    "AC (Highpass Filter)": (1, "Hz"),
    "Scope Filter": (3, "kHz"),
    "Output Zero": (100, "mV"),
    "Secondary Output": ("Pipette Potential", None),
    "Secondary Output Gain": (10, "x"),
    "Secondary Output Lowpass Filter": (100, "kHz"),
    "Pulse Amplitude": (20, "mV"),
    "Pulse Duration": (10, "ms"),
}
# the rows set() takes by a rule of their own, each tested below or in test_amplifier.py
APART = {"Mode": "set_mode", "Feedback Resistor": "load_config", "Rs Compensation Correction": "follows Prediction"}
VALUE_ROWS = [row for row in SETTINGS if row.kind in ("float", "enum") and row.label not in APART]
CHECKBOXES = sorted({(row.modes[0], checkbox_name(row, row.modes[0])) for row in SETTINGS
                     if checkbox_name(row, row.modes[0]) and row.stem != "ModeSwitchEnable"})  # Ext: test_amplifier.py
BUTTONS = [row for row in SETTINGS if row.kind == "action" and row.stem != "Reset"]  # Reset: refused, test_amplifier.py


def amp_in(mode: str, tmp_path, snapshot=None) -> Amplifier:
    """An Amplifier on the two-tab fake in `mode`, at 5 GΩ unless `snapshot` says otherwise."""
    first, other = FILES[mode]
    return Amplifier(log_dir=tmp_path, commander=FakeCommander(snapshot or first, other_tab=other))


def at(resistor_index: int) -> dict:
    """V-Clamp's snapshot at another feedback resistor, by FeedbackResistorVC1's index: 0 is 50 MΩ, 1 500 MΩ, 3 50 GΩ."""
    saved = ommm.load_snapshot(VCLAMP)
    saved["readings"]["FeedbackResistorVC1"] = resistor_index
    return saved


def whole_cell_file(row) -> dict | None:
    """500 MΩ for the rows Commander's window greys out at 5 GΩ."""
    return at(1) if row.enable == "WholeCellCompEnable" or row.stem == "AutoWholeCellComp" else None


# every row


def test_every_value_row_has_a_value_here():
    assert {row.label for row in VALUE_ROWS} == set(VALUES)


@pytest.mark.parametrize("row", VALUE_ROWS, ids=lambda row: row.label)
def test_every_value_is_set_read_back_and_read_again_in_its_unit(tmp_path, row):
    mode = row.modes[0]
    amp = amp_in(mode, tmp_path, whole_cell_file(row))
    value, unit = VALUES[row.label]
    write = amp.set(row.label, value, unit)
    assert (write.label, write.stem, write.mode, write.outcome) == (row.label, row.stem, mode, "ok")
    assert write.after == write.target != write.before  # targets as Commander's float32 holds them
    sent = 1 / write.target if row.stem == "TestSignalFrequency" else write.target  # P21: that setter takes the period
    assert sets(amp.commander)[-1] == (f"Set{row.stem}", sent)
    assert logged(amp)[-1]["after"] == write.after
    if row.kind == "enum":
        assert amp.get(row.label) == value
    else:
        tolerance = row.resolution.get(mode, 0.0) / abs(to_api(row, mode, 1, unit))
        assert amp.get(row.label, unit) == pytest.approx(value, rel=1e-6, abs=tolerance)


@pytest.mark.parametrize("mode, name", CHECKBOXES, ids=lambda item: item)
def test_every_checkbox_is_turned_on_and_off_by_its_name_on_the_window(tmp_path, mode, name):
    amp = amp_in(mode, tmp_path, at(1) if name == "Whole Cell" else None)
    on = amp.enable(name, True)
    assert (on.mode, on.target, on.after, on.outcome) == (mode, True, True, "ok")
    assert amp.get(on.stem) is True
    off = amp.enable(name, False)
    assert (off.before, off.after) == (True, False)
    assert sets(amp.commander)[-2:] == [(f"Set{on.stem}", True), (f"Set{on.stem}", False)]


@pytest.mark.parametrize("row", BUTTONS, ids=lambda row: row.label)
def test_every_button_is_pressed_where_commander_has_it_and_refused_elsewhere(tmp_path, row):
    for mode in ALL_MODES:
        amp = amp_in(mode, tmp_path, whole_cell_file(row) if mode == VC else None)
        if mode in row.modes:
            write = amp.press(row.label)
            assert (write.stem, write.mode, write.outcome) == (row.stem, mode, "ok")
            assert [name for name in names(amp) if not name.startswith(("Get", "Select"))] == [row.stem]
            assert logged(amp)[-1]["after"] == write.after
        else:
            refused(amp, lambda: amp.press(row.label), re.escape(f"{row.label} is not in {mode}"))


# outputs, gains and filters


def test_a_primary_output_signal_brings_back_its_own_values_listed_in_also(tmp_path):
    # P10: gain, filters, Output Zero and Leak Subtraction are kept per Primary Output signal; the Secondary gain is not
    amp = amp_in(VC, tmp_path)
    amp.set("Primary Output", "Membrane Potential")
    amp.set("Primary Output Gain", 10, "x")
    amp.set("Primary Output Lowpass Filter", 2, "kHz")
    amp.set("Leak Subtraction", 500, "MΩ")
    amp.set("Secondary Output Gain", 2, "x")
    write = amp.set("Primary Output", "Membrane Current")
    assert write.also == {"PrimarySignalGain": [10.0, 2.0], "PrimarySignalLPF": [2000.0, 8000.0], "LeakSubResist": [5e8, 1.02375e9]}
    assert logged(amp)[-1]["also"] == write.also
    assert amp.get("Secondary Output Gain", "x") == 2.0
    # so set the signal first, then its gain: a gain set before goes with the signal it was set on
    amp.set("Primary Output Gain", 20, "x")
    assert amp.set("Primary Output", "Membrane Potential").also["PrimarySignalGain"] == [20.0, 10.0]


def test_the_primary_output_gain_rescales_output_zeros_api_value_listed_in_also(tmp_path):
    # P10, parity: Output Zero's API value reads 10 times larger below gain 10
    amp = amp_in(VC, tmp_path)
    amp.set("Output Zero", 100, "mV")
    assert amp.set("Primary Output Gain", 10, "x").also == {"OutputZeroAmplitude": [0.1, 0.01]}


def test_a_signal_not_on_the_tab_is_refused_by_commanders_name(tmp_path):
    amp = amp_in(IC, tmp_path)
    refused(amp, lambda: amp.set("Primary Output", "Membrane Voltage"), "Primary Output on the I-Clamp tab is one of Membrane Potential")
    assert amp.set("Secondary Output", "Pipette Potential").after == 10  # SEC IC_PIPPOTENTIAL in AxMultiClampMsg.h
    refused(amp, lambda: amp.set("Primary Output", "Membrane Potential", "x"), "takes a signal by its name alone")


# Holding, Seal Test and Tuning, Pipette Offset, Slow Current Injection, meters, Pulse


def test_i_clamp_holding_steps_in_pa_and_stays_within_1_v_over_the_feedback_resistor(tmp_path):
    amp = amp_in(IC, tmp_path)
    write = amp.set("Holding", -100, "pA", step=40)
    assert [value for _, value in sets(amp.commander)] == pytest.approx([-4e-11, -8e-11, -1e-10])
    assert (write.outcome, write.steps) == ("ok", pytest.approx((-4e-11, -8e-11, -1e-10)))
    refused(amp, lambda: amp.set("Holding", -300, "pA", step=40), r"Holding in I-Clamp is -200 pA to 200 pA")


def test_seal_test_in_v_clamp_and_tuning_in_i_clamp_share_their_api_names(tmp_path):
    amp = amp_in(VC, tmp_path)
    refused(amp, lambda: amp.set("Seal Test Amplitude", 1500, "mV"), r"Seal Test Amplitude in V-Clamp is -1000 mV to 1000 mV")
    refused(amp, lambda: amp.set("Tuning Amplitude", 50, "pA"), "Tuning Amplitude is not in V-Clamp")
    assert amp.enable("Seal Test", True).stem == "TestSignalEnable"
    amp = amp_in(IC, tmp_path)
    refused(amp, lambda: amp.set("Tuning Amplitude", 3, "nA"), r"Tuning Amplitude in I-Clamp is -2 nA to 2 nA")  # 10 V / 5 GΩ
    assert amp.set("TestSignalAmplitude", 1, "nA").label == "Tuning Amplitude"  # the API name, in the mode's row
    assert amp.enable("Tuning", True).after is True


@pytest.mark.parametrize("mode, label", [(VC, "Seal Test Frequency"), (IC, "Tuning Frequency")])
def test_a_test_signal_frequency_goes_to_commander_as_its_period(tmp_path, mode, label):
    # P21: SetTestSignalFrequency takes the period in s, though the vendor says Hertz; Get reads Hz
    amp = amp_in(mode, tmp_path)
    write = amp.set(label, 50, "Hz")
    assert sets(amp.commander) == [("SetTestSignalFrequency", 0.02)]
    assert (write.outcome, write.target, write.after, amp.get(label, "Hz")) == ("ok", 50.0, 50.0, 50.0)


@pytest.mark.parametrize("mode, label", [(VC, "Seal Test Frequency"), (IC, "Tuning Frequency")])
def test_a_test_signal_frequency_off_commanders_list_is_refused(tmp_path, mode, label):
    # P21: 2, 5, 10, 20, 50, 60, 100, 200, 500 and 1000 Hz each read back as sent; 7 Hz was kept as 10 Hz
    amp = amp_in(mode, tmp_path)
    refused(amp, lambda: amp.set(label, 7, "Hz"), f"{label} is one of Commander's values, not 7 Hz; the values either side: 5 Hz and 10 Hz")
    assert amp.set(label, 60, "Hz").after == 60.0


def test_a_value_off_commanders_unlisted_steps_is_a_mismatch_that_says_so(tmp_path):
    # Commander keeps Buzz Duration on its own steps, whose list ommm does not have (per its Help)
    amp = amp_in(IC, tmp_path)
    after_each_set(amp, lambda stem, value: amp.commander.dll.values.update({("I-Clamp", stem): 1e-3}))
    with pytest.raises(WriteError, match=re.escape("Commander kept 1 ms, not 0.7 ms: Commander keeps one of its steps from 50 µs to 500 ms")):
        amp.set("Buzz Duration", 0.7, "ms")


@pytest.mark.parametrize("mode", [VC, IC])
def test_pipette_offset_held_by_the_last_autos_level_is_a_mismatch_that_names_the_hold(tmp_path, mode):
    # P06: a Set past ±100 mV of the last Auto Pipette Offset's level reads back clipped; P14: the window's sign
    amp = amp_in(mode, tmp_path)
    assert amp.set("Pipette Offset", 80, "mV").outcome == "ok"
    with pytest.raises(WriteError, match=r"Commander kept 100 mV, not 150 mV: Commander holds Pipette Offset within ±100 mV") as raised:
        amp.set("Pipette Offset", 150, "mV")
    assert raised.value.write.outcome == "mismatch"
    assert amp.get("Pipette Offset", "mV") == 100.0


def test_slow_current_injection_is_i_clamps_and_its_level_is_checked_when_turned_on(tmp_path):
    amp = amp_in(IC, tmp_path)
    amp.set("Slow Current Injection Level", -70, "mV")
    amp.set("Slow Current Injection Settling Time", 200, "ms")
    on = amp.enable("Slow Current Injection", True)
    assert on.depends["SlowCurrentInjLevel"] == pytest.approx(-0.07)
    refused(amp, lambda: amp.set("Slow Current Injection Level", -1100, "mV"), r"is -1000 mV to 1000 mV")
    vclamp = amp_in(VC, tmp_path)
    refused(vclamp, lambda: vclamp.enable("Slow Current Injection", True), "^Slow Current Injection is a checkbox in I-Clamp, not in V-Clamp; in V-Clamp, enable takes ")


def test_the_meters_checkboxes_by_mode_and_make_safe_turns_resistance_off(tmp_path):
    amp = amp_in(IC, tmp_path)
    assert amp.enable("Resistance Meter", True).after is True
    refused(amp, lambda: amp.enable("Irms Meter", True), "^Irms Meter is a checkbox in V-Clamp, not in I-Clamp")  # 6004 on Commander (P17)
    assert [(write.label, write.after) for write in amp.make_safe()] == [("Pipette Capacitance Neutralization", False), ("Resistance Meter", False)]


def test_pulse_takes_its_amplitude_by_mode_and_its_duration_on_commanders_steps(tmp_path):
    amp = amp_in(IC, tmp_path)
    refused(amp, lambda: amp.set("Pulse Amplitude", 20, "mV"), "Pulse Amplitude in I-Clamp is a current: pA or nA, not mV")
    refused(amp, lambda: amp.set("Pulse Amplitude", 3000, "pA"), r"Pulse Amplitude in I-Clamp is -2000 pA to 2000 pA")  # 10 V / 5 GΩ
    amp.set("Pulse Amplitude", 100, "pA")
    refused(amp, lambda: amp.set("Pulse Duration", 600, "ms"), r"Pulse Duration in I-Clamp is 0.1 ms to 500 ms")
    after_each_set(amp, lambda stem, value: amp.commander.dll.values.update({("I-Clamp", stem): 1e-3}))
    with pytest.raises(WriteError, match="Commander kept 1 ms, not 0.7 ms: Commander keeps one of its steps from 0.1 to 500 ms"):
        amp.set("Pulse Duration", 0.7, "ms")
    assert amp.press("Pulse").outcome == "ok"


# compensation


def test_cp_fast_and_cp_slow_capacitance_ranges_follow_the_feedback_resistor(tmp_path):
    # per the manual: 0-36 pF and 0-3 pF, but 0-12 pF and 0-1 pF at 50 GΩ
    amp = amp_in(VC, tmp_path, at(3))
    refused(amp, lambda: amp.set("Cp Fast Capacitance", 20, "pF"), r"Cp Fast Capacitance in V-Clamp is 0 pF to 12 pF")
    refused(amp, lambda: amp.set("Cp Slow Capacitance", 2, "pF"), r"Cp Slow Capacitance in V-Clamp is 0 pF to 1 pF")
    amp = amp_in(VC, tmp_path)  # 5 GΩ
    assert amp.set("Cp Fast Capacitance", 20, "pF").depends["FeedbackResistorVC1"] == 2
    assert amp.set("Cp Slow Capacitance", 2, "pF").outcome == "ok"


def test_cp_slow_tau_x20_multiplies_tau_and_its_range(tmp_path):
    # per Commander's Help: 10-200 µs, or 200-4000 µs with Tau x20; P20: the checkbox multiplies the Tau read by 20
    amp = amp_in(VC, tmp_path)
    refused(amp, lambda: amp.set("Cp Slow Tau", 300, "µs"), r"Cp Slow Tau in V-Clamp is 10 µs to 200 µs")
    assert amp.enable("Cp Slow Tau x20", True).also == {"SlowCompTau": [1e-05, 0.0002]}
    assert amp.set("Cp Slow Tau", 300, "µs").depends["SlowCompTauX20Enable"] is True
    refused(amp, lambda: amp.set("Cp Slow Tau", 100, "µs"), r"is 200 µs to 4000 µs")


def test_whole_cell_values_follow_the_feedback_resistor_and_are_refused_where_the_window_greys_them(tmp_path):
    # per the manual and Commander's Help; the panel greyed out at 5 GΩ (capture screenshots)
    amp = amp_in(VC, tmp_path)  # 5 GΩ
    refused(amp, lambda: amp.set("Whole Cell Cm", 33, "pF"), "greys Whole Cell out at a feedback resistor of 5 GΩ")
    amp = amp_in(VC, tmp_path, at(1))
    refused(amp, lambda: amp.set("Whole Cell Cm", 150, "pF"), r"Whole Cell Cm in V-Clamp is 1 pF to 100 pF")
    refused(amp, lambda: amp.set("Whole Cell Rs", 0.2, "MΩ"), r"Whole Cell Rs in V-Clamp is 0.4 MΩ to 1000 MΩ")
    amp = amp_in(VC, tmp_path, at(0))  # 50 MΩ
    assert amp.set("Whole Cell Cm", 150, "pF").outcome == "ok"
    refused(amp, lambda: amp.set("Whole Cell Rs", 200, "MΩ"), r"is 0.1 MΩ to 100 MΩ")


def test_rs_compensation_correction_follows_prediction_while_the_link_is_on(tmp_path):
    # P03, P05: with the link beside it on (the API cannot read or change it), Correction follows Prediction
    amp = amp_in(VC, tmp_path)
    write = amp.set("Rs Compensation Prediction", 60, "%", step=20)
    assert write.also == {"RsCompCorrection": [0.0, 60.0]}  # first before, last after, over the three steps
    with pytest.raises(WriteError, match=r"Commander kept 60 %, not 30 %: with the link beside it on, Correction follows Prediction"):
        amp.set("Rs Compensation Correction", 30, "%")
    on = amp.enable("Rs Compensation", True)  # applies Bandwidth, Prediction and Correction at once, each checked
    assert {"RsCompBandwidth", "RsCompPrediction", "RsCompCorrection"} <= on.depends.keys()


def test_neutralization_lowered_by_the_oscillation_killer_is_a_mismatch_that_says_so(tmp_path):
    # per Commander's Help: in I-Clamp the Oscillation Killer lowers Neutralization by 1 pF (the 3 pF is the test's)
    amp = amp_in(IC, tmp_path)
    assert amp.enable("Oscillation Killer", True).stem == "OscKillerEnable"

    def killer(stem, value):
        if stem == "NeutralizationCap" and value > 3e-12:
            amp.commander.dll.values[("I-Clamp", stem)] = value - 1e-12

    after_each_set(amp, killer)
    assert amp.set("Pipette Capacitance Neutralization", 3, "pF").outcome == "ok"
    with pytest.raises(WriteError, match=r"Commander kept 3 pF, not 4 pF: Commander lowered it \(oscillation killer\)"):
        amp.set("Pipette Capacitance Neutralization", 4, "pF")


def test_bridge_balance_and_leak_subtraction_each_in_its_own_mode(tmp_path):
    amp = amp_in(IC, tmp_path)
    assert amp.set("Bridge Balance", 15, "MΩ").outcome == "ok"
    refused(amp, lambda: amp.set("Leak Subtraction", 1, "GΩ"), "Leak Subtraction is not in I-Clamp")
    amp = amp_in(VC, tmp_path)
    assert amp.set("Leak Subtraction", 1, "GΩ").outcome == "ok"
    refused(amp, lambda: amp.enable("Bridge Balance", True), "^Bridge Balance is a checkbox in I-Clamp, not in V-Clamp")


# buttons


def test_auto_pipette_offset_in_v_clamp_says_it_moved_the_i_clamp_offset_too(tmp_path):
    # P16: pressed in V-Clamp it also moves the I-Clamp tab's offset, which the API reads only with that tab in front
    amp = amp_in(VC, tmp_path)
    amp.commander.dll.found_offsets = {"V-Clamp": 0.004, "I-Clamp": -0.002}
    write = amp.press("Auto Pipette Offset")
    assert (write.after, write.also) == (None, {"PipetteOffset": [0.0, 0.004]})
    assert write.reason == "it also moved the I-Clamp tab's Pipette Offset, which ommm reads in I-Clamp"
    amp.set_mode("I-Clamp")
    assert amp.get("Pipette Offset", "mV") == 2.0  # the window's sign (P14)


@pytest.mark.parametrize("mode", [IC, "I = 0"])
def test_auto_pipette_offset_in_i_clamp_says_it_changes_the_v_clamp_tab_too(tmp_path, mode):
    # P16: pressed in I-Clamp it moved V-Clamp's offset on the model cell, and V-Clamp's Holding with nothing attached
    write = amp_in(mode, tmp_path).press("Auto Pipette Offset")
    assert write.reason == "it also changes the V-Clamp tab's Pipette Offset, or with nothing attached its Holding, which ommm reads in V-Clamp"


def test_an_auto_turns_on_its_checkbox_and_its_result_is_the_diff(tmp_path):
    amp = amp_in(IC, tmp_path)
    assert amp.press("Auto Bridge Balance").also == {"BridgeBalEnable": [False, True]}
    amp = amp_in(VC, tmp_path, at(1))
    assert amp.press("Auto Whole Cell").also["WholeCellCompEnable"] == [False, True]


@pytest.mark.parametrize("button, waited", [("Buzz", 0.5), ("Clear +", 3.0), ("Clear -", 3.0)])
def test_a_button_that_timed_out_waits_its_longest_duration_before_reading(tmp_path, monkeypatch, button, waited):
    # Buzz is up to 500 ms, per Commander's Help; Clear has no documented duration, so the DLL's 3 s once more
    amp = amp_in(IC, tmp_path)
    slept, call, stem = [], amp.commander.dll.call, find(button).stem
    monkeypatch.setattr(amplifier.time, "sleep", slept.append)

    def timing_out(name, *args):
        if name == stem:
            raise CommanderError(name, 6005, "MSGTIMEOUT")
        return call(name, *args)

    amp.commander.dll.call = timing_out
    with pytest.raises(WriteError, match="did not answer in time"):
        amp.press(button)
    assert slept == [waited]
