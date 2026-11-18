import json
import os
import subprocess
import urllib.request
import sounddevice as sd


def _speak_fish_stream(text: str, emotion: str = "focused") -> bool:
    key = os.getenv("FISH_AUDIO_KEY")
    mid = os.getenv("FISH_AUDIO_MODEL_ID")
    if not key or not mid:
        return False
    sample_rate = 24000
    speed = 1.15 if emotion == "urgent" else 0.95 if emotion == "collaborative" else 1.0
    payload = json.dumps({
        "text": text,
        "reference_id": mid,
        "format": "pcm",
        "sample_rate": sample_rate,
        "latency": "balanced",
        "prosody": {"speed": speed, "volume": 0},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.fish.audio/v1/tts",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "model": "s2.1-pro-free",
        },
    )
    with urllib.request.urlopen(req, timeout=15.0) as resp:
        with sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16") as stream:
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                if len(chunk) % 2:
                    chunk = chunk[:-1]
                if chunk:
                    stream.write(chunk)
    return True


def _speak_sapi(text: str, emotion: str = "focused") -> None:
    rate = 2 if emotion == "urgent" else -1 if emotion == "collaborative" else 1 if emotion == "inquisitive" else 0
    clean = text.replace("'", " ").replace('"', " ")
    cmd = f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = {rate}; $s.Speak('{clean}')"
    subprocess.run(["powershell", "-Command", cmd], capture_output=True)


def speak(text: str, emotion: str = "focused") -> None:
    if not text or not text.strip():
        return
    try:
        if _speak_fish_stream(text, emotion=emotion):
            return
    except Exception:
        pass
    try:
        _speak_sapi(text, emotion=emotion)
    except Exception:
        pass
