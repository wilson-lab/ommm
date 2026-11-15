# Coming from Commander

Every control on MultiClamp Commander's window that ommm knows, under Commander's own label: its ommm call, unit and modes, the vendor's range or choices, whether Commander telegraphs it, the API name ommm reads it by, and what it does. Search the page for a label as Commander shows it. ommm drives **one MultiClamp 700B**, headstage 1. Headstage 2's calls (`ommm.Amplifier(headstage=2)`) are in the API but not supported, nor are the MultiClamp 700A and Commander's Quick Select buttons.

The calls in the ommm call column are `ommm.Amplifier`'s, the same in Python and MATLAB, each checked first, read back and logged ([How a write works](writes.md)); `load_config` restarts Commander with a `.mcc` settings file ([mcc.md](mcc.md)).

[Settings](#settings) · [Checkboxes](#checkboxes) · [Buttons](#buttons) · [Output signals](#output-signals) · [Primary Output lowpass cutoffs](#primary-output-lowpass-cutoffs) · [Every API function](#appendix-every-api-function)

## What ommm does

- **Python, every call in the ommm call column**, on `amp = ommm.Amplifier()`: `amp.get("Holding", "mV")`, `amp.set("Holding", -60, "mV")`, `amp.enable("Seal Test", True)`, `amp.press("Zap")`, `amp.set_mode("I-Clamp")` ([How a write works](writes.md)), and `amp.load_config(path, changes=[...])`, which shows what will change; `confirmed=True` does it ([mcc.md](mcc.md)).
- **MATLAB, the same calls**, on `a = ommm.Amplifier()`: `a.get("Holding", "mV")`, `a.set("Holding", -60, "mV")`, `a.enable("Seal Test", true)`, `a.press("Zap")`, `a.set_mode("I-Clamp")`, `a.load_config(path, Changes={"Feedback Resistor", 500, "MΩ", "V-Clamp"})`, which shows what will change; `Confirmed=true` does it. Each write returns a struct, and a refusal is an error, `ommm:refused` ([matlab.md](matlab.md)).
- **Every control:** a snapshot holds them all under `readings`, by the API names ([The snapshot](install-and-testing.md#the-snapshot)).

Not here: the Options dialog's settings but the feedback resistor (External Command Sensitivity, the filter type, Sync Output, the Auto, Advanced and Audio pages), which only a `.mcc` file reaches: set them in Commander, save the file and load it with `load_config` ([mcc.md](mcc.md#an-options-page-setting)); and what has no route at all: the OVERLOAD light, which the API cannot see, the meters' labels, which no API function reads, and a command filter, which Commander 2.2.2.2 does not have.

## How to read the tables

- **Commander control**: the label on Commander's panel, with the knob's name where a panel has several (Rs Compensation Bandwidth). Calls also take the API name, in any case, and these other names: "Oscillation Killer" for Disable/Reduce if Oscillation Detected, "Ext" for Mode Switching, "Resistance" for Resistance Meter, "Irms" for Irms Meter, "Tau x20" for Cp Slow Tau x20.
- **Unit**: as Commander shows it. Every call names its unit (`set("Holding", -60, "mV")`), and one that does not suit the active mode is refused. Greek and ASCII spellings both work: MΩ or MOhm, µs or us, × or x.
- **Modes**: where Commander applies the control. In another mode Commander refuses a Set or Auto with error 6004 and changes nothing, and a read returns 6004 as its value, which a snapshot files under `not_applicable`. I = 0 is listed where Commander's window leaves the control enabled in I = 0.
- **Range or choices**: the vendor's, in the row's unit (Rf is the feedback resistor), or — where ommm has none. Commander itself takes any value without an error: the nearest choice, or the end of the range. ommm refuses a value off the list or out of range instead, naming the nearest choices.
- **Readback within**: how far from the value sent Commander may keep it, on its own steps: a readback that far off or less is an `adjusted` write, further a `mismatch` ([Outcomes](writes.md#outcomes)). It is the largest difference seen on a 700B, rounded up, or the vendor's step; —: none known, so a readback must equal the value sent, as Commander's float32 holds it.
- **Telegraph**: yes, with the field, when Commander's telegraph carries it, so a program that listens (Clampex, ommm's snapshot) sees a change made in Commander's window at once. Otherwise a program sees the change only when it reads the control. No checkbox clicked in the window is telegraphed (Whole Cell's untested).
- **Route**: API `Holding` is the API's `GetHolding` and `SetHolding`, or for a button its one function; checkbox `HoldingEnable` is the checkbox's getter and setter. `.mcc`: only restarting Commander with a `.mcc` settings file changes it, which `load_config` does ([mcc.md](mcc.md)); in brackets, its key in the file, after `AXMCD_FIELD_`.
- **Note**: what the control does, and what to know before using it.

This page is generated from ommm's settings table, `src/ommm/settings.py`, by `src/ommm/docs.py`: change either, then run `uv run python -m ommm.docs`. `tests/test_docs.py` fails while the committed page differs from what they generate.

## Settings

In the settings table's order, which follows Commander's window from the top down. Read one with `get(label, unit)`; a checkbox by the name enable takes (`get("Seal Test")`).

| Commander control | ommm call | Unit | Modes | Range or choices | Readback within | Telegraph | Route | Note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mode | `set_mode("I-Clamp")` | — | all | V-Clamp, I-Clamp, I = 0 | — | yes, `uOperatingMode` | API `Mode` | V-Clamp, I-Clamp or I = 0. ommm's set\_mode goes between V-Clamp and I-Clamp only through I = 0. |
| Mode Switching | `enable("Mode Switching", on)` | — | all | on or off | — | no | API `ModeSwitchEnable` | The checkbox above the tabs, beside the mode buttons: on, the mode follows the MODE input on the front panel, or a Vm threshold set in Options > Auto, and the mode buttons grey out. Each Set toggles it, whatever the value sent. |
| Resistance Meter | `enable("Resistance Meter", on)` | — | V-Clamp, I-Clamp | on or off | — | no | API `MeterResistEnable` | The Resistance checkbox: the first meter shows resistance, from pulses added to the command, instead of the potential. Its reading changes meaning about 0.5 s after the Set. |
| Irms Meter | `enable("Irms Meter", on)` | — | V-Clamp | on or off | — | no | API `MeterIrmsEnable` | The Irms checkbox: the second meter shows the RMS current noise instead of the current. |
| Holding | `set("Holding", value, "mV")`; checkbox: `enable("Holding", on)` | mV in V-Clamp, pA in I-Clamp | V-Clamp, I-Clamp | V-Clamp: ±1000 mV; I-Clamp: ±1 V / Rf (±20 nA at 50 MΩ, ±2 nA at 500 MΩ, ±200 pA at 5 GΩ) | 0.4 mV in V-Clamp, 0.7 pA in I-Clamp | no | API `Holding`, checkbox `HoldingEnable` | The holding level, applied at once while its checkbox is on. It adds to any holding level the acquisition program sends. In V-Clamp, Holding plus the level the last Auto Pipette Offset found stays within ±1000 mV, so near the ends the range is narrower. In I-Clamp it cannot be on together with Slow Current Injection. A value set with the checkbox off is kept, and applied when the checkbox goes on. |
| Seal Test Amplitude | `set("Seal Test Amplitude", value, "mV")`; checkbox: `enable("Seal Test", on)` | mV | V-Clamp | ±1000 mV | 0.032 mV | no | API `TestSignalAmplitude`, checkbox `TestSignalEnable` | Square pulses on the command while Seal Test is on, to watch a seal form. Seal Test sends a Sync Output. |
| Seal Test Frequency | `set("Seal Test Frequency", value, "Hz")`; checkbox: `enable("Seal Test", on)` | Hz | V-Clamp | one of 2, 5, 10, 20, 50, 60, 100, 200, 500, 1000 Hz | — | no | API `TestSignalFrequency`, checkbox `TestSignalEnable` | Seal Test's pulse rate: 2, 5, 10, 20, 50, 60, 100, 200, 500 or 1000 Hz. |
| Tuning Amplitude | `set("Tuning Amplitude", value, "pA")`; checkbox: `enable("Tuning", on)` | pA | I-Clamp | ±10 V / Rf (±200 nA at 50 MΩ, ±20 nA at 500 MΩ, ±2 nA at 5 GΩ) | 3.2 pA | no | API `TestSignalAmplitude`, checkbox `TestSignalEnable` | A square current while Tuning is on, the I-Clamp twin of Seal Test, used to set Pipette Capacitance Neutralization. Tuning sends a Sync Output. |
| Tuning Frequency | `set("Tuning Frequency", value, "Hz")`; checkbox: `enable("Tuning", on)` | Hz | I-Clamp | one of 2, 5, 10, 20, 50, 60, 100, 200, 500, 1000 Hz | — | no | API `TestSignalFrequency`, checkbox `TestSignalEnable` | Tuning's rate: 2, 5, 10, 20, 50, 60, 100, 200, 500 or 1000 Hz. |
| Pipette Offset | `set("Pipette Offset", value, "mV")` | mV; the API's value is the panel's negated in I-Clamp and I = 0 | all | — | 0.03 mV in V-Clamp, 0.0007 mV in I-Clamp, 0.0007 mV in I = 0 | no | API `PipetteOffset` | Zeroes the pipette's junction potential in the bath; set it before the seal. One offset per tab, I = 0 sharing I-Clamp's, each held within ±100 mV of the level the last Auto Pipette Offset found, which nothing reads. |
| Slow Current Injection Level | `set("Slow Current Injection Level", value, "mV")`; checkbox: `enable("Slow Current Injection", on)` | mV | I-Clamp | ±1000 mV | 0.009 mV | no | API `SlowCurrentInjLevel`, checkbox `SlowCurrentInjEnable` | The membrane potential that slow current injection keeps the cell at. It cannot be on together with Holding. Its ±1000 mV range is from the SDK's sample program. |
| Slow Current Injection Settling Time | `set("Slow Current Injection Settling Time", value, "ms")`; checkbox: `enable("Slow Current Injection", on)` | ms | I-Clamp | — | — | no | API `SlowCurrentInjSettlingTime`, checkbox `SlowCurrentInjEnable` | How fast slow current injection follows: the time to 99 % when the load equals the feedback resistor. |
| Cp Fast Capacitance | `set("Cp Fast Capacitance", value, "pF")` | pF | V-Clamp | 0 to 36 pF (0 to 12 pF at 50 GΩ) | — | no | API `FastCompCap` | Fast pipette capacitance compensation, always on: there is no checkbox. 0-12 pF at 50 GΩ. Too much rings. |
| Cp Fast Tau | `set("Cp Fast Tau", value, "µs")` | µs | V-Clamp | 0.5 to 1.8 µs | 0.006 µs | no | API `FastCompTau` | The time constant of the fast capacitance compensation. |
| Cp Slow Capacitance | `set("Cp Slow Capacitance", value, "pF")` | pF | V-Clamp | 0 to 3 pF (0 to 1 pF at 50 GΩ) | 0.048 pF | no | API `SlowCompCap` | Slow pipette capacitance compensation, always on: there is no checkbox. 0-1 pF at 50 GΩ. |
| Cp Slow Tau | `set("Cp Slow Tau", value, "µs")` | µs | V-Clamp | 10 to 4000 µs | 3 µs | no | API `SlowCompTau` | The slow compensation's time constant: 10-200 µs, or 200-4000 µs with Cp Slow Tau x20 on; ommm checks it against the range the checkbox gives. |
| Cp Slow Tau x20 | `enable("Cp Slow Tau x20", on)` | — | V-Clamp | on or off | — | no | API `SlowCompTauX20Enable` | The Tau x20 checkbox: Cp Slow Tau's range times 20, and turning it on multiplies the Tau by 20. Auto Cp Slow sets it when it needs to. |
| Whole Cell Cm | `set("Whole Cell Cm", value, "pF")`; checkbox: `enable("Whole Cell", on)` | pF | V-Clamp | 1 to 1000 pF (2.5 to 1000 pF at 50 MΩ, 1 to 100 pF at 500 MΩ) | 0.002 pF | yes, `dMembraneCap` | API `WholeCellCompCap`, checkbox `WholeCellCompEnable` | The membrane capacitance Whole Cell compensates while its checkbox is on: 1-100 pF at 500 MΩ, 2.5-1000 pF at 50 MΩ. Commander's window offers Whole Cell, its values too, only at those two feedback resistors, and ommm refuses it at the others. The telegraph sends 0 while Whole Cell is off. |
| Whole Cell Rs | `set("Whole Cell Rs", value, "MΩ")`; checkbox: `enable("Whole Cell", on)` | MΩ | V-Clamp | 0.1 to 1000 MΩ (0.1 to 100 MΩ at 50 MΩ, 0.4 to 1000 MΩ at 500 MΩ) | 0.007 MΩ | yes, `dSeriesResistance` | API `WholeCellCompResist`, checkbox `WholeCellCompEnable` | The series resistance Whole Cell compensation assumes, which Rs Compensation works from: 0.4-1000 MΩ at 500 MΩ, 0.1-100 MΩ at 50 MΩ. |
| Rs Compensation Bandwidth | `set("Rs Compensation Bandwidth", value, "kHz")`; checkbox: `enable("Rs Compensation", on)` | kHz | V-Clamp | 0.32 to 16 kHz | 0.04 kHz | no | API `RsCompBandwidth`, checkbox `RsCompEnable` | The lowpass cutoff of the Rs Compensation signal. |
| Rs Compensation Prediction | `set("Rs Compensation Prediction", value, "%")`; checkbox: `enable("Rs Compensation", on)` | % | V-Clamp | 0 to 100 % | — | no | API `RsCompPrediction`, checkbox `RsCompEnable` | Adds a transient to the command so the membrane follows it despite the series resistance; needs Whole Cell on. Open loop, but it saturates if pushed too far. The 0-100 % range is ommm's own, assumed for a percentage. |
| Rs Compensation Correction | `set("Rs Compensation Correction", value, "%")`; checkbox: `enable("Rs Compensation", on)` | % | V-Clamp | 0 to 100 % | — | no | API `RsCompCorrection`, checkbox `RsCompEnable` | Positive feedback against the series resistance's voltage error. Too much oscillates and can kill the cell. With the link button beside it on, it follows Prediction; the API cannot change the link. The 0-100 % range is ommm's own, assumed for a percentage. |
| Disable/Reduce if Oscillation Detected | `enable("Disable/Reduce if Oscillation Detected", on)` | — | V-Clamp, I-Clamp | on or off | — | no | API `OscKillerEnable` | The Oscillation Killer, one checkbox per tab: on, Commander turns off or lowers Rs Compensation (V-Clamp, by 10 %) or Pipette Capacitance Neutralization (I-Clamp, by 1 pF) when it detects oscillation. Options > Auto chooses off or lower. |
| Leak Subtraction | `set("Leak Subtraction", value, "MΩ")`; checkbox: `enable("Leak Subtraction", on)` | MΩ | V-Clamp | — | — | no | API `LeakSubResist`, checkbox `LeakSubEnable` | Subtracts the leak through the seal resistance given from Membrane Current while its checkbox is on; for patches, not whole cell. Kept per Primary Output signal. |
| Zap Duration | `set("Zap Duration", value, "ms")` | ms | V-Clamp | one of 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50 ms | — | no | API `ZapDuration` | How long Zap lasts; too long may harm the seal. |
| Pipette Capacitance Neutralization | `set("Pipette Capacitance Neutralization", value, "pF")`; checkbox: `enable("Pipette Capacitance Neutralization", on)` | pF | I-Clamp | — | — | no | API `NeutralizationCap`, checkbox `NeutralizationEnable` | Partly cancels the pipette's capacitance while its checkbox is on. Too much oscillates and can kill the cell: start at 0 pF. |
| Bridge Balance | `set("Bridge Balance", value, "MΩ")`; checkbox: `enable("Bridge Balance", on)` | MΩ | I-Clamp | — | 0.3 MΩ | no | API `BridgeBalResist`, checkbox `BridgeBalEnable` | Subtracts the electrode's voltage drop from Membrane Potential, for the electrode resistance given, while its checkbox is on; set Pipette Capacitance Neutralization first. |
| Buzz Duration | `set("Buzz Duration", value, "ms")` | ms | I-Clamp, I = 0 | 0.05 to 500 ms | — | no | API `BuzzDuration` | How long Buzz lasts, one of Commander's steps from 50 µs to 500 ms (ommm checks the range, not the steps); too long can kill small cells. |
| Primary Output | `set("Primary Output", "Membrane Current")` | — | all | the signals of the tab shown: [Output signals](#output-signals) | — | yes, `uScaledOutSignal` | API `PrimarySignal` | The signal on the PRIMARY output, from the shown tab's list. Choosing one brings back that signal's own gain, filters, Output Zero and Leak Subtraction. |
| Primary Output Gain | `set("Primary Output Gain", value, "x")` | x | all | one of 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000 x | — | yes, `dAlpha` | API `PrimarySignalGain` | Gain after the filters, on the PRIMARY output. |
| Primary Output Lowpass Filter | `set("Primary Output Lowpass Filter", value, "kHz")` | kHz | all | the filter type's cutoffs, or Bypass (100 kHz): [Primary Output lowpass cutoffs](#primary-output-lowpass-cutoffs) | — | yes, `dLPFCutoff` | API `PrimarySignalLPF` | The four-pole lowpass cutoff, or Bypass (100 kHz). The cutoffs depend on the filter type, Bessel or Butterworth (Options > General), which the API cannot read: ommm takes a cutoff from either list, and Commander keeps the nearest one the active type has. |
| AC (Highpass Filter) | `set("AC (Highpass Filter)", value, "Hz")` | Hz | all | one of 0, 0.1, 1, 3, 10, 30, 100, 300 Hz | — | no | API `PrimarySignalHPF` | Highpass filter on the Primary Output; 0 Hz is DC, the filter bypassed. |
| Scope Filter | `set("Scope Filter", value, "kHz")` | kHz | all | one of 0, 1, 3, 10 kHz | — | no | API `ScopeSignalLPF` | Extra lowpass filter on the SCOPE output only: 1, 3 or 10 kHz, or Bypass, for which ommm has no API value. A signal never given a Scope Filter reads 0, and Commander takes 0 back. |
| Output Zero | `set("Output Zero", value, "mV")`; checkbox: `enable("Output Zero", on)` | mV | all | ±2900 mV | 0.04 mV | no | API `OutputZeroAmplitude`, checkbox `OutputZeroEnable` | A constant offset taken off the Primary Output while its checkbox is on: ±2900 mV at a Primary Output Gain below 10, ±290 mV from 10. The API's value reads 10 times larger below gain 10 than from 10. Kept per Primary Output signal. |
| Secondary Output | `set("Secondary Output", "Membrane Current")` | — | all | the signals of the tab shown: [Output signals](#output-signals) | — | yes, `uRawOutSignal` | API `SecondarySignal` | The signal on the SECONDARY output, from the shown tab's list; I-Clamp's list differs from the Primary Output's. |
| Secondary Output Gain | `set("Secondary Output Gain", value, "x")` | x | all | one of 1, 2, 5, 10, 20, 50, 100 x | — | yes, `dSecondaryAlpha` | API `SecondarySignalGain` | Gain after the filter, on the SECONDARY output. It stays when the Primary Output signal changes. |
| Secondary Output Lowpass Filter | `set("Secondary Output Lowpass Filter", value, "kHz")` | kHz | all | one of 10, 100 kHz | — | yes, `dSecondaryLPFCutoff` | API `SecondarySignalLPF` | 10 kHz single-pole Bessel, or Bypass (100 kHz), which Commander says filters at 30 kHz. |
| Pulse Amplitude | `set("Pulse Amplitude", value, "mV")` | mV in V-Clamp, pA in I-Clamp | V-Clamp, I-Clamp | V-Clamp: ±1000 mV; I-Clamp: ±10 V / Rf (±200 nA at 50 MΩ, ±20 nA at 500 MΩ, ±2 nA at 5 GΩ) | — | no | API `PulseAmplitude` | The step that Pulse sends. |
| Pulse Duration | `set("Pulse Duration", value, "ms")` | ms | V-Clamp, I-Clamp | 0.1 to 500 ms | — | no | API `PulseDuration` | How long Pulse lasts, one of Commander's steps from 0.1 to 500 ms (ommm checks the range, not the steps). |
| Feedback Resistor | `load_config(path, changes=[("Feedback Resistor", value, "MΩ", mode)])`, then confirmed | MΩ | all | V-Clamp: one of 50, 500, 5000, 50000 MΩ; I-Clamp and I = 0: one of 50, 500, 5000 MΩ | — | no | `.mcc` (`ELCTRD_HSTAGE_RST_RNG`) | The headstage's range, Rf, on Options > Gains, one per tab: 50 MΩ, 500 MΩ, 5 GΩ or, in V-Clamp only, 50 GΩ. Read per tab as an index into these (FeedbackResistorVC1 and IC1, on headstage 2 VC2 and IC2); changed only by restarting Commander with a .mcc file, load\_config, about 15 s without Commander (docs/mcc.md). |

## Checkboxes

Each of the window's checkboxes, by the name `enable` takes and `get` reads (`get("Seal Test")`); both take the API name and the other names too, in any case. Where a value shares its checkbox's name, `get` reads the value: `get("Holding", "mV")`, and the checkbox by its API name, `get("HoldingEnable")`.

| Commander checkbox | ommm call | Other names | Modes | API name | Applies |
| --- | --- | --- | --- | --- | --- |
| Mode Switching | `enable("Mode Switching", on)` | "Ext" | all | `ModeSwitchEnable` | — |
| Resistance Meter | `enable("Resistance Meter", on)` | "Resistance" | V-Clamp, I-Clamp | `MeterResistEnable` | — |
| Irms Meter | `enable("Irms Meter", on)` | "Irms" | V-Clamp | `MeterIrmsEnable` | — |
| Holding | `enable("Holding", on)` | — | V-Clamp, I-Clamp | `HoldingEnable` | Holding |
| Seal Test | `enable("Seal Test", on)` | — | V-Clamp | `TestSignalEnable` | Seal Test Amplitude, Seal Test Frequency |
| Tuning | `enable("Tuning", on)` | — | I-Clamp | `TestSignalEnable` | Tuning Amplitude, Tuning Frequency |
| Slow Current Injection | `enable("Slow Current Injection", on)` | — | I-Clamp | `SlowCurrentInjEnable` | Slow Current Injection Level, Slow Current Injection Settling Time |
| Cp Slow Tau x20 | `enable("Cp Slow Tau x20", on)` | "Tau x20" | V-Clamp | `SlowCompTauX20Enable` | — |
| Whole Cell | `enable("Whole Cell", on)` | — | V-Clamp | `WholeCellCompEnable` | Whole Cell Cm, Whole Cell Rs |
| Rs Compensation | `enable("Rs Compensation", on)` | — | V-Clamp | `RsCompEnable` | Rs Compensation Bandwidth, Rs Compensation Prediction, Rs Compensation Correction |
| Disable/Reduce if Oscillation Detected | `enable("Disable/Reduce if Oscillation Detected", on)` | "Oscillation Killer" | V-Clamp, I-Clamp | `OscKillerEnable` | — |
| Leak Subtraction | `enable("Leak Subtraction", on)` | — | V-Clamp | `LeakSubEnable` | Leak Subtraction |
| Pipette Capacitance Neutralization | `enable("Pipette Capacitance Neutralization", on)` | — | I-Clamp | `NeutralizationEnable` | Pipette Capacitance Neutralization |
| Bridge Balance | `enable("Bridge Balance", on)` | — | I-Clamp | `BridgeBalEnable` | Bridge Balance |
| Output Zero | `enable("Output Zero", on)` | — | all | `OutputZeroEnable` | Output Zero |

## Buttons

A button's values are settings: set them first (Zap Duration, then Zap).

| Commander button | ommm call | Modes | Route | Note |
| --- | --- | --- | --- | --- |
| Zap | `press("Zap")`; set first: Zap Duration | V-Clamp | API `Zap` | A +1 V pulse for the Zap Duration, to break into the cell from a seal. Zap sends a Sync Output. |
| Buzz | `press("Buzz")`; set first: Buzz Duration | I-Clamp, I = 0 | API `Buzz` | A strong 10 kHz current for the Buzz Duration, to help the pipette through the membrane or clear its tip; too long can kill small cells. |
| Clear + | `press("Clear +")` | I-Clamp, I = 0 | API `ClearPlus` | A large depolarizing current step, to clear a blocked pipette or help it into a cell. |
| Clear - | `press("Clear -")` | I-Clamp, I = 0 | API `ClearMinus` | A large hyperpolarizing current step, Clear + the other way. |
| Pulse | `press("Pulse")`; set first: Pulse Amplitude, Pulse Duration | V-Clamp, I-Clamp | API `Pulse` | One command step of the Pulse Amplitude, for the Pulse Duration. Pulse sends a Sync Output. |
| Auto Pipette Offset | `press("Auto Pipette Offset")` | all | API `AutoPipetteOffset` | Zeroes Pipette Offset in the bath and locks its padlock, which only a click in Commander opens. It also changes the other tab: pressed in V-Clamp the I-Clamp offset, in I-Clamp the V-Clamp offset (with nothing attached, V-Clamp's Holding). |
| Auto Cp Fast | `press("Auto Cp Fast")` | V-Clamp | API `AutoFastComp` | Measures and sets Cp Fast Capacitance and Tau with test pulses, whose size is set in Options > Advanced. |
| Auto Cp Slow | `press("Auto Cp Slow")` | V-Clamp | API `AutoSlowComp` | Measures and sets Cp Slow Capacitance and Tau, and Tau x20 as needed, with test pulses. |
| Auto Whole Cell | `press("Auto Whole Cell")` | V-Clamp | API `AutoWholeCellComp` | Measures Whole Cell Cm and Rs and turns Whole Cell on. Commander's window offers it only at 50 and 500 MΩ, and ommm refuses it at the others. |
| Auto Output Zero | `press("Auto Output Zero")` | all | API `AutoOutputZero` | Measures the Primary Output's offset for about 70 ms, sets Output Zero to it and turns it on. |
| Auto Leak Subtraction | `press("Auto Leak Subtraction")` | V-Clamp | API `AutoLeakSub` | Measures the seal resistance, sets Leak Subtraction to it and turns it on. |
| Auto Bridge Balance | `press("Auto Bridge Balance")` | I-Clamp | API `AutoBridgeBal` | Measures the electrode resistance with a test pulse, sets Bridge Balance to it and turns it on. Fails if the load is over five times the feedback resistor. |
| Reset to Program Defaults | none: Commander's window only | all | API `Reset` | Sets every control on both tabs back to Commander's defaults. ommm refuses it: press it in Commander's window, since its confirm dialog would block every call until clicked. |

## Output signals

Each tab's signals, as Commander's lists name them, with the name in `AxMultiClampMsg.h` (without `PRI_SIGNAL_` or `SEC_SIGNAL_`) and the id `get("PrimarySignal")` and `get("SecondarySignal")` return. Auxiliary 1 and 2 are whatever is on the rear-panel auxiliary inputs.

| Tab | Commander's name | API name | Primary Output id | Secondary Output id |
| --- | --- | --- | --- | --- |
| V-Clamp | Membrane Current | `VC_MEMBCURRENT` | 0 | 0 |
| V-Clamp | Membrane Potential | `VC_MEMBPOTENTIAL` | 1 | 1 |
| V-Clamp | Pipette Potential | `VC_PIPPOTENTIAL` | 2 | 2 |
| V-Clamp | 100x AC Membrane Potential | `VC_100XACMEMBPOTENTIAL` | 3 | 3 |
| V-Clamp | External Command Potential | `VC_EXTCMDPOTENTIAL` | 4 | 4 |
| V-Clamp | Auxiliary 1 | `VC_AUXILIARY1` | 5 | 5 |
| V-Clamp | Auxiliary 2 | `VC_AUXILIARY2` | 6 | 6 |
| I-Clamp | Membrane Potential | `IC_MEMBPOTENTIAL` | 7 | 7 |
| I-Clamp | Membrane Current | `IC_MEMBCURRENT` | 8 | 8 |
| I-Clamp | Command Current | `IC_CMDCURRENT` | 9 | — |
| I-Clamp | 100x AC Membrane Potential | `IC_100XACMEMBPOTENTIAL` | 10 | 11 |
| I-Clamp | External Command Current | `IC_EXTCMDCURRENT` | 11 | 12 |
| I-Clamp | Auxiliary 1 | `IC_AUXILIARY1` | 12 | 13 |
| I-Clamp | Auxiliary 2 | `IC_AUXILIARY2` | 13 | 14 |
| I-Clamp | Pipette Potential | `IC_PIPPOTENTIAL` | — | 10 |

## Primary Output lowpass cutoffs

The cutoffs of each filter type, and Bypass, 100 kHz, for both. The filter type is chosen in Options > General, and no API function reads it.

- **Bessel**: 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 40, 60, 80, 100, 120, 140, 160, 180, 200, 220, 240, 260, 280, 300, 400, 600, 800 Hz; 1, 1.2, 1.4, 1.6, 1.8, 2, 2.2, 2.4, 2.6, 2.8, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30 kHz
- **Butterworth**: 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 390, 420, 450, 600, 900 Hz; 1.2, 1.5, 1.8, 2.1, 2.4, 2.7, 3, 3.3, 3.6, 3.9, 4.2, 4.5, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45 kHz

## Appendix: every API function

`AxMultiClampMsg.h` (API 1.0.0.9) declares 121 functions: 51 `Get`, 47 `Set` and 23 others. Each is here with the control it serves, or why it serves none; a getter and setter of one API name share a line.

| Functions | Control, or why none |
| --- | --- |
| `AutoBridgeBal` | Auto Bridge Balance |
| `AutoFastComp` | Auto Cp Fast |
| `AutoLeakSub` | Auto Leak Subtraction |
| `AutoOutputZero` | Auto Output Zero |
| `AutoPipetteOffset` | Auto Pipette Offset |
| `AutoSlowComp` | Auto Cp Slow |
| `AutoWholeCellComp` | Auto Whole Cell |
| `BuildErrorText` | setup: Commander's words for an error code |
| `Buzz` | Buzz |
| `CheckAPIVersion` | setup: ommm.Amplifier() checks the DLL against its header |
| `ClearMinus` | Clear - |
| `ClearPlus` | Clear + |
| `CreateObject` | setup: ommm.Amplifier() makes its one handle, reconnect() a new one |
| `DestroyObject` | setup: Commander.close() frees it |
| `FindFirstMultiClamp` | setup: finds the headstage asked for (1 or 2) of the one 700B |
| `FindNextMultiClamp` | setup: finds the headstage asked for (1 or 2) of the one 700B |
| `GetBridgeBalEnable`, `SetBridgeBalEnable` | the checkbox of Bridge Balance |
| `GetBridgeBalResist`, `SetBridgeBalResist` | Bridge Balance |
| `GetBuzzDuration`, `SetBuzzDuration` | Buzz Duration |
| `GetFastCompCap`, `SetFastCompCap` | Cp Fast Capacitance |
| `GetFastCompTau`, `SetFastCompTau` | Cp Fast Tau |
| `GetFeedbackResistorIC1` | read into headstage 1's snapshot, as the Feedback Resistor row's index in I-Clamp; no setter |
| `GetFeedbackResistorIC2` | read into headstage 2's snapshot, as the Feedback Resistor row's index in I-Clamp; no setter |
| `GetFeedbackResistorVC1` | read into headstage 1's snapshot, as the Feedback Resistor row's index in V-Clamp; no setter |
| `GetFeedbackResistorVC2` | read into headstage 2's snapshot, as the Feedback Resistor row's index in V-Clamp; no setter |
| `GetHolding`, `SetHolding` | Holding |
| `GetHoldingEnable`, `SetHoldingEnable` | the checkbox of Holding |
| `GetLeakSubEnable`, `SetLeakSubEnable` | the checkbox of Leak Subtraction |
| `GetLeakSubResist`, `SetLeakSubResist` | Leak Subtraction |
| `GetMeterIrmsEnable`, `SetMeterIrmsEnable` | Irms Meter |
| `GetMeterResistEnable`, `SetMeterResistEnable` | Resistance Meter |
| `GetMeterValue` | the four meters, two per headstage: live readings in the snapshot, not a control |
| `GetMode`, `SetMode` | Mode |
| `GetModeSwitchEnable`, `SetModeSwitchEnable` | Mode Switching |
| `GetNeutralizationCap`, `SetNeutralizationCap` | Pipette Capacitance Neutralization |
| `GetNeutralizationEnable`, `SetNeutralizationEnable` | the checkbox of Pipette Capacitance Neutralization |
| `GetOscKillerEnable`, `SetOscKillerEnable` | Disable/Reduce if Oscillation Detected |
| `GetOutputZeroAmplitude`, `SetOutputZeroAmplitude` | Output Zero |
| `GetOutputZeroEnable`, `SetOutputZeroEnable` | the checkbox of Output Zero |
| `GetPipetteOffset`, `SetPipetteOffset` | Pipette Offset |
| `GetPrimarySignal`, `SetPrimarySignal` | Primary Output |
| `GetPrimarySignalGain`, `SetPrimarySignalGain` | Primary Output Gain |
| `GetPrimarySignalHPF`, `SetPrimarySignalHPF` | AC (Highpass Filter) |
| `GetPrimarySignalLPF`, `SetPrimarySignalLPF` | Primary Output Lowpass Filter |
| `GetPulseAmplitude`, `SetPulseAmplitude` | Pulse Amplitude |
| `GetPulseDuration`, `SetPulseDuration` | Pulse Duration |
| `GetRsCompBandwidth`, `SetRsCompBandwidth` | Rs Compensation Bandwidth |
| `GetRsCompCorrection`, `SetRsCompCorrection` | Rs Compensation Correction |
| `GetRsCompEnable`, `SetRsCompEnable` | the checkbox of Rs Compensation Bandwidth, Rs Compensation Prediction, Rs Compensation Correction |
| `GetRsCompPrediction`, `SetRsCompPrediction` | Rs Compensation Prediction |
| `GetScopeSignalLPF`, `SetScopeSignalLPF` | Scope Filter |
| `GetSecondarySignal`, `SetSecondarySignal` | Secondary Output |
| `GetSecondarySignalGain`, `SetSecondarySignalGain` | Secondary Output Gain |
| `GetSecondarySignalLPF`, `SetSecondarySignalLPF` | Secondary Output Lowpass Filter |
| `GetSlowCompCap`, `SetSlowCompCap` | Cp Slow Capacitance |
| `GetSlowCompTau`, `SetSlowCompTau` | Cp Slow Tau |
| `GetSlowCompTauX20Enable`, `SetSlowCompTauX20Enable` | Cp Slow Tau x20 |
| `GetSlowCurrentInjEnable`, `SetSlowCurrentInjEnable` | the checkbox of Slow Current Injection Level, Slow Current Injection Settling Time |
| `GetSlowCurrentInjLevel`, `SetSlowCurrentInjLevel` | Slow Current Injection Level |
| `GetSlowCurrentInjSettlingTime`, `SetSlowCurrentInjSettlingTime` | Slow Current Injection Settling Time |
| `GetTestSignalAmplitude`, `SetTestSignalAmplitude` | Seal Test Amplitude, Tuning Amplitude |
| `GetTestSignalEnable`, `SetTestSignalEnable` | the checkbox of Seal Test Amplitude, Seal Test Frequency, Tuning Amplitude, Tuning Frequency |
| `GetTestSignalFrequency`, `SetTestSignalFrequency` | Seal Test Frequency, Tuning Frequency |
| `GetWholeCellCompCap`, `SetWholeCellCompCap` | Whole Cell Cm |
| `GetWholeCellCompEnable`, `SetWholeCellCompEnable` | the checkbox of Whole Cell Cm, Whole Cell Rs |
| `GetWholeCellCompResist`, `SetWholeCellCompResist` | Whole Cell Rs |
| `GetZapDuration`, `SetZapDuration` | Zap Duration |
| `Pulse` | Pulse |
| `QuickSelectButton` | not supported: it loads whatever .mcc file the button was given; ommm restarts Commander with one |
| `Reset` | Reset to Program Defaults |
| `SelectMultiClamp` | setup: selects the headstage, and brings its active mode's tab to the front |
| `SetTimeOut` | setup: the wait for Commander's answer, 3 s, set once on each handle |
| `ToggleAlwaysOnTop` | Commander's window only, with no getter to tell its state |
| `ToggleResize` | Commander's window only, with no getter to tell its state |
| `Zap` | Zap |
