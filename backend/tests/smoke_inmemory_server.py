"""SMOKE-TEST ONLY: boots the real FastAPI app (full lifespan) against an in-memory mongomock database,
so startup can be verified on machines without MongoDB. Data is NOT persisted and $vectorSearch is
NOT available - always run the real app against MongoDB Atlas (see README)."""
import os
import sys

os.environ.setdefault("VECTOR_BACKEND", "local")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import mongomock_motor  # noqa: E402
import uvicorn  # noqa: E402

from app.database import mongo  # noqa: E402


class _Client(mongomock_motor.AsyncMongoMockClient):
    def __init__(self, *_a, **_k):
        super().__init__(tz_aware=True)

    @property
    def admin(self):
        class _Admin:
            async def command(self, *_a, **_k):
                return {"ok": 1}
        return _Admin()

    async def close(self):
        return None


mongo.AsyncMongoClient = _Client

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
