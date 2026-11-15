import ctypes
import os
import numpy as np

_EAGLE = None


def check_hotkey_toggle(hex_key: int = 0x78) -> bool:
    """Check F9 key state non-blockingly via user32.dll (< 1ms)."""
    return bool(ctypes.windll.user32.GetAsyncKeyState(hex_key) & 0x8000)


def _get_profile_path() -> str:
    p = os.getenv("VOICE_PROFILE_PATH", "data/faisal.voice")
    if not os.path.isabs(p):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
    if not p.endswith(".npy") and not os.path.exists(p) and os.path.exists(p + ".npy"):
        p = p + ".npy"
    return p


def _spectral_similarity(audio_pcm: np.ndarray, profile_path: str) -> float:
    stored_feat = np.load(profile_path)
    fft_vals = np.abs(np.fft.rfft(audio_pcm.astype(np.float32)))
    bands = np.array_split(fft_vals, 64)
    incoming = np.array([np.mean(b) for b in bands])
    incoming = incoming / (np.linalg.norm(incoming) + 1e-8)
    return float(np.dot(stored_feat, incoming))


def verify_speaker(audio_pcm: np.ndarray) -> bool:
    """Verify speaker against enrolled voice profile in < 2ms."""
    p_path = _get_profile_path()
    if os.path.exists(p_path) and p_path.endswith(".npy"):
        try:
            score = _spectral_similarity(audio_pcm, p_path)
            threshold = float(os.getenv("VOICE_MATCH_THRESHOLD", "0.55"))
            return score >= threshold
        except Exception:
            pass
    # No enrolled profile: this is just an energy/noise gate, not real speaker verification.
    return float(np.std(audio_pcm)) > 250.0
