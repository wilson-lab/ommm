# MATLAB

`ommm.Amplifier` is the main interface: a MATLAB class over ommm's Python `ommm.Amplifier`, with the same method names and Commander's labels, a unit on every value, numbers and structs in and out. Like the package it reads and sets **one headstage of one MultiClamp 700B**, headstage 1 or `Headstage=2`, an object for each ([Two headstages](writes.md#two-headstages)); there is no serial argument. Every write is checked first, read back and logged as [How a write works](writes.md) says; this page is what is MATLAB's own.

[Requirements](#requirements) · [Install](#install) · [Reads and writes](#reads-and-writes) · [Methods](#methods) · [Units](#units) · [The write](#the-write) · [Confirm before a write](#confirm-before-a-write) · [Errors](#errors) · [Without Commander](#without-commander) · [After Commander restarts](#after-commander-restarts) · [Trial records](#trial-records) · [Provenance](#provenance) · [How Python is started](#how-python-is-started) · [Next to the Commander window](#next-to-the-commander-window) · [Tests](#tests)

## Requirements

- **MATLAB R2024b or later**, the first release that loads Python 3.12, which ommm needs. R2026b takes the default `.venv`, Python 3.14.
- **R2024b to R2026a** need the `.venv` on a Python they load: set `UV_PYTHON=3.12` in your environment for R2024b to R2025b, or `UV_PYTHON=3.13` for R2026a, then run `uv sync --locked` in the clone ([Python and MATLAB versions](install-and-testing.md#python-and-matlab-versions), which also says why not `--python`).

## Install

Clone ommm and run `uv sync --locked` in it ([install-and-testing.md](install-and-testing.md#install)), then in MATLAB:

```matlab
addpath(fullfile("<path to ommm>", "matlab"))   % the class finds <ommm>/.venv from its own location
a = ommm.Amplifier();
```

Nothing is copied into MATLAB's own folders. The class sets MATLAB's saved `pyenv` to ommm's Python ([How Python is started](#how-python-is-started)). Without Commander, on a Mac say, `ommm.Amplifier(Fake=file)` runs every call on a saved snapshot ([Without Commander](#without-commander)).

## Reads and writes

```matlab
a = ommm.Amplifier();                          % headstage 1 of the one 700B; Headstage=2 for headstage 2
a.get("Holding", "mV")                         % always with a unit
a.get("Mode")                                  % "V-Clamp"; an output signal by its name, a checkbox true or false
w = a.set("Holding", -60, "mV");               % checks, sends, reads back, logs; w.outcome is 'ok'
a.set("Holding", -40, "mV", Step=5);           % in 5 mV steps, each read back
p = a.plan("Holding", -20, "mV");              % set's checks, sending nothing: p.outcome is 'planned' or 'refused'
a.set("Holding", -20, "mV", Expect=-40);       % refused unless Commander still shows -40 mV
a.enable("Seal Test", true);                   % a checkbox, by its name on Commander's window
a.set("Primary Output", "Membrane Potential"); % an output signal, by Commander's name
a.set_mode("I-Clamp");                         % through I = 0
a.press("Auto Bridge Balance");                % a button, by its name on Commander's window
a.make_safe();                                 % compensation, Seal Test or Tuning, the Resistance meter: off
```

Every write acts on the amplifier at once ([How a write works](writes.md); what ommm leaves to your code: [What ommm does not do](writes.md#what-ommm-does-not-do)).

## Methods

| Call | Returns |
|---|---|
| `a = ommm.Amplifier()` | headstage 1 of the one 700B Commander runs, or `Headstage=2`; refuses if there are none or several, or when the headstage is not connected. `LogDir=folder` puts the write log there instead of in [ommm's log folder](install-and-testing.md#the-write-logs-folder-ommm_log_dir) (`~/ommm-logs` unless set); the folder is fixed when the object is made, so a later `cd` or a Python restart keeps one log |
| `a = ommm.Amplifier(Fake=file)`, `Fake=file, OtherTab=file2` | the same class on ommm's fake Commander, from a saved snapshot, on any OS ([Without Commander](#without-commander)) |
| `a.get(label, unit)` | one control by Commander's label in your unit, from the active mode's tab, which it brings to the front first: `a.get("Holding", "mV")`, `a.get("Feedback Resistor", "MΩ")`. Without a unit: the mode by name (`"V-Clamp"`), an output signal by Commander's name (`"Membrane Current"`), both strings; a checkbox `true` or `false`, by the name `enable` takes (`a.get("Seal Test")`) or its API name (`a.get("HoldingEnable")`). The meters: `a.get("MeterValue1", "mV")`, the potential, or with the Resistance meter on the resistance, in a resistance unit; `a.get("MeterValue2", "pA")`, the current, refused in V-Clamp while Irms Meter is on ([Reads](writes.md#reads)) |
| `a.set(label, value, unit, Step=..., Expect=...)` | the write, a struct ([below](#the-write)): sets a value, or an output signal by name (no unit). `Step` and `Expect` are in the call's unit; an output signal's `Expect` is its name |
| `a.plan(label, value, unit, Step=..., Expect=...)` | the write `set` would make, from fresh reads: outcome `planned`, its `reason` the change in your unit, or `refused` with the reason; sends and logs nothing ([Confirm before a write](#confirm-before-a-write)) |
| `a.enable(name, on)` | the write: a checkbox on (`true`) or off |
| `a.press(name)` | the write: a button, the Autos included |
| `a.set_mode(mode)` | the write: `"V-Clamp"`, `"I-Clamp"` or `"I = 0"`, or Commander's buttons `"VC"`, `"IC"`, `"I=0"`; V-Clamp ↔ I-Clamp through I = 0; the new mode's Holding is yours to set |
| `a.make_safe()` | turns off, where the active mode has them, Pipette Capacitance Neutralization, Rs Compensation, Seal Test (Tuning in I-Clamp) and the Resistance meter: the writes it sent, a struct array; `struct([])` when everything was already off |
| `a.load_config(path, Changes=..., Confirmed=false)` | the plan, a write whose `reason` says what will change; with `Confirmed=true`, Commander restarts with the `.mcc` file and this object takes the new Commander ([mcc.md](mcc.md)). `Changes` has one row per change: `{"Feedback Resistor", 500, "MΩ", "V-Clamp"}`. Refused while the other headstage holds a level, unless `ReleaseOtherHeadstage=true` ([Two headstages](mcc.md#two-headstages)) |
| `a.snapshot()` | struct: every setting in SI units, one telegraph packet, `ommm` (version, commit, dirty, git_error) ([the snapshot](install-and-testing.md#the-snapshot)). A snapshot brings the active mode's tab to the front first |
| `a.state()`, `a.state(snapshot)` | struct: mode, feedback resistor (Ω), each output's `signal` (Commander's name) and `api_name`, gain, scale at gain 1 (V/A or V/V) and low-pass (Hz), and the `blocking`, `problems` and `warnings` found ([`state()`](install-and-testing.md#state-and-summary)) |
| `a.summary()`, `a.summary(snapshot, Manual=...)` | the box `ommm --summary` prints, as a string |
| `[writes, mark] = a.writes_since(mark)` | the write log's lines after byte offset `mark` (0, the default: all), from every program that writes to it, a struct array (`struct([])` for none; a cell array of structs when the lines differ in fields, as a log that also holds 0.1 lines does), and the mark to pass next time ([The log](writes.md#the-log-and-trial-records)) |
| `a.trial_record(before, after, writes, Previous=...)` | struct: two snapshots and what changed between them, each change ommm's or the window's, from `writes_since`'s lines ([Trial records](#trial-records)) |
| `a.reconnect()` | new handles after Commander was closed and started again, when calls fail with 6002; waits for Commander's window, up to 30 s; then, if Holding was on, `a.enable("Holding", true)` as your first write ([After Commander restarts](#after-commander-restarts)). Not needed after this object's own `load_config`, nor after a Python restart |
| `a.headstage`, `a.serial` | the headstage, 1 or 2, and the amplifier's serial, a string; the headstage's full record is the snapshot's `headstage` |
| `a.log_path` | the write log's file, one JSON line per write and refusal, readable without Python |
| `a.fake`, `a.gui` | the snapshot file served instead of Commander (`""` on Commander), and the person at the fake's window ([Without Commander](#without-commander)), as Python's `amp.fake` (`None` on Commander) and `amp.gui` |

- Without a snapshot argument, `state` and `summary` take a new one. A snapshot argument is the struct from `a.snapshot()`, or one saved as JSON and read back: `a.summary(jsondecode(fileread("snapshot.json")))`.
- `trusted` (in `primary` and `secondary`) covers only this output's own scale; check `blocking` first: anything in it (e.g. the other mode's tab in front) overrides trusted.
- Which signal belongs on which output is yours to check: `if a.get("Primary Output") ~= "Membrane Current"`, or `st.primary.signal` from a held snapshot.
- `Manual` holds what Commander cannot report: `struct(lpf_type_v_clamp="bessel", lpf_type_i_clamp="butterworth")`. Case does not matter; another key or filter type is an error.
- Out of `jsondecode`, as every struct here comes: a JSON `null` is `[]` (a missing telegraph, `commit` outside a git checkout, a write's `reason` when there is none), a list of text is a cell array (`blocking`, `problems`, `warnings`, `disagreements`), and a dict is a struct. A snapshot's `errors` and `not_applicable` with none are `struct([])`, so `isempty` works on them as on `disagreements`.

## Units

- Every value names its unit, as Commander's window shows it: Holding in mV in V-Clamp and pA in I-Clamp, MΩ, pF, kHz, %, ms, and `"x"` for a gain. Each control's units, modes and range are its row in [Coming from Commander](coming-from-commander.md). Greek and ASCII spellings both work: `"MΩ"` or `"MOhm"`, `"µs"` or `"us"`, `"×"` or `"x"`.
- A value without its unit, or in a unit the active mode's control does not take, is refused, `ommm:refused` in a write and `ommm:badArgument` in `get`, and the message names the unit to give. In V-Clamp, `a.get("Holding")` says `Holding in V-Clamp is a voltage: give a unit: mV; its checkbox is get("HoldingEnable")`, `a.set("Holding", -40, "pA")` says `Holding in V-Clamp is a voltage: mV, not pA`, and `a.get("MeterValue1")` says `MeterValue1 shows voltage now: give a unit: mV`. ommm never converts between a mode's units and the other's.
- Without a unit: the mode by name (`"V-Clamp"`, `"I-Clamp"`, `"I = 0"`), an output signal by Commander's name (`"Membrane Current"`) and a checkbox (`true`, `false`), as `get` returns them and `set_mode`, `set` and `enable` take them.
- What comes back is SI: a snapshot's `readings` (V, A, Ω, F, Hz, s), and a write's `before`, `target`, `steps`, `after` and `also`, in which the mode and the output signals are the API's ids. `user_value` and `unit` are what you gave; `Step=` and `Expect=` are in the call's unit.

## The write

`set`, `plan`, `enable`, `press`, `set_mode`, `load_config` and each of `make_safe`'s return Python's `Write` as a struct, with the same fields ([Outcomes](writes.md#outcomes)): `label`, `stem`, `mode`, `user_value`, `unit`, `before`, `target`, `steps`, `depends`, `after`, `also`, `outcome`, `reason`, `t`. Its values are the API's (SI, Rs Compensation in percent, gains as plain numbers, checkboxes `true` or `false`, the mode and output signals as ids); `user_value` and `unit` are what you gave. `outcome` is `'ok'` or `'adjusted'` from a write that returns, `'planned'` or `'refused'` from `plan` and `load_config` without `Confirmed=true`.

## Confirm before a write

`plan` makes every check `set` would make, from fresh reads, and sends and logs nothing; a planned write's `reason` is the question, the change in your unit: `Holding 0 mV → -40 mV (V-Clamp)`. `Expect=` then makes `set` refuse, sending nothing, when Commander no longer shows the value the question showed, as after a click in Commander's window while the question was open:

```matlab
shown = a.get("Holding", "mV");                                 % for Expect=
p = a.plan("Holding", -40, "mV", Expect=shown);
if p.outcome == "refused"
    error("%s", p.reason)                                       % out of range, another mode, Mode Switching on: nothing to ask
end
if questdlg(p.reason, "Commander", "Go", "Cancel", "Cancel") == "Go"
    a.set("Holding", -40, "mV", Expect=shown);                  % ommm:refused if Commander changed meanwhile
end
```

- `Expect=` is in the call's unit; for an output signal, its name: `a.set("Primary Output", "Membrane Potential", Expect="Membrane Current")`.
- `plan` covers `set` only, and `set_mode`, `press` and `enable` take no `Expect`: read again after the question (`a.get("Mode")` before a mode change or a button) and stop if it changed. A button's own values are settings, set first with `Expect=`: `a.set("Zap Duration", 0.5, "ms", Expect=shown)`, then `a.press("Zap")`.
- `load_config` without `Confirmed=true` is its own plan: its `reason` says what will change and is the question's text; the same call with `Confirmed=true` does it.

## Errors

Errors from ommm carry an identifier, so code can tell them apart without reading the message:

| Identifier | When | |
|---|---|---|
| `ommm:refused` | A write ommm refused, sending nothing; it is logged | `err.write` |
| `ommm:writeError` | A write sent that did not take: `mismatch`, `unknown` or `error` ([Outcomes](writes.md#outcomes)) | `err.write` |
| `ommm:badArgument` | An argument ommm cannot use, outside a write: an unknown label, a missing or wrong unit or a button given to `get`, a `Fake=` file that is not a snapshot or has a newer `schema` than this ommm's, a log folder ommm cannot use, one this account cannot write to included, refused when the object is made (`LogDir=`, or [`OMMM_LOG_DIR` or the default](install-and-testing.md#the-write-logs-folder-ommm_log_dir); the message names which), a `trial_record` snapshot that is not a struct | |
| `ommm:notApplicable` | `get` of a control the active mode does not have: `a.get("Bridge Balance", "MΩ")` in V-Clamp; or of `MeterValue2` in V-Clamp while Irms Meter is on | |
| `ommm:commander` | Commander failed or is not there: not running in this desktop session, closed or started again since this object connected (6002: `a.reconnect()`), no answer in time (6005), no 700B, one of Commander's files missing from its install folder ([`OMMM_SDK_DIR`](install-and-testing.md#commanders-install-folder-ommm_sdk_dir)), or not Windows ([Error codes](writes.md#error-codes)) | |

The message is Python's; a refusal's says what to do. `err.message` works for every `ommm:` error. `ommm:refused` and `ommm:writeError` are an `ommm.WriteError`, an `MException` with one property more, `err.write`: the write as `set` would have returned it, `outcome` and `reason` included.

```matlab
try
    a.set("Holding", -60, "mV");
catch err
    if err.identifier == "ommm:refused"
        disp(err.message)               % nothing was sent: what to do
    else
        rethrow(err)
    end
end
```

`plan` and `load_config` without `Confirmed=true` return a refusal, `outcome` `'refused'`, instead of raising it. The class's own:

| Identifier | When |
|---|---|
| `ommm:fake` | `Fake=` or `OtherTab=` names no file, `OtherTab=` without `Fake=`, or `a.gui` on Commander |
| `ommm:noVenv` | the clone has no `.venv`: run `uv sync --locked` in it |
| `ommm:otherPython` | MATLAB already runs another Python, or uv rebuilt the `.venv` on another Python ([How Python is started](#how-python-is-started)) |
| `ommm:otherClone` | MATLAB's Python imports ommm from another clone |
| `ommm:pyenvChanged`, a warning | the class replaced MATLAB's saved Python; the message has the line that puts it back |

An argument of the wrong type (`a.enable("Seal Test", "on")`) is MATLAB's own validation error, and so is a `Step=` or `Expect=` that is not one value: a vector, or a cell such as `{-20, "mV"}`. Any other error from Python comes as MATLAB gives it, `MATLAB:Python:PyException`, and so does a refusal by `a.gui`, the fake's window.

## Without Commander

- `a = ommm.Amplifier(Fake=file)` serves a saved snapshot instead of Commander, so the class runs anywhere, a Mac included. ommm ships one for each mode, taken with nothing attached: `vclamp.json`, `iclamp.json` and `i0.json` in `src/ommm/examples/fake/`. On the PC, `ommm --out snapshot.json` saves your own; in MATLAB, `writelines(jsonencode(a.snapshot()), file)` does.
- Every call runs on it. A write changes the fake as it would Commander, and logs to a new temporary folder (`a.log_path`) unless given `LogDir=`, never to the amplifier's log. On a fresh fake, `a.load_config(fullfile("<path to ommm>", "src", "ommm", "examples", "fake", "synthetic.mcc"))` plans a load and `Confirmed=true` runs it, about 5 s; it is a test file the amplifier refuses.
- `OtherTab=file2`, a snapshot taken with the other tab in front, gives the fake both tabs.
- `Headstage=2` serves the snapshot as headstage 2's, whichever headstage it was taken on. Both headstages on one fake are Python's only: `FakeCommander(file, other_headstage=file2)` and `fake.handle(2)` ([`ommm.testing.fake`](../src/ommm/testing/fake.py)).
- `a.gui` is the person at Commander's window, as `amp.gui` in Python: `a.gui.show_tab("I-Clamp")`, `a.gui.mode("I = 0")`, `a.gui.set("Holding", -20, "mV")`, `a.gui.enable("Holding", true)`. Nothing it does is logged, so a trial record puts its changes down to `gui`:

```matlab
a = ommm.Amplifier(Fake=fullfile("<path to ommm>", "src", "ommm", "examples", "fake", "vclamp.json"));
before = a.snapshot();
a.gui.set("Primary Output Gain", 5, "x");     % a click in Commander's window
record = a.trial_record(before, a.snapshot());
record.changed.readings.PrimarySignalGain.source   % 'gui'
```

- After a Python restart the class connects again and starts a new fake from its files, so the writes made before are gone; `a.reconnect()` keeps the fake as it is. What the fake does not model (a cell, the meters, Commander's dialogs): [The fake](install-and-testing.md#the-fake).

## After Commander restarts

- **After this object's own `load_config(..., Confirmed=true)`** the next call works: the object takes the new Commander itself.
- **After someone else restarted Commander** (its window closed and opened, another program's or MATLAB session's `load_config`), reads fail with `ommm:commander` and writes with `ommm:refused`, both naming 6002, until `a.reconnect()`, which waits up to 30 s for Commander's window.
- **A Commander started from MATLAB stays.** `load_config` starts Commander from MATLAB's Python, which runs in a Windows job object that lets no child leave it, so Commander runs inside that job; the job does not end its processes when it closes, so Commander outlives `terminate(pyenv)` and MATLAB's exit.
- **Holding after a restart:** [When something fails](writes.md#when-something-fails); in MATLAB the first write is `a.enable("Holding", true)`.

## Trial records

`a.trial_record(before, after, writes, Previous=...)` tells ommm's changes between two snapshots from the window's, as Python's `ommm.trial_record` ([The log and trial records](writes.md#the-log-and-trial-records)). It takes the structs from `a.snapshot()` (`[]` for one that failed) and `writes_since`'s lines, none, one or many, and returns the record as a struct: `before`, `after`, `changed` and, with `Previous=` the last trial's `after`, `between`:

```matlab
before = a.snapshot();
[~, mark] = a.writes_since();                                  % the log's end now
% ... the trial, and any writes ...
after = a.snapshot();
[writes, mark] = a.writes_since(mark);                         % the lines written during the trial, and the next mark
record = a.trial_record(before, after, writes);                % save it with the trial
```

On the amplifier a snapshot takes 18-22 ms inside Python, plus the JSON round trip to MATLAB; a trial loop that takes one before and after each trial budgets for both.

Save `a.snapshot()` with a trial, not `a`: a saved `ommm.Amplifier` holds no connection, and loaded back it connects again on its first call, to the Commander (or the `Fake=` file) there then.

## Provenance

- Every snapshot says which ommm took it, under `ommm`: `version`, `commit`, `dirty` and `git_error` ([Provenance](install-and-testing.md#provenance)); `demo` is true for Commander's Demo mode, a guard only, since Demo answers no snapshot ([quirks.md](quirks.md#connecting-and-restarting)). Every write-log line carries `ommm` (`version`, `commit`, `dirty`) and `process` (`pid`, `program`) ([The log and trial records](writes.md#the-log-and-trial-records)).
- ommm is imported once per Python, and that is the code snapshots and log lines name. To update: [Update](install-and-testing.md#update), then restart MATLAB. The class loads the `.venv` directly, which only a sync brings to the new version: without it, snapshots name the new commit with the old version.
- A log line written from MATLAB has `process.program` `"MATLAB"`, and `pid` MATLAB's Python's, which changes when Python restarts.

## How Python is started

- **The class sets MATLAB's saved Python** to ommm's interpreter, out of process, and that setting lasts into later MATLAB sessions. When it replaces a saved interpreter, it warns `ommm:pyenvChanged` with the line that puts it back, `terminate(pyenv); pyenv(Version="...", ExecutionMode="...")`; turn the warning off with `warning("off", "ommm:pyenvChanged")`.
- **Another Python already loaded**, or a `.venv` that uv rebuilt on another Python, stops the class with `ommm:otherPython`, whose message names the fix: `terminate(pyenv)` or restart MATLAB; for a rebuilt `.venv`, set `UV_PYTHON` as [Requirements](#requirements) says, run `uv sync --locked` in the clone, then restart MATLAB.

## Next to the Commander window

Commander stays the source of truth: every `snapshot`, `state` and `summary` asks it again, and a change made in the window shows at the next read. Commander does not telegraph a checkbox clicked in its window: it is seen when ommm next reads, since ommm never polls. `ommm.Amplifier()` and `reconnect()` bring the active mode's tab to the front as they connect, and so do every snapshot, `get` and write. A write first re-selects both output signals when the telegraph's are stale, as after Commander starts, each a logged write ([Before every write](writes.md#before-every-write)); a session that only reads keeps the stale telegraph, which `state()` lists as a warning. How Commander behaves under the API: [quirks.md](quirks.md).

## Tests

`matlab/tests/AmplifierTest.m` runs the class on `Fake=` with no Commander: `runtests("<ommm>/matlab/tests")`, after `uv sync --locked`. It starts Python from ommm's `.venv`, stops it at the end, and leaves MATLAB's saved `pyenv` pointing at that interpreter, so run it where that is acceptable.

The suite covers every method on the fake, the writes, refusals as errors with their identifiers and in words that read right in MATLAB, `plan` sending nothing, a `load_config` planned on `synthetic.mcc` and one confirmed (about 5 s), one write log through a `cd` and a Python restart, a saved and loaded object, and the Python startup and recovery. On Windows four tests skip: one kills Python with `kill -9`, two use the `.venv`'s `bin/python` link as a second interpreter (`ommm:otherPython` and `ommm:pyenvChanged`), and one checks the off-Windows error.
