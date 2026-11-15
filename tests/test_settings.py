"""The settings table: names, modes, units and choices; and, when OMMM_SDK_DIR names a Commander install folder (or
a copy of one), the table against Commander's own header, which ommm never copies."""

import ast
import json
import math
import os
import re
from pathlib import Path

import pytest

import ommm.settings
from ommm.commander import parse_header
from ommm.sdk import sdk_file
from ommm.settings import (
    ALIASES,
    ALL_MODES,
    CHECKBOXES,
    MODES,
    NOT_COVERED,
    PRIMARY_SIGNALS,
    SECONDARY_SIGNALS,
    SETTINGS,
    SIGNAL_PREFIX,
    TABS,
    UNITS,
    checkbox,
    checkbox_name,
    checkbox_names,
    find,
    known_unit,
    mode_name,
    tab_for,
    to_api,
)

RIG = Path(__file__).parent / "data" / "rig" / "2026-10-23"
RECORDS = sorted(RIG.glob("*.json"))
API_TYPES = {"float": "double", "bool": "BOOL", "enum": "UINT"}
needs_header = pytest.mark.skipif(not os.environ.get("OMMM_SDK_DIR"), reason="OMMM_SDK_DIR is not set")


@pytest.fixture(scope="module")
def header():
    return parse_header(sdk_file("AxMultiClampMsg/AxMultiClampMsg.h").read_text())


def api_rows():
    return [row for row in SETTINGS if row.kind != "action" and row.route == "api"]


@needs_header
def test_every_api_row_has_its_getter_and_setter_typed_as_its_kind(header):
    functions, _, _ = header
    for row in api_rows():
        for stem, kind in [(row.stem, row.kind)] + ([(row.enable, "bool")] if row.enable else []):
            getter, setter = functions["Get" + stem][1], functions["Set" + stem][1]
            assert getter[1].split()[0] == setter[1].split()[0] == API_TYPES[kind], stem


@needs_header
def test_every_set_function_is_a_row_or_its_checkbox(header):
    functions, _, _ = header
    sets = {name.removeprefix("Set") for name in functions if name.startswith("Set")} - {"TimeOut"}
    assert len(sets) == 46
    assert {row.stem for row in api_rows()} | {row.enable for row in api_rows() if row.enable} == sets


@needs_header
def test_every_action_is_a_function_that_takes_only_the_handle(header):
    functions, _, _ = header
    for row in SETTINGS:
        if row.kind == "action":
            assert [param.split()[0] for param in functions[row.stem][1]] == ["HMCCMSG", "int"], row.label


@needs_header
def test_each_of_the_121_functions_is_in_a_row_or_not_covered_with_a_reason(header):
    functions, _, _ = header
    covered = {row.stem for row in SETTINGS if row.kind == "action"}
    for row in api_rows():
        for stem in filter(None, (row.stem, row.enable)):
            covered |= {"Get" + stem, "Set" + stem}
    not_covered = dict(NOT_COVERED)
    assert len(not_covered) == len(NOT_COVERED)
    assert covered.isdisjoint(not_covered)
    assert covered | not_covered.keys() == functions.keys()
    assert len(functions) == 121


@needs_header
def test_enum_choices_modes_and_signal_ids_are_the_headers(header):
    _, constants, _ = header
    for row in SETTINGS:
        if row.kind == "enum" and row.route == "api":
            assert all(choice in constants for choice in row.choices), row.label
    assert [constants[choice] for choice in find("Mode").choices] == list(MODES)
    assert {constants["PRI_SIGNAL_" + name]: name for name in PRIMARY_SIGNALS.values()} == PRIMARY_SIGNALS
    assert {constants["SEC_SIGNAL_" + name]: name for name in SECONDARY_SIGNALS.values()} == SECONDARY_SIGNALS
    on_700b = {name for name in constants if name.startswith(("PRI_SIGNAL_", "SEC_SIGNAL_"))} - {"SEC_SIGNAL_IC_CMDCURRENT"}
    assert {*find("Primary Output").choices, *find("Secondary Output").choices} == on_700b


def test_labels_are_unique_in_any_case():
    labels = [row.label.lower() for row in SETTINGS]
    assert len(labels) == len(set(labels))


def test_a_stem_and_a_mode_name_one_row():
    pairs = [(row.stem, mode) for row in SETTINGS for mode in row.modes]
    assert len(pairs) == len(set(pairs))


def test_every_row_is_found_by_its_label_in_any_case_and_by_its_stem_in_each_mode():
    for row in SETTINGS:
        assert find(row.label) is find(row.label.upper()) is row
        for mode in row.modes:
            assert find(row.stem, mode) is row


@pytest.mark.parametrize("label, stem, mode, unit, factor", [
    ("Holding", "Holding", "V-Clamp", "mV", 1e-3),
    ("Holding", "Holding", "I-Clamp", "pA", 1e-12),
    ("Seal Test Amplitude", "TestSignalAmplitude", "V-Clamp", "mV", 1e-3),
    ("Tuning Amplitude", "TestSignalAmplitude", "I-Clamp", "pA", 1e-12),
    ("Pipette Offset", "PipetteOffset", "V-Clamp", "mV", 1e-3),
    ("Pipette Offset", "PipetteOffset", "I-Clamp", "mV", -1e-3),  # the API's sign is the panel's opposite (P14)
    ("Pipette Offset", "PipetteOffset", "I = 0", "mV", -1e-3),
    ("Cp Slow Tau", "SlowCompTau", "V-Clamp", "µs", 1e-6),
    ("Whole Cell Rs", "WholeCellCompResist", "V-Clamp", "MΩ", 1e6),
    ("Rs Compensation Bandwidth", "RsCompBandwidth", "V-Clamp", "kHz", 1e3),  # Hz in the API, kHz in Commander
    ("Rs Compensation Correction", "RsCompCorrection", "V-Clamp", "%", 1),  # the API takes percent
    ("Primary Output Gain", "PrimarySignalGain", "I = 0", "x", 1),
    ("Zap Duration", "ZapDuration", "V-Clamp", "ms", 1e-3),
])
def test_label_stem_mode_unit_and_factor_round_trip(label, stem, mode, unit, factor):
    row = find(label)
    assert (row.stem, row.unit[mode]) == (stem, unit)
    assert find(stem, mode) is row
    assert to_api(row, mode, 1, unit) == pytest.approx(factor)


def test_to_api_takes_any_unit_of_the_rows_kind_and_refuses_others():
    assert to_api(find("Holding"), "V-Clamp", -0.06, "V") == to_api(find("Holding"), "V-Clamp", -60, "mV") == -0.06
    assert to_api(find("Whole Cell Rs"), "V-Clamp", 10, "MOhm") == to_api(find("Whole Cell Rs"), "V-Clamp", 0.01, "GΩ")
    with pytest.raises(ValueError, match="Holding in V-Clamp is a voltage: mV, not pA"):
        to_api(find("Holding"), "V-Clamp", -60, "pA")
    with pytest.raises(ValueError, match="Holding in I-Clamp is a current: pA or nA, not mv"):
        to_api(find("Holding"), "I-Clamp", 50, "mv")
    with pytest.raises(ValueError, match="^Whole Cell Rs in V-Clamp is a resistance: MOhm or GOhm, not pF$"):  # ASCII given
        to_api(find("Whole Cell Rs"), "V-Clamp", 10, "pF")
    with pytest.raises(ValueError, match="^Whole Cell Rs in V-Clamp is a resistance: MΩ or GΩ, not pΩ$"):
        to_api(find("Whole Cell Rs"), "V-Clamp", 10, "pΩ")
    with pytest.raises(ValueError, match="^Whole Cell Rs in V-Clamp is a resistance: give a unit: MΩ or GΩ$"):
        to_api(find("Whole Cell Rs"), "V-Clamp", 10, None)
    with pytest.raises(ValueError, match="^Cp Fast Tau in V-Clamp is a time: us or ms, not usec$"):
        to_api(find("Cp Fast Tau"), "V-Clamp", 1, "usec")
    with pytest.raises(ValueError, match="Seal Test Frequency in V-Clamp is a frequency: Hz or kHz, not ms"):
        to_api(find("Seal Test Frequency"), "V-Clamp", 10, "ms")
    with pytest.raises(ValueError, match="Cp Slow Tau x20 takes no unit in V-Clamp"):
        to_api(find("Cp Slow Tau x20"), "V-Clamp", 1, "x")


def test_a_stem_two_rows_share_needs_the_mode():
    with pytest.raises(ValueError, match="'Seal Test Amplitude' or 'Tuning Amplitude': give the mode"):
        find("TestSignalAmplitude")
    assert find("testsignalamplitude", "I-Clamp").label == "Tuning Amplitude"


def test_aliases_unknown_names_and_rows_outside_the_mode():
    assert find("Oscillation Killer") is find("Disable/Reduce if Oscillation Detected")
    assert find("ext") is find("EXT") is find("Mode Switching")
    assert all(find(alias) is find(label) for alias, label in ALIASES.items())
    with pytest.raises(ValueError, match=r"^'holdin' is not a Commander control ommm knows: did you mean 'Holding'\? Every label: docs/coming-from-commander.md$"):
        find("holdin")
    with pytest.raises(ValueError, match=r"^'Oscillation Kille' is not .*: did you mean 'Oscillation Killer'\?"):  # aliases too
        find("Oscillation Kille")
    with pytest.raises(ValueError, match=r"^'zzz' is not a Commander control ommm knows. Every label: docs/coming-from-commander.md$"):
        find("zzz")
    # the mode only picks between rows that share a stem; the caller checks row.modes
    assert find("FastCompCap", "I-Clamp").label == "Cp Fast Capacitance"
    with pytest.raises(ValueError, match="'Seal Test Amplitude' or 'Tuning Amplitude': neither is in I = 0"):
        find("TestSignalAmplitude", "I = 0")


def test_a_checkbox_is_named_as_commanders_window_names_it():
    names = {(row.label, mode): name for row in SETTINGS for mode in row.modes if (name := checkbox_name(row, mode))}
    panels = {name for (label, _), name in names.items() if find(label).kind != "bool"}
    assert panels == {
        "Seal Test", "Tuning", "Whole Cell", "Rs Compensation", "Slow Current Injection", "Holding", "Output Zero",
        "Leak Subtraction", "Bridge Balance", "Pipette Capacitance Neutralization",
    }
    assert names["Seal Test Frequency", "V-Clamp"] == names["Seal Test Amplitude", "V-Clamp"] == "Seal Test"
    assert names["Tuning Amplitude", "I-Clamp"] == "Tuning"
    assert names["Holding", "I-Clamp"] == "Holding"
    assert names["Cp Slow Tau x20", "V-Clamp"] == "Cp Slow Tau x20"
    assert checkbox_name(find("Irms Meter"), "I-Clamp") is None  # not in the mode
    assert checkbox_name(find("Cp Fast Capacitance"), "V-Clamp") is None  # no checkbox
    assert all(row.enable or row.kind == "bool" for row in SETTINGS if checkbox_name(row, row.modes[0]))


def test_the_checkbox_table_matches_the_rows_in_every_mode():
    for mode in ALL_MODES:
        rows = {row.enable for row in SETTINGS if row.enable and mode in row.modes}
        rows |= {row.stem for row in SETTINGS if row.kind == "bool" and mode in row.modes}
        table = [stem for _, stem, modes in CHECKBOXES if mode in modes]
        assert sorted(table) == sorted(rows), mode  # each checkbox once in a mode
        assert len(set(checkbox_names(mode))) == len(table)
    assert len(CHECKBOXES) == 15


# every (mode, name) checkbox() took before the table, from the labels' common first words, with what it gave
ACCEPTED = {
    "V-Clamp": [
        ("Cp Slow Tau x20", "Cp Slow Tau x20", "SlowCompTauX20Enable"),
        ("Disable/Reduce if Oscillation Detected", "Disable/Reduce if Oscillation Detected", "OscKillerEnable"),
        ("Ext", "Mode Switching", "ModeSwitchEnable"),
        ("Holding", "Holding", "HoldingEnable"),
        ("HoldingEnable", "Holding", "HoldingEnable"),
        ("Irms Meter", "Irms Meter", "MeterIrmsEnable"),
        ("Leak Subtraction", "Leak Subtraction", "LeakSubEnable"),
        ("LeakSubEnable", "Leak Subtraction", "LeakSubEnable"),
        ("MeterIrmsEnable", "Irms Meter", "MeterIrmsEnable"),
        ("MeterResistEnable", "Resistance Meter", "MeterResistEnable"),
        ("Mode Switching", "Mode Switching", "ModeSwitchEnable"),
        ("ModeSwitchEnable", "Mode Switching", "ModeSwitchEnable"),
        ("OscKillerEnable", "Disable/Reduce if Oscillation Detected", "OscKillerEnable"),
        ("Oscillation Killer", "Disable/Reduce if Oscillation Detected", "OscKillerEnable"),
        ("Output Zero", "Output Zero", "OutputZeroEnable"),
        ("OutputZeroEnable", "Output Zero", "OutputZeroEnable"),
        ("Resistance Meter", "Resistance Meter", "MeterResistEnable"),
        ("Rs Compensation", "Rs Compensation", "RsCompEnable"),
        ("RsCompEnable", "Rs Compensation", "RsCompEnable"),
        ("Seal Test", "Seal Test", "TestSignalEnable"),
        ("SlowCompTauX20Enable", "Cp Slow Tau x20", "SlowCompTauX20Enable"),
        ("TestSignalEnable", "Seal Test", "TestSignalEnable"),
        ("Whole Cell", "Whole Cell", "WholeCellCompEnable"),
        ("WholeCellCompEnable", "Whole Cell", "WholeCellCompEnable"),
    ],
    "I-Clamp": [
        ("Bridge Balance", "Bridge Balance", "BridgeBalEnable"),
        ("BridgeBalEnable", "Bridge Balance", "BridgeBalEnable"),
        ("Disable/Reduce if Oscillation Detected", "Disable/Reduce if Oscillation Detected", "OscKillerEnable"),
        ("Ext", "Mode Switching", "ModeSwitchEnable"),
        ("Holding", "Holding", "HoldingEnable"),
        ("HoldingEnable", "Holding", "HoldingEnable"),
        ("MeterResistEnable", "Resistance Meter", "MeterResistEnable"),
        ("Mode Switching", "Mode Switching", "ModeSwitchEnable"),
        ("ModeSwitchEnable", "Mode Switching", "ModeSwitchEnable"),
        ("NeutralizationEnable", "Pipette Capacitance Neutralization", "NeutralizationEnable"),
        ("OscKillerEnable", "Disable/Reduce if Oscillation Detected", "OscKillerEnable"),
        ("Oscillation Killer", "Disable/Reduce if Oscillation Detected", "OscKillerEnable"),
        ("Output Zero", "Output Zero", "OutputZeroEnable"),
        ("OutputZeroEnable", "Output Zero", "OutputZeroEnable"),
        ("Pipette Capacitance Neutralization", "Pipette Capacitance Neutralization", "NeutralizationEnable"),
        ("Resistance Meter", "Resistance Meter", "MeterResistEnable"),
        ("Slow Current Injection", "Slow Current Injection", "SlowCurrentInjEnable"),
        ("SlowCurrentInjEnable", "Slow Current Injection", "SlowCurrentInjEnable"),
        ("TestSignalEnable", "Tuning", "TestSignalEnable"),
        ("Tuning", "Tuning", "TestSignalEnable"),
    ],
    "I = 0": [
        ("Ext", "Mode Switching", "ModeSwitchEnable"),
        ("Mode Switching", "Mode Switching", "ModeSwitchEnable"),
        ("ModeSwitchEnable", "Mode Switching", "ModeSwitchEnable"),
        ("Output Zero", "Output Zero", "OutputZeroEnable"),
        ("OutputZeroEnable", "Output Zero", "OutputZeroEnable"),
    ],
}


@pytest.mark.parametrize("mode", ALL_MODES)
def test_every_checkbox_name_taken_before_the_table_is_taken_the_same(mode):
    for name, label, stem in ACCEPTED[mode]:
        assert checkbox(name, mode) == checkbox(name.upper(), mode) == (label, stem)
    names = {name for each in ACCEPTED.values() for name, _, _ in each}
    for name in names - {name for name, _, _ in ACCEPTED[mode]}:
        with pytest.raises(ValueError, match=f"^Commander's window has no {re.escape(name)} checkbox in {mode}$"):
            checkbox(name, mode)


def test_the_windows_own_words_beside_a_checkbox_are_taken_too():
    assert checkbox("Resistance", "I-Clamp") == ("Resistance Meter", "MeterResistEnable")
    assert checkbox("irms", "V-Clamp") == ("Irms Meter", "MeterIrmsEnable")
    assert checkbox("Tau x20", "V-Clamp") == ("Cp Slow Tau x20", "SlowCompTauX20Enable")
    assert find("Resistance") is find("Resistance Meter")


def test_a_misspelt_checkbox_is_offered_by_find():
    with pytest.raises(ValueError, match=r"^'Seal Tst' is not a Commander control ommm knows: did you mean 'Seal Test'\?"):
        find("Seal Tst")


def test_greek_and_ascii_units_are_the_same():
    assert known_unit("MΩ") == known_unit("MOhm") == ("resistance", 1e6)
    assert known_unit("M\u2126") == ("resistance", 1e6)  # the ohm sign, as Windows' Character Map gives it
    assert known_unit("\u00b5s") == known_unit("\u03bcs") == known_unit("us") == ("time", 1e-6)  # micro sign and Greek mu
    assert known_unit("×") == known_unit("x")
    assert (known_unit("Mohm"), known_unit(None), known_unit(5)) == (None, None, None)
    assert "\u03bcs" not in UNITS and "M\u2126" not in UNITS  # one key per spelling


def test_a_misspelt_ascii_unit_is_told_the_ascii_spelling():
    with pytest.raises(ValueError, match="^Whole Cell Rs in V-Clamp is a resistance: MOhm or GOhm, not Mohm$"):
        to_api(find("Whole Cell Rs"), "V-Clamp", 10, "Mohm")
    assert to_api(find("Whole Cell Rs"), "V-Clamp", 10, "M\u2126") == 1e7


def test_per_mode_fields_name_only_the_rows_modes_and_known_units():
    for row in SETTINGS:
        assert row.modes and set(row.modes) <= set(MODES.values()), row.label
        for per_mode in (row.unit, row.limits, row.resolution, row.sign):
            assert set(per_mode) <= set(row.modes), row.label
        assert all(unit in UNITS for unit in row.unit.values()), row.label
        assert all(low < high for low, high in row.limits.values()), row.label
        assert all(step > 0 for step in row.resolution.values()), row.label
        if row.kind == "float":
            assert set(row.unit) == set(row.modes), row.label
        if row.rf_limit_v:
            assert "I-Clamp" in row.modes and "I-Clamp" not in row.limits, row.label


def test_kinds_routes_and_actions():
    for row in SETTINGS:
        assert row.kind in ("float", "bool", "enum", "action"), row.label
        assert row.route in ("api", "mcc"), row.label
        assert row.mcc_key or row.route != "mcc", row.label
        if row.kind == "action":
            assert not (row.unit or row.limits or row.choices or row.enable or row.telegraph), row.label
    assert sum(row.kind == "action" for row in SETTINGS) == 13


def test_numeric_choices_are_inside_the_limits_and_in_order():
    for row in SETTINGS:
        numbers = [choice for choice in row.choices if not isinstance(choice, str)]
        assert numbers == sorted(numbers), row.label
        for low, high in row.limits.values():
            assert all(low <= choice <= high for choice in numbers), row.label


def test_notes_and_reasons_are_one_line_of_plain_text():
    for text in [row.note for row in SETTINGS] + [reason for _, reason in NOT_COVERED]:
        assert text and "\n" not in text and not set(text) & set("`*[]#|"), text


def test_every_row_closes_with_a_comment_on_where_its_facts_come_from():
    source = Path(ommm.settings.__file__).read_text(encoding="utf-8")
    lines = source.splitlines()
    rows = [node for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Setting"]
    assert len(rows) == len(SETTINGS)
    for row in rows:
        assert lines[row.end_lineno - 2].lstrip().startswith("# "), lines[row.lineno]


def test_a_getter_commander_refuses_on_a_tab_is_a_row_for_the_other_tab():
    # every probe started in V-Clamp and read both tabs; a getter that does not apply to a tab answers 6004
    start = json.loads((RIG / "p04_wrong_mode_set.json").read_text(encoding="utf-8"))["start"]
    for tab, snapshot in start.items():
        assert snapshot["not_applicable"], tab
        for stem in snapshot["not_applicable"]:
            rows = [row for row in SETTINGS if stem in (row.stem, row.enable)]
            assert rows, stem
            assert all(tab_for(mode) != tab for row in rows for mode in row.modes), stem


@pytest.mark.parametrize("path", RECORDS, ids=lambda path: path.name)
def test_a_set_or_auto_commander_refused_for_the_mode_is_not_in_that_rows_modes(path):
    # P04 (Rs Compensation in I-Clamp, Bridge Balance in V-Clamp), P06 (Auto Bridge Balance in V-Clamp), P17 (Irms in I-Clamp)
    for step in json.loads(path.read_text(encoding="utf-8"))["steps"]:
        line = step.get("write") or {}
        if line.get("error_code") == 6004:
            rows = [row for row in SETTINGS if line["stem"] in (row.stem, row.enable)]
            assert rows and all(MODES[line["mode"]] not in row.modes for row in rows), line["stem"]


def test_tabs_and_modes():
    assert TABS == ("V-Clamp", "I-Clamp")  # left to right, as Commander numbers them
    assert [tab_for(mode) for mode in MODES.values()] == ["V-Clamp", "I-Clamp", "I-Clamp"]  # I = 0 lives on I-Clamp's tab
    assert [mode_name(name) for name in ("v-clamp", "I-CLAMP", "i = 0")] == list(MODES.values())
    for name in ("V-Clamp 1", "voltage clamp"):  # V-Clamp 1 is the tab's label, not a mode
        with pytest.raises(ValueError, match="use 'V-Clamp', 'I-Clamp' or 'I = 0'"):
            tab_for(name)
    assert tuple(SIGNAL_PREFIX) == TABS
    for name in (*PRIMARY_SIGNALS.values(), *SECONDARY_SIGNALS.values()):
        assert sum(name.startswith(prefix) for prefix in SIGNAL_PREFIX.values()) == 1, name


def test_resolution_covers_what_the_probes_read_back():
    # every float Set in the probe records that read back other than sent, Commander's clips aside: Holding past
    # ±1 V less the Pipette Offset level (P03, parity), Pipette Offsets held by the last Auto (P06), off-list values
    # snapped (P03), and Rs Correction following Prediction (P03, P05)
    for path in RECORDS:
        for step in json.loads(path.read_text(encoding="utf-8"))["steps"]:
            line = step.get("write") or {}
            target, after = line.get("target"), line.get("after")
            numbers = all(isinstance(value, int | float) and not isinstance(value, bool) for value in (target, after))
            if not numbers or target == after or line["stem"] == "RsCompCorrection":
                continue
            if line["stem"] == "PipetteOffset" and abs(after - target) > 1e-4:  # held within ±100 mV of the last
                continue  # Auto's level: the nearest such hold seen was 0.44 mV off (P06), its resolution 30 µV at most
            mode = MODES[line["mode"]]
            row = find(line["stem"], mode)
            low, high = row.limits.get(mode, (-math.inf, math.inf))
            if row.choices or not low <= target <= high:
                continue
            if line["stem"] == "Holding" and abs(target) > 0.9:  # near ±1 V the range narrows by the Pipette Offset level
                continue
            assert abs(after - target) <= row.resolution[mode], (path.name, line["stem"], target, after)


def test_a_mode_by_its_name_or_commanders_button_in_any_case():
    assert [mode_name(name) for name in ("i-clamp", "VC", "ic", "I=0", "I = 0")] == [
        "I-Clamp", "V-Clamp", "I-Clamp", "I = 0", "I = 0"]
    with pytest.raises(ValueError, match="'current clamp' is not a mode: .* or the buttons' 'VC', 'IC' or 'I=0'"):
        mode_name("current clamp")
