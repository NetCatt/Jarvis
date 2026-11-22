import ctypes
import os
import re
import urllib.parse
import webbrowser
from ctypes import HRESULT, POINTER, c_float, c_uint32, c_void_p, cast, byref
from ctypes.wintypes import DWORD

_LAST_SONG = ""
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


def play_youtube(query: str) -> str:
    clean_q = urllib.parse.quote_plus(query.strip())
    webbrowser.open(f"https://www.youtube.com/results?search_query={clean_q}")
    return f"Playing {query} on YouTube."


def play_spotify(query: str) -> str:
    clean_q = urllib.parse.quote(query.strip())
    try:
        os.startfile(f"spotify:search:{clean_q}")
    except Exception:
        webbrowser.open(f"https://open.spotify.com/search/{clean_q}")
    return f"Playing {query} on Spotify."


def play_music(song: str = "", platform: str = "") -> str:
    target_song = song.strip() or "music"
    p = platform.lower().strip()
    if not p:
        if "spotify" in target_song.lower():
            target_song = re.sub(r"\b(on|in)\s+spotify\b", "", target_song, flags=re.IGNORECASE).strip()
            p = "spotify"
        elif "youtube" in target_song.lower():
            target_song = re.sub(r"\b(on|in)\s+youtube\b", "", target_song, flags=re.IGNORECASE).strip()
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
