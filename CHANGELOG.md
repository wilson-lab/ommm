# Changelog

The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/). Every snapshot records the ommm version and commit that took it ([Provenance](docs/install-and-testing.md#provenance)).

## [Unreleased]

## [0.3.0] - 2026-11-15

The package sends Commander what 0.2.1 sends. Released after running on the fake only (the Python and MATLAB tests, and the Python examples from an install from git); on 2026-11-16 `scripts/rig/check_amplifier.py` ran it (`4ecbfcf`) on the amplifier at 5 GΩ with nothing attached, and every check went as expected but the two I-Clamp Slow Current Injection levels, which read 14 µV off after the check's Auto Pipette Offset ([quirks.md](docs/quirks.md#values-come-back-a-little-different)).

It starts the public history, as one commit: 0.1.0 to 0.2.1 were tagged in an earlier history, which is archived, so a commit named below, or stamped in a record in `tests/data/rig/`, is from that archive, and those versions have no tag here.

- Installed from git into another project (`uv add git+https://github.com/wilson-lab/ommm`), ommm's provenance names the commit it was built from, where it had `commit: None`.
- The examples and the fake's snapshots ship with the package, so they are there after such an install too: `ommm.EXAMPLES` is their folder, and `ommm --examples DIR` copies it to a folder of your own.
- They moved: `examples/` is `src/ommm/examples/`, and `tests/data/vclamp.json`, `iclamp.json`, `i0.json` and `synthetic.mcc` are in `src/ommm/examples/fake/`. Code that names the old paths needs the new ones.
- GitHub runs the Python tests on Windows and Linux for every push and pull request.
- `CONTRIBUTING.md` says how to report a problem and propose a change.
- The licence is BSD 3-Clause, where it was MIT.

## 0.2.1 - 2026-10-28

Docs only; the package code does what 0.2.0's does, which ran on the amplifier at `71e7817`.

- The docs say what headstage 2 did on the rig, and that it is not supported.
- Commander has one headstage selection for every program: two programs at once can reach each other's headstage. With both headstages in use, run one program on Commander.
- Docstrings, comments and two messages say what Commander does, not what happened once; dates and run counts are gone from the docs.

## 0.2.0 - 2026-10-28

Still headstage 1 only.

- Tighter calls, messages, docs and tests (the 2026-10 review).
- Every write log line has one shape now (log schema 2).
- Some names changed. Old code may break; the list below says what to use instead:
  - `ommm.load` is `ommm.load_snapshot`.
  - `Amplifier(headstage, *, ...)`: the headstage comes first, the rest by name.
  - MATLAB passes `a.snapshot()` straight in; `snapshotPy` is gone.
  - MATLAB errors are `ommm:badArgument` and `ommm:fake`.
- Headstage 2's calls are in, but not supported yet: they have run on the fake and in one sitting.
- Ran on the amplifier at `71e7817`: `check_amplifier.py` (428 checks; the 2 misses are the known Slow Current Injection offset), the model-cell sitting and the headstage-2 sitting.

To update: `git pull`, `uv sync --locked`, then restart MATLAB.

### Added

- For headstage 2, not supported yet: `ommm.Amplifier(headstage=2)` (MATLAB `Headstage=2`, `ommm --headstage 2`), the same calls on headstage 2, one Amplifier per headstage when both are in use. A headstage whose feedback resistor answers 6006 is refused as not connected.
- Each headstage reads its own feedback resistors (`FeedbackResistorVC2`/`IC2` on headstage 2) and meters (`MeterValue3` and `4`; `get` refuses the other headstage's).
- Each headstage logs to its own file (`<serial>_headstage2.jsonl`), and each log line names its `headstage`.
- `load_config` patches and checks the Amplifier's headstage's sections of the file and names the other headstage in its plan; headstage 2 refuses a file with no settings for it.
- `load_config` refuses while the other headstage holds a level, unless `release_other_headstage=True` (MATLAB `ReleaseOtherHeadstage=true`).
- The fake has two headstages: `FakeCommander(file, headstage=2)`, `other_headstage=`, `other_headstage_tab=`, `fake.handle(2)` and `fake.gui_for(2)`.
- `ommm.__version__`, and `__all__` naming the public names.
- The checkbox names in one table, `ommm.settings.CHECKBOXES` (the window's name, the API name, the modes), and a Checkboxes section on the generated page; the names `enable` took before are taken the same, and the window's own words Resistance, Irms and Tau x20 too.
- MATLAB: `a.trial_record(before, after, writes, Previous=...)`, Python's `ommm.trial_record` on the structs from `a.snapshot()` and `a.writes_since`'s lines (none, one or many).

### Changed

- Every `Write` and log line has one shape, log `schema` 2: `before`, `target` and `after` are the value of what `stem` names, `after` as read back; `steps` holds only what was sent; `also` every other change, `{name: [before, after]}`, readings and telegraph fields side by side. A button's result is in `also`, its `after` `None`; `set_mode`'s `after` is the mode id read back; `load_config`'s `after` is the mode and both feedback resistors, the rest in `also`. Code that read a button's, `set_mode`'s or `load_config`'s `after` as the snapshot diff reads `also`.
- After updating ommm, restart MATLAB (not only `terminate(pyenv)`) and make your objects again: `trial_record` reads schema 2 only, so a 0.1 button's or load's line, read by an object made before the update, puts its changes down to `"gui"`.
- `enable("Mode Switching", on)` that is already so has no `steps`: nothing was sent.
- `ommm.Amplifier(headstage=1, *, log_dir=None, fake=None, other_tab=None, commander=None)`: the headstage comes first, the rest are keyword-only. `fake=` and `other_tab=` take snapshot files, as MATLAB's `Fake=` and `OtherTab=`, and the Amplifier makes the fake; `commander=` takes a fake made by hand or another handle on one, never with `fake=`, and must be on the Amplifier's headstage.
- `amp.headstage` is 1 or 2, and `amp.serial` the serial (MATLAB `a.headstage`, `a.serial`); the full record is the snapshot's `headstage`.
- `amp.gui` is the person at the fake's window, following each new handle; on Commander it raises `AttributeError`. MATLAB's `a.gui` is Python's.
- `ommm.Commander` is internal: `ommm` exports `CommanderError` and `NotApplicable` from `ommm.commander`, and the `ommm` command reads through `ommm.Amplifier`, so it too refuses a log folder it cannot write to. Code that used `ommm.Commander` uses `ommm.Amplifier`.
- `ommm.load` is `ommm.load_snapshot`, so that a load is always `load_config`'s; `ommm.amplifier.LOAD_SETTLE_S` is `LOAD_CONFIG_SETTLE_S`.
- `ommm.process`'s `quit_commander`, `wait_for_api` and `Process.connect` take the headstage to connect through.
- A refusal's message is its reason alone, and a `CommanderError` in ommm's own words leaves out the function (it is on `error.function`); an API call Commander fails says which call: `GetHolding failed: MSGTIMEOUT (6005)`.
- `step=` and `expect=` (`set`, `plan`) and `changes=` (`load_config`) are keyword-only.
- `step=` and `expect=` are numbers in the call's unit, as MATLAB's `Step=` and `Expect=`: `set("Holding", -40, "mV", step=5)`, no longer `step=(5, "mV")`; a pair is refused.
- `enable`'s `on` and `load_config`'s `confirmed` and `release_other_headstage` take only `True` or `False`; `1` or `"yes"` is refused.
- A `log_dir` ommm cannot make or write to is refused when the Amplifier is made.
- Listing no 700B, several, or not the headstage asked for each has its own message, naming what Commander lists.
- A refusal between steps names the values in Commander's words and the call's unit; a `make_safe` failure names what it had turned off.
- `load_config`'s refusals name a file that is not a settings file Commander saved, and the missing settings by Commander's labels.
- `load_config` checks `changes` as a list of four-item changes and refuses a value that is not a number.
- Messages give the MATLAB spelling beside the Python one (`ReleaseOtherHeadstage=true`, `LogDir=`).
- Units are looked up in any Unicode form (the ohm sign, the Greek mu), and a unit refusal suggests units in the spelling given.
- Every message and doc says Mode Switching (Ext still works as a name) and restart for relaunch.
- `state()`'s warnings name each checkbox as Commander's window does, and the summary box's rows use Commander's labels.
- `ommm.provenance()` returns a copy.
- `Amplifier.process` is chosen when the Amplifier is made, and a `FakeProcess` made after an Amplifier or `fake.handle(n)` is refused.
- The active examples drop the cell that closed and started Commander without a file.
- MATLAB's `summary` returns a string, and `Expect=` takes a char vector.
- MATLAB: `state` and `summary` take the struct from `a.snapshot()`, or a snapshot saved as JSON and read back with `jsondecode`; `writes_since`'s first output is `writes`, as in Python.
- `state()`'s `primary` and `secondary`: `signal` is Commander's name (`"Membrane Current"`), `api_name` the API's (`"VC_MEMBCURRENT"`).
- MATLAB: an argument ommm cannot use (Python's `ValueError`: an unknown label or a wrong unit in `get`, a `Fake=` file that is not a snapshot, a `LogDir=` ommm cannot write to) is `ommm:badArgument`; `ommm:refused` is only a refused write and always carries `err.write`.
- MATLAB: `ommm:notFake` and `ommm:noFake` are one identifier, `ommm:fake`.
- `enable` says what a name that is no checkbox in the active mode is: another mode's checkbox (`Tuning is a checkbox in I-Clamp; in V-Clamp it is Seal Test`), a button, a value, or a misspelt name, which `find` now matches against the checkbox names too.
- `press` of a value names the call that sets it, `set("Zap Duration", value, "ms")`, with `enable` where the value has a checkbox and `load_config` for the feedback resistor.
- A control the active mode lacks is refused alike by `set`, `press`, `enable` and `get`, before what kind of control it is, and no message names a call in another mode's unit: `Tuning Amplitude is not in V-Clamp: Commander has it in I-Clamp; in V-Clamp it is Seal Test Amplitude`.
- `set` and `press` of a checkbox the active mode lacks refuse as `enable` does (`Seal Test is a checkbox in V-Clamp; in I-Clamp it is Tuning`), and by its API name they name this mode's checkbox (`TestSignalEnable` in I-Clamp: Tuning).
- `get` of a value without a unit, for the five that share their checkbox's name (Holding, Leak Subtraction, Output Zero, Bridge Balance, Pipette Capacitance Neutralization), names the checkbox's API name: `...: give a unit: mV; its checkbox is get("HoldingEnable")`.
- Messages, docs and the generated page state facts without evidence tags.
- The docs keep each fact on one page and link to it; numbers no decision depends on are cut.
- The fake's docs for users are three lines in `docs/install-and-testing.md`; what it models and the knobs a test turns are in `ommm.testing.fake`'s docstring.

### Removed

- `ommm.PROVENANCE`: use `ommm.provenance()`.
- `Commander`'s `timeout_ms`: every call waits up to 3 s.
- `Setting.source`: where a settings row's facts come from is a comment on the row.
- `state()`'s and `summary()`'s `expected_outputs=` (MATLAB `ExpectedOutputs=`), its output pairing problem, and each output's `short` (`ommm.state.short_name`): which signal belongs on which output is the caller's to check, `st["primary"]["signal"] != "Membrane Current"`.
- MATLAB's `snapshotPy` and `ommm:notSnapshotPy`: `state`, `summary` and `trial_record` take `a.snapshot()`.
- The one-question rig probes, `capture.py`, `restore.py`, `parity.py`, `step_through.py` and `rigtask.ps1`; their answers are in `docs/quirks.md` and their records in `tests/data/rig/`.

### Fixed

- With nothing on headstage 2, `Commander.other_headstage` counts it as not connected when `SelectMultiClamp` refuses it with 6002, as Commander did on the rig; before, every `load_config` there was refused. The fake refuses a headstage it does not list so.
- A `[]` saved from MATLAB for a null loads as `None` at any depth (a reading, a commit outside a checkout), so `ommm.load_snapshot`, `state()` and `summary()` take such a snapshot.
- A negated zero shows as 0 mV, not -0 mV.

## 0.1.1 - 2026-10-27

On the amplifier: this change at `f8ff1a3`, on 0.1.0, ran eleven loads of three settings files Commander saved (one of them as saved and at 50 GΩ in turn), each ok, none skipped; at `bc72482`, on the 0.2.0 candidate, the same eleven loads flagged none that took, and one 50 GΩ load skipped its file on both starts, a `mismatch`. The tagged commit differs from `f8ff1a3` only in the CHANGELOG, docs and a comment.

### Fixed

- `load_config` notices a Commander start that skipped the file (4 of 92 loads on the rig, each to or from 50 GΩ): after each start it compares Pulse, Cp Fast, Cp Slow Capacitance and the other values of the active mode's tab that read back as the file holds them (`ommm.mcc.READ_BACK`).
- On a difference `load_config` logs that start as a `mismatch` and starts Commander with the file once more; a second such start is the load's `mismatch`.
- The fake's `FakeProcess(fake, skip=1)` skips a file, and its loads set those values.
- The MATLAB suite's mode-refusal test refuses a name that is not a mode: `"VC"`, a button's name, is a mode since 0.1.0.

## 0.1.0 - 2026-10-26

First release: one MultiClamp 700B, headstage 1 only, through the running MultiClamp Commander 2.2.x on Windows. On the amplifier, with a PATCH-1U model cell, the package code is what ran there last, at the archived commit `35b954d` (the four examples, whole, from Python and MATLAB), after the 2026-10-26 sitting (the amplifier switched off, Demo mode, restarts by hand, 500 MΩ and 50 GΩ loads, the buttons on a DAQ, BATH and PATCH); this commit differs from it only in docs, comments, tests and the rig probes' names ([What has been tested](docs/install-and-testing.md#what-has-been-tested)).

It started a fresh history: the build and three earlier tags (0.1.0 to 0.1.2, 2026-10-24 to 26) are archived, and a record stamped with one of their commits, such as those in `tests/data/rig/`, names a commit from that archive.

### Added

- Python package `ommm` and MATLAB class `ommm.Amplifier`, with the same calls.
- Reads: `get(label, unit)`, a snapshot of every setting with the telegraph and ommm's provenance, `state()`, the summary box (examples in the README and `install-and-testing.md`, kept current by the tests) and the `ommm` command.
- Writes by Commander's labels with a unit on every value: `set`, `plan`, `enable`, `press`, `set_mode` (also by Commander's button names, `"VC"`, `"IC"`, `"I=0"`) and `make_safe`.
- Each write is checked before it is sent, read back after and logged; refusals in Commander's words, MATLAB errors with `ommm:` identifiers.
- The refusals include a call that fails with no error code (the amplifier off, or Demo mode).
- `load_config`: settings no API function reaches, such as the feedback resistor, by restarting Commander with a `.mcc` file it saved; each load's copy in `~/ommm-logs/mcc/` is named by its changes.
- Three settings files Commander saved, in `examples/mcc/`.
- Commented examples, a cell at a time: `examples/ommm_example_passive.py` and `.m` (reads only) and `examples/ommm_example_active.py` and `.m` (writes, a settings file, closing and starting Commander).
- A fake Commander for tests and for trying ommm without an amplifier.
- `docs/coming-from-commander.md`, generated from the settings table, and `docs/quirks.md`, Commander's behaviour under the API.
- Rig probes `scripts/rig/probes/p01` to `p24`, each one question about Commander; only `p11_relaunch_outputs.m` needs a DAQ.

[Unreleased]: https://github.com/wilson-lab/ommm/compare/v0.3.0...dev
[0.3.0]: https://github.com/wilson-lab/ommm/releases/tag/v0.3.0
