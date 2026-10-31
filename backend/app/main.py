"""MEMORA FastAPI application."""
from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import activity, auth, conversations, demo, graph, memories, system
from app.core.clock import now_for
from app.core.config import get_settings
from app.core.logging import configure_logging, log
from app.database import mongo
from app.database.indexes import (change_streams_available, ensure_collections, ensure_regular_indexes,
                                  ensure_vector_indexes)
from app.demo.seed import ensure_demo_user
from app.llm.embeddings import get_embedder
from app.memory.lifecycle import expire_due


async def _expiry_sweeper(app: FastAPI) -> None:
    """Marks temporary memories as expired (with an activity event) using each user's clock."""
    while True:
        await asyncio.sleep(60)
        try:
            db = mongo.get_db()
            user_ids = await db.memories.distinct("user_id", {"status": "active", "expires_at": {"$ne": None}})
            for uid in user_ids:
                user = await db.users.find_one({"_id": uid})
                if user:
                    await expire_due(db, user, now_for(user))
        except Exception:  # noqa: BLE001
            log.exception("Expiry sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    db = await mongo.connect(settings)
    await ensure_collections(db)
    await ensure_regular_indexes(db, settings)
    app.state.vector_index_status = "not_used (local fallback)"
    if settings.vector_backend == "mongodb":
        try:
            created = await ensure_vector_indexes(db, settings)
            app.state.vector_index_status = f"ready (created: {', '.join(created)})" if created else "ready"
        except Exception as exc:  # noqa: BLE001
            app.state.vector_index_status = f"unavailable: {type(exc).__name__}"
            log.warning("Vector Search indexes could not be created automatically (%s). "
                        "Create them manually - see docs/ARCHITECTURE.md", type(exc).__name__)
    app.state.change_streams = await change_streams_available(db)
    if settings.enable_demo_tools:
        await ensure_demo_user(db, get_embedder())
    sweeper = asyncio.create_task(_expiry_sweeper(app))
    try:
        yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        await mongo.close()


def create_app(use_lifespan: bool = True) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="MEMORA API", version="1.0.0", lifespan=lifespan if use_lifespan else None)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    for module in (auth, conversations, memories, graph, activity, system, demo):
        app.include_router(module.router)
    return app


app = create_app()
