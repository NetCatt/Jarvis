import datetime
import difflib
import json
import os
import sqlite3

import numpy as np

_CONN = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS active_state (
    session_id TEXT PRIMARY KEY,
    current_project TEXT DEFAULT '',
    open_threads TEXT DEFAULT '[]',
    last_topic TEXT DEFAULT '',
    pending_followups TEXT DEFAULT '[]',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.6,
    evidence_count INTEGER DEFAULT 1,
    last_reinforced TEXT,
    UNIQUE(subject, predicate, value)
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    role TEXT,
    text TEXT,
    embedding BLOB,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id, id);

CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_path TEXT,
    task TEXT,
    agent_used TEXT,
    status TEXT,
    result_summary TEXT,
    created_at TEXT
);
"""


def _db_path() -> str:
    p = os.getenv("MEMORY_DB_PATH", "data/memory.db")
    if not os.path.isabs(p):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), p)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        _CONN = sqlite3.connect(_db_path(), check_same_thread=False)
        _CONN.execute("PRAGMA journal_mode=WAL;")
        _CONN.row_factory = sqlite3.Row
    return _CONN


def init_db() -> None:
    conn = _connect()
    conn.executescript(_SCHEMA)
    conn.commit()


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---- Tier 1: working memory ----

def get_active_state(session_id: str) -> dict:
    init_db()
    conn = _connect()
    row = conn.execute("SELECT * FROM active_state WHERE session_id = ?", (session_id,)).fetchone()
    if not row:
        return {"current_project": "", "open_threads": [], "last_topic": "", "pending_followups": []}
    return {
        "current_project": row["current_project"] or "",
        "open_threads": json.loads(row["open_threads"] or "[]"),
        "last_topic": row["last_topic"] or "",
        "pending_followups": json.loads(row["pending_followups"] or "[]"),
    }


def update_active_state(session_id: str, **fields) -> None:
    """Merge-update slots. List-valued fields (open_threads, pending_followups) are capped to last 8 entries."""
    init_db()
    current = get_active_state(session_id)
    current.update({k: v for k, v in fields.items() if v is not None})
    current["open_threads"] = current["open_threads"][-8:]
    current["pending_followups"] = current["pending_followups"][-8:]
    conn = _connect()
    conn.execute(
        """INSERT INTO active_state (session_id, current_project, open_threads, last_topic, pending_followups, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET
             current_project=excluded.current_project, open_threads=excluded.open_threads,
             last_topic=excluded.last_topic, pending_followups=excluded.pending_followups, updated_at=excluded.updated_at""",
        (
            session_id,
            current["current_project"],
            json.dumps(current["open_threads"]),
            current["last_topic"],
            json.dumps(current["pending_followups"]),
            _now(),
        ),
    )
    conn.commit()


# ---- Tier 2: durable facts (confidence + decay) ----

def upsert_fact(subject: str, predicate: str, value: str, confidence: float = 0.6, similarity_threshold: float = 0.6) -> None:
    """Insert a fact, or reinforce an existing similar one (subject+predicate match, fuzzy value match)
    instead of creating a near-duplicate row for slightly different phrasing of the same fact."""
    init_db()
    conn = _connect()
    subject, predicate, value = subject.strip(), predicate.strip(), value.strip()
    existing = conn.execute(
        "SELECT id, value FROM facts WHERE subject = ? AND predicate = ?", (subject, predicate)
    ).fetchall()
    match_id = None
    for row in existing:
        if row["value"] == value or difflib.SequenceMatcher(None, row["value"].lower(), value.lower()).ratio() >= similarity_threshold:
            match_id = row["id"]
            break
    if match_id is not None:
        conn.execute(
            "UPDATE facts SET confidence = MIN(0.99, confidence + 0.15), evidence_count = evidence_count + 1, last_reinforced = ? WHERE id = ?",
            (_now(), match_id),
        )
    else:
        conn.execute(
            "INSERT INTO facts (subject, predicate, value, confidence, evidence_count, last_reinforced) VALUES (?, ?, ?, ?, 1, ?)",
            (subject, predicate, value, confidence, _now()),
        )
    conn.commit()


def decay_facts(halflife_days: float = 30.0, floor: float = 0.05) -> None:
    """Soft-decay confidence for facts not recently reinforced. Call periodically, not per-turn."""
    init_db()
    conn = _connect()
    rows = conn.execute("SELECT id, confidence, last_reinforced FROM facts").fetchall()
    now = datetime.datetime.now()
    for r in rows:
        try:
            last = datetime.datetime.fromisoformat(r["last_reinforced"])
        except Exception:
            continue
        days = (now - last).total_seconds() / 86400.0
        if days <= halflife_days:
            continue
        decayed = max(floor, r["confidence"] * (0.5 ** (days / halflife_days)))
        conn.execute("UPDATE facts SET confidence = ? WHERE id = ?", (decayed, r["id"]))
    conn.commit()


def top_facts(subject: str = "Fas", limit: int = 8) -> list[dict]:
    init_db()
    conn = _connect()
    rows = conn.execute(
        "SELECT subject, predicate, value, confidence FROM facts WHERE subject = ? ORDER BY confidence DESC LIMIT ?",
        (subject, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- Tier 3: episodic turns + embeddings ----

def append_turn(session_id: str, role: str, text: str, embedding: np.ndarray | None = None) -> None:
    init_db()
    conn = _connect()
    blob = embedding.astype(np.float32).tobytes() if embedding is not None else None
    conn.execute(
        "INSERT INTO conversations (session_id, role, text, embedding, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, role, text, blob, _now()),
    )
    conn.commit()


def recent_turns(session_id: str, n: int = 6) -> list[dict]:
    init_db()
    conn = _connect()
    rows = conn.execute(
        "SELECT role, text, created_at FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, n),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def candidate_turns(session_id: str | None = None, limit: int = 500) -> list[dict]:
    """Recency-bounded candidate pool for embedding-based recall (tier 3)."""
    init_db()
    conn = _connect()
    if session_id:
        rows = conn.execute(
            "SELECT id, role, text, embedding, created_at FROM conversations WHERE session_id = ? AND embedding IS NOT NULL ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, role, text, embedding, created_at FROM conversations WHERE embedding IS NOT NULL ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def compact(session_id: str, keep_last: int = 20) -> None:
    """Summarize+archive turns beyond the active window to bound DB/prompt growth over time."""
    init_db()
    conn = _connect()
    rows = conn.execute(
        "SELECT id FROM conversations WHERE session_id = ? ORDER BY id DESC", (session_id,)
    ).fetchall()
    if len(rows) <= keep_last:
        return
    stale_ids = [r["id"] for r in rows[keep_last:]]
    old_rows = conn.execute(
        f"SELECT role, text FROM conversations WHERE id IN ({','.join('?' * len(stale_ids))}) ORDER BY id",
        stale_ids,
    ).fetchall()
    if not old_rows:
        return
    from tools.llm import generate_text

    transcript = "\n".join(f"{r['role']}: {r['text']}" for r in old_rows)
    summary = generate_text(
        f"Summarize this older conversation chunk into 2-3 short factual bullet points worth remembering long-term:\n{transcript}",
        temperature=0.0,
    )
    conn.execute(
        f"DELETE FROM conversations WHERE id IN ({','.join('?' * len(stale_ids))})", stale_ids
    )
    if summary and "LLM error" not in summary:
        conn.execute(
            "INSERT INTO conversations (session_id, role, text, embedding, created_at) VALUES (?, 'summary', ?, NULL, ?)",
            (session_id, summary, _now()),
        )
    conn.commit()


# ---- Workflow log (agent dispatch history) ----

def log_workflow(repo_path: str, task: str, agent_used: str, status: str, result_summary: str) -> None:
    init_db()
    conn = _connect()
    conn.execute(
        "INSERT INTO workflows (repo_path, task, agent_used, status, result_summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (repo_path, task, agent_used, status, result_summary[:2000], _now()),
    )
    conn.commit()
