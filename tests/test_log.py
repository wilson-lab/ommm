"""The write log, ommm.log: one append-only JSONL line per sent call and per refusal, read back with writes_since, and
trial_record telling ommm's changes from the ones made in Commander's window."""

import json
import re
import tempfile
from pathlib import Path

import pytest
from conftest import from_matlab

import ommm
from ommm import Amplifier, WriteError, log
from ommm.amplifier import LOG_DIR
from ommm.testing import FakeCommander

DATA = Path(__file__).parent / "data"
FAKE = ommm.EXAMPLES / "fake"  # the snapshots and the test .mcc the package ships
LINE_KEYS = {"schema", "t", "process", "commander", "serial", "headstage", "label", "stem", "mode", "before", "target", "unit",
             "user_value", "after", "also", "outcome", "reason", "error_code", "telegraph_checks", "ommm"}  # docs/writes.md, "The log and trial records"


def amp_on(tmp_path) -> Amplifier:
    return Amplifier(log_dir=tmp_path, commander=FakeCommander(FAKE / "vclamp.json", other_tab=FAKE / "iclamp.json"))


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


@pytest.mark.parametrize("make", [lambda: Amplifier(fake=FAKE / "vclamp.json"),
                                  lambda: Amplifier(commander=FakeCommander(FAKE / "vclamp.json"))], ids=["fake", "commander"])
def test_a_fake_with_no_log_dir_logs_to_a_new_temporary_folder_never_the_real_amplifiers_log(tmp_path, monkeypatch, make):
    # a fake made from your rig's snapshot has your amplifier's serial
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # what gettempdir gives
    amp = make()
    amp.set("Holding", -60, "mV")
    assert amp.log_path.exists() and amp.log_path.parent.parent == tmp_path
    assert not amp.log_path.is_relative_to(LOG_DIR)


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
    assert not log.explains(line, "telegraph", "dMembraneCap", 2 * cap)  # a later change is not the press's


def test_ext_that_left_another_mode_accounts_for_the_tabs_readings_as_a_mode_write_does():
    line = {"stem": "ModeSwitchEnable", "after": False, "also": {"Mode": [0, 2]}}  # on the rig Ext left I = 0
    assert log.explains(line, "readings", "Mode", 2) and not log.explains(line, "readings", "Mode", 1)
    assert log.explains(line, "readings", "Holding", 0.0) and log.explains(line, "telegraph", "dAlpha", 10.0)
    assert not log.explains(line, "readings", "FeedbackResistorIC1", 2)  # above the tabs
    assert not log.explains(line | {"also": {}}, "readings", "Holding", 0.0)


def test_a_mode_change_accounts_for_the_other_tabs_readings_and_the_telegraph(tmp_path):
    amp = amp_on(tmp_path)
    before = amp.snapshot()
    amp.set_mode("I-Clamp")
    after = amp.snapshot()
    record = ommm.trial_record(before, after, amp.writes_since(0)[0])
    sources = {entry["source"] for section in record["changed"].values() for entry in section.values()}
    assert sources == {"ommm"}
    assert record["changed"]["readings"]["Mode"] == {"before": 0, "after": 1, "source": "ommm", "t": record["changed"]["readings"]["Mode"]["t"]}


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


def test_a_log_dir_on_a_drive_that_does_not_exist_is_refused_before_any_write(tmp_path, monkeypatch):
    # an unmapped Windows drive or an offline share: no part of the path exists
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(ValueError, match=rf"cannot hold the write log \({re.escape(log_dir.anchor)} does not exist\): give log_dir"):
        Amplifier(log_dir=log_dir, commander=FakeCommander(FAKE / "vclamp.json"))
