import ctypes
import time
from ctypes import wintypes

_VK_MAP = {
    "playpause": 0xB3,
    "play": 0xB3,
    "pause": 0xB3,
    "next": 0xB0,
    "nexttrack": 0xB0,
    "prev": 0xB1,
    "prevtrack": 0xB1,
    "stop": 0xB2,
    "volmute": 0xAD,
    "voldown": 0xAE,
    "volup": 0xAF,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,
    "windows": 0x5B,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "space": 0x20,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}
for i in range(1, 13):
    _VK_MAP[f"f{i}"] = 0x6F + i

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulong),
    ]

class _INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT)]
    _anonymous_ = ("_u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_u", _INPUT_UNION),
    ]

def _resolve_vk(key_name: str) -> int:
    clean = key_name.strip().lower()
    if clean in _VK_MAP:
        return _VK_MAP[clean]
    if len(clean) == 1:
        return ord(clean.upper())
    return 0

def os_input(keys: list[str] | str = None, text: str = None, hotkey: bool = True) -> str:
    if not hasattr(ctypes, "windll") or not hasattr(ctypes.windll, "user32"):
        return "os_input unsupported on this platform."
    results = []
    if keys:
        if isinstance(keys, str):
            key_list = [k.strip() for k in keys.replace("+", " ").split() if k.strip()]
        else:
            key_list = [str(k).strip() for k in keys if str(k).strip()]
        vks = [_resolve_vk(k) for k in key_list]
        vks = [vk for vk in vks if vk > 0]
        if vks:
            if hotkey:
                for vk in vks:
                    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                    time.sleep(0.01)
                for vk in reversed(vks):
                    ctypes.windll.user32.keybd_event(vk, 0, 0x0002, 0)
                    time.sleep(0.01)
            else:
                for vk in vks:
                    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(vk, 0, 0x0002, 0)
                    time.sleep(0.01)
            results.append(f"Pressed {'+'.join(key_list)}")
    if text:
        for ch in text:
            scan = ord(ch)
            down = _INPUT(type=1, ki=_KEYBDINPUT(wVk=0, wScan=scan, dwFlags=0x0004, time=0, dwExtraInfo=0))
            up = _INPUT(type=1, ki=_KEYBDINPUT(wVk=0, wScan=scan, dwFlags=0x0004 | 0x0002, time=0, dwExtraInfo=0))
            ctypes.windll.user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_INPUT))
            ctypes.windll.user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_INPUT))
        results.append(f"Typed '{text}'")
    return ", ".join(results) if results else "No keys or text specified."
