from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import check_workspace, current_scope, user_from_token
from app.core.utils import as_utc
from app.database.mongo import get_db

router = APIRouter(prefix="/api/activity", tags=["activity"])


def public_event(e: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in e.items() if k != "_id"}
    out["id"] = e["_id"]
    return out


@router.get("")
async def list_activity(scope=Depends(current_scope), limit: int = Query(default=100, le=500),
                        action: str | None = None) -> list[dict[str, Any]]:
    user, ws = scope
    query: dict[str, Any] = {"user_id": user["_id"], "workspace_id": ws}
    if action:
        query["action"] = action
    docs = await get_db().memory_events.find(query).sort("created_at", -1).to_list(limit)
    return [public_event(d) for d in docs]


async def _stream(request: Request, user_id: str, ws: str) -> AsyncIterator[str]:
    """Server-sent events. Uses a MongoDB change stream when available (replica set / Atlas),
    otherwise falls back to polling the memory_events collection."""
    db = get_db()
    use_cs = bool(getattr(request.app.state, "change_streams", False))
    yield f"event: ready\ndata: {json.dumps({'mode': 'change_stream' if use_cs else 'polling'})}\n\n"
    if use_cs:
        try:
            pipeline = [{"$match": {"operationType": "insert", "fullDocument.user_id": user_id,
                                    "fullDocument.workspace_id": ws}}]
            stream = await db.memory_events.watch(pipeline, max_await_time_ms=2000)
            async with stream:
                while not await request.is_disconnected():
                    change = await stream.try_next()
                    if change:
                        yield f"data: {json.dumps(public_event(change['fullDocument']), default=str)}\n\n"
                    else:
                        yield ": keep-alive\n\n"
            return
        except Exception:  # noqa: BLE001 - degrade to polling
            pass
    latest = await db.memory_events.find_one({"user_id": user_id, "workspace_id": ws}, sort=[("created_at", -1)])
    since = as_utc(latest["created_at"]) if latest else None
    seen: set[str] = set()
    while not await request.is_disconnected():
        query: dict[str, Any] = {"user_id": user_id, "workspace_id": ws}
        if since:
            query["created_at"] = {"$gte": since}
        for e in await db.memory_events.find(query).sort("created_at", 1).to_list(100):
            if e["_id"] in seen:
                continue
            seen.add(e["_id"])
            since = as_utc(e["created_at"])
            yield f"data: {json.dumps(public_event(e), default=str)}\n\n"
        yield ": keep-alive\n\n"
        await asyncio.sleep(2)


@router.get("/stream")
async def stream(request: Request, token: str = Query(...), workspace: str = Query(default="default")):
    user = await user_from_token(token)  # EventSource cannot send headers, so the token is a query param
    ws = check_workspace(user, workspace)
    return StreamingResponse(_stream(request, user["_id"], ws), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
