"""The fake Commander against the rig: each behaviour it models, held against the probe record that shows it
(tests/data/rig/2026-10-23/, amplifier on, nothing attached). Most probes are replayed whole: a fake seeded from the
probe's start makes the same writes and Autos and must read back what Commander did, within the row's resolution."""

import json
import os
import re
from pathlib import Path

import pytest
from conftest import sets

import ommm
from ommm.checks import disagreements
from ommm.commander import CommanderError, NotApplicable, parse_header
from ommm.sdk import sdk_file
from ommm.settings import (
    MODES,
    NOT_COVERED,
    PRIMARY_SIGNALS,
    SECONDARY_SIGNALS,
    SETTINGS,
    SIGNAL_PREFIX,
    TABS,
    tab_for,
)
from ommm.testing import FakeCommander
from ommm.testing.fake import (
    CONSTANTS,
    FUNCTIONS,
    SETUP_FUNCTIONS,
    above_the_tabs,
    tab_shown,
)

DATA = Path(__file__).parent / "data"
FAKE = ommm.EXAMPLES / "fake"  # the snapshots and the test .mcc the package ships
RIG = DATA / "rig" / "2026-10-23"
STALE = DATA / "vclamp_stale_secondary_telegraph.json"  # V-Clamp, the telegraph's secondary stale
AUTO_RESULTS = {"PipetteOffset", "Holding", "HoldingEnable", "OutputZeroEnable", "WholeCellCompEnable"}  # what the fake's Autos set
# The Pipette Offset levels (V-Clamp, I-Clamp; V, API sign) a record started with, where its Sets reach them: no API
# reads them, so these are what the last Auto Pipette Offset before it found: for P03 the last P06 Auto of the
# first run; for parity P16's put-back
LEVELS = {"p03_off_list": (0.039298, -0.07490805), "parity": (-0.028562, -0.011071629)}
# what the parity run read on both tabs after each Set
WATCHED = ("PrimarySignalGain", "PrimarySignalLPF", "Holding", "ZapDuration", "BridgeBalEnable", "OutputZeroAmplitude")
# The fake puts V-Clamp Holding's ends at exactly ±1 V less the V-Clamp level; Commander's -1 V end read 0.43 mV inside
# that. The fake's error at a computed edge, not a step Commander stores values on, so it has its own tolerance
# here and stays out of the row's resolution.
HOLDING_END = 5e-4


def record(name: str) -> dict:
    return json.loads((RIG / f"{name}.json").read_text(encoding="utf-8"))


def at_start(probe: dict, levels: tuple[float, float] = (0.0, 0.0)) -> FakeCommander:
    """A fake as the probe found Commander: V-Clamp, its tab shown, both tabs as the probe read them, and the Pipette
    Offset levels given."""
    fake = FakeCommander(probe["start"]["V-Clamp"], other_tab=probe["start"]["I-Clamp"])
    fake.dll.offset_levels = dict(zip(TABS, levels))
    return fake


def read(fake: FakeCommander, stem: str, tab: str | None = None):
    """A reading as the probes record it, on the tab given (shown for the read, then put back)."""
    shown = fake.dll.shown
    fake.gui.show_tab(tab or shown)
    try:
        return fake.get(stem)
    except NotApplicable as error:
        return f"not applicable ({error.code})"
    finally:
        fake.gui.show_tab(shown)


def agrees(stem: str, mode: str, rig, fake) -> bool:
    """Equal, or for a float within the row's resolution in the mode of the tab read."""
    if isinstance(rig, float) and isinstance(fake, float):
        resolution = max((row.resolution.get(mode, 0) for row in SETTINGS if stem in (row.stem, row.enable) and mode in row.modes), default=0)
        return abs(rig - fake) <= resolution + 1e-6 * abs(rig)
    return rig == fake


def select_signals(fake: FakeCommander):
    """Set the active mode's two output signals to what Commander shows, through the fake's raw API, as ommm's writes
    re-select stale ones: the telegraph then reports them for that mode."""
    for stem in ("PrimarySignal", "SecondarySignal"):
        fake._set(stem, fake.get(stem))


def own(section: dict) -> dict:
    """A tab's own part of a snapshot's readings or not_applicable: not the mode, Ext, the meters or Rf."""
    return {name: value for name, value in section.items() if not above_the_tabs(name.removesuffix("Name"))}


def replay(probe: dict, fake: FakeCommander) -> list[tuple]:
    """Each write and Auto the probe made, on the fake, and each reading its notes hold; returns what differs from the
    rig, as (stem, rig, fake). A note that a tab was shown, or that VC was clicked, is that click; any other note is a
    look at the tab it names. The probes set an output signal only with its own tab shown (the put-back shows each tab
    without a note), so such a Set shows that tab first. An Auto Pipette Offset in V-Clamp finds what it found on the
    rig; the other Autos' measurements are not compared."""
    differ = []

    def check(stem, rig, tab=None):
        tab = tab or fake.dll.shown
        if "Get" + stem in FUNCTIONS and not isinstance(rig, dict):
            seen = read(fake, stem, tab)
            mode = fake.dll.mode_name if fake.dll.active_tab == tab else tab  # the mode of the tab read
            if not agrees(stem, mode, rig, seen):
                differ.append((stem, rig, seen))

    for step in probe["steps"]:
        if "press" in step:
            changed = {tab: step.get("changed", {}).get(tab, {}).get("readings", {}) for tab in TABS}
            if step["press"] == "AutoPipetteOffset" and fake.dll.shown == "V-Clamp":
                fake.dll.found_offsets = {tab: changed[tab].get("PipetteOffset", [None, read(fake, "PipetteOffset", tab)])[1] for tab in TABS}
            try:
                fake._call(step["press"])
                error = None
            except CommanderError as caught:
                error = f"{caught.function}: {caught}"  # as the probe records wrote it
            if error != step["error"]:
                differ.append((step["press"], step["error"], error))
            for tab, readings in changed.items():
                for stem, (_, after) in readings.items():
                    if stem in AUTO_RESULTS:
                        check(stem, after, tab)
        elif "write" in step:
            write = step["write"]
            signals = {"PrimarySignal": PRIMARY_SIGNALS, "SecondarySignal": SECONDARY_SIGNALS}.get(write["stem"])
            if signals and write["error_code"] is None:
                name = signals[write["target"]]
                fake.gui.show_tab(next(tab for tab in TABS if name.startswith(SIGNAL_PREFIX[tab])))
            try:
                fake._set(write["stem"], write["target"])
            except CommanderError as caught:
                if caught.code != write["error_code"]:
                    differ.append((write["stem"], write["error_code"], caught.code))
            check(write["stem"], write["after"])
        else:
            if "tab shown" in step["note"]:
                fake.gui.show_tab(TABS[step["tab"]])
            elif step["note"] == "after clicking VC":
                fake.gui.mode("V-Clamp")
            if fake.get("Mode") != step["mode"]:
                differ.append(("Mode", step["mode"], fake.get("Mode")))
            for key, rig in step.items():
                if key.endswith(" tab"):  # "V-Clamp tab": readings with that tab shown
                    for stem, value in rig.items():
                        check(stem, value, key.removesuffix(" tab"))
                elif not key.startswith("MeterValue"):  # live, not modelled
                    check(key, rig, TABS[step["tab"]])
    return differ


@pytest.mark.parametrize("name, differences", [
    ("p01_set_other_tab", []),
    ("p02_setmode_current", []),
    ("p03_off_list", []),
    ("p04_wrong_mode_set", []),
    ("p05_settle", []),
    ("p06_autos", []),
    ("p07_ext_toggle", [("Mode", 1, 0), ("Mode", 2, 0)]),  # Ext on gave I-Clamp, off again I = 0: the mode input floats (P07); the fake keeps the mode
    ("p08_get_options_open", []),
    ("p09_select", []),
    ("p12_set_options_open", []),
    ("p13_holding_enable", []),
    ("p14_pipette_offset_sign", []),
    # Auto Pipette Offset in I-Clamp: Commander's V-Clamp Holding came out 0.43 mV beyond the offset it added (P16);
    # the fake adds the offset as read
    ("p16_auto_offset_other_mode", [("Holding", -0.18399602, -0.183565)] * 2),
    ("p17_meters", []),
    ("p19_mode_switch", []),
])
def test_the_fake_reads_back_what_commander_did_in_each_probe(name, differences):
    probe = record(name)
    assert replay(probe, at_start(probe, LEVELS.get(name, (0.0, 0.0)))) == differences


@pytest.mark.parametrize("name, differences", [
    ("p05_settle", []),
    ("p06_autos", []),
    ("p17_meters", []),
    ("p19_mode_switch", []),
    # Auto Pipette Offset in I-Clamp on the model cell took both tabs' offsets to about what it found (-16.5 mV) and left
    # V-Clamp's Holding alone; the fake does what Commander did with nothing attached: V-Clamp's offset into its
    # Holding, Holding on, the offset to 0
    ("p16_auto_offset_other_mode", [
        ("Holding", -1.2856196e-07, -0.021471), ("PipetteOffset", -0.016534, 0.0), ("PipetteOffset", -0.016545104, -0.01039212),
        ("PipetteOffset", -0.016534, 0.0), ("Holding", -1.2856196e-07, -0.021471), ("HoldingEnable", False, True),
        ("PipetteOffset", -0.016545104, -0.01039212), ("SlowCurrentInjLevel", -0.051013853, -0.051),
    ]),
])
def test_the_fake_reads_back_what_commander_did_in_each_probe_on_the_model_cell(name, differences):
    probe = json.loads((DATA / "rig" / "2026-10-23-modelcell" / f"{name}.json").read_text(encoding="utf-8"))
    assert replay(probe, at_start(probe)) == differences


def differences(parity: dict, levels: tuple[float, float]) -> list[list]:
    """[what was set, what was read, Commander's, the fake's] for each readback of the parity run that differs, on a
    fake started from the run's start with the Pipette Offset levels it started with. The run made raw Sets, each with
    its tab shown and V-Clamp active, and after each read WATCHED on both tabs and the telegraph's Primary Output gain."""
    rig = next(step for step in parity["steps"] if "seen" in step)
    fake = at_start(parity, levels)
    differ = []
    for (tab, stem, value, _), commander in zip(rig["sets"], rig["seen"], strict=True):
        where = f"{stem} {value!r} with the {tab} tab shown"
        fake.gui.show_tab(tab)
        try:
            fake._set(stem, value)
            error = None
        except CommanderError as caught:
            error = caught.code
        readings = {}
        for name in TABS:
            fake.gui.show_tab(name)
            readings[name] = {watched: read(fake, watched) for watched in WATCHED}
        gain = fake.telegraph.read(fake.headstage.serial, fake.headstage.channel)["dAlpha"]
        if commander["error"] != error:
            differ.append([where, "error", commander["error"], error])
        if commander["telegraph_gain"] != gain:
            differ.append([where, "telegraph dAlpha", commander["telegraph_gain"], gain])
        for name in TABS:  # V-Clamp active throughout, so each tab is read in its own mode
            for watched in WATCHED:
                on_rig, on_fake = commander["readings"][name][watched], readings[name][watched]
                at_end = (watched, name) == ("Holding", "V-Clamp") and abs(on_fake) >= 1.0 - abs(levels[0]) - 1e-6
                if not (agrees(watched, name, on_rig, on_fake) or at_end and abs(on_rig - on_fake) <= HOLDING_END):
                    differ.append([where, f"{name} tab {watched}", on_rig, on_fake])
    return differ


def test_the_fake_reads_back_what_commander_did_in_the_parity_run():
    # the P01 tab case, P03's off-list and out-of-range values, P04 on both tabs, and Output Zero across gain 10, each
    # read on both tabs
    assert differences(record("parity"), LEVELS["parity"]) == []


def test_q11_a_primary_signal_brings_its_own_values_and_output_zero_reads_tenfold_below_gain_10():
    probe = record("p10_signal_swap")
    fake = at_start(probe)
    chosen = probe["steps"][1]  # Pipette Potential's own values, as found: the fake cannot know them
    fake.dll.values |= {("V-Clamp", stem, 2): chosen[stem] for stem in
                        ("PrimarySignalGain", "PrimarySignalLPF", "PrimarySignalHPF", "ScopeSignalLPF", "OutputZeroAmplitude", "LeakSubResist")}
    assert replay(probe, fake) == []

    fake._set("PrimarySignal", 2)
    fake._set("PrimarySignalGain", 10)
    fake._set("OutputZeroAmplitude", 0.001)
    fake._set("PrimarySignalGain", 1)  # P10: 1.0038 mV at gain 10 read 10.038 mV at gain 1
    assert fake.get("OutputZeroAmplitude") == pytest.approx(0.01)
    fake._set("PrimarySignalGain", 20)  # parity: and 1.0038 mV again at gain 20
    assert fake.get("OutputZeroAmplitude") == pytest.approx(0.001)


def test_q1_a_set_with_the_other_tab_shown_lands_there_and_the_telegraph_keeps_the_active_modes():
    probe = record("p01_set_other_tab")
    fake = at_start(probe)
    fake.gui.show_tab("I-Clamp")
    fake._set("PrimarySignalGain", 5)
    packet = fake.telegraph.read(fake.headstage.serial, fake.headstage.channel)
    assert packet["dAlpha"] == probe["steps"][2]["telegraph_primary_gain"] == 2.0
    assert (read(fake, "PrimarySignalGain", "V-Clamp"), read(fake, "PrimarySignalGain", "I-Clamp")) == (2.0, 5.0)


@pytest.mark.parametrize("show_the_active_tab", [
    lambda fake: fake._set("Mode", 0),  # P02: SetMode(current)
    lambda fake: fake.select(),  # P09
    lambda fake: fake.gui.mode("V-Clamp"),  # P02: the VC button
])
def test_q2_q10_setmode_select_and_the_mode_button_show_the_active_modes_tab(show_the_active_tab):
    fake = at_start(record("p02_setmode_current"))
    fake.gui.show_tab("I-Clamp")
    show_the_active_tab(fake)
    assert (fake.get("Mode"), fake.dll.shown) == (0, "V-Clamp")


def test_q24_a_mode_change_shows_at_once_in_the_api_the_tab_and_the_telegraph():
    fake = at_start(record("p19_mode_switch"))
    for mode, tab in [(2, "I-Clamp"), (1, "I-Clamp"), (2, "I-Clamp"), (0, "V-Clamp")]:
        fake._set("Mode", mode)
        packet = fake.telegraph.read(fake.headstage.serial, fake.headstage.channel)
        assert (fake.get("Mode"), fake.dll.shown, packet["uOperatingMode"]) == (mode, tab, mode)


def test_q4_q22_a_set_or_auto_outside_the_mode_is_6004_and_writes_nothing():
    fake = at_start(record("p04_wrong_mode_set"))
    with pytest.raises(CommanderError, match=r"^SetBridgeBalEnable failed: AXMCCMSG: Invalid parameter specified\. \(6004\)") as raised:
        fake._set("BridgeBalEnable", True)
    assert raised.value.function == "SetBridgeBalEnable"
    with pytest.raises(CommanderError, match="6004"):
        fake._call("AutoBridgeBal")
    fake._set("Mode", 2)
    fake._set("Mode", 1)
    with pytest.raises(CommanderError, match="6004"):
        fake._set("MeterIrmsEnable", True)  # P17: Irms in I-Clamp
    assert (read(fake, "BridgeBalEnable"), read(fake, "RsCompEnable", "V-Clamp")) == (False, False)
    assert fake.get("MeterIrmsEnable") is False  # read on any tab, as above the tabs


@pytest.mark.parametrize("name, send", [
    ("p21_raw_periods", lambda fake, stem, value: fake.dll.call("Set" + stem, value)),  # through the DLL: a period in s
    ("p21_test_signal_frequency", lambda fake, stem, value: fake._set(stem, value)),  # in Hz, _set sending the period
])
def test_q27_the_frequency_setter_takes_a_period_and_commander_keeps_the_step_whose_period_is_nearest(name, send):
    # the getter reads Hz; 3 Hz is kept as 5 Hz and 70 Hz as 60 Hz, by period
    probe = json.loads((DATA / "rig" / "2026-10-23-modelcell" / f"{name}.json").read_text(encoding="utf-8"))
    fake = at_start(probe)
    writes = [step["write"] for step in probe["steps"] if step.get("write", {}).get("stem") in ("Mode", "TestSignalFrequency")]
    for write in writes:
        send(fake, write["stem"], write["target"])
        assert fake.get(write["stem"]) == write["after"]
    assert len(writes) > 30


def test_q8_ext_toggles_whatever_the_value_and_greys_out_the_mode():
    fake = at_start(record("p07_ext_toggle"))
    fake._set("ModeSwitchEnable", True)
    assert fake.get("ModeSwitchEnable") is True
    fake._set("Mode", 1)  # with Ext on the mode input decides
    with pytest.raises(ValueError, match="^Commander's mode buttons are greyed out while Mode Switching is on$"):
        fake.gui.mode("I-Clamp")
    fake._set("ModeSwitchEnable", True)
    assert (fake.get("ModeSwitchEnable"), fake.get("Mode")) == (False, 0)


def test_the_gui_clicks_a_checkbox_by_its_name_on_the_window_ext_included():
    fake = at_start(record("p07_ext_toggle"))
    fake.gui.enable("Ext", True)
    assert fake.get("ModeSwitchEnable") is True
    fake.gui.enable("Ext", False)
    fake.gui.show_tab("I-Clamp")
    fake.gui.enable("Tuning", True)
    assert fake.get("TestSignalEnable") is True
    with pytest.raises(ValueError, match="offers no Seal Test checkbox on the I-Clamp tab"):
        fake.gui.enable("Seal Test", True)


def test_the_gui_clicks_a_checkbox_by_its_api_name_too_as_set_takes_stems():
    fake = FakeCommander(FAKE / "vclamp.json")
    fake.gui.enable("HoldingEnable", True)
    fake.gui.enable("osckillerenable", True)
    assert (fake.get("HoldingEnable"), fake.get("OscKillerEnable")) == (True, True)
    fake.gui.enable("Resistance", True)  # the window's own word, as enable() takes it
    assert fake.get("MeterResistEnable") is True
    with pytest.raises(ValueError, match="offers no BridgeBalEnable checkbox on the V-Clamp tab"):
        fake.gui.enable("BridgeBalEnable", True)


def test_the_gui_takes_a_tab_or_mode_in_any_case():
    fake = FakeCommander(FAKE / "vclamp.json", other_tab=FAKE / "iclamp.json")
    fake.gui.show_tab("i-clamp")
    assert (fake.dll.shown, fake.get("Mode")) == ("I-Clamp", 0)
    fake.gui.mode("i = 0")
    assert (fake.dll.shown, fake.get("Mode")) == ("I-Clamp", 2)


@pytest.mark.parametrize("click, name", [("show_tab", "voltage clamp"), ("show_tab", "V-Clamp 1"), ("mode", "current clamp"), ("mode", "V-Clamp 1")])
def test_the_gui_refuses_a_tab_or_mode_it_does_not_know_and_changes_nothing(click, name):
    fake = FakeCommander(FAKE / "vclamp.json", other_tab=FAKE / "iclamp.json")
    before = dict(fake.dll.values)
    with pytest.raises(ValueError, match="'V-Clamp', 'I-Clamp' or 'I = 0'"):
        getattr(fake.gui, click)(name)
    assert (fake.dll.values, fake.dll.shown, sets(fake)) == (before, "V-Clamp", [])


def test_the_gui_chooses_an_output_signal_by_commanders_name_for_it():
    fake = FakeCommander(FAKE / "vclamp.json")
    fake.gui.set("Primary Output", "Membrane Potential")
    fake.gui.set("Secondary Output", "Membrane Current")
    assert (fake.get("PrimarySignal"), fake.get("SecondarySignal")) == (1, 0)


@pytest.mark.parametrize("args, says", [
    (("Feedback Resistor", 500, "MΩ"), "Feedback Resistor changes only by restarting Commander with a .mcc file"),
    (("Bridge Balance", 10, "MΩ"), "offers no Bridge Balance on the V-Clamp tab in V-Clamp"),
    (("Holding", -60, "pA"), "Holding in V-Clamp is a voltage: mV, not pA"),
    (("Holding", -60), "Holding in V-Clamp is a voltage: give a unit: mV"),
    (("Primary Output", "Membrane Voltage"), "Primary Output on the V-Clamp tab is one of Membrane Current, Membrane Potential"),
    (("Cp Slow Tau x20", True), 'Cp Slow Tau x20 is a checkbox: turn it on or off with gui.enable("Cp Slow Tau x20", on)'),
])
def test_the_gui_refuses_what_the_window_does_not_offer_and_changes_nothing(args, says):
    fake = FakeCommander(FAKE / "vclamp.json")
    before = dict(fake.dll.values)
    with pytest.raises(ValueError, match=re.escape(says)):
        fake.gui.set(*args)
    assert (fake.dll.values, sets(fake)) == (before, [])


def test_q15_q5_the_api_allows_what_the_window_refuses():
    fake = at_start(record("p13_holding_enable"))
    assert fake.get("FeedbackResistorVC1") == 2  # 5 GΩ, where the window greys Whole Cell out
    fake._set("WholeCellCompEnable", True)
    fake._call("AutoWholeCellComp")
    fake._set("Mode", 2)
    fake._set("Mode", 1)
    fake._set("SlowCurrentInjEnable", True)
    fake._set("HoldingEnable", True)
    assert (fake.get("HoldingEnable"), fake.get("SlowCurrentInjEnable"), read(fake, "WholeCellCompEnable", "V-Clamp")) == (True, True, True)


def test_q18_the_gui_sets_the_panels_pipette_offset_and_the_api_reads_it_negated_in_i_clamp():
    fake = at_start(record("p14_pipette_offset_sign"))
    fake.gui.mode("I = 0")
    fake.gui.mode("I-Clamp")
    fake.gui.set("Pipette Offset", 5, "mV")
    assert fake.get("PipetteOffset") == pytest.approx(-0.005)
    assert read(fake, "PipetteOffset", "V-Clamp") == 0.0


def test_q25_gui_checkboxes_change_the_readings_and_not_the_telegraph_and_tau_x20_multiplies_tau():
    probe = record("p20_gui_telegraph")
    fake = at_start(probe)
    before = fake.telegraph.read(fake.headstage.serial, fake.headstage.channel)
    fake.gui.enable("Cp Slow Tau x20", True)
    for checkbox, stem in [("Holding", "HoldingEnable"), ("Seal Test", "TestSignalEnable"), ("Rs Compensation", "RsCompEnable"),
                           ("Output Zero", "OutputZeroEnable"), ("Leak Subtraction", "LeakSubEnable")]:
        fake.gui.enable(checkbox, True)
        assert fake.get(stem) is True
    assert fake.telegraph.read(fake.headstage.serial, fake.headstage.channel) == before
    tau_x20 = next(step for step in probe["steps"] if step.get("note") == "V-Clamp tab: 'Tau x20' clicked")
    assert fake.get("SlowCompTau") == tau_x20["changed"]["readings"]["SlowCompTau"][1] == 2e-4


def test_q25_a_mode_button_sends_the_new_modes_values():
    probe = record("p20_gui_telegraph")
    fake = at_start(probe)
    serial, channel = fake.headstage.serial, fake.headstage.channel
    fake.gui.mode("I = 0")
    select_signals(fake)  # as on the rig, I-Clamp's signals were set since Commander started (decision 11)
    fake.gui.mode("V-Clamp")
    clicks = [step for step in probe["steps"] if step.get("note", "").startswith("mode button")]
    for click, mode in zip(clicks, ["I = 0", "I-Clamp", "I = 0", "V-Clamp"], strict=True):
        before = fake.telegraph.read(serial, channel)
        fake.gui.mode(mode)
        after = fake.telegraph.read(serial, channel)
        rig = click["packets"][0]["differs"]
        assert {key for key in after if after[key] != before[key]} == rig.keys()
        assert {key: after[key] for key in rig} == pytest.approx({key: new for key, (_, new) in rig.items()})


def test_the_telegraphs_signals_stay_stale_until_that_modes_signals_are_set():
    fake = FakeCommander(STALE)
    assert fake.snapshot()["disagreements"][0].startswith("secondary signal:")
    fake._set("PrimarySignalGain", 5)  # a gain changes the telegraph's gain only
    assert fake.snapshot()["disagreements"][0].startswith("secondary signal:")
    select_signals(fake)
    assert fake.snapshot()["disagreements"] == []
    fake._set("Mode", 2)  # I = 0's signals not set since the fake started: still the V-Clamp ones
    assert {problem.partition(":")[0] for problem in fake.snapshot()["disagreements"]} == {"primary signal", "secondary signal"}
    select_signals(fake)
    snapshot = fake.snapshot()
    assert snapshot["disagreements"] == []
    assert (snapshot["telegraph"]["uOperatingMode"], snapshot["telegraph"]["dExtCmdSens"]) == (2, 0.0)


def test_the_two_example_snapshots_make_a_two_tab_fake():
    fake = FakeCommander(FAKE / "vclamp.json", other_tab=FAKE / "iclamp.json")  # taken in V-Clamp and in I-Clamp
    assert (fake.get("Mode"), fake.dll.shown, fake.snapshot()["disagreements"]) == (0, "V-Clamp", [])
    fake.gui.show_tab("I-Clamp")
    served, saved = fake.snapshot(show_active_tab=False), ommm.load_snapshot(FAKE / "iclamp.json")
    assert (own(served["readings"]), own(served["not_applicable"])) == (own(saved["readings"]), own(saved["not_applicable"]))
    assert served["readings"]["MeterIrmsEnable"] is False  # the V-Clamp snapshot's: above the tabs
    with pytest.raises(ValueError, match="the other tab's snapshot is of the V-Clamp tab too"):
        FakeCommander(FAKE / "vclamp.json", other_tab=STALE)


def test_a_snapshot_taken_with_the_other_tab_shown_needs_the_active_tabs_beside_it():
    # alone, every snapshot the fake serves would read the active tab, which it would fill with placeholders
    saved = ommm.load_snapshot(FAKE / "iclamp.json")
    saved["readings"]["Mode"] = 0  # the I-Clamp tab shown in V-Clamp
    with pytest.raises(ValueError, match=r"^this snapshot was taken with the I-Clamp tab shown in V-Clamp: give other_tab= "
                                         r"\(MATLAB OtherTab=\) a snapshot of the V-Clamp tab, or read it as saved with ommm.load_snapshot\(file\)$"):
        FakeCommander(saved)
    fake = FakeCommander(saved, other_tab=FAKE / "vclamp.json")
    assert (fake.dll.shown, fake.snapshot()["readings"]["PrimarySignalName"]) == ("I-Clamp", "VC_MEMBCURRENT")


def test_the_tab_no_snapshot_showed_holds_placeholders_with_its_lowpass_filters_bypassed():
    fake = FakeCommander(FAKE / "vclamp.json")
    fake.gui.show_tab("I-Clamp")
    assert (fake.get("PrimarySignal"), fake.get("PrimarySignalLPF"), fake.get("SecondarySignalLPF")) == (7, 1e5, 1e5)


def test_a_signal_id_off_the_tabs_list_stores_that_tabs_membrane_potential():
    # the V-Clamp ids sent with the I-Clamp tab shown left Membrane Potential on both outputs
    fake = FakeCommander(FAKE / "iclamp.json")
    fake._set("PrimarySignal", 0)
    fake._set("SecondarySignal", 1)
    assert (fake.get("PrimarySignal"), fake.get("SecondarySignal")) == (7, 7)


def test_a_gain_set_the_snapshot_had_no_gain_for_fails_with_6006():
    saved = ommm.load_snapshot(FAKE / "vclamp.json")
    del saved["readings"]["PrimarySignalGain"]
    with pytest.raises(CommanderError, match=r"^SetPrimarySignalGain failed: not in the snapshot the fake started from \(6006\)"):
        FakeCommander(saved)._set("PrimarySignalGain", 5)


def test_values_are_stored_as_float32_and_a_getter_that_does_not_apply_hands_back_its_code():
    fake = FakeCommander(FAKE / "vclamp.json")
    fake._set("Holding", 0.1)
    assert fake.dll.values[("V-Clamp", "Holding")] == 0.10000000149011612
    assert fake.get("Holding") == 0.1
    with pytest.raises(NotApplicable, match=r"^GetBridgeBalResist does not apply now: INVALIDPARAMETER \(6004\)"):
        fake.get("BridgeBalResist")
    assert 0 < fake.dll.values[("V-Clamp", "BridgeBalResist")] < 1e-40  # 6004 as a float32's bits
    assert fake.snapshot()["not_applicable"]["BridgeBalResist"] == "INVALIDPARAMETER (6004)"


def test_a_timeout_at_call_k_fails_once_and_changes_nothing():
    fake = FakeCommander(FAKE / "vclamp.json")
    fake.dll.fail_at(2)
    fake._set("PrimarySignalGain", 5)
    with pytest.raises(CommanderError, match=r"^SetPrimarySignalGain failed: MSGTIMEOUT \(6005\)"):
        fake._set("PrimarySignalGain", 10)
    assert fake.get("PrimarySignalGain") == 5.0


def test_a_dead_commander_answers_nothing():
    fake = FakeCommander(FAKE / "vclamp.json")
    fake.dll.dead = True
    with pytest.raises(CommanderError, match=r"^GetMode failed: MCCNOTOPEN \(6002\)"):
        fake.get("Mode")
    with pytest.raises(TimeoutError, match="no telegraph from Commander"):
        fake.telegraph.read(fake.headstage.serial, fake.headstage.channel)
    # a snapshot stops at the first 6002, as at a timeout: every remaining read would fail too
    calls = len(fake.dll.calls)
    with pytest.raises(CommanderError) as raised:
        fake.snapshot()
    assert str(raised.value).endswith("Commander was closed or restarted: reconnect() (amp.reconnect() in Python, a.reconnect() in MATLAB) (6002)")
    assert (raised.value.code, len(fake.dll.calls)) == (6002, calls + 1)


def test_a_snapshot_sends_no_set_or_action():
    fake = FakeCommander(FAKE / "vclamp.json")
    fake.snapshot()
    assert {name for name, *_ in fake.dll.calls} <= {name for name in FUNCTIONS if name.startswith("Get")} | {"SelectMultiClamp"}


def test_a_snapshot_shows_the_active_modes_tab_first_unless_told_not_to():
    fake = FakeCommander(FAKE / "vclamp.json", other_tab=FAKE / "iclamp.json")
    fake.gui.show_tab("I-Clamp")
    assert fake.snapshot(show_active_tab=False)["readings"]["PrimarySignalName"] == "IC_MEMBPOTENTIAL"
    assert fake.dll.shown == "I-Clamp"  # a person's tab click stays
    fake.dll.calls.clear()
    snapshot = fake.snapshot()  # P09: SelectMultiClamp, then every read from the active mode's tab
    assert (snapshot["readings"]["PrimarySignalName"], snapshot["disagreements"], fake.dll.shown) == ("VC_MEMBCURRENT", [], "V-Clamp")
    assert fake.dll.calls[0][0] == "SelectMultiClamp"


def test_set_and_call_match_commander_by_construction():
    # a typo or a reading with no setter raises KeyError, as on Commander; private
    fake = FakeCommander(FAKE / "vclamp.json")
    for name in ("PrimarySignalGian", "FeedbackResistorVC1", "MeterValue1"):
        with pytest.raises(KeyError, match=f"Set{name}"):
            fake._set(name, 5)
    assert fake.constant_name("ERROR_", 6004) == "INVALIDPARAMETER"
    assert (len(fake.functions), fake.headstages(), sets(fake)) == (121, [fake.headstage], [])


def test_the_fakes_setup_functions_are_the_ones_no_row_covers():
    assert SETUP_FUNCTIONS.keys() == dict(NOT_COVERED).keys()


SAVED = sorted(FAKE.glob("*.json")) + sorted(DATA.glob("*.json")) + sorted(RIG.glob("*.json"))


@pytest.mark.parametrize("path", SAVED, ids=lambda path: path.name)
def test_a_snapshot_is_served_as_saved(path):
    saved = json.loads(path.read_text(encoding="utf-8"))
    for group in [{"": saved}] if "readings" in saved else [saved["start"], saved["end"]]:  # a record's: both tabs
        for snapshot in group.values():
            active = tab_for(MODES[snapshot["readings"]["Mode"]])
            if tab_shown(snapshot["readings"]) == active:
                served = FakeCommander(snapshot).snapshot(show_active_tab=False)
                assert {key: served[key] for key in ("readings", "not_applicable", "telegraph", "errors")} == {
                    key: snapshot[key] for key in ("readings", "not_applicable", "telegraph", "errors")
                }
                assert served["disagreements"] == disagreements(snapshot["readings"], snapshot["telegraph"])
                continue
            # the other tab shown: alone it would serve placeholders for every snapshot, so the fake says what to give
            with pytest.raises(ValueError, match=f"taken with the {tab_shown(snapshot['readings'])} tab shown in "
                                                 f"{MODES[snapshot['readings']['Mode']]}: give other_tab="):
                FakeCommander(snapshot)
            fake = FakeCommander(group[active], other_tab=snapshot)
            fake.gui.show_tab(tab_shown(snapshot["readings"]))
            served = fake.snapshot(show_active_tab=False)
            assert [own(served[key]) for key in ("readings", "not_applicable")] == [own(snapshot[key]) for key in ("readings", "not_applicable")]


@pytest.mark.skipif(not os.environ.get("OMMM_SDK_DIR"), reason="OMMM_SDK_DIR is not set")
def test_the_fakes_functions_and_constants_are_the_headers():
    functions, constants, _ = parse_header(sdk_file("AxMultiClampMsg/AxMultiClampMsg.h").read_text())
    typed = {name: (restype, [param.split()[0] + (" *" if "*" in param else "") for param in params])
             for name, (restype, params) in functions.items()}
    assert typed == FUNCTIONS
    assert {name: constants[name] for name in CONSTANTS} == CONSTANTS
    assert {name for name in constants if name.startswith(("ERROR_", "MODE_", "PRI_SIGNAL_", "SEC_SIGNAL_"))} <= CONSTANTS.keys()
