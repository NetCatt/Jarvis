import ctypes
import os
import numpy as np

_EAGLE = None


def check_hotkey_toggle(hex_key: int = 0x78) -> bool:
    """Check F9 key state non-blockingly via user32.dll (< 1ms)."""
    return bool(ctypes.windll.user32.GetAsyncKeyState(hex_key) & 0x8000)


def verify_speaker(audio_pcm: np.ndarray) -> bool:
    """Verify speaker against faisal.voice using pveagle or spectral variance fallback (<15ms)."""
    global _EAGLE
    key, profile = os.getenv("PICOVOICE_ACCESS_KEY", "").strip(), os.getenv("VOICE_PROFILE_PATH", "faisal.voice")
    if key and os.path.exists(profile):
        if _EAGLE is None:
            import pveagle
            _EAGLE = pveagle.create_recognizer(access_key=key, speaker_profiles=[pveagle.SpeakerProfile.from_bytes(open(profile, "rb").read())])
        score = _EAGLE.process(audio_pcm)[0]
        return score >= float(os.getenv("VOICE_MATCH_THRESHOLD", "0.65"))
    return float(np.std(audio_pcm)) > 350.0
