"""Cross-checks on a snapshot: the API readings against themselves and against the telegraph packet.

Two things go wrong in practice (both seen on a 700B with Commander 2.2.2.2):

- The API reads whichever tab Commander is showing (V-Clamp or I-Clamp), not the active mode:
  with the I-Clamp tab open during V-Clamp, signals, gains, filters and compensation are the
  I-Clamp tab's. The mode reading and the telegraph stay with the active mode.
- The telegraph's signal fields go stale, reporting both outputs as membrane current, until an
  output signal is selected again (after API mode changes; also seen in a recorded trial).
"""

from ommm.settings import (
    AUXILIARY_SIGNALS,
    AUXILIARY_TELEGRAPH,
    MODES,
    PRIMARY_SIGNALS,
    PRIMARY_TO_TELEGRAPH,
    SECONDARY_SIGNALS,
    SECONDARY_TO_TELEGRAPH,
    SIGNAL_PREFIX,
    TABS,
    tab_for,
)

PAIRS = [  # (what, API reading, telegraph field)
    ("mode", "Mode", "uOperatingMode"),
    ("primary gain", "PrimarySignalGain", "dAlpha"),
    ("secondary gain", "SecondarySignalGain", "dSecondaryAlpha"),
    ("primary low-pass", "PrimarySignalLPF", "dLPFCutoff"),
    ("secondary low-pass", "SecondarySignalLPF", "dSecondaryLPFCutoff"),
]
CHECKED = {reading for _, reading, _ in PAIRS} | {"PrimarySignal", "SecondarySignal"}  # what disagreements() checks


def tab_of(readings: dict) -> str | None:
    """The tab the readings came from, "V-Clamp" or "I-Clamp", by the prefix of PrimarySignalName;
    None when that is missing."""
    name = readings.get("PrimarySignalName") or ""
    return next((tab for tab in TABS if name.startswith(SIGNAL_PREFIX[tab])), None)


def disagreements(readings: dict, telegraph: dict | None) -> list[str]:
    """Every inconsistency in a snapshot, as readable sentences; the wrong-tab one comes first."""
    problems = []
    mode, shown = MODES.get(readings.get("Mode")), tab_of(readings)
    if mode and shown and shown != tab_for(mode):
        problems.append(
            f"tab: Commander is showing the {shown} tab while the amplifier is in {mode}, so the "
            f"signals, gains, filters and compensation read are that tab's: click the {tab_for(mode)} tab in Commander "
            "and read again"
        )
    if not telegraph:
        return problems

    for what, reading, field in PAIRS:
        if reading in readings and abs(readings[reading] - telegraph[field]) > 1e-6 * max(1.0, abs(readings[reading])):
            problems.append(f"{what}: API {readings[reading]:g}, telegraph {telegraph[field]:g}")

    for output, reading, field, name, signals, mapping in [
        ("primary", "PrimarySignal", "uScaledOutSignal", "ScaledOutSignalName", PRIMARY_SIGNALS, PRIMARY_TO_TELEGRAPH),
        ("secondary", "SecondarySignal", "uRawOutSignal", "RawOutSignalName", SECONDARY_SIGNALS, SECONDARY_TO_TELEGRAPH),
    ]:
        if reading not in readings:
            continue
        auxiliary = signals.get(readings[reading], "")[3:] in AUXILIARY_SIGNALS
        if auxiliary and telegraph[field] in AUXILIARY_TELEGRAPH:
            continue
        api_name = readings.get(reading + "Name", readings[reading])
        expected = mapping.get(readings[reading])
        if expected is None:  # a Command Current secondary: no index has been observed for it
            problems.append(f"{output} signal: no telegraph index is known for {api_name}, so its {output} scale and units are not checked")
        elif telegraph[field] != expected:
            problems.append(
                f"{output} signal: API {api_name} is telegraph index {expected}, "
                f"but the telegraph sent index {telegraph[field]} ({telegraph[name]}), so its {output} scale and units "
                "are not this output's"
            )
    return problems
