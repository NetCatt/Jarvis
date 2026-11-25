import atexit
import json
import os
import re
import subprocess
import threading
import urllib.request
import sounddevice as sd

_KOKORO_PROC = None
_SPEAKING_LOCK = threading.Lock()
_IS_SPEAKING = False
_STOP_SPEAKING = threading.Event()
_SPEAK_THREAD = None
_SPEAK_GEN = 0

def is_speaking() -> bool:
    global _IS_SPEAKING
    return _IS_SPEAKING

def stop_speaking() -> None:
    global _IS_SPEAKING, _SPEAK_GEN
    with _SPEAKING_LOCK:
        _SPEAK_GEN += 1
        _IS_SPEAKING = False
    _STOP_SPEAKING.set()

def _chunk_speech_text(text: str, limit: int = 320) -> list[str]:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if len(clean) <= limit:
        return [clean] if clean else []
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    chunks, cur = [], ""
    for s in sentences:
        if cur and len(cur) + 1 + len(s) > limit:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip() if cur else s
    if cur:
        chunks.append(cur)
    return chunks

def _speak_fish_stream(text: str, emotion: str = "focused") -> bool:
    key = os.getenv("FISH_AUDIO_KEY")
    mid = os.getenv("FISH_AUDIO_MODEL_ID")
    if not key or not mid:
        return False
    sample_rate = 24000
    speed = 1.15 if emotion == "urgent" else 0.95 if emotion in ("collaborative", "empathetic") else 1.05 if emotion == "witty" else 1.0
    parts = _chunk_speech_text(text)
    if not parts:
        return False
    with sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16") as stream:
        carry = b""
        for part in parts:
            if _STOP_SPEAKING.is_set():
                break
            payload = json.dumps({
                "text": part,
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
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                while not _STOP_SPEAKING.is_set():
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    data = carry + chunk
                    rem = len(data) % 2
                    if rem:
                        carry = data[-rem:]
                        data = data[:-rem]
                    else:
                        carry = b""
                    if data and not _STOP_SPEAKING.is_set():
                        stream.write(data)
        if _STOP_SPEAKING.is_set():
            try:
                stream.abort()
            except Exception:
                pass
        else:
            stream.stop()
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
    global _IS_SPEAKING, _SPEAK_GEN
    if not text or not text.strip():
        return
    _STOP_SPEAKING.clear()
    with _SPEAKING_LOCK:
        _SPEAK_GEN += 1
        my_gen = _SPEAK_GEN
        _IS_SPEAKING = True
    try:
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
        if _STOP_SPEAKING.is_set():
            return
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
    finally:
        with _SPEAKING_LOCK:
            if my_gen == _SPEAK_GEN:
                _IS_SPEAKING = False

def speak_async(text: str, emotion: str = "focused") -> threading.Thread | None:
    global _SPEAK_THREAD
    if not text or not text.strip():
        return None
    stop_speaking()
    if _SPEAK_THREAD and _SPEAK_THREAD.is_alive():
        _SPEAK_THREAD.join(timeout=0.35)
    t = threading.Thread(target=speak, args=(text, emotion), daemon=True)
    _SPEAK_THREAD = t
    t.start()
    return t

def check_barge_in(audio_q, preroll, barge_buf, barge_hits: int, noise_floor: float, barge_min_rms: float, rms_fn) -> tuple[bool, int]:
    if os.getenv("ENABLE_BARGE_IN", "0") != "1":
        audio_q.clear()
        return False, 0
    thresh = max(barge_min_rms, noise_floor * 3.5)
    while audio_q and is_speaking():
        f = audio_q.popleft()
        barge_buf.append(f)
        barge_hits = barge_hits + 1 if rms_fn(f) >= thresh else 0
        if barge_hits >= 4:
            stop_speaking()
            preroll.extend(barge_buf)
            barge_buf.clear()
            return True, 0
    return False, barge_hits
