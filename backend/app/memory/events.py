"""Memory activity log (memory_events). Powers the Activity page and the audit trail."""
from __future__ import annotations

import datetime as dt
from typing import Any

from app.core.utils import new_id, truncate

ACTIONS = {
    "created", "updated", "merged", "superseded", "expired", "deleted", "retrieved", "confirmed",
    "rejected", "blocked", "reinforced", "extraction_failed", "episode_closed", "pending_confirmation",
}


async def log_event(db: Any, *, user_id: str, workspace_id: str, action: str, reason: str, now: dt.datetime,
                    memory_id: str | None = None, memory_ids: list[str] | None = None,
                    content_preview: str | None = None, memory_type: str | None = None,
                    details: dict[str, Any] | None = None) -> dict[str, Any]:
    assert action in ACTIONS, action
    event = {
        "_id": new_id("evt"),
        "user_id": user_id,
        "workspace_id": workspace_id,
        "action": action,
        "reason": truncate(reason, 300),
        "memory_id": memory_id,
        "memory_ids": memory_ids or ([memory_id] if memory_id else []),
        "memory_type": memory_type,
        "content_preview": truncate(content_preview, 160) if content_preview else None,
        "details": details or {},
        "created_at": now,
    }
    await db.memory_events.insert_one(event)
    return event


async def redact_events_for_memory(db: Any, user_id: str, memory_id: str) -> None:
    """After a forget request, earlier events must not keep a copy of the forgotten content."""
    await db.memory_events.update_many(
        {"user_id": user_id, "memory_ids": memory_id},
        {"$set": {"content_preview": "[forgotten]", "details": {"redacted": True}}},
    )
