"""docs/coming-from-commander.md, generated from the settings table. `uv run python -m ommm.docs` writes it, and
tests/test_docs.py fails while the committed page differs from what the table gives."""

from pathlib import Path

from ommm.settings import (
    ALIASES,
    ALL_MODES,
    BYPASS_HZ,
    CHECKBOXES,
    IC,
    IC_FEEDBACK_RESISTORS,
    NOT_COVERED,
    PRIMARY_CUTOFFS,
    PRIMARY_SIGNALS,
    SECONDARY_SIGNALS,
    SETTINGS,
    SIGNAL_NAMES,
    SIGNAL_PREFIX,
    TABS,
    UNITS,
    VC,
    Setting,
    checkbox_name,
)
from ommm.summary import rf

PAGE = Path(__file__).resolve().parents[2] / "docs" / "coming-from-commander.md"
OTHER_NAMES = ", ".join(f'"{alias}" for {label}' for alias, label in ALIASES.items())

INTRO = f"""\
# Coming from Commander

Every control on MultiClamp Commander's window that ommm knows, under Commander's own label: its ommm call, unit and \
modes, the vendor's range or choices, whether Commander telegraphs it, the API name ommm reads it by, and what it \
does. Search the page for a label as Commander shows it. ommm drives **one MultiClamp 700B**, headstage \
1. Headstage 2's calls (`ommm.Amplifier(headstage=2)`) are in the API but not supported, nor are the MultiClamp 700A \
and Commander's Quick Select buttons.

The calls in the ommm call column are `ommm.Amplifier`'s, the same in Python and MATLAB, each checked first, read \
back and logged ([How a write works](writes.md)); `load_config` restarts Commander with a `.mcc` settings file \
([mcc.md](mcc.md)).

[Settings](#settings) · [Checkboxes](#checkboxes) · [Buttons](#buttons) · [Output signals](#output-signals) · \
[Primary Output lowpass cutoffs](#primary-output-lowpass-cutoffs) · [Every API function](#appendix-every-api-function)

## What ommm does

- **Python, every call in the ommm call column**, on `amp = ommm.Amplifier()`: `amp.get("Holding", "mV")`, \
`amp.set("Holding", -60, "mV")`, `amp.enable("Seal Test", True)`, `amp.press("Zap")`, `amp.set_mode("I-Clamp")` \
([How a write works](writes.md)), and `amp.load_config(path, changes=[...])`, which shows what will change; \
`confirmed=True` does it ([mcc.md](mcc.md)).
- **MATLAB, the same calls**, on `a = ommm.Amplifier()`: `a.get("Holding", "mV")`, `a.set("Holding", -60, "mV")`, \
`a.enable("Seal Test", true)`, `a.press("Zap")`, `a.set_mode("I-Clamp")`, \
`a.load_config(path, Changes={{"Feedback Resistor", 500, "MΩ", "V-Clamp"}})`, which shows what will change; \
`Confirmed=true` does it. Each write returns a struct, and a refusal is an error, `ommm:refused` \
([matlab.md](matlab.md)).
- **Every control:** a snapshot holds them all under `readings`, by the API names \
([The snapshot](install-and-testing.md#the-snapshot)).

Not here: the Options dialog's settings but the feedback resistor (External Command Sensitivity, the filter type, \
Sync Output, the Auto, Advanced and Audio pages), which only a `.mcc` file reaches: set them in Commander, save the \
file and load it with `load_config` ([mcc.md](mcc.md#an-options-page-setting)); and what has no route at all: the \
OVERLOAD light, which the API cannot see, the meters' labels, which no API function reads, and a command filter, \
which Commander 2.2.2.2 does not have.

## How to read the tables

- **Commander control**: the label on Commander's panel, with the knob's name where a panel has several (Rs \
Compensation Bandwidth). Calls also take the API name, in any case, and these other names: {OTHER_NAMES}.
- **Unit**: as Commander shows it. Every call names its unit (`set("Holding", -60, "mV")`), and one that does \
not suit the active mode is refused. Greek and ASCII spellings both work: MΩ or MOhm, µs or us, × or x.
- **Modes**: where Commander applies the control. In another mode Commander refuses a Set or Auto with error 6004 \
and changes nothing, and a read returns 6004 as its value, which a snapshot files under `not_applicable`. I = 0 is \
listed where Commander's window leaves the control enabled in I = 0.
- **Range or choices**: the vendor's, in the row's unit (Rf is the feedback resistor), or — where ommm has none. \
Commander itself takes any value without an error: the nearest choice, or the end of the range. ommm refuses a \
value off the list or out of range instead, naming the nearest choices.
- **Readback within**: how far from the value sent Commander may keep it, on its own steps: a readback that far off \
or less is an `adjusted` write, further a `mismatch` ([Outcomes](writes.md#outcomes)). It is the largest difference \
seen on a 700B, rounded up, or the vendor's step; —: none known, so a readback must equal the value sent, as \
Commander's float32 holds it.
- **Telegraph**: yes, with the field, when Commander's telegraph carries it, so a program that listens (Clampex, \
ommm's snapshot) sees a change made in Commander's window at once. Otherwise a program sees the change only when \
it reads the control. No checkbox clicked in the window is telegraphed (Whole Cell's untested).
- **Route**: API `Holding` is the API's `GetHolding` and `SetHolding`, or for a button its one function; checkbox \
`HoldingEnable` is the checkbox's getter and setter. `.mcc`: only restarting Commander with a `.mcc` settings file \
changes it, which `load_config` does ([mcc.md](mcc.md)); in brackets, its key in the file, after `AXMCD_FIELD_`.
- **Note**: what the control does, and what to know before using it.

This page is generated from ommm's settings table, `src/ommm/settings.py`, by `src/ommm/docs.py`: change either, \
then run `uv run python -m ommm.docs`. `tests/test_docs.py` fails while the committed page differs from what they \
generate.
"""


def number(value: float) -> str:
    return f"{value:.6g}"


def current(amps: float) -> str:
    return f"{number(amps / 1e-9)} nA" if amps >= 1e-9 else f"{number(amps / 1e-12)} pA"


def span(low: float, high: float, unit: str) -> str:
    factor = UNITS[unit][1]
    if low == -high:
        return f"±{number(high / factor)} {unit}"
    return f"{number(low / factor)} to {number(high / factor)} {unit}"


def cell(text: str) -> str:
    """Free text made safe for a table cell: a | would end the cell, an _ could start italics."""
    return text.replace("|", "\\|").replace("_", "\\_")


def call(row: Setting) -> str:
    """One verb per kind of control: set a value or signal, enable a checkbox, press a button."""
    if row.stem == "Reset":
        return "none: Commander's window only"
    if row.kind == "action":
        parameters = [other.label for other in SETTINGS if other.kind != "action" and other.label.startswith(row.label + " ")]
        return f'`press("{row.label}")`' + (f"; set first: {', '.join(parameters)}" if parameters else "")
    unit, checkbox = row.unit.get(row.modes[0]), checkbox_name(row, row.modes[0])
    if row.route == "mcc":
        return f'`load_config(path, changes=[("{row.label}", value, "{unit}", mode)])`, then confirmed'
    if row.stem == "Mode":
        return '`set_mode("I-Clamp")`'
    if row.kind == "bool":
        return f'`enable("{checkbox}", on)`'
    if row.kind == "enum":
        text = f'`set("{row.label}", "Membrane Current")`'
    else:
        text = f'`set("{row.label}", value, "{unit}")`'
    return text + (f'; checkbox: `enable("{checkbox}", on)`' if checkbox else "")


def unit_text(row: Setting) -> str:
    units = {mode: row.unit[mode] for mode in row.modes if mode in row.unit}
    if not units:
        return "—"
    if len(set(units.values())) == 1:
        text = next(iter(units.values()))
    else:
        text = ", ".join(f"{unit} in {mode}" for mode, unit in units.items())
    if row.sign:
        text += f"; the API's value is the panel's negated in {' and '.join(row.sign)}"
    return text


def readback_text(row: Setting) -> str:
    """The row's resolution in its own unit: how far off a readback may be and still be adjusted."""
    if not row.resolution:
        return "—"
    each = {mode: f"{number(step / UNITS[row.unit[mode]][1])} {row.unit[mode]}" for mode, step in row.resolution.items()}
    if len(set(each.values())) == 1:
        return next(iter(each.values()))
    return ", ".join(f"{text} in {mode}" for mode, text in each.items())


def range_text(row: Setting) -> str:
    if row.kind == "bool":
        return "on or off"
    if row.stem == "Mode":
        return ", ".join(ALL_MODES)
    if row.stem in ("PrimarySignal", "SecondarySignal"):
        return "the signals of the tab shown: [Output signals](#output-signals)"
    if row.stem == "PrimarySignalLPF":
        return f"the filter type's cutoffs, or Bypass ({number(BYPASS_HZ / 1e3)} kHz): [Primary Output lowpass cutoffs](#primary-output-lowpass-cutoffs)"
    if row.route == "mcc":  # the feedback resistor: one per tab, I-Clamp's without 50 GΩ
        listed = {tab: ", ".join(number(ohms / 1e6) for ohms in offered) + " MΩ"
                  for tab, offered in ((VC, row.choices), (IC, IC_FEEDBACK_RESISTORS))}
        return f"V-Clamp: one of {listed[VC]}; I-Clamp and I = 0: one of {listed[IC]}"
    if row.choices:
        unit = row.unit[row.modes[0]]
        return f"one of {', '.join(number(choice / UNITS[unit][1]) for choice in row.choices)} {unit}"
    spans = {mode: span(*limits, row.unit[mode]) for mode, limits in row.limits.items()}
    if row.rf_limits:
        each = ", ".join(f"{span(*limits, row.unit[VC])} at {rf(ohms)}" for ohms, limits in row.rf_limits.items())
        spans[VC] += f" ({each})"
    if row.rf_limit_v:
        each = ", ".join(f"±{current(row.rf_limit_v / ohms)} at {rf(ohms)}" for ohms in IC_FEEDBACK_RESISTORS)
        spans[IC] = f"±{number(row.rf_limit_v)} V / Rf ({each})"
    if not spans:
        return "—"
    if spans.keys() == set(row.modes) and len(set(spans.values())) == 1:
        return next(iter(spans.values()))
    return "; ".join(f"{mode}: {text}" for mode, text in spans.items())


def route(row: Setting) -> str:
    if row.route == "mcc":
        return f"`.mcc` (`{row.mcc_key}`)"
    return f"API `{row.stem}`" + (f", checkbox `{row.enable}`" if row.enable else "")


def modes_text(row: Setting) -> str:
    return "all" if row.modes == ALL_MODES else ", ".join(row.modes)


def table(header: list[str], lines: list[list[str]]) -> str:
    rows = [header, ["---"] * len(header), *lines]
    return "\n".join("| " + " | ".join(row) + " |" for row in rows)


def settings_section() -> str:
    lines = [
        [row.label, call(row), unit_text(row), modes_text(row), range_text(row), readback_text(row),
         f"yes, `{row.telegraph}`" if row.telegraph else "no", route(row), cell(row.note)]
        for row in SETTINGS
        if row.kind != "action"
    ]
    header = ["Commander control", "ommm call", "Unit", "Modes", "Range or choices", "Readback within", "Telegraph", "Route",
              "Note"]
    return (
        "## Settings\n\nIn the settings table's order, which follows Commander's window from the top down. Read one with "
        "`get(label, unit)`; a checkbox by the name enable takes (`get(\"Seal Test\")`).\n\n" + table(header, lines)
    )


def checkboxes_section() -> str:
    lines = []
    for label, stem, modes in CHECKBOXES:
        others = ", ".join(f'"{alias}"' for alias, name in ALIASES.items() if name == label)
        applies = ", ".join(row.label for row in SETTINGS if row.enable == stem and set(row.modes) & set(modes))
        lines.append([label, f'`enable("{label}", on)`', others or "—", "all" if modes == ALL_MODES else ", ".join(modes),
                      f"`{stem}`", applies or "—"])
    header = ["Commander checkbox", "ommm call", "Other names", "Modes", "API name", "Applies"]
    return (
        "## Checkboxes\n\nEach of the window's checkboxes, by the name `enable` takes and `get` reads "
        "(`get(\"Seal Test\")`); both take the API name and the other names too, in any case. Where a value shares its "
        "checkbox's name, `get` reads the value: `get(\"Holding\", \"mV\")`, and the checkbox by its API name, "
        "`get(\"HoldingEnable\")`.\n\n" + table(header, lines)
    )


def buttons_section() -> str:
    lines = [[row.label, call(row), modes_text(row), route(row), cell(row.note)] for row in SETTINGS if row.kind == "action"]
    header = ["Commander button", "ommm call", "Modes", "Route", "Note"]
    return (
        "## Buttons\n\nA button's values are settings: set them first (Zap Duration, then Zap).\n\n" + table(header, lines)
    )


def signals_section() -> str:
    primary = {name: signal for signal, name in PRIMARY_SIGNALS.items()}
    secondary = {name: signal for signal, name in SECONDARY_SIGNALS.items()}
    lines = []
    for tab in TABS:
        prefix = SIGNAL_PREFIX[tab]
        for name in dict.fromkeys(name for name in (*primary, *secondary) if name.startswith(prefix)):
            lines.append([tab, SIGNAL_NAMES[name.removeprefix(prefix)], f"`{name}`",
                          str(primary.get(name, "—")), str(secondary.get(name, "—"))])
    header = ["Tab", "Commander's name", "API name", "Primary Output id", "Secondary Output id"]
    return (
        "## Output signals\n\nEach tab's signals, as Commander's lists name them, with the name in `AxMultiClampMsg.h` "
        "(without `PRI_SIGNAL_` or `SEC_SIGNAL_`) and the id `get(\"PrimarySignal\")` and `get(\"SecondarySignal\")` "
        "return. Auxiliary 1 and 2 are whatever is on the rear-panel auxiliary inputs.\n\n"
        + table(header, lines)
    )


def cutoffs_section() -> str:
    def cutoffs(hz: set[int]) -> str:
        below, above = sorted(f for f in hz if f < 1000), sorted(f for f in hz if f >= 1000)
        return f"{', '.join(map(str, below))} Hz; {', '.join(number(f / 1e3) for f in above)} kHz"

    return (
        "## Primary Output lowpass cutoffs\n\n"
        f"The cutoffs of each filter type, and Bypass, {number(BYPASS_HZ / 1e3)} kHz, for both. The filter type is "
        "chosen in Options > General, and no API function reads it.\n\n"
        + "\n".join(f"- **{kind.capitalize()}**: {cutoffs(hz)}" for kind, hz in PRIMARY_CUTOFFS.items())
    )


def api_functions() -> list[tuple[tuple[str, ...], str]]:
    """Each of the header's functions, with the control it serves or why it serves none: (functions, text), a getter
    and setter of one API name together."""
    settings, checkboxes = {}, {}
    for row in SETTINGS:
        if row.kind != "action" and row.route == "api":
            settings.setdefault(row.stem, []).append(row.label)
            if row.enable:
                checkboxes.setdefault(row.enable, []).append(row.label)
    lines = [((f"Get{stem}", f"Set{stem}"), ", ".join(labels)) for stem, labels in settings.items()]
    lines += [((f"Get{stem}", f"Set{stem}"), f"the checkbox of {', '.join(labels)}") for stem, labels in checkboxes.items()]
    lines += [((row.stem,), row.label) for row in SETTINGS if row.kind == "action"]
    lines += [((name,), reason) for name, reason in NOT_COVERED]
    return sorted(lines)


def functions_section() -> str:
    entries = api_functions()
    functions = [name for names, _ in entries for name in names]
    gets = sum(name.startswith("Get") for name in functions)
    sets = sum(name.startswith("Set") for name in functions)
    lines = [[", ".join(f"`{name}`" for name in names), cell(text)] for names, text in entries]
    return (
        "## Appendix: every API function\n\n"
        f"`AxMultiClampMsg.h` (API 1.0.0.9) declares {len(functions)} functions: {gets} `Get`, {sets} `Set` and "
        f"{len(functions) - gets - sets} others. Each is here with the control it serves, or why it serves none; a "
        "getter and setter of one API name share a line.\n\n"
        + table(["Functions", "Control, or why none"], lines)
    )


def coming_from_commander() -> str:
    sections = (INTRO, settings_section(), checkboxes_section(), buttons_section(), signals_section(), cutoffs_section(), functions_section())
    return "\n\n".join(section.strip("\n") for section in sections) + "\n"


if __name__ == "__main__":
    PAGE.write_text(coming_from_commander(), encoding="utf-8", newline="\n")
    print(f"wrote {PAGE}")
