"""Background tasks scheduled by the chat service."""
from __future__ import annotations

from app.agents.memory_consolidator import apply_extraction
from app.agents.memory_extractor import build_extraction_input, run_extractor
from app.core.clock import now_for
from app.core.config import get_settings
from app.database.mongo import get_db
from app.llm.embeddings import get_embedder
from app.llm.providers import get_llm
from app.memory import episodes
from app.memory.events import log_event


async def extraction_task(user_id: str, workspace_id: str, conversation_id: str, message_ids: list[str]) -> None:
    db = get_db()
    user = await db.users.find_one({"_id": user_id})
    if not user:
        return
    now = now_for(user)
    embedder = get_embedder()
    inp = await build_extraction_input(db, user_id=user_id, workspace_id=workspace_id, conversation_id=conversation_id,
                                       message_ids=message_ids, now=now, embedder=embedder)
    result = await run_extractor(inp, get_llm())
    await apply_extraction(db, user=user, workspace_id=workspace_id, result=result, inp=inp, now=now, embedder=embedder)


async def extraction_failed(user_id: str, workspace_id: str, exc: Exception) -> None:
    db = get_db()
    user = await db.users.find_one({"_id": user_id})
    await log_event(db, user_id=user_id, workspace_id=workspace_id, action="extraction_failed",
                    now=now_for(user or {}), reason=f"Memory extraction failed after retries ({type(exc).__name__})")


async def close_episode_task(user_id: str, episode_id: str) -> None:
    db = get_db()
    user = await db.users.find_one({"_id": user_id})
    await episodes.close_episode(db, episode_id, now_for(user or {}), get_llm(), get_embedder())


async def rolling_summary_task(episode_id: str) -> None:
    await episodes.update_rolling_summary(get_db(), episode_id, get_llm(), get_settings().recent_turn_window)
