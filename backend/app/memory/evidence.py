"""Pointer-based episodic retrieval: memories point to the original messages that support them."""
from __future__ import annotations

import re
from typing import Any

from app.core.utils import truncate

_PAST_REFERENCE = re.compile(
    r"\b(last time|before|earlier|previously|again|what did i|did i (?:say|mention|tell)|remind me|"
    r"why do you think|how do you know|you said|we discussed|back to)\b",
    re.I,
)


async def resolve_evidence(db: Any, user_id: str, message_ids: list[str], limit: int = 5) -> list[dict[str, Any]]:
    ids = list(dict.fromkeys(message_ids))[:limit]
    if not ids:
        return []
    docs = await db.messages.find({"_id": {"$in": ids}, "user_id": user_id}).to_list(limit)
    found = {d["_id"]: d for d in docs}
    out = []
    for mid in ids:
        doc = found.get(mid)
        if doc is None:
            out.append({"message_id": mid, "missing": True,
                        "note": "Original message no longer stored (retention policy or deletion)"})
            continue
        out.append({
            "message_id": mid,
            "conversation_id": doc["conversation_id"],
            "role": doc["role"],
            "created_at": doc["created_at"],
            "redacted": bool(doc.get("redacted")),
            "content": truncate(doc["content"], 300),
        })
    return out


def needs_episodic_evidence(text: str, memories: list[dict[str, Any]]) -> tuple[bool, str]:
    """Gate: only fetch original messages when they are likely to matter."""
    if _PAST_REFERENCE.search(text):
        return True, "Question refers to a past interaction"
    weak = [m for m in memories if float(m.get("confidence", 1)) < 0.6]
    if weak:
        return True, "A relevant memory has low confidence; original evidence included"
    return False, ""
