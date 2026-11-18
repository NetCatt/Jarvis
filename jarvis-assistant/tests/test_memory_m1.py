import os
import psutil
import pytest
import sqlite3
import sys
import tempfile

import memory.store as store
import memory.retrieval as retrieval
import memory.embeddings as embeddings


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test_memory.db")
    monkeypatch.setenv("MEMORY_DB_PATH", db_file)
    store._CONN = None
    yield db_file
    if store._CONN:
        store._CONN.close()
        store._CONN = None


def test_init_db_and_schema():
    store.init_db()
    conn = store._connect()
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow') OR (type='table' AND sql LIKE '%fts5%')"
        ).fetchall()
    ]
    for required in [
        "active_state",
        "facts",
        "personality_traits",
        "skills",
        "skills_fts",
        "conversations",
        "conversations_fts",
        "workflows",
    ]:
        assert required in tables


def test_schema_migration(tmp_path, monkeypatch):
    mig_db = str(tmp_path / "legacy.db")
    monkeypatch.setenv("MEMORY_DB_PATH", mig_db)
    store._CONN = None

    conn = sqlite3.connect(mig_db)
    conn.execute(
        """CREATE TABLE conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        text TEXT,
        embedding BLOB,
        created_at TEXT
    )"""
    )
    conn.execute(
        "INSERT INTO conversations (session_id, role, text, embedding, created_at) VALUES ('s1', 'user', 'legacy turn', X'000102', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    store.init_db()
    c = store._connect()
    cols = [r[1] for r in c.execute("PRAGMA table_info(conversations)").fetchall()]
    assert "embedding" not in cols

    fts_rows = c.execute("SELECT turn_id, content FROM conversations_fts").fetchall()
    assert len(fts_rows) == 1
    assert fts_rows[0]["content"] == "legacy turn"


def test_active_state_crud():
    state = store.get_active_state("s_test")
    assert state["session_id"] == "s_test"
    assert state["current_project"] == ""
    assert state["open_threads"] == []
    assert state["last_topic"] == ""
    assert state["pending_followups"] == []

    store.set_active_state(
        "s_test",
        current_project="jarvis",
        open_threads=["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9"],
        last_topic="memory",
        pending_followups=["f1"],
    )

    updated = store.get_active_state("s_test")
    assert updated["current_project"] == "jarvis"
    assert len(updated["open_threads"]) == 8
    assert updated["open_threads"][-1] == "t9"
    assert updated["last_topic"] == "memory"
    assert updated["pending_followups"] == ["f1"]

    store.update_active_state("s_test", last_topic="rag")
    re_updated = store.get_active_state("s_test")
    assert re_updated["last_topic"] == "rag"
    assert re_updated["current_project"] == "jarvis"


def test_personality_traits_evolution():
    store.update_personality_trait("terse", "Be terse and direct.", delta_weight=0.0)
    store.update_personality_trait("proactive", "Act as a technical project lead.", delta_weight=0.0)
    store.update_personality_trait("verbose", "Explain everything in excessive detail.", delta_weight=-0.6)

    directives = store.get_active_personality_directives()
    assert "Be terse and direct." in directives
    assert "Act as a technical project lead." in directives
    assert "Explain everything in excessive detail." not in directives

    store.update_personality_trait("terse", "Be terse and direct.", delta_weight=-0.6)
    directives_after_decay = store.get_active_personality_directives()
    assert "Be terse and direct." not in directives_after_decay

    store.update_personality_trait("terse", "Be terse and direct.", delta_weight=0.3)
    directives_restored = store.get_active_personality_directives()
    assert "Be terse and direct." in directives_restored


def test_facts_upsert_and_decay():
    store.upsert_fact("Fas", "role", "Lead Architect", confidence=0.8)
    store.upsert_fact("Fas", "role", "lead architect", confidence=0.8)

    facts = store.top_facts("Fas", limit=5)
    assert len(facts) == 1
    assert facts[0]["predicate"] == "role"
    assert facts[0]["confidence"] > 0.8
    assert facts[0]["value"] == "Lead Architect"


def test_skills_upsert_and_bm25_query():
    store.upsert_skill(
        name="anti-overengineering",
        category="architecture",
        description="Enforce YAGNI and KISS with minimal abstractions.",
        pattern="Review PR for unnecessary wrappers and speculative generalization.",
    )
    store.upsert_skill(
        name="token-efficiency",
        category="performance",
        description="Slash context consumption and eliminate token burn.",
        pattern="Surgical edits and line-targeted reading.",
    )

    results = store.query_skills("overengineering YAGNI", limit=1)
    assert len(results) == 1
    assert results[0]["name"] == "anti-overengineering"
    assert results[0]["category"] == "architecture"

    store.upsert_skill(
        name="anti-overengineering",
        category="architecture",
        description="Enforce strict YAGNI, KISS, and minimal abstractions.",
        pattern="Updated pattern.",
    )
    updated_results = store.query_skills("strict YAGNI", limit=1)
    assert len(updated_results) == 1
    assert "strict" in updated_results[0]["description"]


def test_conversations_and_bm25_recall():
    store.record_turn("s1", "user", "How do we implement SQLite FTS5 BM25 search?")
    store.record_turn("s1", "mike", "Use porter unicode61 tokenizer with unindexed metadata columns.")
    store.record_turn("s2", "user", "What is the capital of France?")
    store.record_turn("s2", "mike", "The capital of France is Paris.")

    recent = store.recent_turns("s1", n=2)
    assert len(recent) == 2
    assert recent[0]["role"] == "user"
    assert recent[1]["role"] == "mike"

    recalled_s1 = retrieval.recall("SQLite FTS5", session_id="s1", k=2)
    assert len(recalled_s1) >= 1
    assert any("FTS5" in r or "porter" in r for r in recalled_s1)
    assert not any("Paris" in r for r in recalled_s1)

    recalled_global = retrieval.recall("Paris France", k=2)
    assert len(recalled_global) >= 1
    assert any("Paris" in r for r in recalled_global)


def test_compact_removes_and_summarizes(monkeypatch):
    monkeypatch.setattr("tools.llm.generate_text", lambda prompt, temperature=0.0: "User discussed tasks.")
    for i in range(25):
        store.record_turn("s_comp", "user", f"Turn number {i}")

    store.compact("s_comp", keep_last=10)
    turns = store.recent_turns("s_comp", n=30)
    assert len(turns) <= 12
    assert any(t["role"] == "summary" for t in turns)


def test_workflows():
    store.log_workflow(".", "Refactor memory", "teamwork_worker", "success", "Refactored to 4-tier SQLite")
    wf = store.last_workflow(".")
    assert wf is not None
    assert wf["task"] == "Refactor memory"
    assert wf["status"] == "success"


def test_embeddings_zero_heavy_deps():
    assert embeddings.embed("test") is None
    assert embeddings.cosine(None, None) == 0.0

    forbidden = ["model2vec", "torch"]
    for mod in forbidden:
        assert mod not in sys.modules


def test_rss_memory_under_45mb():
    import subprocess
    code = """
import psutil, memory.store as store, memory.retrieval as retrieval
store.init_db()
for i in range(100):
    store.record_turn("perf_sess", "user", f"Synthetic turn payload for BM25 ranking {i}")
for i in range(50):
    retrieval.recall("Synthetic turn ranking", session_id="perf_sess", k=4)
    store.query_skills("architecture YAGNI", limit=2)
rss_mb = psutil.Process().memory_info().rss / 1024 / 1024
print(f"STANDALONE_RSS:{rss_mb:.2f}")
"""
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    for line in res.stdout.splitlines():
        if line.startswith("STANDALONE_RSS:"):
            rss = float(line.split(":")[1])
            print(f"Subprocess RSS: {rss:.2f} MB")
            assert rss < 45.0
            return
    pytest.fail("STANDALONE_RSS not found in output")
