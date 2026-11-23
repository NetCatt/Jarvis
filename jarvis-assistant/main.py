import collections
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


def _handle_speech_turn(transcript: str, session_id: str, endpoint: DynamicVoiceEndpoint = None) -> None:
    global _LAST_REPLY_TIME, IS_ACTIVE
    clean_text = transcript.strip()
    if endpoint:
        clean_text = endpoint.strip_stop_phrase(clean_text).strip()
    if not clean_text:
        return
    if "standby" in clean_text.lower(): IS_ACTIVE = False; speak("Entering standby mode, Fas."); return
    has_wake = check_wake_phrase(clean_text)
    grace_sec = float(os.getenv("WAKE_GRACE_SEC", "30"))
    in_grace = (time.time() - _LAST_REPLY_TIME) < grace_sec
    require_wake = os.getenv("REQUIRE_WAKE_WORD", "true").lower() in ("true", "1")
    if require_wake and not has_wake and not in_grace:
        return
    command_text = clean_text
    if has_wake:
        matched, stripped = strip_wake_phrase(clean_text)
        command_text = stripped.strip() if matched and stripped.strip() else clean_text
    if not command_text or (has_wake and clean_text.lower() in ("mike", "hey mike", "ross", "hey ross")):
        reply = "I'm right here, Fas. What do you need?"
        print(f"\n[Fas]: {clean_text}\n[Mike]: {reply}")
        speak(reply); _LAST_REPLY_TIME = time.time(); return
    print(f"\n[Fas]: {command_text}")
    reply = process_turn(command_text, session_id=session_id)
    print(f"[Mike]: {reply}")
    speak(reply); _LAST_REPLY_TIME = time.time()


def run_orchestrator() -> None:
    global IS_ACTIVE, _LAST_REPLY_TIME
    init_db()
    session_id = os.getenv("VOICE_SESSION_ID", "voice")
    user, name = os.getenv("USER_NAME", "Fas"), os.getenv("ASSISTANT_NAME", "Mike Ross")
    greeting = f"Hello {user}. {name} is online and ready."
    print(f"\n[Mike]: {greeting}\n[Mike]: Listening for voice commands... (Press F9 for Standby, Ctrl+C to quit)\n")
    speak(greeting); _LAST_REPLY_TIME = time.time()

    transcriber = StreamingTranscriber()
    endpoint = DynamicVoiceEndpoint(vad_mode=int(os.getenv("VAD_MODE", "1")))
    transcriber.start()
    preroll = collections.deque(maxlen=20)
    was_triggered, partial_text = False, ""

    try:
        import sounddevice as sd
        frame_len = 320
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=frame_len) as stream:
            while True:
                if check_hotkey(0x78):
                    IS_ACTIVE = not IS_ACTIVE
                    speak(f"Active mode, {user}" if IS_ACTIVE else f"Standby mode, {user}"); time.sleep(0.3)
                pcm_data, _ = stream.read(frame_len)
                if not IS_ACTIVE:
                    time.sleep(0.02); continue
                pcm_bytes = pcm_data.tobytes()
                is_speech, is_endpoint = endpoint.process_frame(pcm_bytes, partial_text)
                if endpoint.triggered:
                    if not was_triggered:
                        was_triggered = True
                        for f in preroll:
                            transcriber.feed_pcm(f)
                        preroll.clear()
                    partial_text, _ = transcriber.feed_pcm(pcm_bytes)
                    if partial_text:
                        render_live_token(partial_text)
                else:
                    preroll.append(pcm_bytes)
                    was_triggered = False
                if is_endpoint:
                    final_text = (transcriber.get_final() or partial_text).strip()
                    partial_text = ""
                    if not final_text or final_text.lower().strip(".,!?") in ("um", "uh", "er", "ah", "hmm", "umm", "uhh"):
                        endpoint.reset(); transcriber.reset(); preroll.clear(); was_triggered = False; continue
                    sys.stdout.write("\r\033[K"); sys.stdout.flush()
                    stream.stop()
                    _handle_speech_turn(final_text, session_id, endpoint)
                    transcriber.reset(); endpoint.reset(); preroll.clear(); was_triggered = False; stream.start()
    except KeyboardInterrupt:
        pass
    finally:
        transcriber.stop()


if __name__ == "__main__":
    run_orchestrator()
