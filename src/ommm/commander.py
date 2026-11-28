"""MultiClamp 700B readout and control through the running MultiClamp Commander.

AxMultiClampMsg.dll (Molecular Devices' "3rd Party Support" API) sends each call as a Windows message
to MultiClamp Commander, which applies it as if clicked, so Commander stays the display and keeps
broadcasting telegraphs. Commander must be running in the same Windows session as this process
(so not over SSH), and this process must not be elevated when Commander isn't ("Run as administrator").

Function signatures come from the vendor header installed next to the DLL (ommm.sdk), not the PDF
manual, which has type typos (SetHolding takes a double, not a BOOL).
"""

import ctypes
import os
import re
import struct
import sys
from ctypes import wintypes
from dataclasses import asdict, dataclass, replace
from datetime import datetime

import ommm
from ommm import telegraph
from ommm.checks import disagreements
from ommm.settings import HEADSTAGES, VC, feedback_resistor
from ommm.sdk import constant_name, sdk_file

C_TYPES = {
    "HMCCMSG": ctypes.c_void_p,
    "BOOL": ctypes.c_int,
    "UINT": ctypes.c_uint,
    "int": ctypes.c_int,
    "double": ctypes.c_double,
    "LPCSTR": ctypes.c_char_p,
    "LPSTR": ctypes.POINTER(ctypes.c_char),
    "void": None,
}

DECLARATION = re.compile(r"^AXMCCMSG\s+(\w+)\s+WINAPI\s+(?:EXPORT\s+)?MCCMSG_(\w+)\((.*)\);", re.MULTILINE)
CONSTANT = re.compile(r"^const\s+(?:UINT|int)\s+MCCMSG_(\w+)\s*=\s*(\d+);", re.MULTILINE)
VERSION = re.compile(r'#define\s+MCCMSG_APIVERSION_STR\s+"([^"]+)"')
SNAPSHOT_SCHEMA = 1  # the snapshot's layout; when it goes up is in CHANGELOG.md


def parse_header(text: str) -> tuple[dict[str, tuple[str, list[str]]], dict[str, int], str]:
    """Functions as {name: (return type, [param declarations])}, constants, and the API version."""
    functions = {
        name: (restype, [param.strip() for param in params.split(",")])
        for restype, name, params in DECLARATION.findall(text)
    }
    constants = {name: int(value) for name, value in CONSTANT.findall(text)}
    return functions, constants, VERSION.search(text).group(1)


def to_ctype(param: str):
    """'UINT *puVal' -> POINTER(c_uint); string buffers ('char *', LPSTR) take create_string_buffer."""
    c_type = param.split()[0]
    if c_type == "char":
        return ctypes.POINTER(ctypes.c_char)
    if "*" in param:
        return ctypes.POINTER(C_TYPES[c_type])
    return C_TYPES[c_type]


class CommanderError(RuntimeError):
    """Commander's failure: its text and code; `function` is the call that failed, kept out of the message."""

    def __init__(self, function: str, code: int | None, text: str):
        super().__init__(text + ("" if code is None else f" ({code})"))
        self.function, self.code = function, code


class NotApplicable(CommanderError):
    """A getter that doesn't apply to the current mode or headstage (see disguised_error), or the current meter while
    Irms Meter shows the RMS current noise in its place."""


def shortest_float32(value: float) -> float:
    """The shortest decimal with the same float32 bits as value.

    Commander keeps its settings as float32, so the doubles the API returns carry conversion
    tails (5e-07 arrives as 4.999999987376214e-07); this drops them without losing anything stored.
    """
    bits = struct.pack("<f", value)
    for digits in range(1, 10):
        rounded = float(f"{value:.{digits}g}")
        if struct.pack("<f", rounded) == bits:
            return rounded
    return value


def disguised_error(raw: float) -> int | None:
    """The MCCMSG_ERROR_* code Commander returned in place of a value, if any.

    A getter that doesn't apply (an I-Clamp setting read in V-Clamp, the other channel's
    feedback resistor) still reports success but hands back the error code as the value:
    as the integer itself, or for doubles as a float32 whose bits are that integer (6004 -> 8.41e-42).
    """
    code = raw if isinstance(raw, int) else struct.unpack("<I", struct.pack("<f", raw))[0]
    return code if 6001 <= code <= 6006 else None


def changes(before: dict, after: dict) -> dict:
    """Readings and telegraph fields that differ between two snapshots, as {section: {name: [before, after]}}.

    Meter values are left out: they are live measurements and move on their own.
    """
    changed = {}
    for section in ("readings", "telegraph"):
        old, new = before[section] or {}, after[section] or {}
        diffs = {
            key: [old.get(key), new.get(key)]
            for key in sorted(old.keys() | new.keys())
            if not key.startswith("MeterValue") and old.get(key) != new.get(key)
        }
        if diffs:
            changed[section] = diffs
    return changed


@dataclass(frozen=True)
class Headstage:
    model: int
    serial: str
    com_port: int
    device: int
    channel: int


# what reads the other headstage whichever is selected, left out of a headstage's snapshot
OTHER_HEADSTAGE_GETTERS = {
    headstage: {"Get" + feedback_resistor(mode, other) for mode in ("V-Clamp", "I-Clamp") for other in HEADSTAGES if other != headstage}
    for headstage in HEADSTAGES
}
MCCCOMMANDFAIL = 6006  # MCCMSG_ERROR_MCCCOMMANDFAIL: what a headstage that is not connected answers
# Commander's hidden window, found by its title, not as a class name, which other programs (Clampwise, MIES) take as
# "Commander is running"; it goes as Commander exits and is back before the API answers (docs/quirks.md, Closing and
# starting Commander)
STARTUP_WINDOW = "Invisible MultiClamp Startup Window"
CLOSED = "Commander was closed or restarted: reconnect() (amp.reconnect() in Python, a.reconnect() in MATLAB)"


def need_windows():
    """Off Windows, what Commander() and ommm.process's calls into Windows raise."""
    if sys.platform != "win32":
        raise CommanderError(
            "Commander",
            None,
            "needs Windows, where MultiClamp Commander runs; elsewhere read a saved snapshot: "
            "`ommm --summary FILE`, ommm.load_snapshot(FILE) in Python, ommm.Amplifier(Fake=FILE) in MATLAB; "
            "try the writes on it in Python with ommm.Amplifier(fake=FILE)",
        )


if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32")
    user32.FindWindowW.restype, user32.FindWindowW.argtypes = wintypes.HWND, [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


class DLL:
    """AxMultiClampMsg.dll, every function typed from its header, behind one call(name, *args): all Commander
    sends goes through it. ommm.testing.fake.FakeDLL stands in for it off Windows."""

    def __init__(self):
        header, library = sdk_file("AxMultiClampMsg/AxMultiClampMsg.h"), sdk_file("AxMultiClampMsg/AxMultiClampMsg.dll")
        for path in (header, library, sdk_file(telegraph.HEADER)):  # the telegraph's is read later, at its first packet
            if not path.is_file():
                raise CommanderError("Commander", None, f"{path.name} is not in {path.parent}: set OMMM_SDK_DIR to Commander's install folder")
        self.functions, self.constants, self.api_version = parse_header(header.read_text())
        try:
            self.lib = ctypes.WinDLL(str(library))
        except OSError as error:  # a 32-bit or broken DLL, or a DLL it depends on missing (FileNotFoundError)
            raise CommanderError("Commander", None, f"{library} does not load ({error}): set OMMM_SDK_DIR to Commander's "
                                 "install folder") from None
        for name, (restype, params) in self.functions.items():
            func = getattr(self.lib, "MCCMSG_" + name)
            func.restype = C_TYPES[restype]
            func.argtypes = [to_ctype(param) for param in params]

        if not self.lib.MCCMSG_CheckAPIVersion(self.api_version.encode()):
            raise CommanderError("CheckAPIVersion", None, f"AxMultiClampMsg.dll does not match its header's API version {self.api_version}")
        error = ctypes.c_int()
        self.handle = self.lib.MCCMSG_CreateObject(ctypes.byref(error))
        if not self.handle:
            raise CommanderError("CreateObject", error.value, constant_name(self.constants, "ERROR_", error.value))

    def call(self, name: str, *args):
        """Call MCCMSG_<name>(handle, *args, &error); raise with Commander's error text on failure."""
        self.functions[name]  # only call functions whose argtypes came from the header
        error = ctypes.c_int()
        if not getattr(self.lib, "MCCMSG_" + name)(self.handle, *args, ctypes.byref(error)):
            text = ctypes.create_string_buffer(256)
            self.lib.MCCMSG_BuildErrorText(self.handle, error.value, text, len(text))
            message = text.value.decode(errors="replace")
            if error.value == 0:  # Commander failed without setting a code: the amplifier switched off, or Demo mode
                message += ": Commander answers so with the amplifier switched off, or in Demo mode"
            raise CommanderError(name, error.value, f"{name} failed: {message}")

    def close(self):
        """Destroy the handle, once: a second close does nothing."""
        if self.handle:
            self.lib.MCCMSG_DestroyObject(self.handle)
            self.handle = None

    @staticmethod
    def commander_pid() -> int | None:
        """The process id of the Commander running in this desktop session, by its hidden startup window's title; None
        when there is none. Asks Windows, not Commander, so it answers at once."""
        window = user32.FindWindowW(None, STARTUP_WINDOW)
        if not window:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        return pid.value


class Commander:
    """One message handler talking to Commander, pointed at one headstage of the one 700B when made: headstage 1, or
    2 when asked.

    dll and telegraph are what it talks through: AxMultiClampMsg.dll and the telegraph module, or for tests
    ommm.testing.fake's FakeDLL and FakeTelegraph (ommm.testing.FakeCommander makes both from a snapshot)."""

    def __init__(self, dll=None, telegraph=telegraph, headstage: int = 1):
        if headstage not in HEADSTAGES or isinstance(headstage, bool):
            raise ValueError(f"headstage is 1 or 2, the 700B's two, not {headstage!r}")
        self.channel = int(headstage)  # MATLAB passes 2.0
        if dll is None:
            need_windows()
            dll = DLL()
        self.dll, self.telegraph = dll, telegraph
        self.functions, self.constants, self.api_version = dll.functions, dll.constants, dll.api_version
        try:
            self._call("SetTimeOut", 3000)  # ms each call waits for Commander's answer
            self.select()
        except Exception:
            self.close()
            raise

    def _call(self, name: str, *args):
        """Call MCCMSG_<name>(handle, *args, &error); raise with Commander's error text on failure. Private: it sends
        any function the header declares, buttons included, unchecked; ommm.Amplifier is the checked way."""
        self.dll.call(name, *args)

    def get(self, name: str, *args):
        """One Get<name> reading by its API name, e.g. get("Mode") or get("MeterValue", 0)."""
        if "Get" + name not in self.functions:
            raise ValueError(f"get({name!r}): there is no Get{name}")
        out_param = self.functions["Get" + name][1][1]
        out = to_ctype(out_param)._type_()
        self._call("Get" + name, ctypes.byref(out), *args)
        if code := disguised_error(out.value):
            raise NotApplicable("Get" + name, code, f"Get{name} does not apply now: {self.constant_name('ERROR_', code)}")
        if out_param.startswith("BOOL"):
            return bool(out.value)
        if out_param.startswith("double"):
            return shortest_float32(out.value)
        return out.value

    def _set(self, name: str, value):
        """One raw Set<name> call by the API name, with the API's own value and no checks: _set("Holding", -0.06) is
        -60 mV in V-Clamp, and _set("Holding", -60) asks for -60 V. Private, for check_amplifier.py's put-back and the
        tests; ommm.Amplifier.set is the checked way. Seal Test and Tuning frequency go in Hz, as get gives them: _set
        sends their period, which is what SetTestSignalFrequency takes on a 700B, though the manual says Hertz
        (docs/quirks.md, Seal Test and Tuning frequency are set as a period)."""
        if name == "TestSignalFrequency":
            value = 1 / value
        self._call("Set" + name, value)

    def constant_name(self, prefix: str, value: int) -> str | None:
        return constant_name(self.constants, prefix, value)

    def headstages(self) -> list[Headstage]:
        """Every headstage of every amplifier Commander knows about."""
        found = []
        while True:
            model, com_port, device, channel = (ctypes.c_uint() for _ in range(4))
            serial = ctypes.create_string_buffer(self.constants["SERIALNUM_SIZE"])
            args = (ctypes.byref(model), serial, len(serial), ctypes.byref(com_port), ctypes.byref(device), ctypes.byref(channel))
            try:
                self._call("FindNextMultiClamp" if found else "FindFirstMultiClamp", *args)
            except CommanderError as error:
                if error.code == self.constants["ERROR_NOERROR"]:  # FindNext "fails" with it at the end of the list
                    return found  # FindFirst with no amplifier too, a guess: not tried
                if error.code != self.constants["ERROR_MCCNOTOPEN"]:
                    raise
                real = isinstance(self.dll, DLL)  # the fake's 6002 says nothing about this machine
                if real and "SSH_CONNECTION" in os.environ:
                    text = ("Commander not found, maybe because this is an SSH session, which runs apart from the desktop "
                            "where Commander is. Run from a normal terminal on the PC's desktop")
                elif real and ctypes.windll.shell32.IsUserAnAdmin():
                    text = ("Commander not found, maybe because this process runs as administrator, and Windows blocks a "
                            "non-elevated Commander from answering it. Run from a normal terminal on the PC's desktop")
                else:
                    text = "Commander not found: start MultiClamp Commander on this PC's desktop (not elevated), then try again"
                raise CommanderError("FindFirstMultiClamp", error.code, text) from None
            found.append(Headstage(model.value, serial.value.decode(), com_port.value, device.value, channel.value))

    def select(self) -> Headstage:
        """The headstage asked for (1 unless Commander(headstage=2)) of the one MultiClamp 700B Commander runs; refuses
        if there are none or several, or when the headstage is not connected: Commander does not list it (as with it
        unplugged), or lists it and answers its feedback resistor with 6006.
        Commander() calls it, so it is needed again only to re-select on the same handle. Listing the amplifiers takes
        about 1 s."""
        listed = [h for h in self.headstages() if h.model == self.constants["HW_TYPE_MC700B"]]
        serials = sorted({h.serial for h in listed})
        if not serials:
            raise CommanderError("select", None, "Commander lists no MultiClamp 700B")
        if len(serials) > 1:
            raise CommanderError("select", None,
                                 f"ommm drives one MultiClamp 700B; Commander lists {len(serials)}: serials {', '.join(serials)}")
        matches = [h for h in listed if h.channel == self.channel]
        if not matches:
            others = " and ".join(str(h.channel) for h in listed)
            raise CommanderError("select", None,
                                 f"headstage {self.channel} is not connected: Commander lists only headstage {others}")
        self.headstage = matches[0]
        self.show_active_tab()
        try:
            self.get(feedback_resistor(VC, self.channel))
        except NotApplicable as error:
            if error.code == MCCCOMMANDFAIL:
                raise CommanderError("select", None, f"headstage {self.channel} is not connected: Commander answers "
                                     "its feedback resistor with 6006 (MCCCOMMANDFAIL)") from None
        except CommanderError:  # the amplifier off, or Demo mode: every call fails; a read or snapshot says why
            pass
        return self.headstage

    def other_headstage(self, *stems: str) -> dict | None:
        """The other headstage of this 700B, read by its API names: it is selected for a moment, its active mode's tab
        in front, then this one again. A reading that does not apply is None. None when the other headstage is not
        connected (its feedback resistor answers 6006). Reads only; load_config uses it, as a restart reaches both."""
        h = self.headstage
        other = replace(h, channel=next(n for n in HEADSTAGES if n != h.channel))
        try:
            try:
                self._call("SelectMultiClamp", other.model, ctypes.create_string_buffer(other.serial.encode()),
                           other.com_port, other.device, other.channel)
            except CommanderError as error:
                # with headstage 2 unplugged Commander lists headstage 1 alone and refuses to select 2 with 6002;
                # 6004 and 6006 a guess. A Commander that has gone fails the select of this headstage
                # after it too, which raises
                if error.code in (self.constants["ERROR_MCCNOTOPEN"], self.constants["ERROR_INVALIDPARAMETER"], MCCCOMMANDFAIL):
                    return None
                raise
            try:
                self.get(feedback_resistor(VC, other.channel))
            except NotApplicable as error:
                if error.code == MCCCOMMANDFAIL:
                    return None
            readings = {}
            for stem in stems:
                try:
                    readings[stem] = self.get(stem)
                except NotApplicable:
                    readings[stem] = None
            return readings
        finally:
            self.show_active_tab()

    def show_active_tab(self):
        """SelectMultiClamp on the headstage found at connect, which brings the active mode's tab to the front in
        0.1-8 ms, so the reads and Sets after it act on the active mode's tab."""
        h = self.headstage
        try:
            self._call("SelectMultiClamp", h.model, ctypes.create_string_buffer(h.serial.encode()), h.com_port, h.device, h.channel)
        except CommanderError as error:
            if error.code == self.constants["ERROR_MCCNOTOPEN"]:  # a handle that worked at connect
                raise CommanderError("SelectMultiClamp", error.code, CLOSED) from None
            raise

    def snapshot(self, show_active_tab: bool = True) -> dict:
        """Every reading the API offers for the selected headstage, in SI units, plus one telegraph
        packet for what the API can't report (command sensitivity, output scale factors). The four meters are both
        headstages': MeterValue1 and 2 headstage 1's, 3 and 4 headstage 2's.

        It brings the active mode's tab to the front first (show_active_tab), so the readings are the active
        mode's; show_active_tab=False reads the tab Commander shows and leaves a person's tab click alone, as
        scripts/watch.py and scripts/rig/check_amplifier.py do. Readings that don't apply to the current mode (bridge balance in
        V-Clamp) go in "not_applicable" with Commander's code; "errors" holds real failures. "demo" is true for
        Commander's Demo mode and "ommm" is ommm.provenance().
        """
        if show_active_tab:
            self.show_active_tab()
        reads = {
            name[3:]: (name[3:],)
            for name, (_, params) in self.functions.items()
            if name.startswith("Get") and len(params) == 3 and name not in OTHER_HEADSTAGE_GETTERS[self.headstage.channel]
        }
        reads |= {f"MeterValue{meter + 1}": ("MeterValue", meter) for meter in range(4)}
        readings, not_applicable, errors = {}, {}, {}
        for key, get_args in reads.items():
            try:
                readings[key] = self.get(*get_args)
            except NotApplicable as error:
                not_applicable[key] = f"{self.constant_name('ERROR_', error.code)} ({error.code})"
            except CommanderError as error:
                if error.code == self.constants["ERROR_MSGTIMEOUT"]:
                    raise  # Commander has stopped answering: every remaining read would wait out the timeout too
                if error.code == self.constants["ERROR_MCCNOTOPEN"]:  # a handle that worked: every remaining read fails too
                    raise CommanderError("Get" + get_args[0], error.code, CLOSED) from None
                errors[key] = str(error)

        for name, prefix in (("Mode", "MODE_"), ("PrimarySignal", "PRI_SIGNAL_"), ("SecondarySignal", "SEC_SIGNAL_")):
            if name in readings:  # missing when Commander didn't answer; the reason is in errors
                readings[name + "Name"] = self.constant_name(prefix, readings[name])
        if not self.headstage.serial.isdigit():  # the telegraph names a headstage by its serial as a number
            telegraph_packet, errors["telegraph"] = None, "no telegraph for a non-numeric (Demo mode) serial"
        else:
            try:
                telegraph_packet = self.telegraph.read(self.headstage.serial, self.headstage.channel)
            except TimeoutError as error:
                telegraph_packet, errors["telegraph"] = None, str(error)
        return {
            "schema": SNAPSHOT_SCHEMA,
            "time": datetime.now().astimezone().isoformat(),
            "api_version": self.api_version,
            "headstage": asdict(self.headstage),
            "demo": self.headstage.serial.startswith("Demo"),  # Commander's Demo mode: never a recording
            "readings": readings,
            "telegraph": telegraph_packet,
            "disagreements": disagreements(readings, telegraph_packet),
            "not_applicable": not_applicable,
            "errors": errors,
            "ommm": ommm.provenance(),
        }

    def close(self):
        self.dll.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
