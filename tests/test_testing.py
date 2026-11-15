import json
import subprocess
import sys
from pathlib import Path

import pytest

import ommm
from ommm.commander import NotApplicable
from ommm.testing import FakeCommander

FIXTURE = Path(__file__).parent / "data" / "vclamp_stale_secondary_telegraph.json"


def test_fake_is_used_like_commander():
    with FakeCommander(FIXTURE) as fake:
        assert fake.headstage.channel == 1
        assert fake.select() == fake.headstage
        assert fake.get("Mode") == 0
        with pytest.raises(NotApplicable, match=r"^GetBridgeBalResist does not apply now: INVALIDPARAMETER \(6004\)"):
            fake.get("BridgeBalResist")


def test_import_ommm_reaches_the_fake_as_the_off_windows_error_says():
    # a fresh Python: in this one, importing ommm.testing above already set the attribute
    subprocess.run([sys.executable, "-c", "import ommm; ommm.testing.FakeCommander; ommm.NotApplicable"], check=True)


@pytest.mark.parametrize("args", [("Mode",), ("Holding",), ("MeterValue", 0), ("MeterValue", 3)])
def test_fake_get_takes_what_commander_get_takes(args):
    FakeCommander(FIXTURE).get(*args)


@pytest.mark.parametrize("name", ["MeterValue1", "ModeName", "PrimarySignalName", "SecondarySignalName"])
def test_snapshot_only_keys_are_no_getters(name):
    with pytest.raises(ValueError, match=f"there is no Get{name}$"):
        FakeCommander(FIXTURE).get(name)


def test_fake_get_reads_meters_by_index():
    saved = ommm.load_snapshot(FIXTURE)
    saved["readings"]["MeterValue2"] = -0.07
    assert FakeCommander(saved).get("MeterValue", 1) == -0.07


@pytest.mark.parametrize("args", [("MeterValue",), ("Mode", 0)])
def test_fake_get_refuses_a_wrong_argument_count(args):
    # on Windows ctypes refuses these, with each getter's argtypes from the header
    with pytest.raises(TypeError, match=f"Get{args[0]} takes"):
        FakeCommander(FIXTURE).get(*args)


def test_fake_raises_the_code_the_file_stored(tmp_path):
    saved = json.loads(FIXTURE.read_text())
    saved["not_applicable"]["BridgeBalResist"] = "MCCCOMMANDFAIL (6006)"
    (tmp_path / "snapshot.json").write_text(json.dumps(saved))
    with pytest.raises(NotApplicable, match=r"^GetBridgeBalResist does not apply now: MCCCOMMANDFAIL \(6006\)") as raised:
        FakeCommander(tmp_path / "snapshot.json").get("BridgeBalResist")
    assert raised.value.code == 6006


def test_fake_reads_a_snapshot_saved_by_windows_powershell(tmp_path):
    # `ommm > snapshot.json` in Windows PowerShell 5.1 writes UTF-16 with a byte order mark
    saved = tmp_path / "snapshot.json"
    saved.write_text(FIXTURE.read_text(), encoding="utf-16")
    assert FakeCommander(saved).get("Mode") == 0
