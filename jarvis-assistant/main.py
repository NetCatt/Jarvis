import asyncio
import ctypes
import os
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
    """Low-latency edge-tts via winmm.dll mciSendStringW with pyttsx3 fallback."""
    if not text.strip():
        return
    voice = os.getenv("TTS_VOICE", "en-US-ChristopherNeural")
    tmp_mp3 = os.path.abspath("temp_reply.mp3")
    try:
        import edge_tts
        asyncio.run(edge_tts.Communicate(text, voice).save(tmp_mp3))
        _speak_mci(tmp_mp3)
    except Exception:
        import pyttsx3
        engine = pyttsx3.init("sapi5")
        engine.say(text)
        engine.runAndWait()


def _process_audio(r, source) -> None:
    global IS_ACTIVE
    from brain import route_command
    from voice_gate import verify_speaker
    try:
        audio = r.listen(source, timeout=3.0, phrase_time_limit=8.0)
        pcm = audio.get_raw_data(convert_rate=16000, convert_width=2)
        if not verify_speaker(pcm):
            return
        cmd = r.recognize_google(audio).strip()
        if "standby" in cmd.lower():
            IS_ACTIVE = False
            speak("Entering standby.")
            return
        reply = route_command(cmd)
        speak(reply)
    except Exception:
        pass


def listen_and_execute() -> None:
    """Always-On / Standby voice loop with audio self-trigger mute guard."""
    global IS_ACTIVE
    import speech_recognition as sr
    from voice_gate import check_hotkey_toggle
    r = sr.Recognizer()
    r.dynamic_energy_threshold, r.energy_threshold = False, 400
    with sr.Microphone(sample_rate=16000) as source:
        print("[Jarvis]: Online. Listening...")
        while True:
            if check_hotkey_toggle(int(os.getenv("OPTIONAL_TOGGLE_KEY_HEX", "0x78"), 16)):
                IS_ACTIVE = not IS_ACTIVE
                speak("Active mode" if IS_ACTIVE else "Standby mode")
            if IS_ACTIVE:
                _process_audio(r, source)


if __name__ == "__main__":
    load_dotenv()
    listen_and_execute()
