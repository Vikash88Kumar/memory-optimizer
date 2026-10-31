import json

import httpx
import pytest

from app.core.config import get_settings
from app.core.utils import aggregate_list
from app.database.indexes import vector_index_definitions
from app.llm.embeddings import HashEmbedder
from app.llm.providers import AnthropicProvider, LLMError, MockProvider, OpenAIProvider, extract_json
from app.memory.retrieval import vector_search_pipeline


def _settings(**kw):
    s = get_settings().model_copy()
    for k, v in kw.items():
        setattr(s, k, v)
    s.llm_max_retries = 2
    return s


async def test_anthropic_request_shape_and_retry(monkeypatch):
    import asyncio
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    calls = []

    def handler(request: httpx.Request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(529, json={"error": "overloaded"})
        assert request.headers["x-api-key"] == "k" and request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hello"}]})

    p = AnthropicProvider(_settings(anthropic_api_key="k"), transport=httpx.MockTransport(handler))
    out = await p.complete("sys", [{"role": "user", "content": "hi"}], model="claude-test")
    assert out == "hello" and len(calls) == 2
    assert calls[1]["system"] == "sys" and calls[1]["model"] == "claude-test"


async def test_openai_json_mode_and_client_error():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        if body["model"] == "bad":
            return httpx.Response(400, json={"error": "bad request"})
        assert body["response_format"] == {"type": "json_object"} and body["messages"][0]["role"] == "system"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    p = OpenAIProvider(_settings(openai_api_key="k"), transport=httpx.MockTransport(handler))
    assert extract_json(await p.complete("s", [{"role": "user", "content": "x"}], json_mode=True)) == {"ok": True}
    with pytest.raises(LLMError):
        await p.complete("s", [{"role": "user", "content": "x"}], model="bad")


async def _no_sleep(*_a, **_k):
    return None


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise {"b": [1,2]} trailing') == {"b": [1, 2]}


async def test_mock_provider_is_labelled_offline():
    out = await MockProvider().complete("<memory_context>\nM1 preference: Prefers code\n</memory_context>",
                                        [{"role": "user", "content": "Explain binary search"}])
    assert out.startswith("Offline demo model") and "M1 preference" in out and "Personalized using: M1" in out


async def test_hash_embedder_similarity_ordering():
    from app.core.utils import cosine
    e = HashEmbedder(256)
    a, b, c = await e.embed(["struggles with recursion", "I struggle with recursive functions", "prefers short answers"])
    assert len(a) == 256 and cosine(a, b) > cosine(a, c)


def test_atlas_vector_search_pipeline_and_index_definition():
    s = get_settings()
    pipe = vector_search_pipeline([0.1] * s.embedding_dimensions, "u1", "default", 10, s.memory_vector_index)
    stage = pipe[0]["$vectorSearch"]
    assert stage["index"] == s.memory_vector_index and stage["path"] == "embedding"
    assert stage["numCandidates"] >= stage["limit"] == 10
    assert stage["filter"] == {"user_id": {"$eq": "u1"}, "workspace_id": {"$eq": "default"}, "status": {"$eq": "active"}}
    assert pipe[1] == {"$addFields": {"_vs_score": {"$meta": "vectorSearchScore"}}}
    fields = vector_index_definitions(s)["memories"]["definition"]["fields"]
    assert fields[0] == {"type": "vector", "path": "embedding", "numDimensions": s.embedding_dimensions, "similarity": "cosine"}
    assert {f["path"] for f in fields if f["type"] == "filter"} == {"user_id", "workspace_id", "status", "type"}


class _AwaitableAggCollection:
    """Mimics PyMongo's async API where aggregate() is a coroutine."""

    def __init__(self, docs):
        self.docs, self.pipeline = docs, None

    async def aggregate(self, pipeline):
        self.pipeline = pipeline
        docs = self.docs

        class Cursor:
            async def to_list(self, length=None):
                return docs

        return Cursor()


async def test_aggregate_list_supports_pymongo_async_api():
    coll = _AwaitableAggCollection([{"_id": 1}])
    assert await aggregate_list(coll, [{"$match": {}}]) == [{"_id": 1}]
    assert coll.pipeline == [{"$match": {}}]
