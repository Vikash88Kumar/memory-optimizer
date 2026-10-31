"""Index definitions. Regular + TTL indexes are created automatically at startup / by setup_db.py.
Vector Search indexes are created by setup_db.py (or manually in the Atlas UI from atlas_vector_indexes.json)."""
from __future__ import annotations

from typing import Any

from pymongo.errors import CollectionInvalid, OperationFailure
from pymongo.operations import SearchIndexModel

from app.core.config import Settings
from app.core.logging import log

COLLECTIONS = [
    "users", "conversations", "messages", "memories", "entities", "relationships",
    "memory_events", "episodes", "sessions", "context_logs", "tombstones",
]


def regular_indexes(settings: Settings) -> dict[str, list[tuple[list[tuple[str, int]], dict[str, Any]]]]:
    return {
        "users": [([("username", 1)], {"unique": True})],
        "conversations": [([("user_id", 1), ("workspace_id", 1), ("updated_at", -1)], {})],
        "messages": [
            ([("conversation_id", 1), ("created_at", 1)], {}),
            ([("user_id", 1), ("created_at", -1)], {}),
            ([("episode_id", 1)], {}),
            # Only messages that received an expires_at (MESSAGE_RETENTION_DAYS > 0) are purged.
            ([("expires_at", 1)], {"expireAfterSeconds": 0, "name": "messages_retention_ttl"}),
        ],
        "memories": [
            ([("user_id", 1), ("workspace_id", 1), ("status", 1), ("type", 1)], {}),
            ([("user_id", 1), ("workspace_id", 1), ("key", 1), ("scope", 1), ("status", 1)], {}),
            ([("user_id", 1), ("workspace_id", 1), ("created_at", -1)], {}),
            ([("evidence_message_ids", 1)], {}),
            ([("source.conversation_id", 1)], {}),
            # TTL: temporary memories are physically removed ttl_grace_seconds after expires_at.
            # Retrieval independently excludes anything with expires_at <= now (TTL is asynchronous).
            ([("expires_at", 1)], {"expireAfterSeconds": settings.ttl_grace_seconds, "name": "memories_expiry_ttl"}),
        ],
        "entities": [
            ([("user_id", 1), ("workspace_id", 1), ("norm", 1)], {"unique": True}),
            ([("memory_ids", 1)], {}),
        ],
        "relationships": [
            ([("user_id", 1), ("workspace_id", 1), ("source_id", 1), ("relation", 1), ("target_id", 1)], {"unique": True}),
            ([("memory_ids", 1)], {}),
        ],
        "memory_events": [([("user_id", 1), ("workspace_id", 1), ("created_at", -1)], {}), ([("memory_id", 1)], {})],
        "episodes": [
            ([("conversation_id", 1), ("status", 1)], {}),
            ([("user_id", 1), ("workspace_id", 1), ("status", 1)], {}),
            ([("message_ids", 1)], {}),
            ([("expires_at", 1)], {"expireAfterSeconds": 0, "name": "episodes_retention_ttl"}),
        ],
        "sessions": [([("user_id", 1)], {})],
        "context_logs": [([("conversation_id", 1), ("created_at", 1)], {}), ([("user_id", 1), ("created_at", -1)], {})],
        "tombstones": [([("user_id", 1), ("workspace_id", 1), ("type", 1)], {})],
    }


def vector_index_definitions(settings: Settings) -> dict[str, dict[str, Any]]:
    dims = settings.embedding_dimensions
    return {
        "memories": {
            "name": settings.memory_vector_index,
            "definition": {
                "fields": [
                    {"type": "vector", "path": "embedding", "numDimensions": dims, "similarity": "cosine"},
                    {"type": "filter", "path": "user_id"},
                    {"type": "filter", "path": "workspace_id"},
                    {"type": "filter", "path": "status"},
                    {"type": "filter", "path": "type"},
                ]
            },
        },
        "episodes": {
            "name": settings.episode_vector_index,
            "definition": {
                "fields": [
                    {"type": "vector", "path": "embedding", "numDimensions": dims, "similarity": "cosine"},
                    {"type": "filter", "path": "user_id"},
                    {"type": "filter", "path": "workspace_id"},
                    {"type": "filter", "path": "status"},
                ]
            },
        },
    }


async def ensure_collections(db: Any) -> None:
    existing = set(await db.list_collection_names())
    for name in COLLECTIONS:
        if name not in existing:
            try:
                await db.create_collection(name)
            except CollectionInvalid:
                pass


async def ensure_regular_indexes(db: Any, settings: Settings) -> None:
    for collection, specs in regular_indexes(settings).items():
        for keys, options in specs:
            try:
                await db[collection].create_index(keys, **options)
            except OperationFailure as exc:  # e.g. option conflict with an older index
                log.warning("Index on %s not created: %s", collection, exc.code)


async def ensure_vector_indexes(db: Any, settings: Settings) -> list[str]:
    """Create Vector Search indexes if missing. Requires Atlas (or mongodb-atlas-local)."""
    created: list[str] = []
    for collection, spec in vector_index_definitions(settings).items():
        cursor = await db[collection].list_search_indexes()
        names = {idx.get("name") async for idx in cursor}
        if spec["name"] in names:
            continue
        model = SearchIndexModel(definition=spec["definition"], name=spec["name"], type="vectorSearch")
        await db[collection].create_search_index(model)
        created.append(f"{collection}.{spec['name']}")
    return created


async def change_streams_available(db: Any) -> bool:
    """Change streams need a replica set (Atlas and atlas-local qualify; a standalone mongod does not)."""
    try:
        stream = db.memory_events.watch(max_await_time_ms=10)
        if hasattr(stream, "__await__"):
            stream = await stream
        await stream.close()
        return True
    except Exception:  # noqa: BLE001 - any failure means "not available"
        return False
