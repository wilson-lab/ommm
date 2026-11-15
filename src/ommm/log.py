"""The write log and trial records.

Every write ommm.Amplifier sends, and every one it refuses, is one JSON line appended to `<log_dir>/<serial>.jsonl`
(default ~/ommm-logs), from any process: MATLAB, a script, the command line. Nothing is held in memory and there is no
lock; a second writer's change shows in the next write's re-read. trial_record() takes the lines back to tell
ommm's changes from the ones made anywhere else: Commander's window, the front panel, the Oscillation Killer, or a
program that does not use ommm.
"""

import json
from datetime import datetime
from pathlib import Path

from ommm.checks import PAIRS
from ommm.commander import changes

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


def append(path: Path, line: dict):
    """One line at the end of the log, written in one call so two processes' lines do not interleave."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(line, default=str) + "\n")


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


def explains(line: dict, section: str, key: str, value) -> bool:
    """Whether a logged write accounts for one field's new value."""
    stem, after, also = line["stem"], line.get("after"), line.get("also") or {}
    if key in also:
        return also[key][1] == value
    read_back = after if isinstance(after, dict) else {stem: after}  # a load's after: the mode and feedback resistors
    mode_write = stem == "Mode" or "Mode" in also  # Mode Switching's line holds the mode it left
    if section == "telegraph":
        return mode_write or stem in TELEGRAPH_STEMS.get(key, ())
    if key in read_back:
        return read_back[key] == value
    return mode_write and key not in GLOBAL_READINGS  # after a mode change the two snapshots read different tabs


def attributed(old: dict, new: dict, writes) -> dict:
    """changes(old, new), each field as {"before", "after", "source"}: "ommm", with the log's time "t", when a write
    logged between the two snapshots accounts for it, else "gui"."""
    start, end = when(old["time"]), when(new["time"])
    sent = [line for line in writes if line.get("outcome") in SENT and start <= when(line["t"]) <= end]
    diffs = changes(old, new)

    def source(section: str, key: str, value) -> dict:
        explaining = [line for line in sent if explains(line, section, key, value)]
        return {"source": "ommm", "t": explaining[-1]["t"]} if explaining else {"source": "gui"}

    result = {}
    for section, fields in diffs.items():
        result[section] = {}
        for key, (before, after) in fields.items():
            reading = PAIRED.get((section, key))
            if reading in diffs.get("readings", {}):  # one change, one source
                by = source("readings", reading, diffs["readings"][reading][1])
            else:
                by = source(section, key, after)
            result[section][key] = {"before": before, "after": after} | by
    return result


def trial_record(before: dict | None, after: dict | None, writes=(), previous: dict | None = None) -> dict:
    """Snapshots from before and after a recording, with what changed during it (`changed`: before -> after) and
    since the previous trial (`between`: previous's after -> before), each field marked with its `source`: "ommm"
    when a line in `writes` (Amplifier.writes_since) logged between the two accounts for it, else "gui". A mode
    change accounts for every reading of the tab and the telegraph, since the snapshots then read the other tab; a
    telegraph field or name that mirrors a reading takes that reading's source.
    `changed` and `between` are None when a snapshot is missing."""
    return {
        "before": before,
        "after": after,
        "changed": attributed(before, after, writes) if before and after else None,
        "between": attributed(previous, before, writes) if previous and before else None,
    }
