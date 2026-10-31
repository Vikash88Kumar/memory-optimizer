import os

os.environ.update({
    "VECTOR_BACKEND": "local", "LLM_PROVIDER": "mock", "EMBEDDING_PROVIDER": "hash", "EMBEDDING_DIMENSIONS": "256",
    "AUTH_SECRET": "test-secret", "ENVIRONMENT": "test", "ENABLE_DEMO_TOOLS": "true", "ALLOW_SIGNUP": "true",
})

import uuid  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.utils import new_id, utcnow  # noqa: E402
from app.database import mongo  # noqa: E402
from app.database.indexes import ensure_regular_indexes  # noqa: E402
from app.llm.embeddings import HashEmbedder, set_embedder  # noqa: E402
from app.llm.providers import set_llm  # noqa: E402
from app.workers.jobs import runner  # noqa: E402


@pytest.fixture
async def db():
    client = AsyncMongoMockClient(tz_aware=True)
    database = client[f"t{uuid.uuid4().hex[:8]}"]
    await ensure_regular_indexes(database, get_settings())
    mongo.set_db(database)
    set_llm(None)
    set_embedder(HashEmbedder(256))
    yield database
    await runner.drain()


@pytest.fixture
def embedder():
    return HashEmbedder(256)


async def make_user(db, username="alice"):
    user = {"_id": new_id("usr"), "username": username, "display_name": username.title(), "password_hash": "x",
            "workspaces": ["default"], "memory_version": 0, "clock_offset_seconds": 0, "created_at": utcnow()}
    await db.users.insert_one(user)
    return user


@pytest.fixture
async def user(db):
    return await make_user(db)


@pytest.fixture
async def client(db):
    from app.main import create_app

    app = create_app(use_lifespan=False)
    app.state.change_streams = False
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def signup(client, username="student1", password="password123"):
    r = await client.post("/api/auth/register", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
