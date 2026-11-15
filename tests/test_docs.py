"""docs/coming-from-commander.md is generated from the settings table; after changing the table, regenerate the page
with `uv run python -m ommm.docs` and commit both. The README's summary box and the docs' state() example are
what ommm prints for the fake's vclamp.json (ommm.EXAMPLES)."""

import os
import pprint
from pathlib import Path

import pytest

import ommm
from ommm.commander import parse_header
from ommm.docs import PAGE, api_functions, coming_from_commander
from ommm.sdk import sdk_file


def test_the_committed_page_is_the_generated_one():
    assert PAGE.read_text(encoding="utf-8") == coming_from_commander(), (
        "docs/coming-from-commander.md differs from the settings table: run `uv run python -m ommm.docs` and commit it"
    )


@pytest.mark.skipif(not os.environ.get("OMMM_SDK_DIR"), reason="OMMM_SDK_DIR is not set")
def test_the_appendix_lists_each_header_function_once():
    functions, _, _ = parse_header(sdk_file("AxMultiClampMsg/AxMultiClampMsg.h").read_text())
    listed = [name for names, _ in api_functions() for name in names]
    assert sorted(listed) == sorted(functions)


def test_the_page_shows_calls_as_written():
    """An f-string turns a literal {...} into Ellipsis, as it once did to MATLAB's Changes= example."""
    assert "Ellipsis" not in coming_from_commander()


ROOT = Path(__file__).parents[1]


def vclamp_snapshot():
    return ommm.Amplifier(fake=ommm.EXAMPLES / "fake" / "vclamp.json").snapshot()


def test_the_readme_box_is_what_summary_prints():
    assert f"```\n{ommm.summary(vclamp_snapshot())}\n```" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_state_example_is_what_state_returns():
    state = pprint.pformat(ommm.state(vclamp_snapshot()), width=110, sort_dicts=False)
    assert f"```python\n{state}\n```" in (ROOT / "docs" / "install-and-testing.md").read_text(encoding="utf-8")


def test_the_page_states_facts_alone_and_its_calls_read_the_same_in_matlab():
    page = coming_from_commander()
    for words in (" yet", "so far", "seen on headstage", "relaunch", "today"):
        assert words not in page, words
    calls = [line.split(" | ")[1] for line in page.splitlines() if line.startswith("| ") and "`enable(" in line]
    assert calls and not any("True" in call or "False" in call for call in calls)
