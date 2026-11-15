import numpy as np

from memory.embeddings import cosine, embed
from memory.store import candidate_turns


def recall(query: str, session_id: str | None = None, k: int = 4, max_chars: int = 600) -> list[str]:
    """Episodic (tier-3) recall: cosine-rank recency-bounded candidates, return compact snippets.

    This is the fallback long-tail layer only — working state (tier 1) and durable facts
    (tier 2) are loaded unconditionally elsewhere and should not depend on this succeeding.
    """
    candidates = candidate_turns(session_id=session_id)
    if not candidates:
        return []
    q_vec = embed(query)
    scored = []
    for row in candidates:
        try:
            vec = np.frombuffer(row["embedding"], dtype=np.float32)
            score = cosine(q_vec, vec)
        except Exception:
            continue
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    snippets = []
    budget = max_chars
    for score, row in scored[:k]:
        if score < 0.3:
            continue
        snippet = f"[{row['role']}] {row['text']}"[:200]
        if len(snippet) > budget:
            break
        snippets.append(snippet)
        budget -= len(snippet)
    return snippets
