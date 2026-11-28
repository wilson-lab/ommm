import pytest

from ommm import Amplifier, Write, WriteError
from ommm.settings import SETTINGS

BUTTONS = {row.stem for row in SETTINGS if row.kind == "action"}


def sets(fake) -> list[tuple]:
    """The Set calls a FakeCommander was sent, as (function, value)."""
    return [call for call in fake.dll.calls if call[0].startswith("Set")]


def names(amp: Amplifier) -> list[str]:
    return [name for name, *_ in amp.commander.dll.calls]


def logged(amp: Amplifier) -> list[dict]:
    return amp.writes_since(0)[0]


def refused(amp: Amplifier, call, says: str) -> Write:
    """call() is refused, saying `says`, and sends nothing: no Set and no button reaches Commander."""
    sent = len(amp.commander.dll.calls)
    with pytest.raises(WriteError, match=says) as raised:
        call()
    assert raised.value.write.outcome == "refused"
    assert [name for name, *_ in amp.commander.dll.calls[sent:] if name.startswith("Set") or name in BUTTONS] == []
    return raised.value.write


def after_each_set(amp: Amplifier, then):
    """Run then(stem, value) as each Set the fake takes returns: Commander acting on its own, or a click in its
    window before the readback."""
    write = amp.commander.dll.write

    def hooked(stem, value):
        write(stem, value)
        then(stem, value)

    amp.commander.dll.write = hooked


def from_matlab(value, key: str | None = None):
    """A snapshot, log line or list of them as MATLAB hands it back: jsondecode, a.snapshot()'s struct([]) for no errors
    or not_applicable, then jsonencode, which writes every null and struct([]) as [], a one-number list as the
    number, and a whole number below a million with no point (5000.0 as 5000, 1e6 as 1.0E+6), so Python reads it
    back as an int."""
    if value is None or (key in ("errors", "not_applicable") and value == {}):
        return []
    if isinstance(value, dict):
        return {name: from_matlab(item, name) for name, item in value.items()}
    if isinstance(value, list | tuple):
        if len(value) == 1 and isinstance(value[0], int | float) and key != "disagreements":
            return from_matlab(value[0])
        return [from_matlab(item) for item in value]
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e6:
        return int(value)
    return value
