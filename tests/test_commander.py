import re
import struct
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import ommm
from ommm import commander
from ommm.commander import Commander, CommanderError
from ommm.testing import FakeCommander
from ommm.testing.fake import FakeDLL, FakeTelegraph

VCLAMP = ommm.EXAMPLES / "fake" / "vclamp.json"


def test_select_takes_headstage_1_of_the_700b():
    fake = FakeCommander(VCLAMP)
    headstage = fake.headstage
    fake.dll.headstages = [headstage, replace(headstage, channel=2)]
    assert fake.select() == headstage
    assert [name for name, *_ in fake.dll.calls] == ["FindFirstMultiClamp", "FindNextMultiClamp", "FindNextMultiClamp",
                                                     "SelectMultiClamp", "GetFeedbackResistorVC1"]


@pytest.mark.parametrize("headstages, says", [
    ([], "Commander lists no MultiClamp 700B"),  # FindFirstMultiClamp says NOERROR
    ([commander.Headstage(model=0, serial="00123456", com_port=0, device=0, channel=1)], "Commander lists no MultiClamp 700B"),  # a 700A
    ([commander.Headstage(1, "00123456", 0, 0, 1), commander.Headstage(1, "00654321", 0, 0, 1)],
     "ommm drives one MultiClamp 700B; Commander lists 2: serials 00123456, 00654321"),
])
def test_commander_refuses_unless_there_is_exactly_one_700b_headstage_1(headstages, says):
    dll = FakeDLL(ommm.load_snapshot(VCLAMP))
    dll.headstages = headstages
    with pytest.raises(CommanderError, match=f"^{re.escape(says)}$"):
        Commander(dll=dll, telegraph=FakeTelegraph(dll, None))
    assert "SelectMultiClamp" not in {name for name, *_ in dll.calls}


@pytest.mark.skipif(sys.platform == "win32", reason="off Windows only")
def test_off_windows_commander_says_how_to_read_a_saved_snapshot():
    hint = ("elsewhere read a saved snapshot: `ommm --summary FILE`, ommm.load_snapshot(FILE) in Python, ommm.Amplifier(Fake=FILE) in MATLAB; "
            "try the writes on it in Python with ommm.Amplifier(fake=FILE)")
    with pytest.raises(CommanderError, match=re.escape(hint)):
        Commander()


@pytest.mark.parametrize("present, missing", [
    ([], "AxMultiClampMsg.h"),
    (["AxMultiClampMsg/AxMultiClampMsg.h"], "AxMultiClampMsg.dll"),
    (["AxMultiClampMsg/AxMultiClampMsg.h", "AxMultiClampMsg/AxMultiClampMsg.dll"], "MultiClampBroadcastMsg.hpp"),
])
def test_a_missing_commander_file_names_it_and_ommm_sdk_dir(tmp_path, monkeypatch, present, missing):
    # the telegraph header too, though it is read only at the first telegraph; checked before the DLL loads, so any OS
    monkeypatch.setenv("OMMM_SDK_DIR", str(tmp_path))
    for name in present:
        path = tmp_path / "3rd Party Support" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    with pytest.raises(CommanderError, match=f"^{re.escape(missing)} is not in .*: set OMMM_SDK_DIR to Commander's install folder$"):
        commander.DLL()


def test_a_commander_dll_that_does_not_load_names_ommm_sdk_dir(tmp_path, monkeypatch):
    # a 32-bit DLL, say: Windows refuses it when it loads
    def refused(path):
        raise OSError(f"[WinError 193] %1 is not a valid Win32 application: {path!r}")

    monkeypatch.setenv("OMMM_SDK_DIR", str(tmp_path))
    for name in ("AxMultiClampMsg/AxMultiClampMsg.h", "AxMultiClampMsg/AxMultiClampMsg.dll", commander.telegraph.HEADER):
        path = tmp_path / "3rd Party Support" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#define MCCMSG_APIVERSION_STR "1.0.0.9"\n')
    monkeypatch.setattr(commander.ctypes, "WinDLL", refused, raising=False)  # no WinDLL off Windows
    with pytest.raises(CommanderError, match=r"AxMultiClampMsg\.dll does not load \(\[WinError 193\] .*\): set OMMM_SDK_DIR to "
                                             r"Commander's install folder$"):
        commander.DLL()


def test_commander_not_running_says_to_start_it():
    # the fake gives the same text on any OS and over SSH; only the real DLL looks at this machine
    fake = FakeCommander(VCLAMP)
    fake.dll.dead = True
    with pytest.raises(CommanderError) as raised:
        fake.select()
    assert raised.value.function == "FindFirstMultiClamp"
    assert str(raised.value) == (
        "Commander not found: start MultiClamp Commander on this PC's desktop (not elevated), "
        "then try again (6002)"
    )
    assert raised.value.code == 6002


@pytest.mark.parametrize("name", ["Holdng", "Zap", "Cp Fast Capacitance"])
def test_get_without_a_getter_says_so(name):
    # Commander.get takes the API name; ommm.Amplifier.get takes Commander's labels
    with pytest.raises(ValueError) as raised:
        FakeCommander(VCLAMP).get(name)
    assert str(raised.value) == f"get({name!r}): there is no Get{name}"


@pytest.mark.parametrize("code, says", [
    (6005, r"^Get\w+ failed: MSGTIMEOUT \(6005\)$"),
    (6002, r"^Commander was closed or restarted: reconnect\(\) .* \(6002\)$"),
])
def test_snapshot_stops_mid_read_at_a_timeout_or_a_closed_commander(code, says):
    # every remaining read would fail too, each after waiting out the timeout
    fake = FakeCommander(VCLAMP)
    fake.dll.fail_at(3, code)  # SelectMultiClamp, a Get, then this one
    with pytest.raises(CommanderError, match=says) as raised:
        fake.snapshot()
    assert (raised.value.code, len(fake.dll.calls), raised.value.function[:3]) == (code, 3, "Get")


def test_snapshot_files_any_other_error_and_reads_on():
    fake = FakeCommander(VCLAMP)
    fake.dll.fail_at(3, 6006)
    snapshot = fake.snapshot()
    failed = fake.dll.calls[2][0]
    assert snapshot["errors"] == {failed[3:]: f"{failed} failed: MCCCOMMANDFAIL (6006)"}
    assert failed[3:] not in snapshot["readings"]
    assert len(snapshot["readings"]) == len(FakeCommander(VCLAMP).snapshot()["readings"]) - 1


def test_parse_header_reads_declarations_constants_and_version():
    header = (
        '#define MCCMSG_APIVERSION_STR  "1.0.0.9"\r\n'
        "AXMCCMSG BOOL WINAPI EXPORT MCCMSG_GetMode(HMCCMSG hMCCmsg, UINT *puModeID, int *pnError);\r\n"
        "AXMCCMSG void  WINAPI MCCMSG_DestroyObject(HMCCMSG hMCCmsg);\r\n"
        "// AXMCCMSG BOOL WINAPI EXPORT MCCMSG_GetOld(HMCCMSG hMCCmsg, int *pnError);\r\n"
        "const UINT MCCMSG_MODE_ICLAMP                           = 1;   \r\n"
        "const int MCCMSG_ERROR_MSGTIMEOUT                      = 6005;\r\n"
    )
    functions, constants, version = commander.parse_header(header)
    assert functions == {
        "GetMode": ("BOOL", ["HMCCMSG hMCCmsg", "UINT *puModeID", "int *pnError"]),
        "DestroyObject": ("void", ["HMCCMSG hMCCmsg"]),
    }
    assert constants == {"MODE_ICLAMP": 1, "ERROR_MSGTIMEOUT": 6005}
    assert version == "1.0.0.9"


def test_shortest_float32_drops_conversion_tails_only():
    assert commander.shortest_float32(4.999999987376214e-07) == 5e-07
    assert commander.shortest_float32(0.005014102) == 0.005014102
    assert commander.shortest_float32(-0.06) == -0.06


def test_disguised_error_finds_codes_returned_as_values():
    as_float32 = struct.unpack("<f", struct.pack("<I", 6004))[0]  # 8.41e-42
    assert commander.disguised_error(as_float32) == 6004
    assert commander.disguised_error(6006) == 6006
    assert commander.disguised_error(0.02) is None
    assert commander.disguised_error(1) is None


def test_changes_leaves_out_meters_and_empty_sections():
    before = {"readings": {"Mode": 0, "MeterValue1": 1e-9, "Holding": 0.0}, "telegraph": None}
    after = {"readings": {"Mode": 1, "MeterValue1": 2e-9, "Holding": 0.0, "BridgeBalEnable": True}, "telegraph": None}
    assert commander.changes(before, after) == {"readings": {"BridgeBalEnable": [None, True], "Mode": [0, 1]}}
