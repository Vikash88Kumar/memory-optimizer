from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import current_scope
from app.core.clock import now_for
from app.core.utils import new_id
from app.database.mongo import get_db
from app.llm.providers import LLMError
from app.services.chat_service import public_message, send_message

router = APIRouter(prefix="/api/conversations", tags=["chat"])


class NewConversation(BaseModel):
    title: str | None = Field(default=None, max_length=80)


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


def public_conversation(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    out["id"] = out.pop("_id")
    return out


async def _owned(conversation_id: str, user: dict[str, Any], ws: str) -> dict[str, Any]:
    conv = await get_db().conversations.find_one({"_id": conversation_id, "user_id": user["_id"], "workspace_id": ws})
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


@router.get("")
async def list_conversations(scope=Depends(current_scope)) -> list[dict[str, Any]]:
    user, ws = scope
    docs = await get_db().conversations.find({"user_id": user["_id"], "workspace_id": ws}).sort("updated_at", -1).to_list(200)
    return [public_conversation(d) for d in docs]


@router.post("")
async def create_conversation(body: NewConversation, scope=Depends(current_scope)) -> dict[str, Any]:
    user, ws = scope
    now = now_for(user)
    doc = {"_id": new_id("conv"), "user_id": user["_id"], "workspace_id": ws, "title": body.title or "New conversation",
           "created_at": now, "updated_at": now, "total_tokens": 0, "message_count": 0}
    await get_db().conversations.insert_one(doc)
    return public_conversation(doc)


@router.get("/{conversation_id}/messages")
async def list_messages(conversation_id: str, scope=Depends(current_scope)) -> list[dict[str, Any]]:
    user, ws = scope
    await _owned(conversation_id, user, ws)
    docs = await get_db().messages.find({"conversation_id": conversation_id, "user_id": user["_id"]}).sort("created_at", 1).to_list(1000)
    return [public_message(d) for d in docs]


@router.post("/{conversation_id}/messages")
async def post_message(conversation_id: str, body: NewMessage, scope=Depends(current_scope)) -> dict[str, Any]:
    user, ws = scope
    conv = await _owned(conversation_id, user, ws)
    try:
        return await send_message(get_db(), user=user, workspace_id=ws, conversation=conv, content=body.content.strip())
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"The language model request failed: {exc}") from exc


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, scope=Depends(current_scope)) -> dict[str, Any]:
    """Deletes the conversation, its messages, episodes and working-memory session. Memories extracted
    from it remain (they are independent documents); their evidence pointers then resolve as missing."""
    user, ws = scope
    await _owned(conversation_id, user, ws)
    db = get_db()
    deleted = await db.messages.delete_many({"conversation_id": conversation_id, "user_id": user["_id"]})
    await db.episodes.delete_many({"conversation_id": conversation_id, "user_id": user["_id"]})
    await db.sessions.delete_many({"_id": conversation_id, "user_id": user["_id"]})
    await db.context_logs.delete_many({"conversation_id": conversation_id, "user_id": user["_id"]})
    await db.conversations.delete_one({"_id": conversation_id, "user_id": user["_id"]})
    return {"deleted": True, "messages_deleted": deleted.deleted_count}
