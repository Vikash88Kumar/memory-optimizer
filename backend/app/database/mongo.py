"""MongoDB connection management (PyMongo's native async API; Motor is deprecated)."""
from __future__ import annotations

from typing import Any

import certifi
from pymongo import AsyncMongoClient

from app.core.config import Settings
from app.core.logging import log

_client: AsyncMongoClient | None = None
_db: Any = None


def set_db(db: Any) -> None:
    """Inject a database handle (used by tests with an in-memory mock)."""
    global _db
    _db = db


def get_db() -> Any:
    if _db is None:
        raise RuntimeError("Database is not initialised")
    return _db


async def connect(settings: Settings) -> Any:
    global _client, _db
    kwargs: dict[str, Any] = {"tz_aware": True, "appname": "memora"}
    if "mongodb+srv://" in settings.mongodb_uri or "tls=true" in settings.mongodb_uri.lower():
        kwargs["tlsCAFile"] = certifi.where()
    _client = AsyncMongoClient(settings.mongodb_uri, **kwargs)
    await _client.admin.command("ping")
    _db = _client[settings.mongodb_db]
    log.info("Connected to MongoDB database=%s", settings.mongodb_db)
    return _db


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
