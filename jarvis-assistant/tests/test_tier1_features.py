import io
import os
import subprocess
import sys
import pytest

from audio.stt import StreamingTranscriber, render_live_token
from audio.vad import DynamicVoiceEndpoint
import memory.retrieval as retrieval
import memory.store as store
from brain import _build_system_prompt


def test_dynamic_vad_endpointing_happy_path(pcm_factory):
    vad = DynamicVoiceEndpoint(vad_mode=2)
    for frame in pcm_factory.silence_stream(duration_ms=400):
        vad.process_frame(frame, "")
    assert not vad.triggered

    speech_frames = pcm_factory.speech_stream(duration_ms=300)
    for frame in speech_frames:
        is_sp, is_ep = vad.process_frame(frame, "run integration benchmark")
        assert not is_ep
    assert vad.triggered

    reached = False
    for frame in pcm_factory.silence_stream(duration_ms=1600):
        _, is_ep = vad.process_frame(frame, "run integration benchmark")
        if is_ep:
            reached = True
            break
    assert reached


def test_streaming_transcriber_startup_and_stop():
    model_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "vosk-model-en-us-0.22-lgraph"))
    if not os.path.exists(model_path):
        pytest.skip("Vosk model not present")
    stt = StreamingTranscriber(model_path=model_path)
    stt.start()
    assert stt.process is not None
    assert stt.process.poll() is None
    silence = bytes(640)
    transcript, is_final = stt.feed_pcm(silence)
    assert isinstance(transcript, str)
    assert isinstance(is_final, bool)
    stt.stop()
    assert stt.process is None


def test_ansi_live_token_rendering(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    render_live_token("synthesizing architecture")
    output = buf.getvalue()
    assert "\r\033[K" in output
    assert "[Fas, live]: synthesizing architecture" in output


def test_fts5_memory_turn_storage_and_recall(temp_db):
    store.record_turn("session_alpha", "user", "Refactor memory subsystem with zero-model SQLite FTS5")
    store.record_turn("session_alpha", "mike", "Implemented BM25 full-text indexing without dense embeddings")
    store.record_turn("session_alpha", "user", "Optimize active RSS under forty five megabytes")

    results = retrieval.recall("sqlite fts5", session_id="session_alpha")
    assert len(results) > 0
    assert any("zero-model SQLite FTS5" in r or "BM25" in r for r in results)

    results_rss = retrieval.recall("megabytes forty five", session_id="session_alpha")
    assert len(results_rss) > 0
    assert any("forty five megabytes" in r for r in results_rss)


def test_personality_traits_and_directives(temp_db):
    store.update_personality_trait(
        "proactive_lead",
        "Synthesize concrete implementation steps instead of reciting raw tool outputs.",
        delta_weight=0.5,
    )
    directives = store.get_active_personality_directives()
    assert len(directives) >= 1
    assert any("concrete implementation steps" in d for d in directives)


def test_learned_skills_store_and_query(temp_db):
    store.upsert_skill(
        "anti-overengineering",
        "architecture",
        "Enforce YAGNI and minimal code structure",
        "Avoid unnecessary abstractions",
    )
    store.upsert_skill(
        "token-efficiency",
        "performance",
        "Reduce context consumption and remove fluff",
        "Surgical line edits",
    )
    skills = store.query_skills("unnecessary abstractions", limit=2)
    assert len(skills) >= 1
    assert skills[0]["name"] == "anti-overengineering"


def test_tech_lead_prompt_synthesis_happy_path(temp_db):
    store.set_active_state("session_beta", current_project="jarvis-assistant", last_topic="audio-optimization")
    store.upsert_fact("Fas", "role", "Lead Architect")
    store.record_turn("session_beta", "user", "What is the next step for voice streaming?")

    prompt = _build_system_prompt("session_beta", "voice streaming")
    assert "Mike Ross" in prompt
    assert "jarvis-assistant" in prompt
    assert "audio-optimization" in prompt
    assert "Lead Architect" in prompt
    assert "Tier 1: Emergency" not in prompt


def test_rss_memory_budget_under_45mb():
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = """
import psutil
from audio.vad import DynamicVoiceEndpoint
from audio.stt import StreamingTranscriber
import memory.store as store
import memory.retrieval as retrieval
store.init_db()
vad = DynamicVoiceEndpoint(vad_mode=2)
silence = bytes(640)
for _ in range(200):
    vad.process_frame(silence, '')
for i in range(20):
    retrieval.recall('test query ' + str(i))
rss = psutil.Process().memory_info().rss / (1024 * 1024)
print(f'RSS:{rss:.2f}')
assert rss < 45.0, f'RSS exceeded: {rss}'
"""
    proc = subprocess.run([sys.executable, "-c", script], cwd=repo_dir, capture_output=True, text=True)
    assert proc.returncode == 0, f"Error: {proc.stderr}"
    assert "RSS:" in proc.stdout
