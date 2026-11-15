"""Every call names its unit, and settings.to_api is the one conversion: the Amplifier on the two-tab fake."""

from pathlib import Path

import pytest

import ommm
from ommm import Amplifier, WriteError
from ommm.testing import FakeCommander

from conftest import sets

DATA = Path(__file__).parent / "data"
FAKE = ommm.EXAMPLES / "fake"  # the snapshots and the test .mcc the package ships


def amplifier(tmp_path, mode: str = "V-Clamp") -> Amplifier:
    files = [FAKE / "vclamp.json", FAKE / "iclamp.json"]
    snapshot, other_tab = files if mode == "V-Clamp" else files[::-1]
    return Amplifier(log_dir=tmp_path, commander=FakeCommander(snapshot, other_tab=other_tab))


def test_holding_in_mv_is_sent_in_volts(tmp_path):
    amp = amplifier(tmp_path)
    assert amp.set("Holding", -60, "mV").target == -0.06
    assert sets(amp.commander) == [("SetHolding", -0.06)]
    assert amp.get("Holding", "mV") == -60.0
    assert amp.get("Holding", "V") == -0.06
    assert amp.snapshot()["readings"]["Holding"] == -0.06  # snapshots are SI


def test_holding_in_mv_is_refused_in_i_clamp_where_it_is_pa(tmp_path):
    amp = amplifier(tmp_path, "I-Clamp")
    with pytest.raises(WriteError, match="Holding in I-Clamp is a current: pA or nA, not mV"):
        amp.set("Holding", -60, "mV")
    assert amp.set("Holding", -60, "pA").target == pytest.approx(-6e-11)
    assert amp.get("Holding", "pA") == -60.0


@pytest.mark.parametrize("unit, says", [
    (None, "Holding in V-Clamp is a voltage: give a unit: mV"),
    ("millivolts", "Holding in V-Clamp is a voltage: mV, not millivolts"),
    ("pA", "Holding in V-Clamp is a voltage: mV, not pA"),
])
def test_a_missing_unknown_or_wrong_kind_of_unit_is_refused_and_nothing_is_sent(tmp_path, unit, says):
    amp = amplifier(tmp_path)
    with pytest.raises(WriteError, match=says) as raised:
        amp.set("Holding", -60, unit)
    assert (raised.value.write.outcome, sets(amp.commander)) == ("refused", [])
    with pytest.raises(ValueError, match=says):
        amp.get("Holding", unit)


def test_greek_and_ascii_units_are_the_same(tmp_path):
    amp = amplifier(tmp_path, "I-Clamp")
    assert amp.set("Bridge Balance", 10, "MΩ").target == amp.set("Bridge Balance", 10, "MOhm").target == 1e7
    assert amp.get("Bridge Balance", "MΩ") == amp.get("Bridge Balance", "MOhm") == 10.0


def test_rs_compensation_bandwidth_in_khz_goes_to_the_api_in_hz(tmp_path):
    amp = amplifier(tmp_path)
    amp.set("Rs Compensation Bandwidth", 5, "kHz")
    assert sets(amp.commander) == [("SetRsCompBandwidth", 5000.0)]
    assert amp.get("Rs Compensation Bandwidth", "kHz") == 5.0


def test_pipette_offset_is_set_and_read_with_the_panels_sign(tmp_path):
    amp = amplifier(tmp_path, "I-Clamp")
    amp.set("Pipette Offset", 5, "mV")
    assert sets(amp.commander) == [("SetPipetteOffset", -0.005)]  # P14: the API's I-Clamp value is the panel's negated
    assert amp.get("Pipette Offset", "mV") == 5.0


def test_a_zero_pipette_offset_in_i_clamp_is_0_not_minus_0(tmp_path):
    # the API's I-Clamp value is the panel's negated: 0 would come back as -0.0
    amp = amplifier(tmp_path, "I-Clamp")
    amp.set("Pipette Offset", 0, "mV")
    assert str(amp.get("Pipette Offset", "mV")) == "0.0"
    assert amp.plan("Pipette Offset", 10, "mV").reason == "Pipette Offset 0 mV → 10 mV (I-Clamp)"


def test_get_names_the_mode_signals_and_checkboxes_and_takes_no_unit_for_them(tmp_path):
    amp = amplifier(tmp_path)
    assert (amp.get("Mode"), amp.get("Primary Output"), amp.get("Secondary Output")) == ("V-Clamp", "Membrane Current", "Membrane Potential")
    assert (amp.get("Mode Switching"), amp.get("HoldingEnable"), amp.get("holdingenable")) == (False, False, False)
    assert amp.get("Feedback Resistor", "GΩ") == 5.0
    with pytest.raises(ValueError, match="Mode takes no unit, not x"):
        amp.get("Mode", "x")


def test_the_meters_take_a_unit_of_what_they_show(tmp_path):
    # MeterValue1 is the potential, or the resistance while the Resistance meter is on (P17)
    amp = amplifier(tmp_path)
    assert amp.get("MeterValue1", "mV") == pytest.approx(-0.22888184)
    assert amp.get("MeterValue2", "pA") == pytest.approx(-0.80871583)
    with pytest.raises(ValueError, match="^MeterValue1 shows voltage now: give a unit: mV$"):
        amp.get("MeterValue1")
    with pytest.raises(ValueError, match="^MeterValue2 shows current now: pA or nA, not mV$"):
        amp.get("MeterValue2", "mV")
    amp.enable("Resistance Meter", True)
    with pytest.raises(ValueError, match="^MeterValue1 shows resistance now: MOhm or GOhm, not mV$"):
        amp.get("MeterValue1", "mV")
    assert amp.get("MeterValue1", "MOhm") == amp.get("MeterValue1", "M\u2126")
