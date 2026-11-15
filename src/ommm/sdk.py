"""Commander's own files (the AxMultiClampMsg header and DLL, the telegraph header, MC700B.exe), read or run where
Commander installed them and never copied into ommm. OMMM_SDK_DIR names another Commander install folder, e.g. a
copy of one for the header tests on a Mac."""

import os
from pathlib import Path

INSTALL_DIR = r"C:\Program Files\Molecular Devices\MultiClamp 700B Commander"


def install_dir() -> Path:
    """Commander's install folder: OMMM_SDK_DIR if set, else Commander's default."""
    return Path(os.environ.get("OMMM_SDK_DIR") or INSTALL_DIR)


def sdk_file(name: str) -> Path:
    """'AxMultiClampMsg/AxMultiClampMsg.h' -> that file in the install folder's '3rd Party Support'."""
    return install_dir() / "3rd Party Support" / name


def constant_name(constants: dict[str, int], prefix: str, value: int) -> str | None:
    """The name of a header constant by its prefix and value, without the prefix: ("MODE_", 1) -> "ICLAMP"."""
    return next((name.removeprefix(prefix) for name, v in constants.items() if name.startswith(prefix) and v == value), None)
