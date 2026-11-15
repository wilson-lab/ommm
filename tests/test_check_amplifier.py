"""scripts/rig/check_amplifier.py on the fake: it covers every row, and replayed from the start of each run on the model
cell (amplifier on, PATCH-1U at CELL, 5 GΩ: tests/data/rig/2026-10-23-modelcell/, and a second run in
tests/data/rig/2026-10-23-modelcell-2/) every check goes as it went on Commander, the differences named."""

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ommm.settings import SETTINGS
from ommm.testing import FakeCommander

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts" / "rig"))
import check_amplifier
import rig

RIG = Path(__file__).parent / "data" / "rig"
RECORDS = [RIG / "2026-10-23-modelcell" / "check_amplifier.json", RIG / "2026-10-23-modelcell-2" / "check_amplifier.json"]
# what the fake cannot know, besides the live meters: a snapshot does not say whether a tab's telegraph signals were
# set since Commander started, so the fake takes the I-Clamp tab's as stale and set_mode refreshes them (a capture before
# the run had set them on the rig); Ext on left Commander in V-Clamp and off in I = 0, from the floating MODE input (P07), so
# set_mode sent a SetMode there, where the fake keeps the mode
DIFFERENCES = [
    ("set_mode I = 0", "ok ['SetMode']", "ok ['SetMode', 'SetPrimarySignal', 'SetSecondarySignal']"),
    ("set_mode V-Clamp", "ok ['SetMode']", "ok []"),
]


def took(step: dict) -> str:
    """A check as compared: a value read, or the outcome (ok and adjusted alike: the fake keeps no Commander steps) and
    what was sent."""
    if "value" in step:  # + 0.0: the rig's -0.0 Pipette Offsets, from before get() turned them into 0
        return repr(step["value"] + 0.0 if isinstance(step["value"], float) else step["value"])
    outcome = "ok" if step.get("outcome") == "adjusted" else step.get("outcome")
    return f"{outcome} {[sent['call'] for sent in step.get('sent', [])]}"


def unpaired(check: str) -> str:
    """A recorded check's name as the check names it now: "step=(5, 'mV')" is "step=5"."""
    return re.sub(r"=\((-?[\d.]+), '[^']+'\)", r"=\1", check)


def test_every_row_has_values_to_check():
    assert {row.label for row in check_amplifier.VALUE_ROWS} == set(check_amplifier.VALUES)


def test_every_button_but_reset_is_pressed_where_commander_has_it():
    pressed = {(mode, name) for mode, names in check_amplifier.PRESSED.items() for name in names}
    buttons = {row.label for row in SETTINGS if row.kind == "action"} - {"Reset to Program Defaults"}
    assert {name for _, name in pressed} == buttons
    assert all(mode in next(row for row in SETTINGS if row.label == name).modes for mode, name in pressed)


@pytest.mark.parametrize("record", RECORDS, ids=lambda path: path.parent.name)
def test_the_check_goes_on_the_fake_as_it_went_on_the_model_cell(tmp_path, monkeypatch, record):
    recorded = json.loads(record.read_text(encoding="utf-8"))
    fake = FakeCommander(recorded["start"]["V-Clamp"], other_tab=recorded["start"]["I-Clamp"])
    monkeypatch.setattr(rig, "screen", SimpleNamespace(commander_windows=list), raising=False)
    monkeypatch.setattr(rig, "shown_tab", lambda: rig.TABS.index(fake.dll.shown))
    monkeypatch.setattr(rig, "screenshot", lambda path, window=None: None)
    monkeypatch.setattr(sys, "platform", "darwin")  # no window to look for
    p = rig.Probe("check_amplifier", "replay", fake, tmp_path, recorded["header"]["setup"])

    check_amplifier.body(p)

    ran = [step for step in p.steps if "check" in step]
    went = [step for step in recorded["steps"] if "check" in step]
    # the rig ran before get() turned the negated sign's -0.0 into 0: "set Pipette Offset -0.0 mV" in I = 0, and
    # before step= and expect= were numbers in the call's unit: "step=(5, 'mV')"
    assert [step["check"] for step in ran] == [unpaired(step["check"].replace(" -0.0 ", " 0.0 ")) for step in went]
    assert all(step["as_expected"] for step in went + ran)
    differ = [(step["check"], took(was), took(step)) for step, was in zip(ran, went)
              if took(step) != took(was) and "MeterValue" not in step["check"] and "write log" not in step["check"]]
    assert differ == DIFFERENCES


@pytest.mark.parametrize("argv", [[], ["--model-cell", "CELL", "--no-cell-attached"]])
def test_the_check_refuses_unless_told_what_is_on_the_headstage(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["check_amplifier.py", *argv])
    with pytest.raises(SystemExit):
        rig.run("check_amplifier", "a question", check_amplifier.body)
