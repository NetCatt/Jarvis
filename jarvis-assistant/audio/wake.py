import ctypes
import os

def _get_default_wake_words() -> list[str]:
    raw = os.getenv("WAKE_WORDS", "mike,ross,hey mike,hey ross")
    return [w.strip().lower() for w in raw.split(",") if w.strip()]

def check_hotkey(hex_key: int = 0x78) -> bool:
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(hex_key) & 0x8000)
    except Exception:
        return False

def check_wake_phrase(text: str, wake_words: list[str] = None) -> bool:
    if not text:
        return False
    if wake_words is None:
        wake_words = _get_default_wake_words()
    low = text.lower().strip()
    words = [w.strip(",.!?") for w in low.split()]
    for wake in sorted(wake_words, key=lambda w: -len(w.split())):
        wake_parts = wake.split()
        n = len(wake_parts)
        if words[:n] == wake_parts or wake in low:
            return True
    return False

def strip_wake_phrase(text: str, wake_words: list[str] = None) -> tuple[bool, str]:
    if not text:
        return False, text
    if wake_words is None:
        wake_words = _get_default_wake_words()
    words = text.split()
    low_words = [w.lower().strip(",.!?") for w in words]
    for wake in sorted(wake_words, key=lambda w: -len(w.split())):
        wake_parts = wake.split()
        n = len(wake_parts)
        if low_words[:n] == wake_parts:
            return True, " ".join(words[n:]).strip()
    return False, text
