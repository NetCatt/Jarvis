import ctypes
from ctypes import wintypes
import os
import subprocess

class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]

def _setup_ctypes_signatures(user32, kernel32):
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]

_INITIALIZED = False

def _query_now_playing() -> str:
    ps = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType=WindowsRuntime] | Out-Null
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$sessions = $mgr.GetSessions()
foreach ($s in $sessions) {
    $info = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
    $pb = $s.GetPlaybackInfo()
    if ($info.Title) {
        $app = ($s.SourceAppUserModelId -replace '\.exe$', '')
        Write-Output "$app|$($pb.PlaybackStatus)|$($info.Title)|$($info.Artist)"
    }
}
"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=3.0,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        lines = [l.strip() for l in (proc.stdout or "").splitlines() if "|" in l]
        if not lines:
            return "Nothing is currently playing in Windows media controls, Fas."
        parts = lines[0].split("|", 3)
        app, status, title, artist = parts[0], parts[1], parts[2], parts[3]
        by_str = f" by {artist}" if artist else ""
        return f"On {app}, you're listening to {title}{by_str} ({status}), Fas."
    except Exception as exc:
        return f"Unable to inspect media session: {exc}"

def os_context(query_type: str = "active_window") -> str:
    global _INITIALIZED
    if os.name != "nt":
        return "os_context only available on Windows."
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not _INITIALIZED:
        _setup_ctypes_signatures(user32, kernel32)
        _INITIALIZED = True
    q = query_type.lower().strip()
    if q in ("now_playing", "media", "spotify", "song", "music", "playing"):
        return _query_now_playing()
    if q in ("active_window", "window", "foreground"):
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "No active foreground window."
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip() or "Untitled Window"
        return f"Active window: {title}"
    if q in ("clipboard", "paste"):
        if not user32.OpenClipboard(None):
            return "Unable to access clipboard."
        try:
            h_data = user32.GetClipboardData(13)
            if not h_data:
                return "Clipboard is empty or non-text."
            p_data = kernel32.GlobalLock(h_data)
            if not p_data:
                return "Clipboard lock failed."
            try:
                text = ctypes.wstring_at(p_data)
            finally:
                kernel32.GlobalUnlock(h_data)
            return f"Clipboard: {text[:200]}"
        finally:
            user32.CloseClipboard()
    if q in ("system_stats", "ram", "memory"):
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        total_gb = stat.ullTotalPhys / (1024 ** 3)
        avail_gb = stat.ullAvailPhys / (1024 ** 3)
        return f"System Memory: {stat.dwMemoryLoad}% used ({avail_gb:.1f} GB free of {total_gb:.1f} GB)."
    return f"Unknown context query: {query_type}"
