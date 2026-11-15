"""What one snapshot says about the amplifier's outputs, in SI, and what puts that in doubt.

state() takes each value from the interface that is reliable for it:

- signal identity and the feedback resistor from the API, which never goes stale; a 'tab:'
  disagreement is blocking, so the identity always belongs to the active mode;
- mode, gains, low-pass cutoffs, membrane capacitance and command sensitivity from the telegraph
  packet, the one that carries the sensitivity; without a telegraph (Demo mode) the mode is the
  API's, and the snapshot blocks;
- output scale factors from a fixed table (signal x feedback resistor, or the external command
  sensitivity), with the telegraph's scale as a cross-check only, because the telegraph's signal
  fields go stale after a mode switch.
"""

from ommm.checks import disagreements
from ommm.settings import (
    AUXILIARY_SIGNALS,
    FEEDBACK_RESISTORS,
    MODES,
    SIGNAL_NAMES,
    checkbox_label,
    checkbox_modes,
    feedback_resistor,
)

# scale at gain 1 by API signal name without its VC_/IC_ prefix: a current's is the feedback resistor in V/A, a
# potential's is fixed (both match the telegraph's); an external command's is 1 / the external command sensitivity, so
# the output gives back the command input's volts: 25 V/nA at 40 pA/V, 50 V/V at 20 mV/V
CURRENTS = {"MEMBCURRENT", "CMDCURRENT"}
POTENTIALS = {"MEMBPOTENTIAL": 10, "PIPPOTENTIAL": 1, "100XACMEMBPOTENTIAL": 100}
EXT_COMMANDS = {"EXTCMDCURRENT": "V/A", "EXTCMDPOTENTIAL": "V/V"}

# the telegraph's uScaleFactorUnits index (MCTG_UNITS_*) -> factor to V/V or V/A
TELEGRAPH_TO_SI = {0: 1, 1: 1e3, 2: 1e6, 3: 1, 4: 1e3, 5: 1e6, 6: 1e9, 7: 1e12}

EXT_CMD_UNITS = {"V-Clamp": "V/V", "I-Clamp": "A/V"}
# the checkboxes a warning names when on, by the window's name for each, with what it does to the outputs
WARNED_ENABLES = {
    "LeakSubEnable": "",
    "OutputZeroEnable": "",
    "HoldingEnable": "",
    "ModeSwitchEnable": "",
    "TestSignalEnable": "",
    "SlowCurrentInjEnable": "",
    # per the 700B manual: the meter's pulses add to the command; the secondary Membrane Potential carries the
    # Rs-compensation commands, the primary's does not
    "MeterResistEnable": ", and its pulses add to the command",
    "RsCompEnable": ", and the Secondary Output's Membrane Potential includes its commands",
}

OUTPUTS = [  # output, API name key, telegraph gain, scale, units and low-pass keys
    ("primary", "PrimarySignalName", "dAlpha", "dScaleFactor", "uScaleFactorUnits", "dLPFCutoff"),
    ("secondary", "SecondarySignalName", "dSecondaryAlpha", "dRawScaleFactor", "uRawScaleFactorUnits", "dSecondaryLPFCutoff"),
]


def table_scale(signal: str, resistor: float | None, sensitivity: float | None = None) -> tuple[float, str] | tuple[None, None]:
    """Scale at gain 1 in SI and its units for a signal; (None, None) when the table has no entry, or the feedback
    resistor or external command sensitivity it needs is unknown or 0."""
    if signal in EXT_COMMANDS and sensitivity:
        return 1 / sensitivity, EXT_COMMANDS[signal]
    if signal in CURRENTS and resistor:
        return resistor, "V/A"
    if signal in POTENTIALS:
        return POTENTIALS[signal], "V/V"
    return None, None


def state(snapshot: dict) -> dict:
    """The mode, feedback resistor (ohms), each output's signal, gain, scale (V/A or V/V at gain 1)
    and low-pass (Hz), the external command sensitivity and the membrane capacitance (F), None
    where unknown, plus the `blocking`, `problems` and `warnings` found.

    An output's `trusted` is False when its scale is unknown or in doubt (a gain disagreement, or a
    telegraph scale that contradicts the table); the reason is in `problems`. `trusted` covers only
    this output's own scale; check `blocking` first: anything in it (e.g. the other mode's tab in
    front) overrides trusted. An output's `signal` is Commander's name for it ("Membrane Current"),
    `api_name` the API's ("VC_MEMBCURRENT").
    """
    readings, telegraph = snapshot["readings"], snapshot["telegraph"]
    if not isinstance(telegraph, dict):  # also the [] that MATLAB's jsonencode writes for a null
        telegraph = None
    blocking, problems, warnings = [], [], []

    mode = MODES.get(telegraph["uOperatingMode"] if telegraph else readings.get("Mode"))
    resistor_key = feedback_resistor(mode or "V-Clamp", int(snapshot["headstage"]["channel"]))
    needed = ["ModeName", "PrimarySignalName", "SecondarySignalName", "PrimarySignalGain", "SecondarySignalGain"]
    # a *Name reading is None when its ID matched no header constant (commander.py)
    missing = (["telegraph"] if telegraph is None else []) + [key for key in needed + [resistor_key] if readings.get(key) is None]
    if missing:
        blocking.append("incomplete snapshot: no " + ", ".join(missing))
    resistor_index = readings.get(resistor_key)
    if resistor_index is not None and resistor_index not in FEEDBACK_RESISTORS:
        blocking.append(f"feedback resistor: {resistor_key} = {resistor_index} is not a range index (0..3)")
    resistor = FEEDBACK_RESISTORS.get(resistor_index) if mode else None  # the index is read by mode

    disagreed = {entry.partition(":")[0]: entry for entry in disagreements(readings, telegraph)}
    for what, entry in disagreed.items():
        if what in ("tab", "mode"):
            blocking.append(entry)
        elif what.endswith("gain"):
            problems.append(entry)
        else:  # a stale '<output> signal' telegraph, or a low-pass cutoff
            warnings.append(entry)

    sensitivity = telegraph["dExtCmdSens"] if telegraph else None
    result = {"mode": mode, "feedback_resistor": resistor}
    for output, name_key, gain_key, scale_key, units_key, lpf_key in OUTPUTS:
        api_name = readings.get(name_key)
        signal = (api_name or "").partition("_")[2]
        scale, units = table_scale(signal, resistor, sensitivity)
        if signal in EXT_COMMANDS and scale is None and telegraph:
            problems.append(f"{output} signal: {api_name} scales by the external command sensitivity, which is 0 (off)")
        elif api_name and signal not in AUXILIARY_SIGNALS | EXT_COMMANDS.keys() and scale is None and resistor:
            problems.append(f"{output} signal: {api_name} is not in the scale table")
        trusted = scale is not None and f"{output} gain" not in disagreed
        if telegraph and scale is not None and f"{output} signal" not in disagreed:  # the telegraph's scale is this output's
            telegraph_scale = telegraph[scale_key] * TELEGRAPH_TO_SI.get(telegraph[units_key], 0)
            if abs(telegraph_scale - scale) > 1e-6 * scale:
                problems.append(
                    f"{output} scale: table {scale:g} {units}, telegraph {telegraph_scale:g} {units} (units index {telegraph[units_key]})"
                )
                trusted = False
        result[output] = {
            "signal": SIGNAL_NAMES.get(signal, api_name) if api_name else None,
            "api_name": api_name,
            "gain": telegraph[gain_key] if telegraph else None,
            "scale": scale,
            "units": units,
            "lpf": telegraph[lpf_key] if telegraph else None,
            "trusted": trusted,
        }

    if mode in EXT_CMD_UNITS and sensitivity == 0:
        problems.append(f"external command sensitivity: 0 (off) in {mode}, so an external command does nothing")
    for key, does in WARNED_ENABLES.items():
        # only where the mode has the checkbox, as get() reads it: I = 0 shares I-Clamp's tab, but not its Holding
        if readings.get(key) and (mode is None or mode in checkbox_modes(key)):
            warnings.append(f"{checkbox_label(key, mode)} is on{does} ({key})")

    return result | {
        "ext_cmd_sensitivity": sensitivity,
        "ext_cmd_units": EXT_CMD_UNITS.get(mode),
        "membrane_capacitance": telegraph["dMembraneCap"] if telegraph else None,
        "blocking": blocking,
        "problems": problems,
        "warnings": warnings,
    }
