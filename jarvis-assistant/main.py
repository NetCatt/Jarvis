import asyncio
import ctypes
import os
import numpy as np
from dotenv import load_dotenv

IS_ACTIVE = True


def _speak_mci(tmp_mp3: str) -> None:
    mci = ctypes.windll.winmm.mciSendStringW
    mci(f'open "{tmp_mp3}" type mpegvideo alias reply_audio', None, 0, 0)
    mci("play reply_audio wait", None, 0, 0)
    mci("close reply_audio", None, 0, 0)
    if os.path.exists(tmp_mp3):
        os.remove(tmp_mp3)


def speak(text: str) -> None:
    """Low-latency edge-tts via winmm.dll mciSendStringW with native Windows SAPI fallback."""
    if not text.strip():
        return
    voice = os.getenv("TTS_VOICE", "en-GB-RyanNeural")
    tmp_mp3 = os.path.abspath("temp_reply.mp3")
    try:
        import edge_tts
        asyncio.run(edge_tts.Communicate(text, voice).save(tmp_mp3))
        _speak_mci(tmp_mp3)
    except Exception:
        import subprocess
        clean = text.replace("'", " ").replace('"', " ")
        cmd = f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{clean}')"
        subprocess.run(["powershell", "-Command", cmd], capture_output=True)


def _capture_audio_sd(duration: float = 4.0, rate: int = 16000) -> bytes:
    """Record PCM audio using pre-installed sounddevice backend (0 PyAudio dependency)."""
    import sounddevice as sd
    rec = sd.rec(int(duration * rate), samplerate=rate, channels=1, dtype="int16")
    sd.wait()
    return rec.tobytes()


def _process_audio(r) -> None:
    global IS_ACTIVE
    from brain import route_command
    from voice_gate import verify_speaker
    import speech_recognition as sr
    try:
        pcm = _capture_audio_sd(duration=4.0, rate=16000)
        audio_arr = np.frombuffer(pcm, dtype=np.int16)
        if np.abs(audio_arr).mean() < 300:
            return
        if not verify_speaker(audio_arr):
            return
        audio_data = sr.AudioData(pcm, 16000, 2)
        cmd = r.recognize_google(audio_data).strip()
        if not cmd:
            return
        print(f"[Fas]: {cmd}")
        if "standby" in cmd.lower():
            IS_ACTIVE = False
            speak("Entering standby mode, Fas.")
            return
        reply = route_command(cmd)
        print(f"[Mike]: {reply}")
        speak(reply)
    except Exception:
        pass


def listen_and_execute() -> None:
    """Always-On / Standby voice loop with sounddevice + Google STT."""
    global IS_ACTIVE
    import speech_recognition as sr
    from voice_gate import check_hotkey_toggle
    r = sr.Recognizer()
    print("[Mike]: Online. Listening for Fas (Press F9 for Standby)...")
    speak("Mike Ross online. Ready for Fas.")
    while True:
        if check_hotkey_toggle(int(os.getenv("OPTIONAL_TOGGLE_KEY_HEX", "0x78"), 16)):
            IS_ACTIVE = not IS_ACTIVE
            speak("Active mode, Fas" if IS_ACTIVE else "Standby mode, Fas")
        if IS_ACTIVE:
            _process_audio(r)


if __name__ == "__main__":
    load_dotenv()
    listen_and_execute()
