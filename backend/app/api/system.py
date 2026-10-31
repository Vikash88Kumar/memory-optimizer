from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import current_scope
from app.core.clock import now_for
from app.core.config import get_settings
from app.database.mongo import get_db
from app.llm.embeddings import get_embedder
from app.llm.providers import get_llm
from app.memory.retrieval import backend_label
from app.workers.jobs import runner

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/system/status")
async def system_status(request: Request, scope=Depends(current_scope)) -> dict[str, Any]:
    user, _ = scope
    s = get_settings()
    llm, emb = get_llm(), get_embedder()
    return {
        "llm_provider": llm.name, "llm_offline": llm.is_offline, "chat_model": None if llm.is_offline else s.chat_model,
        "embedding_provider": emb.name, "embedding_offline": emb.is_offline, "embedding_dimensions": emb.dims,
        "retrieval_backend": backend_label(), "change_streams": bool(getattr(request.app.state, "change_streams", False)),
        "vector_index_status": getattr(request.app.state, "vector_index_status", "unknown"),
        "demo_tools": s.enable_demo_tools, "user_clock": now_for(user), "pending_jobs": runner.pending(user["_id"]),
    }


@router.get("/system/jobs")
async def jobs(scope=Depends(current_scope)) -> dict[str, int]:
    user, _ = scope
    return {"pending": runner.pending(user["_id"])}


@router.get("/context-logs")
async def context_logs(conversation_id: str = Query(...), scope=Depends(current_scope)) -> list[dict[str, Any]]:
    user, ws = scope
    docs = await get_db().context_logs.find({"user_id": user["_id"], "workspace_id": ws,
                                             "conversation_id": conversation_id}).sort("created_at", 1).to_list(500)
    return [{**{k: v for k, v in d.items() if k != "_id"}, "id": d["_id"]} for d in docs]
