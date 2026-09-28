"""Small Win32 helpers via ctypes: session lock state and forcing a window to the foreground."""

import ctypes
import os
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32")
_kernel32 = ctypes.WinDLL("kernel32")
_wtsapi32 = ctypes.WinDLL("wtsapi32")

_wtsapi32.WTSQuerySessionInformationW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wintypes.DWORD),
]
_wtsapi32.WTSQuerySessionInformationW.restype = wintypes.BOOL
_wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]

_WTS_CURRENT_SESSION = 0xFFFFFFFF
_WTS_SESSION_INFO_EX = 25
_WTS_SESSIONSTATE_LOCK = 0
# WTSINFOEXW: DWORD Level, then the 8-byte aligned WTSINFOEX_LEVEL1_W
# (ULONG SessionId, WTS_CONNECTSTATE_CLASS SessionState, LONG SessionFlags, ...).
_SESSION_FLAGS_OFFSET = 16


def is_session_locked() -> bool:
    buffer = ctypes.c_void_p()
    size = wintypes.DWORD()
    if not _wtsapi32.WTSQuerySessionInformationW(
        None, _WTS_CURRENT_SESSION, _WTS_SESSION_INFO_EX, ctypes.byref(buffer), ctypes.byref(size)
    ):
        return False
    try:
        flags = ctypes.c_long.from_address(buffer.value + _SESSION_FLAGS_OFFSET).value
        return flags == _WTS_SESSIONSTATE_LOCK
    finally:
        _wtsapi32.WTSFreeMemory(buffer)


def foreground_is_own_process() -> bool:
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def force_foreground(hwnd: int) -> None:
    """Bring hwnd to the foreground, working around Windows' focus stealing prevention."""
    foreground = _user32.GetForegroundWindow()
    foreground_thread = _user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    own_thread = _kernel32.GetCurrentThreadId()
    attached = bool(
        foreground_thread
        and foreground_thread != own_thread
        and _user32.AttachThreadInput(foreground_thread, own_thread, True)
    )
    try:
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(foreground_thread, own_thread, False)
