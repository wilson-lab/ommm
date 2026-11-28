import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import from_matlab

import ommm
from ommm.__main__ import main
from ommm.commander import SNAPSHOT_SCHEMA
from ommm.testing import FakeCommander

FIXTURE = Path(__file__).parent / "data" / "vclamp_stale_secondary_telegraph.json"
EXAMPLES = [ommm.EXAMPLES / "fake" / f"{mode}.json" for mode in ("vclamp", "iclamp", "i0")]  # the README's examples


def test_load_returns_the_snapshot_as_saved(tmp_path):
    # time and provenance are the file's own, not now and the code checked out here; UTF-16 as PowerShell 5.1 writes it
    saved = json.loads(FIXTURE.read_text()) | {"ommm": {"version": "0.0.1", "commit": "0" * 40, "dirty": True, "git_error": None}}
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(saved), encoding="utf-16")
    assert ommm.load_snapshot(path) == saved


def test_none_saved_from_matlab_as_an_empty_list_loads_as_none(tmp_path):
    # MATLAB's snapshot() gives no errors as struct([]), which jsonencode writes as []; MATLAB's Fake= takes the file
    saved = json.loads(EXAMPLES[0].read_text()) | {"errors": []}
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(saved))
    assert ommm.load_snapshot(path)["errors"] == {}
    assert FakeCommander(path).snapshot()["errors"] == {}


def test_a_null_reading_saved_from_matlab_loads_as_none(tmp_path):
    # a *Name reading whose ID matched no header constant is None; MATLAB's jsonencode writes it as []
    saved = json.loads(EXAMPLES[0].read_text())
    saved["readings"]["SecondarySignalName"] = []
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(saved))
    snapshot = ommm.load_snapshot(path)
    assert snapshot["readings"]["SecondarySignalName"] is None
    assert ommm.state(snapshot)["secondary"]["signal"] is None
    assert "?" in ommm.summary(snapshot)


@pytest.mark.parametrize("telegraph", [True, False])
def test_a_snapshot_through_matlab_comes_back_as_python_had_it(telegraph):
    # every null MATLAB writes as [], at any depth, is None again; no errors or not_applicable is {}, no disagreements []
    snapshot = json.loads(EXAMPLES[0].read_text())
    snapshot["readings"]["SecondarySignalName"] = None
    snapshot["ommm"] |= {"commit": None, "dirty": None, "git_error": "not ommm's own checkout"}
    snapshot |= {"errors": {}, "not_applicable": {}, "disagreements": []}
    if not telegraph:
        snapshot |= {"telegraph": None, "errors": {"telegraph": "no telegraph"}, "disagreements": ["tab: one", "mode: two"]}
    assert from_matlab(snapshot) != snapshot
    assert ommm.without_matlab_empties(from_matlab(snapshot)) == snapshot

@pytest.mark.parametrize("example", EXAMPLES[1:], ids=lambda path: path.name)
def test_every_fake_snapshot_has_the_keys_of_vclamp(example):
    def keys(snapshot):  # a reading the mode lacks is in not_applicable instead
        return set(snapshot), set(snapshot["readings"]) | set(snapshot["not_applicable"]), set(snapshot["telegraph"])

    assert keys(ommm.load_snapshot(example)) == keys(ommm.load_snapshot(EXAMPLES[0]))


def test_a_newer_schema_is_refused_and_a_missing_one_accepted(tmp_path):
    saved = json.loads(EXAMPLES[0].read_text())
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(saved | {"schema": SNAPSHOT_SCHEMA + 1}))
    message = f"{re.escape(str(path))} is a schema {SNAPSHOT_SCHEMA + 1} snapshot"
    with pytest.raises(ValueError, match=message):
        ommm.load_snapshot(path)
    with pytest.raises(ValueError, match=message):
        FakeCommander(path)
    del saved["schema"]  # a file from before schema 1
    path.write_text(json.dumps(saved))
    assert ommm.load_snapshot(path) == saved


def test_a_file_that_is_not_a_snapshot_is_refused_by_name(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"Mode": 0}')
    message = re.escape(f"{path} is not an ommm snapshot: it has no headstage, readings, telegraph")
    with pytest.raises(ValueError, match=message):
        ommm.load_snapshot(path)
    with pytest.raises(ValueError, match=message):
        FakeCommander(path)


def test_the_command_prints_a_saved_snapshot_as_saved(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ommm", str(FIXTURE)])
    main()
    assert json.loads(capsys.readouterr().out) == json.loads(FIXTURE.read_text())


def test_the_command_prints_the_summary_of_a_saved_snapshot(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ommm", "--summary", str(FIXTURE)])
    main()
    assert capsys.readouterr().out == ommm.summary(json.loads(FIXTURE.read_text())) + "\n"


def test_the_command_copies_the_examples_into_a_new_folder(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("sys.argv", ["ommm", "--examples", str(tmp_path / "mine")])
    main()
    copied = sorted(path.relative_to(tmp_path / "mine").as_posix() for path in (tmp_path / "mine").rglob("*") if path.is_file())
    assert copied == sorted(path.relative_to(ommm.EXAMPLES).as_posix() for path in ommm.EXAMPLES.rglob("*")
                            if path.is_file() and "__pycache__" not in path.parts)
    assert {"ommm_example_passive.py", "ommm_example_active.m", "mcc/vclamp_5gohm.mcc", "fake/vclamp.json", "fake/synthetic.mcc"} <= set(copied)
    with pytest.raises(SystemExit, match="ommm: .*mine"):  # never over a folder that is there
        main()


def on_the_fake(monkeypatch):
    """`ommm` with no FILE, on an Amplifier over FakeCommander(FIXTURE) on the headstage asked for."""
    amplifier = ommm.Amplifier
    monkeypatch.setattr(ommm, "Amplifier", lambda headstage: amplifier(headstage, fake=FIXTURE))


def test_the_command_reads_the_headstage_asked_for(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ommm", "--summary", "--headstage", "2"])
    on_the_fake(monkeypatch)
    main()
    assert re.search(r"Headstage: +2 \(00123456\)", capsys.readouterr().out)


def test_the_command_prints_the_amplifiers_snapshot_as_json(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["ommm"])
    on_the_fake(monkeypatch)
    main()
    printed = json.loads(capsys.readouterr().out)
    expected = FakeCommander(FIXTURE).snapshot()
    assert printed.keys() == expected.keys()
    assert {key: printed[key] for key in ("headstage", "readings", "telegraph")} == {
        key: expected[key] for key in ("headstage", "readings", "telegraph")}


def test_the_command_says_why_it_could_not_read(monkeypatch):
    def no_commander(headstage):
        raise ommm.CommanderError("FindFirstMultiClamp", 6002, "Commander not found")

    monkeypatch.setattr("sys.argv", ["ommm"])
    monkeypatch.setattr(ommm, "Amplifier", no_commander)
    with pytest.raises(SystemExit, match="^ommm: Commander not found"):
        main()


def test_the_command_writes_the_snapshot_to_a_new_file(monkeypatch, capsys, tmp_path):
    out = tmp_path / "snapshot.json"
    monkeypatch.setattr("sys.argv", ["ommm", "--out", str(out)])
    on_the_fake(monkeypatch)
    main()
    assert capsys.readouterr().out == ""
    assert json.loads(out.read_text(encoding="utf-8"))["readings"] == FakeCommander(FIXTURE).snapshot()["readings"]


def test_the_command_writes_the_summary_to_a_new_file_as_utf8(monkeypatch, tmp_path):
    out = tmp_path / "summary.txt"
    monkeypatch.setattr("sys.argv", ["ommm", "--summary", str(FIXTURE), "--out", str(out)])
    main()
    assert out.read_text(encoding="utf-8") == ommm.summary(json.loads(FIXTURE.read_text())) + "\n"


def test_the_command_rewrites_a_utf16_snapshot_as_utf8(monkeypatch, tmp_path):
    # `ommm > snapshot.json` in Windows PowerShell 5.1 writes UTF-16 with a byte order mark
    saved = json.loads(FIXTURE.read_text())
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    old.write_text(json.dumps(saved), encoding="utf-16")
    monkeypatch.setattr("sys.argv", ["ommm", str(old), "--out", str(new)])
    main()
    assert new.read_bytes().startswith(b"{")  # no byte order mark
    assert json.loads(new.read_text(encoding="utf-8")) == saved


def test_the_command_refuses_a_file_that_is_there_before_reading_commander(monkeypatch, capsys, tmp_path):
    out = tmp_path / "snapshot.json"
    out.write_text("mine")
    monkeypatch.setattr("sys.argv", ["ommm", "--out", str(out)])
    monkeypatch.setattr(ommm, "Amplifier", lambda headstage: pytest.fail("Commander was read"))
    with pytest.raises(SystemExit, match=f"^ommm: {re.escape(str(out))} exists"):
        main()
    assert (out.read_text(), capsys.readouterr().out) == ("mine", "")


def test_the_command_writes_the_summary_as_utf8_to_a_cp1252_file_or_pipe():
    # Windows encodes a redirected stdout as cp1252, which has no ♡ or Ω
    result = subprocess.run([sys.executable, "-m", "ommm", "--summary", str(FIXTURE)], capture_output=True,
                            encoding="utf-8", env=os.environ | {"PYTHONIOENCODING": "cp1252"})
    assert (result.returncode, result.stdout) == (0, ommm.summary(json.loads(FIXTURE.read_text())) + "\n")


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda path: path.name)
def test_an_example_has_every_key_the_snapshot_table_lists_and_nothing_to_report(example):
    docs = (Path(__file__).parents[1] / "docs" / "install-and-testing.md").read_text(encoding="utf-8")
    table = docs.split("\n## The snapshot\n")[1].split("\n## ")[0]
    snapshot = ommm.load_snapshot(example)
    assert snapshot.keys() == set(re.findall(r"^\| `(\w+)` \|", table, re.MULTILINE))
    found = ommm.state(snapshot)
    assert (found["blocking"], found["problems"], found["warnings"]) == ([], [], [])


@pytest.mark.parametrize("text", ["{}", "[tool.uv]\n"])  # JSON without the keys, and not JSON at all
def test_the_command_refuses_a_file_that_is_not_a_snapshot(tmp_path, monkeypatch, text):
    path = tmp_path / "settings.json"
    path.write_text(text)
    monkeypatch.setattr("sys.argv", ["ommm", str(path)])
    with pytest.raises(SystemExit, match=f"ommm: {re.escape(str(path))} is not an ommm snapshot"):
        main()
