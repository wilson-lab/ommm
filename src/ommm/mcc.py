"""Commander's .mcc settings files, as Amplifier.load_config reads and changes them.

A .mcc file is a Windows INI file that Commander's Save Configuration button writes: [SECTION] lines, then
AXMCD_FIELD_<name>=<value> lines, with CRLF line endings. ommm reads it line by line and changes one line per value,
never through configparser, which lowercases keys and rewrites the lines it does not change. Only whole files load:
Commander refused a file holding one key.
"""

from pathlib import Path

PREFIX = "AXMCD_FIELD_"
FIRST = "MC700_GLOBAL"  # the section every Commander-saved file starts with
# the mode the file loads in, by MCCMSG_MODE_* id: 0 V-Clamp, 1 I-Clamp, 2 I = 0; the files in ommm.EXAMPLES / "mcc", saved
# in each mode, differ only here
MODE_KEY = "MODE_SLCT"
# how ommm's test files in Commander's layout start (examples/fake/synthetic.mcc); a saved file starts with [MC700_GLOBAL]
SYNTHETIC = "; synthetic"
# besides the mode and the feedback resistors, what load_config compares with the file after a start, in the tab the
# active mode shows, by API name: its key in that tab's section. Each read back as the file holds it after every load
# on the rig; after a start that did not apply the file Commander showed Pulse 0 and 100 µs, and Cp Fast and Slow as
# before the close. Holding and Pipette Offset read 0 after any load, the output signals, gains and filters are
# positions in lists ommm does not know, and Cp Slow Tau reads x20 by another key, so none of those is compared.
READ_BACK = {
    "V-Clamp": {
        "FastCompCap": "COMP_FST_MAG", "FastCompTau": "COMP_FST_TAU", "SlowCompCap": "COMP_SLW_MAG",
        "PulseAmplitude": "TESTSIG_PULSE_AMP", "PulseDuration": "TESTSIG_PULSE_DUR", "TestSignalAmplitude": "TESTSIG_AMP",
        "RsCompBandwidth": "RSCOMP_BNDWDTH", "OscKillerEnable": "OSCKILLER_ENBL",
    },
    "I-Clamp": {
        "PulseAmplitude": "TESTSIG_PULSE_AMP", "PulseDuration": "TESTSIG_PULSE_DUR", "TestSignalAmplitude": "TESTSIG_AMP",
        "BuzzDuration": "TESTSIG_BUZZ_DUR", "OscKillerEnable": "OSCKILLER_ENBL", "NeutralizationEnable": "COMP_CAP_NEUT_ENBL",
    },
}


def channel(headstage: int) -> str:
    """A headstage's section above its tabs': MC700_CHANNEL1, or MC700_CHANNEL2 on headstage 2."""
    return f"MC700_CHANNEL{headstage}"


def tab_sections(headstage: int) -> dict[str, str]:
    """Each tab's section on a headstage; I = 0 shares I-Clamp's."""
    return {"V-Clamp": f"{channel(headstage)}_VCLAMP", "I-Clamp": f"{channel(headstage)}_ICLAMP"}


def read(path: Path) -> str:
    """A file's text with its own line endings; latin-1 keeps every byte as it is."""
    return Path(path).read_bytes().decode("latin-1")


def write(path: Path, text: str):
    Path(path).write_bytes(text.encode("latin-1"))


def values(text: str) -> dict[tuple[str, str], str]:
    """{(section, key): value} for every AXMCD_FIELD_ line, the key without its prefix and the value as written; a key
    twice in a section keeps the first, as Windows reads it."""
    found, section = {}, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line.strip("[]")
        elif line.startswith(PREFIX) and "=" in line:
            key, _, value = line.partition("=")
            found.setdefault((section, key.removeprefix(PREFIX).strip()), value.strip())
    return found


def parsed(value: str) -> bool | float:
    """A value as written, TRUE, FALSE or a number such as -2.50000000e-002, as the API reads it."""
    switches = {"TRUE": True, "FALSE": False}
    return switches[value] if value in switches else float(value)


def patched(text: str, section: str, key: str, value: str) -> str:
    """The text with one key's value changed in one section: the first such line, its line ending kept, every other
    byte as it was. A key the section does not hold raises ValueError: ommm changes only what the file holds."""
    lines, current = text.splitlines(keepends=True), None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            current = stripped.strip("[]")
        elif current == section and stripped.partition("=")[0].strip() == PREFIX + key:
            body = line.rstrip("\r\n")
            lines[i] = body.partition("=")[0] + "=" + value + line[len(body):]
            return "".join(lines)
    raise ValueError(f"the file has no {PREFIX}{key} in [{section}]")
