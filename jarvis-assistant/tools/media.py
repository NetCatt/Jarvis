import ctypes
import os
import re
import ssl
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from ctypes import HRESULT, POINTER, c_float, c_uint32, c_void_p, cast, byref
from ctypes.wintypes import DWORD

_LAST_SONG = ""
_LAST_PLATFORM = ""
CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
IID_IAudioEndpointVolume = "{5CDF2C82-841E-4546-9722-0CF74078229A}"

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", DWORD),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

def _parse_guid(guid_str: str) -> GUID:
    guid = GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(guid_str), byref(guid))
    return guid

def _get_endpoint_volume():
    if os.name != "nt":
        return None
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        clsid_enum = _parse_guid(CLSID_MMDeviceEnumerator)
        iid_enum = _parse_guid(IID_IMMDeviceEnumerator)
        iid_aev = _parse_guid(IID_IAudioEndpointVolume)
        pEnum = c_void_p()
        hr = ole32.CoCreateInstance(byref(clsid_enum), None, 1, byref(iid_enum), byref(pEnum))
        if hr != 0 or not pEnum.value:
            return None
        vtable_enum = cast(pEnum.value, POINTER(POINTER(c_void_p))).contents
        get_def_ep = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_uint32, c_uint32, POINTER(c_void_p))(vtable_enum[4])
        pDev = c_void_p()
        hr = get_def_ep(pEnum, 0, 1, byref(pDev))
        if hr != 0 or not pDev.value:
            return None
        vtable_dev = cast(pDev.value, POINTER(POINTER(c_void_p))).contents
        activate = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), DWORD, c_void_p, POINTER(c_void_p))(vtable_dev[3])
        pAev = c_void_p()
        hr = activate(pDev, byref(iid_aev), 23, None, byref(pAev))
        if hr != 0 or not pAev.value:
            return None
        return pAev
    except Exception:
        return None

def get_volume() -> str:
    pAev = _get_endpoint_volume()
    if not pAev:
        return "Audio volume controller unavailable on this system."
    try:
        vtable_aev = cast(pAev.value, POINTER(POINTER(c_void_p))).contents
        get_vol = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_float))(vtable_aev[9])
        cur_vol = c_float()
        hr = get_vol(pAev, byref(cur_vol))
        if hr == 0:
            percent = int(round(cur_vol.value * 100))
            return f"Current master volume is at {percent}%."
        return "Failed to read system volume."
    except Exception as exc:
        return f"Error reading volume: {exc}"

def set_volume(level: int | str) -> str:
    try:
        val = int(str(level).replace("%", "").strip())
    except ValueError:
        return f"Invalid volume level: {level}"
    val = max(0, min(100, val))
    pAev = _get_endpoint_volume()
    if not pAev:
        return "Audio volume controller unavailable on this system."
    try:
        vtable_aev = cast(pAev.value, POINTER(POINTER(c_void_p))).contents
        set_vol = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_float, c_void_p)(vtable_aev[7])
        scalar = val / 100.0
        hr = set_vol(pAev, scalar, None)
        if hr == 0:
            return f"Master volume set to {val}%, Fas."
        return "Failed to set system volume."
    except Exception as exc:
        return f"Error setting volume: {exc}"

def change_volume(delta: int = 10) -> str:
    pAev = _get_endpoint_volume()
    if not pAev:
        return "Audio volume controller unavailable on this system."
    try:
        vtable_aev = cast(pAev.value, POINTER(POINTER(c_void_p))).contents
        get_vol = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_float))(vtable_aev[9])
        set_vol = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_float, c_void_p)(vtable_aev[7])
        cur_vol = c_float()
        hr = get_vol(pAev, byref(cur_vol))
        if hr != 0:
            return "Failed to read system volume."
        new_val = max(0, min(100, int(round(cur_vol.value * 100)) + delta))
        hr = set_vol(pAev, new_val / 100.0, None)
        if hr == 0:
            direction = "Cranked" if delta > 0 else "Lowered"
            return f"{direction} volume to {new_val}%, Fas."
        return "Failed to adjust system volume."
    except Exception as exc:
        return f"Error adjusting volume: {exc}"

def search_google(query: str) -> str:
    clean = urllib.parse.quote_plus(query.strip())
    webbrowser.open(f"https://www.google.com/search?q={clean}")
    return f"Searching Google for {query}."

def open_browser(url: str = "") -> str:
    target = url.strip() or "https://www.google.com"
    if not target.startswith("http://") and not target.startswith("https://"):
        target = f"https://{target}"
    webbrowser.open(target)
    return "Opened browser."

def _resolve_song_query(song: str) -> str:
    global _LAST_SONG
    cleaned = re.sub(r"\b(please|for me|once more)\b", "", (song or "").strip(), flags=re.IGNORECASE).strip(" .!?")
    replay_tokens = ("", "it", "that", "this", "the song", "that song", "the track", "same song", "again", "it again", "that again", "this again", "the song again", "that song again")
    if cleaned.lower() in replay_tokens:
        return _LAST_SONG or "lofi beats"
    _LAST_SONG = cleaned
    return cleaned

def _resolve_youtube_video_url(query: str) -> str:
    clean_q = urllib.parse.quote_plus(query.strip())
    search_url = f"https://www.youtube.com/results?search_query={clean_q}"
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=2.5, context=ctx).read().decode("utf-8", errors="ignore")
        match = re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
        if match:
            return f"https://www.youtube.com/watch?v={match.group(1)}&autoplay=1"
    except Exception:
        pass
    return search_url

def _autoplay_youtube_browser() -> None:
    if os.name != "nt" or os.getenv("DISABLE_MEDIA_UI_AUTOMATION", "0") == "1":
        return
    def _worker():
        time.sleep(2.6)
        from tools.os_context import os_context
        from tools.os_input import os_input
        status = os_context("now_playing")
        if "(Playing)" not in status:
            os_input(keys=["k"])
    threading.Thread(target=_worker, daemon=True).start()

def _find_spotify_hwnd() -> int:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    found = []
    enum_cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        ln = user32.GetWindowTextLengthW(hwnd)
        if ln <= 0:
            return True
        buf = ctypes.create_unicode_buffer(ln + 1)
        user32.GetWindowTextW(hwnd, buf, ln + 1)
        title = buf.value
        if any(b in title for b in ("Mozilla Firefox", "Google Chrome", "Microsoft Edge", "Visual Studio Code", "Antigravity")):
            return True
        pid = DWORD()
        user32.GetWindowThreadProcessId(hwnd, byref(pid))
        hproc = kernel32.OpenProcess(0x1000, False, pid.value)
        exe = ""
        if hproc:
            try:
                pbuf = ctypes.create_unicode_buffer(260)
                sz = DWORD(260)
                if kernel32.QueryFullProcessImageNameW(hproc, 0, pbuf, byref(sz)):
                    exe = pbuf.value.lower()
            finally:
                kernel32.CloseHandle(hproc)
        if exe.endswith("spotify.exe") or title.startswith("Spotify"):
            found.append(hwnd)
            return False
        return True
    user32.EnumWindows(enum_cb(_cb), 0)
    return found[0] if found else 0

def _focus_hwnd(hwnd: int) -> None:
    if not hwnd:
        return
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    fg = user32.GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    if fg_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, True)
    user32.ShowWindow(hwnd, 9)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if fg_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, False)

def _find_green_play_in_image(img) -> tuple[int, int] | None:
    w, h = img.size
    px = img.load()
    pts = []
    for y in range(int(h * 0.10), int(h * 0.65), 3):
        row_xs = [x for x in range(int(w * 0.05), int(w * 0.80), 3) if px[x, y][1] > 180 and px[x, y][0] < 80 and px[x, y][2] < 135]
        if len(row_xs) >= 6:
            pts.extend((x, y) for x in row_xs)
    if not pts:
        return None
    buckets = {}
    for x, y in pts:
        buckets.setdefault((x // 45, y // 45), []).append((x, y))
    top_pts = max(buckets.values(), key=len)
    if len(top_pts) < 20:
        return None
    return sum(p[0] for p in top_pts) // len(top_pts), sum(p[1] for p in top_pts) // len(top_pts)

def _click_spotify_green_play(hwnd: int) -> bool:
    try:
        from PIL import ImageGrab
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
        hit = _find_green_play_in_image(img)
        if not hit:
            return False
        cx, cy = rect.left + hit[0], rect.top + hit[1]
        user32.SetCursorPos(cx, cy)
        time.sleep(0.05)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        return True
    except Exception:
        return False

def _autoplay_spotify_ui(song_query: str = "") -> None:
    if os.name != "nt" or os.getenv("DISABLE_MEDIA_UI_AUTOMATION", "0") == "1":
        return
    def _worker():
        hwnd = 0
        deadline = time.time() + 6.0
        while time.time() < deadline:
            hwnd = _find_spotify_hwnd()
            if hwnd:
                break
            time.sleep(0.3)
        if not hwnd:
            return
        time.sleep(0.6)
        _focus_hwnd(hwnd)
        from tools.os_input import os_input
        from tools.os_context import os_context
        time.sleep(0.25)
        os_input(keys=["ctrl", "k"], hotkey=True)
        time.sleep(0.35)
        if song_query:
            os_input(text=song_query)
            time.sleep(1.0)
        os_input(keys=["down"])
        time.sleep(0.15)
        os_input(keys=["shift", "enter"], hotkey=True)
        time.sleep(0.95)
        if "(Playing)" not in os_context("now_playing"):
            os_input(keys=["enter"])
            time.sleep(0.95)
            _focus_hwnd(hwnd)
            time.sleep(0.15)
            _click_spotify_green_play(hwnd)
    threading.Thread(target=_worker, daemon=True).start()

def play_youtube(query: str) -> str:
    global _LAST_PLATFORM
    resolved = _resolve_song_query(query)
    _LAST_PLATFORM = "youtube"
    target_url = _resolve_youtube_video_url(resolved)
    webbrowser.open(target_url)
    if "/watch?v=" in target_url:
        _autoplay_youtube_browser()
    return f"Playing {resolved} on YouTube."

def play_spotify(query: str) -> str:
    global _LAST_PLATFORM
    resolved = _resolve_song_query(query)
    _LAST_PLATFORM = "spotify"
    clean_q = urllib.parse.quote(resolved)
    try:
        os.startfile(f"spotify:search:{clean_q}")
        _autoplay_spotify_ui(resolved)
    except Exception:
        webbrowser.open(f"https://open.spotify.com/search/{clean_q}")
    return f"Playing {resolved} on Spotify."

def play_music(song: str = "", platform: str = "") -> str:
    target_song = (song or "").strip()
    p = (platform or "").lower().strip()
    if not p:
        if "spotify" in target_song.lower():
            target_song = re.sub(r"\b(on|in)\s+(?:the\s+)?spotify\b", "", target_song, flags=re.IGNORECASE).strip()
            p = "spotify"
        elif "youtube" in target_song.lower():
            target_song = re.sub(r"\b(on|in)\s+(?:the\s+)?youtube\b", "", target_song, flags=re.IGNORECASE).strip()
            p = "youtube"
        else:
            p = os.getenv("DEFAULT_MUSIC_PLATFORM", "youtube").lower()
    if "spotify" in p:
        return play_spotify(target_song)
    return play_youtube(target_song)

def pause_music() -> str:
    if os.name == "nt":
        ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xB3, 0, 2, 0)
        return "Toggled playback, Fas."
    return "Media control unavailable."

def next_track() -> str:
    if os.name == "nt":
        ctypes.windll.user32.keybd_event(0xB0, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xB0, 0, 2, 0)
        return "Skipped to next track, Fas."
    return "Media control unavailable."

def prev_track() -> str:
    if os.name == "nt":
        ctypes.windll.user32.keybd_event(0xB1, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xB1, 0, 2, 0)
        return "Playing previous track, Fas."
    return "Media control unavailable."
