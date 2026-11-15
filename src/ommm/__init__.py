"""ommm: read and set one MultiClamp 700B, headstage 1, through the running MultiClamp Commander; headstage 2's calls
are in the API but not supported."""

import json
import subprocess
from importlib.metadata import distribution
from pathlib import Path

from ommm import testing  # so ommm.testing.FakeCommander works after `import ommm`
from ommm.amplifier import Amplifier, Write, WriteError
from ommm.commander import CommanderError, NotApplicable
from ommm.log import trial_record
from ommm.state import state
from ommm.summary import summary

__all__ = [
    "EXAMPLES",
    "Amplifier",
    "CommanderError",
    "NotApplicable",
    "Write",
    "WriteError",
    "load_snapshot",
    "provenance",
    "state",
    "summary",
    "testing",
    "trial_record",
]

# the folder the package ships: the four example scripts, mcc/ (three settings files Commander saved) and fake/
# (a snapshot per mode for Amplifier(fake=...), and synthetic.mcc, a test settings file for the fake only)
EXAMPLES = Path(__file__).parent / "examples"


def git_state(package_dir: Path) -> dict:
    """The commit of ommm's checkout and whether tracked files differ from it (untracked ones don't count).
    Outside ommm's own checkout, or when git fails ("dubious ownership", no git), commit and dirty are
    None and git_error says why."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(package_dir), *args],
            capture_output=True,
            text=True,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # no console window flashing on Windows
        ).stdout

    try:
        top, commit = git("rev-parse", "--show-toplevel", "HEAD").splitlines()
        status = git("status", "--porcelain", "--untracked-files=no")
    except subprocess.CalledProcessError as error:
        return {"commit": None, "dirty": None, "git_error": error.stderr.strip()}
    except OSError as error:  # no git on PATH
        return {"commit": None, "dirty": None, "git_error": str(error)}
    if Path(top, "src", "ommm").resolve() != package_dir.resolve():  # e.g. installed into another project's .venv
        return {"commit": None, "dirty": None, "git_error": f"not ommm's own checkout: {top}"}
    return {"commit": commit, "dirty": bool(status.strip()), "git_error": None}


def installed_commit(direct_url: str | None) -> str | None:
    """The commit an install from git was built from (`uv add git+https://...`), read from the direct_url.json the
    installer leaves beside the package's metadata; None for any other install (a folder, an editable one, a wheel)."""
    if direct_url is None:
        return None
    return json.loads(direct_url).get("vcs_info", {}).get("commit_id")


def find_provenance(package_dir: Path, direct_url: str | None) -> dict:
    """git_state in ommm's own checkout; where git names no commit, the commit an install from git was built from,
    which is never dirty: the installer built it from that commit's files."""
    found = git_state(package_dir)
    if found["commit"] is None and (commit := installed_commit(direct_url)):
        return {"commit": commit, "dirty": False, "git_error": None}
    return found


# once, at import: a long-lived host (MATLAB's Python) keeps this code loaded after a git pull, and
# the snapshot must name the commit that is running, not the one on disk
_INSTALLED = distribution("ommm")
__version__ = _INSTALLED.version
_PROVENANCE = {"version": __version__, **find_provenance(Path(__file__).parent, _INSTALLED.read_text("direct_url.json"))}


def provenance() -> dict:
    """ommm's version, git commit and dirty flag, as every snapshot records them under "ommm"; a copy each call."""
    return dict(_PROVENANCE)


def load_snapshot(path: str | Path) -> dict:
    """A saved snapshot (`ommm > snapshot.json`), as saved: its own time and provenance. Read as bytes, so
    json finds the encoding: Windows PowerShell 5.1 writes UTF-16."""
    try:
        snapshot = json.loads(Path(path).read_bytes())
    except json.JSONDecodeError as error:  # its message names no file
        raise ValueError(f"{path} is not an ommm snapshot: not JSON ({error})") from None
    missing = [key for key in ("headstage", "readings", "telegraph") if key not in snapshot]
    if missing:
        raise ValueError(f"{path} is not an ommm snapshot: it has no {', '.join(missing)}")
    return without_matlab_empties(snapshot)


# the keys whose [] from MATLAB is an empty list or dict; every other [] is a null
MATLAB_EMPTIES = {"disagreements": list, "steps": list, "telegraph_checks": list, "errors": dict, "not_applicable": dict, "also": dict, "depends": dict}


def without_matlab_empties(value):
    """A snapshot, a write log line or a list of either, as MATLAB's jsonencode wrote it, with each [] read back as
    Python's: no errors, not_applicable, also or depends is {}, no disagreements, steps or telegraph_checks is [], and any other [] is
    the null it was, at any depth: no telegraph, a null reading (a *Name whose ID matched no header constant), a
    commit outside a checkout, a button's after, a load's stem."""
    if isinstance(value, list):
        return [None if item == [] else without_matlab_empties(item) for item in value]
    if isinstance(value, dict):
        return {key: (MATLAB_EMPTIES[key]() if key in MATLAB_EMPTIES else None) if item == [] else without_matlab_empties(item)
                for key, item in value.items()}
    return value
