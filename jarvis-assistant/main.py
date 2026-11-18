import os
import sys
import time
from dotenv import load_dotenv

from audio import (
    DynamicVoiceEndpoint,
    StreamingTranscriber,
    check_hotkey,
    check_wake_phrase,
    render_live_token,
    speak,
    strip_wake_phrase,
)
from brain import process_turn
from memory.store import init_db

load_dotenv()

IS_ACTIVE = True
_LAST_REPLY_TIME = 0.0


def _handle_speech_turn(transcriber: StreamingTranscriber, transcript: str, session_id: str) -> None:
    global _LAST_REPLY_TIME, IS_ACTIVE
    clean_text = transcript.strip()
    if not clean_text:
        return
    if "standby" in clean_text.lower():
        IS_ACTIVE = False
        speak("Entering standby mode, Fas.")
        return
    has_wake = check_wake_phrase(clean_text)
    grace_sec = float(os.getenv("WAKE_GRACE_SEC", "8"))
    in_grace = (time.time() - _LAST_REPLY_TIME) < grace_sec
    if not has_wake and not in_grace:
        return
    command_text = strip_wake_phrase(clean_text) if has_wake else clean_text
    if not command_text:
        return
    print(f"\n[Fas]: {command_text}")
    reply = process_turn(command_text, session_id=session_id)
    print(f"[Mike]: {reply}")
    speak(reply)
    _LAST_REPLY_TIME = time.time()


def run_orchestrator() -> None:
    global IS_ACTIVE
    init_db()
    session_id = os.getenv("VOICE_SESSION_ID", "voice")
    user = os.getenv("USER_NAME", "Fas")
    name = os.getenv("ASSISTANT_NAME", "Mike Ross")
    greeting = f"Hello {user}. {name} is online and ready."
    print(f"\n[Mike]: {greeting}")
    print("[Mike]: Listening for voice commands... (Press F9 for Standby, Ctrl+C to quit)\n")
    speak(greeting)

    transcriber = StreamingTranscriber()
    endpoint = DynamicVoiceEndpoint()
    transcriber.start()

    try:
        import sounddevice as sd
        frame_len = 320
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=frame_len) as stream:
            while True:
                if check_hotkey(0x78):
                    IS_ACTIVE = not IS_ACTIVE
                    speak(f"Active mode, {user}" if IS_ACTIVE else f"Standby mode, {user}")
                    time.sleep(0.3)
                pcm_data, _ = stream.read(frame_len)
                if not IS_ACTIVE:
                    time.sleep(0.02)
                    continue
                pcm_bytes = pcm_data.tobytes()
                partial_text, is_final = transcriber.feed_pcm(pcm_bytes)
                if partial_text:
                    render_live_token(partial_text)
                is_speech, is_endpoint = endpoint.process_frame(pcm_bytes, partial_text)
                if is_endpoint and partial_text:
                    _handle_speech_turn(transcriber, partial_text, session_id)
                    transcriber.reset()
                    endpoint.reset()
    except KeyboardInterrupt:
        pass
    finally:
        transcriber.stop()


if __name__ == "__main__":
    run_orchestrator()
