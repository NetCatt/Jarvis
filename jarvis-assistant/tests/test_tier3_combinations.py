import json
import os
import subprocess
import sys
from unittest.mock import MagicMock
import pytest

from audio.vad import DynamicVoiceEndpoint
import memory.retrieval as retrieval
import memory.store as store
from brain import _build_system_prompt
from tools.dispatch import dispatch_coding_agent


def test_speech_stream_to_fts5_recall_pipeline(pcm_factory, temp_db):
    session_id = "session_pipeline"
    store.record_turn(session_id, "user", "How do we prevent audio buffer underrun in the vosk worker?")
    store.record_turn(session_id, "mike", "Use unbuffered binary pipes with 640 byte chunks.")

    vad = DynamicVoiceEndpoint(vad_mode=2)
    simulated_transcript = "buffer underrun vosk worker"
    for frame in pcm_factory.speech_stream(duration_ms=200):
        vad.process_frame(frame, simulated_transcript)
    assert vad.triggered

    reached = False
    for frame in pcm_factory.silence_stream(duration_ms=1200):
        _, is_ep = vad.process_frame(frame, simulated_transcript)
        if is_ep:
            reached = True
            break
    assert reached

    snippets = retrieval.recall(simulated_transcript, session_id=session_id, k=2)
    assert len(snippets) > 0
    assert any("buffer underrun" in s for s in snippets)


def test_fts5_context_to_lead_prompt_injection(temp_db):
    session_id = "session_prompt_inj"
    store.record_turn(session_id, "user", "The hardware budget is dual-core i3 with 45 MB RSS.")
    store.record_turn(session_id, "mike", "All STT and RAG routines will run within that boundary.")

    prompt = _build_system_prompt(session_id, "hardware budget")
    assert "Relevant past context:" in prompt
    assert "dual-core i3 with 45 MB RSS" in prompt or "boundary" in prompt


def test_personality_evolution_influences_lead_prompt(temp_db):
    store.update_personality_trait(
        "proactive_root_cause",
        "Diagnose technical root causes before suggesting code changes.",
        delta_weight=0.0,
    )
    store.update_personality_trait(
        "modularity_enforcement",
        "Enforce strict modular separation across all components.",
        delta_weight=-0.2,
    )
    directives = store.get_active_personality_directives()
    assert len(directives) >= 2
    assert "Diagnose technical root causes" in directives[0]
    assert "Enforce strict modular separation" in directives[1]


def test_lead_reasoning_to_agent_dispatch_workflow_logging(temp_db, monkeypatch):
    mock_claude_json = {
        "result": "Created audio/vosk_worker.py and isolated STT memory to child process.",
        "is_error": False,
        "total_cost_usd": 0.035,
    }

    class FakeProc:
        stdout = json.dumps(mock_claude_json)
        stderr = ""
        returncode = 0

    monkeypatch.setattr("tools.dispatch._find_claude_cli", lambda: "fake_claude.exe")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeProc())

    task = "Isolate STT memory footprint using child worker"
    res = dispatch_coding_agent(task, agent="architect", repo_path=".")
    assert "Created audio/vosk_worker.py" in res

    workflow = store.last_workflow()
    assert workflow is not None
    assert workflow["task"] == task
    assert workflow["agent_used"] in ("architect", "Plan")
    assert workflow["status"] == "success"
    assert "$0.035" in workflow["result_summary"]


def test_combined_pipeline_memory_rss_budget():
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = """
import psutil
from audio.vad import DynamicVoiceEndpoint
import memory.store as store
import memory.retrieval as retrieval

store.init_db()
vad = DynamicVoiceEndpoint(vad_mode=2)

for i in range(10):
    store.record_turn("pipeline_sess", "user", f"Turn query item {i} regarding database index optimization")
    store.record_turn("pipeline_sess", "mike", f"Turn response item {i} with concrete execution plan")

silence = bytes(640)
for _ in range(100):
    vad.process_frame(silence, "database index")

for _ in range(20):
    retrieval.recall("database index optimization", session_id="pipeline_sess")

store.update_personality_trait("trait_a", "Directive A", delta_weight=0.1)
directives = store.get_active_personality_directives()

store.log_workflow(".", "task_x", "general", "success", "summary")
wf = store.last_workflow()

rss = psutil.Process().memory_info().rss / (1024 * 1024)
print(f"COMBINED_PIPELINE_RSS:{rss:.2f}")
assert rss < 45.0, f"RSS exceeded 45 MB: {rss}"
"""
    proc = subprocess.run([sys.executable, "-c", script], cwd=repo_dir, capture_output=True, text=True)
    assert proc.returncode == 0, f"Failed: {proc.stderr}"
    assert "COMBINED_PIPELINE_RSS:" in proc.stdout
