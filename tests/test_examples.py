"""The Python examples run whole: the active one on the fake to the end, and on Commander it stops before its confirmed
loads of ommm's own settings file; the passive one with Irms Meter on too."""

import builtins
import runpy

import pytest

import ommm
from ommm import Amplifier, amplifier

ACTIVE = ommm.EXAMPLES / "ommm_example_active.py"
PASSIVE = ommm.EXAMPLES / "ommm_example_passive.py"


@pytest.fixture
def amp(tmp_path, monkeypatch) -> Amplifier:
    """The Amplifier the example's ommm.Amplifier() makes, on the fake; the example's question answered y."""
    amp = Amplifier(log_dir=tmp_path, fake=ommm.EXAMPLES / "fake" / "vclamp.json")
    monkeypatch.setattr(ommm, "Amplifier", lambda: amp)
    monkeypatch.setattr(builtins, "input", lambda prompt: "y")
    monkeypatch.setattr(amplifier.time, "sleep", lambda s: None)  # the time module ommm.process waits with too
    return amp


def test_the_active_example_runs_whole_on_the_fake_with_ommms_settings_file(amp):
    runpy.run_path(str(ACTIVE))
    assert len(amp.process.started) == 2  # its copy at 500 MΩ, then the file unchanged


def test_on_commander_the_active_example_stops_before_loading_ommms_settings_file(amp):
    amp.fake = None  # as on Commander
    with pytest.raises(AssertionError, match="point setup at that file$"):
        runpy.run_path(str(ACTIVE))
    assert amp.process.started == []


def test_the_passive_example_runs_whole_with_irms_meter_on(amp, tmp_path, monkeypatch):
    # in V-Clamp with Irms Meter on, get refuses the current meter, which then shows the RMS noise
    amp.gui.enable("Irms Meter", True)
    monkeypatch.chdir(tmp_path)  # it saves snapshot.json in the working folder
    runpy.run_path(str(PASSIVE))
    assert (tmp_path / "snapshot.json").exists()
