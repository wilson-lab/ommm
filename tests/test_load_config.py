"""Amplifier.load_config on the fake's FakeProcess, and the .mcc file code (ommm.mcc) on a synthetic file: the plan
sends nothing, a load relaunches Commander with a patched copy and checks it, every refusal comes before Commander
is closed, a start that did not apply the file is followed by one more, and a Commander that does not close, start or
answer is reported, never retried."""

import json
import re
from pathlib import Path

import pytest
from conftest import from_matlab, logged, refused

import ommm
from ommm import Amplifier, WriteError, amplifier, mcc
from ommm.commander import CommanderError
from ommm.testing import FakeCommander, FakeProcess

DATA = Path(__file__).parent / "data"
FAKE = ommm.EXAMPLES / "fake"  # the snapshots and the test .mcc the package ships
VCLAMP, ICLAMP = FAKE / "vclamp.json", FAKE / "iclamp.json"  # both at 5 GΩ, V-Clamp active, serial 00123456
MCC = FAKE / "synthetic.mcc"  # CRLF, both tabs at 5 GΩ, V-Clamp
TO_500M = [("Feedback Resistor", 500, "MΩ", "V-Clamp")]
BACK = [("Feedback Resistor", 5, "GΩ", "V-Clamp")]
RIG = DATA / "rig" / "2026-10-23-loadcfg" / "p24_load_config_500m.json"  # 500 MΩ and back on the model cell, CELL
RST = "ELCTRD_HSTAGE_RST_RNG"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(amplifier.time, "sleep", lambda s: None)  # the time module ommm.process waits with too


@pytest.fixture
def fake():
    return FakeCommander(VCLAMP, other_tab=ICLAMP)


def with_text(path: Path, text: str) -> Path:
    mcc.write(path, text)
    return path


def changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    return [(old, new) for old, new in zip(before.splitlines(keepends=True), after.splitlines(keepends=True)) if old != new]


def the_copy(tmp_path: Path) -> Path:
    """The one copy a load wrote, as Commander was given it."""
    (copy,) = (tmp_path / "mcc").iterdir()
    return copy.resolve()


# the file code


def test_values_are_read_by_section_as_written():
    held = mcc.values(mcc.read(MCC))
    assert held[("MC700_CHANNEL1_VCLAMP", RST)] == held[("MC700_CHANNEL1_ICLAMP", RST)] == "2"
    assert held[("MC700_CHANNEL1", "MODE_SLCT")] == "0"
    assert held[("MC700_GLOBAL", "SYSTEM_AUTOCOMP_AMP_FAST")] == "-2.50000000e-002"  # MSVC's %e, kept as written


@pytest.mark.parametrize("ending", ["\r\n", "\n"])
def test_a_patch_changes_one_line_of_one_section_and_keeps_every_other_byte(ending):
    text = mcc.read(MCC).replace("\r\n", ending)
    out = mcc.patched(text, "MC700_CHANNEL1_VCLAMP", RST, "1")
    assert changed_lines(text, out) == [(f"AXMCD_FIELD_{RST}=2{ending}", f"AXMCD_FIELD_{RST}=1{ending}")]
    assert len(out) == len(text) and out.count(ending) == text.count(ending)
    assert mcc.values(out)[("MC700_CHANNEL1_ICLAMP", RST)] == "2"


def test_a_patch_refuses_a_key_the_section_does_not_hold():
    with pytest.raises(ValueError, match=r"the file has no AXMCD_FIELD_INPUT_DCOFST_VCLAMP in \[MC700_CHANNEL1_ICLAMP\]"):
        mcc.patched(mcc.read(MCC), "MC700_CHANNEL1_ICLAMP", "INPUT_DCOFST_VCLAMP", "0")


# the plan


def test_without_confirmed_it_plans_and_sends_writes_and_logs_nothing(fake, tmp_path):
    running = fake.dll.process
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    plan = amp.load_config(MCC, changes=TO_500M)
    assert (plan.label, plan.outcome, plan.mode, plan.user_value, plan.steps) == ("Load Configuration", "planned", "V-Clamp", str(MCC), ())
    assert plan.before == {"Mode": 0, "FeedbackResistorVC1": 2, "FeedbackResistorIC1": 2}
    assert plan.target == {"Mode": 0, "FeedbackResistorVC1": 1, "FeedbackResistorIC1": 2}
    copy = re.search(r"starts again with (\S+), about 15 s", plan.reason).group(1)
    assert Path(copy).parent == (tmp_path / "mcc").resolve() and copy.endswith("_synthetic_vc-feedback-resistor-500-mohm.mcc")  # the copy says what the change set
    assert plan.reason == (
        "Feedback Resistor (V-Clamp) 5 GΩ → 500 MΩ; the mode stays V-Clamp; Feedback Resistor (I-Clamp) stays 5 GΩ. "
        f"Commander closes and starts again with {copy}, about 15 s without Commander; every handle on it dies. "
        "The file also sets everything else it holds: Holding, compensation and the output signals (set those after "
        "with set and enable) and the Options pages (only another file changes those).")
    assert (running.started, running.pid, logged(amp)) == ([], 1000, [])
    assert not (tmp_path / "mcc").exists()
    assert not [name for name, *_ in fake.dll.calls if name.startswith("Set")]


def test_a_new_i_clamp_feedback_resistor_says_the_dac_command_scales_with_it(fake, tmp_path):
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    plan = amp.load_config(MCC, changes=[("Feedback Resistor", 500, "MΩ", "I-Clamp")])
    assert plan.reason.startswith("Feedback Resistor (I-Clamp) 5 GΩ → 500 MΩ; the mode stays V-Clamp; Feedback Resistor "
                                  "(V-Clamp) stays 5 GΩ. I-Clamp External Command Sensitivity follows the I-Clamp feedback "
                                  "resistor (40 pA/V at 5 GΩ, 400 pA/V at 500 MΩ): every DAQ current command scales with it.")
    assert "External Command" not in amp.load_config(MCC, changes=TO_500M).reason


def test_the_plan_says_holding_comes_back_off_when_it_is_on(fake, tmp_path):
    """Before the question is answered, not only after the load: the cell steps when Holding goes off."""
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    amp.set("Holding", -20, "mV")
    amp.enable("Holding", True)
    plan = amp.load_config(MCC, changes=TO_500M)
    assert plan.outcome == "planned"
    assert plan.reason.startswith("Feedback Resistor (V-Clamp) 5 GΩ → 500 MΩ; the mode stays V-Clamp; Feedback Resistor "
                                  "(I-Clamp) stays 5 GΩ. Holding is on at -20 mV now; Commander comes back with it off, "
                                  "at the file's level: after the load, set Holding to -20 mV, then turn it on. Commander "
                                  "closes and starts again with ")


@pytest.mark.parametrize("confirmed", ["no", "yes", 1, "True"])
def test_only_confirmed_true_loads(fake, tmp_path, confirmed):
    """Mo ran confirmed="no" on the fake and it relaunched: the confirmation is the one guard on 15 s without Commander.
    Anything but True or False is refused as loudly as a confirmed load, since it may have meant one."""
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    refused(amp, lambda: amp.load_config(MCC, changes=TO_500M, confirmed=confirmed),
            re.escape(f"confirmed is True or False, not {confirmed!r}"))
    assert fake.dll.process.started == []


def test_release_other_headstage_is_true_or_false(fake, tmp_path):
    plan = Amplifier(log_dir=tmp_path, commander=fake).load_config(MCC, changes=TO_500M, release_other_headstage=1)
    assert (plan.outcome, plan.reason) == ("refused", "release_other_headstage is True or False, not 1")


def test_changes_is_never_positional(fake, tmp_path):
    with pytest.raises(TypeError):
        Amplifier(log_dir=tmp_path, commander=fake).load_config(MCC, TO_500M)


def test_confirmed_is_never_positional(fake, tmp_path):
    with pytest.raises(TypeError):
        Amplifier(log_dir=tmp_path, commander=fake).load_config(MCC, TO_500M, True)
    assert fake.dll.process.started == []


def test_set_refuses_the_feedback_resistor_and_names_the_load_config_call(fake, tmp_path):
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    refused(amp, lambda: amp.set("Feedback Resistor", 500, "MΩ"),
            r"^Feedback Resistor changes only by restarting Commander with a \.mcc file: "
            r"load_config with the file and the change \(Feedback Resistor, 500, MΩ, V-Clamp\) shows what will change; "
            r"confirmed, it makes it \(docs/mcc\.md\)$")


def one_key(tmp_path):
    return with_text(tmp_path / "one_key.mcc", f"[MC700_CHANNEL1_VCLAMP]\r\nAXMCD_FIELD_{RST}=1\r\n"), TO_500M


def partial(tmp_path):
    text = f"[MC700_GLOBAL]\r\nAXMCD_FIELD_AUDIO_GAIN=0\r\n[MC700_CHANNEL1_VCLAMP]\r\nAXMCD_FIELD_{RST}=1\r\n"
    return with_text(tmp_path / "partial.mcc", text), TO_500M


def a_snapshot(tmp_path):
    return with_text(tmp_path / "vclamp.json", (FAKE / "vclamp.json").read_text()), ()


def no_iclamp_key(tmp_path):
    text = mcc.read(MCC).replace(f"[MC700_CHANNEL1_ICLAMP]\r\nAXMCD_FIELD_{RST}=2\r\n", "[MC700_CHANNEL1_ICLAMP]\r\n")
    return with_text(tmp_path / "no_iclamp_key.mcc", text), ()


def i_clamp_file(tmp_path):
    return with_text(tmp_path / "iclamp.mcc", mcc.read(MCC).replace("MODE_SLCT=0", "MODE_SLCT=1")), ()


def one_value(name, section, key, value):
    """synthetic.mcc with one value changed, as by hand or by a script."""
    return lambda tmp_path: (with_text(tmp_path / name, mcc.patched(mcc.read(MCC), section, key, value)), ())


@pytest.mark.parametrize("make, says", [
    (one_key, r"^one_key\.mcc is not a settings file Commander saved: load one saved with Save Configuration \(F5\)$"),
    (a_snapshot, r"^vclamp\.json is not a settings file Commander saved: load one saved with Save Configuration \(F5\)$"),
    (partial, (r"^partial\.mcc is not a whole settings file: it does not set the mode, Feedback Resistor \(I-Clamp\), and "
               r"Commander refused a partial file with a dialog that blocked it until clicked: load a whole file Commander "
               r"saved \(Save Configuration, F5\)$")),
    (no_iclamp_key, (r"^no_iclamp_key\.mcc is not a whole settings file: it does not set Feedback Resistor \(I-Clamp\), "
                    r".*: load a whole file Commander saved \(Save Configuration, F5\)$")),
    # a change to a key the file lacks is refused with the file, before it is patched (mcc.patched raises ValueError)
    (lambda tmp_path: (no_iclamp_key(tmp_path)[0], [("Feedback Resistor", 500, "MΩ", "I-Clamp")]),
     r"^no_iclamp_key\.mcc is not a whole settings file: it does not set Feedback Resistor \(I-Clamp\), "),
    (i_clamp_file, (r"the file starts Commander in I-Clamp; ommm goes between V-Clamp and I-Clamp through I = 0: "
                   r'set_mode\("I = 0"\) first, then load$')),
    (lambda tmp_path: (tmp_path / "missing.mcc", ()), r"cannot read .*missing\.mcc"),
    (one_value("ic_50g.mcc", "MC700_CHANNEL1_ICLAMP", RST, "3"),
     r"^ic_50g\.mcc: Feedback Resistor in I-Clamp is one of 50 MΩ, 500 MΩ, 5 GΩ, not 50 GΩ$"),
    (one_value("vc_7.mcc", "MC700_CHANNEL1_VCLAMP", RST, "7"),
     r"^vc_7\.mcc: Feedback Resistor in V-Clamp is one of 50 MΩ, 500 MΩ, 5 GΩ, 50 GΩ, not index 7$"),
    (one_value("mode_5.mcc", "MC700_CHANNEL1", "MODE_SLCT", "5"),
     r"^mode_5\.mcc: AXMCD_FIELD_MODE_SLCT=5 in \[MC700_CHANNEL1\] is not a mode: 0 is V-Clamp, 1 I-Clamp, 2 I = 0$"),
    (lambda tmp_path: (MCC, [("Holding", -60, "mV", "V-Clamp")]), "Holding is set through the API, not in the file"),
    (lambda tmp_path: (MCC, [("Feedback Resistr", 500, "MΩ", "V-Clamp")]),
     r"^'Feedback Resistr' is not a Commander control ommm knows: did you mean 'Feedback Resistor'\? load_config changes only"),
    (lambda tmp_path: (MCC, [("Feedback Resistor", 50, "GΩ", "I-Clamp")]),
     "Feedback Resistor in I-Clamp is one of 50 MΩ, 500 MΩ, 5 GΩ, not 50 GΩ"),
    (lambda tmp_path: (MCC, [("Feedback Resistor", 300, "MΩ", "V-Clamp")]),
     "Feedback Resistor in V-Clamp is one of 50 MΩ, 500 MΩ, 5 GΩ, 50 GΩ, not 300 MΩ"),
    (lambda tmp_path: (MCC, [("Feedback Resistor", 500, "MΩ")]),
     r'^changes is a list of \(label, value, unit, mode\), such as \[\("Feedback Resistor", 500, "MΩ", "V-Clamp"\)\]; '
     r"not \[\('Feedback Resistor', 500, 'MΩ'\)\]$"),
    (lambda tmp_path: (MCC, ("Feedback Resistor", 500, "MΩ", "V-Clamp")), r"^changes is a list of .*; not \('Feedback"),  # one change, no list
    (lambda tmp_path: (MCC, [("Feedback Resistor", 500, "MΩ", "VC1")]), r"^the change \(.*\): 'VC1' is not a mode"),
    (lambda tmp_path: (MCC, [("Feedback Resistor", "500", "MΩ", "V-Clamp")]), r"^Feedback Resistor takes a number, not '500'$"),
    (lambda tmp_path: (MCC, [("Feedback Resistor", 7.0, "MΩ", "V-Clamp")]),  # a MATLAB number
     r"^Feedback Resistor in V-Clamp is one of 50 MΩ, 500 MΩ, 5 GΩ, 50 GΩ, not 7 MΩ$"),
    (lambda tmp_path: (MCC, [("Feedback Resistor", 500, "pA", "V-Clamp")]), "Feedback Resistor in V-Clamp is a resistance"),
    (lambda tmp_path: (MCC, [("External Command Sensitivity", 400, "pA/V", "I-Clamp")]),
     (r"^'External Command Sensitivity' is not a Commander control ommm knows\. load_config changes only the Feedback "
     r"Resistor: set other Options-page settings in Commander's Options dialog and save the file "
     r"\(docs/mcc\.md#an-options-page-setting\)$")),
])
def test_every_refusal_comes_before_commander_is_closed(fake, tmp_path, make, says):
    running = fake.dll.process
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    path, changes = make(tmp_path)
    assert amp.load_config(path, changes=changes).outcome == "refused"
    write = refused(amp, lambda: amp.load_config(path, changes=changes, confirmed=True), says)
    assert (write.label, logged(amp)[-1]["outcome"]) == ("Load Configuration", "refused")
    assert (running.started, running.pid, fake.get("Mode")) == ([], 1000, 0)  # still running and answering


def test_a_load_beside_another_commander_is_refused_in_the_plan(fake, tmp_path):
    fake.dll.process.pids = lambda: [1000, 2000]
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    plan = amp.load_config(MCC, changes=TO_500M)
    assert plan.outcome == "refused" and plan.reason.startswith("2 Commanders run on this PC (processes 1000, 2000)")
    refused(amp, lambda: amp.load_config(MCC, changes=TO_500M, confirmed=True), "only when one runs")
    assert (fake.dll.process.started, fake.get("Mode")) == ([], 0)


def test_a_load_is_refused_in_the_plan_when_mc700b_exe_is_not_where_ommm_starts_it(fake, tmp_path, monkeypatch):
    """OMMM_SDK_DIR set to a copy of the SDK files alone: Commander would close and not start again."""
    monkeypatch.setenv("OMMM_SDK_DIR", str(tmp_path))
    running = fake.dll.process
    running.program_found = ommm.process.Process().program_found  # as on Windows, in a folder without MC700B.exe
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    refused(amp, lambda: amp.load_config(MCC, changes=TO_500M, confirmed=True),
            rf"^MC700B\.exe is not in {re.escape(str(tmp_path))}, where ommm starts Commander again after closing it: "
            "set OMMM_SDK_DIR to Commander's install folder$")
    assert (running.started, running.pid) == ([], 1000)


class NotTheFake:
    """The fake's process as load_config sees a real one: answering as the fake's, but not a FakeProcess."""

    def __init__(self, running):
        self.running = running

    def __getattr__(self, name):
        return getattr(self.running, name)


def test_a_fake_process_made_after_the_amplifier_is_refused(fake, tmp_path):
    # the Amplifier keeps the process it was made with: a new one would go unused, and its writes fail after a load
    running = fake.dll.process
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    with pytest.raises(ValueError, match=r"make the FakeProcess before any Amplifier or fake.handle\(n\)$"):
        FakeProcess(fake, slow=3)
    amp.load_config(MCC, changes=TO_500M, confirmed=True)
    assert amp.process is running and len(running.started) == 1


def test_a_fake_process_made_after_a_handle_is_refused(fake):
    # a handle takes the process of its moment: a new one would restart without it, and the handle never dies
    fake.handle(1)
    with pytest.raises(ValueError, match=r"before any Amplifier or fake.handle\(n\)$"):
        FakeProcess(fake, skip=1)


def test_a_refused_amplifier_does_not_hold_the_fake_process(fake, tmp_path):
    (tmp_path / "a file").write_text("x")
    with pytest.raises(ValueError, match="cannot hold the write log"):
        Amplifier(log_dir=tmp_path / "a file" / "logs", commander=fake)
    FakeProcess(fake, slow=3)


def test_a_fake_process_made_before_the_amplifier_is_the_one_it_uses(fake, tmp_path):
    running = FakeProcess(fake, slow=3)
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    amp.load_config(MCC, changes=TO_500M, confirmed=True)
    assert amp.process is running and len(running.started) == 1
    assert amp.set("Holding", -60, "mV").outcome == "ok"


def test_the_synthetic_file_loads_only_on_the_fake(fake, tmp_path):
    """Its first line says Commander did not save it: ommm never closes a real Commander for it."""
    running = fake.dll.process
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    assert amp.load_config(MCC).outcome == "planned"
    amp.process = NotTheFake(running)
    refused(amp, lambda: amp.load_config(MCC, confirmed=True),
            r"^synthetic\.mcc is a test file, not one Commander saved \(its first line says so\): ommm loads it "
            r"only on the fake; load a file Commander saved \(Save Configuration, F5\)$")
    assert (running.started, running.pid) == ([], 1000)


def test_a_load_between_v_clamp_and_i_clamp_goes_through_i_0_first(fake, tmp_path):
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    path = with_text(tmp_path / "iclamp.mcc", mcc.read(MCC).replace("MODE_SLCT=0", "MODE_SLCT=1"))
    assert amp.load_config(path).outcome == "refused"
    amp.set_mode("I = 0")
    assert amp.load_config(path).reason.startswith("the mode I = 0 → I-Clamp;")
    amp.set_mode("I-Clamp")
    refused(amp, lambda: amp.load_config(MCC, confirmed=True), "the file starts Commander in V-Clamp; ommm goes between")


def test_a_log_dir_with_a_space_is_refused_since_commander_takes_the_copy_from_there(fake, tmp_path):
    amp = Amplifier(log_dir=tmp_path / "my logs", commander=fake)
    refused(amp, lambda: amp.load_config(MCC, confirmed=True), r"Commander cannot take a path with a space: give the Amplifier a log_dir \(LogDir= in MATLAB\) without one$")


def test_ext_on_is_refused_as_for_every_write(fake, tmp_path):
    fake.gui.enable("Ext", True)
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    refused(amp, lambda: amp.load_config(MCC, confirmed=True), r"^Mode Switching is on")


# the load


def test_a_load_relaunches_commander_with_a_patched_copy_and_takes_the_new_handle(fake, tmp_path):
    running = FakeProcess(fake, slow=3)
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    write = amp.load_config(MCC, changes=TO_500M, confirmed=True)
    copy = the_copy(tmp_path)
    assert (write.outcome, write.steps) == ("ok", ())
    assert running.started == [["/S00123456", f"/C{copy}"]]
    assert changed_lines(mcc.read(MCC), mcc.read(copy)) == [(f"AXMCD_FIELD_{RST}=2\r\n", f"AXMCD_FIELD_{RST}=1\r\n")]
    assert (write.before["FeedbackResistorVC1"], write.after) == (2, write.target)
    assert write.after["FeedbackResistorVC1"] == 1 and "FeedbackResistorVC1" not in write.also
    assert write.also["dScaleFactor"] == [5.0, 0.5]  # Membrane Current: 5 V/nA at 5 GΩ, 0.5 at 500 MΩ
    assert write.reason.startswith(f"Commander restarted with {copy} (process 1000 → 1001): every handle on it from before died")
    assert amp.get("Feedback Resistor", "MΩ") == 500
    with pytest.raises(CommanderError) as raised:
        fake.get("Mode")  # the handle from before the load
    assert raised.value.code == 6002
    assert amp.set("Holding", -40, "mV").outcome == "ok"  # on the new one


def test_a_load_says_when_commander_shows_holding_off_that_was_on_and_never_turns_it_on_itself(fake, tmp_path):
    """As the load from MATLAB on the model cell: Commander came back with Holding off at 0 mV; enable alone would
    hold 0 mV."""
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    assert "Holding" not in amp.load_config(MCC, confirmed=True).reason  # off before: nothing to say
    amp.set("Holding", -60, "mV")
    amp.enable("Holding", True)
    write = amp.load_config(MCC, confirmed=True)
    note = ("Holding was on at -60 mV before the restart; Commander came back with it off at 0 mV: set Holding to -60 mV, "
            "then turn it on")
    assert write.outcome == "ok" and write.reason.endswith(note)
    assert logged(amp)[-1]["reason"] == write.reason
    assert amp.get("HoldingEnable") is False and amp.get("Holding", "mV") == 0


def test_the_holding_note_after_a_start_that_kept_the_level_says_turn_it_on_again():
    """A start with no file, V-Clamp Holding on at -60 mV: Commander came back with it off at -60 mV (model cell
    BATH and CELL, P11 with Holding on)."""
    before = {"readings": {"Mode": 0, "Holding": -0.06, "HoldingEnable": True}}
    after = {"readings": {"Mode": 0, "Holding": -0.06, "HoldingEnable": False}}
    assert amplifier.holding_left_on(before, after) == (
        "Holding was on at -60 mV before the restart; Commander now shows it off: turn it on again")


def test_there_is_no_holding_note_in_i_0_which_applies_no_holding():
    before = {"readings": {"Mode": 2, "Holding": -2e-11, "HoldingEnable": True}}
    after = {"readings": {"Mode": 2, "Holding": -2e-11, "HoldingEnable": False}}
    assert amplifier.holding_left_on(before, after) is None


def test_a_load_from_i_0_with_i_clamp_holding_on_is_ok_and_logs_its_last_line(fake, tmp_path):
    """i0_5gohm.mcc loaded from I = 0, I-Clamp's Holding on before and off after, as a start may leave it (a guess:
    I-Clamp's was not tried): the note raised KeyError once Commander had restarted, and the last log line was lost."""
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    amp.set_mode("I-Clamp")
    amp.enable("Holding", True)
    amp.set_mode("I = 0")
    running = fake.dll.process
    start = running.start

    def start_with_i_clamp_holding_off(args):
        pid = start(args)
        running.fake.dll.values[("I-Clamp", "HoldingEnable")] = False
        return pid

    running.start = start_with_i_clamp_holding_off
    write = amp.load_config(EXAMPLES / "i0_5gohm.mcc", confirmed=True)
    assert (write.outcome, amp.get("Mode")) == ("ok", "I = 0")
    assert "Holding was on" not in write.reason and logged(amp)[-1]["reason"] == write.reason


def test_a_load_logs_each_phase_and_a_trial_record_credits_its_changes_to_ommm(fake, tmp_path):
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    before = amp.snapshot()
    amp.load_config(MCC, changes=TO_500M, confirmed=True)
    after = amp.snapshot()
    lines = logged(amp)
    load = [line for line in lines if line["label"] == "Load Configuration"]
    assert [line["reason"].split(" (")[0] for line in load[:3]] == ["closed Commander", "started Commander", "Commander"]
    assert "answered" in load[2]["reason"] and load[-1]["after"]["FeedbackResistorVC1"] == 1
    assert [line["stem"] for line in lines if line["label"] != "Load Configuration"] == ["PrimarySignal", "SecondarySignal"]
    record = ommm.trial_record(before, after, lines)
    assert {change["source"] for fields in record["changed"].values() for change in fields.values()} == {"ommm"}
    # from MATLAB, where its phase lines' null stem and after are []
    matlab = [ommm.without_matlab_empties(from_matlab(value)) for value in (before, after, lines)]
    assert ommm.trial_record(*matlab) == record


def test_a_file_in_i_clamp_changes_the_mode_and_the_refresh_after_it_sends_no_set_mode(fake, tmp_path):
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    path = with_text(tmp_path / "iclamp.mcc", mcc.read(MCC).replace("MODE_SLCT=0", "MODE_SLCT=1"))
    amp.set_mode("I = 0")
    write = amp.load_config(path, confirmed=True)
    assert (write.outcome, amp.get("Mode")) == ("ok", "I-Clamp")
    sent = [name for name, *_ in amp.commander.dll.calls if name.startswith("Set")]
    assert "SetMode" not in sent and {"SetPrimarySignal", "SetSecondarySignal"} <= set(sent)  # stale after the start
    assert amp.snapshot()["disagreements"] == []


def with_pulse(tmp_path: Path) -> Path:
    """synthetic.mcc with V-Clamp's Pulse at 5 mV and 0.5 ms, as in a file Commander saved: Commander came back
    at 0 mV and 100 µs when it started without that file."""
    pulse = "AXMCD_FIELD_TESTSIG_PULSE_AMP=5.00000000e-003\r\nAXMCD_FIELD_TESTSIG_PULSE_DUR=5.00000000e-004\r\n"
    text = mcc.read(MCC).replace("[MC700_CHANNEL1_VCLAMP]\r\n", "[MC700_CHANNEL1_VCLAMP]\r\n" + pulse)
    return with_text(tmp_path / "pulse.mcc", text)


def test_a_start_without_the_file_is_logged_and_followed_by_one_more(fake, tmp_path):
    """As at 16:16 on 2026-10-27: a 50 GΩ file, Commander back at 5 GΩ with no sign of trouble but that."""
    running = FakeProcess(fake, skip=1)
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    write = amp.load_config(MCC, changes=TO_500M, confirmed=True)
    copy = the_copy(tmp_path)
    assert write.outcome == "ok" and running.started == [["/S00123456", f"/C{copy}"]] * 2
    assert amp.get("Feedback Resistor", "MΩ") == 500 and write.after["FeedbackResistorVC1"] == 1
    skipped = "Feedback Resistor (V-Clamp): the file sets 500 MΩ, Commander has 5 GΩ"
    assert write.reason.startswith(f"Commander restarted with {copy} (process 1000 → 1001 → 1002): every handle on it")
    assert write.reason.endswith(f"; process 1001 started without the file ({skipped}), so ommm closed it and started it again")
    load = [line for line in logged(amp) if line["label"] == "Load Configuration"]
    one_start = ["closed Commander", "started Commander", "Commander"]  # ... answered
    assert [line["reason"].split(" (")[0] for line in load[:-1]] == [*one_start, "Commander", *one_start]
    assert (load[3]["outcome"], load[3]["reason"]) == ("mismatch", (f"Commander (process 1001) started without {copy.name}: "
                                                                    f"{skipped}; closing it to start it with the file once more"))
    assert load[-1]["reason"] == write.reason
    assert [line["stem"] for line in logged(amp) if line["label"] != "Load Configuration"] == ["PrimarySignal", "SecondarySignal"] * 2


@pytest.mark.parametrize(("mode", "make", "says"), [
    ("V-Clamp", with_pulse, ("Pulse Amplitude (V-Clamp): the file sets 5 mV, Commander has 0 mV; Pulse Duration (V-Clamp): "
                             "the file sets 0.5 ms, Commander has 0.1 ms")),
    ("I = 0", lambda tmp_path: EXAMPLES / "i0_5gohm.mcc", ("Pulse Amplitude (I-Clamp): the file sets 5 pA, Commander has 0 pA; "
                                                           "Pulse Duration (I-Clamp): the file sets 0.5 ms, Commander has 0.1 ms")),
])
def test_a_start_without_the_file_at_its_feedback_resistors_shows_in_its_other_values(fake, tmp_path, mode, make, says):
    """As at 16:43 on 2026-10-27: the mode and the feedback resistors already the file's, Pulse back at 0 and 100 µs."""
    running = FakeProcess(fake, skip=1)
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    amp.set_mode(mode)
    write = amp.load_config(make(tmp_path), confirmed=True)
    assert write.outcome == "ok" and len(running.started) == 2
    assert f"started without the file ({says}), so ommm closed it" in write.reason


def test_a_file_commander_does_not_take_twice_is_a_mismatch_with_the_new_handle_kept(fake, tmp_path):
    running = FakeProcess(fake, skip=2)
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    with pytest.raises(WriteError, match=r"started it again; Feedback Resistor \(V-Clamp\): the file sets 500 MΩ, Commander has 5 GΩ$") as raised:
        amp.load_config(MCC, changes=TO_500M, confirmed=True)
    assert raised.value.write.outcome == "mismatch" and logged(amp)[-1]["outcome"] == "mismatch"
    assert len(running.started) == 2 and amp.get("Feedback Resistor", "MΩ") == 5000


def test_only_values_the_file_holds_are_compared():
    """The synthetic file holds no Pulse, so Commander's is not compared."""
    held = mcc.values(mcc.read(MCC))
    after = {"readings": {"Mode": 0, "FeedbackResistorVC1": 2, "FeedbackResistorIC1": 2, "PulseAmplitude": 0.0}}
    assert amplifier.unapplied({"Mode": 0, "FeedbackResistorVC1": 2, "FeedbackResistorIC1": 2}, held, after, 1) == []


def test_a_commander_that_does_not_close_is_left_running_and_nothing_is_started(fake, tmp_path):
    running = FakeProcess(fake, prompt=True)
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    with pytest.raises(WriteError, match=r"Commander was not closed: .*still running 30 s after it was asked to close") as raised:
        amp.load_config(MCC, changes=TO_500M, confirmed=True)
    assert raised.value.write.outcome == "error"
    assert (running.started, fake.get("Mode")) == ([], 0)


def test_a_commander_that_does_not_answer_after_its_start_is_reported_not_retried(fake, tmp_path, monkeypatch):
    running = FakeProcess(fake, slow=1)
    monkeypatch.setattr(ommm.process, "API_S", 0)
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    with pytest.raises(WriteError, match=r"did not answer within 0 s: a dialog in its window may be waiting for a person") as raised:
        amp.load_config(MCC, confirmed=True)
    assert raised.value.write.outcome == "unknown" and len(running.started) == 1
    assert [line["reason"].split(" (")[0] for line in logged(amp)][:2] == ["closed Commander", "started Commander"]


def test_a_commander_closed_that_does_not_start_says_to_start_it_from_its_icon(fake, tmp_path):
    """The worst outcome: Commander closed and not started again. Nothing is retried."""
    running = fake.dll.process

    def not_found(args):
        running.started.append(args)
        raise FileNotFoundError(2, "No such file or directory", "MC700B.exe")

    running.start = not_found
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    with pytest.raises(WriteError) as raised:
        amp.load_config(MCC, confirmed=True)
    assert raised.value.write.outcome == "error"
    assert raised.value.write.reason.startswith("Commander is closed and did not start: ")
    assert "start it from its icon, then reconnect()" in raised.value.write.reason
    reasons = [line["reason"] for line in logged(amp)]
    assert len(reasons) == 2 and reasons[0].startswith("closed Commander (process 1000)") and reasons[1] == raised.value.write.reason
    assert len(running.started) == 1


def test_no_snapshot_after_the_load_is_unknown_with_the_new_handle_kept(fake, tmp_path):
    running, handles = fake.dll.process, []
    connect = running.connect

    def no_snapshot():
        raise CommanderError("GetMode", 6005, "MSGTIMEOUT")

    def answers_then_fails(headstage):
        commander = connect(headstage)
        commander.snapshot = no_snapshot
        handles.append(commander)
        return commander

    running.connect = answers_then_fails
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    with pytest.raises(WriteError, match=r"; no snapshot after it: MSGTIMEOUT \(6005\)$") as raised:
        amp.load_config(MCC, changes=TO_500M, confirmed=True)
    assert raised.value.write.outcome == "unknown"
    assert amp.commander is handles[-1] is not fake


# the loads on the amplifier, replayed


def test_the_model_cells_two_loads_replay_on_the_fake_from_where_they_started(tmp_path):
    """p24_load_config_500m.py on the model cell at CELL: from the run's start, the fake plans
    each load in the same words, from and to the same mode and feedback resistors, refuses Auto Whole Cell at 5 GΩ in
    the same words, and loads ok with the same feedback resistor and scale changes. The fake's file sets nothing else, so
    the rig's other changes, the file's own values (the primary filter and Pulse), are left out."""
    rig = json.loads(RIG.read_text(encoding="utf-8"))
    fake = FakeCommander(rig["start"]["V-Clamp"], other_tab=rig["start"]["I-Clamp"])
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    with pytest.raises(WriteError) as raised:
        amp.press("Auto Whole Cell")
    assert raised.value.write.reason == rig["steps"][0]["refused"]["reason"]
    loads = [step for step in rig["steps"] if "load" in step]
    for step, change in zip(loads, (TO_500M, BACK), strict=True):
        plan = amp.load_config(MCC, changes=change)
        assert (plan.before, plan.target) == (step["plan"]["before"], step["plan"]["target"])
        # the same changes named; the rig's plan put them after the close, which the reason now leads with
        on_rig = step["plan"]["reason"].partition("dies: ")[2].partition(". ")[0].split("; ")
        assert sorted(plan.reason.partition(". ")[0].split("; ")) == sorted(on_rig)
        done = amp.load_config(MCC, changes=change, confirmed=True)
        assert done.outcome == step["write"]["outcome"] == "ok"
        on_rig = step["write"]["after"]  # schema 1: the {readings, telegraph} diff
        assert done.after == plan.target | {"FeedbackResistorVC1": on_rig["readings"]["FeedbackResistorVC1"][1]}
        assert done.also == {"dScaleFactor": on_rig["telegraph"]["dScaleFactor"]}


# the examples Commander saved (ommm.EXAMPLES / "mcc")


EXAMPLES = ommm.EXAMPLES / "mcc"


@pytest.mark.parametrize(("name", "mode"), [("vclamp_5gohm", "0"), ("iclamp_5gohm", "1"), ("i0_5gohm", "2")])
def test_each_example_is_a_whole_saved_file_differing_only_in_its_mode(name, mode):
    text = mcc.read(EXAMPLES / f"{name}.mcc")
    found = mcc.values(text)
    assert text.startswith(f"[{mcc.FIRST}]") and "\r\n" in text
    assert found[(mcc.channel(1), mcc.MODE_KEY)] == mode
    assert found[("MC700_CHANNEL1_VCLAMP", RST)] == found[("MC700_CHANNEL1_ICLAMP", RST)] == "2"  # 5 GΩ
    base = mcc.values(mcc.read(EXAMPLES / "vclamp_5gohm.mcc"))
    assert {key for key in found if found[key] != base[key]} <= {(mcc.channel(1), mcc.MODE_KEY)}


@pytest.mark.parametrize(("name", "outcome"), [("vclamp_5gohm", "planned"), ("i0_5gohm", "planned"), ("iclamp_5gohm", "refused")])
def test_from_v_clamp_the_examples_plan_except_the_i_clamp_one(fake, tmp_path, name, outcome):
    plan = Amplifier(log_dir=tmp_path, commander=fake).load_config(EXAMPLES / f"{name}.mcc")
    assert plan.outcome == outcome
    assert outcome == "planned" or "through I = 0" in plan.reason


def test_a_reading_the_snapshot_after_a_load_misses_is_a_mismatch_not_a_crash(fake, tmp_path, monkeypatch):
    # Commander has restarted by then: the load must still log, try once more and raise as a mismatch
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    taken = amplifier.Commander.snapshot

    def missing_ic_resistor(self, *args, **kwargs):
        snapshot = taken(self, *args, **kwargs)
        if fake.dll.process.started:  # only the snapshots after a start
            snapshot["readings"].pop("FeedbackResistorIC1", None)
            snapshot["errors"]["FeedbackResistorIC1"] = "GetFeedbackResistorIC1 failed: MSGTIMEOUT (6005)"
        return snapshot

    monkeypatch.setattr(amplifier.Commander, "snapshot", missing_ic_resistor)
    with pytest.raises(WriteError) as raised:
        amp.load_config(MCC, changes=TO_500M, confirmed=True)
    write = raised.value.write
    assert write.outcome == "mismatch" and write.after["FeedbackResistorIC1"] is None
    assert logged(amp)[-1]["outcome"] == "mismatch"
