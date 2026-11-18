import datetime
import difflib
import json
import os
import re
import sqlite3
import threading
import time

_CONN = None
_INITIALIZED = False
_DB_LOCK = threading.RLock()

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

CREATE TABLE IF NOT EXISTS personality_traits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trait_key TEXT NOT NULL UNIQUE,
    directive TEXT NOT NULL,
    origin TEXT DEFAULT 'default',
    weight REAL DEFAULT 1.0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    pattern TEXT NOT NULL,
    usage_count INTEGER DEFAULT 1,
    effectiveness REAL DEFAULT 1.0,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(
    skill_id UNINDEXED,
    name,
    category,
    description,
    pattern,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
    turn_id UNINDEXED,
    session_id UNINDEXED,
    role UNINDEXED,
    content,
    created_at UNINDEXED,
    tokenize = 'porter unicode61'
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
    global _CONN, _INITIALIZED
    if _CONN is None:
        _CONN = sqlite3.connect(_db_path(), timeout=30.0, check_same_thread=False)
        _CONN.execute("PRAGMA journal_mode=WAL;")
        _CONN.execute("PRAGMA busy_timeout = 30000;")
        _CONN.execute("PRAGMA cache_size = -64;")
        _CONN.execute("PRAGMA mmap_size = 0;")
        _CONN.execute("PRAGMA temp_store = FILE;")
        _CONN.execute("PRAGMA wal_autocheckpoint = 100;")
        _CONN.row_factory = sqlite3.Row
        _INITIALIZED = False
    return _CONN


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def init_db(force: bool = False) -> None:
    global _INITIALIZED
    with _DB_LOCK:
        if _INITIALIZED and not force and _CONN is not None:
            return
        conn = _connect()
        conn.executescript(_SCHEMA)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()]
        if "embedding" in cols:
            try:
                conn.execute("ALTER TABLE conversations DROP COLUMN embedding")
            except Exception:
                pass

        conv_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM conversations_fts").fetchone()[0]
        if conv_count > 0 and fts_count == 0:
            conn.execute(
                "INSERT INTO conversations_fts (turn_id, session_id, role, content, created_at) SELECT id, session_id, role, text, created_at FROM conversations"
            )

        skills_count = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        skills_fts_count = conn.execute("SELECT COUNT(*) FROM skills_fts").fetchone()[0]
        if skills_count > 0 and skills_fts_count == 0:
            conn.execute(
                "INSERT INTO skills_fts (skill_id, name, category, description, pattern) SELECT id, name, category, description, pattern FROM skills"
            )
        conn.commit()
        _INITIALIZED = True


def get_active_state(session_id: str) -> dict:
    init_db()
    with _DB_LOCK:
        conn = _connect()
        row = conn.execute("SELECT * FROM active_state WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            return {
                "session_id": session_id,
                "current_project": "",
                "open_threads": [],
                "last_topic": "",
                "pending_followups": [],
            }
        return {
            "session_id": row["session_id"],
            "current_project": row["current_project"] or "",
            "open_threads": json.loads(row["open_threads"] or "[]"),
            "last_topic": row["last_topic"] or "",
            "pending_followups": json.loads(row["pending_followups"] or "[]"),
        }


def set_active_state(
    session_id: str,
    current_project: str | None = None,
    open_threads: list | None = None,
    last_topic: str | None = None,
    pending_followups: list | None = None,
) -> None:
    init_db()
    with _DB_LOCK:
        current = get_active_state(session_id)
        if current_project is not None:
            current["current_project"] = current_project
        if open_threads is not None:
            current["open_threads"] = open_threads[-8:]
        if last_topic is not None:
            current["last_topic"] = last_topic
        if pending_followups is not None:
            current["pending_followups"] = pending_followups[-8:]
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


def update_active_state(session_id: str, **fields) -> None:
    set_active_state(
        session_id,
        current_project=fields.get("current_project"),
        open_threads=fields.get("open_threads"),
        last_topic=fields.get("last_topic"),
        pending_followups=fields.get("pending_followups"),
    )


def get_active_personality_directives() -> list[str]:
    init_db()
    with _DB_LOCK:
        conn = _connect()
        rows = conn.execute(
            "SELECT directive FROM personality_traits WHERE weight >= 0.5 ORDER BY weight DESC, id DESC LIMIT 6"
        ).fetchall()
        return [row["directive"] for row in rows]


def update_personality_trait(
    trait_key: str, directive: str, delta_weight: float = 0.1, origin: str = "user_feedback"
) -> None:
    init_db()
    with _DB_LOCK:
        conn = _connect()
        row = conn.execute(
            "SELECT id, weight FROM personality_traits WHERE trait_key = ?", (trait_key,)
        ).fetchone()
        if row:
            new_weight = max(0.0, min(1.0, float(row["weight"]) + delta_weight))
            conn.execute(
                "UPDATE personality_traits SET directive = ?, weight = ?, origin = ?, updated_at = ? WHERE id = ?",
                (directive, new_weight, origin, _now(), row["id"]),
            )
        else:
            initial_weight = max(0.0, min(1.0, 1.0 + delta_weight if delta_weight < 0 else 1.0))
            conn.execute(
                "INSERT INTO personality_traits (trait_key, directive, origin, weight, updated_at) VALUES (?, ?, ?, ?, ?)",
                (trait_key, directive, origin, initial_weight, _now()),
            )
        conn.commit()


def upsert_fact(
    subject: str,
    predicate: str,
    value: str,
    confidence: float = 0.6,
    similarity_threshold: float = 0.6,
) -> None:
    init_db()
    with _DB_LOCK:
        conn = _connect()
        subject, predicate, value = subject.strip(), predicate.strip(), value.strip()
        existing = conn.execute(
            "SELECT id, value FROM facts WHERE subject = ? AND predicate = ?", (subject, predicate)
        ).fetchall()
        match_id = None
        for row in existing:
            if (
                row["value"] == value
                or difflib.SequenceMatcher(None, row["value"].lower(), value.lower()).ratio()
                >= similarity_threshold
            ):
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
    init_db()
    with _DB_LOCK:
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


def top_facts(subject: str | None = "Fas", limit: int = 8) -> list[dict]:
    init_db()
    with _DB_LOCK:
        conn = _connect()
        if subject:
            rows = conn.execute(
                "SELECT subject, predicate, value, confidence FROM facts WHERE subject = ? ORDER BY confidence DESC LIMIT ?",
                (subject, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT subject, predicate, value, confidence FROM facts ORDER BY confidence DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def upsert_skill(name: str, category: str, description: str, pattern: str) -> None:
    init_db()
    with _DB_LOCK:
        conn = _connect()
        row = conn.execute("SELECT id FROM skills WHERE name = ?", (name,)).fetchone()
        if row:
            skill_id = row["id"]
            conn.execute(
                "UPDATE skills SET category = ?, description = ?, pattern = ?, updated_at = ? WHERE id = ?",
                (category, description, pattern, _now(), skill_id),
            )
            conn.execute("DELETE FROM skills_fts WHERE skill_id = ?", (str(skill_id),))
            conn.execute(
                "INSERT INTO skills_fts (skill_id, name, category, description, pattern) VALUES (?, ?, ?, ?, ?)",
                (str(skill_id), name, category, description, pattern),
            )
        else:
            cur = conn.execute(
                "INSERT INTO skills (name, category, description, pattern, usage_count, effectiveness, updated_at) VALUES (?, ?, ?, ?, 1, 1.0, ?)",
                (name, category, description, pattern, _now()),
            )
            skill_id = cur.lastrowid
            conn.execute(
                "INSERT INTO skills_fts (skill_id, name, category, description, pattern) VALUES (?, ?, ?, ?, ?)",
                (str(skill_id), name, category, description, pattern),
            )
        conn.commit()


def query_skills(query: str, limit: int = 2) -> list[dict]:
    init_db()
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return []
    match_query = " OR ".join(f'"{t}"*' for t in tokens)
    with _DB_LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT name, category, description, pattern, bm25(skills_fts) AS rank FROM skills_fts WHERE skills_fts MATCH ? ORDER BY rank LIMIT ?",
                (match_query, limit),
            ).fetchall()
            return [
                {
                    "name": row["name"],
                    "category": row["category"],
                    "description": row["description"],
                    "pattern": row["pattern"],
                }
                for row in rows
            ]
        except Exception:
            return []


def record_turn(session_id: str, role: str, text: str) -> None:
    init_db()
    with _DB_LOCK:
        for attempt in range(5):
            try:
                conn = _connect()
                cur = conn.execute(
                    "INSERT INTO conversations (session_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                    (session_id, role, text, _now()),
                )
                turn_id = cur.lastrowid
                conn.execute(
                    "INSERT INTO conversations_fts (turn_id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (str(turn_id), session_id, role, text, _now()),
                )
                conn.commit()
                return
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() and attempt < 4:
                    time.sleep(0.05 * (2 ** attempt))
                    continue
                raise


def append_turn(session_id: str, role: str, text: str, embedding: object = None) -> None:
    record_turn(session_id, role, text)


def recent_turns(session_id: str, n: int = 6) -> list[dict]:
    init_db()
    with _DB_LOCK:
        conn = _connect()
        rows = conn.execute(
            "SELECT role, text, created_at FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, n),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def compact(session_id: str, keep_last: int = 20) -> None:
    init_db()
    with _DB_LOCK:
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
        conn.execute(
            f"DELETE FROM conversations_fts WHERE turn_id IN ({','.join('?' * len(stale_ids))})",
            [str(i) for i in stale_ids],
        )
        if summary and "LLM error" not in summary:
            cur = conn.execute(
                "INSERT INTO conversations (session_id, role, text, created_at) VALUES (?, 'summary', ?, ?)",
                (session_id, summary, _now()),
            )
            conn.execute(
                "INSERT INTO conversations_fts (turn_id, session_id, role, content, created_at) VALUES (?, ?, 'summary', ?, ?)",
                (str(cur.lastrowid), session_id, summary, _now()),
            )
        conn.commit()


def log_workflow(
    repo_path: str, task: str, agent_used: str, status: str, result_summary: str
) -> None:
    init_db()
    with _DB_LOCK:
        conn = _connect()
        conn.execute(
            "INSERT INTO workflows (repo_path, task, agent_used, status, result_summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (repo_path, task, agent_used, status, (result_summary or "")[:2000], _now()),
        )
        conn.commit()


def last_workflow(repo_path: str | None = None) -> dict | None:
    init_db()
    with _DB_LOCK:
        conn = _connect()
        if repo_path:
            row = conn.execute(
                "SELECT * FROM workflows WHERE repo_path = ? ORDER BY id DESC LIMIT 1",
                (repo_path,),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM workflows ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
