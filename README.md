<p align="center"><img src="docs/ommm-wordmark.svg" alt="ommm: one more MultiClamp manager" width="420"></p>

# ommm

One More MultiClamp Manager. ommm reads and sets a MultiClamp 700B through the MultiClamp Commander that is already running, over Commander's own interfaces (the AxMultiClampMsg API and the telegraph), by Commander's labels with a unit on every value. It records a snapshot of every setting and a log of every write. The main interface is a MATLAB class, `ommm.Amplifier`, over a Python package of the same name, with the same calls in both.

ommm is not a Commander replacement and not an acquisition program. Commander stays the display and the source of truth, and ommm knows nothing about the cell on the pipette.

**Version 0.3.0.** It supports one MultiClamp 700B, headstage 1. Headstage 2's calls are in the API but not supported. It does not support mode switching through the MODE input (the front panel's analog input) or Commander's Auto mode switching ([What ommm does not do](docs/writes.md#what-ommm-does-not-do)).

## Requirements

- **One 700B,** headstage 1. The MultiClamp 700A is not supported.
- Windows, 64-bit Python 3.12 or later, [uv](https://docs.astral.sh/uv/).
- MultiClamp Commander 2.2.1 or later (2.2.1 fixed setting the primary low-pass filter on 64-bit Windows), tested with 2.2.2.2 only. Run ommm in Commander's own desktop session at the same privilege level: not over SSH, not "Run as administrator".
- For the MATLAB class: MATLAB R2024b or later ([versions](docs/install-and-testing.md#python-and-matlab-versions)).

On a Mac or Linux ommm imports, its tests run, it reads saved snapshots, and its fake Commander takes every call. It cannot reach Commander there.

## Install

```
git clone --branch v0.3.0 https://github.com/wilson-lab/ommm
cd ommm
uv sync --locked
uv tool install --editable .    # optional: the `ommm` command
```

Commander's install folder: `OMMM_SDK_DIR` (default `C:\Program Files\Molecular Devices\MultiClamp 700B Commander`; [what ommm takes from it](docs/install-and-testing.md#commanders-install-folder-ommm_sdk_dir)). Releases are listed in the [changelog](CHANGELOG.md).

To update: [Update](docs/install-and-testing.md#update), then restart MATLAB.

## Quickstart

Python (`uv run python` in the clone) reads and writes ([How a write works](docs/writes.md)):

```python
import ommm

amp = ommm.Amplifier()                 # headstage 1 of the one 700B
# amp = ommm.Amplifier(fake=ommm.EXAMPLES / "fake/vclamp.json")  # no Commander
snapshot = amp.snapshot()              # every setting in SI, the telegraph, ommm's version and commit
print(ommm.summary(snapshot))          # the box `ommm --summary` prints
amp.get("Holding", "mV")               # one control, always with a unit
amp.set("Holding", -60, "mV")          # checks first, reads back after, logs the write
amp.enable("Holding", True)            # its checkbox: Holding applies once it is on
amp.set_mode("I-Clamp")                # through I = 0
amp.press("Auto Bridge Balance")       # a button, by its name on Commander's window
```

The lines up to `get` only read; each write after them acts on the amplifier at once. Without Commander (a Mac, say), make the amplifier with the commented line instead, and every line runs on [ommm's fake Commander](docs/install-and-testing.md#the-fake). On a fresh fake, `amp.load_config(ommm.EXAMPLES / "fake/synthetic.mcc", changes=[("Feedback Resistor", 500, "MΩ", "V-Clamp")])` plans a load and `confirmed=True` runs it; `synthetic.mcc` is a test file, refused on the amplifier ([The fake](docs/install-and-testing.md#the-fake)).

On the fake with `vclamp.json`, `print(ommm.summary(snapshot))` prints:

```
======================♡====MultiClamp 700B=====♡======================
= Headstage:            1 (00123456)                                 =
= Mode:                 V-Clamp                                      =
= Feedback Resistor:    5 GΩ                                         =
= Holding:              off, 0 mV                                    =
= External Command Sensitivity: 20 mV/V                              =
= ------------------------------------------------------------------ =
= Primary Output:       Membrane Current                             =
= Primary Units:        10 V/nA (gain 2)                             =
= Primary Output Lowpass Filter: 8 kHz Bessel (from cutoff)          =
= ------------------------------------------------------------------ =
= Secondary Output:     Membrane Potential                           =
= Secondary Units:      50 mV/mV (gain 5)                            =
= Secondary Output Lowpass Filter: 10 kHz single-pole Bessel (fixed) =
= ------------------------------------------------------------------ =
= Pipette Offset:       0 mV                                         =
= Cp Fast Capacitance:  0 pF                                         =
= Cp Slow Capacitance:  0 pF                                         =
= Whole Cell:           off (32.96 pF, 0.4 MΩ)                       =
= Rs Compensation:      off (correction 0%, prediction 0%)           =
======================================================================
```

MATLAB, the same calls ([docs/matlab.md](docs/matlab.md)):

```matlab
addpath(fullfile("<path to ommm>", "matlab"))
a = ommm.Amplifier();               % headstage 1; Python starts from ommm's .venv
s = a.snapshot();                   % every setting in SI units, one telegraph packet, ommm's version and commit
disp(a.summary())                   % the box `ommm --summary` prints
a.get("Holding", "mV")              % one control, always with a unit
w = a.set("Holding", -60, "mV");    % checks first, reads back after, logs; the write as a struct
a.enable("Holding", true);          % its checkbox: Holding applies once it is on
a.set_mode("I-Clamp");              % through I = 0
a.press("Auto Bridge Balance");     % a button, by its name on Commander's window
```

A refused write is an error, `ommm:refused`, with the reason ([Errors](docs/matlab.md#errors)). Without Commander, `a = ommm.Amplifier(Fake=fullfile("<path to ommm>", "src", "ommm", "examples", "fake", "vclamp.json"))` runs every line. On a fresh fake, `a.load_config(fullfile("<path to ommm>", "src", "ommm", "examples", "fake", "synthetic.mcc"), Changes={"Feedback Resistor", 500, "MΩ", "V-Clamp"})` plans a load and `Confirmed=true` runs it.

Longer, commented examples, a cell at a time, in `src/ommm/examples/`: `ommm_example_passive.py` and `.m` (reads only), `ommm_example_active.py` and `.m` (writes and a settings file). Each also runs on the fake. They ship with the package: `ommm.EXAMPLES` is their folder, and `ommm --examples DIR` copies it to a new folder `DIR` of your own.

Command line: `ommm --summary` prints the box, `ommm > snapshot.json` saves the whole snapshot, and `ommm --summary snapshot.json` prints a saved one on any OS ([The `ommm` command](docs/install-and-testing.md#the-ommm-command-and-the-scripts)).

## Scope

ommm works next to Commander's window: change anything from either, in any order. It keeps no copy of Commander's settings and never polls; it brings the active mode's tab to the front, reads before each write, reads back after and logs the write, so a trial record tells ommm's changes from the window's.

Before sending anything it refuses a value outside Commander's documented range or off Commander's list (never snapped to the nearest) and what Commander's window greys out, such as Whole Cell at 5 GΩ. V-Clamp ↔ I-Clamp goes through I = 0. What ommm leaves to your code, and what it never does: [What ommm does not do](docs/writes.md#what-ommm-does-not-do).

The feedback resistor and the Options dialog, which no API function sets, take `load_config`: it shows what will change, then, with `confirmed=True`, restarts Commander with a file you saved with Commander's Save Configuration, about 15 s ([docs/mcc.md](docs/mcc.md)).

What has run on an amplifier, and what only on the fake: [What has been tested](docs/install-and-testing.md#what-has-been-tested).

## Where things are

- `src/ommm/`: the Python package. `amplifier.py` is `ommm.Amplifier` (reads, writes, refusals, readback); `commander.py` and `telegraph.py` talk to Commander's API and telegraph; `settings.py` is the table of every Commander control (label, API name, units, modes, ranges); `mcc.py` and `process.py` load `.mcc` files by restarting Commander; `state.py`, `summary.py` and `checks.py` turn a snapshot into scales and the summary box; `log.py` is the write log; `testing/` is the fake Commander.
- `matlab/+ommm/`: the MATLAB class `ommm.Amplifier`, over the Python package; its tests are in `matlab/tests/`.
- `docs/`: the reference pages listed below.
- `src/ommm/examples/` (`ommm.EXAMPLES`): the four examples in the [Quickstart](#quickstart); `mcc/`: three settings files Commander saved, one setup in each mode; `fake/`: a snapshot per mode and a test settings file, for the fake.
- `scripts/`: `watch.py` prints every change Commander reports; `scripts/rig/check_amplifier.py` checks ommm against your Commander, control by control.
- `tests/`: the pytest suite; `tests/data/` holds the records the fake is checked against.

## Docs

To use ommm, read the [Quickstart](#quickstart) and [How a write works](docs/writes.md); the other pages are reference, for when you need them.

- [Coming from Commander](docs/coming-from-commander.md): every Commander control by its label, with its call, unit, modes and range.
- [How a write works](docs/writes.md): read it before writing: every call and its units, the checks and every refusal, readback and outcomes, failures, error codes and the write log.
- [Settings files and `load_config`](docs/mcc.md): the feedback resistor and the Options dialog, by restarting Commander with a `.mcc` file; three Commander-saved examples in `src/ommm/examples/mcc/`.
- [MATLAB](docs/matlab.md): the `ommm.Amplifier` class: its methods, units and errors, a question before a write, the fake, Commander restarts, trial records, provenance, and how it starts Python.
- [Install, running and testing](docs/install-and-testing.md): install and update, Python and MATLAB versions, running next to Commander, the snapshot, the fake Commander, the tests and what has been tested.
- [Commander 2.2.2.2: behaviour to know](docs/quirks.md): what Commander does when a program drives it, where its own documentation is silent or says otherwise.
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## See also

Other software that reads or controls a MultiClamp through Commander; ommm copies no code from any of them.

- [ACQ4](https://github.com/acq4/acq4) (Python): a MultiClamp driver with the telegraph, inside a full acquisition system.
- [MIES](https://github.com/AllenInstitute/MIES) (Igor Pro): amplifier control for the Allen Institute's patch-clamp pipeline.
- [mcc-xop](https://github.com/AllenInstitute/mcc-xop) (Igor Pro XOP): the AxMultiClampMsg functions for Igor.
- [Symphony](https://github.com/Symphony-DAS/symphony-core) (C#): MultiClamp telegraph support in a data acquisition system.
- [Clampwise](https://github.com/Du5ty0311/Clampwise) (Python): a table of MultiClamp setters and actions.
- [WaveSurfer](https://github.com/JaneliaSciComp/WaveSurfer) (MATLAB): reads the MultiClamp telegraph.
- [ipfx](https://github.com/AllenInstitute/ipfx) (Python): saves MultiClamp settings beside recordings.

## Licence

Written by Stephen Holtz. BSD 3-Clause ([LICENSE](LICENSE)). Commander's SDK files (headers, DLL, manuals) are read from its install folder and never copied into this repository.

MultiClamp, Axon, pCLAMP and Clampex are trademarks of Molecular Devices, LLC. ommm is not affiliated with or endorsed by Molecular Devices.
