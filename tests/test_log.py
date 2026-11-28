"""The write log, ommm.log: one append-only JSONL line per sent call and per refusal, read back with writes_since, and
trial_record telling ommm's changes from the ones made in Commander's window."""

import json
import os
import re
import tempfile
from pathlib import Path

import pytest
from conftest import from_matlab

import ommm
from ommm import Amplifier, WriteError, amplifier, log, mcc
from ommm.amplifier import LOG_DIR
from ommm.testing import FakeCommander

DATA = Path(__file__).parent / "data"
FAKE = ommm.EXAMPLES / "fake"  # the snapshots and the test .mcc the package ships
LINE_KEYS = {"schema", "t", "process", "commander", "serial", "headstage", "label", "stem", "mode", "before", "target", "unit",
             "user_value", "after", "also", "outcome", "reason", "error_code", "telegraph_checks", "ommm"}  # docs/writes.md, "The log and trial records"
VCLAMP, ICLAMP, I_ZERO = ("V-Clamp", "V-Clamp"), ("I-Clamp", "I-Clamp"), ("I-Clamp", "I = 0")  # (tab, mode), as log.tab_and_mode


def amp_on(tmp_path) -> Amplifier:
    return Amplifier(log_dir=tmp_path, commander=FakeCommander(FAKE / "vclamp.json", other_tab=FAKE / "iclamp.json"))


def sources(changed: dict) -> dict:
    return {(section, key): change["source"] for section, fields in changed.items() for key, change in fields.items()}


def test_one_line_per_sent_call_and_per_refusal_none_for_a_plan(tmp_path):
    amp = amp_on(tmp_path)
    amp.plan("Holding", -60, "mV")
    amp.enable("Ext", False)  # already off: nothing sent
    assert not amp.log_path.exists()
    amp.set("Holding", -60, "mV", step=30)
    with pytest.raises(WriteError):
        amp.set("Holding", 2000, "mV")
    lines = [json.loads(line) for line in amp.log_path.read_text(encoding="utf-8").splitlines()]
    assert [(line["target"], line["outcome"]) for line in lines] == [(-0.03, "ok"), (-0.06, "ok"), (None, "refused")]
    assert all(line.keys() == LINE_KEYS for line in lines)
    first = lines[0]
    assert (first["schema"], first["serial"], first["label"], first["stem"], first["mode"], first["unit"], first["user_value"]) == (
        2, "00123456", "Holding", "Holding", "V-Clamp", "mV", -60)
    assert (first["before"], first["after"], first["error_code"], first["telegraph_checks"]) == (0.0, -0.03, None, None)
    assert first["ommm"] == {key: value for key, value in ommm.provenance().items() if key != "git_error"}
    assert first["commander"] == {"pid": 1000}  # the fake's FakeProcess
    assert amp.log_path == tmp_path / "00123456.jsonl"


@pytest.mark.parametrize("value, text", [(float("nan"), "nan"), (float("inf"), "inf"), (float("-inf"), "-inf")])
def test_a_refused_nan_or_infinity_is_logged_as_text_so_the_line_is_json(tmp_path, value, text):
    # JSON has no NaN or Infinity, and readers other than Python's refuse them
    def no_constants(name):
        raise ValueError(f"{name} is not JSON")

    amp = amp_on(tmp_path)
    with pytest.raises(WriteError, match=f"^Holding takes a number, not {text}$"):
        amp.set("Holding", value, "mV")
    [line] = amp.log_path.read_text(encoding="utf-8").splitlines()
    assert json.loads(line, parse_constant=no_constants)["user_value"] == text


@pytest.mark.parametrize("make", [lambda: Amplifier(fake=FAKE / "vclamp.json"),
                                  lambda: Amplifier(commander=FakeCommander(FAKE / "vclamp.json"))], ids=["fake", "commander"])
def test_a_fake_with_no_log_dir_logs_to_a_new_temporary_folder_never_the_real_amplifiers_log(tmp_path, monkeypatch, make):
    # a fake made from your rig's snapshot has your amplifier's serial
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temp"))  # what gettempdir gives
    monkeypatch.setenv("OMMM_LOG_DIR", str(tmp_path / "amplifier"))  # the amplifier's log, set for every program on its PC
    amp = make()
    amp.set("Holding", -60, "mV")
    assert amp.log_path.exists() and amp.log_path.parent.parent == tmp_path / "temp"
    assert not amp.log_path.is_relative_to(LOG_DIR)
    assert not (tmp_path / "amplifier").exists()


def on_commander(monkeypatch, **kwargs) -> Amplifier:
    """An Amplifier made as on Commander: the fake's DLL taken for Commander's own, so it picks its log as there."""
    commander = FakeCommander(FAKE / "vclamp.json")
    monkeypatch.setattr(ommm.testing.fake, "FakeDLL", type("CommanderDLL", (), {}))
    return Amplifier(commander=commander, **kwargs)


def test_ommm_log_dir_names_the_log_folder_on_commander(tmp_path, monkeypatch):
    monkeypatch.setenv("OMMM_LOG_DIR", str(tmp_path / "logs"))
    assert on_commander(monkeypatch).log_path == (tmp_path / "logs" / "00123456.jsonl").resolve()


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_without_ommm_log_dir_the_log_goes_to_ommm_logs(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("OMMM_LOG_DIR", raising=False)
    else:
        monkeypatch.setenv("OMMM_LOG_DIR", value)
    assert on_commander(monkeypatch).log_dir == LOG_DIR.resolve()


def test_a_relative_ommm_log_dir_is_refused(monkeypatch):
    # each program would take it from its own working folder: one log per folder
    monkeypatch.setenv("OMMM_LOG_DIR", "ommm-logs")
    with pytest.raises(ValueError, match=r"^OMMM_LOG_DIR must be an absolute folder, such as C:\\ommm-logs, not ommm-logs: "):
        on_commander(monkeypatch)


def test_a_log_dir_given_wins_over_ommm_log_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OMMM_LOG_DIR", "ommm-logs")  # not even read
    assert on_commander(monkeypatch, log_dir=tmp_path / "given").log_dir == (tmp_path / "given").resolve()


def test_a_fake_that_only_reads_and_plans_leaves_no_folder(tmp_path, monkeypatch):
    # the first line logged makes the folder
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with Amplifier(commander=FakeCommander(FAKE / "vclamp.json")) as amp:
        amp.get("Holding", "mV")
        amp.snapshot()
        amp.plan("Holding", -60, "mV")
        assert amp.load_config(FAKE / "synthetic.mcc").outcome == "planned"
        assert amp.writes_since(0) == ([], 0)
    assert list(tmp_path.iterdir()) == []


def test_a_relative_log_dir_is_fixed_when_the_amplifier_is_made(tmp_path, monkeypatch):
    # MATLAB's cd moves its Python's working folder too
    (tmp_path / "trial2").mkdir()
    monkeypatch.chdir(tmp_path)
    amp = Amplifier(log_dir="ommm-logs", commander=FakeCommander(FAKE / "vclamp.json"))
    amp.set("Holding", -40, "mV")
    monkeypatch.chdir(tmp_path / "trial2")
    amp.set("Holding", -60, "mV")
    assert amp.log_path.is_absolute()
    assert list(tmp_path.rglob("*.jsonl")) == [tmp_path / "ommm-logs" / "00123456.jsonl"]
    assert [line["target"] for line in amp.writes_since(0)[0]] == [-0.04, -0.06]


def test_a_fakes_log_path_is_the_same_when_its_log_dir_is_passed_back(tmp_path, monkeypatch):
    # MATLAB's reconnect passes log_dir back; a temporary folder may be named by a path that is not its resolved one,
    # as macOS's /var/folders is /private/var/folders
    (tmp_path / "trial2").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "trial2" / ".."))
    first = Amplifier(commander=FakeCommander(FAKE / "vclamp.json"))
    assert Amplifier(log_dir=first.log_dir, commander=FakeCommander(FAKE / "vclamp.json")).log_path == first.log_path


def test_writes_since_a_mark_returns_the_new_lines_and_the_next_mark(tmp_path):
    amp = amp_on(tmp_path)
    assert amp.writes_since(0) == ([], 0)  # no log yet
    amp.set("Holding", -60, "mV")
    lines, mark = amp.writes_since(0)
    assert ([line["target"] for line in lines], mark) == ([-0.06], amp.log_path.stat().st_size)
    amp.set("Holding", -50, "mV")
    lines, mark = amp.writes_since(mark)
    assert [line["target"] for line in lines] == [-0.05]
    assert amp.writes_since(mark) == ([], mark)


def test_a_line_still_being_written_is_left_for_the_next_call(tmp_path):
    path = tmp_path / "00123456.jsonl"
    path.write_bytes(b'{"t": 1}\n{"t": 2')  # bytes: text mode would write CRLF on Windows and move the marks
    lines, mark = log.writes_since(path)
    assert (lines, mark) == ([{"t": 1}], len('{"t": 1}\n'))
    with path.open("ab") as file:
        file.write(b"}\n")
    assert log.writes_since(path, mark)[0] == [{"t": 2}]


@pytest.mark.parametrize("mark", [3, 12, 100])  # inside the first line, inside the second, past the end
def test_a_mark_that_is_not_a_line_start_names_the_log_and_the_mark(tmp_path, mark):
    # not the JSON decoder's "Expecting value: line 1 column 1 (char 0)"
    path = tmp_path / "00123456.jsonl"
    path.write_bytes(b'{"t": 1}\n{"t": 2}\n')
    with pytest.raises(ValueError, match=f"^{re.escape(str(path))}: no line starts at mark {mark}: give 0 or a mark writes_since returned"):
        log.writes_since(path, mark)
    assert log.writes_since(path, 18) == ([], 18)  # the end, as the last call returned


def test_a_second_amplifier_appends_to_the_same_log(tmp_path):
    first, second = amp_on(tmp_path), amp_on(tmp_path)
    first.set("Holding", -60, "mV")
    second.set("Holding", -50, "mV")
    first.set("Holding", -40, "mV")
    assert [line["target"] for line in second.writes_since(0)[0]] == [-0.06, -0.05, -0.04]


def test_trial_record_marks_each_change_ommm_or_gui(tmp_path):
    amp = amp_on(tmp_path)
    previous = amp.snapshot()
    amp.gui.set("Seal Test Amplitude", 10, "mV")  # a click between trials
    amp.set("Pipette Offset", 3, "mV")  # ommm, between trials
    before = amp.snapshot()
    amp.set("Holding", -60, "mV")
    amp.gui.set("Primary Output Gain", 5, "x")  # telegraphed
    amp.press("Auto Output Zero")
    after = amp.snapshot()

    record = ommm.trial_record(before, after, amp.writes_since(0)[0], previous)

    changed = record["changed"]["readings"]
    assert {key: entry["source"] for key, entry in changed.items()} == {
        "Holding": "ommm", "PrimarySignalGain": "gui", "OutputZeroEnable": "ommm"}
    assert changed["Holding"] | {"t": None} == {"before": 0.0, "after": -0.06, "source": "ommm", "t": None}
    assert changed["Holding"]["t"] == next(line["t"] for line in amp.writes_since(0)[0] if line["target"] == -0.06)
    assert record["changed"]["telegraph"]["dAlpha"]["source"] == "gui"
    between = record["between"]["readings"]
    assert {key: entry["source"] for key, entry in between.items()} == {"TestSignalAmplitude": "gui", "PipetteOffset": "ommm"}


def test_trial_record_takes_snapshots_and_lines_as_matlab_hands_them_back(tmp_path):
    # MATLAB's a.trial_record: a.snapshot()'s structs and writes_since's struct array, through jsonencode
    amp = amp_on(tmp_path)
    previous = amp.snapshot()
    amp.gui.set("Seal Test Amplitude", 10, "mV")
    before = amp.snapshot()
    amp.set("Holding", -60, "mV")
    amp.press("Auto Output Zero")  # a line with no before, target or after
    amp.set_mode("I-Clamp")
    after = amp.snapshot()
    lines = amp.writes_since(0)[0]
    record = ommm.trial_record(before, after, lines, previous)
    snapshots = [ommm.without_matlab_empties(from_matlab(snapshot)) for snapshot in (before, after, previous)]
    assert ommm.trial_record(*snapshots[:2], ommm.without_matlab_empties(from_matlab(lines)), snapshots[2]) == record


def test_a_change_ommm_made_and_the_gui_then_changed_again_is_the_guis_in_the_readings_and_the_telegraph(tmp_path):
    amp = amp_on(tmp_path)
    before = amp.snapshot()
    amp.set("Primary Output Gain", 5, "x")
    amp.gui.set("Primary Output Gain", 10, "x")
    changed = ommm.trial_record(before, amp.snapshot(), amp.writes_since(0)[0])["changed"]
    assert (changed["readings"]["PrimarySignalGain"], changed["telegraph"]["dAlpha"]) == (
        {"before": 2.0, "after": 10.0, "source": "gui"}, {"before": 2.0, "after": 10.0, "source": "gui"})


def test_what_else_a_set_changed_is_ommms_only_at_the_value_it_left(tmp_path):
    amp = amp_on(tmp_path)
    before = amp.snapshot()
    assert amp.enable("Cp Slow Tau x20", True).also == {"SlowCompTau": [1e-05, 0.0002]}  # Tau x20 multiplies Tau by 20
    amp.gui.set("Cp Slow Tau", 1000, "µs")
    changed = ommm.trial_record(before, amp.snapshot(), amp.writes_since(0)[0])["changed"]["readings"]
    assert {key: entry["source"] for key, entry in changed.items()} == {"SlowCompTau": "gui", "SlowCompTauX20Enable": "ommm"}


def test_a_press_credits_the_reading_it_changed_to_ommm_through_also(tmp_path):
    amp = Amplifier(log_dir=tmp_path, commander=FakeCommander(FAKE / "iclamp.json", other_tab=FAKE / "vclamp.json"))
    before = amp.snapshot()
    amp.press("Auto Bridge Balance")
    amp.gui.set("Holding", 50, "pA")
    lines = amp.writes_since(0)[0]
    assert [(line["before"], line["target"], line["after"], line["also"]) for line in lines] == [
        (None, None, None, {"BridgeBalEnable": [False, True]})]
    changed = ommm.trial_record(before, amp.snapshot(), lines)["changed"]["readings"]
    assert {key: entry["source"] for key, entry in changed.items()} == {"BridgeBalEnable": "ommm", "Holding": "gui"}


def test_auto_whole_cells_membrane_capacitance_in_the_telegraph_is_ommms_through_also(tmp_path):
    # no Set's stem explains dMembraneCap here: only the press's snapshot diff names it
    saved = ommm.load_snapshot(FAKE / "vclamp.json")
    saved["readings"]["FeedbackResistorVC1"] = 1  # 500 MΩ, where Whole Cell is offered
    amp = Amplifier(log_dir=tmp_path, commander=FakeCommander(saved, other_tab=FAKE / "iclamp.json"))
    before = amp.snapshot()
    amp.press("Auto Whole Cell")
    [line] = amp.writes_since(0)[0]
    cap = line["also"]["dMembraneCap"][1]
    telegraph = ommm.trial_record(before, amp.snapshot(), [line])["changed"]["telegraph"]
    assert (telegraph["dMembraneCap"]["after"], telegraph["dMembraneCap"]["source"]) == (cap, "ommm")
    assert telegraph["dSeriesResistance"]["source"] == "ommm"
    assert not log.explains(line, "telegraph", "dMembraneCap", 2 * cap, VCLAMP, VCLAMP)  # a later change is not the press's


def test_ext_that_left_another_mode_accounts_for_the_tabs_readings_as_a_mode_write_does():
    line = {"stem": "ModeSwitchEnable", "after": False, "also": {"Mode": [0, 2]}}  # on the rig Ext left I = 0
    assert log.explains(line, "readings", "Mode", 2, VCLAMP, I_ZERO) and not log.explains(line, "readings", "Mode", 1, VCLAMP, I_ZERO)
    assert log.explains(line, "readings", "Holding", 0.0, VCLAMP, I_ZERO)
    assert log.explains(line, "telegraph", "dAlpha", 10.0, VCLAMP, I_ZERO)
    assert not log.explains(line, "readings", "FeedbackResistorIC1", 2, VCLAMP, I_ZERO)  # above the tabs
    assert not log.explains(line | {"also": {}}, "readings", "Holding", 0.0, VCLAMP, I_ZERO)


def test_a_mode_write_accounts_for_a_tab_only_across_tabs_and_for_the_telegraph_only_across_modes():
    line = {"stem": "Mode", "after": 0, "also": {}, "outcome": "ok"}
    assert log.explains(line, "readings", "Holding", 0.0, ICLAMP, VCLAMP)
    assert not log.explains(line, "readings", "Holding", 0.0, VCLAMP, VCLAMP)
    assert not log.explains(line, "readings", "Holding", 0.0, ICLAMP, I_ZERO)  # one tab
    assert log.explains(line, "telegraph", "dExtCmdSens", 0.0, ICLAMP, I_ZERO)  # two modes
    assert not log.explains(line, "telegraph", "dExtCmdSens", 0.0, VCLAMP, VCLAMP)
    # a snapshot that does not tell its tab or mode: the mode write still accounts
    assert log.explains(line, "readings", "Holding", 0.0, (None, None), VCLAMP)
    assert log.explains(line, "telegraph", "dAlpha", 10.0, VCLAMP, (None, None))


def test_a_mode_change_accounts_for_the_telegraphs_mode_when_a_snapshot_could_not_read_the_apis(tmp_path):
    # GetMode failed in the snapshot after: its Mode and ModeName are missing, and the telegraph still tells the mode
    amp = amp_on(tmp_path)
    before = amp.snapshot()
    amp.set_mode("I-Clamp")
    after = amp.snapshot()
    del after["readings"]["Mode"], after["readings"]["ModeName"]
    after["errors"]["Mode"] = "GetMode failed: MSGTIMEOUT (6005)"
    assert log.tab_and_mode(after) == ICLAMP
    changed = ommm.trial_record(before, after, amp.writes_since(0)[0])["changed"]
    assert changed["readings"]["Mode"]["after"] is None
    assert sources(changed)[("telegraph", "uOperatingMode")] == "ommm"
    # GetMode failed in the snapshot before: the mode's name still takes the source of the mode the later one read
    del before["readings"]["Mode"], before["readings"]["ModeName"]
    after = amp.snapshot()
    assert sources(ommm.trial_record(before, after, amp.writes_since(0)[0])["changed"])[("readings", "ModeName")] == "ommm"
    # and an output signal's name, its reading missing from the snapshot before
    del after["readings"]["PrimarySignal"], after["readings"]["PrimarySignalName"]
    amp.set("Primary Output", "Membrane Current")
    changed = ommm.trial_record(after, amp.snapshot(), amp.writes_since(0)[0])["changed"]
    assert sources(changed)[("readings", "PrimarySignalName")] == "ommm"


def test_a_snapshots_tab_is_its_output_signals_and_its_mode_the_apis_else_the_telegraphs():
    snapshot = ommm.load_snapshot(FAKE / "vclamp.json")
    assert log.tab_and_mode(snapshot) == VCLAMP
    del snapshot["readings"]["Mode"]  # a read that failed
    assert log.tab_and_mode(snapshot) == VCLAMP
    snapshot["telegraph"] = None
    assert log.tab_and_mode(snapshot) == ("V-Clamp", None)
    del snapshot["readings"]["PrimarySignalName"]
    assert log.tab_and_mode(snapshot) == (None, None)


def test_a_mode_change_accounts_for_the_other_tabs_readings_and_the_telegraph(tmp_path):
    amp = amp_on(tmp_path)
    before = amp.snapshot()
    amp.set_mode("I-Clamp")
    after = amp.snapshot()
    record = ommm.trial_record(before, after, amp.writes_since(0)[0])
    assert set(sources(record["changed"]).values()) == {"ommm"}
    assert record["changed"]["readings"]["Mode"] == {"before": 0, "after": 1, "source": "ommm", "t": record["changed"]["readings"]["Mode"]["t"]}


def test_a_click_after_a_mode_change_and_back_is_the_guis(tmp_path):
    # both snapshots read the V-Clamp tab, so the mode changes between them account for none of its readings
    amp = amp_on(tmp_path)
    before = amp.snapshot()
    amp.set_mode("I-Clamp")
    amp.set_mode("V-Clamp")
    amp.gui.set("Primary Output Gain", 5, "x")
    changed = ommm.trial_record(before, amp.snapshot(), amp.writes_since(0)[0])["changed"]
    assert sources(changed) == {("readings", "PrimarySignalGain"): "gui", ("telegraph", "dAlpha"): "gui"}


def test_auto_pipette_offsets_change_to_the_other_tab_is_ommms_after_a_mode_change_and_back(tmp_path):
    # pressed in I-Clamp with nothing attached, it moves V-Clamp's offset into V-Clamp's Holding and turns Holding on;
    # its line holds only the I-Clamp tab's changes
    amp = amp_on(tmp_path)
    amp.set("Pipette Offset", 3, "mV")
    before = amp.snapshot()
    amp.set_mode("I-Clamp")
    amp.press("Auto Pipette Offset")
    amp.set_mode("V-Clamp")
    amp.gui.set("Seal Test Amplitude", 10, "mV")
    changed = ommm.trial_record(before, amp.snapshot(), amp.writes_since(0)[0])["changed"]
    assert sources(changed) == {("readings", "Holding"): "ommm", ("readings", "HoldingEnable"): "ommm",
                                ("readings", "PipetteOffset"): "ommm", ("readings", "TestSignalAmplitude"): "gui"}


def test_auto_pipette_offset_in_v_clamp_leaves_i_clamps_holding_to_the_window(tmp_path):
    # pressed in V-Clamp it changes the I-Clamp tab's offset and moves its Slow Current Injection level a few µV, both
    # ommm's; a click on I-Clamp's Holding after it is the window's
    amp = amp_on(tmp_path)
    amp.commander.dll.found_offsets = {"V-Clamp": 0.004, "I-Clamp": -0.002}
    amp.set_mode("I-Clamp")
    before = amp.snapshot()
    amp.set_mode("V-Clamp")
    amp.press("Auto Pipette Offset")
    amp.set_mode("I-Clamp")
    amp.gui.set("Holding", 20, "pA")
    changed = ommm.trial_record(before, amp.snapshot(), amp.writes_since(0)[0])["changed"]
    assert sources(changed) == {("readings", "PipetteOffset"): "ommm", ("readings", "SlowCurrentInjLevel"): "ommm",
                                ("readings", "Holding"): "gui"}


def test_auto_pipette_offset_accounts_for_the_other_tab_by_the_tab_it_was_pressed_on():
    # its line holds only the changes to the tab it was pressed on
    pressed_in_v_clamp = {"stem": "AutoPipetteOffset", "mode": "V-Clamp", "after": None,
                          "also": {"PipetteOffset": [0.005, -0.18]}, "outcome": "ok"}
    assert log.explains(pressed_in_v_clamp, "readings", "PipetteOffset", -0.11, ICLAMP, ICLAMP)
    assert log.explains(pressed_in_v_clamp, "readings", "SlowCurrentInjLevel", -0.05099115, ICLAMP, ICLAMP)
    assert not log.explains(pressed_in_v_clamp, "readings", "Holding", 2e-11, ICLAMP, ICLAMP)
    assert not log.explains(pressed_in_v_clamp, "readings", "SlowCurrentInjLevel", -0.05099115, VCLAMP, ICLAMP)
    pressed_in_i_clamp = pressed_in_v_clamp | {"mode": "I-Clamp", "also": {"PipetteOffset": [0.01, 0.0]}}
    assert log.explains(pressed_in_i_clamp, "readings", "Holding", -0.021, VCLAMP, VCLAMP)
    assert log.explains(pressed_in_i_clamp, "readings", "HoldingEnable", True, VCLAMP, VCLAMP)
    assert not log.explains(pressed_in_i_clamp, "readings", "SlowCurrentInjLevel", -0.05099115, ICLAMP, ICLAMP)


def test_auto_pipette_offset_does_not_account_for_the_other_tab_after_a_mode_change_in_the_window(tmp_path):
    # the window changed the mode, so it accounts for the tab's changes, a click there among them
    amp = amp_on(tmp_path)
    amp.set_mode("I-Clamp")
    before = amp.snapshot()
    amp.press("Auto Pipette Offset")
    amp.gui.mode("V-Clamp")
    amp.gui.set("Holding", -20, "mV")
    changed = ommm.trial_record(before, amp.snapshot(), amp.writes_since(0)[0])["changed"]
    assert sources(changed)[("readings", "Holding")] == "gui"


def test_a_load_does_not_account_for_the_other_tab_after_a_mode_change_in_the_window(tmp_path, monkeypatch):
    # the file set the I-Clamp tab too, but the window changed the mode: that tab's changes are the window's, as for
    # any mode change made there, and so is a click on it after
    monkeypatch.setattr(amplifier.time, "sleep", lambda s: None)
    amp = amp_on(tmp_path)
    before = amp.snapshot()
    amp.load_config(FAKE / "synthetic.mcc", confirmed=True)
    amp.gui.mode("I-Clamp")
    amp.gui.set("Primary Output Gain", 5, "x")
    changed = sources(ommm.trial_record(before, amp.snapshot(), amp.writes_since(0)[0])["changed"])
    assert changed[("readings", "PrimarySignalGain")] == changed[("telegraph", "dAlpha")] == "gui"
    assert changed[("telegraph", "uOperatingMode")] == changed[("telegraph", "OperatingModeName")] == "gui"


def test_a_load_accounts_for_the_tab_it_did_not_log():
    # a load sets both tabs from the file, and logs what the mode it came back in shows
    line = {"stem": None, "after": {"Mode": 0, "FeedbackResistorVC1": 0, "FeedbackResistorIC1": 0},
            "also": {"Holding": [0.0, -0.06]}, "outcome": "ok"}
    assert log.explains(line, "readings", "Holding", 2e-11, ICLAMP, ICLAMP)
    assert log.explains(line, "readings", "Holding", 2e-11, ("I-Clamp", "V-Clamp"), ("I-Clamp", "V-Clamp"))  # the tab shown
    assert log.explains(line, "telegraph", "dExtCmdSens", 4e-10, ICLAMP, ICLAMP)
    # across tabs and modes the mode change's own source decides
    assert not log.explains(line, "readings", "Holding", 2e-11, VCLAMP, ICLAMP)
    assert not log.explains(line, "telegraph", "dExtCmdSens", 4e-10, VCLAMP, ICLAMP)
    assert not log.explains(line, "telegraph", "OperatingModeName", "I-Clamp", VCLAMP, ICLAMP)
    assert log.explains(line, "readings", "FeedbackResistorIC1", 0, ICLAMP, ICLAMP)  # read back
    assert not log.explains(line, "readings", "FeedbackResistorIC1", 2, ICLAMP, ICLAMP)
    assert log.explains(line, "readings", "Holding", -0.06, VCLAMP, VCLAMP)  # the tab it logged: at the value it left
    assert not log.explains(line, "readings", "Holding", -0.07, VCLAMP, VCLAMP)
    # schema 1 (ommm 0.1): a button's and a load's after was the snapshot diff, which accounts for nothing
    old = {"stem": "AutoOutputZero", "after": {"readings": {"OutputZeroEnable": [False, True]}}, "also": {}, "outcome": "ok"}
    assert not log.explains(old, "readings", "Holding", 2e-11, ICLAMP, ICLAMP)


def test_a_load_accounts_for_the_tab_it_did_not_log_between_two_snapshots_of_that_tab_shown(tmp_path, monkeypatch):
    # snapshot(show_active_tab=False), as scripts/watch.py takes them, with the I-Clamp tab shown in V-Clamp
    monkeypatch.setattr(amplifier.time, "sleep", lambda s: None)
    path = tmp_path / "test_signal.mcc"
    mcc.write(path, mcc.read(FAKE / "synthetic.mcc").replace("[MC700_CHANNEL1_ICLAMP]\r\n",
                                                             "[MC700_CHANNEL1_ICLAMP]\r\nAXMCD_FIELD_TESTSIG_AMP=1.00000000e-010\r\n"))
    amp = amp_on(tmp_path)
    amp.gui.show_tab("I-Clamp")
    before = amp.commander.snapshot(show_active_tab=False)
    amp.load_config(path, confirmed=True)  # comes back in V-Clamp
    amp.gui.show_tab("I-Clamp")
    after = amp.commander.snapshot(show_active_tab=False)
    assert log.tab_and_mode(before) == log.tab_and_mode(after) == ("I-Clamp", "V-Clamp")
    changed = ommm.trial_record(before, after, amp.writes_since(0)[0])["changed"]["readings"]
    assert (changed["TestSignalAmplitude"]["after"], changed["TestSignalAmplitude"]["source"]) == (1e-10, "ommm")


def test_a_tab_clicked_between_two_snapshots_that_leave_the_tab_alone_is_no_mode_change(tmp_path):
    # snapshot(show_active_tab=False), as scripts/watch.py takes them, reads the tab Commander shows
    amp = amp_on(tmp_path)
    amp.set_mode("I-Clamp")  # the I-Clamp tab's output signals selected again, once, before the trial
    amp.set_mode("V-Clamp")
    before = amp.commander.snapshot(show_active_tab=False)
    amp.set_mode("I-Clamp")
    amp.set_mode("V-Clamp")
    amp.gui.show_tab("I-Clamp")
    changed = ommm.trial_record(before, amp.commander.snapshot(show_active_tab=False), amp.writes_since(0)[0])["changed"]
    assert changed["readings"] and set(sources(changed).values()) == {"gui"}
    # to I-Clamp, with the V-Clamp tab clicked back: one tab read, two modes
    amp.gui.show_tab("V-Clamp")
    before = amp.commander.snapshot(show_active_tab=False)
    amp.set_mode("I-Clamp")
    amp.gui.show_tab("V-Clamp")
    amp.gui.set("Seal Test Amplitude", 20, "mV")
    changed = ommm.trial_record(before, amp.commander.snapshot(show_active_tab=False), amp.writes_since(0)[0])["changed"]
    assert sources(changed)[("readings", "TestSignalAmplitude")] == "gui"
    assert {source for (section, key), source in sources(changed).items() if key != "TestSignalAmplitude"} == {"ommm"}


def test_a_write_outside_the_interval_or_refused_accounts_for_nothing(tmp_path):
    amp = amp_on(tmp_path)
    amp.set("Holding", -60, "mV")  # before the trial
    before = amp.snapshot()
    with pytest.raises(WriteError):
        amp.set("Holding", -60, "pA")  # refused: wrong unit
    amp.gui.set("Holding", -70, "mV")
    after = amp.snapshot()
    changed = ommm.trial_record(before, after, amp.writes_since(0)[0])["changed"]
    assert changed["readings"]["Holding"]["source"] == "gui"


def test_trial_record_with_a_snapshot_missing(tmp_path):
    snapshot = amp_on(tmp_path).snapshot()
    assert ommm.trial_record(snapshot, None) == {"before": snapshot, "after": None, "changed": None, "between": None}
    assert ommm.trial_record(snapshot, snapshot)["changed"] == {}


def test_trial_record_of_two_trials_from_matlab_on_the_amplifier():
    """Two trials a MATLAB program saved through the ommm.Amplifier class on the model cell, each from a snapshot
    before and one after, with writes during and between them; every change is ommm's, and without the log every
    change is the window's."""
    record = json.loads((DATA / "rig" / "2026-10-23-matlab" / "check_amp.json").read_text(encoding="utf-8"))
    first, second = record["trials"]
    one = ommm.trial_record(first["before"], first["after"], record["writes"])
    two = ommm.trial_record(second["before"], second["after"], record["writes"], first["after"])

    def sources(changes: dict) -> dict:
        return {(section, key): change["source"] for section, fields in changes.items() for key, change in fields.items()}

    assert sources(one["changed"]) == {("readings", "Holding"): "ommm"}
    assert sources(two["between"]) == {("readings", "Holding"): "ommm", ("readings", "TestSignalEnable"): "ommm"}
    assert sources(two["changed"]) == {("readings", "TestSignalEnable"): "ommm"}
    unlogged = ommm.trial_record(second["before"], second["after"], (), first["after"])
    assert set(sources(unlogged["between"]).values()) == {"gui"}


@pytest.mark.parametrize("make", [
    lambda tmp: (tmp / "a file").write_text("x") and tmp / "a file",
    lambda tmp: (tmp / "a file").write_text("x") and tmp / "a file" / "logs",
])
def test_a_log_dir_ommm_cannot_write_is_refused_before_any_write(tmp_path, make):
    log_dir = make(tmp_path)
    with pytest.raises(ValueError, match=r"cannot hold the write log .*is a file\): give log_dir \(LogDir= in MATLAB\) a folder ommm can write to$"):
        Amplifier(log_dir=log_dir, commander=FakeCommander(FAKE / "vclamp.json"))


def test_an_ommm_log_dir_ommm_cannot_write_is_refused_naming_it(tmp_path, monkeypatch):
    # another log_dir would split the log every program shares through it
    (tmp_path / "a file").write_text("x")
    monkeypatch.setenv("OMMM_LOG_DIR", str(tmp_path / "a file" / "logs"))
    with pytest.raises(ValueError, match=r"^OMMM_LOG_DIR .*logs cannot hold the write log \(.*is a file\): make it writable for "
                                         r"this account, or set OMMM_LOG_DIR to a folder every program's account can write to$"):
        on_commander(monkeypatch)


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="chmod takes a folder from an account on POSIX, never from root")
@pytest.mark.parametrize("logs", ["", "logs"], ids=["the folder", "a folder in it"])
def test_a_folder_the_account_cannot_write_is_refused_though_os_access_says_it_can(tmp_path, monkeypatch, logs):
    # on Windows os.access says every folder is writable, whatever its permissions
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    monkeypatch.setattr(os, "access", lambda *args, **kwargs: True)
    monkeypatch.setenv("OMMM_LOG_DIR", str(locked / logs))
    with pytest.raises(ValueError, match=r"^OMMM_LOG_DIR .* cannot hold the write log \(.*locked is not writable\): make it "
                                         r"writable for this account"):
        on_commander(monkeypatch)


def test_a_default_log_folder_ommm_cannot_write_is_refused_naming_ommm_log_dir_and_log_dir(tmp_path, monkeypatch):
    (tmp_path / "a file").write_text("x")
    monkeypatch.delenv("OMMM_LOG_DIR", raising=False)
    monkeypatch.setattr(amplifier, "LOG_DIR", tmp_path / "a file" / "ommm-logs")  # a home folder ommm cannot write to
    with pytest.raises(ValueError, match=r"^the default log folder .*ommm-logs cannot hold the write log \(.*is a file\): set "
                                         r"OMMM_LOG_DIR to a folder ommm can write to, or give log_dir \(LogDir= in MATLAB\) one$"):
        on_commander(monkeypatch)


def test_a_fakes_log_folder_ommm_cannot_write_is_refused_naming_log_dir_never_ommm_log_dir(tmp_path, monkeypatch):
    (tmp_path / "a file").write_text("x")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "a file"))
    monkeypatch.setenv("OMMM_LOG_DIR", str(tmp_path / "logs"))  # which a fake never reads
    with pytest.raises(ValueError, match=r"^the fake's log folder .* cannot hold the write log \(.*is a file\): give log_dir "
                                         r"\(LogDir= in MATLAB\) a folder ommm can write to$"):
        Amplifier(fake=FAKE / "vclamp.json")


@pytest.mark.parametrize("chosen, remedy", [
    ("the fake's log folder", r"give log_dir \(LogDir= in MATLAB\) a folder without one"),
    ("OMMM_LOG_DIR", "set OMMM_LOG_DIR to a folder without one, for every program that logs there"),
    ("the default log folder", r"set OMMM_LOG_DIR to a folder without one, or give log_dir \(LogDir= in MATLAB\) one"),
])
def test_load_config_refuses_a_log_folder_with_a_space_naming_what_chose_it(tmp_path, monkeypatch, chosen, remedy):
    # a given log_dir: tests/test_load_config.py. A fake never reads OMMM_LOG_DIR, and another log_dir would split the
    # log every program shares through it
    folder = tmp_path / "Your Name" / "ommm-logs"  # a home folder with a space
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    monkeypatch.setenv("OMMM_LOG_DIR", str(folder) if chosen == "OMMM_LOG_DIR" else "")
    monkeypatch.setattr(amplifier, "LOG_DIR", folder)
    if chosen == "the fake's log folder":
        amp = Amplifier(commander=FakeCommander(FAKE / "vclamp.json"))
    else:
        amp = on_commander(monkeypatch)
        amp.process = amp.commander.dll.process  # the fake's, so the plan gets as far as the copy's folder
    plan = amp.load_config(FAKE / "synthetic.mcc")
    assert (plan.outcome, amp.log_dir.is_relative_to(folder.resolve())) == ("refused", True)
    assert re.search(rf", in {chosen} .*, and Commander cannot take a path with a space: {remedy}$", plan.reason), plan.reason


def test_a_log_dir_on_a_drive_that_does_not_exist_is_refused_before_any_write(tmp_path, monkeypatch):
    # an unmapped Windows drive or an offline share: no part of the path exists
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(ValueError, match=rf"cannot hold the write log \({re.escape(log_dir.anchor)} does not exist\): give log_dir"):
        Amplifier(log_dir=log_dir, commander=FakeCommander(FAKE / "vclamp.json"))
