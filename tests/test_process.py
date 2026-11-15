"""Closing Commander and starting it again (ommm.process) on the fake's FakeProcess: WM_CLOSE and its wait, the
command line of a launch, waiting for the API, and the handles before and after."""

import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

import ommm
from ommm import Amplifier, WriteError, amplifier, process
from ommm.commander import CommanderError
from ommm.testing import FakeCommander, FakeProcess

DATA = Path(__file__).parent / "data"
FAKE = ommm.EXAMPLES / "fake"  # the snapshots and the test .mcc the package ships
VCLAMP, ICLAMP = FAKE / "vclamp.json", FAKE / "iclamp.json"  # both at 5 GΩ, serial 00123456


@pytest.fixture
def fake():
    return FakeCommander(VCLAMP, other_tab=ICLAMP)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(process.time, "sleep", lambda s: None)


def one_key_file(path: Path, section: str, index: int) -> Path:
    path.write_bytes(f"[{section}]\r\nAXMCD_FIELD_ELCTRD_HSTAGE_RST_RNG={index}\r\n".encode())
    return path


def test_quit_reads_the_serial_closes_and_kills_every_handle(fake):
    running = FakeProcess(fake)
    assert running.window_pid() == fake.dll.commander_pid() == 1000
    assert process.quit_commander(running) == 1000
    assert running.serial == "00123456"
    assert running.window_pid() is fake.dll.commander_pid() is None
    with pytest.raises(CommanderError) as raised:
        fake.get("Mode")
    assert raised.value.code == 6002


def test_quit_without_commander_refuses(fake):
    running = FakeProcess(fake)
    process.quit_commander(running)
    with pytest.raises(CommanderError, match="Commander is not running in this desktop session"):
        process.quit_commander(running)


def test_quit_refuses_beside_another_commander_which_would_stop_the_launch(fake):
    running = FakeProcess(fake)
    running.pids = lambda: [1000, 2000]
    with pytest.raises(CommanderError, match=r"2 Commanders run on this PC \(processes 1000, 2000\)"):
        process.quit_commander(running)
    assert (running.serial, fake.get("Mode")) == (None, 0)  # not closed


def test_a_commander_that_does_not_exit_is_left_running_and_reported(fake):
    running = FakeProcess(fake, prompt=True)
    with pytest.raises(CommanderError, match=r"still running 30 s after it was asked to close: .* never kills Commander"):
        process.quit_commander(running)
    assert running.pids() == [1000]
    assert fake.get("Mode") == 0  # still answering


def test_launch_starts_the_same_amplifier_with_the_file(fake, tmp_path):
    running = FakeProcess(fake)
    mcc = one_key_file(tmp_path / "vc_500M.mcc", "MC700_CHANNEL1_VCLAMP", 1)
    process.quit_commander(running)
    assert process.launch_commander(mcc, running) == 1001
    assert running.started == [["/S00123456", f"/C{mcc.resolve()}"]]


def test_launch_refuses_while_commander_runs_and_before_a_quit(fake):
    running = FakeProcess(fake)
    with pytest.raises(CommanderError, match=r"Commander is running \(process 1000\): close it first with quit_commander\(\)"):
        process.launch_commander(process=running)
    running.pid = None  # closed by hand: no serial was read
    with pytest.raises(CommanderError, match="only after closing it with quit_commander"):
        process.launch_commander(process=running)
    assert running.started == []


def test_launch_refuses_a_path_with_spaces_and_a_missing_file(fake, tmp_path):
    running = FakeProcess(fake)
    process.quit_commander(running)
    spaced = tmp_path / "my settings"
    spaced.mkdir()
    with pytest.raises(ValueError, match="path has no spaces"):
        process.launch_commander(one_key_file(spaced / "vc.mcc", "MC700_CHANNEL1_VCLAMP", 1), running)
    with pytest.raises(FileNotFoundError):
        process.launch_commander(tmp_path / "missing.mcc", running)
    assert running.started == []


def test_a_commander_in_demo_mode_is_not_closed(fake):
    fake.dll.headstages[0] = replace(fake.dll.headstages[0], serial="Demo")
    running = FakeProcess(fake)
    with pytest.raises(CommanderError, match=r"Commander is in Demo mode \(Demo\)"):
        process.quit_commander(running)
    assert running.pids() == [1000] and running.serial is None


def test_wait_for_api_tries_until_the_new_commander_answers(fake, monkeypatch):
    running = FakeProcess(fake, slow=3)
    fake.gui.set("Holding", -20, "mV")
    process.quit_commander(running)
    process.launch_commander(process=running)
    tries = []
    monkeypatch.setattr(process.time, "sleep", tries.append)
    commander = process.wait_for_api(running)
    assert tries == [0.5] * 3
    assert commander.get("Holding") == pytest.approx(-0.02)  # the state carried over
    with pytest.raises(CommanderError):
        fake.get("Holding")  # the handle from before stays dead


def test_wait_for_api_gives_up_after_its_timeout(fake, monkeypatch):
    running = FakeProcess(fake)
    process.quit_commander(running)
    monkeypatch.setattr(process, "API_S", 0)
    with pytest.raises(CommanderError) as raised:
        process.wait_for_api(running)
    assert raised.value.code == 6002


def test_a_launch_with_a_whole_file_sets_its_feedback_resistor(fake, tmp_path):
    running = FakeProcess(fake)
    process.quit_commander(running)
    mcc = tmp_path / "vc_500M.mcc"
    mcc.write_bytes(b"[MC700_GLOBAL]\r\nAXMCD_FIELD_AUDIO_GAIN=0\r\n" + one_key_file(mcc, "MC700_CHANNEL1_VCLAMP", 1).read_bytes())
    process.launch_commander(mcc, running)
    amp = Amplifier(log_dir=tmp_path, commander=process.wait_for_api(running))
    assert amp.get("Feedback Resistor", "MΩ") == 500
    assert amp.commander.get("FeedbackResistorIC1") == 2


def test_a_launch_with_a_one_key_file_never_answers(fake, tmp_path, monkeypatch):
    """Commander shows "not a valid MultiClamp configuration file" and waits for OK (the partial-file record, `partial_mcc_file.json`)."""
    running = FakeProcess(fake)
    process.quit_commander(running)
    process.launch_commander(one_key_file(tmp_path / "vc_500M.mcc", "MC700_CHANNEL1_VCLAMP", 1), running)
    monkeypatch.setattr(process, "API_S", 0)
    with pytest.raises(CommanderError) as raised:
        process.wait_for_api(running)
    assert raised.value.code == 6002
    assert running.refused == tmp_path / "vc_500M.mcc"
    assert fake.dll.values[(None, "FeedbackResistorVC1")] == 2


def test_after_a_relaunch_the_telegraph_signals_are_stale_until_set(fake):
    running = FakeProcess(fake)
    fake.gui.set("Primary Output", "Membrane Potential")
    assert fake.snapshot()["disagreements"] == []
    process.quit_commander(running)
    process.launch_commander(process=running)
    commander = process.wait_for_api(running)
    assert any(entry.startswith("primary signal") for entry in commander.snapshot()["disagreements"])


def test_an_amplifier_from_before_a_relaunch_says_reconnect(fake, tmp_path, monkeypatch):
    amp = Amplifier(log_dir=tmp_path, commander=fake)
    running = fake.dll.process
    process.quit_commander(running)
    process.launch_commander(process=running)
    process.wait_for_api(running)
    with pytest.raises(WriteError, match=r"Commander was closed or restarted: reconnect\(\)"):
        amp.set("Holding", -60, "mV")
    monkeypatch.setattr(amplifier, "RECONNECT_S", 0)  # at the first try
    amp.reconnect()
    assert amp.set("Holding", -60, "mV").outcome == "ok"


@pytest.mark.skipif(sys.platform == "win32", reason="what ommm.process says off Windows")
def test_off_windows_each_function_says_needs_windows_at_once():
    for call in (process.others_running, process.quit_commander, process.launch_commander, process.wait_for_api):
        started = time.monotonic()
        with pytest.raises(CommanderError, match="^needs Windows, "):
            call()
        assert time.monotonic() - started < 1


@pytest.mark.skipif(not os.environ.get("OMMM_SDK_DIR"), reason="needs OMMM_SDK_DIR, a Commander install folder")
def test_commander_is_started_from_its_install_folder():
    assert process.Process().program_found()  # load_config's plan checks it before Commander is closed
