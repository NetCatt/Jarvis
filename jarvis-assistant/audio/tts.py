import atexit
import json
import os
import subprocess
import urllib.request
import sounddevice as sd

_KOKORO_PROC = None


def _speak_fish_stream(text: str, emotion: str = "focused") -> bool:
    key = os.getenv("FISH_AUDIO_KEY")
    mid = os.getenv("FISH_AUDIO_MODEL_ID")
    if not key or not mid:
        return False
    sample_rate = 24000
    speed = 1.15 if emotion == "urgent" else 0.95 if emotion in ("collaborative", "empathetic") else 1.05 if emotion == "witty" else 1.0
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


def _get_kokoro_worker():
    global _KOKORO_PROC
    if _KOKORO_PROC is not None and _KOKORO_PROC.poll() is None:
        return _KOKORO_PROC
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    py_path = os.path.join(base_dir, ".venv-kokoro", "Scripts", "python.exe")
    worker_script = os.path.join(base_dir, "audio", "kokoro_worker.py")
    voice_path = os.path.join(base_dir, "data", "ross.pt")
    if not os.path.exists(py_path) or not os.path.exists(worker_script) or not os.path.exists(voice_path):
        return None
    try:
        proc = subprocess.Popen(
            [py_path, worker_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            if line.strip() == "READY":
                _KOKORO_PROC = proc
                return _KOKORO_PROC
        proc.terminate()
        return None
    except Exception:
        return None


def _speak_kokoro(text: str, emotion: str = "focused") -> bool:
    worker = _get_kokoro_worker()
    if not worker:
        return False
    speed = 1.15 if emotion == "urgent" else 0.95 if emotion in ("collaborative", "empathetic") else 1.05 if emotion == "witty" else 1.0
    payload = json.dumps({"text": text, "speed": speed}) + "\n"
    try:
        worker.stdin.write(payload)
        worker.stdin.flush()
        resp_line = worker.stdout.readline()
        if not resp_line:
            return False
        res = json.loads(resp_line.strip())
        return res.get("status") == "done"
    except Exception:
        return False


def _cleanup_kokoro():
    global _KOKORO_PROC
    if _KOKORO_PROC is not None:
        try:
            if _KOKORO_PROC.poll() is None:
                _KOKORO_PROC.stdin.write("CMD:STOP\n")
                _KOKORO_PROC.stdin.flush()
                _KOKORO_PROC.wait(timeout=1.0)
        except Exception:
            try:
                _KOKORO_PROC.terminate()
            except Exception:
                pass
        _KOKORO_PROC = None


atexit.register(_cleanup_kokoro)


def _speak_sapi(text: str, emotion: str = "focused") -> None:
    rate = 2 if emotion == "urgent" else -1 if emotion == "collaborative" else 1 if emotion == "inquisitive" else 0
    clean = text.replace("'", " ").replace('"', " ")
    cmd = f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = {rate}; $s.Speak('{clean}')"
    subprocess.run(["powershell", "-Command", cmd], capture_output=True)


def speak(text: str, emotion: str = "focused") -> None:
    if not text or not text.strip():
        return
    engine = os.getenv("TTS_ENGINE", "fish_audio").lower()
    if engine == "kokoro" or os.getenv("ENABLE_KOKORO_TTS", "0") == "1":
        try:
            if _speak_kokoro(text, emotion=emotion):
                return
        except Exception:
            pass
    try:
        if _speak_fish_stream(text, emotion=emotion):
            return
    except Exception:
        pass
    if engine != "sapi" and os.getenv("ENABLE_KOKORO_FALLBACK", "0") == "1":
        try:
            if _speak_kokoro(text, emotion=emotion):
                return
        except Exception:
            pass
    try:
        _speak_sapi(text, emotion=emotion)
    except Exception:
        pass
