from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import current_scope
from app.core.clock import now_for
from app.database.mongo import get_db
from app.memory import graph
from app.memory.lifecycle import public_memory

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("")
async def get_graph(include_superseded: bool = False, scope=Depends(current_scope)) -> dict[str, Any]:
    user, ws = scope
    return await graph.export_graph(get_db(), user["_id"], ws, include_superseded)


@router.get("/nodes/{node_id}")
async def node_detail(node_id: str, scope=Depends(current_scope)) -> dict[str, Any]:
    user, ws = scope
    db = get_db()
    node = await db.entities.find_one({"_id": node_id, "user_id": user["_id"], "workspace_id": ws})
    if not node:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    rels = await db.relationships.find({"user_id": user["_id"], "workspace_id": ws,
                                        "$or": [{"source_id": node_id}, {"target_id": node_id}]}).to_list(200)
    other_ids = {r["source_id"] for r in rels} | {r["target_id"] for r in rels}
    names = {e["_id"]: e["name"] for e in await db.entities.find({"_id": {"$in": list(other_ids)}}).to_list(400)}
    memory_ids = set(node.get("memory_ids", [])) | {m for r in rels for m in r.get("memory_ids", [])}
    if node["kind"] == "user":
        memory_ids = set()
    mems = await db.memories.find({"_id": {"$in": list(memory_ids)}, "user_id": user["_id"]}).to_list(100)
    now = now_for(user)
    return {
        "node": {"id": node["_id"], "label": node["name"], "kind": node["kind"], "created_at": node["created_at"]},
        "relationships": [
            {"id": r["_id"], "relation": r["relation"], "status": r.get("status", "active"),
             "direction": "out" if r["source_id"] == node_id else "in",
             "other": names.get(r["target_id"] if r["source_id"] == node_id else r["source_id"], "?"),
             "memory_ids": r.get("memory_ids", [])}
            for r in rels
        ],
        "memories": [public_memory(m, now) for m in mems],
    }
