"""Save a PNG of each MultiClamp Commander window (the main window, Options, ...), even when covered.

    uv run python scripts/screenshot_commander.py [--log-dir DIR]     (default ~/ommm-logs)

Must run in the desktop session, like Commander. PrintWindow asks each window to draw itself, so
the image is the window's own content rather than whatever sits on top of it. No dependencies:
the PNG is written with zlib.
"""

import argparse
import ctypes
import struct
import sys
import zlib
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

PW_RENDERFULLCONTENT = 0x2

if sys.platform == "win32":  # so --help works anywhere; rig/rig.py uses user32 from here at its own import
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.SetProcessDPIAware()  # window rectangles in real pixels
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    for func, restype, argtypes in [  # handles are 64-bit; ctypes' default int would truncate them
        (user32.EnumWindows, wintypes.BOOL, [WNDENUMPROC, wintypes.LPARAM]),
        (user32.GetWindowTextW, ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
        (user32.GetWindowThreadProcessId, wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
        (user32.IsWindowVisible, wintypes.BOOL, [wintypes.HWND]),
        (user32.GetWindowRect, wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]),
        (user32.GetWindowDC, wintypes.HDC, [wintypes.HWND]),
        (user32.ReleaseDC, ctypes.c_int, [wintypes.HWND, wintypes.HDC]),
        (user32.PrintWindow, wintypes.BOOL, [wintypes.HWND, wintypes.HDC, wintypes.UINT]),
        (gdi32.CreateCompatibleDC, wintypes.HDC, [wintypes.HDC]),
        (gdi32.CreateCompatibleBitmap, wintypes.HBITMAP, [wintypes.HDC, ctypes.c_int, ctypes.c_int]),
        (gdi32.SelectObject, wintypes.HGDIOBJ, [wintypes.HDC, wintypes.HGDIOBJ]),
        (gdi32.GetDIBits, ctypes.c_int, [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                         ctypes.c_void_p, wintypes.UINT]),
        (gdi32.DeleteObject, wintypes.BOOL, [wintypes.HGDIOBJ]),
        (gdi32.DeleteDC, wintypes.BOOL, [wintypes.HDC]),
    ]:
        func.restype, func.argtypes = restype, argtypes


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


def top_level_windows() -> list[int]:
    found = []
    user32.EnumWindows(WNDENUMPROC(lambda hwnd, _: found.append(hwnd) or True), 0)
    return found


def title(hwnd: int) -> str:
    text = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, text, 256)
    return text.value


def process_id(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def commander_windows() -> list[int]:
    """Commander's main window (titled "MultiClamp 700B : (serial)") and its other visible windows."""
    main = next((hwnd for hwnd in top_level_windows() if title(hwnd).startswith("MultiClamp 700B")), None)
    if main is None:
        sys.exit("screenshot_commander: no MultiClamp Commander window in this session")
    pid = process_id(main)
    return [hwnd for hwnd in top_level_windows() if process_id(hwnd) == pid and user32.IsWindowVisible(hwnd)]


def capture(hwnd: int) -> tuple[int, int, bytes]:
    """Width, height and RGB bytes of a window, drawn by the window itself."""
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(memory_dc, bitmap)
    user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT)
    header = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=width, biHeight=-height,  # top-down
                              biPlanes=1, biBitCount=32)
    bgra = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory_dc, bitmap, 0, height, bgra, ctypes.byref(header), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(hwnd, window_dc)
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra.raw[2::4], bgra.raw[1::4], bgra.raw[0::4]
    return width, height, bytes(rgb)


def write_png(path: Path, width: int, height: int, rgb: bytes):
    rows = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--log-dir", type=Path, default=Path.home() / "ommm-logs")
    out_dir = parser.parse_args().log_dir
    if sys.platform != "win32":
        sys.exit("screenshot_commander: needs Windows, where Commander runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%dT%H%M%S}"
    for number, hwnd in enumerate(commander_windows()):
        width, height, rgb = capture(hwnd)
        path = out_dir / f"commander_{stamp}_{number}.png"
        write_png(path, width, height, rgb)
        print(f"{path}  {width}x{height}  {title(hwnd)!r}")


if __name__ == "__main__":
    main()
