"""Checks against Commander's own headers, which ommm never copies: they run when OMMM_SDK_DIR names a
Commander install folder (or a copy of one) and are skipped otherwise."""

import ctypes
import os
import re

import pytest

from ommm import telegraph
from ommm.commander import C_TYPES, OTHER_HEADSTAGE_GETTERS, parse_header, to_ctype
from ommm.sdk import sdk_file
from ommm.settings import AUXILIARY_SIGNALS, PRIMARY_TO_TELEGRAPH, SECONDARY_TO_TELEGRAPH, SIGNAL_NAMES
from ommm.state import CURRENTS, EXT_COMMANDS, POTENTIALS, TELEGRAPH_TO_SI

pytestmark = pytest.mark.skipif(not os.environ.get("OMMM_SDK_DIR"), reason="OMMM_SDK_DIR is not set")


@pytest.fixture(scope="module")
def header():
    return parse_header(sdk_file("AxMultiClampMsg/AxMultiClampMsg.h").read_text())


def test_api_1_0_0_9_declares_121_functions(header):
    functions, _, version = header
    assert version == "1.0.0.9"
    assert len(functions) == 121
    assert sum(name.startswith("Get") for name in functions) == 51
    assert sum(name.startswith("Set") for name in functions) == 47  # SetTimeOut included
    assert set().union(*OTHER_HEADSTAGE_GETTERS.values()) <= functions.keys()


def test_every_type_maps_to_ctypes_and_bool_is_four_bytes(header):
    functions, _, _ = header
    for restype, params in functions.values():
        assert restype in C_TYPES
        for param in params:
            to_ctype(param)
    assert to_ctype("BOOL bEnable") is ctypes.c_int
    assert to_ctype("BOOL *pbEnable")._type_ is ctypes.c_int
    assert to_ctype("HMCCMSG hMCCmsg") is ctypes.c_void_p
    assert to_ctype("char *pszSerialNum")._type_ is ctypes.c_char


def test_constants_the_code_relies_on(header):
    _, constants, _ = header
    assert {name: constants[name] for name in ("ERROR_NOERROR", "ERROR_MCCNOTOPEN", "ERROR_MSGTIMEOUT", "HW_TYPE_MC700B", "SERIALNUM_SIZE")} == {
        "ERROR_NOERROR": 6000, "ERROR_MCCNOTOPEN": 6002, "ERROR_MSGTIMEOUT": 6005, "HW_TYPE_MC700B": 1, "SERIALNUM_SIZE": 16,
    }
    assert [constants[f"MODE_{mode}"] for mode in ("VCLAMP", "ICLAMP", "ICLAMPZERO")] == [0, 1, 2]


def test_every_api_signal_is_scaled_or_auxiliary(header):
    _, constants, _ = header
    signals = {name.split("_", 3)[3] for name in constants if name.startswith(("PRI_SIGNAL_", "SEC_SIGNAL_"))}
    assert signals <= CURRENTS | POTENTIALS.keys() | EXT_COMMANDS.keys() | AUXILIARY_SIGNALS
    assert signals <= SIGNAL_NAMES.keys()


@pytest.mark.parametrize("prefix, mapping", [("PRI_SIGNAL_", PRIMARY_TO_TELEGRAPH), ("SEC_SIGNAL_", SECONDARY_TO_TELEGRAPH)])
def test_api_signal_ids_map_to_the_telegraph_index_of_the_same_signal(header, prefix, mapping):
    _, constants, _ = header
    names = telegraph.signal_names()
    assert len(names) == 40
    for name, api_id in constants.items():
        if name.startswith(prefix) and api_id in mapping:
            assert names[mapping[api_id]] == SIGNAL_NAMES[name.split("_", 3)[3]], name


def test_telegraph_units_factors_follow_the_header():
    constants = telegraph.header_constants()
    factors = {"VOLT": 1, "MILLIVOLT": 1e3, "MICROVOLT": 1e6, "AMP": 1, "MILLIAMP": 1e3, "MICROAMP": 1e6, "NANOAMP": 1e9, "PICOAMP": 1e12}
    assert {constants[f"MCTG_UNITS_VOLTS_PER_{unit}"]: factor for unit, factor in factors.items()} == TELEGRAPH_TO_SI


def test_telegraph_struct_matches_the_header():
    text = sdk_file(telegraph.HEADER).read_text()
    body = re.search(r"struct MC_TELEGRAPH_DATA\s*\{(.*?)\};", text, re.DOTALL).group(1)
    declared = re.findall(r"^\s*(UINT|double|char)\s+(\w+)(?:\[(\d+)\])?;", body, re.MULTILINE)
    c_types = {"UINT": ctypes.c_uint, "double": ctypes.c_double}
    expected = [(name, c_types[kind] if kind != "char" else ctypes.c_char * int(size)) for kind, name, size in declared]
    actual = telegraph.MC_TELEGRAPH_DATA._fields_
    assert [name for name, _ in actual] == [name for name, _ in expected]
    assert all(ctypes.sizeof(a) == ctypes.sizeof(e) for (_, a), (_, e) in zip(actual, expected))


def test_decode_names_mode_signals_and_units():
    packet = telegraph.MC_TELEGRAPH_DATA(
        uVersion=14, uStructSize=256, uChannelID=1, uOperatingMode=0, uScaledOutSignal=0, dAlpha=2.0,
        dScaleFactor=0.5, uScaleFactorUnits=6, uRawOutSignal=11, dRawScaleFactor=10.0, uRawScaleFactorUnits=0,
        uHardwareType=1, szAppVersion=b"2.2.2.2", szSerialNumber=b"00123456",
    )
    fields = telegraph.decode(packet)
    assert (fields["uVersion"], fields["dScaleFactor"], fields["szAppVersion"], fields["szSerialNumber"]) == (14, 0.5, "2.2.2.2", "00123456")
    assert (fields["OperatingModeName"], fields["ScaledOutSignalName"], fields["RawOutSignalName"]) == (
        "VCLAMP", "Membrane Current", "Membrane Potential",
    )
    assert (fields["ScaleFactorUnitsName"], fields["RawScaleFactorUnitsName"]) == ("VOLTS_PER_NANOAMP", "VOLTS_PER_VOLT")
    assert "pcPadding" not in fields
