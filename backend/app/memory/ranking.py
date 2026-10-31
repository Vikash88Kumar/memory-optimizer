"""Configurable weighted ranking with an explanation for every retrieved memory."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.memory import decay

TYPE_WEIGHTS = {
    "preference": 1.0, "constraint": 0.9, "learning_difficulty": 0.9, "strategy": 0.9, "goal": 0.8,
    "decision": 0.7, "interest": 0.7, "knowledge": 0.6, "experience": 0.6, "feedback": 0.6, "fact": 0.6,
}


@dataclass
class Scored:
    memory: dict[str, Any]
    similarity: float
    score: float
    strength: float
    reasons: list[str] = field(default_factory=list)
    graph_reason: str | None = None
    scope_match: bool = False
    pinned: bool = False

    @property
    def id(self) -> str:
        return self.memory["_id"]


def detect_subjects(text: str, settings: Settings | None = None) -> set[str]:
    settings = settings or get_settings()
    words = set(re.findall(r"[a-z]+", text.lower()))
    found = set()
    for canonical, aliases in settings.subject_aliases.items():
        if canonical in words or any(a in words for a in aliases):
            found.add(canonical)
    return found


def scope_subject(memory: dict[str, Any]) -> str | None:
    scope = memory.get("scope") or "global"
    return scope.split(":", 1)[1] if scope.startswith("topic:") else None


def score_memory(memory: dict[str, Any], *, similarity: float, now: dt.datetime, subjects: set[str],
                 graph_reason: str | None = None, pinned: bool = False,
                 settings: Settings | None = None) -> Scored | None:
    """Return None when the memory does not apply (scoped to a different subject)."""
    s = settings or get_settings()
    subject = scope_subject(memory)
    if subject and subject not in subjects:
        return None
    strength = decay.strength_at(memory, now)
    importance = float(memory.get("importance", 0.5))
    confidence = float(memory.get("confidence", 0.5))
    type_w = TYPE_WEIGHTS.get(memory.get("type", ""), 0.6)
    scope_match = bool(subject)
    score = (
        s.w_similarity * similarity
        + s.w_importance * importance
        + s.w_confidence * confidence
        + s.w_strength * strength
        + s.w_type * type_w
        + s.w_graph * (1.0 if graph_reason else 0.0)
        + s.w_scope * (1.0 if scope_match else 0.0)
    )
    reasons = []
    if pinned:
        reasons.append("Core profile: high-confidence item pinned for this session")
    if similarity >= s.min_similarity:
        reasons.append(f"Semantic match with your message ({similarity:.2f})")
    if graph_reason:
        reasons.append(graph_reason)
    if scope_match:
        reasons.append(f"Scoped to {subject}, which this message is about")
    reasons.append(f"Importance {importance:.2f}, confidence {confidence:.2f}")
    if float(memory.get("decay_lambda", 0)) > 0:
        reasons.append(f"Current strength {strength:.2f} (fades with time since last use)")
    if memory.get("confirmation") == "pending":
        reasons.append("Unconfirmed inference - used tentatively")
    return Scored(memory=memory, similarity=similarity, score=round(score, 4), strength=round(strength, 4),
                  reasons=reasons, graph_reason=graph_reason, scope_match=scope_match, pinned=pinned)


def passes_gate(item: Scored, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return item.pinned or bool(item.graph_reason) or item.scope_match or item.similarity >= s.min_similarity


def resolve_scope_overrides(items: list[Scored]) -> tuple[list[Scored], list[dict[str, Any]]]:
    """A topic-scoped memory overrides a global memory with the same key, for that topic only."""
    scoped_keys = {i.memory.get("key") for i in items if i.scope_match and i.memory.get("key")}
    kept, overridden = [], []
    for item in items:
        key = item.memory.get("key")
        if key in scoped_keys and not item.scope_match:
            overridden.append({
                "id": item.id, "content": item.memory["content"], "type": item.memory["type"],
                "reason": "Overridden by a topic-specific preference for this question",
            })
        else:
            kept.append(item)
    return kept, overridden
