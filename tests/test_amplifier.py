"""ommm.Amplifier's writes on the fake: the checks before, the readback after, the rules of docs/writes.md, failures,
and sharing Commander with the person at its window (fake.gui)."""

import json
import math
import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import ommm
from ommm import Amplifier, WriteError, amplifier, process, settings
from ommm.commander import CommanderError, NotApplicable
from ommm.testing import FakeCommander

from conftest import after_each_set, logged, names, refused, sets

DATA = Path(__file__).parent / "data"
FAKE = ommm.EXAMPLES / "fake"  # the snapshots and the test .mcc the package ships
VCLAMP, ICLAMP = FAKE / "vclamp.json", FAKE / "iclamp.json"  # both at 5 GΩ
STALE = DATA / "vclamp_stale_secondary_telegraph.json"  # V-Clamp at 500 MΩ, the telegraph's secondary signal stale


def amp_on(tmp_path, snapshot=VCLAMP, other_tab=ICLAMP) -> Amplifier:
    """An Amplifier on the two-tab fake, logging in tmp_path."""
    return Amplifier(log_dir=tmp_path, commander=FakeCommander(snapshot, other_tab=other_tab))


def before_call(amp: Amplifier, function: str, then, nth: int = 1) -> list[str]:
    """Run then() just before the nth call of `function` from now: a click in Commander's window between two reads, or
    Commander failing (then() raises). Returns the calls of `function` tried, a failed one included."""
    call, tried = amp.commander.dll.call, []

    def hooked(name, *args):
        if name == function:
            tried.append(name)
            if len(tried) == nth:
                then()
        return call(name, *args)

    amp.commander.dll.call = hooked
    return tried


def fails(code: int, text: str):
    def raising():
        raise CommanderError("Commander", code, text)

    return raising


# readback


def test_a_write_reads_before_and_after_and_returns_what_it_did(tmp_path):
    amp = amp_on(tmp_path)
    write = amp.set("Primary Output Gain", 5, "x")
    assert (write.before, write.target, write.after, write.outcome, write.mode) == (2.0, 5.0, 5.0, "ok", "V-Clamp")
    assert write.depends == {"Mode": 0, "ModeSwitchEnable": False, "PrimarySignalGain": 2.0}
    assert names(amp)[-3:] == ["SetPrimarySignalGain", "GetPrimarySignalGain", "GetOutputZeroAmplitude"]  # what it also changes
    assert write.also == {}  # Output Zero is 0 at both gains
    with pytest.raises(FrozenInstanceError):
        write.outcome = "error"


@pytest.mark.parametrize("off_by, outcome", [(0.0, "ok"), (-3.5e-4, "adjusted"), (-1e-3, "mismatch")])
def test_a_readback_within_the_rows_resolution_is_adjusted_and_beyond_it_a_mismatch(tmp_path, off_by, outcome):
    # P03: Commander stores Holding on coarse steps (12.3456 mV read 11.995 mV); V-Clamp Holding's resolution is 0.4 mV
    amp = amp_on(tmp_path)
    after_each_set(amp, lambda stem, value: amp.commander.dll.values.update({("V-Clamp", "Holding"): value + off_by}))
    if outcome == "mismatch":
        with pytest.raises(WriteError, match=r"Commander kept -61 mV, not -60 mV: in V-Clamp, Holding plus the level") as raised:
            amp.set("Holding", -60, "mV")
        write = raised.value.write
    else:
        write = amp.set("Holding", -60, "mV")
    assert write.outcome == outcome
    assert logged(amp)[-1]["outcome"] == outcome


def test_a_readback_that_does_not_apply_is_a_mismatch(tmp_path):
    amp = amp_on(tmp_path)
    after_each_set(amp, lambda stem, value: amp.gui.mode("I = 0"))  # a click before the readback
    with pytest.raises(WriteError, match="the readback does not apply") as raised:
        amp.set("Cp Fast Capacitance", 2, "pF")
    assert raised.value.write.outcome == "mismatch"


def stale_gain(amp: Amplifier):
    """A telegraph that keeps sending a Primary Output gain of 2."""
    read = amp.commander.telegraph.read
    amp.commander.telegraph.read = lambda *args: read(*args) | {"dAlpha": 2.0}


def test_a_telegraphed_setting_is_checked_against_the_telegraph(tmp_path):
    amp = amp_on(tmp_path)
    assert amp.set("Primary Output Gain", 5, "x").outcome == "ok"
    assert logged(amp)[-1]["telegraph_checks"] == []
    stale_gain(amp)
    with pytest.raises(WriteError, match="the telegraph disagrees: primary gain: API 10, telegraph 2") as raised:
        amp.set("Primary Output Gain", 10, "x")
    assert raised.value.write.outcome == "mismatch"
    assert logged(amp)[-1]["telegraph_checks"] == ["primary gain: API 10, telegraph 2"]


def no_telegraph(*args):
    raise TimeoutError("no telegraph from Commander for serial 1 channel 1 within 1.0 s")


@pytest.mark.parametrize("call, label", [
    (lambda amp: amp.set("Primary Output Gain", 5, "x"), "Primary Output Gain"),
    (lambda amp: amp.set_mode("I = 0"), "Mode"),
], ids=["set", "set_mode"])
def test_no_telegraph_after_a_set_is_unknown(tmp_path, call, label):
    # the API read it back as sent; the telegraph did not disagree, it did not come
    amp = amp_on(tmp_path)
    after_each_set(amp, lambda stem, value: setattr(amp.commander.telegraph, "read", no_telegraph))
    with pytest.raises(WriteError, match=rf"^{label}: unknown: read back as sent, but no telegraph came to check it: no telegraph from Commander for serial") as raised:
        call(amp)
    assert raised.value.write.after == raised.value.write.target
    assert [(line["outcome"], line["error_code"], line["telegraph_checks"]) for line in logged(amp)] == [("unknown", None, None)]


def test_only_the_mode_signals_gains_and_lowpass_filters_are_checked_against_the_telegraph(tmp_path):
    # Whole Cell's Cm and Rs are telegraphed only while it is on, so they are not checked
    amp = amp_on(tmp_path, STALE)  # 500 MΩ
    amp.set("Whole Cell Cm", 20, "pF")
    amp.set("Primary Output Lowpass Filter", 2, "kHz")
    assert [(line["stem"], line["telegraph_checks"]) for line in logged(amp)][-2:] == [("WholeCellCompCap", None), ("PrimarySignalLPF", [])]


# the checks: nothing is sent when one fails


@pytest.mark.parametrize("args, says", [
    (("Holding", 2000, "mV"), r"Holding in V-Clamp is -1000 mV to 1000 mV, so not 2000 mV"),
    (("Holding", float("nan"), "mV"), "Holding takes a number, not nan"),
    (("Primary Output Gain", 7, "x"), r"Primary Output Gain is one of Commander's values, not 7 x; the values either side: 5 x and 10 x$"),
    (("Primary Output Gain", 3, "x"), r"not 3 x; the values either side: 2 x and 5 x$"),
    (("Primary Output Gain", 0.5, "x"), r"not 0.5 x; the smallest: 1 x$"),
    (("Secondary Output Lowpass Filter", 5, "kHz"), r"not 5 kHz; the smallest: 10 kHz$"),
    (("Zap Duration", 0.4, "ms"), r"the values either side: 0.2 ms and 0.5 ms$"),
    (("Primary Output", "Membrane Voltage"), "Primary Output on the V-Clamp tab is one of Membrane Current, Membrane Potential"),
    (("Bridge Balance", 10, "MΩ"), r"Bridge Balance is not in V-Clamp: Commander has it in I-Clamp"),
    (("Feedback Resistor", 500, "MΩ"), r"restarting Commander with a .mcc file: load_config"),
    (("Zap", 1, "ms"), r'Zap is a button: press\("Zap"\)'),
    (("Seal Test", 1, "mV"), r'Seal Test is a checkbox: turn it on or off with enable\("Seal Test", on\)'),
    (("Cp Slow Tau x20", True, None), r'Cp Slow Tau x20 is a checkbox: turn it on or off with enable\("Cp Slow Tau x20", on\)'),
    (("Mode", "I-Clamp", None), r'set_mode\("I-Clamp"\)'),
])
def test_values_off_the_list_out_of_range_or_for_another_control_are_refused_never_snapped(tmp_path, args, says):
    amp = amp_on(tmp_path)
    refused(amp, lambda: amp.set(*args), says)
    assert logged(amp)[-1]["outcome"] == "refused"


def test_i_clamp_ranges_follow_the_feedback_resistor_and_output_zero_the_gain(tmp_path):
    amp = amp_on(tmp_path, ICLAMP, VCLAMP)  # 5 GΩ: ±1 V / Rf is ±200 pA
    refused(amp, lambda: amp.set("Holding", 300, "pA"), r"Holding in I-Clamp is -200 pA to 200 pA, so not 300 pA")
    amp.set("Holding", 150, "pA")
    amp.set("Output Zero", 1000, "mV")  # ±2900 mV below a Primary Output gain of 10
    amp.set("Primary Output Gain", 10, "x")
    refused(amp, lambda: amp.set("Output Zero", 1000, "mV"), r"Output Zero in I-Clamp is -290 mV to 290 mV")


def test_plan_runs_the_same_checks_and_sends_and_logs_nothing(tmp_path):
    amp = amp_on(tmp_path)
    planned = amp.plan("Holding", -60, "mV", step=25, expect=0)
    assert (planned.outcome, planned.before, planned.steps) == ("planned", 0.0, (-0.025, -0.05, -0.06))
    assert amp.plan("Holding", 2000, "mV").outcome == "refused"
    assert (sets(amp.commander), logged(amp)) == ([], [])


@pytest.mark.parametrize("args, question", [
    (("Holding", -40, "mV"), "Holding 0 mV → -40 mV (V-Clamp); Holding is off: the value applies once it is on"),
    (("Zap Duration", 0.5, "ms"), "Zap Duration 0.025 ms → 0.5 ms (V-Clamp)"),
    (("Zap Duration", 500, "µs"), "Zap Duration 25 µs → 500 µs (V-Clamp)"),  # the caller's unit
    (("Primary Output", "Membrane Potential"), "Primary Output Membrane Current → Membrane Potential (V-Clamp)"),
])
def test_a_planned_writes_reason_is_the_question_and_the_set_keeps_it(tmp_path, args, question):
    amp = amp_on(tmp_path)
    assert amp.plan(*args).reason == question
    assert amp.set(*args).reason == logged(amp)[-1]["reason"] == question


def test_a_value_whose_checkbox_is_off_says_it_applies_once_the_checkbox_is_on(tmp_path):
    # Commander takes Holding with its checkbox off and applies it once the checkbox is on
    amp = amp_on(tmp_path)  # vclamp.json: Holding and Seal Test off
    off = "Holding 0 mV → -60 mV (V-Clamp); Holding is off: the value applies once it is on"
    assert amp.plan("Holding", -60, "mV").reason == off
    write = amp.set("Holding", -60, "mV")
    assert (write.outcome, write.reason, write.depends["HoldingEnable"]) == ("ok", off, False)
    assert amp.plan("Seal Test Amplitude", 10, "mV").reason.endswith("; Seal Test is off: the value applies once it is on")
    amp.enable("Holding", True)
    write = amp.set("Holding", -40, "mV")
    assert (write.reason, write.depends["HoldingEnable"]) == ("Holding -60 mV → -40 mV (V-Clamp)", True)


def test_expect_refuses_once_commander_no_longer_shows_what_a_dialog_showed(tmp_path):
    amp = amp_on(tmp_path)
    shown = amp.plan("Primary Output Gain", 5, "x").before  # the dialog shows 2
    amp.gui.set("Primary Output Gain", 10, "x")  # someone turns it in Commander meanwhile
    refused(amp, lambda: amp.set("Primary Output Gain", 5, "x", expect=shown), "Commander no longer shows 2 x for Primary Output Gain: it shows 10 x")
    assert amp.get("Primary Output Gain", "x") == 10.0  # read, never overwritten
    assert amp.set("Primary Output Gain", 5, "x", expect=10).outcome == "ok"


HOLDING = ("Holding", -60, "mV")


@pytest.mark.parametrize("args, kwargs, says", [
    (HOLDING, {"step": (5, "mV")}, "the step is a number in the call's unit, not (5, 'mV')"),  # 0.1's pair
    (HOLDING, {"step": math.nan}, "the step is a number in the call's unit, not nan"),
    (HOLDING, {"step": True}, "the step is a number in the call's unit, not True"),
    (HOLDING, {"step": "5"}, "the step is a number in the call's unit, not '5'"),
    (HOLDING, {"expect": (-10, "mV")}, "the expected value is a number in the call's unit, not (-10, 'mV')"),
    (HOLDING, {"expect": "-40"}, "the expected value is a number in the call's unit, not '-40'"),  # MATLAB's Expect="-40"
    (HOLDING, {"expect": math.nan}, "the expected value is a number in the call's unit, not nan"),
    (("Primary Output", "Membrane Potential"), {"expect": 0}, 'the expected value of Primary Output is a signal\'s name, such as "Membrane Current"'),
])
def test_a_malformed_step_or_expect_is_refused_naming_it(tmp_path, args, kwargs, says):
    # checked as value is; expect=nan once passed the guard, and the write went
    amp = amp_on(tmp_path)
    amp.set("Holding", -10, "mV")
    plan = amp.plan(*args, **kwargs)
    assert (plan.outcome, plan.reason) == ("refused", says)
    refused(amp, lambda: amp.set(*args, **kwargs), re.escape(says) + "$")
    assert logged(amp)[-1]["outcome"] == "refused"


def test_every_write_shows_the_active_modes_tab_first_and_lists_amplifiers_only_at_connect(tmp_path):
    amp = amp_on(tmp_path)
    amp.gui.show_tab("I-Clamp")  # someone looks at the other tab
    amp.set("Primary Output Gain", 5, "x")
    assert names(amp)[0] == "SelectMultiClamp" and "FindFirstMultiClamp" not in names(amp)
    assert amp.commander.dll.values[("V-Clamp", "PrimarySignalGain", 0)] == 5.0  # P01 would have put it on the I-Clamp tab
    assert amp.commander.dll.values[("I-Clamp", "PrimarySignalGain", 7)] == 2.0


def test_commander_closed_refuses_before_any_call(tmp_path):
    amp = amp_on(tmp_path)
    amp.commander.dll.dead = True
    refused(amp, lambda: amp.set("Holding", -60, "mV"), "Commander is not running in this desktop session")
    assert amp.commander.dll.calls == []
    assert logged(amp)[-1]["commander"] == {"pid": None}


def test_a_handle_from_before_a_relaunch_refuses_and_says_reconnect(tmp_path):
    # 6002 from SelectMultiClamp, the first call of every write: a handle from before Commander restarted
    amp = amp_on(tmp_path)
    amp.commander.dll.fail_at(1, 6002)
    refused(amp, lambda: amp.set("Holding", -60, "mV"), r"^Commander was closed or restarted: reconnect\(\) \(amp.reconnect\(\) in Python")


def test_ext_on_refuses_every_write_but_turning_ext_off(tmp_path):
    amp = amp_on(tmp_path)
    amp.gui.enable("Ext", True)
    for call in (lambda: amp.set("Holding", -60, "mV"), lambda: amp.set_mode("I-Clamp"), amp.make_safe,
                 lambda: amp.press("Auto Output Zero"), lambda: amp.enable("Seal Test", True)):
        refused(amp, call, r'^Mode Switching is on, so the mode follows the MODE input: turn it off first: enable\("Mode Switching", on\) with on false$')
    assert sets(amp.commander) == []
    assert amp.enable("Ext", False).after is False


def test_ext_is_read_first_and_sent_only_to_change_it(tmp_path):
    # P07: each Set of Mode Switching flips it, whatever the value sent
    amp = amp_on(tmp_path)
    write = amp.enable("Ext", False)
    assert (write.outcome, write.steps, sets(amp.commander), logged(amp)) == ("ok", (), [], [])
    assert amp.enable("Mode Switching", True).after is True
    assert amp.enable("ext", False).after is False
    assert sets(amp.commander) == [("SetModeSwitchEnable", True), ("SetModeSwitchEnable", False)]


def test_ext_off_that_changes_the_mode_shows_it_in_also_and_the_reason(tmp_path):
    # on the model cell Ext on and off left I = 0, from the floating MODE input (P07); the fake does not model the input
    amp = amp_on(tmp_path)
    amp.gui.enable("Ext", True)

    def mode_input(stem, value):  # as Ext goes off, the mode input leaves I = 0
        if stem == "ModeSwitchEnable":
            amp.commander.dll.set_mode(2)

    after_each_set(amp, mode_input)
    write = amp.enable("Ext", False)
    assert (write.outcome, write.after, write.also) == ("ok", False, {"Mode": [0, 2]})
    assert write.reason == "the mode is now I = 0 (the MODE input)"
    assert (logged(amp)[-1]["also"], logged(amp)[-1]["reason"]) == ({"Mode": [0, 2]}, write.reason)


def test_a_telegraph_mode_that_disagrees_refuses(tmp_path):
    amp = amp_on(tmp_path)
    read = amp.commander.telegraph.read
    amp.commander.telegraph.read = lambda *args: read(*args) | {"uOperatingMode": 1}
    refused(amp, lambda: amp.set("Holding", -60, "mV"), "Commander's API says V-Clamp and its telegraph I-Clamp")


def test_a_telegraph_packet_of_another_size_refuses(tmp_path):
    amp = amp_on(tmp_path)
    read = amp.commander.telegraph.read
    amp.commander.telegraph.read = lambda *args: read(*args) | {"uStructSize": 128}
    refused(amp, lambda: amp.set("Holding", -60, "mV"), "a telegraph packet of 128 bytes; ommm decodes 256-byte ones")


def test_no_telegraph_refuses_writes_but_not_make_safe(tmp_path):
    saved = ommm.load_snapshot(VCLAMP)
    saved["readings"]["TestSignalEnable"] = saved["readings"]["RsCompEnable"] = True
    amp = Amplifier(log_dir=tmp_path, commander=FakeCommander(saved | {"telegraph": None}))
    refused(amp, lambda: amp.set("Holding", -60, "mV"), "^the mode cannot be checked: no telegraph")
    writes = amp.make_safe()
    assert [(write.label, write.before, write.after) for write in writes] == [("Rs Compensation", True, False), ("Seal Test", True, False)]
    assert sets(amp.commander) == [("SetRsCompEnable", False), ("SetTestSignalEnable", False)]
    assert amp.make_safe() == []  # nothing on: nothing sent


@pytest.mark.parametrize("function, outcome, says", [
    # each says what it had turned off already
    ("SetTestSignalEnable", "unknown", r"Seal Test: unknown: Commander did not answer in time.*\(after turning off Rs Compensation\)$"),  # its second Set
    ("GetTestSignalEnable", "refused", r"could not read TestSignalEnable: MSGTIMEOUT \(6005\) \(after turning off Rs Compensation\)$"),  # its second read
], ids=["set", "read"])
def test_make_safe_stops_at_its_first_failure(tmp_path, function, outcome, says):
    saved = ommm.load_snapshot(VCLAMP)
    saved["readings"] |= {"RsCompEnable": True, "TestSignalEnable": True, "MeterResistEnable": True}
    amp = Amplifier(log_dir=tmp_path, commander=FakeCommander(saved, other_tab=ICLAMP))
    before_call(amp, function, fails(6005, "MSGTIMEOUT"))
    with pytest.raises(WriteError, match=f"^{says}") as raised:
        amp.make_safe()
    assert raised.value.write.stem == "TestSignalEnable"
    assert sets(amp.commander) == [("SetRsCompEnable", False)]  # exactly one went through; the meter was left on
    assert amp.get("Resistance Meter") is True
    assert [(line["stem"], line["outcome"]) for line in logged(amp)] == [("RsCompEnable", "ok"), ("TestSignalEnable", outcome)]


def test_ext_command_sensitivity_0_is_a_snapshot_problem_and_does_not_refuse_writes(tmp_path):
    saved = ommm.load_snapshot(VCLAMP)
    saved["telegraph"] = saved["telegraph"] | {"dExtCmdSens": 0.0}
    amp = Amplifier(log_dir=tmp_path, commander=FakeCommander(saved))
    assert amp.set("Holding", -60, "mV").outcome == "ok"
    assert any(problem.startswith("external command sensitivity: 0 (off)") for problem in ommm.state(amp.snapshot())["problems"])


# checkboxes


def test_holding_and_slow_current_injection_are_never_both_on_in_i_clamp(tmp_path):
    amp = amp_on(tmp_path, ICLAMP, VCLAMP)
    amp.enable("Slow Current Injection", True)
    refused(amp, lambda: amp.enable("Holding", True), "Holding and Slow Current Injection are never both on in I-Clamp: turn Slow Current Injection off first")
    amp.enable("Slow Current Injection", False)
    amp.enable("Holding", True)
    refused(amp, lambda: amp.enable("Slow Current Injection", True), "turn Holding off first")


def test_whole_cell_is_refused_where_commanders_window_greys_it_out(tmp_path):
    amp = amp_on(tmp_path)  # 5 GΩ
    refused(amp, lambda: amp.enable("Whole Cell", True), "greys Whole Cell out at a feedback resistor of 5 GΩ: it needs 50 or 500 MΩ")
    refused(amp, lambda: amp.press("Auto Whole Cell"), "at a feedback resistor of 5 GΩ")
    amp = amp_on(tmp_path, STALE)  # 500 MΩ
    assert amp.enable("Whole Cell", True).depends["FeedbackResistorVC1"] == 1
    assert amp.press("Auto Whole Cell").outcome == "ok"


def test_turning_a_checkbox_on_checks_the_value_it_applies_at_once(tmp_path):
    amp = amp_on(tmp_path, ICLAMP, VCLAMP)
    amp.commander.dll.values[("I-Clamp", "Holding")] = 5e-10  # 500 pA stored, as set at 500 MΩ; ±200 pA at 5 GΩ
    refused(amp, lambda: amp.enable("Holding", True), r"turning Holding on applies Holding, 500 pA, at once, and that is outside -200 pA to 200 pA")
    amp.set("Holding", -20, "pA")
    assert amp.enable("Holding", True).depends["Holding"] == pytest.approx(-2e-11)


def test_a_checkbox_is_named_as_on_commanders_window_in_the_active_mode(tmp_path):
    amp = amp_on(tmp_path)
    assert amp.enable("Seal Test", True).stem == "TestSignalEnable"
    refused(amp, lambda: amp.enable("Tuning", True), "^Tuning is a checkbox in I-Clamp; in V-Clamp it is Seal Test$")
    refused(amp, lambda: amp.enable("Seal Test", "on"), "Seal Test is on or off: True or False, not 'on'")
    refused(amp, lambda: amp.enable("Seal Test", 1.0), "Seal Test is on or off: True or False, not 1.0")
    assert amp.enable("Oscillation Killer", True).label == "Disable/Reduce if Oscillation Detected"


@pytest.mark.parametrize("call", [
    lambda amp, name: amp.set(name, 1, "mV"),
    lambda amp, name: amp.press(name),
], ids=["set", "press"])
@pytest.mark.parametrize("name, says", [
    ("Seal Test", 'Seal Test is a checkbox: turn it on or off with enable("Seal Test", on)'),
    ("Rs Compensation", 'Rs Compensation is a checkbox: turn it on or off with enable("Rs Compensation", on)'),
    ("Whole Cell", 'Whole Cell is a checkbox: turn it on or off with enable("Whole Cell", on)'),
    ("TestSignalEnable", 'Seal Test is a checkbox: turn it on or off with enable("Seal Test", on)'),
    ("Cp Slow Tau x20", 'Cp Slow Tau x20 is a checkbox: turn it on or off with enable("Cp Slow Tau x20", on)'),
])
def test_a_checkbox_given_to_set_or_press_says_to_enable_it(tmp_path, call, name, says):
    amp = amp_on(tmp_path)
    refused(amp, lambda: call(amp, name), re.escape(says) + "$")
    assert amp.plan(name, 1, "mV").reason == says


def test_a_checkbox_of_another_mode_names_it_there(tmp_path):
    amp = amp_on(tmp_path, ICLAMP, VCLAMP)
    for call in (lambda: amp.set("Seal Test", 1, "mV"), lambda: amp.press("Seal Test"), lambda: amp.enable("Seal Test", True)):
        refused(amp, call, "^Seal Test is a checkbox in V-Clamp; in I-Clamp it is Tuning$")
    assert amp.enable("Tuning", True).stem == "TestSignalEnable"


@pytest.mark.parametrize("name, says", [
    # the API name gives this mode's checkbox, which enable takes here
    ("TestSignalEnable", 'Tuning is a checkbox: turn it on or off with enable("Tuning", on)'),
    # set and press send the caller nowhere enable refuses: they refuse as enable does
    ("Whole Cell", "Whole Cell is a checkbox in V-Clamp, not in I-Clamp; in I-Clamp, enable takes Mode Switching"),
    ("Cp Slow Tau x20", "Cp Slow Tau x20 is a checkbox in V-Clamp, not in I-Clamp; in I-Clamp, enable takes Mode Switching"),
])
@pytest.mark.parametrize("call", [
    lambda amp, name: amp.set(name, 1, "mV"),
    lambda amp, name: amp.press(name),
], ids=["set", "press"])
def test_set_and_press_of_a_checkbox_name_only_what_enable_takes_in_the_mode(tmp_path, call, name, says):
    amp = amp_on(tmp_path, ICLAMP, VCLAMP)
    write = refused(amp, lambda: call(amp, name), "^" + re.escape(says))
    if "enable(" in says:
        assert amp.enable(write.reason.split('"')[1], True).after is True
    else:
        refused(amp, lambda: amp.enable(name, True), "^" + re.escape(says))


@pytest.mark.parametrize("name, says", [
    ("Tuning", "Tuning is a checkbox in I-Clamp; in V-Clamp it is Seal Test"),
    ("Bridge Balance", ("Bridge Balance is a checkbox in I-Clamp, not in V-Clamp; in V-Clamp, enable takes Mode Switching, "
                        "Resistance Meter, Irms Meter, Holding, Seal Test, Cp Slow Tau x20, Whole Cell, Rs Compensation, "
                        "Disable/Reduce if Oscillation Detected, Leak Subtraction, Output Zero")),
    ("Zap", 'Zap is a button: press("Zap")'),
    ("Primary Output Gain", 'Primary Output Gain is a value: set("Primary Output Gain", value, "x")'),
    ("Seal Test Amplitude", 'Seal Test Amplitude is a value: set("Seal Test Amplitude", value, "mV"), or enable("Seal Test", on)'),
    ("Seal Tst", ("'Seal Tst' is not a Commander control ommm knows: did you mean 'Seal Test'? Every label: "
                  "docs/coming-from-commander.md; in V-Clamp, enable takes Mode Switching, Resistance Meter")),
])
def test_enable_says_what_a_name_that_is_no_checkbox_here_is(tmp_path, name, says):
    # in this order: another mode's checkbox, a button, a value, then find's did-you-mean
    amp = amp_on(tmp_path)
    refused(amp, lambda: amp.enable(name, True), "^" + re.escape(says))


@pytest.mark.parametrize("name, says", [
    ("Zap Duration", 'Zap Duration is a value, not a button: set("Zap Duration", value, "ms")'),
    ("Holding", 'Holding is a value, not a button: set("Holding", value, "mV"), or enable("Holding", on)'),
    ("Primary Output", 'Primary Output is a value, not a button: set("Primary Output", "Membrane Current")'),
    ("Mode", 'Mode is a value, not a button: set_mode("I-Clamp")'),
    ("Feedback Resistor", ("Feedback Resistor is a value, not a button: load_config with a .mcc file, which restarts "
                           "Commander (docs/mcc.md)")),
])
def test_press_of_a_value_names_the_call_that_sets_it(tmp_path, name, says):
    amp = amp_on(tmp_path)
    refused(amp, lambda: amp.press(name), "^" + re.escape(says) + "$")


@pytest.mark.parametrize("name, says", [
    ("Tuning Amplitude", "Tuning Amplitude is not in V-Clamp: Commander has it in I-Clamp; in V-Clamp it is Seal Test Amplitude"),
    ("Tuning Frequency", "Tuning Frequency is not in V-Clamp: Commander has it in I-Clamp; in V-Clamp it is Seal Test Frequency"),
    ("BridgeBalResist", "Bridge Balance is not in V-Clamp: Commander has it in I-Clamp"),
    ("Auto Bridge Balance", "Auto Bridge Balance is not in V-Clamp: Commander has it in I-Clamp"),
])
@pytest.mark.parametrize("call", [
    lambda amp, name: amp.set(name, 1, "pA"),
    lambda amp, name: amp.press(name),
    lambda amp, name: amp.enable(name, True),
], ids=["set", "press", "enable"])
def test_a_control_the_mode_lacks_is_refused_alike_by_set_press_and_enable(tmp_path, call, name, says):
    # never a set() call that set refuses, nor another mode's unit; a stem shared across modes names this mode's row
    amp = amp_on(tmp_path)
    refused(amp, lambda: call(amp, name), "^" + re.escape(says) + "$")


def test_how_to_set_a_row_the_mode_lacks_is_sets_refusal(tmp_path):
    assert amplifier.how_to_set(settings.find("Tuning Amplitude"), "V-Clamp") == (
        "Tuning Amplitude is not in V-Clamp: Commander has it in I-Clamp; in V-Clamp it is Seal Test Amplitude")
    assert amplifier.how_to_set(settings.find("Holding"), "I = 0") == "Holding is not in I = 0: Commander has it in V-Clamp, I-Clamp"


@pytest.mark.parametrize("label, unit, stem", [
    ("Holding", "mV", "HoldingEnable"),
    ("Leak Subtraction", "MΩ or GΩ", "LeakSubEnable"),
    ("Output Zero", "mV", "OutputZeroEnable"),
    ("Bridge Balance", "MΩ or GΩ", "BridgeBalEnable"),
    ("Pipette Capacitance Neutralization", "pF", "NeutralizationEnable"),
])
def test_get_of_a_value_named_as_its_checkbox_without_a_unit_names_the_checkbox(tmp_path, label, unit, stem):
    row = settings.find(label)
    mode = row.modes[0]
    amp = amp_on(tmp_path, *((VCLAMP, ICLAMP) if mode == "V-Clamp" else (ICLAMP, VCLAMP)))
    amp.enable(label, True)
    with pytest.raises(ValueError, match=re.escape(f'give a unit: {unit}; its checkbox is get("{stem}")') + "$"):
        amp.get(label)
    assert amp.get(stem) is True
    with pytest.raises(ValueError, match="give a unit: mV$"):  # a value with its own name for the checkbox
        amp.get("Seal Test Amplitude" if mode == "V-Clamp" else "Slow Current Injection Level")


def test_the_values_named_as_their_checkbox_are_these_five():
    names = {label for label, _, _ in settings.CHECKBOXES}
    shared = {row.label for row in settings.SETTINGS if row.kind != "bool" and row.label in names}
    assert shared == {"Holding", "Leak Subtraction", "Output Zero", "Bridge Balance", "Pipette Capacitance Neutralization"}


# steps and failures


def test_step_sends_and_reads_back_each_step(tmp_path):
    amp = amp_on(tmp_path)
    write = amp.set("Holding", -60, "mV", step=25)
    assert sets(amp.commander) == [("SetHolding", -0.025), ("SetHolding", -0.05), ("SetHolding", -0.06)]
    assert (write.outcome, write.after) == ("ok", -0.06)
    assert [line["target"] for line in logged(amp)] == [-0.025, -0.05, -0.06]
    refused(amp, lambda: amp.set("Primary Output Gain", 10, "x", step=1), "Primary Output Gain is one of Commander's values: it takes no step")
    refused(amp, lambda: amp.set("Holding", 60, "mV", step=0.01), "steps of that size would take 12000, more than 1000")


def test_a_value_the_oscillation_killer_lowered_stops_the_steps_as_a_mismatch(tmp_path):
    amp = amp_on(tmp_path)
    amp.enable("Oscillation Killer", True)

    def killer(stem, value):  # past 50 % it oscillates, and Commander lowers it by 10 % (per its Help; the 50 % is the test's)
        if stem == "RsCompPrediction" and value > 50:
            amp.commander.dll.values[("V-Clamp", "RsCompPrediction")] = value - 10

    after_each_set(amp, killer)
    with pytest.raises(WriteError, match=r"Commander kept 50 %, not 60 %: Commander lowered it \(oscillation killer\) \(step 3 of 4; the last confirmed 40 %\)") as raised:
        amp.set("Rs Compensation Prediction", 80, "%", step=20)
    assert (raised.value.write.outcome, raised.value.write.before, raised.value.write.after) == ("mismatch", 0.0, 50.0)
    assert sets(amp.commander)[-3:] == [("SetRsCompPrediction", 20.0), ("SetRsCompPrediction", 40.0), ("SetRsCompPrediction", 60.0)]


def test_a_gui_change_between_steps_stops_the_next(tmp_path):
    amp = amp_on(tmp_path)
    before_call(amp, "SelectMultiClamp", lambda: amp.gui.set("Holding", -10, "mV"), nth=2)  # before step 2's reads
    with pytest.raises(WriteError, match=r"Commander changed since the write was checked: Holding was -25 mV, now -10 mV \(step 2 of 3; the last confirmed -25 mV\)$") as raised:
        amp.set("Holding", -60, "mV", step=25)
    assert sets(amp.commander) == [("SetHolding", -0.025)]  # the first step was sent
    write = raised.value.write
    assert (write.outcome, write.before, write.target) == ("refused", 0.0, -0.05)  # as a mismatch mid-sequence reports it


def test_a_checkbox_click_between_steps_is_named_as_the_window_names_it(tmp_path):
    amp = amp_on(tmp_path)
    was = amp.get("HoldingEnable")
    before_call(amp, "SelectMultiClamp", lambda: amp.gui.enable("Holding", not was), nth=2)
    on_off = ("on", "off") if was else ("off", "on")
    with pytest.raises(WriteError, match=rf"checked: Holding was {on_off[0]}, now {on_off[1]} \(step 2 of 3; "):
        amp.set("Holding", -60, "mV", step=25)


def test_step_and_expect_are_in_the_calls_unit(tmp_path):
    # as MATLAB's Step= and Expect=: 0.025 V steps are 25 mV ones, and 0 V is the 0 mV shown
    amp = amp_on(tmp_path)
    in_volts = amp.plan("Holding", -0.06, "V", step=0.025, expect=0)
    assert (in_volts.outcome, in_volts.steps) == ("planned", amp.plan("Holding", -60, "mV", step=25).steps)
    amp.set("Holding", -20, "mV")
    refused(amp, lambda: amp.set("Holding", -0.04, "V", expect=-20), "Commander no longer shows -20 V for Holding: it shows -0.02 V")
    refused(amp, lambda: amp.set("Holding", -40, "mV", step=5, expect=-0.02), "Commander no longer shows -0.02 mV for Holding: it shows -20 mV")
    assert amp.set("Holding", -40, "mV", step=5, expect=-20).steps == (-0.025, -0.03, -0.035, -0.04)


def test_the_first_timeout_stops_the_steps_as_unknown_and_is_never_sent_again(tmp_path):
    amp = amp_on(tmp_path)
    tried = before_call(amp, "SetHolding", fails(6005, "MSGTIMEOUT"), nth=2)
    with pytest.raises(WriteError, match=r"did not answer in time.*\(step 2 of 3; the last confirmed -25 mV\)") as raised:
        amp.set("Holding", -60, "mV", step=25)
    assert (raised.value.write.outcome, raised.value.write.target) == ("unknown", -0.05)
    assert tried == ["SetHolding", "SetHolding"]
    assert (logged(amp)[-1]["outcome"], logged(amp)[-1]["error_code"]) == ("unknown", 6005)


def test_a_button_that_timed_out_waits_its_longest_duration_then_reads_and_never_presses_again(tmp_path, monkeypatch):
    amp = amp_on(tmp_path)
    waited = []
    monkeypatch.setattr(amplifier.time, "sleep", waited.append)
    tried = before_call(amp, "Zap", fails(6005, "MSGTIMEOUT"))
    with pytest.raises(WriteError, match="did not answer in time") as raised:
        amp.press("Zap")
    assert (raised.value.write.outcome, raised.value.write.after, raised.value.write.also, tried, waited) == ("unknown", None, {}, ["Zap"], [0.05])
    assert logged(amp)[-1]["error_code"] == 6005


@pytest.mark.parametrize("call, function, label", [
    (lambda amp: amp.set("Holding", -60, "mV"), "SetHolding", "Holding"),
    (lambda amp: amp.enable("Seal Test", True), "SetTestSignalEnable", "Seal Test"),
    (lambda amp: amp.press("Auto Output Zero"), "AutoOutputZero", "Auto Output Zero"),
], ids=["set", "enable", "press"])
def test_a_call_commander_refuses_is_an_error_and_stops(tmp_path, call, function, label):
    amp = amp_on(tmp_path)
    tried = before_call(amp, function, fails(6004, "AXMCCMSG: Invalid parameter specified."))
    with pytest.raises(WriteError, match=rf"^{label}: error: AXMCCMSG: Invalid parameter specified. \(6004\)$"):
        call(amp)
    assert tried == [function]
    assert [(line["outcome"], line["error_code"]) for line in logged(amp)] == [("error", 6004)]


def test_a_readback_that_fails_after_the_set_is_unknown(tmp_path):
    amp = amp_on(tmp_path)
    before_call(amp, "SetHolding", lambda: amp.commander.dll.fail_at(2))  # the call after the Set: its readback
    with pytest.raises(WriteError, match=r"^Holding: unknown: sent, but the readback failed: GetHolding failed: MSGTIMEOUT \(6005\)$") as raised:
        amp.set("Holding", -60, "mV")
    assert (raised.value.write.target, raised.value.write.after) == (-0.06, None)
    assert sets(amp.commander) == [("SetHolding", -0.06)]
    assert [(line["outcome"], line["error_code"]) for line in logged(amp)] == [("unknown", 6005)]


def test_a_checkbox_that_does_not_read_back_raises(tmp_path):
    amp = amp_on(tmp_path)
    after_each_set(amp, lambda stem, value: amp.commander.dll.values.update({("V-Clamp", stem): False}))
    with pytest.raises(WriteError, match=r"^Seal Test: mismatch: Commander kept False, not True$") as raised:
        amp.enable("Seal Test", True)
    assert (raised.value.write.before, raised.value.write.after) == (False, False)
    assert logged(amp)[-1]["outcome"] == "mismatch"


def test_a_writes_t_is_when_its_first_call_was_sent_the_t_of_its_first_log_line(tmp_path, monkeypatch):
    # one meaning for every call, so a Write finds its lines in the log, and in trial_record
    ticks = iter(range(1000))
    monkeypatch.setattr(amplifier, "now", lambda: f"t{next(ticks)}")
    amp = amp_on(tmp_path)
    mark = 0
    for call in (lambda: amp.set("Holding", -60, "mV"), lambda: amp.set("Holding", -40, "mV", step=10),
                 lambda: amp.enable("Seal Test", True), lambda: amp.make_safe()[0], lambda: amp.press("Auto Output Zero"),
                 lambda: amp.set_mode("I-Clamp")):
        write = call()
        lines, mark = amp.writes_since(mark)
        assert write.t == lines[0]["t"]
    assert len(lines) == 4  # set_mode: two SetModes, then the new mode's stale signals refreshed
    before_call(amp, "SetHolding", fails(6005, "MSGTIMEOUT"), nth=2)
    with pytest.raises(WriteError) as raised:  # a step sequence's WriteError: its before and t are the first step's
        amp.set("Holding", 100, "pA", step=50)
    lines, mark = amp.writes_since(mark)
    assert raised.value.write.t == lines[0]["t"] != lines[1]["t"]


# the mode


def test_v_clamp_to_i_clamp_goes_through_i_0_and_reports_what_a_snapshot_shows_changed(tmp_path):
    amp = amp_on(tmp_path)
    write = amp.set_mode("I-Clamp")
    assert (write.mode, write.before, write.target, write.steps, write.after, write.outcome) == ("V-Clamp", 0, 1, (2, 1), 1, "ok")
    changed = write.also
    assert (changed["PrimarySignal"], changed["TestSignalAmplitude"], changed["uOperatingMode"]) == ([0, 7], [0.005014102, 5.014102e-12], [0, 1])
    assert "Mode" not in changed
    assert [call for call in sets(amp.commander) if call[0] == "SetMode"] == [("SetMode", 2), ("SetMode", 1)]
    lines = [line for line in logged(amp) if line["stem"] == "Mode"]  # a line per SetMode, each read back at once (P19)
    assert [(line["before"], line["target"], line["after"], line["telegraph_checks"]) for line in lines] == [(0, 2, 2, []), (2, 1, 1, [])]
    again = amp.set_mode("i-clamp")
    assert (again.before, again.steps, again.after, again.also, again.reason) == (1, (), 1, {}, "already in I-Clamp: nothing sent")
    assert amp.set_mode("V-Clamp").steps == (2, 0)
    assert amp.set_mode("I = 0").steps == (2,)
    assert amp.set_mode("VC").steps == (0,)  # Commander's button name
    refused(amp, lambda: amp.set_mode("current clamp"), "'current clamp' is not a mode")


def test_a_mode_click_between_the_two_steps_stops_at_i_0(tmp_path):
    amp = amp_on(tmp_path)  # Selects: the checks, the snapshot before, then the second step's re-read
    before_call(amp, "SelectMultiClamp", lambda: amp.gui.mode("V-Clamp"), nth=3)
    with pytest.raises(WriteError, match="Commander changed since the write was checked: the mode was I = 0, now V-Clamp$") as raised:
        amp.set_mode("I-Clamp")
    assert raised.value.write.outcome == "refused"
    assert [call for call in sets(amp.commander) if call[0] == "SetMode"] == [("SetMode", 2)]  # the first step was sent


def ignores_set_mode_i_clamp(amp: Amplifier):
    def stay_in_i_0(stem, value):
        if (stem, value) == ("Mode", 1):
            amp.commander.dll.set_mode(2)

    after_each_set(amp, stay_in_i_0)


@pytest.mark.parametrize("fail, outcome, says", [
    (lambda amp: before_call(amp, "SetMode", fails(6005, "MSGTIMEOUT"), nth=2), "unknown", "Commander did not answer in time"),
    (ignores_set_mode_i_clamp, "mismatch", "Commander kept 2, not 1"),
], ids=["timeout", "not-taken"])
def test_a_set_mode_that_does_not_take_stops_and_may_leave_i_0(tmp_path, fail, outcome, says):
    amp = amp_on(tmp_path)
    fail(amp)
    with pytest.raises(WriteError, match=f"^Mode: {outcome}: {says}") as raised:
        amp.set_mode("I-Clamp")
    assert (raised.value.write.before, raised.value.write.target) == (2, 1)  # the step from I = 0
    assert amp.get("Mode") == "I = 0"
    assert [(line["target"], line["outcome"]) for line in logged(amp)] == [(2, "ok"), (1, outcome)]


@pytest.mark.parametrize("call", [
    lambda amp: amp.set_mode("I-Clamp"),
    lambda amp: amp.press("Auto Output Zero"),
], ids=["set_mode", "press"])
def test_a_snapshot_that_fails_before_set_mode_or_a_button_refuses(tmp_path, call):
    amp = amp_on(tmp_path)
    before_call(amp, "GetMeterIrmsEnable", fails(6005, "MSGTIMEOUT"))  # read by snapshots only
    refused(amp, lambda: call(amp), r"no snapshot before it: MSGTIMEOUT \(6005\)$")


def test_a_snapshot_that_fails_after_set_mode_still_returns_ok(tmp_path):
    # the mode was read back from the API and the telegraph; only the report of what changed is missing
    amp = amp_on(tmp_path)
    before_call(amp, "GetMeterIrmsEnable", fails(6005, "MSGTIMEOUT"), nth=2)
    write = amp.set_mode("I-Clamp")
    assert (write.outcome, write.after, write.also) == ("ok", 1, {})
    assert write.reason == "in I-Clamp, but the snapshot after it failed: MSGTIMEOUT (6005)"
    assert amp.get("Mode") == "I-Clamp"


def test_a_snapshot_that_fails_after_a_button_is_unknown(tmp_path):
    amp = amp_on(tmp_path)
    before_call(amp, "GetMeterIrmsEnable", fails(6005, "MSGTIMEOUT"), nth=2)
    with pytest.raises(WriteError, match=r"^Auto Output Zero: unknown: pressed, but the snapshot after it failed: MSGTIMEOUT \(6005\)$") as raised:
        amp.press("Auto Output Zero")
    assert (raised.value.write.after, raised.value.write.also) == (None, {})
    assert names(amp).count("AutoOutputZero") == 1
    assert [(line["outcome"], line["error_code"]) for line in logged(amp)] == [("unknown", 6005)]


def test_stale_signals_are_refreshed_first_and_logged(tmp_path):
    amp = amp_on(tmp_path, STALE)
    amp.set("Primary Output Gain", 5, "x")
    assert sets(amp.commander) == [("SetPrimarySignal", 0), ("SetSecondarySignal", 1), ("SetPrimarySignalGain", 5.0)]
    refreshes = [line for line in logged(amp) if line["reason"] and line["reason"].startswith("refresh_signals: secondary signal")]
    assert [line["stem"] for line in refreshes] == ["PrimarySignal", "SecondarySignal"]
    assert amp.snapshot()["disagreements"] == []
    amp.set("Primary Output Gain", 2, "x")
    assert len(sets(amp.commander)) == 4  # fresh now: no refresh


def test_a_refresh_that_times_out_is_unknown_and_both_its_lines_are_logged(tmp_path):
    amp = amp_on(tmp_path, STALE)
    before_call(amp, "SetSecondarySignal", fails(6005, "MSGTIMEOUT"))
    with pytest.raises(WriteError, match=r"^Secondary Output: unknown: Commander did not answer in time.* \(refresh_signals: secondary signal") as raised:
        amp.set("Primary Output Gain", 5, "x")
    assert (raised.value.write.outcome, raised.value.write.user_value) == ("unknown", "Membrane Potential")
    lines = logged(amp)
    assert [(line["stem"], line["outcome"], line["error_code"]) for line in lines] == [("PrimarySignal", "ok", None), ("SecondarySignal", "unknown", 6005)]
    assert sets(amp.commander) == [("SetPrimarySignal", 0)]  # the gain never sent


def test_after_a_mode_change_the_new_modes_signals_are_refreshed(tmp_path):
    amp = amp_on(tmp_path)  # I-Clamp's signals not set since the fake started: the telegraph's are V-Clamp's
    amp.set_mode("I-Clamp")
    assert sets(amp.commander)[-2:] == [("SetPrimarySignal", 7), ("SetSecondarySignal", 8)]
    assert amp.snapshot()["disagreements"] == []


# buttons


def test_a_button_returns_what_the_snapshot_shows_changed(tmp_path):
    amp = amp_on(tmp_path)
    write = amp.press("Auto Output Zero")
    assert (write.label, write.stem, write.outcome) == ("Auto Output Zero", "AutoOutputZero", "ok")
    assert (write.before, write.target, write.after, write.steps, write.also) == (None, None, None, (), {"OutputZeroEnable": [False, True]})
    assert [name for name in names(amp) if not name.startswith(("Get", "Select"))] == ["AutoOutputZero"]
    refused(amp, lambda: amp.press("Auto Bridge Balance"), "Auto Bridge Balance is not in V-Clamp: Commander has it in I-Clamp")
    refused(amp, lambda: amp.press("Holding"), re.escape('Holding is a value, not a button: set("Holding", value, "mV"), or enable("Holding", on)'))


@pytest.mark.parametrize("snapshot, other", [(VCLAMP, ICLAMP), (ICLAMP, VCLAMP), (FAKE / "i0.json", VCLAMP)])
def test_reset_to_program_defaults_is_refused_in_every_mode(tmp_path, snapshot, other):
    # its confirm dialog may block every later call (not tried), and it was never pressed on Commander or the fake
    amp = amp_on(tmp_path, snapshot, other)
    write = refused(amp, lambda: amp.press("Reset to Program Defaults"), "press it in Commander's window; ommm does not")
    assert write.reason == amplifier.RESET


# reads


def test_a_snapshot_makes_no_set_or_action_call(tmp_path):
    amp = amp_on(tmp_path)
    amp.snapshot()
    assert {name for name in names(amp) if not name.startswith("Get")} == {"SelectMultiClamp"}


def test_get_refuses_a_button_and_a_control_the_mode_lacks(tmp_path):
    amp = amp_on(tmp_path)
    with pytest.raises(ValueError, match="Zap is a button, with nothing to read"):
        amp.get("Zap")
    with pytest.raises(NotApplicable, match="Bridge Balance is not in V-Clamp"):
        amp.get("Bridge Balance", "MΩ")
    with pytest.raises(NotApplicable, match="^Tuning Amplitude is not in V-Clamp: Commander has it in I-Clamp; in V-Clamp it is Seal Test Amplitude$"):
        amp.get("Tuning Amplitude", "pA")


def test_get_reads_a_checkbox_by_the_name_enable_takes_after_any_label(tmp_path):
    amp = amp_on(tmp_path)
    amp.enable("Seal Test", True)
    assert (amp.get("Seal Test"), amp.get("seal test"), amp.get("TestSignalEnable")) == (True, True, True)
    assert amp.get("Rs Compensation") is False
    assert amp.get("Holding", "mV") == 0.0  # the label first: Holding is the value, its checkbox HoldingEnable
    assert amp.get("HoldingEnable") is False
    with pytest.raises(ValueError, match="Seal Test takes no unit"):
        amp.get("Seal Test", "mV")


@pytest.mark.parametrize("name", ["Tuning", "BridgeBalEnable"])
def test_get_of_a_checkbox_the_mode_lacks_is_not_applicable_by_either_name(tmp_path, name):
    # as a value the mode lacks is, so a loop over every control can skip it; ValueError is for unknown names
    amp = amp_on(tmp_path)
    with pytest.raises(NotApplicable, match=f"^{name} is not in V-Clamp: Commander has it in I-Clamp$"):
        amp.get(name)


def test_an_output_signal_is_named_in_any_case(tmp_path):
    amp = amp_on(tmp_path)
    assert amp.set("Primary Output", "membrane potential", expect="MEMBRANE CURRENT").outcome == "ok"
    assert amp.get("Primary Output") == "Membrane Potential"
    amp.gui.set("Primary Output", "membrane current")
    assert amp.get("Primary Output") == "Membrane Current"


def test_an_unknown_name_suggests_the_nearest_label(tmp_path):
    amp = amp_on(tmp_path)
    says = r"'Holdng' is not a Commander control ommm knows: did you mean 'Holding'\? Every label: docs/coming-from-commander.md"
    refused(amp, lambda: amp.set("Holdng", -60, "mV"), says)
    refused(amp, lambda: amp.press("Auto Bridge Balanse"), "did you mean 'Auto Bridge Balance'")
    with pytest.raises(ValueError, match=says):
        amp.get("Holdng", "mV")


# shared control with the person at Commander's window


def test_a_gui_change_between_two_writes_is_read_never_overwritten(tmp_path):
    amp = amp_on(tmp_path)
    amp.set("Holding", -60, "mV")
    amp.gui.set("Primary Output Gain", 10, "x")
    amp.gui.set("Holding", -40, "mV")
    write = amp.set("Seal Test Amplitude", 10, "mV")
    assert (amp.get("Primary Output Gain", "x"), amp.get("Holding", "mV")) == (10.0, -40.0)
    assert amp.set("Holding", -50, "mV").before == -0.04
    assert write.outcome == "ok"


def test_a_mode_clicked_in_the_window_is_seen_at_the_next_call(tmp_path):
    amp = amp_on(tmp_path)
    amp.gui.mode("I = 0")
    amp.gui.mode("I-Clamp")
    refused(amp, lambda: amp.set("Holding", -60, "mV"), "Holding in I-Clamp is a current: pA or nA")
    assert amp.get("Mode") == "I-Clamp"


def test_an_untelegraphed_gui_change_shows_at_the_next_read(tmp_path):
    amp = amp_on(tmp_path, ICLAMP, VCLAMP)
    amp.gui.set("Bridge Balance", 12, "MΩ")
    assert amp.get("Bridge Balance", "MΩ") == 12.0


# connecting


def test_fake_serves_a_snapshot_file_on_the_headstage_asked_for(tmp_path):
    amp = Amplifier(2, log_dir=tmp_path, fake=VCLAMP, other_tab=ICLAMP)
    assert (amp.headstage, amp.serial) == (2, "00123456")
    record = amp.snapshot()["headstage"]  # the full record: model, serial, com_port, device, channel
    assert (record["serial"], record["channel"]) == ("00123456", 2)
    assert amp.log_path == tmp_path / "00123456_headstage2.jsonl"
    amp.gui.show_tab("I-Clamp")  # the snapshot on the other tab
    assert amp.gui.dll.shown == "I-Clamp"


@pytest.mark.parametrize("given, says", [
    ({"fake": VCLAMP, "commander": "a handle"}, r"^give fake= \(a snapshot\) or commander=, not both$"),
    ({"other_tab": ICLAMP}, r"^other_tab= is the fake's other tab: give fake= too$"),
    ({"commander": "on headstage 2"}, r"^the commander given is on headstage 2, not 1: pass headstage=2$"),
])
def test_an_amplifier_is_refused_what_it_cannot_use(tmp_path, given, says):
    fake = FakeCommander(VCLAMP, other_tab=ICLAMP, other_headstage=VCLAMP)
    given = {key: {"a handle": fake, "on headstage 2": fake.handle(2)}.get(value, value) for key, value in given.items()}
    with pytest.raises(ValueError, match=says):
        Amplifier(log_dir=tmp_path, **given)


def test_the_gui_follows_each_new_commander_after_a_load_and_a_reconnect(tmp_path, monkeypatch):
    amp = amp_on(tmp_path)
    monkeypatch.setattr(amplifier.time, "sleep", lambda s: None)
    monkeypatch.setattr(amplifier, "RECONNECT_S", 0)
    assert amp.load_config(FAKE / "synthetic.mcc", confirmed=True).outcome == "ok"
    amp.gui.set("Holding", -70, "mV")  # the person at the window of the Commander now running
    assert amp.get("Holding", "mV") == -70
    running = amp.process
    process.quit_commander(running)
    process.launch_commander(process=running)
    amp.reconnect()
    amp.gui.set("Holding", -50, "mV")
    assert amp.get("Holding", "mV") == -50


def test_only_an_amplifier_on_the_fake_has_a_gui(tmp_path):
    amp = amp_on(tmp_path)
    amp.process = process.PROCESS  # as on Windows: Commander's program
    with pytest.raises(AttributeError, match=r"^only an Amplifier on the fake \(fake=FILE\) has a gui: on Commander, use its window$"):
        amp.gui.show_tab("I-Clamp")


def test_reconnect_waits_for_commander_and_takes_a_new_handle(tmp_path, monkeypatch):
    amp = amp_on(tmp_path)
    running = amp.commander.dll.process
    monkeypatch.setattr(amplifier, "RECONNECT_S", 0)
    process.quit_commander(running)
    with pytest.raises(CommanderError, match="Commander is not running"):
        amp.reconnect()
    process.launch_commander(process=running)
    process.wait_for_api(running)  # the program that started it took its handle
    amp.reconnect()
    assert names(amp)[:3] == ["SetTimeOut", "FindFirstMultiClamp", "FindNextMultiClamp"]  # a new handle, as Commander()
    assert amp.set("Holding", -60, "mV").outcome == "ok"


def test_reconnect_right_after_a_launch_takes_the_first_handle(tmp_path, monkeypatch):
    # no other program took a handle first; Commander's window is there once it starts
    amp = amp_on(tmp_path)
    running = amp.commander.dll.process
    monkeypatch.setattr(amplifier, "RECONNECT_S", 0)
    process.quit_commander(running)
    process.launch_commander(process=running)
    amp.reconnect()
    assert amp.set("Holding", -60, "mV").outcome == "ok"


def test_reconnect_makes_a_new_commander_on_windows(tmp_path, monkeypatch):
    # Process.connect(): a new Commander(), tried every 2 s until one answers, the old one closed
    first, second = FakeCommander(VCLAMP, other_tab=ICLAMP), FakeCommander(VCLAMP, other_tab=ICLAMP)
    answers = [CommanderError("FindFirstMultiClamp", 6002, "Commander not found"), second]

    def commander(headstage):
        assert headstage == 1
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(process, "Commander", commander)
    monkeypatch.setattr(first.dll, "commander_pid", lambda: 1000)
    waited, closed = [], []
    monkeypatch.setattr(amplifier.time, "sleep", waited.append)
    monkeypatch.setattr(first.dll, "close", lambda: closed.append("first"))
    amp = Amplifier(log_dir=tmp_path, commander=first)
    amp.process = process.PROCESS  # a handle on Windows: Commander's program
    amp.reconnect()
    assert (amp.commander, closed, waited) == (second, ["first"], [2])
    assert amp.set("Holding", -60, "mV").outcome == "ok"
    assert sets(first) == []


def test_with_amplifier_closes_the_handle_at_the_end_even_after_an_error(tmp_path, monkeypatch):
    closed = []
    with pytest.raises(WriteError, match="^Holding in V-Clamp is"):
        with amp_on(tmp_path) as amp:
            monkeypatch.setattr(amp.commander.dll, "close", lambda: closed.append(True))
            assert amp.set("Holding", -60, "mV").outcome == "ok"
            amp.set("Holding", 2000, "mV")
    assert closed == [True]


def test_the_write_error_carries_the_write_and_logs_it(tmp_path):
    amp = amp_on(tmp_path)
    with pytest.raises(WriteError) as raised:
        amp.set("Holding", 2000, "mV")
    assert str(raised.value) == raised.value.write.reason  # a refusal is its reason alone
    line = json.loads(amp.log_path.read_text().splitlines()[-1])
    assert (line["label"], line["outcome"], line["user_value"], line["unit"]) == ("Holding", "refused", 2000, "mV")


@pytest.mark.parametrize("call, says", [
    (lambda amp: amp.set(-60, "mV"), "-60 is not a Commander control ommm knows"),
    (lambda amp: amp.set_mode(0), "0 is not a mode"),
    (lambda amp: amp.press(None), "None is not a Commander control ommm knows"),
    (lambda amp: amp.enable(3, True), "3 is not a Commander control ommm knows"),
])
def test_a_name_that_is_not_text_is_refused_as_any_unknown_name(tmp_path, call, says):
    amp = amp_on(tmp_path)
    refused(amp, lambda: call(amp), says)


def test_plan_returns_a_refused_write_for_a_name_that_is_not_text(tmp_path):
    assert amp_on(tmp_path).plan(-60, "mV").outcome == "refused"


def test_step_and_expect_are_never_positional(tmp_path):
    with pytest.raises(TypeError):
        amp_on(tmp_path).set("Holding", -40, "mV", (10, "mV"))


def test_a_failed_read_while_checking_a_write_is_a_refusal(tmp_path):
    # the check's reason is in hand when the checkbox read fails: the refusal replaces it
    amp = ommm.Amplifier(log_dir=tmp_path, fake=FAKE / "vclamp.json")
    amp.commander.dll.fail_at(5)
    write = refused(amp, lambda: amp.set("Holding", -10, "mV"), "could not read")
    assert "MSGTIMEOUT" in write.reason


def test_a_failed_api_call_names_the_call(tmp_path):
    amp = ommm.Amplifier(log_dir=tmp_path, fake=FAKE / "vclamp.json")
    amp.commander.dll.fail_at(1)
    with pytest.raises(CommanderError, match=r"^SelectMultiClamp failed: MSGTIMEOUT \(6005\)$"):
        amp.snapshot()
