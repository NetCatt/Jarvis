import ctypes
import datetime
import json
import os

import numpy as np
from dotenv import load_dotenv

IS_ACTIVE = True
_VOSK_MODEL = None


def _speak_mci(tmp_mp3: str) -> None:
    mci = ctypes.windll.winmm.mciSendStringW
    win_p = os.path.normpath(tmp_mp3)
    mci(f'open "{win_p}" type mpegvideo alias reply_audio', None, 0, 0)
    mci("play reply_audio wait", None, 0, 0)
    mci("close reply_audio", None, 0, 0)
    if os.path.exists(tmp_mp3):
        os.remove(tmp_mp3)


def _speak_fish(text: str, tmp_mp3: str) -> bool:
    key, mid = os.getenv("FISH_AUDIO_KEY"), os.getenv("FISH_AUDIO_MODEL_ID")
    if not key or not mid:
        return False
    import urllib.request
    payload = json.dumps({"text": text, "reference_id": mid, "format": "mp3"}).encode("utf-8")
    req = urllib.request.Request("https://api.fish.audio/v1/tts", data=payload, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "model": "s2.1-pro-free"})
    with urllib.request.urlopen(req, timeout=8.0) as resp:
        with open(tmp_mp3, "wb") as f:
            f.write(resp.read())
    _speak_mci(tmp_mp3)
    return True


def speak(text: str) -> None:
    """TTS strictly via custom cloned Mike Ross voice (Fish Audio) with native SAPI fallback."""
    if not text.strip():
        return
    tmp_mp3 = os.path.abspath("temp_reply.mp3")
    try:
        if _speak_fish(text, tmp_mp3):
            return
    except Exception as exc:
        print(f"[Mike:tts] Fish Audio clone failed ({exc}); falling back to Windows SAPI.")
    import subprocess
    clean = text.replace("'", " ").replace('"', " ")
    cmd = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{clean}')"
    subprocess.run(["powershell", "-Command", cmd], capture_output=True)


def _get_vosk_model():
    """Lazy-loaded offline English-only STT model (Kaldi/C++ backend, no torch/onnxruntime)."""
    global _VOSK_MODEL
    if _VOSK_MODEL is None:
        import vosk
        vosk.SetLogLevel(-1)
        default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "vosk-model-small-en-us-0.15")
        model_path = os.getenv("VOSK_MODEL_PATH", default_path)
        _VOSK_MODEL = vosk.Model(model_path)
    return _VOSK_MODEL


def _capture_audio_vad(rate: int = 16000, frame_ms: int = 20, max_duration: float = 10.0, silence_ms: int = 700) -> bytes:
    """Record one utterance gated by WebRTC VAD: starts on detected speech, stops after trailing silence."""
    import sounddevice as sd
    import webrtcvad

    vad = webrtcvad.Vad(int(os.getenv("VAD_MODE", "2")))
    frame_len = int(rate * frame_ms / 1000)
    max_frames = int(max_duration * 1000 / frame_ms)
    silence_frames_needed = max(1, int(silence_ms / frame_ms))

    frames: list[bytes] = []
    triggered = False
    silence_count = 0
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16", blocksize=frame_len) as stream:
        for _ in range(max_frames):
            data, _ = stream.read(frame_len)
            pcm_bytes = data.tobytes()
            if len(pcm_bytes) < frame_len * 2:
                continue
            is_speech = vad.is_speech(pcm_bytes, rate)
            if is_speech:
                frames.append(pcm_bytes)
                triggered = True
                silence_count = 0
            elif triggered:
                frames.append(pcm_bytes)
                silence_count += 1
                if silence_count >= silence_frames_needed:
                    break
    return b"".join(frames)


def _transcribe(pcm_bytes: bytes, rate: int = 16000) -> str:
    """English-only offline transcription (Vosk) — structurally cannot output another language."""
    import vosk
    model = _get_vosk_model()
    rec = vosk.KaldiRecognizer(model, rate)
    rec.AcceptWaveform(pcm_bytes)
    result = json.loads(rec.FinalResult())
    return result.get("text", "").strip()


def _process_audio(session_id: str) -> None:
    global IS_ACTIVE
    from brain import converse
    from voice_gate import verify_speaker
    try:
        pcm = _capture_audio_vad()
        if not pcm:
            return
        audio_arr = np.frombuffer(pcm, dtype=np.int16)
        if not verify_speaker(audio_arr):
            return
        cmd = _transcribe(pcm)
        if not cmd:
            return
        print(f"[Fas]: {cmd}")
        if "standby" in cmd.lower():
            IS_ACTIVE = False
            speak("Entering standby mode, Fas.")
            return
        reply = converse(session_id, cmd)
        print(f"[Mike]: {reply}")
        speak(reply)
    except Exception as exc:
        print(f"[Mike:error] {exc}")


def listen_and_execute() -> None:
    """Always-On / Standby voice loop: VAD-gated capture, offline English STT, stateful conversation."""
    global IS_ACTIVE
    from voice_gate import check_hotkey_toggle
    session_id = f"voice-{os.getpid()}-{datetime.datetime.now():%Y%m%d%H%M%S}"
    user = os.getenv("USER_NAME", "Fas")
    name = os.getenv("ASSISTANT_NAME", "Mike Ross")
    greeting = f"Hello {user}. {name} is online and ready."
    print(f"\n[Mike]: {greeting}")
    print("[Mike]: Listening for voice commands... (Press F9 for Standby, Ctrl+C to quit)\n")
    speak(greeting)
    while True:
        if check_hotkey_toggle(int(os.getenv("OPTIONAL_TOGGLE_KEY_HEX", "0x78"), 16)):
            IS_ACTIVE = not IS_ACTIVE
            speak(f"Active mode, {user}" if IS_ACTIVE else f"Standby mode, {user}")
        if IS_ACTIVE:
            _process_audio(session_id)


if __name__ == "__main__":
    load_dotenv()
    listen_and_execute()
