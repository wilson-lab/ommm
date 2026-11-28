# Commander 2.2.2.2: behaviour to know

What MultiClamp Commander does when a program drives it through its API (AxMultiClampMsg) and listens to its telegraph, where its own documentation is silent or says otherwise. It holds for any program, ommm or not. Everything here was seen on one MultiClamp 700B, on headstage 1, and with both headstages under [Two headstages](#two-headstages). Nothing covers the 700A.

## Summary

1. The API reads and sets [the tab Commander shows](#the-api-works-on-the-tab-shown), which need not be the mode the amplifier is in. [Connecting brings the active mode's tab to the front](#what-brings-the-active-tab-to-the-front).
2. [Commander never says no to a value](#commander-never-says-no-to-a-value): off its list it takes the nearest one, past its range it takes the end, and it reports no error.
3. [The API turns on what the window greys out](#the-api-turns-on-what-the-window-greys-out): Whole Cell at 5 GΩ, Holding together with Slow Current Injection.
4. [Mode Switching flips whatever you pass it](#mode-switching-flips-whatever-you-pass-it), and the mode it leaves cannot be predicted.
5. Pipette Offset is [one per tab, with the opposite sign in I-Clamp](#one-pipette-offset-per-tab-opposite-sign-in-i-clamp). It [moves only 100 mV either side of where the last Auto put it](#pipette-offset-moves-only-100-mv-from-the-last-auto), a level nothing can read, and [Auto Pipette Offset changes the other mode too](#auto-pipette-offset-changes-the-other-mode-too).
6. [Choosing a Primary Output signal brings back that signal's own gain and filters](#a-primary-output-signal-brings-back-its-own-settings).
7. [Checkboxes clicked in Commander's window are not telegraphed](#checkboxes-clicked-in-the-window-are-not-telegraphed): a program sees them at its next read.
8. [Every Set and Auto returns when it is done](#every-set-and-auto-returns-when-it-is-done): nothing times out, not even with the Options dialog open.
9. [Seal Test and Tuning frequency are set as a period](#seal-test-and-tuning-frequency-are-set-as-a-period): send the Hertz the vendor documents and Commander keeps 2 Hz.
10. [After a restart Commander shows Holding off](#holding-reads-off-after-a-restart): restarted with no file, the amplifier still holds the command; after `load_config` it follows Commander.
11. [A start with a `.mcc` file sometimes skips the file](#closing-and-starting-commander), with no error: 4 loads in 92 came back as before the close, and a second start right after did too.
12. [With two headstages, one selection serves every program](#two-headstages): two programs at once can reach each other's headstage.

## How to read this page

- Each item says what Commander does, then, after **ommm:**, what ommm does about it, or what to do in your own code. ommm's checked writes are the Python `ommm.Amplifier`'s ([How a write works](writes.md)); every item here applies as well to any program that calls Commander's API directly.
- What is still open is under [Not seen yet](#not-seen-yet).

## Tabs and modes

### The API works on the tab shown

Commander has one tab per mode, V-Clamp and I-Clamp; I = 0 uses the I-Clamp tab. The API's Gets and Sets act on the tab Commander shows, not on the mode the amplifier is in, while `Mode` and the telegraph follow the active mode.

- **A Set lands on the tab shown.** With V-Clamp active and the I-Clamp tab shown, a Primary Output gain of 5 changes the I-Clamp tab's gain; the V-Clamp tab and the telegraph keep theirs.
- To read the other mode's settings without changing the mode, click its tab: the API then reads that tab.
- With the active mode's tab shown, a Set or Auto that does not apply in that mode fails at once with 6004 (`INVALIDPARAMETER`) and changes nothing: Rs Compensation on in I-Clamp, Bridge Balance on in V-Clamp, Irms in I-Clamp, Auto Bridge Balance in V-Clamp. With the other tab shown, a Set for that tab lands there: Bridge Balance on, with V-Clamp active and the I-Clamp tab shown, turns the I-Clamp tab's on without an error. A Get that does not apply instead succeeds and hands back the code as its value ([the snapshot](install-and-testing.md#the-snapshot)).

**ommm:** every read, snapshot and write first brings the active mode's tab to the front with `SelectMultiClamp` ([next](#what-brings-the-active-tab-to-the-front)), so it acts on the active mode's tab, and a tab clicked to look at the other mode goes back at ommm's next call. A snapshot that reads the tab shown (`snapshot(show_active_tab=False)`, as `scripts/watch.py` takes them) names a tab that disagrees with the mode in `disagreements`; `state()` then blocks, and `summary()` shows only the headstage, the mode and the `!!` lines.

### What brings the active tab to the front

- Changing the mode: the tab follows at once.
- `SetMode` to the mode Commander is already in, and clicking that mode's button.
- Connecting: `SelectMultiClamp`, on an open handle or a new one (`ommm.Amplifier()`, `reconnect()`), brings the active mode's tab to the front in V-Clamp, I-Clamp and I = 0. The tab is in front when the call returns, so a snapshot taken at once reads the active tab. It takes 3 ms with the other tab shown and 0.2 ms with the active one.
- Turning Mode Switching off need not: it can leave I = 0 active with the V-Clamp tab still shown.

**ommm:** `SelectMultiClamp` on the headstage found at connect, before every read, snapshot and write. Listing the amplifiers (about 1 s, nearly all of it `FindFirstMultiClamp`) happens only at connect and `reconnect()` ([Connecting and restarting](#connecting-and-restarting)).

### Mode Switching flips whatever you pass it

- `SetModeSwitchEnable`, Commander's Mode Switching checkbox, toggles whatever its argument: `Set(True)` with it off turns it on, and a second `Set(True)` turns it off. So read `ModeSwitchEnable` first, and call it only to change Mode Switching.
- With Mode Switching on, the mode buttons grey out and the mode follows the amplifier's mode input, which floats with nothing connected to it. What the mode does then cannot be predicted: turning Mode Switching on and off again, starting in V-Clamp, has ended in I-Clamp and in I = 0.
- While Mode Switching is on, `SetMode` is ignored, and output signal ids land on the other mode's list (both outputs became Membrane Potential).

**ommm:** refuses every write while Mode Switching is on but `enable("Mode Switching", False)`, which it sends only when Mode Switching is on. After it goes off, check the mode.

### Mode changes show at once

`GetMode`, the telegraph and the tab shown all have the new mode at the first read after `SetMode` returns, between V-Clamp, I = 0 and I-Clamp. `SetMode` itself takes 40-230 ms. Other programs (ACQ4, MIES) wait 100-500 ms after a mode change for the amplifier's outputs to settle; how long that takes is not yet checked.

**ommm:** a read right after a mode change needs no wait.

## Values

### Commander never says no to a value

A value off Commander's list becomes the nearest one, and a value past the range becomes its end, with no error:

| Set | Reads back |
|---|---|
| Primary Output gain 7, 9 | 5, 10 |
| Primary Output gain 0.5, 5000 | 1, 2000 |
| Primary Output low-pass 1.05, 1.15 kHz (Bessel) | 1, 1.2 kHz |
| Primary Output low-pass 2.1 kHz, a Butterworth-only cutoff, with Bessel | 2.2 kHz |
| Zap duration 300, 400 µs | 200, 500 µs |
| Zap duration 100 ms | 50 ms |
| Holding ±2 V (V-Clamp) | ±1000 mV, less the Pipette Offset level (below) |

**Holding's V-Clamp range moves with the Pipette Offset.** Holding plus the level the last Auto Pipette Offset found ([below](#pipette-offset-moves-only-100-mv-from-the-last-auto)) stays within ±1000 mV, so the end on the level's side comes in by the level:

| Level (V-Clamp) | Set | Reads back |
|---|---|---|
| +39.3 mV | +2 V, −2 V | +961.0 mV, −1000 mV |
| −28.6 mV | +2 V; −0.98 V, −1.2 V, −2 V | +1000 mV; −971.0 mV each |
| −86.8 mV | +2 V, −2 V | +1000 mV, −913.0 mV |

Holding sits on top of the zero the Pipette Offset sets. No function reads that level, so a program cannot know the range near ±1000 mV.

**ommm:** refuses a value outside Commander's documented range or off its list, before sending, and reads every write back: a value Commander kept otherwise is a `mismatch` ([Outcomes](writes.md#outcomes)).

### Values come back a little different

Commander keeps values on its own steps, so a readback seldom equals the Set exactly: Holding 12.3456 mV reads 11.995 mV and −20 mV reads −20.013 mV; Cp Fast τ 1.5 µs reads 1.494 µs; Cp Slow τ 100 µs reads 102.6 µs; Cp Slow 0.5 pF reads 0.476 pF (steps of 3/63 pF); Whole Cell 10 MΩ reads 10.007 MΩ; Rs Compensation Bandwidth 5 kHz reads 4.97 kHz; Bridge Balance 10 MΩ reads 9.77 MΩ; an I-Clamp Pipette Offset of +5 mV reads +4.9997 mV; Seal Test amplitude 10 mV reads 9.99687 mV (steps of 31.3 µV); Tuning 10 pA reads 10.0282 pA at 5 GΩ (steps of 31.3 fA). It also stores them as float32 ([the snapshot](install-and-testing.md#the-snapshot)).

- After an Auto Pipette Offset, V-Clamp Holding and the I-Clamp Slow Current Injection level read slightly off what was set (0 mV reads −0.28 µV, −51 mV reads −51.006 mV) until the Pipette Offset is set again.

**ommm:** a readback within the control's resolution (in the settings table) is `adjusted`, beyond it a `mismatch`.

### Seal Test and Tuning frequency are set as a period

`SetTestSignalFrequency` takes the period in seconds, though the vendor's documentation says Hertz, while `GetTestSignalFrequency` reads Hertz. Sent 50, 100 or 200 (meant as Hz), Commander keeps 2 Hz (a 50 s period is past its longest); sent 0.01 it keeps 100 Hz, and 0.001 1000 Hz. Seal Test (V-Clamp) and Tuning (I-Clamp) share it.

- Commander keeps one of 2, 5, 10, 20, 50, 60, 100, 200, 500 and 1000 Hz. A frequency between them becomes the step whose period is nearest: 3, 7, 15, 30, 70, 150, 300 and 700 Hz become 5, 10, 20, 50, 60, 200, 500 and 1000 Hz; 1 Hz becomes 2 Hz and 2000 Hz 1000 Hz.

**ommm:** sends the period (`set` takes Hertz for it, as `get` gives), and refuses a frequency off that list, naming the two either side of it.

### Rs Compensation: Prediction carries Correction

With the link between Prediction and Correction on: Correction 10 % with Prediction at 0 % stays 0 %; Prediction 10 % takes both to 10 %; Correction 0 % then stays 10 %; Prediction 0 % takes both to 0 %. The link is a button on the panel that the API can neither read nor set. What Correction does with the link off is not yet checked.

**ommm:** cannot tell whether the link is on. A Correction that follows Prediction reads back as a `mismatch` that names the link.

### The API turns on what the window greys out

- **Whole Cell at 5 GΩ.** The window offers Whole Cell only with the 50 and 500 MΩ feedback resistors. At 5 GΩ, `SetWholeCellCompEnable(True)` turns it on, and Auto Whole Cell runs and turns it on, both without an error. On a model cell of 33 pF behind 10 MΩ it found 57.4 pF and 1.42 MΩ, far from both.
- **Holding and Slow Current Injection.** In I-Clamp they exclude each other, and the window greys one out while the other is on. The API turns both on, in either order, without an error; the panel then shows both checked and greyed, so the window can turn neither off, while the API can.
- Holding is taken while its checkbox is off, and applied when the checkbox is turned on.

**ommm:** refuses what the window greys out: turning on I-Clamp Holding with Slow Current Injection on (or the reverse), and Whole Cell, its values and Auto Whole Cell at 5 and 50 GΩ, where the window greys out the whole panel ([Checkboxes, buttons and the mode](writes.md#checkboxes-buttons-and-the-mode)).

### Whole Cell at 500 MΩ on the model cell

At 500 MΩ, where the window offers it, Auto Whole Cell on a PATCH-1U model cell at CELL (33 pF behind 10 MΩ), with Cp Fast and Cp Slow at 0, turns Whole Cell on with 12.23 pF and 12.85 MΩ, as the API, the telegraph and the window all show. After Auto Cp Fast (3.9 pF) it finds 30.0-30.5 pF and 11.2 MΩ, the same from the API and from the window's own buttons: the 12 pF was Commander's answer with Cp Fast at 0, not the API's. Rs Compensation then goes on at Prediction 50 %, Correction following through the link, bandwidth 10 kHz, with no oscillation warning or dialog; with Disable/Reduce if Oscillation Detected on, Correction stepped 10 → 100 % in 2 s steps took every step, Rs Compensation stayed on at 100 % and nothing acted (twice at CELL; once at PATCH with Whole Cell on at 33 pF / 10 MΩ, where each step kicked both outputs, ±0.3 V at 100 %, and the primary's noise band widened about five times at 100 %; a 10 kS/s DAQ behind the 8 kHz Bessel cannot show an oscillation above about 5 kHz, so that band may be one, aliased, that Commander, which watches the headstage before the filter, judged below its threshold). What makes the killer act is still not seen; a cell with real access resistance may.
- A Set of Whole Cell Cm to 33 pF at 500 MΩ, with Whole Cell off, came back `mismatch: Commander kept 32.9632 pF` (the loaded file's value); whether Commander ignores that Set while Whole Cell is off, or snapped to a grid, is not known.

**ommm:** reports what Commander found; it knows nothing about the cell.

### A Primary Output signal brings back its own settings

In V-Clamp, choosing another Primary Output signal brings in that signal's own gain, low-pass filter, AC (highpass), Scope filter, Output Zero and Leak Subtraction resistance, and choosing the first signal again brings its values back; the Secondary Output gain stays as it is. Whether I-Clamp does the same, and whether Bridge Balance (which a saved `.mcc` also keeps per signal) comes back too, is not yet checked.

- A signal change takes 0.4-0.5 s.
- Output Zero's API value reads 10 times larger below a Primary Output gain of 10: 1.0038 mV set at gain 10 reads 10.038 mV at gains 5, 2 and 1, and 1.0038 mV again at 20 and 50. Commander's documented range is ±2900 mV below gain 10 and ±290 mV from 10.

**ommm:** a snapshot after a signal change shows the values it brought back.

## Pipette Offset

### One Pipette Offset per tab, opposite sign in I-Clamp

- V-Clamp and I-Clamp each have their own Pipette Offset, and I = 0 uses I-Clamp's. Setting one leaves the other as it was.
- In I-Clamp and I = 0 the API's value is the negative of the window's: +5 mV through the API shows −5.00 mV. In V-Clamp the two agree.

**ommm:** `get` and `set` take Pipette Offset with the window's sign in every mode; a snapshot records the API's value, so its I-Clamp Pipette Offset has the opposite sign to the window's; the summary box shows the window's sign.

### Pipette Offset moves only 100 mV from the last Auto

- Commander holds a Pipette Offset Set within ±100 mV of the level the last Auto Pipette Offset found, and a Set past that ends at the edge, without an error: after Autos that found −193.3 mV and −269.7 mV, a Set of 0 mV reads −93.3 mV and −169.7 mV.
- The level also narrows V-Clamp Holding's range ([above](#commander-never-says-no-to-a-value)).
- No function reads that level. A Set, a mode change or a tab click does not move it; another Auto does.
- So after an Auto, 0 mV may be out of reach. Pressing Auto again until its result is within 100 mV of 0 brings it back in reach.

**ommm:** a snapshot records the offset, never the level. A Pipette Offset Set that Commander clipped reads back as a `mismatch` that names the hold.

### Auto Pipette Offset changes the other mode too

- **In V-Clamp** it also sets the I-Clamp Pipette Offset and its ±100 mV range: V-Clamp went +5 → −183.6 mV and I-Clamp +10 → −113.2 mV (API sign). It also moves I-Clamp's Slow Current Injection level by a few µV, and leaves V-Clamp's Holding reading a few tenths of a µV, which a Set of Holding 0 does not clear and the next Pipette Offset Set does.
- **In I-Clamp** it changes the V-Clamp side too, and how depends on the load. On a model cell it takes both tabs' offsets to about what it found (V-Clamp −21.5 → −16.5 mV, I-Clamp −10.4 → −16.5 mV, API sign) and leaves Holding alone. With nothing attached it changes no I-Clamp reading, but turns V-Clamp's Holding on at the old V-Clamp offset and takes that offset to 0, or as near as its ±100 mV range allows: an offset of −183.6 mV became Holding −184.0 mV, on, with the offset at −83.6 mV.
- On a model cell, repeated Autos in V-Clamp find the same offsets; with nothing attached the level wanders from Auto to Auto.
- At BATH (the model cell's 10 MΩ, no real offset), from +5 mV in V-Clamp and +10 mV in I-Clamp: the V-Clamp Auto took both tabs to about 0 (−0.33 and +0.35 mV) and left Holding alone; the I-Clamp Auto then changed only I-Clamp's (+0.30 mV). After both, V-Clamp's padlock was locked and I-Clamp's open.
- It takes 1.1-1.8 s.

**ommm:** `press("Auto Pipette Offset")` reports what changed on the active mode's tab, and its `reason` says the other tab changed too; read the other mode when you next switch to it.

### The padlock

- After Auto Pipette Offset in V-Clamp the padlock shows locked on both tabs, and the window's Auto is greyed.
- Through the API a Set, and another Auto, work with it locked. The API can neither read nor open it; a click in the window opens it.

**ommm:** never clicks Commander's window: open the padlock by hand to use the window's Auto again.

## Timing

### Pulse, Zap, Buzz and Clear act after the call returns

On the DAQ (PATCH-1U model cell at PATCH): each button's action starts within 0.1 s of the call. Pulse (10 mV, 10 ms) and Zap (0.5 ms) are over before the call returns; a longer Pulse (to 500 ms) or Zap (to 50 ms) is not yet checked. Buzz (1 ms) and Clear + and Clear − drive the primary output to its rail for about 0.4 s after the call, which returned in 40-200 ms ([below](#every-set-and-auto-returns-when-it-is-done)). A mode change (V-Clamp → I-Clamp through I = 0, 0.36 s) shifts the outputs by their new signals' levels and nothing more.

**ommm:** a `press` returns when Commander's call does, not when the action ends: wait about 0.5 s after Buzz or Clear before recording.

### Every Set and Auto returns when it is done

- A Set has its new value in place at the first read after the call returns: Primary Output gain and low-pass, Holding and its checkbox, Mode, Cp Fast and Cp Slow, Whole Cell, Rs Compensation, the oscillation killer, Pipette Capacitance Neutralization, Bridge Balance.
- Most Sets take 10-100 ms. Slower: Mode 40-230 ms; the Primary Output gain about 0.2 s for the active mode's Membrane Current (V-Clamp) or Membrane Potential (I-Clamp), and 15-30 ms for Pipette Potential, or on the tab not active; changing the Primary Output signal 0.4-0.5 s. A value that is only stored takes about 1 ms: Holding with its checkbox off, Rs Compensation %, Zap duration, Output Zero.
- The Autos block until done, and their result is final at the first read after they return: Auto Output Zero 0.20-0.24 s, Pipette Offset 1.1-1.8 s, Cp Fast 1.2-1.8 s, Cp Slow 0.71-0.73 s, Leak Subtraction 2.2 s, Bridge Balance 0.63-0.66 s, Whole Cell 0.88-1.5 s. None reaches the DLL's 3000 ms default timeout, and with 10000 ms they are the same: no 6005 (`MSGTIMEOUT`). Other programs (MIES, Clampwise) report that with a real cell they can outlast 3 s; that is not yet checked.
- The calls for Zap, Pulse, Buzz and Clear return in 0.17-0.19 s, 0.08-0.21 s, 0.04-0.06 s and 0.04-0.07 s; which actions are over by then: [above](#pulse-zap-buzz-and-clear-act-after-the-call-returns).
- **The Options dialog does not block the API.** With it open, a Get answers at once (0.4-17 ms; 0.1 ms with it closed), and a Set is taken (221 ms) and kept after the dialog closes: no 6005. Options has Close and Help but no OK or Cancel.

**ommm:** reads each write back right after it returns, with no wait. A 6005 stops a snapshot and a write, which is logged `unknown` and never sent again.

## Telegraph and meters

### Checkboxes clicked in the window are not telegraphed

Commander telegraphs the mode, the output signals, their gains, low-pass filters and scale factors, Whole Cell capacitance and External Command Sensitivity.

- A telegraph connection held open gets one packet when it opens and one unasked per mode-button click, 45-120 ms after it, carrying the new mode, output signals, gains and External Command Sensitivity.
- No packet comes for a checkbox clicked in the window: Holding, Seal Test, Tuning, Tau x20, Rs Compensation, Disable if oscillation detected, Output Zero, Leak Subtraction, Slow Current Injection, Pipette Capacitance Neutralization, Bridge Balance. Each shows at the next API read. Whole Cell, and gains, filters and values changed in the window: [not seen yet](#not-seen-yet).
- Seal Test (V-Clamp) and Tuning (I-Clamp) are one API setting, `TestSignalEnable`; Tau x20 multiplies the Cp Slow τ the API reads by 20 (10 µs → 200 µs).
- The telegraph's signal fields are stale from Commander's start until each mode's output signals are set; ommm re-selects them before a write ([Before every write](writes.md#before-every-write)).
- An external command signal's scale is 1 / the External Command Sensitivity, so the output gives back the command input's volts: External Command Current reads 25 V/nA at 40 pA/V. Every other signal's scale is the [table's](install-and-testing.md#output-scales-at-gain-1).

**ommm:** never polls: a change made in the window is seen at the next read.

### Meter values change meaning

The four meter values, `GetMeterValue` with index 0 to 3, which ommm's `get` reads as `MeterValue1` to `MeterValue4`, the names a snapshot records them under:

| Meter | Normally | With Resistance on | With Irms on (V-Clamp only) |
|---|---|---|---|
| 0 | membrane potential, V | resistance, Ω | membrane potential, V |
| 1 | membrane current, A | membrane current, A | current RMS, A |
| 2, 3 | headstage 2's membrane potential, V, and current, A; 0 with headstage 2 unplugged | | |

- The meaning changes about 0.5 s after the Set; a read at once still gives the old one. On a 10 MΩ load the resistance reads 0 at 2 s and a valid value at 4 s; with nothing attached it is noise, once even negative.
- When Commander's meter shows OVLD, the API gives the number Commander shows, never OVLD (the manual says overload is not visible to the API): at 5 GΩ on a model cell's 510 MΩ, the V-Clamp Resistance meter wandered over 5·10⁷ to 2·10¹⁰ Ω.
- Irms in I-Clamp fails with 6004.
- The Resistance meter applies its own test pulses.

**ommm:** a snapshot records `MeterResistEnable` and `MeterIrmsEnable` beside the meter values, and `trial_record` leaves the meters out of `changed`. `get("MeterValue2")` raises `NotApplicable` in V-Clamp while Irms is on, but not in I-Clamp or I = 0.

## Connecting and restarting

- `FindNextMultiClamp` reports the end of the list as a failure with 6000 (`NOERROR`) ([error codes](writes.md#error-codes)).
- `FindFirstMultiClamp` takes about 1 s every time, and `FindNextMultiClamp` 0.1 ms, so listing the amplifiers and selecting one (ommm's `select()`) takes 1.0 s, while `SelectMultiClamp` alone takes 0.1-8 ms.
- Commander's hidden window, "Invisible MultiClamp Startup Window", is found by its title, not as a class name. Other programs (Clampwise, MIES) take it as "Commander is running"; it goes as Commander exits and comes back before the API answers ([below](#closing-and-starting-commander)). ommm looks for it before every write and refuses at once without it.
- Commander answers only programs in its own desktop session at its own privilege level; over SSH the API fails with 6002 ([Running next to Commander](install-and-testing.md#running-next-to-commander)).
- Killed with `taskkill /F`, Commander comes back with older settings: it saves them only when closed from its window. The window has no File menu: closing by hand is its X.
- After Commander restarts every open handle is dead (6002); when the API answers again: [below](#closing-and-starting-commander).
- **With the amplifier switched off** and Commander left running, its window looks as before (the meters frozen, nothing greyed, no dialog), and the API's first `FindFirstMultiClamp` still lists the headstage; every call after it fails at once with Commander's text `AXMCCMSG: Unexpected error code 0.`, a failure with no code set. The same in Demo mode, once `FindFirstMultiClamp` has listed the `Demo` headstage. **ommm:** `Amplifier()` still constructs; a snapshot and a read raise `CommanderError` at once with the two causes added, and a write is refused.
- **With headstage 2 unplugged,** `FindFirstMultiClamp` lists headstage 1 alone, and `SelectMultiClamp` on headstage 2 fails with 6002 (`MCCNOTOPEN`), the code for Commander not running, while headstage 1 goes on answering. **ommm:** takes that 6002 as headstage 2 not connected, so `load_config` plans as for one headstage; `Amplifier(headstage=2)` refuses, finding no headstage 2.
- **Commander remembers its last device.** Started from its icon with the amplifier off it asks, with Demo the only choice; closed in Demo, the next plain start opens in Demo even with the amplifier on. Started with `/S<serial>` (as `load_config` starts it) it opens on the amplifier, and the next plain start does too.
- The vendor's PDF gives `SetHolding` a BOOL; the header's double is right. BOOL is a 4-byte int, and, as Clampwise's authors report, a function called without declared argument types can cut a 64-bit handle short.

**ommm:** takes every function's types from the header (the header tests check each one); its 6002 message names the likely cause; `reconnect()` makes new handles after a restart, in Python and MATLAB.

## Closing and starting Commander

What a close (WM_CLOSE, `ommm.process.quit_commander`) and a start (`MC700B.exe /S<serial> [/C<file>]`) do:

- **Closing:** Commander closes without asking, even when it was started with a file and changed since. It has exited 1.2-1.5 s after `quit_commander` is called, which reads the serial first (about 1 s).
- **While closed:** the hidden window is gone at once; a Get on a handle from before fails with 6002 in 0.1 ms; a new handle fails with 6002 after 1.0 s; a telegraph read gets nothing.
- **Starting,** timed from when `MC700B.exe` is started: the hidden window is back after about 1.5 s, 1.5 s or more before the API answers. The API answers 4.4-10.1 s after the start, and a snapshot has settled 11-14 s after it. The first telegraph read, once the API answers, gets a packet within 18 ms with the mode and both output signals the API reads, with no re-opening.
- **The outputs through a close and start** (Membrane Current and Membrane Potential, in V-Clamp with Holding off at 0 mV, Seal Test off, Pipette Offset 0 and no compensation): neither output changes level; the secondary output shows spikes of 10-25 mV, 0.1-0.3 ms, at Commander's exit, during its start and once about 5 s after. With Holding on, see [next](#holding-reads-off-after-a-restart).
- **A restart does not always bring everything back.** A restart with no file sometimes comes back with I-Clamp values changed: Secondary Output Auxiliary 2 (was Membrane Current) and its gain, the Slow Current Injection level 0, Pulse 0 pA and 100 µs, Pipette Capacitance Neutralization off; the telegraph's secondary output is then stale at first. The V-Clamp tab comes back unchanged. Why is not known. Started with a whole file, those values come back as the file holds them.
- **A `.mcc` file holding one key is refused:** Commander shows the file's path and "not a valid MultiClamp configuration file" with an OK button, stays at its "Connecting to MultiClamp 700B device" splash, and the API does not answer (6002) until OK is pressed; then every reading and every Options page is as before that start. Whole files saved by Commander load; which smaller files Commander takes is not yet checked.
- **A start sometimes skips its file.** In 4 of 92 loads Commander started with `/C<file>`, answered as usual and did not apply the file: the V-Clamp feedback resistor stayed where it was before the close (5 GΩ against the file's 50 GΩ three times, 50 GΩ against 5 GΩ once), Cp Fast and Cp Slow kept their values from before the close, Pulse came back at 0 and 100 µs where the file holds 5 mV and 0.5 ms, and the I-Clamp Secondary Output came back Auxiliary 2 where the file and the state before had Membrane Current. Each was a load to or from 50 GΩ (4 of 42 such loads; none of 50 others). The one time the same file was started again at once, that start skipped it too, in the same way; the next load, of another file, took. The API answered 7.0-7.1 s after each of those starts, against 8.5-10.1 s for most loads, but 22 loads that changed a feedback resistor and took answered as fast, so the time does not tell. What differs those times is not known. Pipette Offset, which no file holds, reads 0 in a snapshot right after every load, skipped or not, so it does not tell either.
- **A load sets more than its file holds, and all of what it holds.** A load of a Commander-saved file turns I-Clamp's Bridge Balance on, though no key in the file names it; Pipette Offset, Mode Switching and the meter checkboxes stay as they were. Every value the file holds comes with it, the Options pages' too: an older saved file, edited only in its feedback resistor, brings back its own primary filter, Pulse, Mute, I-Clamp Audio signal and Auto page Vm threshold. The Advanced page's Automatic Bridge Balance box is greyed after some loads and active after others; which key sets it is not known.

**ommm:** `quit_commander` waits up to 30 s and never kills; `wait_for_api` gives up after 30 s, three times the slowest start seen, and `load_config` then names a dialog as the likely cause. `load_config` loads whole files only, refusing one without `[MC700_GLOBAL]`, the mode or either feedback resistor before Commander is closed, so the file sets every value it holds; it then selects the active mode's output signals again and checks the mode, the feedback resistors and, on the active mode's tab, Pulse, Cp Fast and the other values that read back as the file holds them against the file. A start that fails that check is logged as a `mismatch`, and `load_config` closes Commander and starts it with the file once more; only a second start that fails it too makes the load a `mismatch` ([mcc.md](mcc.md#what-a-load-does)). On the amplifier the check flagged no load that took (22 loads of three Commander-saved files), and caught the one skip among them; its second start skipped too, so that load was a `mismatch`: load again. The other tab is not read, so code that relies on the other mode's output signals selects them after a change to that mode.

### Holding reads off after a restart

With V-Clamp Holding on (−60 mV, feedback resistor 5 GΩ), Commander closed (WM_CLOSE) and started again with no file:

- **The amplifier keeps holding.** The command and the current stay flat before the close, through the 6-7 s without Commander and after its API answers.
- **Commander comes back with Holding off.** Right after the restart the API reads the Holding checkbox off, its value still −60 mV, while the amplifier holds −60 mV. Commander's window and a snapshot then say Holding is off when it is on; Commander's meters, which show the amplifier and not the checkbox, read −60.0 mV. The amplifier holds until the next mode change; whether any write ends it sooner is not yet checked.
- **Closed and started by hand** (the X, then the icon) with Holding on at −20 mV, the DAQ recording (three runs): the amplifier held −20 mV through the 5-10 s without Commander, through `reconnect()`, through the first write (`set("Holding", -20, "mV")`, which selects the output signals again) and through `enable("Holding", True)`; nothing moved. Commander came back reading Holding −20 mV with its checkbox off in two runs and on in the third. In that third run the amplifier had been at −16.2 mV with Holding −20 mV on, and went to −20.3 mV as Commander started, 5 s after the close: Commander's start applied its own Holding. Where the 4 mV came from is open.
- **After `load_config`, the amplifier follows Commander.** With V-Clamp Holding on at −20 mV, after `load_config` with `vclamp_5gohm.mcc` (`src/ommm/examples/mcc/`), Commander comes back with Holding off at the file's level, 0 mV, and right after the load, which also selects the output signals again, Commander's meters read about 0 mV and 0 pA. Whether the file's start or the first write moved the amplifier, and what it held in between, is not yet checked.

**ommm:** with Holding on, `load_config`'s plan says that Commander comes back with it off, and its `Write`'s `reason` after the load says Holding was on before and reads off now: turn it on again, or set Holding to the old level first when Commander came back at another. It turns Holding on by itself neither then nor after `reconnect()`, which cannot know what Holding was before someone else's restart: then turn it on, `enable("Holding", True)`, as your first write. Whether ommm's own first write after a start, which selects the output signals again, moves the amplifier first is [not seen yet](#not-seen-yet). The fake Commander turns V-Clamp Holding off at each start: at its level with no file, and at 0 V with one. Whether I-Clamp Holding does the same is not yet checked.

## Two headstages

Seen with headstage 2 plugged in and nothing on it, beside headstage 1 on a model cell.

- **One selection for all of Commander.** `SelectMultiClamp` sends every later Get, Set and button to the headstage selected, from every handle and every program: the selection is Commander's, not the handle's or the process's. A process that selected headstage 1 read headstage 2's gain and Holding once another process had selected headstage 2.
- **Commander shows one of four tabs,** each headstage's V-Clamp and I-Clamp. Selecting a headstage brings its active mode's tab to the front, whichever tab was shown before.
- **Writes stay on their headstage.** Holding, a gain and a mode change on one leave the other's readings and telegraph as they were.
- **Some names belong to a headstage, whichever is selected:** `FeedbackResistorVC1`/`IC1` read headstage 1's and `VC2`/`IC2` headstage 2's, and the four meter values read the same with either selected ([Meter values change meaning](#meter-values-change-meaning)).
- **Each headstage telegraphs** with its own channel, `uChannelID` 2 for headstage 2.
- **A file saved with both** holds headstage 2's sections beside headstage 1's, the same names with `CHANNEL2` ([mcc.md](mcc.md#the-files-format)).
- **A load restarts Commander for both headstages,** and both come back with Holding off. A file with headstage 1's sections alone leaves headstage 2's mode and feedback resistor as they were, turns its Holding off and takes its Primary Output gain to 1.

**ommm:** each Amplifier selects its headstage before every call, so two called from one thread of a program take turns. Two programs at once can still reach each other's headstage between a select and the calls after it: with both headstages in use, run one program on Commander. `load_config` refuses while the other headstage holds a level, unless `release_other_headstage=True`, and says to check a headstage the file has no settings for ([mcc.md](mcc.md#two-headstages)).

## Not seen yet

What other programs report and is not yet seen here, and what is still open:

- **Two headstages:** whether a command on one headstage shows on the other's outputs, and whether [the API works on the tab shown](#the-api-works-on-the-tab-shown) on headstage 2 as on headstage 1.
- **External Command Sensitivity reading 0 in V-Clamp or I-Clamp:** MIES and ACQ4 report this as a Commander fault, cleared by resetting Commander; in I = 0 it is 0 by design. **ommm:** `state()` lists a 0 outside I = 0 as a problem.
- **The primary filter type** (Bessel or Butterworth) has no API getter or setter; it is chosen in Options → General, one per mode. Still open: which `.mcc` key holds it, and how [off-list cutoffs](#commander-never-says-no-to-a-value) snap with Butterworth.
- **Commander's other dialogs** (the Reset to Program Defaults confirmation, a second Commander starting, the oscillation warning): whether they block the API.
- **`FindFirstMultiClamp` with no 700B on:** what it answers when Commander lists no amplifier. The fake answers 6000, as `FindNextMultiClamp` does at the end of the list.
- **Demo mode's telegraph and its other channels:** in Demo the API answers only the first `FindFirstMultiClamp`, which lists one headstage, serial `Demo` ([Connecting and restarting](#connecting-and-restarting)); inferno's authors report `Demo1` and `Demo2` too. Whether Demo sends a telegraph is open; the amplifier's packets are 256 bytes, version 14 (before version 7 they were 128 bytes). **ommm:** a snapshot whose serial starts with `Demo` is marked `demo` and has no telegraph; none has been taken, since Demo answers no snapshot.
- **A held command through a close and start with compensation on, or with a file:** what the outputs do with Whole Cell or Rs Compensation on, and through a load while Holding is on.
- **A checkbox clicked in the window** while a program watches: a value typed in the window commits as soon as its box loses focus, which any command run from MATLAB causes, and the box then follows an API write at once; a gain or filter changed in the window shows in the API and the telegraph within 0.5 s, and a Holding value in the API (the telegraph has no Holding). Whether a checkbox click shows the same way is not yet watched.
