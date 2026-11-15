import os
import numpy as np
import sounddevice as sd

PROFILE_PATH = os.path.join(os.path.dirname(__file__), os.getenv("VOICE_PROFILE_PATH", "data/faisal.voice"))
if not PROFILE_PATH.endswith(".npy"):
    PROFILE_PATH += ".npy"
os.makedirs(os.path.dirname(PROFILE_PATH), exist_ok=True)


def extract_features(audio: np.ndarray) -> np.ndarray:
    """Extract normalized FFT spectral energy distribution."""
    fft_vals = np.abs(np.fft.rfft(audio.astype(np.float32)))
    bands = np.array_split(fft_vals, 64)
    energies = np.array([np.mean(b) for b in bands])
    return energies / (np.linalg.norm(energies) + 1e-8)


def enroll() -> None:
    print("\n--- VOICE ENROLLMENT: FAS ---")
    print("When recording begins, speak normally for 5 seconds.")
    print("Example: 'I am Fas, and this is my voice authorization for Mike Ross.'")
    input("\nPress ENTER when ready to record...")

    print("\n[Recording... SPEAK NOW!]")
    audio = sd.rec(int(5.0 * 16000), samplerate=16000, channels=1, dtype="int16")
    sd.wait()
    print("[Recording complete. Processing voiceprint...]")

    flat = audio.flatten()
    if np.abs(flat).mean() < 200:
        print("ERROR: Microphone input was too quiet or silent. Please check mic and retry.")
        return

    feat = extract_features(flat)
    np.save(PROFILE_PATH, feat)
    print(f"\nSUCCESS: Voiceprint saved to {os.path.basename(PROFILE_PATH)}")
    print("Mike Ross will now filter background audio and only respond to your voice!\n")


if __name__ == "__main__":
    enroll()
