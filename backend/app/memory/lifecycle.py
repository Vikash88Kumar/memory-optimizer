"""Memory lifecycle: CREATE, UPDATE, MERGE, SUPERSEDE, EXPIRE, DELETE (forget), CONFIRM/REJECT.
Every transition writes a memory_event with a reason."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.utils import cosine, jaccard, new_id, normalized_similarity, term_set, truncate
from app.llm.embeddings import Embedder
from app.memory import decay, graph, safety
from app.memory.events import log_event, redact_events_for_memory

PUBLIC_EXCLUDE = {"embedding"}


def public_memory(doc: dict[str, Any], now: dt.datetime | None = None) -> dict[str, Any]:
    out = {k: v for k, v in doc.items() if k not in PUBLIC_EXCLUDE}
    out["id"] = out.pop("_id")
    if now is not None:
        out["strength_now"] = round(decay.strength_at(doc, now), 4)
    return out


async def bump_memory_version(db: Any, user_id: str) -> None:
    await db.users.update_one({"_id": user_id}, {"$inc": {"memory_version": 1}})


@dataclass
class RememberResult:
    action: str  # created | merged | blocked
    memory: dict[str, Any] | None
    superseded: list[str] = field(default_factory=list)
    reason: str = ""


async def _check_tombstone(db: Any, user_id: str, ws: str, mtype: str, content: str, origin: str,
                           newest_evidence_at: dt.datetime | None) -> dict[str, Any] | None:
    """Forgotten information must not come back from old messages or inference. A fresh, explicit
    statement made after the forget request is a new decision by the user and is allowed."""
    terms = term_set(content)
    async for tomb in db.tombstones.find({"user_id": user_id, "workspace_id": ws, "type": mtype}):
        if jaccard(terms, set(tomb.get("terms", []))) < 0.5:
            continue
        created = tomb["created_at"]
        fresh = origin == "explicit" and newest_evidence_at is not None and newest_evidence_at > created
        if not fresh:
            return tomb
    return None


async def remember(db: Any, *, user: dict[str, Any], workspace_id: str, mtype: str, key: str, content: str,
                   scope: str, confidence: float, importance: float, origin: str, temporary: bool,
                   expires_at: dt.datetime | None, evidence_ids: list[str], conversation_id: str | None,
                   entities: list[dict[str, str]], requires_confirmation: bool, now: dt.datetime,
                   embedder: Embedder, reason: str, newest_evidence_at: dt.datetime | None = None,
                   force_supersede: list[dict[str, Any]] | None = None, seed: bool = False) -> RememberResult:
    settings = get_settings()
    uid = user["_id"]
    content = truncate(content, 300)

    if safety.contains_secret(content):
        await log_event(db, user_id=uid, workspace_id=workspace_id, action="blocked", now=now, memory_type=mtype,
                        reason="Not stored: looks like a password, key or other secret")
        return RememberResult("blocked", None, reason="secret")
    if safety.looks_like_injection(content):
        await log_event(db, user_id=uid, workspace_id=workspace_id, action="blocked", now=now, memory_type=mtype,
                        reason="Not stored: content looks like an instruction to the assistant (prompt injection)")
        return RememberResult("blocked", None, reason="injection")
    tomb = await _check_tombstone(db, uid, workspace_id, mtype, content, origin, newest_evidence_at)
    if tomb:
        await log_event(db, user_id=uid, workspace_id=workspace_id, action="blocked", now=now, memory_type=mtype,
                        reason="Not stored: matches information the user asked to forget")
        return RememberResult("blocked", None, reason="forgotten")

    embedding = await embedder.embed_one(content, "document")
    active = await db.memories.find(
        {"user_id": uid, "workspace_id": workspace_id, "status": "active", "type": mtype}
    ).to_list(300)

    # 1) Duplicate -> reinforce existing memory and merge evidence.
    terms = term_set(content)
    for old in active:
        sim = normalized_similarity(cosine(embedding, old.get("embedding")))
        same_slot = old.get("key") == key and old.get("scope") == scope
        if sim >= settings.duplicate_threshold or (same_slot and jaccard(terms, term_set(old["content"])) >= 0.8):
            new_conf = min(0.99, max(float(old.get("confidence", 0)), confidence) + 0.05)
            update = {
                "$set": {
                    "confidence": round(new_conf, 3),
                    "importance": max(float(old.get("importance", 0)), importance),
                    "strength": decay.reinforced(old, now),
                    "last_reinforced_at": now,
                    "updated_at": now,
                    **({"confirmation": "not_required"} if origin == "explicit" and old.get("confirmation") == "pending" else {}),
                },
                "$addToSet": {"evidence_message_ids": {"$each": evidence_ids}},
                "$inc": {"reinforce_count": 1},
                "$push": {"history": {"at": now, "action": "merged", "content": content, "reason": "Repeated information"}},
            }
            await db.memories.update_one({"_id": old["_id"]}, update)
            await log_event(db, user_id=uid, workspace_id=workspace_id, action="merged", now=now, memory_id=old["_id"],
                            memory_type=mtype, content_preview=old["content"],
                            reason=f"Repeated information merged into an existing memory (similarity {sim:.2f}); evidence added")
            await bump_memory_version(db, uid)
            return RememberResult("merged", await db.memories.find_one({"_id": old["_id"]}))

    # 2) Conflicts in the same slot (same key and same scope) are superseded. Different scopes coexist.
    to_supersede = list(force_supersede or [])
    coexist_note = None
    for old in active:
        if old.get("key") != key or any(o["_id"] == old["_id"] for o in to_supersede):
            continue
        if old.get("scope") != scope:
            coexist_note = "Different scope: both memories kept (topic-specific overrides global for that topic)"
            continue
        if temporary != bool(old.get("temporary")):
            coexist_note = "Temporary statement does not overwrite a lasting preference; both kept"
            continue
        to_supersede.append(old)

    if origin == "assistant" or requires_confirmation or (origin == "inferred" and confidence < settings.confirm_threshold):
        confirmation = "pending"
    else:
        confirmation = "not_required"

    mid = new_id("mem")
    doc = {
        "_id": mid,
        "user_id": uid,
        "workspace_id": workspace_id,
        "type": mtype,
        "key": key,
        "content": content,
        "scope": scope,
        "confidence": round(confidence, 3),
        "importance": round(importance, 3),
        "origin": origin,
        "source": {"conversation_id": conversation_id, "message_ids": evidence_ids, "origin": origin},
        "evidence_message_ids": evidence_ids,
        "status": "active",
        "confirmation": confirmation,
        "temporary": temporary,
        "expires_at": expires_at,
        "created_at": now,
        "updated_at": now,
        "last_reinforced_at": now,
        "strength": decay.initial_strength(importance),
        "decay_lambda": decay.decay_lambda(mtype, importance),
        "reinforce_count": 0,
        "retrieval_count": 0,
        "supersedes": [o["_id"] for o in to_supersede],
        "superseded_by": None,
        "entity_ids": [],
        "history": [{"at": now, "action": "created", "content": content, "reason": reason}],
        "seed": seed,
        "embedding": embedding,
    }
    await db.memories.insert_one(doc)

    for old in to_supersede:
        await db.memories.update_one(
            {"_id": old["_id"]},
            {"$set": {"status": "superseded", "superseded_by": mid, "updated_at": now},
             "$push": {"history": {"at": now, "action": "superseded", "content": old["content"],
                                   "reason": f"Replaced by: {content}"}}},
        )
        await graph.unlink_memory(db, uid, old["_id"], "supersede", now)
        await log_event(db, user_id=uid, workspace_id=workspace_id, action="superseded", now=now,
                        memory_id=old["_id"], memory_ids=[old["_id"], mid], memory_type=old["type"],
                        content_preview=old["content"],
                        reason=f"Replaced by a newer statement: \u201c{truncate(content, 80)}\u201d (kept in history)")

    await graph.link_memory(db, doc, entities, user.get("display_name") or user.get("username", "User"), now)
    action = "pending_confirmation" if confirmation == "pending" else "created"
    why = reason + (f". {coexist_note}" if coexist_note else "")
    await log_event(db, user_id=uid, workspace_id=workspace_id, action=action, now=now, memory_id=mid,
                    memory_type=mtype, content_preview=content, reason=why,
                    details={"scope": scope, "origin": origin, "temporary": temporary,
                             "expires_at": expires_at.isoformat() if expires_at else None})
    await bump_memory_version(db, uid)
    return RememberResult("created", await db.memories.find_one({"_id": mid}),
                          superseded=[o["_id"] for o in to_supersede], reason=why)


async def update_memory(db: Any, *, user: dict[str, Any], memory: dict[str, Any], content: str | None,
                        now: dt.datetime, embedder: Embedder, reason: str, evidence_ids: list[str] | None = None,
                        fields: dict[str, Any] | None = None, actor: str = "agent") -> dict[str, Any]:
    uid = user["_id"]
    set_fields: dict[str, Any] = {"updated_at": now, **(fields or {})}
    if content and content != memory["content"]:
        if safety.contains_secret(content) or safety.looks_like_injection(content):
            raise ValueError("Content rejected by safety checks")
        set_fields["content"] = truncate(content, 300)
        set_fields["embedding"] = await embedder.embed_one(content, "document")
    if "type" in set_fields or "importance" in set_fields:
        mtype = set_fields.get("type", memory["type"])
        set_fields["decay_lambda"] = decay.decay_lambda(mtype, float(set_fields.get("importance", memory.get("importance", 0.5))))
    if actor == "user":
        set_fields["confirmation"] = "confirmed"
    update: dict[str, Any] = {
        "$set": set_fields,
        "$push": {"history": {"at": now, "action": "updated", "content": memory["content"], "reason": reason}},
    }
    if evidence_ids:
        update["$addToSet"] = {"evidence_message_ids": {"$each": evidence_ids}}
    await db.memories.update_one({"_id": memory["_id"], "user_id": uid}, update)
    updated = await db.memories.find_one({"_id": memory["_id"]})
    if "content" in set_fields or "scope" in set_fields or "type" in set_fields:
        await graph.unlink_memory(db, uid, memory["_id"], "delete", now)
        await graph.link_memory(db, updated, [], user.get("display_name") or user.get("username", "User"), now)
    await log_event(db, user_id=uid, workspace_id=memory["workspace_id"], action="updated", now=now,
                    memory_id=memory["_id"], memory_type=updated["type"], content_preview=updated["content"],
                    reason=reason, details={"before": truncate(memory["content"], 120)})
    await bump_memory_version(db, uid)
    return updated


async def merge_memories(db: Any, *, user: dict[str, Any], keep: dict[str, Any], others: list[dict[str, Any]],
                         now: dt.datetime, reason: str) -> dict[str, Any]:
    uid = user["_id"]
    evidence = [e for o in others for e in o.get("evidence_message_ids", [])]
    conf = max([float(keep.get("confidence", 0))] + [float(o.get("confidence", 0)) for o in others])
    await db.memories.update_one(
        {"_id": keep["_id"]},
        {"$set": {"confidence": conf, "strength": decay.reinforced(keep, now), "last_reinforced_at": now, "updated_at": now},
         "$addToSet": {"evidence_message_ids": {"$each": evidence}},
         "$push": {"history": {"at": now, "action": "merged", "content": keep["content"], "reason": reason}}},
    )
    for other in others:
        await db.memories.update_one(
            {"_id": other["_id"]},
            {"$set": {"status": "superseded", "superseded_by": keep["_id"], "updated_at": now},
             "$push": {"history": {"at": now, "action": "merged", "content": other["content"], "reason": reason}}},
        )
        await graph.unlink_memory(db, uid, other["_id"], "delete", now)
    await log_event(db, user_id=uid, workspace_id=keep["workspace_id"], action="merged", now=now, memory_id=keep["_id"],
                    memory_ids=[keep["_id"]] + [o["_id"] for o in others], memory_type=keep["type"],
                    content_preview=keep["content"], reason=reason)
    await bump_memory_version(db, uid)
    return await db.memories.find_one({"_id": keep["_id"]})


async def forget_memory(db: Any, *, user: dict[str, Any], memory: dict[str, Any], now: dt.datetime, reason: str,
                        cascade: bool = True) -> list[str]:
    """Delete policy: the memory is tombstoned (content, embedding and history wiped), graph edges are
    removed, earlier events are redacted, supporting messages and episode summaries are redacted
    (FORGET_REDACTS_EVIDENCE) and near-duplicate active memories are forgotten too."""
    settings = get_settings()
    uid, ws = user["_id"], memory["workspace_id"]
    original_content = memory["content"]
    original_embedding = memory.get("embedding")
    evidence = list(memory.get("evidence_message_ids", []))
    await db.memories.update_one(
        {"_id": memory["_id"], "user_id": uid},
        {"$set": {"status": "deleted", "content": "[forgotten]", "key": None, "history": [], "entity_ids": [],
                  "deleted_at": now, "updated_at": now, "evidence_message_ids": [],
                  "source": {"conversation_id": None, "message_ids": [], "origin": memory.get("origin")}},
         "$unset": {"embedding": ""}},
    )
    await graph.unlink_memory(db, uid, memory["_id"], "delete", now)
    await db.tombstones.insert_one({
        "_id": new_id("tomb"), "user_id": uid, "workspace_id": ws, "type": memory["type"],
        "terms": sorted(term_set(original_content)), "memory_id": memory["_id"], "created_at": now,
    })
    await redact_events_for_memory(db, uid, memory["_id"])
    if settings.forget_redacts_evidence and evidence:
        await db.messages.update_many(
            {"_id": {"$in": evidence}, "user_id": uid},
            {"$set": {"content": "[redacted after a forget request]", "redacted": True}, "$unset": {"embedding": ""}},
        )
        await db.episodes.update_many(
            {"user_id": uid, "message_ids": {"$in": evidence}},
            {"$set": {"summary": "[summary removed after a forget request]", "rolling_summary": ""},
             "$unset": {"embedding": ""}},
        )
    await log_event(db, user_id=uid, workspace_id=ws, action="deleted", now=now, memory_id=memory["_id"],
                    memory_type=memory["type"], reason=reason,
                    details={"evidence_redacted": bool(settings.forget_redacts_evidence and evidence)})
    forgotten = [memory["_id"]]
    if cascade and original_embedding:
        others = await db.memories.find(
            {"user_id": uid, "workspace_id": ws, "status": "active", "type": memory["type"]}
        ).to_list(300)
        terms = term_set(original_content)
        for other in others:
            sim = normalized_similarity(cosine(original_embedding, other.get("embedding")))
            other_terms = term_set(other["content"])
            contained = len(terms & other_terms) / len(terms) if terms else 0.0  # forgotten info inside another memory
            if sim >= 0.90 or contained >= 0.8:
                forgotten += await forget_memory(db, user=user, memory=other, now=now, cascade=False,
                                                 reason="Forgotten together with a matching memory")
    await bump_memory_version(db, uid)
    return forgotten


async def set_confirmation(db: Any, *, user: dict[str, Any], memory: dict[str, Any], accept: bool,
                           now: dt.datetime) -> dict[str, Any]:
    uid = user["_id"]
    if accept:
        await db.memories.update_one(
            {"_id": memory["_id"], "user_id": uid},
            {"$set": {"confirmation": "confirmed", "confidence": max(0.95, float(memory.get("confidence", 0))),
                      "updated_at": now},
             "$push": {"history": {"at": now, "action": "confirmed", "content": memory["content"], "reason": "Confirmed by user"}}},
        )
        await log_event(db, user_id=uid, workspace_id=memory["workspace_id"], action="confirmed", now=now,
                        memory_id=memory["_id"], memory_type=memory["type"], content_preview=memory["content"],
                        reason="Confirmed by the user")
    else:
        await db.memories.update_one(
            {"_id": memory["_id"], "user_id": uid},
            {"$set": {"confirmation": "rejected", "status": "rejected", "updated_at": now},
             "$push": {"history": {"at": now, "action": "rejected", "content": memory["content"], "reason": "Rejected by user"}}},
        )
        await graph.unlink_memory(db, uid, memory["_id"], "delete", now)
        await log_event(db, user_id=uid, workspace_id=memory["workspace_id"], action="rejected", now=now,
                        memory_id=memory["_id"], memory_type=memory["type"], content_preview=memory["content"],
                        reason="Rejected by the user; it will not be used")
    await bump_memory_version(db, uid)
    return await db.memories.find_one({"_id": memory["_id"]})


async def expire_due(db: Any, user: dict[str, Any], now: dt.datetime) -> int:
    """Mark temporary memories past expires_at as expired (TTL removes them later, asynchronously)."""
    uid = user["_id"]
    due = await db.memories.find({"user_id": uid, "status": "active", "expires_at": {"$ne": None, "$lte": now}}).to_list(500)
    for mem in due:
        await db.memories.update_one(
            {"_id": mem["_id"]},
            {"$set": {"status": "expired", "updated_at": now},
             "$push": {"history": {"at": now, "action": "expired", "content": mem["content"], "reason": "Temporary memory reached its expiry time"}}},
        )
        await graph.unlink_memory(db, uid, mem["_id"], "delete", now)
        await log_event(db, user_id=uid, workspace_id=mem["workspace_id"], action="expired", now=now,
                        memory_id=mem["_id"], memory_type=mem["type"], content_preview=mem["content"],
                        reason="Temporary memory reached its expiry time and is no longer retrieved")
    if due:
        await bump_memory_version(db, uid)
    return len(due)


async def reinforce_used(db: Any, user: dict[str, Any], memories: list[dict[str, Any]], now: dt.datetime,
                         workspace_id: str, query_preview: str) -> None:
    if not memories:
        return
    for mem in memories:
        await db.memories.update_one(
            {"_id": mem["_id"]},
            {"$set": {"strength": decay.reinforced(mem, now), "last_reinforced_at": now, "last_retrieved_at": now},
             "$inc": {"retrieval_count": 1}},
        )
    await log_event(db, user_id=user["_id"], workspace_id=workspace_id, action="retrieved", now=now,
                    memory_ids=[m["_id"] for m in memories],
                    reason=f"{len(memories)} memories used to answer a message",
                    details={"query_preview": truncate(query_preview, 80)})
