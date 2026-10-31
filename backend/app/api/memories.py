from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import current_scope
from app.core.clock import now_for
from app.database.mongo import get_db
from app.llm.embeddings import get_embedder
from app.memory import lifecycle
from app.memory.evidence import resolve_evidence
from app.models.extraction import MemoryType, canonical_scope

router = APIRouter(prefix="/api/memories", tags=["memories"])


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, min_length=3, max_length=300)
    type: MemoryType | None = None
    importance: float | None = Field(default=None, ge=0, le=1)
    scope: str | None = Field(default=None, max_length=60)


class Confirmation(BaseModel):
    accept: bool


async def _owned(memory_id: str, user: dict[str, Any], ws: str) -> dict[str, Any]:
    mem = await get_db().memories.find_one({"_id": memory_id, "user_id": user["_id"], "workspace_id": ws})
    if not mem:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memory not found")
    return mem


@router.get("")
async def list_memories(scope=Depends(current_scope), q: str | None = Query(default=None, max_length=100),
                        type: str | None = None,
                        status_filter: Literal["active", "superseded", "expired", "deleted", "rejected", "all"] = Query(default="active", alias="status"),
                        confirmation: str | None = None) -> list[dict[str, Any]]:
    user, ws = scope
    db = get_db()
    now = now_for(user)
    await lifecycle.expire_due(db, user, now)
    query: dict[str, Any] = {"user_id": user["_id"], "workspace_id": ws}
    if status_filter != "all":
        query["status"] = status_filter
    if type:
        query["type"] = type
    if confirmation:
        query["confirmation"] = confirmation
    if q:
        query["content"] = {"$regex": re.escape(q), "$options": "i"}
    docs = await db.memories.find(query).sort("updated_at", -1).to_list(500)
    return [lifecycle.public_memory(d, now) for d in docs]


@router.get("/{memory_id}")
async def get_memory(memory_id: str, scope=Depends(current_scope)) -> dict[str, Any]:
    user, ws = scope
    return lifecycle.public_memory(await _owned(memory_id, user, ws), now_for(user))


@router.patch("/{memory_id}")
async def edit_memory(memory_id: str, body: MemoryPatch, scope=Depends(current_scope)) -> dict[str, Any]:
    user, ws = scope
    mem = await _owned(memory_id, user, ws)
    if mem["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only active memories can be edited")
    fields: dict[str, Any] = {}
    if body.type:
        fields["type"] = body.type
    if body.importance is not None:
        fields["importance"] = body.importance
    if body.scope is not None:
        fields["scope"] = canonical_scope(body.scope)
    try:
        updated = await lifecycle.update_memory(get_db(), user=user, memory=mem, content=body.content, now=now_for(user),
                                                embedder=get_embedder(), reason="Edited by the user", fields=fields, actor="user")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return lifecycle.public_memory(updated, now_for(user))


@router.post("/{memory_id}/confirm")
async def confirm_memory(memory_id: str, body: Confirmation, scope=Depends(current_scope)) -> dict[str, Any]:
    user, ws = scope
    mem = await _owned(memory_id, user, ws)
    if mem["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only active memories can be confirmed or rejected")
    updated = await lifecycle.set_confirmation(get_db(), user=user, memory=mem, accept=body.accept, now=now_for(user))
    return lifecycle.public_memory(updated, now_for(user))


@router.delete("/{memory_id}")
async def forget(memory_id: str, scope=Depends(current_scope)) -> dict[str, Any]:
    user, ws = scope
    mem = await _owned(memory_id, user, ws)
    if mem["status"] == "deleted":
        return {"forgotten": [], "message": "Already forgotten"}
    ids = await lifecycle.forget_memory(get_db(), user=user, memory=mem, now=now_for(user),
                                        reason="User deleted this memory from the Memory Explorer")
    return {"forgotten": ids, "message": f"Forgotten {len(ids)} memory(ies); graph links and evidence removed"}


@router.get("/{memory_id}/evidence")
async def evidence(memory_id: str, scope=Depends(current_scope)) -> dict[str, Any]:
    user, ws = scope
    mem = await _owned(memory_id, user, ws)
    items = await resolve_evidence(get_db(), user["_id"], mem.get("evidence_message_ids", []), limit=10)
    return {"memory_id": memory_id, "conversation_id": (mem.get("source") or {}).get("conversation_id"), "evidence": items}


@router.get("/{memory_id}/history")
async def history(memory_id: str, scope=Depends(current_scope)) -> dict[str, Any]:
    user, ws = scope
    mem = await _owned(memory_id, user, ws)
    db = get_db()
    chain = []
    for key in ("supersedes",):
        for mid in mem.get(key, []) or []:
            old = await db.memories.find_one({"_id": mid, "user_id": user["_id"]})
            if old:
                chain.append({"id": old["_id"], "content": old["content"], "status": old["status"], "relation": "replaced"})
    if mem.get("superseded_by"):
        newer = await db.memories.find_one({"_id": mem["superseded_by"], "user_id": user["_id"]})
        if newer:
            chain.append({"id": newer["_id"], "content": newer["content"], "status": newer["status"], "relation": "replaced_by"})
    events = await db.memory_events.find({"user_id": user["_id"], "memory_ids": memory_id}).sort("created_at", -1).to_list(100)
    return {"memory_id": memory_id, "history": mem.get("history", []), "related": chain,
            "events": [{**{k: v for k, v in e.items() if k != "_id"}, "id": e["_id"]} for e in events]}
