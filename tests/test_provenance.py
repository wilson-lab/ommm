import json
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import ommm
from ommm.testing import FakeCommander

VCLAMP = ommm.EXAMPLES / "fake" / "vclamp.json"


def git(directory, *args):
    subprocess.run(["git", "-C", str(directory), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def test_provenance_is_computed_once_at_import():
    found = ommm.provenance()
    assert found.keys() == {"version", "commit", "dirty", "git_error"}
    assert found["version"] == ommm.__version__
    if found["commit"] is None:  # a copy that is not a git checkout, e.g. from an sdist
        assert found["git_error"]
    else:
        assert re.fullmatch(r"[0-9a-f]{40}", found["commit"])
        assert isinstance(found["dirty"], bool)


def test_importing_a_clone_never_installed_says_to_sync_it():
    # -I -S: a Python with no site-packages, so no install of ommm, and the clone's src on its path
    src = Path(ommm.__file__).parents[1]
    run = subprocess.run([sys.executable, "-I", "-S", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import ommm", str(src)],
                         capture_output=True, text=True)
    assert run.returncode == 1
    assert run.stderr.splitlines()[-1] == ("ImportError: ommm is not installed in this Python: run `uv sync --locked` in the "
                                           "clone, then `uv run python` there")


def test_changing_what_provenance_returns_changes_no_later_snapshot():
    ommm.provenance()["version"] = "x"
    assert ommm.provenance()["version"] == ommm.__version__
    assert FakeCommander(VCLAMP).snapshot()["ommm"]["version"] == ommm.__version__


def test_the_namespace_lists_the_public_names():
    assert "Amplifier" in ommm.__all__ and "provenance" in ommm.__all__
    assert not {"json", "subprocess", "Path", "version", "git_state", "find_provenance", "installed_commit", "distribution",
                "without_matlab_empties"} & set(ommm.__all__)
    assert all(hasattr(ommm, name) for name in ommm.__all__)


def test_dirty_counts_tracked_files_only(tmp_path):
    package = tmp_path / "src" / "ommm"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "first")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "x.pyc").write_text("")
    found = ommm.git_state(package)
    assert (len(found["commit"]), found["dirty"], found["git_error"]) == (40, False, None)
    (package / "__init__.py").write_text("x = 1\n")
    assert ommm.git_state(package)["dirty"] is True


def test_outside_a_git_checkout_commit_and_dirty_are_none(tmp_path):
    found = ommm.git_state(tmp_path)
    assert (found["commit"], found["dirty"]) == (None, None)
    assert "not a git repository" in found["git_error"]


def test_inside_another_project_is_not_ommms_checkout(tmp_path):
    package = tmp_path / ".venv" / "lib" / "ommm"
    package.mkdir(parents=True)
    (tmp_path / "README").write_text("")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "README")
    git(tmp_path, "commit", "-q", "-m", "first")
    found = ommm.git_state(package)
    assert (found["commit"], found["dirty"]) == (None, None)
    assert found["git_error"].startswith("not ommm's own checkout")


def direct_url(**kind):
    return json.dumps({"url": "https://github.com/wilson-lab/ommm", **kind})


def test_an_install_from_git_names_the_commit_it_was_built_from(tmp_path):
    commit = "485a642" + "0" * 33
    from_git = direct_url(vcs_info={"vcs": "git", "requested_revision": "v0.2.1", "commit_id": commit})
    assert ommm.find_provenance(tmp_path, from_git) == {"commit": commit, "dirty": False, "git_error": None}


def test_an_install_from_a_folder_or_a_wheel_names_no_commit(tmp_path):
    for other in (None, direct_url(dir_info={}), direct_url(dir_info={"editable": True}), direct_url(archive_info={})):
        found = ommm.find_provenance(tmp_path, other)
        assert (found["commit"], found["dirty"]) == (None, None)
        assert "not a git repository" in found["git_error"]


def test_ommms_own_checkout_comes_before_the_install_record(tmp_path):
    package = tmp_path / "src" / "ommm"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "first")
    stale = direct_url(vcs_info={"vcs": "git", "commit_id": "0" * 40})
    assert ommm.find_provenance(package, stale) == ommm.git_state(package)


def test_snapshot_records_schema_demo_and_provenance():
    snapshot = FakeCommander(VCLAMP).snapshot()
    assert (snapshot["schema"], snapshot["demo"], snapshot["ommm"]) == (1, False, ommm.provenance())
    assert snapshot["readings"]["ModeName"] == "VCLAMP"


def test_demo_mode_snapshot_has_no_telegraph_and_says_why():
    # Commander's Demo mode has a serial like "Demo1"; the telegraph packs the serial as a number
    demo = FakeCommander(VCLAMP)
    demo.dll.headstages = [replace(demo.headstage, serial="Demo1")]
    demo.select()
    snapshot = demo.snapshot()
    assert (snapshot["demo"], snapshot["telegraph"]) == (True, None)
    assert snapshot["errors"] == {"telegraph": "no telegraph for a non-numeric (Demo mode) serial"}
