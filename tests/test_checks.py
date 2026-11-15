import copy
import json
import re
from pathlib import Path

from ommm.checks import disagreements
from ommm.summary import summary

# The "before" snapshot of a break-in trial (V-Clamp). Commander's
# telegraph sent the primary's index and scale (0, 0.5 V/nA) as the secondary; the API and the
# recorded data both say the secondary was membrane potential.
GLITCHED = json.loads((Path(__file__).parent / "data" / "vclamp_stale_secondary_telegraph.json").read_text())

# The same snapshot with the secondary fields the telegraph sent earlier that day (index 11, 10 V/V)
CONSISTENT = copy.deepcopy(GLITCHED)
CONSISTENT["telegraph"] |= {
    "uRawOutSignal": 11,
    "dRawScaleFactor": 10.0,
    "uRawScaleFactorUnits": 0,
    "RawOutSignalName": "Membrane Potential",
    "RawScaleFactorUnitsName": "VOLTS_PER_VOLT",
}


def test_consistent_packet_has_no_disagreements():
    assert disagreements(CONSISTENT["readings"], CONSISTENT["telegraph"]) == []


def test_glitched_secondary_is_caught():
    (problem,) = disagreements(GLITCHED["readings"], GLITCHED["telegraph"])
    assert "secondary" in problem
    assert "VC_MEMBPOTENTIAL" in problem
    assert "index 0" in problem


def test_the_other_mode_tab_showing_is_caught():
    # watch.py: in V-Clamp with Commander's I-Clamp tab showing, the API read that tab
    readings = CONSISTENT["readings"] | {
        "PrimarySignal": 7, "PrimarySignalName": "IC_MEMBPOTENTIAL",
        "SecondarySignal": 14, "SecondarySignalName": "IC_AUXILIARY2",
        "PrimarySignalLPF": 24000.0, "SecondarySignalGain": 2.0,
    }
    problems = disagreements(readings, CONSISTENT["telegraph"])
    assert problems[0] == (
        "tab: Commander is showing the I-Clamp tab while the amplifier is in V-Clamp, so the signals, gains, filters and "
        "compensation read are that tab's: click the V-Clamp tab in Commander and read again"
    )
    text = summary(CONSISTENT | {"readings": readings, "disagreements": problems})
    assert (
        "!! Blocking: tab: Commander is showing the I-Clamp tab while the amplifier is in V-Clamp: "
        "click the V-Clamp tab in Commander and read again"
    ) in text
    assert text.count("I-Clamp tab") == 1


def test_auxiliary_signals_use_the_telegraph_aux_codes():
    # on a 700B: VC secondary Auxiliary 2 with nothing on the aux input -> 44, NOTCONNECTED_AUX
    readings = CONSISTENT["readings"] | {"SecondarySignal": 6, "SecondarySignalName": "VC_AUXILIARY2"}
    telegraph = CONSISTENT["telegraph"] | {"uRawOutSignal": 44, "RawOutSignalName": None, "dRawScaleFactor": 0.0}
    assert disagreements(readings, telegraph) == []


def test_gain_and_cutoff_disagreements_are_caught():
    telegraph = CONSISTENT["telegraph"] | {"dAlpha": 5.0, "dSecondaryLPFCutoff": 100000.0}
    problems = disagreements(CONSISTENT["readings"], telegraph)
    assert any("primary gain" in problem for problem in problems)
    assert any("secondary low-pass" in problem for problem in problems)


def test_box_takes_the_secondary_from_the_api_when_the_telegraph_disagrees():
    snapshot = GLITCHED | {"disagreements": disagreements(GLITCHED["readings"], GLITCHED["telegraph"])}
    text = summary(snapshot)
    assert re.search("^= Secondary Output: +Membrane Potential ", text, re.MULTILINE)
    assert re.search(r"^= Secondary Units: +50 mV/mV \(gain 5\) ", text, re.MULTILINE)  # state()'s table scale, not the stale telegraph's 0.5 V/nA
    assert re.search("^= !! Warning: +secondary signal: API VC_MEMBPOTENTIAL is telegraph index 11, but the telegraph sent index 0", text, re.MULTILINE)
    assert "!! Problem" not in text  # the API's outputs are the pairing the analysis expects


def test_box_for_a_consistent_packet():
    text = summary(CONSISTENT | {"disagreements": []})
    assert "50 mV/mV (gain 5)" in text
    assert "!!" not in text


def test_command_current_secondary_has_no_known_telegraph_index():
    readings = CONSISTENT["readings"] | {"Mode": 1, "ModeName": "ICLAMP", "PrimarySignal": 7, "PrimarySignalName": "IC_MEMBPOTENTIAL",
                                         "SecondarySignal": 9, "SecondarySignalName": "IC_CMDCURRENT"}
    telegraph = CONSISTENT["telegraph"] | {"uOperatingMode": 1, "uScaledOutSignal": 20, "uRawOutSignal": 31}
    assert disagreements(readings, telegraph) == [
        "secondary signal: no telegraph index is known for IC_CMDCURRENT, so its secondary scale and units are not checked"
    ]
