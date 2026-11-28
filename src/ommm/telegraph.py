"""MultiClamp 700B telegraph packets: what Commander broadcasts about each headstage's outputs.

The telegraph carries what the AxMultiClampMsg API can't report: external command sensitivity and the
scale factor and units of both outputs. read() opens a connection, takes the first packet Commander
sends back, and closes again, so Commander never sends to a window that nobody is pumping. While it waits it pumps
only its own window's messages, never the rest of the calling thread's queue.

Protocol and struct layout from Molecular Devices' Telegraph SDK (MultiClampBroadcastMsg.hpp and the
"Telegraph Interface Specification" PDF, installed next to Commander). Names are the header's.
The Windows parts are set up on the first read(), so this module imports on any OS.
"""

import ctypes
import functools
import re
import time
from ctypes import wintypes

from ommm.sdk import constant_name, sdk_file

HEADER = "Telegraph_SDK/MultiClampBroadcastMsg.hpp"
CLASS_NAME = "OmmmTelegraphClient"

LRESULT = ctypes.c_ssize_t
HWND_BROADCAST = 0xFFFF
HWND_MESSAGE = -3
WM_COPYDATA = 0x004A
PM_REMOVE = 0x0001


class COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [("dwData", ctypes.c_size_t), ("cbData", wintypes.DWORD), ("lpData", ctypes.c_void_p)]


class MC_TELEGRAPH_DATA(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 4  # the header's #pragma pack(push,4); without it every field after dAlpha is misread
    _fields_ = [
        ("uVersion", ctypes.c_uint),
        ("uStructSize", ctypes.c_uint),
        ("uComPortID", ctypes.c_uint),
        ("uAxoBusID", ctypes.c_uint),
        ("uChannelID", ctypes.c_uint),
        ("uOperatingMode", ctypes.c_uint),
        ("uScaledOutSignal", ctypes.c_uint),
        ("dAlpha", ctypes.c_double),
        ("dScaleFactor", ctypes.c_double),
        ("uScaleFactorUnits", ctypes.c_uint),
        ("dLPFCutoff", ctypes.c_double),
        ("dMembraneCap", ctypes.c_double),
        ("dExtCmdSens", ctypes.c_double),
        ("uRawOutSignal", ctypes.c_uint),
        ("dRawScaleFactor", ctypes.c_double),
        ("uRawScaleFactorUnits", ctypes.c_uint),
        ("uHardwareType", ctypes.c_uint),
        ("dSecondaryAlpha", ctypes.c_double),
        ("dSecondaryLPFCutoff", ctypes.c_double),
        ("szAppVersion", ctypes.c_char * 16),
        ("szFirmwareVersion", ctypes.c_char * 16),
        ("szDSPVersion", ctypes.c_char * 16),
        ("szSerialNumber", ctypes.c_char * 16),
        ("dSeriesResistance", ctypes.c_double),
        ("pcPadding", ctypes.c_char * 76),
    ]


assert ctypes.sizeof(MC_TELEGRAPH_DATA) == 256

packets = {}  # hwnd -> latest MC_TELEGRAPH_DATA copy, filled by the window procedure


@functools.cache
def win32():
    """user32, the telegraph's message ids and the registered window class, made on first use."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    for func, restype, argtypes in [
        (user32.DefWindowProcW, LRESULT, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
        (user32.RegisterWindowMessageW, wintypes.UINT, [wintypes.LPCWSTR]),
        (user32.RegisterClassW, wintypes.ATOM, [ctypes.POINTER(WNDCLASSW)]),
        (user32.CreateWindowExW, wintypes.HWND, [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                                 ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                 wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]),
        (user32.DestroyWindow, wintypes.BOOL, [wintypes.HWND]),
        (user32.PostMessageW, wintypes.BOOL, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
        (user32.PeekMessageW, wintypes.BOOL, [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]),
        (user32.TranslateMessage, wintypes.BOOL, [ctypes.POINTER(wintypes.MSG)]),
        (user32.DispatchMessageW, LRESULT, [ctypes.POINTER(wintypes.MSG)]),
        (kernel32.GetModuleHandleW, wintypes.HMODULE, [wintypes.LPCWSTR]),
    ]:
        func.restype, func.argtypes = restype, argtypes

    messages = {
        name: user32.RegisterWindowMessageW(f"MultiClampTelegraph{name.capitalize()}Msg")
        for name in ("open", "close", "request")
    }

    @WNDPROC
    def window_proc(hwnd, msg, wparam, lparam):
        if msg == WM_COPYDATA:
            copy = ctypes.cast(lparam, ctypes.POINTER(COPYDATASTRUCT)).contents
            if copy.dwData == messages["request"]:
                packet = MC_TELEGRAPH_DATA()
                ctypes.memmove(ctypes.byref(packet), copy.lpData, min(copy.cbData, ctypes.sizeof(packet)))
                packets[hwnd] = packet
                return 1
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    window_class = WNDCLASSW(lpfnWndProc=window_proc, hInstance=kernel32.GetModuleHandleW(None), lpszClassName=CLASS_NAME)
    if not user32.RegisterClassW(ctypes.byref(window_class)):  # e.g. by an earlier copy of this module (a reload)
        raise ctypes.WinError(
            ctypes.get_last_error(), "telegraph window class already registered: restart Python (terminate(pyenv) in MATLAB)"
        )
    return user32, messages, window_class


def header_constants() -> dict[str, int]:
    return {
        name: int(value)
        for name, value in re.findall(r"^const\s+(?:UINT|long)\s+(\w+)\s*=\s*(\d+);", sdk_file(HEADER).read_text(), re.MULTILINE)
    }


def signal_names() -> list[str]:
    """MCTG_OUT_GLDR_LONG_NAMES, indexed by uScaledOutSignal / uRawOutSignal ("Membrane Potential", ...)."""
    table = re.search(r"MCTG_OUT_GLDR_LONG_NAMES\[[^\]]*\]\s*=\s*\{(.*?)\};", sdk_file(HEADER).read_text(), re.DOTALL).group(1)
    return re.findall(r'"([^"]*)"', table)


def signal_ids(serial: str, channel: int) -> int:
    """MCTG_Pack700BSignalIDs: channel in the top 4 bits, serial number in the low 28."""
    return (int(serial) & 0x0FFFFFFF) | (channel << 28)


def read(serial: str, channel: int, timeout_s: float = 1.0) -> dict:
    """One telegraph packet for a 700B headstage, decoded."""
    ids = signal_ids(serial, channel)  # first, so a bad serial never leaves a window behind
    user32, messages, window_class = win32()
    hwnd = user32.CreateWindowExW(0, CLASS_NAME, None, 0, 0, 0, 0, 0, HWND_MESSAGE, None, window_class.hInstance, None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        user32.PostMessageW(HWND_BROADCAST, messages["open"], hwnd, ids)
        msg = wintypes.MSG()
        deadline = time.monotonic() + timeout_s
        while hwnd not in packets:
            if time.monotonic() > deadline:
                raise TimeoutError(f"no telegraph from Commander for headstage {channel} within {timeout_s:g} s")
            # this window's messages only: what is posted to the calling thread (a GUI host's timers and events) waits
            # for the host's own loop. Commander's WM_COPYDATA is sent, not posted, so it arrives during the peek
            # whatever the filter, and so do messages other threads send to the host's windows
            while user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.005)
        packet = packets.pop(hwnd)
    finally:
        user32.PostMessageW(HWND_BROADCAST, messages["close"], hwnd, ids)
        user32.DestroyWindow(hwnd)
        packets.pop(hwnd, None)
    return decode(packet)


def decode(packet: MC_TELEGRAPH_DATA) -> dict:
    """The packet's raw fields plus its mode, signal and unit names from the telegraph header."""
    fields = {
        name: getattr(packet, name).decode(errors="replace") if name.startswith("sz") else getattr(packet, name)
        for name, _ in MC_TELEGRAPH_DATA._fields_
        if name != "pcPadding"
    }
    constants = header_constants()
    names = signal_names()
    fields["OperatingModeName"] = constant_name(constants, "MCTG_MODE_", packet.uOperatingMode)
    fields["ScaledOutSignalName"] = names[packet.uScaledOutSignal] if packet.uScaledOutSignal < len(names) else None
    fields["RawOutSignalName"] = names[packet.uRawOutSignal] if packet.uRawOutSignal < len(names) else None
    fields["ScaleFactorUnitsName"] = constant_name(constants, "MCTG_UNITS_", packet.uScaleFactorUnits)
    fields["RawScaleFactorUnitsName"] = constant_name(constants, "MCTG_UNITS_", packet.uRawScaleFactorUnits)
    return fields
