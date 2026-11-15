"""check_amplifier.py's harness (scripts/rig/rig.py) where it needs no Commander: the write log line, the record's
header, the put-back's order of writes and its Pipette Offsets; the records in tests/data/rig/; and every script's
--help."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import ommm
from ommm.commander import Commander, CommanderError
from ommm.testing import FakeCommander
from ommm.testing.fake import FakeDLL, FakeTelegraph, Gui

from conftest import sets

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "rig"))
import rig

FIXTURE = Path(__file__).parent / "data" / "vclamp_stale_secondary_telegraph.json"
RIG_RECORDS = sorted((Path(__file__).parent / "data" / "rig").glob("*/*.json"))
SCRIPTS = sorted((Path(__file__).parents[1] / "scripts").rglob("*.py"))
NOTHING = "amplifier on, nothing attached to the headstage (--no-cell-attached)"


class Wandering(FakeDLL):
    """Commander with nothing attached: each Auto Pipette Offset in V-Clamp finds the next (V-Clamp, I-Clamp) pair of
    `levels`, which wander from Auto to Auto (P06)."""

    def __init__(self, levels: list[tuple[float, float]]):
        super().__init__(ommm.load_snapshot(FIXTURE))
        self.levels = iter(levels)

    def press(self, action):
        if action == "AutoPipetteOffset" and self.shown == "V-Clamp":
            self.found_offsets = dict(zip(("V-Clamp", "I-Clamp"), next(self.levels)))
        super().press(action)


def logged(p: rig.Probe) -> list[dict]:
    return [json.loads(line) for line in p.log_path.read_text().splitlines()]


@pytest.mark.parametrize("target, outcome", [(7, "mismatch"), (5, "ok")])  # Commander takes gain 7 as 5 (P03)
def test_a_write_is_one_line_with_the_reads_before_and_after(tmp_path, target, outcome):
    fake = FakeCommander(FIXTURE)
    p = rig.Probe("P00", "a question", fake, tmp_path, NOTHING)

    line = p.write("PrimarySignalGain", target, settle=0)

    assert sets(fake) == [("SetPrimarySignalGain", target)]
    assert logged(p) == [line]
    assert {key: line[key] for key in ("schema", "probe", "stem", "mode", "before", "target", "after", "outcome")} == {
        "schema": 1, "probe": "P00", "stem": "PrimarySignalGain", "mode": 0, "before": 2.0, "target": target, "after": 5.0, "outcome": outcome,
    }
    assert line["error_code"] is None and line["reason"] is None
    assert line["ommm"] == {key: value for key, value in ommm.provenance().items() if key != "git_error"}
    assert p.steps == [{"write": line, "set_ms": p.steps[0]["set_ms"]}]


def test_an_action_has_no_target_and_is_ok_unless_commander_refuses():
    error = CommanderError("AutoBridgeBal", 6006, "as Commander says it")
    done = rig.log_line("P06", stem="AutoPipetteOffset", mode=0, before={"PipetteOffset": 0.0}, target=None,
                          after={"PipetteOffset": 0.003}, error=None)
    refused = rig.log_line("P06", stem="AutoBridgeBal", mode=0, before={}, target=None, after={}, error=error)
    assert (done["target"], done["outcome"]) == (None, "ok")
    assert (refused["outcome"], refused["error_code"]) == ("error", 6006)


def test_lines_append(tmp_path):
    p = rig.Probe("P00", "a question", FakeCommander(FIXTURE), tmp_path, NOTHING)
    p.write("Holding", -0.02, settle=0)
    p.write("Holding", 0.0, settle=0)
    assert [line["target"] for line in logged(p)] == [-0.02, 0.0]


def test_a_refused_write_is_an_answer_recorded_not_raised(tmp_path):
    p = rig.Probe("P04", "a question", FakeCommander(FIXTURE), tmp_path, NOTHING)

    line = p.write("BridgeBalEnable", True, settle=0)  # an I-Clamp setting, set in V-Clamp

    assert (line["before"], line["after"]) == ("not applicable (6004)", "not applicable (6004)")
    assert (line["outcome"], line["error_code"], line["reason"]) == (
        "error", 6004, "SetBridgeBalEnable failed: AXMCCMSG: Invalid parameter specified. (6004)",
    )


def test_a_timeout_is_logged_then_raised(tmp_path):
    fake = FakeCommander(FIXTURE)
    p = rig.Probe("P03", "a question", fake, tmp_path, NOTHING)
    fake.dll.fail_at(3)  # write() reads the mode and the gain, then sets
    with pytest.raises(CommanderError, match="6005"):
        p.write("PrimarySignalGain", 5, settle=0)
    assert logged(p)[0]["error_code"] == 6005


def test_the_header_names_the_probe_what_is_on_the_headstage_commander_api_and_ommm():
    snapshot = FakeCommander(FIXTURE).snapshot()
    assert rig.header("P01", "a question", snapshot, NOTHING) == {
        "probe": "P01",
        "question": "a question",
        "time": snapshot["time"],
        "setup": NOTHING,
        "commander": "2.2.2.2",
        "firmware": "2.0.00.25",
        "dsp": "2.0.0.16",
        "api_version": "1.0.0.9",
        "ommm": ommm.provenance(),
    }


def test_the_put_back_turns_enables_off_then_values_then_enables_on():
    target = {"Mode": 1, "ModeSwitchEnable": False, "PrimarySignal": 7, "FeedbackResistorIC1": 2,
              "HoldingEnable": True, "Holding": -1e-11, "SlowCurrentInjEnable": False, "SlowCurrentInjLevel": -0.05,
              "SlowCompTau": 2e-4, "SlowCompTauX20Enable": True, "OutputZeroAmplitude": 1e-3, "PrimarySignalGain": 2.0,
              "SecondarySignalGain": 5.0, "MeterValue1": 0.1}
    current = target | {"Mode": 0, "ModeSwitchEnable": True, "PrimarySignal": 8, "FeedbackResistorIC1": 3,
                        "HoldingEnable": False, "Holding": 0.0, "SlowCurrentInjEnable": True, "SlowCompTau": 1e-5,
                        "SlowCompTauX20Enable": False, "PrimarySignalGain": 10.0, "MeterValue1": 0.2}
    settable = {"Mode", "ModeSwitchEnable", "PrimarySignal", "HoldingEnable", "Holding", "SlowCurrentInjEnable",
                "SlowCurrentInjLevel", "SlowCompTau", "SlowCompTauX20Enable", "OutputZeroAmplitude", "PrimarySignalGain",
                "SecondarySignalGain"}

    assert rig.writes(target, current, settable) == [
        ("SlowCompTauX20Enable", True),  # first: it multiplies the Tau by 20 (P20)
        ("SlowCurrentInjEnable", False),
        ("PrimarySignalGain", 2.0),  # before Output Zero, which scales with it (P10)
        ("Holding", -1e-11), ("SlowCompTau", 2e-4),
        ("OutputZeroAmplitude", 1e-3),  # agreed, but the gain write rescales it
        ("HoldingEnable", True),
    ]  # mode, Ext and signals are written apart; no setter for the feedback resistor or a meter; the secondary gain agrees


@pytest.mark.parametrize("argv, setup", [
    (["--no-cell-attached"], NOTHING),
    (["--model-cell", "cell"], "amplifier on, a model cell on the headstage, its switch at CELL (--model-cell CELL)"),
    (["--model-cell", "PATCH"], "amplifier on, a model cell on the headstage, its switch at PATCH (--model-cell PATCH)"),
])
def test_what_is_on_the_headstage_goes_into_the_records_header(argv, setup):
    assert rig.setup(rig.parser("a question").parse_args(argv), "P01") == setup


@pytest.mark.parametrize("argv, code", [
    ([], "P01: say what is on the headstage: --no-cell-attached, or --model-cell BATH, PATCH or CELL"),
    (["--model-cell", "ON"], 2),  # argparse's usage error: not a position
    (["--no-cell-attached", "--model-cell", "CELL"], 2),  # argparse's usage error: not both
], ids=["neither", "not a position", "both"])
def test_a_run_refuses_unless_told_what_is_on_the_headstage(monkeypatch, capsys, argv, code):
    monkeypatch.setattr(sys, "argv", ["check_amplifier.py", *argv])
    with pytest.raises(SystemExit) as exited:
        rig.run("P01", "a question", lambda p: None)
    assert exited.value.code == code


def next_to(fake, monkeypatch, *argv: str):
    """rig.run() on the fake, with no Commander window: the tabs are the fake's, no screenshot is taken."""
    monkeypatch.setattr(sys, "argv", ["check_amplifier.py", "--no-cell-attached", *argv])
    monkeypatch.setattr(rig, "Commander", lambda: fake)
    monkeypatch.setattr(rig, "shown_tab", lambda: rig.TABS.index(fake.dll.shown))
    monkeypatch.setattr(rig, "show_tab", lambda tab: fake.gui.show_tab(rig.TABS[tab]))
    monkeypatch.setattr(rig, "is_checked", lambda key: fake.get("ModeSwitchEnable"))
    monkeypatch.setattr(rig, "screenshot", lambda path, window=None: None)


def test_a_run_refuses_unless_commander_is_in_the_start_state(tmp_path, monkeypatch):
    fake = FakeCommander(FIXTURE)
    fake.gui.mode("I = 0")
    next_to(fake, monkeypatch, "--log-dir", str(tmp_path))
    with pytest.raises(SystemExit, match="^P01: start with V-Clamp active, its tab shown and Mode Switching off; found "):
        rig.run("P01", "a question", lambda p: None)
    assert list(tmp_path.iterdir()) == []


def test_a_run_that_fails_still_puts_commander_back_and_keeps_the_record(tmp_path, monkeypatch):
    fake = FakeCommander(FIXTURE)
    next_to(fake, monkeypatch, "--log-dir", str(tmp_path))

    def body(p):
        raise RuntimeError("the body failed")

    with pytest.raises(SystemExit, match="RuntimeError: the body failed") as exited:
        rig.run("P01", "a question", body)
    record = json.loads(next(tmp_path.glob("p01_*.json")).read_text(encoding="utf-8"))
    assert record["error"] == exited.value.code
    assert record["left_changed"] == {} and set(record["end"]) == set(rig.TABS)
    assert record["steps"][-1]["note"] == "end"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.name)
def test_every_script_prints_its_help_on_any_os(script):
    subprocess.run([sys.executable, str(script), "--help"], check=True, capture_output=True)


def serials(node):
    """Every serial field in a record, at any depth: the headstage's `serial` and the telegraph's `szSerialNumber`."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("serial", "szSerialNumber"):
                yield from value if isinstance(value, list) else [value]
            else:
                yield from serials(value)
    elif isinstance(node, list):
        for item in node:
            yield from serials(item)


@pytest.mark.parametrize("path", RIG_RECORDS, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_a_rig_record_has_the_fake_serial_a_clean_commit_and_nothing_left_changed(path):
    """Or, for a probe that stopped (Commander did not come back), nothing put back and nothing read at the end."""
    record = json.loads(path.read_text(encoding="utf-8"))
    assert set(serials(record)) == {"00123456"}
    assert record["header"]["ommm"]["dirty"] is False
    if "probe.Stop" in (record["error"] or ""):
        assert record["left_changed"] is None and record["end"] is None
    else:
        assert record["left_changed"] == {}


def test_offsets_out_of_reach_of_the_last_auto_get_auto_pressed_again_in_vclamp(tmp_path, monkeypatch):
    dll = Wandering([(-0.12548, -0.087), (0.02, -0.108), (-0.091, -0.081)])  # (V-Clamp, I-Clamp) levels, as seen on the amplifier
    fake, gui = Commander(dll=dll, telegraph=FakeTelegraph(dll, None)), Gui(dll)
    fake._call("AutoPipetteOffset")  # the first: V-Clamp's 0 V out of reach
    monkeypatch.setattr(rig, "screen", SimpleNamespace(commander_windows=list), raising=False)  # no windows open
    monkeypatch.setattr(rig, "shown_tab", lambda: rig.TABS.index(dll.shown))
    monkeypatch.setattr(rig, "show_tab", lambda tab: gui.show_tab(rig.TABS[tab]))
    monkeypatch.setattr(rig, "MODE_SETTLE_S", 0)
    p = rig.Probe("P06", "a question", fake, tmp_path, NOTHING)

    p.put_back_pipette_offsets({"V-Clamp": 0.0, "I-Clamp": 0.0})

    pressed = [line for line in logged(p) if line["stem"] == "AutoPipetteOffset"]
    assert [line["mode"] for line in pressed] == [0, 0]  # in V-Clamp; the second Auto left I-Clamp out of reach
    assert [dll.values[(tab, "PipetteOffset")] for tab in rig.TABS] == [0.0, 0.0]
    assert (dll.mode_name, dll.shown) == ("V-Clamp", "V-Clamp")  # back in the mode it started in
