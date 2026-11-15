# Settings files and `load_config`

Some of Commander's settings have no API function: the feedback resistor and the rest of the Options dialog (External Command Sensitivity, the primary filter type, Sync Output, the Auto, Advanced and Audio pages), the meter assignment, the SoftPanel and the Rs Compensation link. Commander reads them from a `.mcc` settings file as it starts, so ommm's one route to them is `load_config`: close Commander, start it again with a file, check what came up. One MultiClamp 700B; with two headstages a load reaches both ([Two headstages](#two-headstages)).

## Change the feedback resistor

1. In Commander, Save Configuration (F5) to any file: it saves the setup as it is now.
2. `plan = amp.load_config(file, changes=[("Feedback Resistor", 500, "MΩ", "V-Clamp")])`, then `print(plan.reason)`. This sends nothing.
3. The same call with `confirmed=True` does it, in about 15 s; about 30 s when Commander's first start skips the file and ommm starts it once more ([What a load does](#what-a-load-does)).

Everything else comes back from the file as saved. The plan's reason, on [the fake](install-and-testing.md#the-fake) with `synthetic.mcc`, whose copy goes to the fake's temporary log folder (on the amplifier, `~/ommm-logs/mcc/`):

```text
Feedback Resistor (V-Clamp) 5 GΩ → 500 MΩ; the mode stays V-Clamp; Feedback Resistor (I-Clamp) stays 5 GΩ. Commander closes and starts again with .../ommm-fake-5c1e9a07/mcc/20261023T195520_synthetic_vc-feedback-resistor-500-mohm.mcc, about 15 s without Commander; every handle on it dies. The file also sets everything else it holds: Holding, compensation and the output signals (set those after with set and enable) and the Options pages (only another file changes those).
```

## What a load does to the cell

- **Commander is gone while it restarts**, and nobody can use its window meanwhile. This Amplifier, in Python or MATLAB, takes the new Commander; every other program calls `reconnect()`.
- **The outputs:** with no command applied (V-Clamp, Holding and Seal Test off, Pipette Offset 0), a restart shows no level change on either output, and the secondary shows spikes of 10-25 mV lasting 0.1-0.3 ms. With V-Clamp Holding on, a restart with no file does not move the command or the current, before, while Commander is gone or after. No measurement covers what a load with a file does to the outputs while Holding is on, or any restart with compensation on: do not load with a cell you want to keep.
- **Holding:** Commander comes back with Holding off at the file's level, and the amplifier follows it; the plan and the write say so ([Holding after a restart](writes.md#when-something-fails)).
- **The file sets every value it holds**, the Options pages included, and a load also turns I-Clamp Bridge Balance on.
- **A changed I-Clamp feedback resistor scales I-Clamp External Command Sensitivity with it**: 40 pA/V at 5 GΩ, 400 pA/V at 500 MΩ, and every DAQ current command scales with it.

## Your own file

Save it from Commander with the setup you want (Save Configuration, F5), in any folder and under any name: ommm loads a copy. Plan the load with `load_config(file)`, then load it with `confirmed=True`; afterwards set Holding and the rest with `set` and `enable`. After you change Commander's setup, save the file again, or a load brings its old values back.

The details: [The file](#the-file) · [An Options-page setting](#an-options-page-setting) · [What a load does](#what-a-load-does) · [Every refusal](#every-refusal) · [When something fails](#when-something-fails) · [The file's format](#the-files-format)

## The file

- **A whole file Commander saved**, with its Save Configuration button (F5), which saves every control setting. Set Commander up as you want to start a recording, save it once, and load it from then on.
- **Not a partial file.** Commander refuses a file holding one key with a dialog, "This file is not a valid MultiClamp configuration file", and answers nothing until OK is pressed. `load_config` refuses a file without the `[MC700_GLOBAL]` section every saved file starts with, or without the Amplifier's headstage's mode (`MODE_SLCT`) or either tab's feedback resistor (`ELCTRD_HSTAGE_RST_RNG`), so such a file never reaches Commander.
- **The file sets every value it holds**, not only what you change: the mode, the feedback resistors, Holding, Pipette Capacitance Neutralization, Whole Cell, Rs Compensation, the output signals, gains and filters, and the Options pages. A file you edit by hand or by script brings back all its other values too, so save the file again after changing Commander's setup. A saved file does not hold Pipette Offset, Mode Switching, the meter checkboxes or the Pipette Offset padlock, and a load leaves them as they were. It holds no Bridge Balance checkbox either, yet a load turns I-Clamp's Bridge Balance on.
- **Anywhere, any name.** ommm starts Commander with a copy in `~/ommm-logs/mcc/` (the Amplifier's `log_dir`), named by the time, the file's name (spaces made `_`, since Commander cannot take a path with a space) and each change: `20261026T142052_vclamp_5gohm_vc-feedback-resistor-50-gohm.mcc` is that file with the V-Clamp feedback resistor set to 50 GΩ. The plan's reason and the load's final reason name the copy's full path; the copy is the record of what was loaded.
- **Examples:** `src/ommm/examples/mcc/` (`ommm.EXAMPLES / "mcc"`) holds three files Commander 2.2.2.2 saved from one setup, one per mode it starts in: `vclamp_5gohm.mcc`, `iclamp_5gohm.mcc` and `i0_5gohm.mcc` (`MODE_SLCT` 0, 1 and 2; nothing else differs). The setup: Feedback Resistor 5 GΩ in both modes; V-Clamp primary Membrane Current at gain 2 and 8 kHz Bessel, secondary Membrane Potential at gain 5; I-Clamp primary Membrane Potential; Holding off. Use one as a start only if its setup suits your recording; better, save your own (F5). ommm itself never saves one.
- <a id="try-it-without-commander"></a>**Try it without Commander** (a Mac, say): on the fake, `synthetic.mcc` (in `src/ommm/examples/fake/`) plans and loads like a saved file.

  ```python
  import ommm

  fake = ommm.EXAMPLES / "fake"
  amp = ommm.Amplifier(fake=fake / "vclamp.json")
  plan = amp.load_config(fake / "synthetic.mcc", changes=[("Feedback Resistor", 500, "MΩ", "V-Clamp")])
  done = amp.load_config(fake / "synthetic.mcc", changes=[("Feedback Resistor", 500, "MΩ", "V-Clamp")], confirmed=True)
  ```

  In MATLAB, from the clone's `src/ommm/examples/fake/`: `a = ommm.Amplifier(Fake="vclamp.json")`, then `a.load_config("synthetic.mcc", Changes={"Feedback Resistor", 500, "MΩ", "V-Clamp"})`, and `Confirmed=true` to load.

  It is a test file in Commander's layout, a few keys of each kind, not a file Commander saved, and never for the amplifier: its first line says so, and ommm refuses it there ([Every refusal](#every-refusal)). The fake's Commander sets only the mode, the feedback resistors and the other values a load checks ([What a load does](#what-a-load-does)) that a file holds, and turns V-Clamp Holding off at each start, as Commander does; to make its next start skip the file, as Commander sometimes does, make the fake and its process by hand, in this order: `fake = ommm.testing.FakeCommander(ommm.EXAMPLES / "fake/vclamp.json")`, `ommm.testing.FakeProcess(fake, skip=1)`, then `amp = ommm.Amplifier(commander=fake)`.

## An Options-page setting

- **The feedback resistor:** `changes=[("Feedback Resistor", 500, "MΩ", "V-Clamp")]` patches it in the copy, one line per change, the rest of the file byte for byte. One per tab: 50 MΩ, 500 MΩ, 5 GΩ or 50 GΩ in V-Clamp; 50 MΩ, 500 MΩ or 5 GΩ in I-Clamp and I = 0, which share I-Clamp's. `set("Feedback Resistor", ...)` refuses and names this call. Any resistance unit works: `("Feedback Resistor", 5, "GΩ", "V-Clamp")` is `5000, "MΩ"`.
- **Anything else on the Options pages** (External Command Sensitivity, the filter type, Sync Output, the Auto, Advanced and Audio pages): set it in Commander's Options dialog, where it takes effect at once and stays across restarts, then save the file, so `load_config` brings the whole setup back. ommm patches only the feedback resistor, and a change naming anything else is refused with a pointer here; the keys found for a few others are in [The file's format](#the-files-format).
- **Quick Select** buttons are not supported: they load a file from Commander's window; load the file with `load_config` instead.

## Two headstages

- A load closes Commander, so it restarts both headstages, and every handle on Commander dies: the other headstage's Amplifier needs `reconnect()`. A file holds settings for each headstage connected when it was saved.
- The plan names the other headstage, its mode and Holding. While Holding is on there it refuses, `headstage 2 holds 20 pA in I-Clamp: the load restarts Commander for both headstages, and both come back with Holding off, releasing a held cell. Turn headstage 2's Holding off first, or pass release_other_headstage=True (ReleaseOtherHeadstage=true in MATLAB)`, unless `release_other_headstage=True` (MATLAB `ReleaseOtherHeadstage=true`). Check the other headstage after the load.
- The file must hold the Amplifier's headstage's sections: headstage 2 refuses a file saved with headstage 1 alone. When the file lacks the other headstage's, the plan says to check that headstage after the load.
- The fake's Commander sets each connected headstage's mode, feedback resistors and the other values a load checks from the file, and turns V-Clamp Holding off on both.

## What a load does

`confirmed` and `release_other_headstage` are `True` or `False`: anything else is refused (`confirmed is True or False, not 1`), and raises unless `confirmed` is `False`. Without `confirmed=True`, `load_config` reads Commander, makes every check in [Every refusal](#every-refusal) and returns the plan: a `Write` with outcome `planned`, whose `reason` says what changes first, then that Commander closes and starts again with the copy, and what else the file sets ([the example above](#change-the-feedback-resistor)); a new I-Clamp feedback resistor adds that I-Clamp External Command Sensitivity follows it. `before` and `target` are the mode and both feedback resistors now and in the file, as the API reads them (`Mode` 0 V-Clamp, 1 I-Clamp, 2 I = 0; [feedback resistor indexes](install-and-testing.md#feedback-resistor-range-indexes)). It sends, writes and logs nothing.

With `confirmed=True` it plans again from fresh reads, then:

1. **A snapshot**, and the copy written to `~/ommm-logs/mcc/`.
2. **Commander closes**, as its close button closes it (WM_CLOSE), so it saves its settings; killed, it comes back with older ones, so ommm never kills it. Waits up to 30 s.
3. **Commander starts** from its install folder (`OMMM_SDK_DIR` if set) on the same amplifier, with the copy: `MC700B.exe /S<serial> /C<file>`. Waits up to 30 s for the API ([how long it takes](quirks.md#closing-and-starting-commander)).
4. **The new handle.** Every handle on Commander from before is dead (6002): this Amplifier, in Python or MATLAB, takes the new one, so its next call works; every other program and MATLAB session calls `reconnect()`.
5. **5 s later**, both output signals of the active mode are selected again as Commander shows them, each a logged write read back: after a start the telegraph's secondary output can still be stale 5 s after the API answers, and Clampex scales by it. No `SetMode` is sent.
6. **A snapshot and the check against the file:** the mode and both feedback resistors, and on the active mode's tab the values that read back as a file holds them, where the file holds them: in V-Clamp Cp Fast Capacitance and Tau, Cp Slow Capacitance, Pulse Amplitude and Duration, Seal Test Amplitude, Rs Compensation Bandwidth and the Oscillation Killer checkbox; in I-Clamp and I = 0 Pulse Amplitude and Duration, Tuning Amplitude, Buzz Duration, the Oscillation Killer and Pipette Capacitance Neutralization checkboxes. Holding comes back 0 and Pipette Offset reads 0 right after any load, and the output signals, gains and filters are kept in the file as positions in lists ommm does not know, so those are not checked.
7. **One more start when the first skipped the file.** Commander sometimes starts without applying the file and says nothing ([quirks.md](quirks.md#closing-and-starting-commander)). When anything in the check differs, ommm logs that start as a `mismatch` naming each difference, then closes Commander and starts it with the same copy once more, steps 2 to 6 again; the load then takes about 30 s. That second start can skip the file too: then load again.
8. **The telegraph:** it agrees with the API on the mode, the gains and the output scales, which follow the feedback resistor ([`state()`](install-and-testing.md#state-and-summary)'s problems). A difference here, or in the check after the last start, makes the load a `mismatch`.

It returns the `Write`: outcome `ok`, `after` the mode and both feedback resistors read back, `also` what else the snapshot shows changed (the active mode's tab only, and the telegraph), and `reason` naming the copy's full path and Commander's processes (`process 1000 → 1001`, or `1000 → 1001 → 1002` with what the skipped start showed after a second start), and Holding when it was on before and reads off after; the plan already says so when Holding is on ([What a load does to the cell](#what-a-load-does-to-the-cell)). More on closing and starting Commander is in [quirks.md](quirks.md#closing-and-starting-commander). The write log gets a line as Commander closes, one as it starts, one as it answers and one per output signal selected, for each start; one for a start that skipped the file; and the `Write`'s own. A `trial_record` puts the load's changes down to ommm.

**After the load** the file's values are Commander's: set Holding, compensation and the rest with `set` and `enable`, Holding first if it was on ([above](#what-a-load-does-to-the-cell)). The other mode's tab is not read: check it with a `set_mode` before you rely on it. A restart with no file sometimes brings I-Clamp values back changed ([quirks.md](quirks.md#closing-and-starting-commander)); a load with a file brings them back as the file holds them.

## Every refusal

Each is decided before Commander is closed, sends nothing and leaves Commander running; with `confirmed=True` it is logged and raises `ommm.WriteError`, without it `load_config` returns it. Examples from the fake, in V-Clamp at 5 GΩ:

| When | The reason |
|---|---|
| What every write checks first: Commander not running, Mode Switching on, no telegraph, the telegraph's mode not the API's | as for every write ([writes.md](writes.md#every-refusal)) |
| Another Commander runs | `2 Commanders run on this PC (processes 1000, 2000): ommm closes Commander only when one runs, since only then can it start it again` |
| On the amplifier: `MC700B.exe` is not where ommm would start it again (`OMMM_SDK_DIR` names a copy of the SDK files, say) | `MC700B.exe is not in C:\sdk-copy, where ommm starts Commander again after closing it: set OMMM_SDK_DIR to Commander's install folder` |
| The file cannot be read | `cannot read C:\mcc\missing.mcc: No such file or directory` |
| On the amplifier: a file whose first line marks it one of ommm's test files, such as `synthetic.mcc` | `synthetic.mcc is a test file, not one Commander saved (its first line says so): ommm loads it only on the fake; load a file Commander saved (Save Configuration, F5)` |
| A file with no settings for the Amplifier's headstage | `synthetic.mcc holds no settings for headstage 2: load a file Commander saved with headstage 2 connected (Save Configuration, F5)` |
| The other headstage holds a level | `headstage 2 holds 20 pA in I-Clamp: the load restarts Commander for both headstages, ...`, unless `release_other_headstage=True` ([Two headstages](#two-headstages)) |
| No `[MC700_GLOBAL]` section, which every saved file starts with | `one_key.mcc is not a settings file Commander saved: load one saved with Save Configuration (F5)` |
| Not a whole file: no mode for the Amplifier's headstage, or no feedback resistor on a tab | `partial.mcc is not a whole settings file: it does not set the mode, Feedback Resistor (I-Clamp), and Commander refused a partial file with a dialog that blocked it until clicked: load a whole file Commander saved (Save Configuration, F5)` |
| `confirmed` or `release_other_headstage` that is not `True` or `False` | `confirmed is True or False, not 1` |
| `changes` that is not a list of four things each | `changes is a list of (label, value, unit, mode), such as [("Feedback Resistor", 500, "MΩ", "V-Clamp")]; not [('Feedback Resistor', 500, 'MΩ')]` |
| A change whose mode is not a mode | `the change ('Feedback Resistor', 500, 'MΩ', 'VC1'): 'VC1' is not a mode: use 'V-Clamp', 'I-Clamp' or 'I = 0', or the buttons' 'VC', 'IC' or 'I=0'` |
| A change for a setting the API reaches | `Holding is set through the API, not in the file: load the file, then set it` |
| A change for another Options-page setting | `'External Command Sensitivity' is not a Commander control ommm knows. load_config changes only the Feedback Resistor: set other Options-page settings in Commander's Options dialog and save the file (docs/mcc.md#an-options-page-setting)` |
| A feedback resistor Commander does not offer, in a change or in the file | `Feedback Resistor in I-Clamp is one of 50 MΩ, 500 MΩ, 5 GΩ, not 50 GΩ`; in the file, after its name: `vc_7.mcc: Feedback Resistor in V-Clamp is one of 50 MΩ, 500 MΩ, 5 GΩ, 50 GΩ, not index 7` |
| A mode in the file that Commander does not have | `mode_5.mcc: AXMCD_FIELD_MODE_SLCT=5 in [MC700_CHANNEL1] is not a mode: 0 is V-Clamp, 1 I-Clamp, 2 I = 0` |
| A value that is not a number | `Feedback Resistor takes a number, not '500'` |
| A unit of another kind | `Feedback Resistor in V-Clamp is a resistance: MOhm or GOhm, not pA` ([Units](writes.md#units)) |
| A file that would start Commander in I-Clamp from V-Clamp, or the other way: Commander would switch without I = 0 | `the file starts Commander in I-Clamp; ommm goes between V-Clamp and I-Clamp through I = 0: set_mode("I = 0") first, then load` |
| The copy's folder has a space | `ommm starts Commander with a copy of the file in C:\my logs\mcc, and Commander cannot take a path with a space: give the Amplifier a log_dir (LogDir= in MATLAB) without one` |

## When something fails

ommm never kills Commander, and starts it once more only after a start that skipped the file ([What a load does](#what-a-load-does)); nothing else is retried. Each failure is logged and raises `ommm.WriteError`, whose `write.reason` says where it stopped:

| Where | Outcome | Commander | What to do |
|---|---|---|---|
| Commander did not close within 30 s (a dialog in its window, say), or runs in Demo mode | `error`: `Commander was not closed: ...` | still running | answer what its window shows; nothing was started. It may close once the dialog is answered: then start it from its icon and `reconnect()` |
| Commander closed and did not start | `error`: `Commander is closed and did not start: ...; start it from its icon, then reconnect()` | closed | start it from its icon, then `reconnect()`; it reconnects to the amplifier it last had |
| Commander started and did not answer within 30 s | `unknown`: `... a dialog in its window may be waiting for a person, as for a file it refuses` | running, maybe behind a dialog | answer the dialog, then `reconnect()` |
| Two starts in a row skipped the file, or the telegraph disagrees after the load | `mismatch`, each difference named | running; this Amplifier has the new handle | read the reason, then `snapshot()`; load again |
| No snapshot after the load | `unknown`: `... no snapshot after it: ...` | running; this Amplifier has the new handle | `reconnect()`, then `snapshot()` |

## The file's format

- A Windows INI file: `[SECTION]` lines, then `AXMCD_FIELD_<name>=<value>` lines, with CRLF line endings; a copy with LF endings loads too. Numbers are kept as Commander writes them: `-2.50000000e-002`, with three exponent digits, or integers; switches are `TRUE` or `FALSE`. Some numbers are positions in a list, not values: `AXMCD_FIELD_OUT_SCLD_LPF_FREQ=38` is not 38 Hz.
- **Sections:** `[MC700_GLOBAL]` (audio, Sync Output, the Advanced page's amplitudes), then for headstage 1 `[MC700_CHANNEL1_VCLAMP_SO_0]` to `_6` and `[MC700_CHANNEL1_ICLAMP_SO_0]` to `_6` (what each output signal keeps), `[MC700_CHANNEL1]` (the mode, the Auto page, the oscillation warning), `[MC700_CHANNEL1_VCLAMP]` and `[MC700_CHANNEL1_ICLAMP]` (each tab), and the SoftPanel's. No serial is in the file. Headstage 2's are the same with `CHANNEL2`.
- **What ommm reads:** `MODE_SLCT` in `[MC700_CHANNEL1]` (`[MC700_CHANNEL2]` on headstage 2), the mode, 0 for V-Clamp, 1 for I-Clamp and 2 for I = 0. For the check after a load, these keys in each tab's section, each as the API reads it (SI, switches `TRUE` or `FALSE`): `COMP_FST_MAG`, `COMP_FST_TAU` and `COMP_SLW_MAG` (Cp Fast Capacitance and Tau, Cp Slow Capacitance), `TESTSIG_PULSE_AMP` and `TESTSIG_PULSE_DUR` (Pulse), `TESTSIG_AMP` (Seal Test or Tuning Amplitude), `RSCOMP_BNDWDTH`, `TESTSIG_BUZZ_DUR`, `OSCKILLER_ENBL` and `COMP_CAP_NEUT_ENBL` (`ommm.mcc.READ_BACK`). **What it changes:** `ELCTRD_HSTAGE_RST_RNG` in each tab's section, the feedback resistor's index, 0-3 for 50 MΩ to 50 GΩ, 3 in V-Clamp only: one line in the Amplifier's headstage's sections, keeping every other byte, line endings included; everything else in the file loads as it is.
- **Other keys found:** `AUDIO_GAIN_ENBL` in `[MC700_GLOBAL]`, `FALSE` with the Audio page's Mute on; `AUDIO_MUX` in each tab's section, the Audio signal, 0 Membrane Current, and in I-Clamp 1 Membrane Potential; `MODE_AUTO_THRESHOLD_LEVEL` in `[MC700_CHANNEL1_VCLAMP]`, the Auto page's Vm threshold in V. With `INPUT_GAIN=1` in both tabs, External Command Sensitivity is 20 mV/V and, at 5 GΩ, 40 pA/V, the lower of each tab's two. ommm does not patch these.
- **The command line:** Commander's documented options are `/S<serial>`, which starts it on that amplifier, `/C<file>`, with that file, and `/D`, in Demo mode. ommm uses `/S` with the serial it reads from the running Commander, never one you give, and `/C` unquoted; it does not use `/D`.
