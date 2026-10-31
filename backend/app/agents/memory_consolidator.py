"""Applies validated extraction operations to MongoDB: maps refs to real ids, deduplicates,
resolves conflicts by scope and specificity, and keeps the knowledge graph in sync."""
from __future__ import annotations

import datetime as dt
from typing import Any

from app.core.config import get_settings
from app.core.utils import as_utc, cosine, jaccard, normalized_similarity, term_set, truncate
from app.llm.embeddings import Embedder
from app.memory import graph, lifecycle
from app.models.extraction import ExtractionInput, ExtractionResult


async def find_forget_targets(db: Any, *, user_id: str, workspace_id: str, description: str,
                              embedder: Embedder) -> list[dict[str, Any]]:
    settings = get_settings()
    qvec = await embedder.embed_one(description, "query")
    terms = term_set(description)
    active = await db.memories.find({"user_id": user_id, "workspace_id": workspace_id, "status": "active"}).to_list(1000)
    scored = []
    for mem in active:
        sim = normalized_similarity(cosine(qvec, mem.get("embedding")))
        lexical = 0.5 + 0.5 * jaccard(terms, term_set(mem["content"]))
        score = max(sim, lexical)
        if score >= settings.forget_match_threshold:
            scored.append((score, mem))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:1]]


async def apply_extraction(db: Any, *, user: dict[str, Any], workspace_id: str, result: ExtractionResult,
                           inp: ExtractionInput, now: dt.datetime, embedder: Embedder) -> list[dict[str, Any]]:
    uid = user["_id"]
    msg_by_ref = {m.ref: m for m in inp.messages}
    mem_by_ref = {e["ref"]: e["_id"] for e in inp.existing}
    last_user = next((m for m in reversed(inp.messages) if m.role == "user"), None)
    applied: list[dict[str, Any]] = []
    touched_ids: list[str] = []

    async def load_targets(refs: list[str]) -> list[dict[str, Any]]:
        ids = [mem_by_ref[r] for r in refs if r in mem_by_ref]  # unknown refs are ignored, never trusted
        if not ids:
            return []
        docs = await db.memories.find({"_id": {"$in": ids}, "user_id": uid, "workspace_id": workspace_id,
                                       "status": "active"}).to_list(len(ids))
        return docs

    for op in result.operations:
        if op.action == "NOOP":
            continue
        evidence = [msg_by_ref[r] for r in op.evidence_refs if r in msg_by_ref]
        if not evidence and last_user:
            evidence = [last_user]
        origin = op.origin
        if origin == "explicit" and not any(m.role == "user" for m in evidence):
            origin = "inferred"  # only the user's own words can make a memory explicit
        evidence_ids = [m.id for m in evidence]
        newest = max((as_utc(m.created_at) for m in evidence if m.created_at), default=None)
        targets = await load_targets(op.target_refs)

        if op.action in ("CREATE", "SUPERSEDE", "REQUEST_CONFIRMATION"):
            expires_at = now + dt.timedelta(days=op.expires_in_days) if op.temporary and op.expires_in_days else None
            res = await lifecycle.remember(
                db, user=user, workspace_id=workspace_id, mtype=op.type, key=op.key, content=op.content,
                scope=op.scope, confidence=op.confidence, importance=op.importance, origin=origin,
                temporary=op.temporary, expires_at=expires_at, evidence_ids=evidence_ids,
                conversation_id=inp.conversation_id, entities=[e.model_dump() for e in op.entities],
                requires_confirmation=op.requires_confirmation or op.action == "REQUEST_CONFIRMATION",
                now=now, embedder=embedder, reason=op.reason or "Extracted from conversation",
                newest_evidence_at=newest, force_supersede=targets if op.action == "SUPERSEDE" else None,
            )
            applied.append({"action": res.action, "memory_id": res.memory["_id"] if res.memory else None,
                            "superseded": res.superseded, "reason": res.reason})
            if res.memory:
                touched_ids.append(res.memory["_id"])
        elif op.action == "UPDATE" and targets:
            updated = await lifecycle.update_memory(
                db, user=user, memory=targets[0], content=op.content, now=now, embedder=embedder,
                reason=op.reason or "Updated with new information", evidence_ids=evidence_ids,
                fields={"confidence": max(op.confidence, float(targets[0].get("confidence", 0)))},
            )
            applied.append({"action": "updated", "memory_id": updated["_id"]})
            touched_ids.append(updated["_id"])
        elif op.action == "MERGE" and len(targets) >= 2:
            merged = await lifecycle.merge_memories(db, user=user, keep=targets[0], others=targets[1:], now=now,
                                                    reason=op.reason or "Duplicate memories merged")
            applied.append({"action": "merged", "memory_id": merged["_id"]})
        elif op.action == "DELETE":
            if not targets and op.content:
                targets = await find_forget_targets(db, user_id=uid, workspace_id=workspace_id,
                                                    description=op.content, embedder=embedder)
            forgotten: list[str] = []
            for target in targets:
                forgotten += await lifecycle.forget_memory(
                    db, user=user, memory=target, now=now,
                    reason=f"User asked to forget: \u201c{truncate(op.content or 'this memory', 60)}\u201d",
                )
            applied.append({"action": "deleted" if forgotten else "delete_not_found", "memory_ids": forgotten})

    if result.relationships and touched_ids:
        await graph.link_relationships(db, uid, workspace_id, [r.model_dump() for r in result.relationships],
                                       touched_ids, now)
    return applied
