import ctypes
import json
import os
import time

import numpy as np
from dotenv import load_dotenv

IS_ACTIVE = True
_VOSK_MODEL = None
_LAST_REPLY_TIME = 0.0


def _wake_words() -> list[str]:
    return [w.strip().lower() for w in os.getenv("WAKE_WORDS", "mike,ross,hey mike,hey ross").split(",") if w.strip()]


def _strip_wake_word(text: str) -> tuple[bool, str]:
    """Detect a wake word near the start of an utterance and strip it off the command text.
    Checks multi-word phrases ('hey mike') before single words so 'hey mike, play music' matches
    the phrase rather than stopping at a bare 'hey'."""
    words = text.split()
    low_words = [w.lower().strip(",.") for w in words]
    for wake in sorted(_wake_words(), key=lambda w: -len(w.split())):
        wake_parts = wake.split()
        n = len(wake_parts)
        if low_words[:n] == wake_parts:
            return True, " ".join(words[n:]).strip()
    return False, text


def _speak_mci(tmp_mp3: str) -> None:
    mci = ctypes.windll.winmm.mciSendStringW
    win_p = os.path.normpath(tmp_mp3)
    mci(f'open "{win_p}" type mpegvideo alias reply_audio', None, 0, 0)
    mci("play reply_audio wait", None, 0, 0)
    mci("close reply_audio", None, 0, 0)
    if os.path.exists(tmp_mp3):
        os.remove(tmp_mp3)


def _speak_fish_stream(text: str) -> bool:
    """Stream raw PCM straight into the output device as it arrives, instead of downloading a
    complete MP3 then opening it in MCI. This is the actual mechanism behind Fish Audio's
    'start talking before the whole clip is ready' latency claim — confirmed via their docs:
    the plain POST /v1/tts endpoint supports format='pcm' (no decode library needed, feed bytes
    straight to sounddevice) and latency='balanced' (lowest time-to-first-audio mode)."""
    key, mid = os.getenv("FISH_AUDIO_KEY"), os.getenv("FISH_AUDIO_MODEL_ID")
    if not key or not mid:
        return False
    import urllib.request
    import sounddevice as sd

    sample_rate = 24000
    payload = json.dumps({
        "text": text, "reference_id": mid, "format": "pcm",
        "sample_rate": sample_rate, "latency": "balanced",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.fish.audio/v1/tts", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "model": "s2.1-pro-free"},
    )
    with urllib.request.urlopen(req, timeout=15.0) as resp:
        with sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16") as stream:
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                if len(chunk) % 2:  # PCM16 frames must be whole samples (even byte count)
                    chunk = chunk[:-1]
                if chunk:
                    stream.write(chunk)
    return True


def _speak_fish_file(text: str, tmp_mp3: str) -> bool:
    """Fallback: download the complete MP3, then play it via MCI. Slower (no audio until the
    whole clip is generated) but the proven-reliable path if streaming playback fails for any
    reason — network hiccup, unexpected API response, etc."""
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
    """TTS strictly via custom cloned Mike Ross voice (Fish Audio) with native SAPI fallback.
    Three tiers, each falling through to the next on any failure: streaming PCM (fastest) ->
    full-file MP3 download+MCI (the previously-working path) -> Windows SAPI (last resort)."""
    if not text.strip():
        return
    try:
        if _speak_fish_stream(text):
            return
    except Exception as exc:
        print(f"[Mike:tts] Streaming playback failed ({exc}); falling back to full-file playback.")
    tmp_mp3 = os.path.abspath("temp_reply.mp3")
    try:
        if _speak_fish_file(text, tmp_mp3):
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


def _capture_and_transcribe(rate: int = 16000, frame_ms: int = 20) -> tuple[str, bytes]:
    """Record one utterance gated by WebRTC VAD, transcribing INCREMENTALLY as frames arrive
    instead of buffering the whole utterance and decoding it afterward. Vosk accepts audio in
    chunks natively, so feeding it frame-by-frame during capture overlaps decode time with
    capture time — by the time silence ends the utterance, most of the transcription work is
    already done, instead of stacking a full decode pass after the fact.

    Two independent capture budgets, NOT one shared cap: `VAD_LISTEN_TIMEOUT_SEC` is how long to
    wait silently for speech to start (gives up and returns empty if nothing is said), and
    `VAD_MAX_DURATION_SEC` is how long an utterance may run ONCE SPEECH STARTS. Counting both
    phases against a single cap (an earlier bug) truncated longer sentences mid-word whenever any
    time was spent waiting before Fas started talking.

    Returns (transcript, raw_pcm_bytes) — the raw bytes are still needed for speaker verification.
    """
    import sounddevice as sd
    import vosk
    import webrtcvad

    vad = webrtcvad.Vad(int(os.getenv("VAD_MODE", "1")))
    rec = vosk.KaldiRecognizer(_get_vosk_model(), rate)
    frame_len = int(rate * frame_ms / 1000)
    pre_trigger_max_frames = int(float(os.getenv("VAD_LISTEN_TIMEOUT_SEC", "8")) * 1000 / frame_ms)
    post_trigger_max_frames = int(float(os.getenv("VAD_MAX_DURATION_SEC", "20")) * 1000 / frame_ms)
    silence_frames_needed = max(1, int(int(os.getenv("VAD_SILENCE_MS", "650")) / frame_ms))

    frames: list[bytes] = []
    triggered = False
    silence_count = 0
    pre_count = 0
    post_count = 0
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16", blocksize=frame_len) as stream:
        while True:
            data, _ = stream.read(frame_len)
            pcm_bytes = data.tobytes()
            if len(pcm_bytes) < frame_len * 2:
                continue
            is_speech = vad.is_speech(pcm_bytes, rate)
            if not triggered:
                pre_count += 1
                if is_speech:
                    triggered = True
                    frames.append(pcm_bytes)
                    rec.AcceptWaveform(pcm_bytes)
                elif pre_count >= pre_trigger_max_frames:
                    return "", b""
                continue
            frames.append(pcm_bytes)
            rec.AcceptWaveform(pcm_bytes)  # incremental decode, overlapped with capture
            post_count += 1
            if is_speech:
                silence_count = 0
            else:
                silence_count += 1
                if silence_count >= silence_frames_needed:
                    break
            if post_count >= post_trigger_max_frames:
                break
    text = json.loads(rec.FinalResult()).get("text", "").strip()
    return text, b"".join(frames)


def _process_audio(session_id: str) -> None:
    global IS_ACTIVE, _LAST_REPLY_TIME
    from brain import converse
    from voice_gate import verify_speaker
    try:
        cmd, pcm = _capture_and_transcribe()
        if not pcm or not cmd:
            return
        audio_arr = np.frombuffer(pcm, dtype=np.int16)
        if not verify_speaker(audio_arr):
            return
        print(f"[Fas]: {cmd}")
        if "standby" in cmd.lower():
            IS_ACTIVE = False
            speak("Entering standby mode, Fas.")
            return

        # Only engage on a wake word ("Mike", "Ross", "hey Mike"...), or within a short grace
        # window right after Mike's last reply so a direct follow-up doesn't need re-waking.
        # Otherwise this is ambient speech/side-commentary not directed at him — ignore it
        # silently rather than trying to interpret every fragment as a command.
        woke, stripped = _strip_wake_word(cmd)
        grace_sec = float(os.getenv("WAKE_GRACE_SEC", "8"))
        in_grace = (time.time() - _LAST_REPLY_TIME) < grace_sec
        if not woke and not in_grace:
            print(f"[Mike:ignored, no wake word] {cmd}")
            return
        final_cmd = stripped if woke else cmd
        if not final_cmd.strip():
            return

        reply = converse(session_id, final_cmd)
        print(f"[Mike]: {reply}")
        speak(reply)
        _LAST_REPLY_TIME = time.time()
    except Exception as exc:
        print(f"[Mike:error] {exc}")


def listen_and_execute() -> None:
    """Always-On / Standby voice loop: VAD-gated capture, offline English STT, stateful conversation."""
    global IS_ACTIVE
    from voice_gate import check_hotkey_toggle
    # Stable across restarts, not randomized per launch (was `voice-{pid}-{timestamp}`) — a fresh
    # session id on every run meant a crash or manual restart silently wiped all short-term memory
    # and working state, which looked exactly like "forgets everything after one sentence." Memory
    # itself works correctly across turns (verified directly) when the session id stays constant;
    # it just wasn't staying constant across process restarts before.
    session_id = os.getenv("VOICE_SESSION_ID", "voice")
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
