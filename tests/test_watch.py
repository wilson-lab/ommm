"""scripts/watch.py on the fake."""

import re
import sys
from pathlib import Path

import pytest

import ommm
from ommm.testing import FakeCommander

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import watch


def test_watch_stops_with_one_line_when_commander_closes(tmp_path, monkeypatch):
    fake = FakeCommander(ommm.EXAMPLES / "fake" / "vclamp.json")
    monkeypatch.setattr(watch, "Commander", lambda: fake)
    monkeypatch.setattr(watch.time, "sleep", lambda seconds: setattr(fake.dll, "dead", True))  # closed between snapshots
    monkeypatch.setattr(sys, "argv", ["watch.py", "--log-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as stopped:
        watch.main()
    assert re.fullmatch(r"watch: stopped, Commander was closed, restarted or did not answer \(Get\w+, 6002\): "
                        "run watch again once it is back", stopped.value.code)
