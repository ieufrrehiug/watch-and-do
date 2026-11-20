"""Windows handles and file versions for the local Jianying editor only."""
import ctypes
from ctypes import wintypes
from pathlib import Path

import psutil
import win32api
import win32gui
import win32process


U = ctypes.WinDLL("user32", use_last_error=True)
for name, result, arguments in [
    ("GetForegroundWindow", wintypes.HWND, []),
    ("GetAncestor", wintypes.HWND, [wintypes.HWND, wintypes.UINT]),
    ("WindowFromPoint", wintypes.HWND, [wintypes.POINT]),
    ("GetWindowThreadProcessId", wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
    ("GetDpiForWindow", wintypes.UINT, [wintypes.HWND]),
    ("GetWindowLongW", wintypes.LONG, [wintypes.HWND, ctypes.c_int]),
    ("IsWindowEnabled", wintypes.BOOL, [wintypes.HWND]),
    ("ShowWindowAsync", wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
    ("SetForegroundWindow", wintypes.BOOL, [wintypes.HWND]),
    ("BringWindowToTop", wintypes.BOOL, [wintypes.HWND]),
    ("AttachThreadInput", wintypes.BOOL, [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]),
]:
    function = getattr(U, name)
    function.restype = result
    function.argtypes = arguments


def rect(hwnd):
    return win32gui.GetWindowRect(hwnd)


def windows():
    # UI Automation and screenshots are used only after an executable and window match.
    processes = {}
    rows = []

    def collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid not in processes:
            processes[pid] = None
            try:
                exe = Path(psutil.Process(pid).exe())
            except (OSError, psutil.Error):
                return
            if exe.name.casefold() != "jianyingpro.exe":
                return
            info = win32api.GetFileVersionInfo(str(exe), "\\")
            ms, ls = info["FileVersionMS"], info["FileVersionLS"]
            processes[pid] = ".".join(map(str, [ms >> 16, ms & 65535, ls >> 16, ls & 65535]))
        if processes[pid]:
            rows.append(dict(hwnd=hwnd, pid=pid, title=win32gui.GetWindowText(hwnd), version=processes[pid]))

    win32gui.EnumWindows(collect, None)
    return rows
