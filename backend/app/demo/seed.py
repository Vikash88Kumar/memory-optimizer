"""Sample data for the demo account. It goes through the real lifecycle code (embeddings, graph,
events) but is created only for the dedicated demo user and is flagged seed=True."""
from __future__ import annotations

import datetime as dt
from typing import Any

from app.agents.memory_consolidator import apply_extraction
from app.core.config import get_settings
from app.core.security import hash_password
from app.core.utils import new_id, utcnow
from app.llm.embeddings import Embedder
from app.memory import episodes
from app.models.extraction import ExtractionInput, ExtractionMessage, ExtractionResult

USER_COLLECTIONS = ["conversations", "messages", "memories", "entities", "relationships", "memory_events",
                    "episodes", "sessions", "context_logs", "tombstones"]

SEED_TURNS = [
    ("user", "I'm learning NLP these days, and eventually I want to build AI agents."),
    ("assistant", "That's a great path: NLP fundamentals feed directly into building agents."),
    ("user", "Honestly I struggle with recursion. The call stack confuses me."),
    ("assistant", "Recursion trips up a lot of people. We can trace the call stack together step by step."),
]


async def ensure_demo_user(db: Any, embedder: Embedder) -> dict[str, Any]:
    s = get_settings()
    user = await db.users.find_one({"username": s.demo_username})
    if user:
        return user
    now = utcnow()
    user = {"_id": new_id("usr"), "username": s.demo_username, "display_name": "Demo student",
            "password_hash": hash_password(s.demo_password), "is_demo": True, "workspaces": ["default"],
            "memory_version": 0, "clock_offset_seconds": 0, "created_at": now}
    await db.users.insert_one(user)
    await seed_sample_data(db, user, embedder)
    return await db.users.find_one({"_id": user["_id"]})


async def reset_user_data(db: Any, user_id: str) -> None:
    for name in USER_COLLECTIONS:
        await db[name].delete_many({"user_id": user_id})
    await db.users.update_one({"_id": user_id}, {"$set": {"memory_version": 0, "clock_offset_seconds": 0, "state": {}}})


async def seed_sample_data(db: Any, user: dict[str, Any], embedder: Embedder) -> None:
    ws = "default"
    start = utcnow() - dt.timedelta(days=2)
    conv_id = new_id("conv")
    await db.conversations.insert_one({"_id": conv_id, "user_id": user["_id"], "workspace_id": ws,
                                       "title": "Earlier session (sample data)", "created_at": start,
                                       "updated_at": start, "total_tokens": 0, "message_count": len(SEED_TURNS),
                                       "seed": True})
    episode = await episodes.open_episode(db, user_id=user["_id"], workspace_id=ws, conversation_id=conv_id,
                                          now=start, first_text=SEED_TURNS[0][1])
    msgs: list[ExtractionMessage] = []
    for i, (role, text) in enumerate(SEED_TURNS):
        at = start + dt.timedelta(minutes=i)
        mid = new_id("msg")
        emb = await embedder.embed_one(text, "query") if role == "user" else None
        doc = {"_id": mid, "user_id": user["_id"], "workspace_id": ws, "conversation_id": conv_id, "role": role,
               "content": text, "tokens": len(text) // 4, "created_at": at, "episode_id": episode["_id"], "seed": True}
        await db.messages.insert_one(doc)
        episode = await episodes.add_message(db, episode, mid, role, at, emb)
        msgs.append(ExtractionMessage(ref=f"M{i + 1}", id=mid, role=role, content=text, created_at=at))
    result = ExtractionResult.model_validate({
        "operations": [
            {"action": "CREATE", "type": "interest", "key": "interest_nlp", "content": "Is learning NLP",
             "confidence": 0.9, "importance": 0.6, "evidence_refs": ["M1"], "entities": [{"name": "NLP", "kind": "topic"}],
             "reason": "Sample data: stated interest"},
            {"action": "CREATE", "type": "goal", "key": "goal_ai_agents", "content": "Wants to build AI agents",
             "confidence": 0.9, "importance": 0.8, "evidence_refs": ["M1"], "entities": [{"name": "AI Agents", "kind": "goal"}],
             "reason": "Sample data: stated goal"},
            {"action": "CREATE", "type": "learning_difficulty", "key": "difficulty_recursion",
             "content": "Struggles with recursion (the call stack is confusing)", "confidence": 0.9, "importance": 0.7,
             "evidence_refs": ["M3"], "entities": [{"name": "Recursion", "kind": "difficulty"}],
             "reason": "Sample data: stated difficulty"},
        ],
        "relationships": [
            {"source": "NLP", "relation": "related_to", "target": "Machine Learning"},
            {"source": "AI Agents", "relation": "builds_on", "target": "NLP"},
        ],
        "reasoning_summary": "Seeded sample memories for the demo account.",
    })
    inp = ExtractionInput(messages=msgs, existing=[], conversation_id=conv_id, now_iso=start.isoformat())
    await apply_extraction(db, user=user, workspace_id=ws, result=result, inp=inp, now=start, embedder=embedder)
    await db.memories.update_many({"user_id": user["_id"]}, {"$set": {"seed": True}})

    class _Offline:
        is_offline = True

    await episodes.close_episode(db, episode["_id"], start + dt.timedelta(minutes=5), _Offline(), embedder)
