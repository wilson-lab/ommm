# Install, running and testing

ommm reads and sets **one MultiClamp 700B**, headstage 1, through the MultiClamp Commander running on the same Windows PC. Headstage 2's calls are in the API but not supported ([Two headstages](writes.md#two-headstages)). The 700A is not supported.

- **Set up:** [Install](#install) · [Update](#update) · [Python and MATLAB versions](#python-and-matlab-versions) · [Commander's install folder](#commanders-install-folder-ommm_sdk_dir)
- **Run:** [next to Commander](#running-next-to-commander) · [the `ommm` command and the scripts](#the-ommm-command-and-the-scripts) · [checking ommm against your Commander](#checking-ommm-against-your-commander)
- **Read and write:** [how a write works](writes.md) · [the snapshot](#the-snapshot) · [provenance](#provenance) · [`state()` and `summary()`](#state-and-summary) · [output scales](#output-scales-at-gain-1) · [feedback resistor indexes](#feedback-resistor-range-indexes) · [error codes](writes.md#error-codes)
- **Test:** [tests](#tests) · [the fake](#the-fake) · [what has been tested](#what-has-been-tested) · [planned](#planned)

## Install

```
git clone --branch v0.3.0 https://github.com/wilson-lab/ommm   # a release; without --branch, main
cd ommm
uv sync --locked                # .venv with ommm and its test tools
uv tool install --editable .    # optional: the `ommm` command
uv tool update-shell            # once, if `ommm` is not found: puts uv's tool folder on PATH (sign out and in)
```

- Clone ommm next to the code that uses it. Its own `.venv` is what other programs load: the MATLAB class loads `<ommm>/.venv` by path ([matlab.md](matlab.md)).
- `--locked` installs exactly what `uv.lock` says and leaves the file alone. A plain `uv sync` with a newer uv can rewrite `uv.lock`, and an edited tracked file makes every snapshot's provenance read dirty.
- **In another Python project,** `uv add git+https://github.com/wilson-lab/ommm --tag v0.3.0` installs the package, and its snapshots name the tag's commit ([Provenance](#provenance)). The examples and the fake's snapshots come with it (`ommm.EXAMPLES`; `uv run ommm --examples DIR` copies them to a new folder `DIR`); the scripts, the tests and the MATLAB class are in the clone only.
- On a Mac or Linux the same commands work: ommm imports, its tests run, and saved snapshots can be read (`ommm.load_snapshot`, `ommm.summary`, `ommm.state`, `ommm FILE`). Only talking to Commander needs Windows.

## Update

```
git fetch --tags
git checkout <tag>               # the release you want, e.g. v0.3.0; or `git checkout main && git pull` for the latest
uv sync --locked                # the .venv at the new version
uv tool upgrade ommm            # if you installed the `ommm` command
```

Then restart MATLAB, and restart any other Python that has ommm imported.

- **The sync keeps the version in step with the commit.** A snapshot's `version` is the installed package's, which uv writes when it installs ommm; an editable install runs a pull's code at once but keeps the old `version` until uv installs it again. `uv sync --locked` brings the `.venv`'s version up to date, and `uv tool upgrade ommm` the command's.
- `uv run` syncs the `.venv` first, so code run through it is in step without the sync. MATLAB loads the `.venv` directly, and the `ommm` command runs from uv's own tool folder: neither syncs.
- **The restart:** a Python that imported ommm before the pull still runs, and records, the old code ([Provenance](#provenance)). Restart MATLAB itself, not only its Python (`terminate(pyenv)`): MATLAB keeps running the old class's code for objects made before the update, so they call the new Python with the old arguments; and an object made before the update, such as one that keeps trial records, still reads the log from where it started, and the new version may read the older lines otherwise (0.2.0's log schema 2: a button's or a load's change logged by 0.1 goes down to `"gui"`, [The log and trial records](writes.md#the-log-and-trial-records)). Make your objects again after the restart.

## Python and MATLAB versions

ommm needs Python 3.12 or later. The `.python-version` file pins 3.14, which uv downloads if needed. The MATLAB class loads the `.venv`'s interpreter, so the `.venv` must be on a Python your MATLAB release supports, as listed in MathWorks' [Versions of Python compatible with MATLAB](https://www.mathworks.com/support/requirements/python-compatibility.html):

| MATLAB | Python it loads | Set up ommm with |
|---|---|---|
| R2026b | 3.10 to 3.14 | `uv sync --locked` (3.14, the pin) |
| R2026a | 3.9 to 3.13 | `UV_PYTHON=3.13` in your environment, then `uv sync --locked` |
| R2024b, R2025a, R2025b | 3.9 to 3.12 | `UV_PYTHON=3.12` in your environment, then `uv sync --locked` |
| R2024a and older | 3.11 at most | not supported: ommm needs 3.12 |

- The rows for releases before R2026b follow MathWorks' table; what has run: [What has been tested](#what-has-been-tested).
- **Set `UV_PYTHON`, not `--python`.** With `UV_PYTHON=3.12` (or `3.13`) in your environment every uv command follows it, `uv run` and `pytest` included; on Windows, `setx UV_PYTHON 3.12` sets it for your user, in terminals opened after it. `uv sync --locked --python 3.12` alone is undone by the next `uv sync` or `uv run` without the flag, the README's quickstart and the tests included, which rebuild the `.venv` on the pinned 3.14. Do not change `.python-version` (`uv python pin`): it is tracked, so every snapshot would read dirty.
- `uv.lock` covers every Python from 3.12, so `--locked` works on any of them and leaves the clone clean: provenance stays `dirty: false`.
- After the `.venv` changes Python, restart MATLAB or run `terminate(pyenv)`: the class refuses a loaded Python other than the `.venv`'s (`ommm:otherPython`), and its message names the `UV_PYTHON` fix.
- The class does not check MATLAB's release; an unsupported pairing fails when `pyenv` loads the interpreter.

## Commander's install folder (`OMMM_SDK_DIR`)

`OMMM_SDK_DIR` names Commander's install folder; unset, ommm uses `C:\Program Files\Molecular Devices\MultiClamp 700B Commander`. ommm reads three of its files and starts one program from it, and never copies any of them into the repository: the headers carry an Axon Instruments copyright and no licence.

| File | Used for |
|---|---|
| `3rd Party Support\AxMultiClampMsg\AxMultiClampMsg.h` | every function's signature and every constant, parsed when an `ommm.Amplifier` is made (the header, not the PDF, which has type typos: `SetHolding` takes a double) |
| `3rd Party Support\AxMultiClampMsg\AxMultiClampMsg.dll` | the API itself |
| `3rd Party Support\Telegraph_SDK\MultiClampBroadcastMsg.hpp` | the telegraph's mode, signal and unit names |
| `MC700B.exe` | Commander itself: `load_config` starts it again from here after closing it ([mcc.md](mcc.md#what-a-load-does)) |

- **On the PC,** leave it unset, or name the folder Commander runs from if it is installed elsewhere.
- **Not a copy of the SDK files alone.** Reads and writes work with the three files, but `load_config` refuses in its plan, before Commander is closed, when `MC700B.exe` is not in the folder ([Every refusal](mcc.md#every-refusal)), since it could not start Commander again.
- **For the header tests** (on a Mac, say), name the install folder or a copy of the whole folder: they read the two headers, and one checks that `MC700B.exe` is there ([Tests](#tests)).

## Running next to Commander

- **Same desktop session, same privilege level.** Every read is a Windows message to Commander, and Commander answers only programs in its own session at its own integrity level. A process run as administrator while Commander is not should fail the same way, since Windows keeps Commander's answers from reaching a higher integrity level. Over SSH the API fails with 6002 (`MCCNOTOPEN`): run ommm in Commander's desktop session. When Commander cannot be reached, ommm's error names the likely cause (an SSH session, or running as administrator) or says to start Commander.
- **The active mode's tab comes to the front.** The API reads and sets the tab Commander shows, not the active mode, so every ommm read, snapshot and write first brings the active mode's tab to the front with `SelectMultiClamp` (0.1-8 ms). A tab clicked to look at the other mode goes back at ommm's next call ([quirks.md](quirks.md#tabs-and-modes)).
- **Mode Switching.** `SetModeSwitchEnable` toggles Mode Switching whatever its argument, and the mode it leaves cannot be predicted, so after turning it off set the mode back and check the tab ([quirks.md](quirks.md#mode-switching-flips-whatever-you-pass-it)).
- **A clone made from an elevated shell** (for example over SSH) is owned by Administrators, and git in the desktop session may refuse it as "dubious ownership". Provenance then records git's error instead of a commit. `git config --global --add safe.directory <path to ommm>` from the desktop session allows it.
- **Close Commander from its window, never kill it.** Commander saves its settings only on a clean exit; killed with `taskkill /F`, it comes back with older ones. After Commander restarts, every open handle on it is dead: `reconnect()` (`amp.reconnect()` in Python, `a.reconnect()` in MATLAB). From code, `load_config` closes and starts it as its window does, once you confirm ([mcc.md](mcc.md)).

## The `ommm` command and the scripts

- `ommm` prints a snapshot of headstage 1 as JSON (`--headstage 2`: headstage 2's); `ommm --summary` prints a compact box: mode, feedback resistor, holding, command sensitivity, both outputs (signal, scale × gain, low-pass), compensation, and `!!` lines for what `state()` found.
- `ommm [--summary] FILE` prints a saved snapshot instead, as saved (its own `time` and `ommm`), with no Commander, on any OS; in Python `ommm.load_snapshot(FILE)` returns it. Both read a file saved as UTF-16 (`ommm > snapshot.json` in Windows PowerShell 5.1) and refuse a file that is not a snapshot.
- `ommm --examples DIR` copies ommm's examples (`ommm.EXAMPLES`: the four scripts, `mcc/` and `fake/`) into a new folder `DIR`, with no Commander; it refuses a folder that exists.
- The scripts run from the clone, on the desktop, with `uv run --locked python scripts/<name>.py`. Logs and images go to `~/ommm-logs/`, or to `--log-dir DIR`.

| Script | Does | Changes the amplifier |
|---|---|---|
| `watch.py [--seconds N]` | prints and logs every change Commander reports, to check reads against changes made by hand | no |
| `screenshot_commander.py` | saves a PNG of each Commander window, even when covered | no |
| `rig/check_amplifier.py --no-cell-attached` or `--model-cell POSITION` | checks `ommm.Amplifier` against Commander, control by control ([below](#checking-ommm-against-your-commander)) | yes, and puts back what the API can |

### Checking ommm against your Commander

`scripts/rig/check_amplifier.py` runs `ommm.Amplifier` against your Commander control by control, in each mode: every row read, set and set back, refused out of range, off its list and in a mode without it; every checkbox turned over; every button but Reset pressed where Commander has it; `set_mode`, Mode Switching and `make_safe`; the write log read back. It saves one JSON record and exits 1 if a check went otherwise. It changes the amplifier, and puts back what the API can: run it with nothing or a model cell on the headstage, never a cell, and say which, as its record's header keeps it: `--no-cell-attached`, or `--model-cell POSITION` for a model cell and its switch's position (`BATH`, `PATCH` or `CELL`). Run it on the PC, next to Commander, with V-Clamp active, its tab shown and Mode Switching off, and nobody at Commander's window (it clicks the tabs):

```
uv run --locked python scripts/rig/check_amplifier.py --no-cell-attached
uv run --locked python scripts/rig/check_amplifier.py --model-cell CELL
```

Records of past runs are in `tests/data/rig/`; `pytest` replays them on the fake. A record's header names the probe it was recorded under (`header.probe`); the probes themselves are no longer in the repository; what they found is in [quirks.md](quirks.md).

## The snapshot

`ommm.Amplifier().snapshot()` returns one dict; `ommm` prints it as JSON.

```python
import ommm

with ommm.Amplifier() as amp:     # selects headstage 1 of the one 700B (headstage=2 for 2), or raises CommanderError
    snapshot = amp.snapshot()
    mode = amp.get("Mode")        # one control by Commander's label: "V-Clamp", "I-Clamp" or "I = 0"
```

Its readings are the active mode's, since it brings that tab to the front first ([Running next to Commander](#running-next-to-commander)). `scripts/watch.py` reads the tab Commander shows instead and leaves a tab clicked in its window alone; with the other tab shown, the snapshot's `disagreements` say so.

| Key | Holds |
|---|---|
| `schema` | 1, this layout |
| `time` | when it was taken, local time with UTC offset |
| `api_version` | the AxMultiClampMsg API version from the header (`1.0.0.9`) |
| `headstage` | `model`, the API's hardware type as a number, not text (1 = 700B); `serial` (text); `com_port`, `device`; `channel` (1 or 2, the headstage) |
| `demo` | true when the serial starts with `Demo`: Commander's Demo mode, a simulation, so the snapshot never passes for a recording. It has no telegraph, which names a headstage by a numeric serial |
| `readings` | every value the API's getters return, in SI units (V, A, Ω, F, s, Hz), plus `ModeName`, `PrimarySignalName`, `SecondarySignalName` from the header's constants |
| `telegraph` | one telegraph packet, Commander's broadcast of each output's signal and scaling, plus decoded names; `null` if none came within 1 s or in Demo mode, with the reason in `errors` |
| `disagreements` | inconsistencies as sentences, normally none: Commander showing the other mode's tab, and every way the telegraph contradicts the API |
| `not_applicable` | getters that do not apply now, with Commander's code (6004 for another mode's setting) |
| `errors` | real failures, such as a telegraph that did not answer |
| `ommm` | the code that took it: `version`, `commit`, `dirty`, `git_error` (see [Provenance](#provenance)) |

- `ommm.load_snapshot()` returns a file as saved, so a file from before schema 1 lacks `schema`, `demo`, `disagreements` and `ommm`. The one change: the `[]` that MATLAB's `jsonencode` writes for a null, at any depth (a missing telegraph, a null reading, a commit outside a checkout), and for no `errors` or `not_applicable`, reads back as `None` and `{}`, in `ommm.load_snapshot()` and in the fake alike, so a snapshot saved from MATLAB without a telegraph still blocks `state()`.
- Commander stores settings as float32; each double from the API is rounded to the shortest decimal with the same float32 bits (5e-07, not 4.999999987376214e-07), so nothing stored is lost.
- A getter that does not apply reports success and hands back the error code as the value: the integer, or for a double a float32 whose bits are the code (6004 reads as 8.41e-42). Those land in `not_applicable`; `get()` raises `ommm.NotApplicable` for them.
- The telegraph's signal fields are stale from Commander's start until each mode's output signals are set; every write re-selects them first ([Before every write](writes.md#before-every-write)).
- Each call waits up to 3 s for Commander's answer. Every Set and Auto returns well within it ([quirks.md](quirks.md#every-set-and-auto-returns-when-it-is-done)). A snapshot stops at the first timeout instead of waiting out every remaining read.
- In MATLAB's `jsondecode` a JSON `null` becomes `[]`.

**Two snapshots:** `ommm.trial_record(before, after, writes=(), previous=None)` returns `before`, `after`, `changed` and `between`: every reading and telegraph field that differs, the four meter values left out (they move on their own), as `{"readings" | "telegraph": {name: {"before", "after", "source"}}}`, `source` being `"ommm"` or `"gui"` ([The log and trial records](writes.md#the-log-and-trial-records)). `changed` and `between` are `None` unless both their snapshots are given, for example when one could not be taken.

## Provenance

Every snapshot records which ommm took it, under `ommm`; `ommm.provenance()` returns a copy of that dict, and `ommm.__version__` the version:

| Key | Holds |
|---|---|
| `version` | the installed package's version, brought up to date by `uv sync --locked` ([Update](#update)) |
| `commit` | the git commit of ommm's checkout; installed from git into another project (`uv add git+https://...`), the commit it was built from |
| `dirty` | true when tracked files differ from that commit; untracked files (`__pycache__`, logs) don't count. An install from git is never dirty |
| `git_error` | `None`, or why `commit` and `dirty` are `None`: not a git checkout, ommm installed inside another project from a folder or a wheel, git missing, or git refusing a clone it calls "dubious ownership" |

- It is computed once, when ommm is imported, not per snapshot: a long-lived Python host (MATLAB's keeps modules loaded across reconnects) still runs the code it imported after a `git pull`, and the snapshot names that code. After a pull, sync and restart the host ([Update](#update)).
- Git's errors are stored as text and never raised.

## `state()` and `summary()`

`ommm.state(snapshot)` says what a snapshot means for the two outputs, in SI, with `None` for anything unknown:

| Key | Holds |
|---|---|
| `mode` | `"V-Clamp"`, `"I-Clamp"` or `"I = 0"`, from the telegraph; without one (Demo mode, or a `[]` saved from MATLAB), from the API's `Mode`, and the snapshot blocks |
| `feedback_resistor` | Ω (50e6, 500e6, 5e9, 50e9), from `FeedbackResistorVC1` or `FeedbackResistorIC1` by mode ([indexes](#feedback-resistor-range-indexes)) |
| `primary`, `secondary` | `signal` (Commander's name, e.g. `Membrane Current`), `api_name` (the API's, e.g. `VC_MEMBCURRENT`), `gain` (telegraph), `scale` at gain 1 ([output scales](#output-scales-at-gain-1)), `units` (`"V/A"` or `"V/V"`), `lpf` (Hz; 1e5 is bypass), `trusted` (false when the scale is unknown or contradicted) |
| `ext_cmd_sensitivity`, `ext_cmd_units` | the external command sensitivity, V/V in V-Clamp, A/V in I-Clamp; 0 and `None` in I = 0 |
| `membrane_capacitance` | F, from the telegraph (0 without Whole Cell) |
| `blocking`, `problems`, `warnings` | sentences: the wrong tab, an API/telegraph mode mismatch or an incomplete snapshot block; a gain mismatch, a scale contradiction or a 0 command sensitivity outside I = 0 are problems; a stale telegraph signal, a low-pass mismatch and checkboxes worth knowing about that are on, where the mode has them, are warnings |

- `trusted` covers only this output's own scale; check `blocking` first: anything in it (e.g. the other mode's tab in front) overrides trusted.
- Which signal belongs on which output is the caller's to check: `if st["primary"]["signal"] != "Membrane Current": ...`.
- `ommm.summary(snapshot, manual=None)` is the box, built from `state()`, so the two agree; with the other mode's tab shown it gives only the headstage, the mode and the `!!` lines, since every setting read would be that tab's. Its rows are the controls the mode has, by the settings table, as `get()` reads them: in I = 0, which shares the I-Clamp tab, no Holding, Bridge Balance or Pipette Capacitance Neutralization. `manual` holds the settings Commander cannot report, entered by hand: `{"lpf_type_v_clamp": "bessel", "lpf_type_i_clamp": "butterworth"}`; case does not matter, and another key or filter type is an error.

For the fake's `vclamp.json`, `ommm.state(snapshot)` is (the box it gives is in the [README](../README.md#quickstart)):

```python
{'mode': 'V-Clamp',
 'feedback_resistor': 5000000000.0,
 'primary': {'signal': 'Membrane Current',
             'api_name': 'VC_MEMBCURRENT',
             'gain': 2.0,
             'scale': 5000000000.0,
             'units': 'V/A',
             'lpf': 8000.0,
             'trusted': True},
 'secondary': {'signal': 'Membrane Potential',
               'api_name': 'VC_MEMBPOTENTIAL',
               'gain': 5.0,
               'scale': 10,
               'units': 'V/V',
               'lpf': 10000.0,
               'trusted': True},
 'ext_cmd_sensitivity': 0.02,
 'ext_cmd_units': 'V/V',
 'membrane_capacitance': 0.0,
 'blocking': [],
 'problems': [],
 'warnings': []}
```

## Output scales at gain 1

`state()` takes each output's scale from this table, by the API's signal name without its `VC_`/`IC_` prefix, and uses the telegraph's own scale (`dScaleFactor`, `dRawScaleFactor`) only as a cross-check, because the telegraph's signal fields can be stale. The output on the BNC is the signal × scale × gain.

| Commander's signal | API name | Scale at gain 1 |
|---|---|---|
| Membrane Current | `MEMBCURRENT` | the feedback resistor, in V/A (0.5 V/nA at 500 MΩ) |
| Command Current (I-Clamp) | `CMDCURRENT` | the feedback resistor, in V/A |
| External Command Current (I-Clamp) | `EXTCMDCURRENT` | 1 / the external command sensitivity, in V/A (25 V/nA at 40 pA/V) |
| Membrane Potential | `MEMBPOTENTIAL` | 10 V/V |
| Pipette Potential | `PIPPOTENTIAL` | 1 V/V |
| 100x AC Membrane Potential | `100XACMEMBPOTENTIAL` | 100 V/V |
| External Command Potential (V-Clamp) | `EXTCMDPOTENTIAL` | 1 / the external command sensitivity (50 V/V at 20 mV/V) |
| Auxiliary 1, Auxiliary 2 | `AUXILIARY1`, `AUXILIARY2` | none: whatever is on the auxiliary input |

The scales are the telegraph's, read once each signal was set, in both modes. An external command signal gives back the command input's volts; with the sensitivity off (0, as in I = 0) it has no scale, and `state()` says so. The header tests check that every API signal is in this table or auxiliary.

## Feedback resistor range indexes

`FeedbackResistorVC1` and `FeedbackResistorIC1` are a range index, not a resistance. Commander's API can read them but has no setter.

| Index | Feedback resistor | Modes |
|---|---|---|
| 0 | 50 MΩ | V-Clamp, I-Clamp |
| 1 | 500 MΩ | V-Clamp, I-Clamp |
| 2 | 5 GΩ | V-Clamp, I-Clamp |
| 3 | 50 GΩ | V-Clamp only |

Another index makes `state()` block.

## Tests

```
uv run --locked pytest                                                      # any OS, no Commander
OMMM_SDK_DIR="/path/to/MultiClamp 700B Commander" uv run --locked pytest    # adds the header tests
```

In MATLAB, after `uv sync --locked`: `runtests("<ommm>/matlab/tests")` ([matlab.md](matlab.md#tests)).

GitHub runs the Python suite on Windows and Linux, Python 3.12 and 3.14, for every push to `main` or `dev` and every pull request (`.github/workflows/tests.yml`), without the header tests; it also installs ommm from git into an empty environment and checks the commit its provenance names.

Neither suite reaches the DLL calls or the telegraph read, which need Windows and Commander; nothing runs against Commander automatically.

[coming-from-commander.md](coming-from-commander.md) is generated from the settings table (`src/ommm/settings.py`) by `src/ommm/docs.py`: after changing either, run `uv run --locked python -m ommm.docs` and commit the page with it. `tests/test_docs.py` fails while the committed page differs from what they generate.

### The fake

- `ommm.Amplifier(fake=ommm.EXAMPLES / "fake/vclamp.json")` (MATLAB `ommm.Amplifier(Fake=file)`, [Without Commander](matlab.md#without-commander)) serves a saved snapshot in place of Commander, so code that uses ommm runs on any OS, `with` and `load_config` included. ommm ships one snapshot per mode, taken with nothing attached, in `src/ommm/examples/fake/` (`ommm.EXAMPLES / "fake"`): `vclamp.json`, `iclamp.json` and `i0.json`; `other_tab=` (`OtherTab=`) adds one taken with the other tab shown, else that tab holds placeholders. Its `load_config` takes `synthetic.mcc` from the same folder, a test file the amplifier refuses ([mcc.md](mcc.md#the-file)).
- `amp.gui` is the person at Commander's window, in its labels and units: `amp.gui.set("Primary Output Gain", 7, "x")` types 7, Commander keeps 5, and `amp.get("Primary Output Gain", "x")` reads 5.0; `show_tab`, `mode` and `enable` click a tab, a mode button and a checkbox. A click is not logged, so a trial record puts it down to `"gui"`. On Commander, `amp.gui` raises `AttributeError`.
- It is a table of values, not a cell: it measures nothing (the Autos, the meters), keeps a continuous value as sent, as float32, where Commander keeps its own steps, and shows no dialogs. What it models, and the knobs a test turns: the docstring of [`src/ommm/testing/fake.py`](../src/ommm/testing/fake.py).

## What has been tested

- **Versions:** Windows, MultiClamp Commander 2.2.2.2 (API 1.0.0.9), Python 3.14 and MATLAB R2026b; a Python 3.12 `.venv` also loads in R2026b on macOS.
- **On a 700B, headstage 1,** first with nothing attached, then with a PATCH-1U model cell at its BATH, CELL and PATCH positions: every reading and the snapshot; every setting and button through `ommm.Amplifier`, with readback and refusals; mode changes, I = 0 included; Pulse, Zap, Buzz, Clear and a mode change on a DAQ recording.
- **Restarts:** `load_config` with files Commander saved, taking the feedback resistor from 5 GΩ to 500 MΩ and to 50 GΩ and back, with Auto Whole Cell and Rs Compensation at 500 MΩ in between; the check against the file after each start, and its second start, over 22 loads of three saved files with a skip among them; closing and starting Commander without a file through `ommm.process`, from Python and MATLAB; V-Clamp Holding through a Commander restart by ommm and by hand, with `reconnect()` and the first writes after it, on a DAQ recording ([what happens](quirks.md#holding-reads-off-after-a-restart)).
- **The amplifier off and Demo mode:** what ommm does with the amplifier switched off under a running Commander, and with Commander started in Demo mode (clean errors, [quirks.md](quirks.md#connecting-and-restarting)).
- **MATLAB:** the class, and an acquisition program built on it, saving trial records. The class is a thin layer over the Python (argument handling, units and errors, the Python environment), so `scripts/rig/check_amplifier.py` is the control-by-control check for both; the MATLAB suite on the fake covers the layer, and the MATLAB examples run it on the amplifier. There is no MATLAB counterpart of `check_amplifier.py`, by design.
- **Examples:** the four scripts in `src/ommm/examples/`, each run whole from Python or MATLAB on the model cell at CELL.
- **Off the rig:** the Python and MATLAB test suites on macOS against the fake Commander, and the MATLAB suite on Windows; `pytest` also checks Commander's API header when `OMMM_SDK_DIR` is set.
- **Headstage 2:** alone and beside headstage 1, on the fake from Python and MATLAB. On a 700B, unplugged, and plugged in with nothing on it beside headstage 1 on the model cell: Holding, a gain and a mode change on each headstage; Commander's selection from two handles and from two programs; the tabs; the feedback resistors and meters; the telegraph; `load_config` with a file of both headstages and a file of headstage 1 alone. Not supported.
- **Not supported:** the MultiClamp 700A.

Details of each run are kept by the maintainers.

### Planned

- **A real cell**, from an acquisition program.
- **The oscillation killer at work:** Rs Compensation at 500 MΩ stepped to 100 % on the model cell, at CELL and at PATCH with Whole Cell on, did not make it act ([quirks.md](quirks.md#whole-cell-at-500-mω-on-the-model-cell)); a real cell may.

What is still open about Commander is in [quirks.md](quirks.md#not-seen-yet).
