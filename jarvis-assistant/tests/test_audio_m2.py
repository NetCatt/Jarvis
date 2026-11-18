import io
import os
import subprocess
import sys
import tempfile
import time
import wave
import psutil
import pytest

from audio import (
    DynamicVoiceEndpoint,
    StreamingTranscriber,
    check_hotkey,
    check_wake_phrase,
    render_live_token,
    speak,
    strip_wake_phrase,
)

def _generate_sapi_pcm(phrase: str) -> bytes:
    temp_dir = tempfile.gettempdir()
    wav_path = os.path.join(temp_dir, f"sapi_{int(time.time()*1000)}.wav").replace("\\", "/")
    ps_script = f"""
Add-Type -AssemblyName System.Speech
$syn = New-Object System.Speech.Synthesis.SpeechSynthesizer
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$syn.SetOutputToWaveFile('{wav_path}', $fmt)
$syn.Speak('{phrase}')
$syn.Dispose()
"""
    ps_path = os.path.join(temp_dir, f"gen_{int(time.time()*1000)}.ps1")
    with open(ps_path, "w", encoding="utf-8") as f:
        f.write(ps_script)
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_path], check=True, capture_output=True)
        with wave.open(wav_path, "rb") as wf:
            return wf.readframes(wf.getnframes())
    finally:
        if os.path.exists(ps_path):
            os.remove(ps_path)
        if os.path.exists(wav_path):
            os.remove(wav_path)

def test_audio_exports():
    assert StreamingTranscriber is not None
    assert DynamicVoiceEndpoint is not None
    assert callable(render_live_token)
    assert callable(speak)
    assert callable(check_hotkey)
    assert callable(check_wake_phrase)
    assert callable(strip_wake_phrase)

def test_vad_micro_pause_bridging():
    endpoint = DynamicVoiceEndpoint(sample_rate=16000, frame_ms=20, vad_mode=1)
    endpoint.reset()
    silent_frame = b"\x00" * endpoint.expected_frame_len
    for _ in range(12):
        endpoint.hangover_buffer.append(True)
    endpoint.triggered = True
    endpoint.silence_ms = 0
    for _ in range(3):
        is_speech, is_ep = endpoint.process_frame(silent_frame, "hello world testing")
        assert is_speech
        assert not is_ep
        assert endpoint.silence_ms == 0

def test_vad_context_adaptive_thresholds():
    endpoint = DynamicVoiceEndpoint(sample_rate=16000, frame_ms=20, vad_mode=1)
    silent_frame = b"\x00" * endpoint.expected_frame_len

    endpoint.reset()
    endpoint.triggered = True
    frames = 0
    for _ in range(100):
        frames += 1
        _, is_ep = endpoint.process_frame(silent_frame, "hello")
        if is_ep:
            break
    assert is_ep
    assert frames == 60

    endpoint.reset()
    endpoint.triggered = True
    frames = 0
    for _ in range(100):
        frames += 1
        _, is_ep = endpoint.process_frame(silent_frame, "open the browser now")
        if is_ep:
            break
    assert is_ep
    assert frames == 40

    for conj in ["and", "or", "to", "because", "with", "but"]:
        endpoint.reset()
        endpoint.triggered = True
        frames = 0
        for _ in range(100):
            frames += 1
            _, is_ep = endpoint.process_frame(silent_frame, f"open the browser {conj}")
            if is_ep:
                break
        assert is_ep
        assert frames == 70

def test_vad_short_conjunction_precedence():
    endpoint = DynamicVoiceEndpoint(sample_rate=16000, frame_ms=20, vad_mode=1)
    silent_frame = b"\x00" * endpoint.expected_frame_len

    for short_conj in ["Because", "and", "or", "to"]:
        endpoint.reset()
        endpoint.triggered = True
        frames = 0
        for _ in range(100):
            frames += 1
            _, is_ep = endpoint.process_frame(silent_frame, short_conj)
            if is_ep:
                break
        assert is_ep
        assert frames == 70

def test_vad_stop_phrase_word_boundaries():
    endpoint = DynamicVoiceEndpoint(sample_rate=16000, frame_ms=20, vad_mode=1, stop_phrase="over")
    silent_frame = b"\x00" * endpoint.expected_frame_len

    endpoint.reset()
    _, is_ep = endpoint.process_frame(silent_frame, "hello world over")
    assert is_ep
    assert endpoint.strip_stop_phrase("hello world over") == "hello world"

    endpoint.reset()
    _, is_ep = endpoint.process_frame(silent_frame, "over.")
    assert is_ep
    assert endpoint.strip_stop_phrase("over.") == ""

    endpoint.reset()
    _, is_ep = endpoint.process_frame(silent_frame, "OVER!")
    assert is_ep
    assert endpoint.strip_stop_phrase("OVER!") == ""

    endpoint.reset()
    for safe_word in ["I want to discover", "The handover", "moreover", "hover", "rollover", "leftover"]:
        endpoint.reset()
        _, is_ep = endpoint.process_frame(silent_frame, safe_word)
        assert not is_ep
        assert endpoint.strip_stop_phrase(safe_word) == safe_word

def test_terminal_rendering_ansi_escape():
    old_stdout = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    try:
        render_live_token("dynamic listening test")
    finally:
        sys.stdout = old_stdout
    out = buf.getvalue()
    assert "\r\033[K[Fas, live]: dynamic listening test" in out

def test_wake_phrase_and_hotkey():
    assert isinstance(check_hotkey(0x78), bool)
    assert check_wake_phrase("mike how is the project", ["mike", "ross"])
    assert check_wake_phrase("hey mike run tests", ["mike", "ross", "hey mike"])
    assert not check_wake_phrase("good morning computer", ["mike", "ross"])

    matched, stripped = strip_wake_phrase("hey mike run tests", ["mike", "ross", "hey mike"])
    assert matched
    assert stripped == "run tests"

    matched, stripped = strip_wake_phrase("hello friend", ["mike", "ross"])
    assert not matched
    assert stripped == "hello friend"

def test_real_speech_streaming_and_parent_rss():
    speech_pcm = _generate_sapi_pcm("open the browser and check the project status")
    assert len(speech_pcm) > 0

    transcriber = StreamingTranscriber()
    transcriber.start()

    partials = []
    for offset in range(0, len(speech_pcm), 640):
        chunk = speech_pcm[offset:offset + 640]
        text, _ = transcriber.feed_pcm(chunk)
        if text:
            partials.append(text)

    assert len(partials) > 0
    final_text = transcriber.get_final().lower()
    assert len(final_text.strip()) > 0
    assert "open" in final_text or "browser" in final_text or "project" in final_text

    transcriber.reset()
    assert transcriber.get_transcript() == ""
    transcriber.stop()

    code = """
import os, sys, psutil
sys.path.insert(0, os.path.abspath("."))
from audio import StreamingTranscriber
proc = psutil.Process()
rss_init = proc.memory_info().rss / 1048576
stt = StreamingTranscriber()
stt.start()
rss_start = proc.memory_info().rss / 1048576
for _ in range(20):
    stt.feed_pcm(b"\\x00" * 640)
rss_stream = proc.memory_info().rss / 1048576
stt.stop()
rss_stop = proc.memory_info().rss / 1048576
print(f"RSS_METRICS:{rss_init:.2f},{rss_start:.2f},{rss_stream:.2f},{rss_stop:.2f}")
"""
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    for line in res.stdout.splitlines():
        if line.startswith("RSS_METRICS:"):
            parts = [float(x) for x in line.split(":")[1].split(",")]
            for val in parts:
                assert val < 45.0
            return
    pytest.fail("RSS_METRICS not found in output")

def test_zero_comments_enforcement():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    audio_dir = os.path.join(base_dir, "audio")
    files_to_check = [
        os.path.join(audio_dir, f) for f in os.listdir(audio_dir) if f.endswith(".py")
    ]
    files_to_check.append(os.path.abspath(__file__))
    comment_char = chr(35)
    for file_path in files_to_check:
        with open(file_path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                assert comment_char not in line, f"Comment found in {file_path}:{idx}: {line.strip()}"
