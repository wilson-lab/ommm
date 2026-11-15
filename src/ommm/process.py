"""Closing MultiClamp Commander and starting it again: what Amplifier.load_config uses. To change a
setting, use load_config (docs/mcc.md); what a close and a start do: docs/quirks.md.

Closed with WM_CLOSE, as its close button closes it, Commander saves its settings; killed, it came back with older ones,
so ommm never kills it. Every handle from before is dead (6002) once Commander has gone. The serial for /S is read from
the running Commander by quit_commander, never given or written down.
Process makes the Windows calls, and off Windows says it needs Windows, as Commander() does; ommm.testing.FakeProcess
stands in for it there (process=).
"""

import csv
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from ommm.commander import DLL, Commander, CommanderError, need_windows
from ommm.sdk import install_dir

EXE = "MC700B.exe"
MAIN_WINDOW = "MultiClamp 700B"  # the start of the main window's title, "MultiClamp 700B :  ( serial )"
# WM_CLOSE exited in under 1 s and asked nothing, also after a load and a change; still running after this, Commander
# waits for a person
QUIT_S = 30
# for the API after a start, three times the slowest seen (docs/quirks.md, Closing and starting Commander); a start
# that shows a dialog does not answer while the dialog is open
API_S = 30
POLL_S = 0.5
NOT_RUNNING = "Commander is not running in this desktop session"
WM_CLOSE, SYNCHRONIZE, WAIT_OBJECT_0 = 0x0010, 0x00100000, 0

if sys.platform == "win32":
    user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    for func, restype, argtypes in [  # handles are 64-bit; ctypes' default int would truncate them
        (user32.EnumWindows, wintypes.BOOL, [WNDENUMPROC, wintypes.LPARAM]),
        (user32.GetWindowTextW, ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
        (user32.GetWindowThreadProcessId, wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
        (user32.PostMessageW, wintypes.BOOL, [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]),
        (kernel32.OpenProcess, wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
        (kernel32.WaitForSingleObject, wintypes.DWORD, [wintypes.HANDLE, wintypes.DWORD]),
        (kernel32.CloseHandle, wintypes.BOOL, [wintypes.HANDLE]),
    ]:
        func.restype, func.argtypes = restype, argtypes


class Process:
    """MC700B.exe, Commander's program, through Windows: found by its hidden window, closed through its main window,
    started from Commander's install folder. `serial` is the amplifier of the Commander quit_commander closed, which
    launch_commander starts again."""

    def __init__(self):
        self.serial = None

    def window_pid(self) -> int | None:
        need_windows()
        return DLL.commander_pid()

    def pids(self) -> list[int]:
        """Every MC700B.exe running on this PC, in any session."""
        need_windows()
        listed = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
        return [int(row[1]) for row in csv.reader(listed.splitlines()) if row and row[0].lower() == EXE.lower()]

    def close_window(self, pid: int):
        """Post WM_CLOSE to the process's main window, as its close button does."""
        need_windows()
        found = []

        def take(hwnd, _):
            owner, title = wintypes.DWORD(), ctypes.create_unicode_buffer(256)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            user32.GetWindowTextW(hwnd, title, 256)
            if owner.value == pid and title.value.startswith(MAIN_WINDOW):
                found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(take), 0)
        if not found:
            raise CommanderError("quit_commander", None, f"Commander (process {pid}) has no window titled {MAIN_WINDOW!r}... to close")
        user32.PostMessageW(found[0], WM_CLOSE, 0, 0)

    def wait_exit(self, pid: int, timeout_s: float) -> bool:
        """Whether the process has exited within timeout_s."""
        need_windows()
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:  # gone already, or not ours to wait on
            return pid not in self.pids()
        try:
            return kernel32.WaitForSingleObject(handle, round(timeout_s * 1000)) == WAIT_OBJECT_0
        finally:
            kernel32.CloseHandle(handle)

    def program_found(self) -> bool:
        """Whether MC700B.exe is where start runs it, in Commander's install folder."""
        return (install_dir() / EXE).is_file()

    def start(self, args: list[str]) -> int:
        """Start MC700B.exe from Commander's install folder; its process id. Out of any job object this process runs in
        where the job allows it, so that closing the job (uv, MATLAB, a scheduled task) cannot kill Commander.
        Started from Python under uv run in a scheduled task, Commander outlived both. MATLAB's out-of-process Python
        runs in a job that allows no breakaway but does not kill on close: Commander starts inside it, and outlived
        terminate(pyenv) and MATLAB's exit (docs/matlab.md, After Commander restarts)."""
        need_windows()
        command, devnull = [str(install_dir() / EXE), *args], subprocess.DEVNULL
        try:
            started = subprocess.Popen(command, stdin=devnull, stdout=devnull, stderr=devnull,
                                       creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB)
        except PermissionError:  # a job that allows no breakaway
            started = subprocess.Popen(command, stdin=devnull, stdout=devnull, stderr=devnull)
        return started.pid

    def connect(self, headstage: int = 1) -> Commander:
        return Commander(headstage=headstage)


PROCESS = Process()


def others_running(process=PROCESS) -> str | None:
    """Why Commander cannot be closed now: more than one MC700B.exe runs, and launch_commander would refuse to start
    this one again."""
    running = process.pids()
    if len(running) < 2:
        return None
    return (f"{len(running)} Commanders run on this PC (processes {', '.join(map(str, running))}): ommm closes Commander "
            "only when one runs, since only then can it start it again")


def quit_commander(process=PROCESS, headstage: int = 1) -> int:
    """Close Commander as its close button does (WM_CLOSE), so that it saves its settings, and wait until it has
    exited; its process id. Reads the amplifier's serial first, for launch_commander, so a Commander that does not answer,
    runs in Demo mode or runs beside another Commander is not closed. Still running after 30 s, Commander is waiting for
    something only a person can answer, a dialog in its window say: ommm raises and leaves it be. `headstage` is the one
    the serial is read through, a connected one; closing Commander stops it for both."""
    pid = process.window_pid()
    if pid is None:
        raise CommanderError("quit_commander", None, NOT_RUNNING)
    if why := others_running(process):
        raise CommanderError("quit_commander", None, why)
    with process.connect(headstage) as commander:
        serial = commander.headstage.serial
    if not serial.isdigit():
        raise CommanderError("quit_commander", None, f"Commander is in Demo mode ({serial}): ommm closes and starts it only on an amplifier")
    process.serial = serial
    process.close_window(pid)
    if not process.wait_exit(pid, QUIT_S):
        raise CommanderError(
            "quit_commander", None,
            f"Commander (process {pid}) is still running {QUIT_S} s after it was asked to close: answer or close what its "
            "window shows. ommm never kills Commander, which would lose its settings",
        )
    return pid


def launch_commander(mcc: str | Path | None = None, process=PROCESS) -> int:
    """Start Commander on the amplifier quit_commander closed (/S<serial>), with a .mcc settings file if given
    (/C<file>); its process id. The file's path may hold no space: ommm does not quote it. Refuses while any
    MC700B.exe runs, since one amplifier takes one Commander, and before quit_commander, which reads the serial.
    Returns at once: wait_for_api waits for the API."""
    if running := process.pids():
        raise CommanderError("launch_commander", None, f"Commander is running (process {', '.join(map(str, running))}): close it first with quit_commander()")
    if process.serial is None:
        raise CommanderError("launch_commander", None, "ommm starts Commander only after closing it with quit_commander(), "
                             "which reads the amplifier's serial: start Commander from its icon")
    args = [f"/S{process.serial}"]
    if mcc is not None:
        path = Path(mcc).resolve(strict=True)
        if " " in str(path):
            raise ValueError(f"{path}: put the .mcc file where its path has no spaces; ommm does not quote it")
        args.append(f"/C{path}")
    return process.start(args)


def wait_for_api(process=PROCESS, headstage: int = 1) -> Commander:
    """A new handle on Commander, on `headstage`, once it answers after launch_commander, tried every 0.5 s; the last
    CommanderError after API_S. When the API answered after a start: docs/quirks.md, Closing and starting Commander. A
    start that shows a dialog, such as a refused .mcc file, never answers until OK is pressed. Off Windows, Process's
    "needs Windows" at once, as no try can clear it."""
    if isinstance(process, Process):
        need_windows()
    deadline = time.monotonic() + API_S
    while True:
        try:
            return process.connect(headstage)
        except CommanderError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(POLL_S)
