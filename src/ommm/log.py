"""The write log and trial records.

Every write ommm.Amplifier sends, and every one it refuses, is one JSON line appended to `<log_dir>/<serial>.jsonl`
(ommm.Amplifier says which folder), from any process: MATLAB, a script, the command line. Nothing is held in memory
and there is no lock; a second writer's change shows in the next write's re-read. trial_record() takes the lines back
to tell ommm's changes from the ones made anywhere else: Commander's window, the front panel, the Oscillation Killer,
or a program that does not use ommm.
"""

import json
import math
from datetime import datetime
from pathlib import Path

from ommm.checks import PAIRS, tab_of
from ommm.commander import changes
from ommm.settings import IC, MODES, VC, find, tab_for

SCHEMA = 2
SENT = {"ok", "adjusted", "mismatch", "unknown", "error"}  # outcomes of a call that was sent

# which writes change each telegraph field
TELEGRAPH_STEMS = {
    **dict.fromkeys(("uOperatingMode", "OperatingModeName", "dExtCmdSens"), ("Mode",)),
    **dict.fromkeys(
        ("uScaledOutSignal", "ScaledOutSignalName", "dScaleFactor", "uScaleFactorUnits", "ScaleFactorUnitsName"), ("PrimarySignal",)
    ),
    **dict.fromkeys(
        ("uRawOutSignal", "RawOutSignalName", "dRawScaleFactor", "uRawScaleFactorUnits", "RawScaleFactorUnitsName"), ("SecondarySignal",)
    ),
    "dAlpha": ("PrimarySignalGain", "PrimarySignal"),
    "dLPFCutoff": ("PrimarySignalLPF", "PrimarySignal"),
    "dSecondaryAlpha": ("SecondarySignalGain",),
    "dSecondaryLPFCutoff": ("SecondarySignalLPF",),
    "dMembraneCap": ("WholeCellCompCap", "WholeCellCompEnable"),
    "dSeriesResistance": ("WholeCellCompResist", "WholeCellCompEnable"),
}
# above the tabs: the same whichever tab a snapshot read
GLOBAL_READINGS = {"Mode", "ModeName", "ModeSwitchEnable", "MeterResistEnable", "MeterIrmsEnable",
                   "FeedbackResistorVC1", "FeedbackResistorIC1", "FeedbackResistorVC2", "FeedbackResistorIC2"}
# fields that change with a reading, so they take that reading's source: the telegraph's pairs and the names
PAIRED = {("telegraph", field): reading for _, reading, field in PAIRS} | {
    ("readings", stem + "Name"): stem for stem in ("Mode", "PrimarySignal", "SecondarySignal")}
# what Auto Pipette Offset changes on the other tab, which its line does not hold, by the tab it was pressed on
OTHER_TAB_STEMS = {VC: {"PipetteOffset", "SlowCurrentInjLevel"}, IC: {"PipetteOffset", "Holding", "HoldingEnable"}}


def as_json(value):
    """`value` with each NaN and infinity in it as text ("nan", "inf", "-inf"), which JSON has no number for."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: as_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [as_json(item) for item in value]
    return value


def append(path: Path, line: dict):
    """One line at the end of the log, written in one call so two processes' lines do not interleave."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(as_json(line), default=str) + "\n")


def writes_since(path: Path, mark: int = 0) -> tuple[list[dict], int]:
    """The log's lines after byte offset `mark` (0, or what the last call returned), and the offset to pass next time.
    A line still being written is left for the next call."""
    if not Path(path).exists():
        return [], mark
    with open(path, "rb") as log:
        if mark:
            log.seek(mark - 1)
            if log.read(1) != b"\n":
                raise ValueError(f"{path}: no line starts at mark {mark}: give 0 or a mark writes_since returned for this log")
        tail = log.read()
    complete = tail[: tail.rfind(b"\n") + 1]
    return [json.loads(line) for line in complete.splitlines() if line.strip()], mark + len(complete)


def when(text: str) -> datetime:
    return datetime.fromisoformat(text)


def tab_of_mode(mode: str | None) -> str | None:
    return mode and tab_for(mode)


def tab_and_mode(snapshot: dict) -> tuple[str | None, str | None]:
    """The tab a snapshot's readings came from and its mode, each None where the snapshot does not tell. The tab is
    its output signals', so a snapshot taken with show_active_tab=False gives the tab Commander showed; without them,
    the mode's. The mode is the API's, else the telegraph's."""
    readings = snapshot["readings"]
    mode = MODES.get(readings.get("Mode", (snapshot.get("telegraph") or {}).get("uOperatingMode")))
    return tab_of(readings) or tab_of_mode(mode), mode


def differ(a, b) -> bool:
    """Whether two tabs or modes differ; None, one a snapshot does not tell, differs from any."""
    return a is None or b is None or a != b


def crossed(section: str, old: tuple, new: tuple) -> bool:
    """Whether a mode change accounts for a section's differences between two snapshots, given as (tab, mode): the
    telegraph's when their modes differ; the readings' when they read different tabs and their modes are on different
    tabs, so a tab clicked between two snapshots taken with show_active_tab=False is not the mode change's."""
    if section == "telegraph":
        return differ(old[1], new[1])
    return differ(old[0], new[0]) and differ(tab_of_mode(old[1]), tab_of_mode(new[1]))


def same(section: str, old: tuple, new: tuple) -> bool:
    """Whether two snapshots, given as (tab, mode), read the same tab (readings) or are in the same mode (telegraph)."""
    i = 1 if section == "telegraph" else 0
    return not differ(old[i], new[i])


def took(line: dict, value) -> bool:
    """Whether a reading is what a line that was not read back sent, as Commander may have kept it: within the
    control's resolution."""
    target, mode = line.get("target"), line["mode"]
    # an int too: MATLAB's jsonencode writes a whole number, 5000.0, as 5000, which Python reads back as an int
    if all(isinstance(x, int | float) and not isinstance(x, bool) for x in (target, value)):
        return abs(value - target) <= find(line["stem"], mode).resolution.get(mode, 0.0)
    return value == target


def explains(line: dict, section: str, key: str, value, old: tuple, new: tuple) -> bool:
    """Whether a logged write accounts for one field's new value; `old` and `new` are the two snapshots' (tab, mode),
    as tab_and_mode gives them."""
    stem, after, also = line["stem"], line.get("after"), line.get("also") or {}
    # a load sets both tabs from the file, and logs what the mode it came back in shows (schema 1's after has no Mode);
    # Auto Pipette Offset changes the other tab too. Each accounts for the tab it does not log only between two
    # snapshots of that tab (for the telegraph, of one mode): across them, the mode change's own source decides
    if isinstance(after, dict) and "Mode" in after and (section == "telegraph" or key not in GLOBAL_READINGS):
        mode = MODES.get(after["Mode"])
        if same(section, old, new) and not same(section, (tab_of_mode(mode), mode), new):
            return True
    if stem == "AutoPipetteOffset" and section == "readings" and key in OTHER_TAB_STEMS[tab_for(line["mode"])]:
        if same(section, old, new) and differ(tab_for(line["mode"]), new[0]):
            return True
    if key in also:
        return also[key][1] == value
    if line.get("outcome") == "unknown" and after is None and key == stem:  # sent and not read back: it may have taken
        return took(line, value)
    read_back = after if isinstance(after, dict) else {stem: after}  # a load's after: the mode and feedback resistors
    mode_write = stem == "Mode" or "Mode" in also  # Mode Switching's line holds the mode it left
    if section == "telegraph":
        return crossed(section, old, new) if mode_write else stem in TELEGRAPH_STEMS.get(key, ())
    if key in read_back:
        return read_back[key] == value
    return mode_write and key not in GLOBAL_READINGS and crossed(section, old, new)


def attributed(old: dict, new: dict, writes) -> dict:
    """changes(old, new), each field as {"before", "after", "source"}: "ommm", with the log's time "t", when a write
    logged between the two snapshots accounts for it, else "gui"."""
    start, end = when(old["time"]), when(new["time"])
    sent = [line for line in writes if line.get("outcome") in SENT and start <= when(line["t"]) <= end]
    diffs = changes(old, new)
    ends = tab_and_mode(old), tab_and_mode(new)

    def source(section: str, key: str, value) -> dict:
        explaining = [line for line in sent if explains(line, section, key, value, *ends)]
        return {"source": "ommm", "t": explaining[-1]["t"]} if explaining else {"source": "gui"}

    result = {}
    for section, fields in diffs.items():
        result[section] = {}
        for key, (before, after) in fields.items():
            reading = PAIRED.get((section, key))
            # one change, one source; a reading the later snapshot could not read (None) cannot give it
            if reading in diffs.get("readings", {}) and diffs["readings"][reading][1] is not None:
                by = source("readings", reading, diffs["readings"][reading][1])
            else:
                by = source(section, key, after)
            result[section][key] = {"before": before, "after": after} | by
    return result


def trial_record(before: dict | None, after: dict | None, writes=(), previous: dict | None = None) -> dict:
    """Snapshots from before and after a recording, with what changed during it (`changed`: before -> after) and
    since the previous trial (`between`: previous's after -> before), each field marked with its `source`: "ommm"
    when a line in `writes` (Amplifier.writes_since) logged between the two accounts for it, else "gui". A mode
    change accounts for every reading of the tab when the two snapshots read different tabs, and for the telegraph
    when their modes differ; a load and Auto Pipette Offset for what they change on the tab they do not log, when
    both snapshots read that tab. A write that was sent but not read back (unknown) accounts for its value at what it
    sent, within the control's resolution. A telegraph field or name that mirrors a reading takes that reading's
    source, where the later snapshot read it.
    `changed` and `between` are None when a snapshot is missing."""
    return {
        "before": before,
        "after": after,
        "changed": attributed(before, after, writes) if before and after else None,
        "between": attributed(previous, before, writes) if previous and before else None,
    }
