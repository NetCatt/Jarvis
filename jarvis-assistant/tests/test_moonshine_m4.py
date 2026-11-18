import io
import json
import os
import psutil
import pytest
import subprocess
import sys
import tempfile
import time

from audio.stt import StreamingTranscriber, render_live_token
from tests.test_audio_m2 import _generate_sapi_pcm

def test_moonshine_worker_direct_handshake_and_commands():
    worker_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audio", "moonshine_worker.py")
    proc = subprocess.Popen(
        [sys.executable, "-u", worker_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    ready_line = proc.stdout.readline().decode("utf-8", errors="replace").strip()
    assert ready_line == "READY"

    proc.stdin.write(b"CMD:RESET".ljust(640, b"\x00"))
    proc.stdin.flush()
    reset_line = proc.stdout.readline().decode("utf-8", errors="replace").strip()
    assert reset_line.startswith("FINAL:")
    reset_data = json.loads(reset_line[6:])
    assert reset_data.get("text") == ""

    proc.stdin.write(b"CMD:FINAL".ljust(640, b"\x00"))
    proc.stdin.flush()
    final_line = proc.stdout.readline().decode("utf-8", errors="replace").strip()
    assert final_line.startswith("FINAL:")
    final_data = json.loads(final_line[6:])
    assert final_data.get("text") == ""

    proc.stdin.close()
    proc.terminate()
    proc.wait(timeout=2.0)

def test_moonshine_worker_failure_on_invalid_model():
    worker_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audio", "moonshine_worker.py")
    env = os.environ.copy()
    env["MOONSHINE_MODEL_PATH"] = "C:/invalid_nonexistent_model_directory"
    proc = subprocess.Popen(
        [sys.executable, "-u", worker_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    stdout, stderr = proc.communicate(timeout=5.0)
    assert proc.returncode != 0
    assert b"ERROR:" in stderr

def test_streaming_transcriber_auto_detection_moonshine():
    stt = StreamingTranscriber(engine="auto")
    stt.start()
    assert stt.active_engine == "moonshine"
    for _ in range(10):
        transcript, is_final = stt.feed_pcm(b"\x00" * 640)
    final = stt.get_final()
    assert isinstance(final, str)
    stt.stop()
    assert stt.process is None

def test_streaming_transcriber_explicit_moonshine_engine():
    stt = StreamingTranscriber(engine="moonshine")
    stt.start()
    assert stt.active_engine == "moonshine"
    stt.stop()

def test_streaming_transcriber_fallback_when_moonshine_fails():
    old_env = os.environ.get("MOONSHINE_MODEL_PATH")
    os.environ["MOONSHINE_MODEL_PATH"] = "C:/nonexistent_dir_for_fallback_test"
    try:
        stt = StreamingTranscriber(engine="auto")
        stt.start()
        assert stt.active_engine == "vosk"
        stt.feed_pcm(b"\x00" * 640)
        stt.stop()
    finally:
        if old_env is not None:
            os.environ["MOONSHINE_MODEL_PATH"] = old_env
        else:
            os.environ.pop("MOONSHINE_MODEL_PATH", None)

def test_streaming_transcriber_explicit_vosk_engine():
    stt = StreamingTranscriber(engine="vosk")
    stt.start()
    assert stt.active_engine == "vosk"
    transcript, _ = stt.feed_pcm(b"\x00" * 640)
    stt.stop()

def test_mock_worker_token_streaming():
    mock_script_content = """import sys, json
sys.stdout.write("READY\\n")
sys.stdout.flush()
while True:
    chunk = sys.stdin.buffer.read(640)
    if not chunk:
        break
    if chunk.startswith(b"CMD:FINAL"):
        sys.stdout.write("FINAL:" + json.dumps({"text": "done"}) + "\\n")
        sys.stdout.flush()
    elif chunk.startswith(b"CMD:RESET"):
        sys.stdout.write("FINAL:" + json.dumps({"text": ""}) + "\\n")
        sys.stdout.flush()
    else:
        sys.stdout.write("PARTIAL:" + json.dumps({"partial": "hello mock"}) + "\\n")
        sys.stdout.flush()
"""
    temp_dir = tempfile.gettempdir()
    mock_path = os.path.join(temp_dir, f"mock_worker_{int(time.time()*1000)}.py")
    with open(mock_path, "w", encoding="utf-8") as f:
        f.write(mock_script_content)

    try:
        stt = StreamingTranscriber()
        stt.process = subprocess.Popen(
            [sys.executable, "-u", mock_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        line = stt.process.stdout.readline().decode("utf-8").strip()
        assert line == "READY"
        stt.active_engine = "mock"
        stt.reader_thread = None
        import threading
        stt.stop_event.clear()
        stt.reader_thread = threading.Thread(target=stt._reader_loop, daemon=True)
        stt.reader_thread.start()

        time.sleep(0.05)
        text, is_final = stt.feed_pcm(b"\x01\x02" * 320)
        time.sleep(0.05)
        text, is_final = stt.feed_pcm(b"\x01\x02" * 320)
        assert "hello mock" in stt.get_transcript()

        final = stt.get_final()
        assert "done" in final

        stt.reset()
        assert stt.get_transcript() == ""
        stt.stop()
    finally:
        if os.path.exists(mock_path):
            os.remove(mock_path)

def test_moonshine_real_speech_streaming():
    speech_pcm = _generate_sapi_pcm("synthesize technical architecture")
    assert len(speech_pcm) > 0

    stt = StreamingTranscriber(engine="moonshine")
    stt.start()
    assert stt.active_engine == "moonshine"

    partials = []
    for offset in range(0, len(speech_pcm), 640):
        chunk = speech_pcm[offset:offset + 640]
        text, _ = stt.feed_pcm(chunk)
        if text:
            partials.append(text)

    assert len(partials) > 0
    final_text = stt.get_final().lower()
    assert len(final_text.strip()) > 0
    assert "synthesize" in final_text or "technical" in final_text or "architecture" in final_text

    stt.reset()
    assert stt.get_transcript() == ""
    stt.stop()

def test_host_process_rss_under_45mb_with_moonshine():
    code = """import os, sys, psutil
sys.path.insert(0, os.path.abspath("."))
from audio.stt import StreamingTranscriber
proc = psutil.Process()
rss_init = proc.memory_info().rss / 1048576
stt = StreamingTranscriber(engine="moonshine")
stt.start()
rss_start = proc.memory_info().rss / 1048576
for _ in range(30):
    stt.feed_pcm(b"\\x00" * 640)
rss_stream = proc.memory_info().rss / 1048576
stt.stop()
rss_stop = proc.memory_info().rss / 1048576
print(f"MOONSHINE_RSS:{rss_init:.2f},{rss_start:.2f},{rss_stream:.2f},{rss_stop:.2f}")
"""
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    found = False
    for line in res.stdout.splitlines():
        if line.startswith("MOONSHINE_RSS:"):
            found = True
            vals = [float(x) for x in line.split(":")[1].split(",")]
            for v in vals:
                assert v < 45.0
    assert found

def test_reader_loop_buffer_poisoning_immunity():
    stt = StreamingTranscriber()
    class MockOut:
        def __init__(self):
            self.lines = [b"FINAL: bad_json\n", b'FINAL: {"text": "ok"}\n']
        def readline(self):
            return self.lines.pop(0) if self.lines else b""
    stt.process = type("MockProc", (), {"stdout": MockOut()})()
    stt.stop_event.clear()
    stt._reader_loop()
    items = []
    while not stt.out_queue.empty():
        items.append(stt.out_queue.get_nowait())
    assert any("ok" in item for item in items)

def test_feed_pcm_defensive_recovery_on_dead_worker():
    stt = StreamingTranscriber()
    class DeadProc:
        def __init__(self):
            self.stdin = None
        def poll(self):
            return 1
    stt.process = DeadProc()
    transcript, is_final = stt.feed_pcm(b"\x00" * 640)
    assert transcript == ""
    assert is_final is False

def test_zero_comments_in_moonshine_files():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_files = [
        os.path.join(base_dir, "audio", "moonshine_worker.py"),
        os.path.join(base_dir, "audio", "stt.py"),
        os.path.join(base_dir, "memory", "store.py"),
        os.path.abspath(__file__),
    ]
    comment_char = chr(35)
    for fpath in target_files:
        with open(fpath, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                assert comment_char not in line, f"Comment found in {fpath}:{idx}: {line.strip()}"
