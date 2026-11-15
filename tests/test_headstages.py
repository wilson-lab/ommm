"""Headstage 2, alone and beside headstage 1, on the fake: Commander(headstage=2), Amplifier(headstage=2), the fake's
two headstages, and load_config reaching both."""

import ctypes
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

import ommm
from ommm import Amplifier, WriteError, amplifier, mcc
from ommm.commander import Commander, CommanderError
from ommm.testing import FakeCommander
from ommm.testing.fake import FakeDLL, FakeTelegraph, as_headstage

DATA = Path(__file__).parent / "data"
FAKE = ommm.EXAMPLES / "fake"  # the snapshots and the test .mcc the package ships
VCLAMP, ICLAMP = FAKE / "vclamp.json", FAKE / "iclamp.json"
MCC = FAKE / "synthetic.mcc"  # headstage 1 only, V-Clamp, both tabs at 5 GΩ
RST = "ELCTRD_HSTAGE_RST_RNG"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(amplifier.time, "sleep", lambda s: None)


@pytest.fixture
def both():
    """Headstage 1 in V-Clamp, headstage 2 in I-Clamp, on one Commander."""
    return FakeCommander(VCLAMP, other_tab=ICLAMP, other_headstage=ICLAMP, other_headstage_tab=VCLAMP)


def with_headstage_2(tmp_path: Path) -> Path:
    """synthetic.mcc with headstage 2's sections too: headstage 1's, copied, in I-Clamp."""
    text = mcc.read(MCC)
    first, softpanel = text.index("[MC700_CHANNEL1_VCLAMP_SO_0]"), text.index("[MC700_SOFTPANEL_VCLAMP]")
    second = text[first:softpanel].replace("MC700_CHANNEL1", "MC700_CHANNEL2").replace("MODE_SLCT=0", "MODE_SLCT=1")
    path = tmp_path / "both.mcc"
    mcc.write(path, text[:softpanel] + second + text[softpanel:])
    return path


# Commander


def test_commander_takes_headstage_2_when_asked():
    fake = FakeCommander(VCLAMP, other_tab=ICLAMP, headstage=2)
    assert fake.select().channel == 2
    assert [name for name, *_ in fake.dll.calls] == ["FindFirstMultiClamp", "FindNextMultiClamp", "SelectMultiClamp",
                                                     "GetFeedbackResistorVC2"]
    assert fake.dll.calls[2][-1] == 2  # SelectMultiClamp's channel


@pytest.mark.parametrize("headstage", [0, 3, True, "2"])
def test_a_headstage_is_1_or_2(headstage):
    dll = FakeDLL(ommm.load_snapshot(VCLAMP))
    with pytest.raises(ValueError, match="headstage is 1 or 2"):
        Commander(dll=dll, telegraph=FakeTelegraph(dll, None), headstage=headstage)
    assert dll.calls == []


def test_a_headstage_listed_but_not_connected_is_refused():
    fake = FakeCommander(VCLAMP, other_tab=ICLAMP)
    fake.dll.headstages = [fake.headstage, replace(fake.headstage, channel=2)]
    with pytest.raises(CommanderError, match="^" + re.escape("headstage 2 is not connected: Commander answers its feedback "
                                                             "resistor with 6006 (MCCCOMMANDFAIL)") + "$"):
        fake.handle(2)


def test_a_headstage_not_listed_is_refused_as_headstage_1_is():
    # as Commander lists a 700B with nothing on headstage 2: no dataclass repr in the message
    with pytest.raises(CommanderError, match="^headstage 2 is not connected: Commander lists only headstage 1$"):
        FakeCommander(VCLAMP, other_tab=ICLAMP).handle(2)


def test_headstage_2s_snapshot_reads_its_own_feedback_resistors_and_all_four_meters():
    snapshot = FakeCommander(VCLAMP, other_tab=ICLAMP, headstage=2).snapshot()
    readings = snapshot["readings"]
    assert snapshot["headstage"]["channel"] == 2 and snapshot["telegraph"]["uChannelID"] == 2
    assert (readings["FeedbackResistorVC2"], readings["FeedbackResistorIC2"]) == (2, 2)
    assert "FeedbackResistorVC1" not in readings and "FeedbackResistorVC1" not in snapshot["not_applicable"]
    assert (readings["MeterValue1"], readings["MeterValue2"]) == (0.0, 0.0)  # headstage 1, not connected
    assert readings["MeterValue3"] == ommm.load_snapshot(VCLAMP)["readings"]["MeterValue1"]
    assert ommm.state(snapshot)["blocking"] == []


def test_as_headstage_moves_what_names_a_headstage_and_nothing_else():
    snapshot = ommm.load_snapshot(VCLAMP)
    moved = as_headstage(snapshot, 2)
    assert moved["headstage"]["channel"] == 2 and moved["telegraph"]["uChannelID"] == 2
    assert moved["readings"]["FeedbackResistorVC2"] == snapshot["readings"]["FeedbackResistorVC1"]
    assert as_headstage({**snapshot, "not_applicable": {"FeedbackResistorVC2": "MCCCOMMANDFAIL (6006)"}}, 2)["not_applicable"] == {
        "FeedbackResistorVC1": "MCCCOMMANDFAIL (6006)"}
    assert moved["readings"]["MeterValue3"] == snapshot["readings"]["MeterValue1"]
    assert moved["readings"]["Holding"] == snapshot["readings"]["Holding"]
    assert as_headstage(moved, 1) == snapshot and as_headstage(snapshot, 1) is snapshot


# Amplifier


def test_headstage_2_alone_reads_writes_and_logs_to_its_own_file(tmp_path):
    amp = Amplifier(2, log_dir=tmp_path, fake=VCLAMP, other_tab=ICLAMP)
    assert (amp.headstage, amp.get("Feedback Resistor", "MΩ")) == (2, 5000.0)
    amp.set("Holding", -40, "mV")
    assert amp.get("Holding", "mV") == -40.0
    assert amp.log_path == tmp_path / "00123456_headstage2.jsonl"
    assert [json.loads(line)["headstage"] for line in amp.log_path.read_text(encoding="utf-8").splitlines()] == [2]


def test_each_headstage_reads_its_own_meters_by_name(both):
    one, two = Amplifier(commander=both), Amplifier(2, commander=both.handle(2))
    assert two.get("MeterValue4", "pA") == pytest.approx(ommm.load_snapshot(ICLAMP)["readings"]["MeterValue2"] * 1e12)
    with pytest.raises(ValueError, match="MeterValue1 is headstage 1's meter; headstage 2's are MeterValue3, the potential, "
                                         "and MeterValue4, the current"):
        two.get("MeterValue1", "mV")
    with pytest.raises(ValueError, match="MeterValue3 is headstage 2's meter; headstage 1's are MeterValue1"):
        one.get("MeterValue3", "mV")


def test_an_amplifier_takes_its_commanders_headstage(both):
    assert Amplifier(2, commander=both.handle(2)).headstage == 2
    with pytest.raises(ValueError, match="the commander given is on headstage 1, not 2"):
        Amplifier(commander=both, headstage=2)


def test_two_amplifiers_on_one_commander_each_reach_only_their_headstage(tmp_path, both):
    one, two = Amplifier(log_dir=tmp_path, commander=both), Amplifier(2, log_dir=tmp_path, commander=both.handle(2))
    assert (one.get("Mode"), two.get("Mode")) == ("V-Clamp", "I-Clamp")
    two.set("Holding", 20, "pA")
    one.set("Holding", -50, "mV")
    assert (one.get("Holding", "mV"), two.get("Holding", "pA")) == (-50.0, 20.0)
    two.set_mode("I = 0")
    assert (one.snapshot()["telegraph"]["uOperatingMode"], two.snapshot()["telegraph"]["uOperatingMode"]) == (0, 2)
    assert one.log_path != two.log_path
    assert {json.loads(line)["headstage"] for line in two.log_path.read_text(encoding="utf-8").splitlines()} == {2}


def test_each_headstage_has_its_own_panel_in_the_window(both):
    one, two = Amplifier(commander=both), Amplifier(2, commander=both.handle(2))
    both.gui_for(2).set("Holding", 30, "pA")
    both.gui.show_tab("I-Clamp")
    assert (two.get("Holding", "pA"), one.get("Holding", "mV")) == (30.0, 0.0)
    assert both.gui is both.gui_for(1)
    with pytest.raises(ValueError, match="headstage 2 is not connected"):
        FakeCommander(VCLAMP, other_tab=ICLAMP).gui_for(2).show_tab("I-Clamp")


# load_config


def test_a_load_names_the_other_headstage_and_refuses_while_it_holds(tmp_path, both):
    one, two = Amplifier(log_dir=tmp_path, commander=both), Amplifier(2, log_dir=tmp_path, commander=both.handle(2))
    plan = one.load_config(MCC)
    assert plan.outcome == "planned" and plan.reason.startswith("Headstage 1: the mode stays V-Clamp;")
    assert "Headstage 2 is in I-Clamp, Holding off; the restart reaches it too." in plan.reason
    assert "The file holds no settings for headstage 2: check it after the load." in plan.reason
    two.set("Holding", 20, "pA")
    two.enable("Holding", True)
    plan = one.load_config(MCC)
    assert plan.outcome == "refused"
    assert plan.reason.startswith("headstage 2 holds 20 pA in I-Clamp: the load restarts Commander for both headstages")
    assert plan.reason.endswith("Turn headstage 2's Holding off first, or pass release_other_headstage=True "
                                "(ReleaseOtherHeadstage=true in MATLAB)")
    plan = one.load_config(MCC, release_other_headstage=True)
    assert plan.outcome == "planned" and "Headstage 2 holds 20 pA in I-Clamp now; the restart reaches it too" in plan.reason
    assert one.get("Mode") == "V-Clamp" and two.get("Mode") == "I-Clamp"  # the look at headstage 2 left both selected as they were


def test_without_headstage_2_connected_the_plan_is_as_before(tmp_path):
    plan = Amplifier(log_dir=tmp_path, fake=VCLAMP, other_tab=ICLAMP).load_config(MCC)
    assert plan.reason.startswith("the mode stays V-Clamp;") and "headstage 2" not in plan.reason.lower()


def test_with_nothing_on_headstage_2_its_select_fails_with_6002_as_on_the_rig(tmp_path):
    """On a 700B with nothing on headstage 2, Commander listed headstage 1 alone, refused SelectMultiClamp on
    2 with 6002, and every load_config on the candidate was refused for it."""
    fake = FakeCommander(VCLAMP, other_tab=ICLAMP)
    h = fake.headstage
    with pytest.raises(CommanderError) as raised:
        fake.dll.call("SelectMultiClamp", h.model, ctypes.create_string_buffer(h.serial.encode()), h.com_port, h.device, 2)
    assert raised.value.code == 6002
    assert fake.other_headstage("Mode") is None and fake.get("Mode") == 0  # headstage 1 selected again
    write = Amplifier(log_dir=tmp_path, commander=fake).load_config(MCC, confirmed=True)
    assert write.outcome == "ok" and "headstage 2" not in write.reason.lower()


def test_a_commander_gone_while_headstage_2_is_read_still_raises():
    """6002 on headstage 2's select counts as not connected, but the select of this headstage after it fails too."""
    fake = FakeCommander(VCLAMP, other_tab=ICLAMP)
    fake.dll.dead = True
    with pytest.raises(CommanderError) as raised:
        fake.other_headstage("Mode")
    assert raised.value.code == 6002


@pytest.mark.parametrize("code", [6002, 6004, 6006])
def test_a_select_of_headstage_2_that_commander_refuses_counts_as_not_connected(tmp_path, monkeypatch, code):
    fake = FakeCommander(VCLAMP, other_tab=ICLAMP)
    call = fake.dll.call

    def refusing(name, *args):
        if name == "SelectMultiClamp" and args[-1] == 2:
            raise CommanderError(name, code, "refused")
        return call(name, *args)

    monkeypatch.setattr(fake.dll, "call", refusing)
    assert fake.other_headstage("Mode") is None
    assert Amplifier(log_dir=tmp_path, commander=fake).load_config(MCC).outcome == "planned"


def test_headstage_2_loads_only_a_file_with_its_settings(tmp_path):
    amp = Amplifier(2, log_dir=tmp_path, fake=VCLAMP, other_tab=ICLAMP)
    plan = amp.load_config(MCC)
    assert (plan.outcome, plan.reason) == ("refused", "synthetic.mcc holds no settings for headstage 2: load a file "
                                                      "Commander saved with headstage 2 connected (Save Configuration, F5)")
    assert amp.load_config(with_headstage_2(tmp_path)).outcome == "refused"  # headstage 2's file part is in I-Clamp


def test_a_load_on_headstage_2_patches_its_sections_and_restarts_both(tmp_path, both):
    one, two = Amplifier(log_dir=tmp_path, commander=both), Amplifier(2, log_dir=tmp_path, commander=both.handle(2))
    one.enable("Holding", True)
    path, change = with_headstage_2(tmp_path), [("Feedback Resistor", 500, "MΩ", "I-Clamp")]
    assert two.load_config(path, changes=change).reason.startswith("headstage 1 holds 0 mV in V-Clamp:")
    write = two.load_config(path, changes=change, confirmed=True, release_other_headstage=True)
    assert write.outcome == "ok" and write.target == {"Mode": 1, "FeedbackResistorVC2": 2, "FeedbackResistorIC2": 1}
    copy = mcc.values(mcc.read(next((tmp_path / "mcc").iterdir())))
    assert (copy[("MC700_CHANNEL2_ICLAMP", RST)], copy[("MC700_CHANNEL1_ICLAMP", RST)]) == ("1", "2")
    assert (two.headstage, two.get("Feedback Resistor", "MΩ")) == (2, 500.0)
    with pytest.raises(CommanderError, match="Commander was closed or restarted"):  # every handle from before died
        one.get("Mode")
    one.reconnect()
    assert (one.headstage, one.get("Feedback Resistor", "MΩ"), one.get("HoldingEnable")) == (1, 5000.0, False)


def test_headstage_2s_restart_check_reads_its_own_headstage(tmp_path, both):
    two = Amplifier(2, log_dir=tmp_path, commander=both.handle(2))
    both.dll.process._load_config = lambda path: None  # Commander starts with nothing from the file
    with pytest.raises(WriteError, match=r"Feedback Resistor \(I-Clamp\): the file sets 500 MΩ, Commander has 5 GΩ"):
        two.load_config(with_headstage_2(tmp_path), changes=[("Feedback Resistor", 500, "MΩ", "I-Clamp")], confirmed=True)
