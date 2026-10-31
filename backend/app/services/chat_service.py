"""Chat orchestration: store message -> build working memory -> answer -> schedule memory jobs."""
from __future__ import annotations

import datetime as dt
from typing import Any

from app.agents.main_agent import generate_reply
from app.agents.memory_extractor import should_extract
from app.core.clock import now_for
from app.core.config import get_settings
from app.core.utils import estimate_tokens, new_id, truncate
from app.llm.embeddings import get_embedder
from app.llm.providers import get_llm
from app.memory import episodes, lifecycle
from app.memory.working_memory import build_turn_context
from app.workers import tasks
from app.workers.jobs import runner


def public_message(doc: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in doc.items() if k not in ("embedding",)}
    out["id"] = out.pop("_id")
    return out


async def store_message(db: Any, *, user: dict[str, Any], workspace_id: str, conversation_id: str, role: str,
                        content: str, now: dt.datetime, embedding: list[float] | None = None,
                        extra: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_settings()
    tokens = estimate_tokens(content)
    doc = {
        "_id": new_id("msg"), "user_id": user["_id"], "workspace_id": workspace_id, "conversation_id": conversation_id,
        "role": role, "content": content, "tokens": tokens, "created_at": now, "episode_id": None, **(extra or {}),
    }
    if embedding:
        doc["embedding"] = embedding
    if settings.message_retention_days > 0:
        doc["expires_at"] = now + dt.timedelta(days=settings.message_retention_days)
    await db.messages.insert_one(doc)
    await db.conversations.update_one(
        {"_id": conversation_id},
        {"$inc": {"total_tokens": tokens, "message_count": 1}, "$set": {"updated_at": now}},
    )
    return doc


async def send_message(db: Any, *, user: dict[str, Any], workspace_id: str, conversation: dict[str, Any],
                       content: str) -> dict[str, Any]:
    settings = get_settings()
    now = now_for(user)
    await lifecycle.expire_due(db, user, now)
    user = await db.users.find_one({"_id": user["_id"]})  # fresh memory_version after expiry

    embedder = get_embedder()
    embedding = await embedder.embed_one(content, "query")
    user_msg = await store_message(db, user=user, workspace_id=workspace_id, conversation_id=conversation["_id"],
                                   role="user", content=content, now=now, embedding=embedding)
    if not conversation.get("message_count"):
        await db.conversations.update_one({"_id": conversation["_id"]}, {"$set": {"title": truncate(content, 60)}})
    conversation = await db.conversations.find_one({"_id": conversation["_id"]})

    ctx = await build_turn_context(db, user=user, workspace_id=workspace_id, conversation=conversation,
                                   user_message=user_msg, now=now)
    llm = get_llm()
    reply = await generate_reply(llm, ctx, content)

    context_summary = {
        "memories_used": ctx.used, "overridden": ctx.overridden, "episode": ctx.episode, "tokens": ctx.tokens,
        "evidence": ctx.evidence, "evidence_reason": ctx.evidence_reason, "retrieval_backend": ctx.retrieval_backend,
        "offline_model": llm.is_offline, "trivial": ctx.trivial, "boundary": ctx.boundary,
    }
    assistant_msg = await store_message(db, user=user, workspace_id=workspace_id, conversation_id=conversation["_id"],
                                        role="assistant", content=reply, now=now,
                                        extra={"episode_id": ctx.episode["id"], "context": context_summary})
    episode = await db.episodes.find_one({"_id": ctx.episode["id"]})
    if episode:
        await episodes.add_message(db, episode, assistant_msg["_id"], "assistant", now)
    await lifecycle.reinforce_used(db, user, ctx.used_docs, now, workspace_id, content)

    # ---- Background memory work (the user does not wait for any of this) ------------------
    session = await db.sessions.find_one({"_id": conversation["_id"]}) or {}
    pending = list(session.get("pending_extraction", [])) + [user_msg["_id"]]
    scheduled = False
    if not ctx.trivial and (should_extract(content) or len(pending) >= settings.extraction_batch_size):
        uid, cid = user["_id"], conversation["_id"]
        runner.submit(uid, "extract", lambda ids=list(pending): tasks.extraction_task(uid, workspace_id, cid, ids),
                      on_failure=lambda exc: tasks.extraction_failed(uid, workspace_id, exc))
        pending = []
        scheduled = True
    elif ctx.trivial:
        pending = list(session.get("pending_extraction", []))
    await db.sessions.update_one({"_id": conversation["_id"]}, {"$set": {"pending_extraction": pending}})
    if ctx.closed_episode_id:
        uid, eid = user["_id"], ctx.closed_episode_id
        runner.submit(uid, "close_episode", lambda: tasks.close_episode_task(uid, eid))
    if episode and int(episode.get("turns", 0)) > settings.recent_turn_window // 2:
        eid = episode["_id"]
        runner.submit(user["_id"], "rolling_summary", lambda: tasks.rolling_summary_task(eid))

    context_summary["extraction_scheduled"] = scheduled
    await db.messages.update_one({"_id": assistant_msg["_id"]}, {"$set": {"context.extraction_scheduled": scheduled}})
    assistant_msg["context"] = context_summary
    return {"user_message": public_message(user_msg), "assistant_message": public_message(assistant_msg),
            "context": context_summary}
