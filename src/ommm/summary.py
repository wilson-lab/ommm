"""A compact box of what Commander is set to now.

The mode, feedback resistor and output scales are state()'s, so the box and state() agree. Settings
Commander can't report (the primary filter type) come from `manual`, the values entered by hand, and
are marked "(manually set)". What state() blocks or flags (the wrong tab, a mode or gain mismatch,
a stale telegraph) comes last, once each, as "!! Blocking", "!! Problem" and "!! Warning" lines.

The API reads the tab Commander shows. When that is not the active mode's tab, the readings are the
other tab's, and the box gives only the headstage, the mode and the !! lines.
"""

from ommm.checks import tab_of
from ommm.settings import PRIMARY_CUTOFFS, SIGNAL_NAMES, find, tab_for
from ommm.state import state

MANUAL_KEYS = ["lpf_type_v_clamp", "lpf_type_i_clamp"]  # the primary filter type, by mode
LABEL_WIDTH = 21  # the labels' column, at most: a longer label, Commander's, pushes its value along


def signal(api_name: str | None) -> str:
    """'VC_MEMBCURRENT' -> 'Membrane Current', in Commander's words."""
    return SIGNAL_NAMES.get((api_name or "?").partition("_")[2], api_name or "?")


def rf(ohms: float | None) -> str:
    """A feedback resistor as Commander writes it: '500 MΩ', '5 GΩ'."""
    if ohms is None:
        return "?"
    return f"{ohms / 1e9:g} GΩ" if ohms >= 1e9 else f"{ohms / 1e6:g} MΩ"


def khz(hz: float) -> str:
    return "bypass" if hz >= 1e5 else f"{hz / 1000:g} kHz"  # 1e5 is the telegraph's MCTG_LPF_BYPASS


def pf(farads: float) -> str:
    return f"{round(farads * 1e12, 2) + 0.0:g} pF"  # Commander's precision; + 0.0 turns -0.0 into 0


def mohm(ohms: float) -> str:
    return f"{round(ohms / 1e6, 3) + 0.0:g} MΩ"


def primary_filter(cutoff_hz: float, entered: str | None) -> tuple[str, str | None]:
    """The Primary Filter value, and a warning if the entered type can't have that cutoff."""
    if cutoff_hz >= 1e5:
        return "bypass", None
    types = [name for name, cutoffs in PRIMARY_CUTOFFS.items() if round(cutoff_hz) in cutoffs]
    if len(types) == 1:
        (from_cutoff,) = types
        if entered and entered != from_cutoff:
            return f"{khz(cutoff_hz)} {from_cutoff.capitalize()} (from cutoff)", f"entered {entered}, but {khz(cutoff_hz)} is {from_cutoff}-only"
        return f"{khz(cutoff_hz)} {from_cutoff.capitalize()} ({'manually set, cutoff agrees' if entered else 'from cutoff'})", None
    if not types:  # bypass, or a cutoff not in the manual's lists
        return f"{khz(cutoff_hz)}" + (f" {entered.capitalize()} (manually set)" if entered else " (type not reported)"), None
    return f"{khz(cutoff_hz)} " + (f"{entered.capitalize()} (manually set)" if entered else "(type not reported, both have this cutoff)"), None


def secondary_filter(cutoff_hz: float) -> str:
    return f"{khz(cutoff_hz)} single-pole Bessel (fixed)" if round(cutoff_hz) == 10000 else khz(cutoff_hz)


def on(enabled: bool) -> str:
    return "on" if enabled else "off"


def has(label: str, mode: str) -> bool:
    """Whether the mode has the control, by the settings table, as get() asks it: I = 0 shares the I-Clamp tab, but
    has no Holding, Bridge Balance or Pipette Capacitance Neutralization."""
    return mode in find(label).modes


def compensation(readings: dict, mode: str) -> list[tuple[str, str]]:
    r = readings
    # with the window's sign, which in I-Clamp and I = 0 is the API's negated (docs/quirks.md)
    offset = r["PipetteOffset"] * find("Pipette Offset").sign.get(mode, 1)
    pipette_offset = ("Pipette Offset", f"{offset * 1e3 + 0.0:g} mV")  # + 0.0 turns -0.0 into 0
    if mode == "V-Clamp":
        return [
            pipette_offset,
            ("Cp Fast Capacitance", pf(r["FastCompCap"])),
            ("Cp Slow Capacitance", pf(r["SlowCompCap"])),
            ("Whole Cell", f"{on(r['WholeCellCompEnable'])} ({pf(r['WholeCellCompCap'])}, {mohm(r['WholeCellCompResist'])})"),
            ("Rs Compensation", f"{on(r['RsCompEnable'])} (correction {r['RsCompCorrection']:g}%, prediction {r['RsCompPrediction']:g}%)"),
        ]
    rows = [pipette_offset]
    if has("Bridge Balance", mode):
        rows.append(("Bridge Balance", f"{on(r['BridgeBalEnable'])} ({mohm(r['BridgeBalResist'])})"))
    if has("Pipette Capacitance Neutralization", mode):
        rows.append(("Pipette Capacitance Neutralization", f"{on(r['NeutralizationEnable'])} ({pf(r['NeutralizationCap'])})"))
    return rows


def summary(snapshot: dict, manual: dict | None = None) -> str:
    """The box `ommm --summary` prints. In manual, e.g. {"lpf_type_v_clamp": "Bessel"}, case does not
    matter; an unknown key or filter type raises ValueError, since it would go unused without a word."""
    manual = {key: str(value).lower() for key, value in (manual or {}).items()}
    if unknown := [key for key in manual if key not in MANUAL_KEYS]:
        raise ValueError(f"manual: unknown key {unknown}; use {MANUAL_KEYS}")
    if unknown := [value for value in manual.values() if value not in PRIMARY_CUTOFFS]:
        raise ValueError(f"manual: unknown filter type {unknown}; use {list(PRIMARY_CUTOFFS)}")
    headstage = snapshot["headstage"]
    found = state(snapshot)
    errors = dict(snapshot["errors"])
    rows = [("Headstage", f"{headstage['channel']} ({headstage['serial']})"), ("Mode", found["mode"] or "?")]
    if found["mode"] and tab_of(snapshot["readings"]) == tab_for(found["mode"]):
        try:
            rows += setting_rows(snapshot, found, manual)
        except KeyError as missing:  # a reading Commander didn't return, or one that doesn't apply now
            (key,) = missing.args
            why = snapshot["not_applicable"].get(key) or errors.pop(key, "not in the snapshot")
            rows.append(("!! Not read", f"{key}: {why}"))
    rows += [("!! Error", error) for error in errors.values()]
    for label, entries in (("!! Blocking", "blocking"), ("!! Problem", "problems"), ("!! Warning", "warnings")):
        for entry in found[entries]:
            # checks.py's sentences go on with ", so <what that means for the readings>", left out since
            # the label says as much; a ": <what to do>" at the end stays
            what, _, meaning = entry.partition(", so ")
            _, colon, fix = meaning.partition(": ")
            rows.append((label, what + colon + fix))
    return box(rows)


def box(rows: list[tuple[str, str] | None]) -> str:
    """None rows are separators."""
    label_width = min(max(len(row[0]) for row in rows if row) + 1, LABEL_WIDTH)
    inner = [f"{row[0] + ':':<{label_width}} {row[1]}" if row else None for row in rows]
    width = max(35, max(len(line) for line in inner if line) + 4)
    lines = [f"{'♡====MultiClamp 700B=====♡':=^{width}}"]
    lines += [f"= {line:<{width - 4}} =" if line else f"= {'-' * (width - 4)} =" for line in inner]
    lines.append("=" * width)
    return "\n".join(lines)


def units(output: dict, gain: float) -> str:
    """state()'s scale x gain, currents in V/nA and potentials in mV/mV; '?' when state() does not
    trust it (the reason is in the !! lines). gain is the API's, which a trusted output's telegraph matches."""
    if not output["trusted"]:
        scaled = "?"
    elif output["units"] == "V/A":
        scaled = f"{output['scale'] * gain / 1e9:g} V/nA"
    else:
        scaled = f"{output['scale'] * gain:g} mV/mV"
    return f"{scaled} (gain {gain:g})"


def setting_rows(snapshot: dict, found: dict, manual: dict) -> list[tuple[str, str] | None]:
    readings, telegraph = snapshot["readings"], snapshot["telegraph"]
    mode = found["mode"]
    vc = mode == "V-Clamp"
    entered_type = manual.get("lpf_type_v_clamp" if vc else "lpf_type_i_clamp")
    primary_lpf, filter_warning = primary_filter(readings["PrimarySignalLPF"], entered_type)

    rows = [("Feedback Resistor", rf(found["feedback_resistor"]))]
    if has("Holding", mode):
        rows.append(("Holding", f"{on(readings['HoldingEnable'])}, {readings['Holding'] * (1e3 if vc else 1e12):g} {'mV' if vc else 'pA'}"))

    sensitivity = {}
    if telegraph:
        sensitivity = {"V-Clamp": f"{telegraph['dExtCmdSens'] * 1e3:g} mV/V", "I-Clamp": f"{telegraph['dExtCmdSens'] * 1e12:g} pA/V"}
    primary, secondary = signal(readings["PrimarySignalName"]), signal(readings["SecondarySignalName"])
    rows += [
        ("External Command Sensitivity", sensitivity.get(mode, "off (I = 0)") if telegraph else "? (no telegraph packet)"),
        None,
        ("Primary Output", primary),
        ("Primary Units", units(found["primary"], readings["PrimarySignalGain"])),
        ("Primary Output Lowpass Filter", primary_lpf),
        *([("!! Filter Type", filter_warning)] if filter_warning else []),
        None,
        ("Secondary Output", secondary),
        ("Secondary Units", units(found["secondary"], readings["SecondarySignalGain"])),
        ("Secondary Output Lowpass Filter", secondary_filter(readings["SecondarySignalLPF"])),
    ]
    return rows + [None, *compensation(readings, mode)]
