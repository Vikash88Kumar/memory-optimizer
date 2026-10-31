"""Demo tools: a per-user clock to show decay/expiry live, and a reset for the demo account."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import current_scope
from app.core.clock import now_for
from app.core.config import get_settings
from app.database.mongo import get_db
from app.demo.seed import reset_user_data, seed_sample_data
from app.llm.embeddings import get_embedder
from app.memory import lifecycle
from app.workers.jobs import runner

router = APIRouter(prefix="/api/demo", tags=["demo"])


class ClockChange(BaseModel):
    advance_days: float | None = Field(default=None, gt=0, le=365)
    reset: bool = False


def _enabled() -> None:
    if not get_settings().enable_demo_tools:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Demo tools are disabled on this deployment")


@router.post("/clock")
async def change_clock(body: ClockChange, scope=Depends(current_scope)) -> dict[str, Any]:
    _enabled()
    user, _ = scope
    db = get_db()
    if body.reset:
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"clock_offset_seconds": 0}})
    elif body.advance_days:
        await db.users.update_one({"_id": user["_id"]}, {"$inc": {"clock_offset_seconds": body.advance_days * 86400}})
    user = await db.users.find_one({"_id": user["_id"]})
    expired = await lifecycle.expire_due(db, user, now_for(user))
    return {"clock": now_for(user), "offset_days": round(user.get("clock_offset_seconds", 0) / 86400, 3), "expired": expired}


@router.post("/reset")
async def reset_demo(scope=Depends(current_scope)) -> dict[str, Any]:
    _enabled()
    user, _ = scope
    if not user.get("is_demo"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the demo account can be reset")
    await runner.drain()
    db = get_db()
    await reset_user_data(db, user["_id"])
    await seed_sample_data(db, await db.users.find_one({"_id": user["_id"]}), get_embedder())
    return {"reset": True}
