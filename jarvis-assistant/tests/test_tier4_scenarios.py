import os
import subprocess
import sys
from unittest.mock import MagicMock, patch
import pytest

import memory.retrieval as retrieval
import memory.store as store
from brain import _build_system_prompt, converse


def test_multi_turn_conversational_lifecycle(temp_db):
    session_id = "session_lifecycle"
    store.set_active_state(session_id, current_project="jarvis-assistant", last_topic="memory-redesign")

    store.record_turn(session_id, "user", "We are redesigning the memory store to remove dense embeddings.")
    store.record_turn(session_id, "mike", "Switched memory to zero-model SQLite FTS5 with BM25 ranking.")
    store.record_turn(session_id, "user", "Ensure active RSS remains strictly under 45 megabytes.")
    store.record_turn(session_id, "mike", "Profiled memory footprint under load; active RSS is 34 megabytes.")

    state = store.get_active_state(session_id)
    assert state["current_project"] == "jarvis-assistant"
    assert state["last_topic"] == "memory-redesign"

    recalled = retrieval.recall("memory threshold megabytes", session_id=session_id, k=2)
    assert len(recalled) > 0
    assert any("45 megabytes" in r or "34 megabytes" in r for r in recalled)


def test_task_blocker_inquiry_and_actionable_breakdown(temp_db):
    session_id = "session_blocker"
    store.set_active_state(session_id, current_project="jarvis-assistant", last_topic="stt-memory-isolation")
    store.upsert_fact("Fas", "focus", "dual-core i3 optimization")

    user_query = "The Vosk model in the main process exceeds our 45 MB budget. What can we do about it?"

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.function_calls = None
    mock_resp.text = (
        "Diagnose: Vosk Kaldi model loads acoustic graph taking ~200MB in-process. "
        "Strategy: Decouple vosk_worker into a headless child process communicating over binary stdio pipes. "
        "Action: Main process keeps only DynamicVoiceEndpoint (<35MB RSS), streaming raw PCM frames to worker."
    )
    mock_resp.candidates = [MagicMock()]
    mock_client.models.generate_content.return_value = mock_resp

    with patch("brain._get_client", return_value=mock_client):
        reply = converse(session_id, user_query)

    assert mock_client.models.generate_content.called

    call_kwargs = mock_client.models.generate_content.call_args.kwargs
    sys_prompt = call_kwargs["config"].system_instruction
    assert "Mike Ross" in sys_prompt
    assert "jarvis-assistant" in sys_prompt
    assert "stt-memory-isolation" in sys_prompt
    assert "dual-core i3 optimization" in sys_prompt
    assert "Tier 1: Emergency" not in sys_prompt
    assert "Tier 2: High" not in sys_prompt

    assert "Decouple" in reply
    assert "pipes" in reply
    assert "Tier 1" not in reply

    turns = store.recent_turns(session_id)
    assert len(turns) >= 2
    assert turns[-2]["role"] == "user"
    assert turns[-2]["text"] == user_query
    assert turns[-1]["role"] == "mike"
    assert turns[-1]["text"] == reply

    recalled = retrieval.recall("decouple vosk worker", session_id=session_id)
    assert len(recalled) > 0
    assert any("Decouple" in r for r in recalled)


def test_skill_learning_and_subsequent_recall(temp_db):
    store.upsert_skill(
        "sqlite-concurrency",
        "database",
        "Use PRAGMA synchronous = NORMAL and journal_mode = WAL for concurrent reader-writer operations",
        "sqlite3.connect(..., check_same_thread=False)",
    )

    query = "How should we configure SQLite for concurrency?"
    matched = store.query_skills(query, limit=1)
    assert len(matched) == 1
    assert matched[0]["name"] == "sqlite-concurrency"
    assert "journal_mode = WAL" in matched[0]["description"]


def test_database_persistence_across_process_restarts(temp_db):
    session_id = "session_persist"
    store.set_active_state(session_id, current_project="jarvis-core", last_topic="persistence-test")
    store.upsert_fact("Fas", "editor", "VS Code")
    store.record_turn(session_id, "user", "Persistent memory verification across restarts")
    store.record_turn(session_id, "mike", "Verified database durability")
    store.upsert_skill("code-modularity", "architecture", "Enforce strict module boundaries", "One concern per module")
    store.update_personality_trait("lead_persona", "Act as a proactive Technical Project Lead.", delta_weight=0.0)

    if store._CONN is not None:
        store._CONN.close()
        store._CONN = None

    state = store.get_active_state(session_id)
    assert state["current_project"] == "jarvis-core"
    assert state["last_topic"] == "persistence-test"

    facts = store.top_facts("Fas")
    assert any(f["predicate"] == "editor" and f["value"] == "VS Code" for f in facts)

    recalled = retrieval.recall("Persistent memory", session_id=session_id)
    assert len(recalled) > 0
    assert "Persistent memory verification" in recalled[0]

    skills = store.query_skills("code modularity", limit=1)
    assert len(skills) == 1
    assert skills[0]["name"] == "code-modularity"

    directives = store.get_active_personality_directives()
    assert any("Technical Project Lead" in d for d in directives)


def test_prolonged_session_memory_stability_under_45mb():
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = """
import psutil
from audio.vad import DynamicVoiceEndpoint
import memory.store as store
import memory.retrieval as retrieval

store.init_db()
vad = DynamicVoiceEndpoint(vad_mode=2)

for i in range(100):
    store.record_turn("stress_sess", "user", f"Turn query item {i} regarding database performance")
    store.record_turn("stress_sess", "mike", f"Turn response item {i} describing action plan")

silence = bytes(640)
for _ in range(200):
    vad.process_frame(silence, "database performance")

for i in range(40):
    retrieval.recall(f"database performance item {i}", session_id="stress_sess")

rss = psutil.Process().memory_info().rss / (1024 * 1024)
print(f"PROLONGED_SESSION_RSS:{rss:.2f}")
assert rss < 45.0, f"Memory exceeded 45 MB: {rss}"
"""
    proc = subprocess.run([sys.executable, "-c", script], cwd=repo_dir, capture_output=True, text=True)
    assert proc.returncode == 0, f"Failed: {proc.stderr}"
    assert "PROLONGED_SESSION_RSS:" in proc.stdout
