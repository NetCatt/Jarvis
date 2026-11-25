import collections
import os
import sys
import time
from dotenv import load_dotenv

from audio import DynamicVoiceEndpoint, StreamingTranscriber, check_barge_in, check_hotkey, check_wake_phrase, frame_rms, is_speaking, render_live_token, speak, speak_async, stop_speaking, strip_wake_phrase
from brain import process_turn
from memory.store import init_db

load_dotenv()

IS_ACTIVE = True
_LAST_REPLY_TIME = 0.0
_LAST_TTS_TIME = 0.0

def _handle_speech_turn(transcript: str, session_id: str, endpoint: DynamicVoiceEndpoint = None) -> None:
    global _LAST_REPLY_TIME, _LAST_TTS_TIME, IS_ACTIVE
    clean_text = endpoint.strip_stop_phrase(transcript.strip()).strip() if endpoint else transcript.strip()
    if not clean_text: return
    if "standby" in clean_text.lower(): IS_ACTIVE = False; speak("Entering standby mode, Fas."); _LAST_TTS_TIME = time.time(); return
    has_wake = check_wake_phrase(clean_text)
    in_grace = (time.time() - _LAST_REPLY_TIME) < float(os.getenv("WAKE_GRACE_SEC", "30"))
    if os.getenv("REQUIRE_WAKE_WORD", "true").lower() in ("true", "1") and not has_wake and not in_grace: return
    command_text = clean_text
    if has_wake:
        matched, stripped = strip_wake_phrase(clean_text)
        command_text = stripped.strip() if matched and stripped.strip() else clean_text
    if not command_text or (has_wake and clean_text.lower() in ("mike", "hey mike", "ross", "hey ross")):
        reply = "I'm right here, Fas. What do you need?"
        print(f"\n[Fas]: {clean_text}\n[Mike]: {reply}")
        speak_async(reply); _LAST_REPLY_TIME = _LAST_TTS_TIME = time.time(); return
    print(f"\n[Fas]: {command_text}")
    reply = process_turn(command_text, session_id=session_id)
    print(f"[Mike]: {reply}")
    speak_async(reply); _LAST_REPLY_TIME = _LAST_TTS_TIME = time.time()

def run_orchestrator() -> None:
    global IS_ACTIVE, _LAST_TTS_TIME
    init_db()
    session_id, user, name = os.getenv("VOICE_SESSION_ID", "voice"), os.getenv("USER_NAME", "Fas"), os.getenv("ASSISTANT_NAME", "Mike Ross")
    greeting = f"Hello {user}. {name} is online and ready."
    print(f"\n[Mike]: {greeting}\n[Mike]: Listening for voice commands... (Press F9 for Standby, Ctrl+C to quit)\n")
    speak_async(greeting); _LAST_TTS_TIME = time.time()
    engine_mode = os.getenv("STT_ENGINE", "groq").lower()
    min_speech, echo_guard, barge_min_rms = int(os.getenv("VAD_MIN_SPEECH_FRAMES", "12")), float(os.getenv("TTS_ECHO_GUARD_SEC", "0.75")), float(os.getenv("BARGE_IN_MIN_RMS", "1400"))
    transcriber = StreamingTranscriber(engine=engine_mode)
    endpoint = DynamicVoiceEndpoint(vad_mode=int(os.getenv("VAD_MODE", "3")), base_silence_ms=int(os.getenv("VAD_SILENCE_MS", "550")), onset_frames=int(os.getenv("VAD_ONSET_FRAMES", "5")))
    transcriber.start()
    audio_q, preroll, barge_buf, utterance_pcm = collections.deque(maxlen=250), collections.deque(maxlen=20), collections.deque(maxlen=6), bytearray()
    was_triggered, partial_text, barge_hits = False, "", 0

    def _audio_cb(indata, frames, time_info, status):
        if IS_ACTIVE: audio_q.append(bytes(indata))

    def _reset_turn():
        nonlocal was_triggered, partial_text
        partial_text = ""; utterance_pcm.clear(); endpoint.reset(); transcriber.reset(); preroll.clear(); was_triggered = False

    try:
        import sounddevice as sd
        with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=320, callback=_audio_cb):
            while True:
                if check_hotkey(0x78):
                    IS_ACTIVE = not IS_ACTIVE; stop_speaking(); audio_q.clear()
                    speak_async(f"Active mode, {user}" if IS_ACTIVE else f"Standby mode, {user}"); _LAST_TTS_TIME = time.time(); time.sleep(0.3)
                if not IS_ACTIVE:
                    audio_q.clear(); _reset_turn(); time.sleep(0.02); continue
                if is_speaking():
                    _LAST_TTS_TIME = time.time()
                    barged, barge_hits = check_barge_in(audio_q, preroll, barge_buf, barge_hits, endpoint.noise_floor, barge_min_rms, frame_rms)
                    if barged: _LAST_TTS_TIME = 0.0
                    if is_speaking(): time.sleep(0.01); continue
                elif (time.time() - _LAST_TTS_TIME) <= echo_guard:
                    audio_q.clear(); barge_buf.clear(); barge_hits = 0; _reset_turn(); time.sleep(0.01); continue
                if not audio_q: time.sleep(0.005); continue
                pcm_bytes = audio_q.popleft()
                _, is_endpoint = endpoint.process_frame(pcm_bytes, partial_text)
                if endpoint.triggered:
                    if not was_triggered:
                        was_triggered = True
                        for f in preroll:
                            if engine_mode != "groq": transcriber.feed_pcm(f, drain_timeout=0.0)
                            utterance_pcm.extend(f)
                        preroll.clear()
                    utterance_pcm.extend(pcm_bytes)
                    if engine_mode != "groq":
                        partial_text, _ = transcriber.feed_pcm(pcm_bytes, drain_timeout=0.0)
                        if partial_text: render_live_token(partial_text)
                else:
                    preroll.append(pcm_bytes); was_triggered = False
                if is_endpoint:
                    if endpoint.active_speech_frames < min_speech:
                        _reset_turn(); continue
                    final_text = (transcriber.transcribe_hybrid(bytes(utterance_pcm), partial_hint=partial_text) if engine_mode in ("groq", "hybrid") else (transcriber.get_final() or partial_text)).strip()
                    sys.stdout.write("\r\033[K"); sys.stdout.flush()
                    if not final_text or final_text.lower().strip(".,!?") in ("um", "uh", "er", "ah", "hmm", "umm", "uhh"):
                        _reset_turn(); continue
                    _handle_speech_turn(final_text, session_id, endpoint)
                    audio_q.clear(); _reset_turn()
    except KeyboardInterrupt:
        pass
    finally:
        stop_speaking(); transcriber.stop()

if __name__ == "__main__":
    run_orchestrator()
