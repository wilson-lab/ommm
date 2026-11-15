# Contributing to ommm

Report problems and propose changes through [issues](https://github.com/wilson-lab/ommm/issues) and pull requests. For anything larger than a fix, open an issue first; what ommm does not take is in [Scope](README.md#scope).

## Reporting a problem

Say what you ran, what you expected and what happened: the Python traceback, or the MATLAB `ommm:` identifier and its message. Attach:

- the snapshot, `ommm > snapshot.json` (`uv run --locked ommm > snapshot.json` in the clone);
- the write-log lines involved, from `~/ommm-logs/<serial>.jsonl`, and for `load_config` the `.mcc` file;
- what was on the headstage: nothing, a model cell and its switch position, or a cell;
- your Windows, Python and MATLAB versions, which the snapshot does not record.

Replace your amplifier's serial with `00123456` before you attach anything: it is in the snapshot, the summary box, every write-log line and the log's file name, and in the title bar of a Commander screenshot.

## Proposing a change

- Clone without `--branch`, so you start from `main` ([Install](docs/install-and-testing.md#install)), and open one pull request per change, to `main`; it is merged with a merge commit, so squash your own commits first if you want fewer.
- Run the Python tests before you open it, and the MATLAB tests too if the change touches `matlab/` or what the class calls ([Tests](docs/install-and-testing.md#tests)). GitHub runs the Python tests on every pull request; nothing runs the MATLAB ones for you.
- A fix comes with a test on [the fake](docs/install-and-testing.md#the-fake) that fails without it.
- **Neither suite reaches Commander:** if a change obviously affects what ommm sends Commander or reads back, try to run it on a 700B with `scripts/rig/check_amplifier.py` ([the scripts](docs/install-and-testing.md#the-ommm-command-and-the-scripts)). The pull request says what ran there, with Commander's version and what was on the headstage, or that nothing did.
- **`check_amplifier.py` changes the amplifier's settings:** run it with nothing on the headstage (`--no-cell-attached`) or a model cell (`--model-cell BATH`, `PATCH` or `CELL`), never a cell, and with nobody at Commander's window.

## Never commit

- **Commander's SDK files stay in Commander's install folder:** the headers, the DLL, the manuals and the Help pages ([Commander's install folder](docs/install-and-testing.md#commanders-install-folder-ommm_sdk_dir)).
- **No serial numbers, PC names or user names:** the snapshots, logs and records in the repository use serial `00123456`.
