import re
from memory.store import _connect, init_db


def recall(
    query: str, session_id: str | None = None, k: int = 4, max_chars: int = 600
) -> list[str]:
    init_db()
    if not query or not isinstance(query, str):
        return []
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return []
    match_query = " OR ".join(f'"{t}"' for t in tokens)
    conn = _connect()
    try:
        if session_id:
            rows = conn.execute(
                "SELECT role, content, bm25(conversations_fts) AS rank FROM conversations_fts WHERE conversations_fts MATCH ? AND session_id = ? ORDER BY rank LIMIT ?",
                (match_query, session_id, k * 2),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT role, content, bm25(conversations_fts) AS rank FROM conversations_fts WHERE conversations_fts MATCH ? ORDER BY rank LIMIT ?",
                (match_query, k * 2),
            ).fetchall()
    except Exception:
        return []

    snippets = []
    budget = max_chars
    for row in rows:
        snippet = f"[{row['role']}] {row['content']}"[:200]
        if len(snippet) > budget:
            break
        snippets.append(snippet)
        budget -= len(snippet)
        if len(snippets) >= k:
            break
    return snippets
