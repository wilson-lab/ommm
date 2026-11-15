# How a write works

`ommm.Amplifier` reads and sets **one headstage of one MultiClamp 700B**, headstage 1 or `headstage=2` ([Two headstages](#two-headstages)), through the Commander running on the same PC, by Commander's labels and with a unit on every value. This page is the Python class; MATLAB's `ommm.Amplifier` makes the same calls under the same names, each write returned as a struct and a refusal raised as an error with an identifier ([matlab.md](matlab.md)). Each control's unit, modes, range and readback tolerance are in [coming-from-commander.md](coming-from-commander.md).

```python
import ommm

amp = ommm.Amplifier()                            # headstage 1 of the one 700B; ommm.Amplifier(2) for headstage 2
amp.get("Holding", "mV")                          # -60.0: always with a unit
amp.set("Holding", -60, "mV")                     # checks, sends, reads back, logs: a Write
amp.set("Holding", -40, "mV", step=5)            # in 5 mV steps, each read back
amp.plan("Rs Compensation Correction", 60, "%")   # set's checks; sends nothing
amp.enable("Seal Test", True)                     # a checkbox, by its name on Commander's window
amp.set("Primary Output", "Membrane Potential")   # an output signal, by Commander's name; its gain after
amp.set_mode("I-Clamp")                           # through I = 0; returns what changed
amp.press("Auto Bridge Balance")                  # a button, by its name on Commander's window
amp.make_safe()                                   # compensation, Seal Test or Tuning, the Resistance meter: off
```

Every one of these acts on the amplifier at once, exactly as Commander's own control does: Holding steps the command, Zap pulses the pipette. What ommm leaves to your code: [What ommm does not do](#what-ommm-does-not-do).

Without Commander, `ommm.Amplifier(fake=ommm.EXAMPLES / "fake/vclamp.json", other_tab=ommm.EXAMPLES / "fake/iclamp.json")` runs every call on [the fake](install-and-testing.md#the-fake).

[The calls](#the-calls) · [Two headstages](#two-headstages) · [Units](#units) · [Reads](#reads) · [Before every write](#before-every-write) · [Every refusal](#every-refusal) · [Sending and reading back](#sending-and-reading-back) · [Outcomes](#outcomes) · [Checkboxes, buttons and the mode](#checkboxes-buttons-and-the-mode) · [`make_safe`](#make_safe) · [When something fails](#when-something-fails) · [Error codes](#error-codes) · [The log and trial records](#the-log-and-trial-records) · [What ommm does not do](#what-ommm-does-not-do)

## The calls

| Call | Does | Returns |
|---|---|---|
| `ommm.Amplifier(headstage=1, *, log_dir=None, fake=None, other_tab=None, commander=None)` | finds headstage 1 (or 2) of the one 700B Commander runs, refusing none or several, or a headstage that is not connected; logs to `log_dir`, `~/ommm-logs` by default, a relative one from the working folder when the Amplifier is made; `fake=` serves a saved snapshot instead of Commander, `other_tab=` the snapshot of its other tab ([the fake](install-and-testing.md#the-fake)); `commander=`, never with `fake=`, takes a fake made by hand or another handle on it (`fake.handle(2)`), on the Amplifier's headstage; on a fake the log goes to a new temporary folder, made by its first line (`amp.log_path`); a `log_dir` ommm cannot make or write to is refused when the Amplifier is made | the amplifier |
| `get(label, unit)` | reads one control, in your unit ([Reads](#reads)) | the value |
| `set(label, value, unit, *, step=None, expect=None)` | checks, sends, reads back and logs a value or an output signal; `step=5` and `expect=-50` are numbers in the call's unit, an output signal's `expect` its name | a `Write` |
| `plan(label, value, unit, *, step=None, expect=None)` | `set`'s checks, from fresh reads; sends and logs nothing | a `Write`, `planned` or `refused` |
| `enable(name, on)` | turns a checkbox on or off | a `Write` |
| `press(name)` | presses a button, the Autos included | a `Write` |
| `set_mode(mode)` | `"V-Clamp"`, `"I-Clamp"` or `"I = 0"`, or Commander's buttons `"VC"`, `"IC"`, `"I=0"`; V-Clamp ↔ I-Clamp through I = 0 | a `Write` |
| `make_safe()` | turns off what can harm a cell left on | the `Write`s it sent |
| `snapshot()` | every reading, the telegraph and ommm's provenance ([The snapshot](install-and-testing.md#the-snapshot)) | a dict, in SI |
| `writes_since(mark=0)` | the write log's lines after a byte offset | `(lines, next mark)` |
| `reconnect()` | new handles after Commander was closed or restarted | — |
| `headstage`, `serial`, `log_path`, `gui` | 1 or 2; the amplifier's serial; the write log; on the fake, the person at Commander's window ([the fake](install-and-testing.md#the-fake)). The headstage's full record is `snapshot()["headstage"]` | — |
| `load_config(path, *, changes=(), confirmed=False, release_other_headstage=False)` | closes Commander and starts it again with a `.mcc` settings file, for the feedback resistor and the rest of the Options dialog; without `confirmed=True`, the plan only; refused while the other headstage holds a level, unless `release_other_headstage=True` ([mcc.md](mcc.md)) | a `Write` |

`set`, `enable`, `press`, `set_mode`, `make_safe` and `load_config` with `confirmed=True` raise `ommm.WriteError` unless the write was `ok` or `adjusted` ([Outcomes](#outcomes)); its `write` holds what was read, sent and read back. Its message is the reason alone for a refusal, and `label: outcome: reason` for a write that was sent. `with ommm.Amplifier() as amp:` closes the handle at the end.

## Two headstages

- **Headstage 2 is not supported;** its calls are in the API. `ommm.Amplifier(2)` (MATLAB `Headstage=2`, the command `ommm --headstage 2`) drives headstage 2. With both in use, make one Amplifier for each: each selects its own headstage before every call, so their calls take turns. Commander has one selection for every program, so two programs at once can reach each other's headstage: with both in use, run one ([quirks.md](quirks.md#two-headstages)).
- What names a headstage: its feedback resistor readings (`FeedbackResistorVC1` and `IC1`, on headstage 2 `VC2` and `IC2`), its meters (`MeterValue1` and `2`, on headstage 2 `3` and `4`; `get` refuses the other headstage's), its sections of a `.mcc` file, and its write log, each line with its `headstage`. A snapshot holds its headstage's feedback resistors and all four meters.
- A headstage that is not connected is refused when the Amplifier is made: unplugged, `headstage 2 is not connected: Commander lists only headstage 1`; listed but not answering, `headstage 2 is not connected: Commander answers its feedback resistor with 6006 (MCCCOMMANDFAIL)`.
- Both headstages share one Commander, so `load_config` restarts it for both ([mcc.md](mcc.md#two-headstages)).
- What has run on headstage 2: [What has been tested](install-and-testing.md#what-has-been-tested). What Commander does with two headstages: [quirks.md](quirks.md#two-headstages).

## Units

- **Every value carries a unit**, of the kind Commander shows for that control in the active mode: `set("Holding", -60, "mV")`, or `set("Holding", -0.06, "V")`, in V-Clamp; in I-Clamp Holding is a current, so `"pA"` or `"nA"`, and `"mV"` refuses. A missing, unknown or wrong-kind unit refuses a write, and `get` raises `ValueError`.
- **The units:** V, mV; A, nA, pA; F, pF; Ω, MΩ, GΩ (or Ohm, MOhm, GOhm); s, ms, µs (or us); Hz, kHz; % for Rs Compensation; × (or x) for gains. Ω also works as the ohm sign (U+2126) and µ as the Greek mu (U+03BC). A refusal names the units to give in the spelling of the one you gave: `MOhm or GOhm, not pA`, `MΩ or GΩ, not µs`.
- **No unit:** an output signal by Commander's name for it (`"Membrane Current"`), a checkbox's `True` or `False`, the mode by name.
- **Pipette Offset** takes and gives the window's sign in every mode, though the API's value in I-Clamp and I = 0 is its negative.
- **Rs Compensation Bandwidth** is in kHz, as Commander shows it; the API's is in Hz.
- **A `Write`, the log and the snapshot** hold the API's values: SI, Rs Compensation Prediction and Correction in percent, gains as plain numbers, checkboxes as `True` or `False`, the mode and output signals as ids. `user_value` and `unit` are what you gave.
- **float32.** Commander stores values as float32 ([the snapshot](install-and-testing.md#the-snapshot)), so ommm sends each as the shortest decimal with the same float32 bits (0.1 ms goes as 0.0001, not 9.999999999999999e-05), and `get` returns readings that way.

## Reads

- `get(label, unit)` reads one control in your unit: `get("Holding", "mV")` in V-Clamp, `get("Holding", "pA")` in I-Clamp.
- Without a unit: the mode by name (`get("Mode")` is `"V-Clamp"`), an output signal by Commander's name (`"Membrane Current"`), a checkbox row as `True` or `False` (`get("Mode Switching")`), and any checkbox by the name `enable` takes (`get("Seal Test")`), or its API name; a label comes first, so `get("Holding", "mV")` is the value and `get("HoldingEnable")` its checkbox.
- The meters: `get("MeterValue1", "mV")`, the membrane potential, or with the Resistance meter on the resistance, which then needs a resistance unit; `get("MeterValue2", "pA")`, the current; on headstage 2, `MeterValue3` and `MeterValue4`. Their meaning changes about 0.5 s after the Resistance meter is turned on or off. Commander's meter can show OVLD, which the API cannot see: `get` gives only the number.
- A control the active mode lacks raises `ommm.NotApplicable`; a wrong or missing unit, `ValueError`; a button, `ValueError` too.
- `snapshot()` holds every reading in SI ([The snapshot](install-and-testing.md#the-snapshot)). It sends no Set and presses nothing.
- **Every read and write first brings the active mode's tab to the front** (`SelectMultiClamp`, 0.1-8 ms), since the API reads and sets the tab Commander shows. So a tab you click in Commander's window to look at the other mode goes back at ommm's next call; nothing is refused and nothing needs a click. Listing the amplifiers (`select()`, about 1 s) happens only at connect and `reconnect()`.

## Before every write

`plan()` and `set()` read Commander afresh and refuse, sending nothing, unless all of these hold. `enable`, `press` and `set_mode` make the same checks where they apply. Every refusal names the reason and what to do ([Every refusal](#every-refusal)).

1. **Commander is running** in this desktop session: ommm looks for its hidden window, "Invisible MultiClamp Startup Window", by its title. The window goes as soon as Commander closes, so a closed Commander refuses at once, instead of after a 3 s timeout.
2. **The active mode's tab is in front** ([Reads](#reads)) and the mode is read; **the telegraph agrees** on it. A write without a telegraph refuses, so writes do not work in Commander's Demo mode.
3. **Mode Switching is off**, except to turn it off: with it on, the mode follows the MODE input, which floats with nothing connected to it, so turning Mode Switching on and off again can leave the amplifier in another mode, such as I = 0. The `Write`'s `also` shows such a mode change, `{"Mode": [0, 2]}`, and its `reason` names the new mode.
4. **The control is in the active mode**, by its label: `set("Seal Test Frequency", 10, "Hz")` refuses in I-Clamp, where the same API setting is Tuning Frequency. A checkbox is `enable`'s (`set("Seal Test", ...)` refuses and says to turn it on or off with `enable("Seal Test", on)`), a button `press`'s, the mode `set_mode`'s, and the feedback resistor `load_config`'s ([mcc.md](mcc.md)). A name ommm does not know refuses with the nearest label: `"Holdng"`, did you mean `'Holding'`?
5. **The value is valid**: a number, in a unit of the control's kind, one of Commander's values where it offers a list, within the vendor's range ([Range or choices](coming-from-commander.md#settings)). ommm never snaps a value: an off-list one refuses and names Commander's values either side of it, `set("Primary Output Gain", 3, "x")` 2 x and 5 x, or past an end the smallest or largest. Commander itself takes any value without an error, snapping or clipping it.
   - In I-Clamp, Holding is ±1 V over the feedback resistor, and Tuning and Pulse ±10 V over it: ±200 pA of Holding at 5 GΩ.
   - In V-Clamp, Cp Fast is 0-36 pF and Cp Slow 0-3 pF, but 0-12 pF and 0-1 pF at 50 GΩ; Whole Cell is 1-100 pF and 0.4-1000 MΩ at 500 MΩ, 2.5-1000 pF and 0.1-100 MΩ at 50 MΩ.
   - **Whole Cell** (its values, its checkbox and Auto Whole Cell) is refused at 5 and 50 GΩ, where Commander's window greys the whole panel out. The API alone would still run it.
   - Cp Slow Tau is 10-200 µs, or 200-4000 µs with Cp Slow Tau x20 on.
   - Output Zero is ±2900 mV at a Primary Output gain below 10, ±290 mV from 10.
   - Seal Test and Tuning Frequency are one of 2, 5, 10, 20, 50, 60, 100, 200, 500 and 1000 Hz, each read back as sent; Commander keeps any other as the one whose period is nearest. ommm sends the period that `SetTestSignalFrequency` takes, though the vendor documents Hertz ([quirks.md](quirks.md#seal-test-and-tuning-frequency-are-set-as-a-period)).
   - The Primary Output lowpass takes the cutoffs of either filter type; the API cannot read which one Commander uses, so a cutoff of the other type reads back as Commander's nearest, a `mismatch` that says so.
   - Pulse Duration and Buzz Duration are within their ranges, but Commander keeps each on its own list of steps, which ommm does not have: a value off it reads back as another, a `mismatch` that says so.
6. **Turning a checkbox on checks every value it applies against its range first**, whichever checkbox it is: Holding, Seal Test, Pipette Capacitance Neutralization and Rs Compensation apply their stored values at once.
7. **Holding and Slow Current Injection are never both on in I-Clamp**: turning one on refuses while the other is on. The API alone would turn both on.
8. **`expect=`**, when given, is what Commander still shows, in the call's unit, within the control's resolution: a confirm dialog passes the value it showed, so a click in Commander's window meanwhile refuses rather than being overwritten.
9. **The telegraph's output signals are fresh.** They are stale from Commander's start until each mode's signals are set; when they disagree with the API's, ommm first re-selects both outputs' signals as Commander shows them, each a write read back and logged, so the telegraph, and Clampex, which scales by it, report them. One that does not take raises `WriteError`, and the write you asked for is not sent.

`plan()` returns the `Write` with outcome `planned`, or `refused` and the reason, and logs nothing. A planned write's `reason` is the text of a confirm dialog, the change in the caller's unit: `Holding 0 mV → -40 mV (V-Clamp)`, `Zap Duration 0.025 ms → 0.5 ms (V-Clamp)`; the `set` that follows keeps the same line. When the control's checkbox is off (Holding, Seal Test, Bridge Balance, Whole Cell, ...), Commander stores the value and applies it once the checkbox is on, and the line says so: `Holding 0 mV → -40 mV (V-Clamp); Holding is off: the value applies once it is on`. It covers `set` only.

## Every refusal

A refusal is logged and raises `ommm.WriteError`, and nothing is sent (between steps, nothing more); `plan()` returns it and logs nothing. `load_config`'s own are in [mcc.md](mcc.md#every-refusal). Its `reason` is one of these, naming each control as Commander's window does and saying what to do. The examples are for V-Clamp at 5 GΩ, unless a row says otherwise.

**Commander and the mode,** checked before every write:

| When | The reason |
|---|---|
| Commander is not running in this desktop session | `Commander is not running in this desktop session: start it, then reconnect()` |
| Commander was closed or restarted since ommm connected (6002) | `Commander was closed or restarted: reconnect() (amp.reconnect() in Python, a.reconnect() in MATLAB) (6002)` |
| Mode Switching is on, for every write but turning it off, `make_safe` included | `Mode Switching is on, so the mode follows the MODE input: turn it off first: enable("Mode Switching", on) with on false` |
| The telegraph reports another mode than the API | `Commander's API says V-Clamp and its telegraph I-Clamp: try again` |
| No telegraph packet came; `make_safe` needs none | `the mode cannot be checked: no telegraph from Commander for headstage 1 within 1 s`; in Commander's Demo mode, `the mode cannot be checked: no telegraph for a non-numeric (Demo mode) serial` |
| A telegraph packet of another size | `a telegraph packet of 128 bytes; ommm decodes 256-byte ones` |
| A reading a check needs fails | `could not read FeedbackResistorVC1: ...`, then Commander's error |

**The name:**

| When | The reason |
|---|---|
| A name ommm does not know | `'Holdng' is not a Commander control ommm knows: did you mean 'Holding'? Every label: docs/coming-from-commander.md` |
| A control the active mode lacks, given to `set`, `press`, `enable` or `get` | `Bridge Balance is not in V-Clamp: Commander has it in I-Clamp`; for a row whose API name another row has in this mode, `Tuning Amplitude is not in V-Clamp: Commander has it in I-Clamp; in V-Clamp it is Seal Test Amplitude` |
| An API name two labels share, neither in the active mode (I = 0) | `TestSignalAmplitude is 'Seal Test Amplitude' or 'Tuning Amplitude': neither is in I = 0` |
| A checkbox given to `set` or `press` | `Seal Test is a checkbox: turn it on or off with enable("Seal Test", on)`; for one the active mode lacks, `enable`'s reason below |
| A button given to `set` | `Zap is a button: press("Zap")` |
| A setting given to `press` | `Zap Duration is a value, not a button: set("Zap Duration", value, "ms")`; for a value with a checkbox, `Holding is a value, not a button: set("Holding", value, "mV"), or enable("Holding", on)`; for the feedback resistor, `load_config with a .mcc file, which restarts Commander (docs/mcc.md)` |
| The mode given to `set` | `the mode changes with set_mode("I-Clamp"), which goes through I = 0` |
| The feedback resistor | `Feedback Resistor changes only by restarting Commander with a .mcc file: load_config with the file and the change (Feedback Resistor, 500, MΩ, V-Clamp) shows what will change; confirmed, it makes it (docs/mcc.md)` |
| Reset to Program Defaults | `Reset to Program Defaults: press it in Commander's window; ommm does not, since its confirm dialog would block every call until clicked` |
| A checkbox `enable` does not find in the active mode | another mode's: `Tuning is a checkbox in I-Clamp; in V-Clamp it is Seal Test`, or `Bridge Balance is a checkbox in I-Clamp, not in V-Clamp; in V-Clamp, enable takes Mode Switching, Resistance Meter, ...`; a button: `Zap is a button: press("Zap")`; a value: `Primary Output Gain is a value: set("Primary Output Gain", value, "x")`; any other name, the unknown name's reason above, with the names `enable` takes |
| A mode `set_mode` does not know | `'current clamp' is not a mode: use 'V-Clamp', 'I-Clamp' or 'I = 0', or the buttons' 'VC', 'IC' or 'I=0'` |

**The value:**

| When | The reason |
|---|---|
| Not a number | `Holding takes a number, not '-60'` |
| No unit, or a unit of another kind | `Holding in V-Clamp is a voltage: mV, not pA`, without a unit `Holding in V-Clamp is a voltage: give a unit: mV`; in I-Clamp, `a current: pA or nA`. In `get`, a value that shares its checkbox's name adds the checkbox's API name: `...: give a unit: mV; its checkbox is get("HoldingEnable")` |
| Off Commander's list | `Primary Output Gain is one of Commander's values, not 3 x; the values either side: 2 x and 5 x`; past an end, `the largest: 2000 x` |
| Outside the vendor's range, in the active mode at the feedback resistor read | `Holding in V-Clamp is -1000 mV to 1000 mV, so not -1200 mV` |
| An output signal with a unit or `step=` | `Primary Output takes a signal by its name alone: set("Primary Output", "Membrane Current")` |
| An output signal not on the tab's list | `Primary Output on the V-Clamp tab is one of Membrane Current, Membrane Potential, ...; not 'Vm'` |
| Whole Cell's values, its checkbox or Auto Whole Cell at 5 or 50 GΩ | `Commander's window greys Whole Cell out at a feedback resistor of 5 GΩ: it needs 50 or 500 MΩ, which load_config sets (docs/mcc.md)` |
| `expect=` is not what Commander shows | `Commander no longer shows -50 mV for Holding: it shows 0 mV`; for an output signal, `Commander no longer shows Membrane Potential: it shows Membrane Current` |
| `step=` or `expect=` that is not a finite number; `True` and `"5"` are not numbers | `the step is a number in the call's unit, not '5'`; `the expected value is a number in the call's unit, not nan`; for an output signal, `the expected value of Primary Output is a signal's name, such as "Membrane Current"` |
| `step=` for a value from a list | `Primary Output Gain is one of Commander's values: it takes no step` |
| `step=` of 0 | `the step needs to be larger than 0` |
| `step=` of more than 1000 steps | `steps of that size would take 6000, more than 1000: take a larger step` |

**Checkboxes:**

| When | The reason |
|---|---|
| Neither `True` nor `False` (1 and 0 included) | `Seal Test is on or off: True or False, not 1` |
| Holding or Slow Current Injection while the other is on, in I-Clamp | `Holding and Slow Current Injection are never both on in I-Clamp: turn Slow Current Injection off first` |
| A value the checkbox applies at once is out of its range (I-Clamp at 5 GΩ, 500 pA stored) | `turning Holding on applies Holding, 500 pA, at once, and that is outside -200 pA to 200 pA: set it first` |

**During the write:**

| When | The reason |
|---|---|
| Commander changed between two steps of `step=`, or between `set_mode`'s two `SetMode`s; the earlier steps were sent | `Commander changed since the write was checked: Holding was -25 mV, now -10 mV (step 2 of 3; the last confirmed -25 mV)`; in `set_mode`, `the mode was I = 0, now V-Clamp` |
| The reads between two steps fail | `could not read Commander: ...`, then Commander's error |
| The snapshot before `press` or `set_mode` fails; nothing was sent | `no snapshot before it: ...`, then Commander's error |
| `make_safe` fails after turning something off | its reason, then what it had turned off: `(after turning off Rs Compensation)` |

## Sending and reading back

- `set()` sends the value in one go, as Commander does when you type it, then reads it back at once: a Set or an Auto has its result in place by the time it returns. The mode, the output signals and the two outputs' gains and lowpass filters are also checked against a telegraph packet. Whole Cell's Cm and Rs are telegraphed only while it is on, so ommm does not check them.
- `step=5`, for a continuous value, in the call's unit: steps of that size from the value read, then the value asked for, each sent and read back. Before each step ommm reads again what the write was checked against (the mode, Mode Switching, the value it last read back) and stops if anything changed. At most 1000 steps.
- **What else a Set changed** is read before and after it, and the `Write`'s `also` lists it as `{API name: [before, after]}` (in the log too): choosing a Primary Output signal brings back that signal's own gain, lowpass and highpass filters, Scope Filter, Output Zero and Leak Subtraction, but not the Secondary Output's gain; the Primary Output gain rescales Output Zero's API value; Cp Slow Tau x20 multiplies Cp Slow Tau by 20; with the link beside them on, Rs Compensation Correction follows Prediction; turning Mode Switching on or off can change the mode, which then follows the floating mode input.
- **Set the signal first, then its gain:** a gain set before is kept with the signal it was set on. No call sets two controls.

## Outcomes

Each call returns a `Write` (a frozen dataclass): `label, stem, mode, user_value, unit, before, target, steps, depends, after, also, outcome, reason, t`. `depends` holds what the write was checked against. `before`, `target` and `after` are the value of what `stem` names, `after` as read back: for `set_mode` the mode id, for `load_config` the mode and both feedback resistors, and for a button, which has no value, `None`. `steps` holds only what was sent. `also` holds every other change as `{name: [before, after]}`, reading and telegraph names side by side: for a Set, the other readings it changed ([Sending and reading back](#sending-and-reading-back)); for a button, `set_mode` and `load_config`, the rest of what a snapshot shows changed. `t` is when the first Set or button was sent; each log line has its own. `reason` also carries a note on an `ok` write that needs one (nothing sent, the other tab's Pipette Offset, a checkbox that is off).

| Outcome | Means | `set` |
|---|---|---|
| `planned` | `plan()`: every check passed | — |
| `ok` | read back as sent | returns |
| `adjusted` | Commander kept it on its own step, within the control's resolution | returns |
| `mismatch` | read back as another value, or a telegraph that disagrees; the reason says why when ommm knows (Commander lowered it with the oscillation killer; Pipette Offset held within ±100 mV of the last Auto's level; Correction following Prediction; a value off Commander's steps) | raises |
| `refused` | a check failed; nothing was sent. Between the steps of `step=`, a refusal comes after the earlier steps were sent: its reason names the step and the last value confirmed, as a `mismatch` mid-sequence does | raises |
| `unknown` | sent, and Commander did not answer in time (6005), so it may or may not have changed; or read back as sent, but no telegraph came to check it | raises |
| `error` | Commander refused the call ([Error codes](#error-codes)) | raises |

**Resolution.** Commander keeps values on its own steps, so a readback seldom equals the value sent: Holding 12.3456 mV reads 11.995 mV; Seal Test Amplitude 10 mV reads 9.99687 mV, in steps of 31.3 µV, and Cp Slow Capacitance 0.5 pF reads 0.476 pF, in steps of 3/63 pF. A readback within the control's resolution is `adjusted`, beyond it a `mismatch`. Each control's resolution is its **Readback within** in [coming-from-commander.md](coming-from-commander.md#settings): the largest difference seen on the amplifier, rounded up, or the vendor's step; where none is known, any difference is a `mismatch`.

## Checkboxes, buttons and the mode

- **`enable(name, on)`** takes a checkbox by its name on Commander's window: a panel's (Seal Test, Tuning, Rs Compensation, Holding) or a standalone one's (Cp Slow Tau x20, Resistance Meter), Mode Switching and Oscillation Killer too; every one is in [Checkboxes](coming-from-commander.md#checkboxes), with the other names it takes (Ext, Resistance, Irms, Tau x20). Turning one on is checked as [above](#before-every-write).
  - Whole Cell is refused at a feedback resistor of 5 or 50 GΩ, where Commander's window greys it out; the API alone would turn it on.
  - Mode Switching is read first and sent only to change it, since each Set flips it whatever the value.
- **`press(name)`** presses a button: Zap, Buzz, `Clear +`, `Clear -`, Pulse, every Auto. Reset to Program Defaults is refused: press it in Commander's window, since its confirm dialog would block every call until clicked. Its values are settings, set first (`set("Zap Duration", 0.5, "ms")`); the `Write`'s `also` is the button's result, what a snapshot shows changed, and its `before`, `target` and `after` are `None` ([Outcomes](#outcomes)). Auto Whole Cell is refused where Whole Cell is.
  - **Auto Pipette Offset also changes the other tab:** pressed in V-Clamp, the I-Clamp offset; pressed in I-Clamp, the V-Clamp offset, or with nothing attached to the headstage V-Clamp's Holding instead. The API reads a tab only while Commander shows it, and only a click or a mode change shows the inactive one, so that change shows when the other mode is read; the `Write`'s `reason` says so. It also locks the window's padlock, which only a click opens.
  - **The Autos return when they are done**, their result final at the first read. Pulse and Zap are over when `press` returns; Buzz and Clear drive the primary output for about 0.4 s after it, so wait that long before recording ([quirks.md](quirks.md#pulse-zap-buzz-and-clear-act-after-the-call-returns)).
- **`set_mode(mode)`** goes between V-Clamp and I-Clamp only through I = 0, a logged write per `SetMode`, each read back from the API and the telegraph as soon as it returns, which shows the new mode at once. `SetMode` takes about 40-230 ms, and a whole `set_mode`, with its snapshots, 125-370 ms. ommm adds no wait for the outputs to settle: if a recording needs them settled after a mode change, wait before it ([quirks.md](quirks.md#mode-changes-show-at-once)).
  - It then refreshes the new mode's telegraph signals if they are stale.
  - It returns one `Write`: `after` is the mode id read back last, `steps` the mode ids sent, and `also` what else a snapshot shows changed from before the first `SetMode` to the end, the new mode's tab included, so its Holding and checkboxes are in front of you. Already in that mode, it sends nothing: `steps` is empty and `after` is `before`.
  - A failure after the first `SetMode` leaves Commander in I = 0, which passes no command current. Set I-Clamp's Holding yourself after.

## `make_safe`

`make_safe()` turns off, where the active mode has them, Pipette Capacitance Neutralization, Rs Compensation, Seal Test or Tuning, and the Resistance meter: so in V-Clamp Rs Compensation, Seal Test and the meter, in I-Clamp Neutralization, Tuning and the meter, and in I = 0 none of them. Each is read first and sent only if on, and it stops at its first failure. It turns nothing on, steps no Holding and needs no telegraph, but still needs Mode Switching off. A failure's reason ends with what it had turned off already.

## When something fails

- **No retry, no rollback.** The first failure stops: a step sequence stops at its first `mismatch`, `unknown`, `error` or refusal, and nothing is undone; the `WriteError` says how far it got and the last value confirmed, and its `before` is the value before the first step.
- **6005, no answer in time** (3 s): the write is `unknown` and never sent again. After a button times out, ommm waits its longest documented duration (Zap 50 ms, Buzz and Pulse 500 ms; 3 s for the others, which have none documented) before reading. A modal Commander dialog, such as the Reset to Program Defaults confirmation or an oscillation warning, may block every call this way; an open Options dialog does not.
- **6002, Commander closed or restarted:** the handles from before are dead, and a write refuses at its first call. After Commander's window, another program or another MATLAB session restarted it, `reconnect()` waits for Commander's window and takes a new handle, as `load_config` does, every 2 s for up to 30 s, and only reads. From your own code, `load_config(..., confirmed=True)` is the one way to restart Commander ([mcc.md](mcc.md)); ommm never kills it.
- **Holding after a restart.** After `load_config`, Commander comes back with Holding off and the amplifier follows it; the plan and the write say so. After someone else's restart the amplifier may still hold while Commander shows Holding off, so turn it on, `amp.enable("Holding", True)`, as your first write; ommm never turns it on itself ([quirks.md](quirks.md#holding-reads-off-after-a-restart)).
- **The race:** the few milliseconds between ommm's last read and its Set are not protected, so a click in Commander's window then is overwritten.

## Error codes

The API's `MCCMSG_ERROR_*` codes, what they mean, and what a write does with them:

| Code | Name | Seen as |
|---|---|---|
| 0 | none | a failure with no code set, whose text from Commander is `AXMCCMSG: Unexpected error code 0.`: every call after the first listing fails so with the amplifier switched off (Commander's window looks as before), and in Demo mode. `ommm.Amplifier()` still connects, since the first `FindFirstMultiClamp` answers; the next call fails at once, a write is refused, and ommm's message adds the two causes |
| 6000 | `NOERROR` | also how `FindNextMultiClamp` reports the end of the list, as a failure; ommm takes it as the end. From `FindFirstMultiClamp` ommm takes it as no amplifier, and `ommm.Amplifier()` says it found none |
| 6002 | `MCCNOTOPEN` | Commander not reachable: over SSH, elevated, or not running ([Running next to Commander](install-and-testing.md#running-next-to-commander)); also a handle from before a Commander restart, where a snapshot stops and a write refuses, each saying `reconnect()` |
| 6004 | `INVALIDPARAMETER` | returned *as the value* by a getter that does not apply in this mode or tab; in `not_applicable`, and `get()` raises `NotApplicable`. A Set or Auto that does not apply in the active mode (Rs Compensation in I-Clamp, Bridge Balance in V-Clamp) fails with it at once and changes nothing. ommm refuses those before sending; one that still comes makes a write `error` |
| 6005 | `MSGTIMEOUT` | Commander did not answer within the timeout (3 s by default): a snapshot stops there, a write is `unknown`. The Autos finish well within it, and an open Options dialog does not cause it |
| 6006 | `MCCCOMMANDFAIL` | returned *as the value* by a getter for a headstage that is not connected: headstage 2's feedback resistor, read with headstage 2 unplugged; ommm refuses a headstage that Commander lists but whose feedback resistor answers 6006 |

Other failures raise `ommm.CommanderError` with Commander's own error text and the code; in a write, a call that fails is `error`, with the code in the log.

## The log and trial records

- Every write ommm sends, and every one it refuses, is one line appended to `~/ommm-logs/<serial>.jsonl`, for headstage 2 `<serial>_headstage2.jsonl` (`log_dir=` elsewhere), from any process, with no lock: `schema` (2), `t`, `process` (`pid`, `program`), `commander` (`pid`), `serial`, `headstage`, `label`, `stem`, `mode`, `before`, `target`, `unit`, `user_value`, `after`, `also`, `outcome`, `reason`, `error_code`, `telegraph_checks`, `ommm` (`version`, `commit`, `dirty`). A step sequence logs a line per step, `set_mode` a line per `SetMode`. `plan()` and a change that needed no Set log nothing.
- Each line has the `Write`'s shape ([Outcomes](#outcomes)): `before`, `target` and `after` are the value of what `stem` names, and `also` every other change, `{name: [before, after]}`. A button's line has `None` for all three and its result in `also`; a `load_config` line has the mode and both feedback resistors in `after` and the rest of what changed in `also`. In schema 1 (ommm 0.1), a button's and a load's `after` was the snapshot diff, `{"readings": {...}, "telegraph": {...}}`: `trial_record` does not read that, and puts those changes down to `"gui"`, so restart MATLAB after updating ([Update](install-and-testing.md#update)).
- `amp.writes_since(mark)` returns the lines after byte offset `mark` and the next mark (`ommm.log.writes_since(path, mark)` for any log file); a line still being written waits for the next call. A mark that is not where a line of this log starts (one from another log, or past its end) raises `ValueError`.
- `ommm.trial_record(before, after, writes=(), previous=None)` takes two snapshots, the log lines and optionally the previous trial's `after`, and returns `before`, `after`, `changed` (before → after) and `between` (previous → before). Each changed field is `{"before", "after", "source"}`: `"ommm"`, with the log time `t`, when a write logged between the two snapshots accounts for it, else `"gui"`: Commander's window, the front panel, the oscillation killer, or a program not using ommm. A mode change accounts for every tab reading and telegraph field, since the two snapshots then read different tabs, and so does turning Mode Switching on or off when the mode changed with it. What else a write changed (`also`: a Set's other readings, a button's or a load's snapshot diff) is ommm's only at the value the write left it. A telegraph field that mirrors a reading (the mode, the gains, the lowpass filters) and an output signal's or the mode's name take that reading's source, so one change has one source: ommm sets the gain to 5, then a click sets 10, and both the gain and the telegraph's `dAlpha` are `"gui"`.

## What ommm does not do

- **No callbacks and no rules of its own** beyond Commander's: a Holding range, a Zap length or "not now" is your code before the call.
- **No judgement about the cell.** Commander's Help warns that too much Rs Compensation or Pipette Capacitance Neutralization oscillates and can kill the cell, that Buzz for too long can kill a small one, and that Pipette Offset is set before the seal. ommm checks only the vendor's ranges; the Oscillation Killer is Commander's (`enable("Oscillation Killer", True)`).
- **Nothing during acquisition:** ommm cannot see your DAQ, so it cannot tell a recording is running. Don't write while recording.
- **No mode switching from outside Commander:** ommm changes the mode only through Commander (`set_mode`). Driving it from a DAQ through the amplifier's MODE input (Mode Switching on: 0 V I-Clamp, 5 V V-Clamp), or by Commander's Auto mode switching (a Vm threshold in Options > Auto, the same checkbox), is not accounted for. With Mode Switching on, every write is refused and `state()` warns. A switch during a recording is not seen at all: a snapshot and `state()` give the output signals and scales of the mode they read, so a trial that switches and comes back shows no change in its trial record. If you switch this way, record the mode yourself; the 700B manual's way is the SYNC output set to "Mode on channel 1" (5 V V-Clamp, 0 V I-Clamp).
- **No retry or rollback** ([When something fails](#when-something-fails)), and no restart of its own: it restarts Commander only in a confirmed `load_config` (twice when the first start skips the file), never kills it, and never clicks its window (open the Pipette Offset padlock yourself).
- **No polling:** a change made in Commander's window shows at ommm's next read, and a checkbox clicked there is not telegraphed.
- **No writes in Commander's Demo mode:** every write checks the mode against the telegraph, which ommm cannot read for Demo mode's serial.
- **Not supported:** the MultiClamp 700A, and Commander's Quick Select buttons.
