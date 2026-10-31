"""Configurable embedding providers. The same model must embed both documents and queries."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Literal

import httpx

from app.core.config import Settings, get_settings
from app.core.utils import normalize_vector, tokenize
from app.llm.providers import LLMError, post_with_retries

InputType = Literal["document", "query"]


class Embedder(ABC):
    name = "base"
    is_offline = False

    def __init__(self, dims: int):
        self.dims = dims

    @abstractmethod
    async def embed(self, texts: list[str], input_type: InputType = "document") -> list[list[float]]:
        ...

    async def embed_one(self, text: str, input_type: InputType = "document") -> list[float]:
        return (await self.embed([text], input_type))[0]

    def _check(self, vectors: list[list[float]]) -> list[list[float]]:
        for v in vectors:
            if len(v) != self.dims:
                raise LLMError(f"Embedding has {len(v)} dimensions, expected EMBEDDING_DIMENSIONS={self.dims}")
        return vectors


class HashEmbedder(Embedder):
    """OFFLINE FALLBACK: deterministic feature-hashing embeddings (words, bigrams, character trigrams).
    Captures lexical overlap only - use a real embedding model for semantic retrieval."""
    name = "hash"
    is_offline = True

    def _features(self, text: str) -> list[tuple[str, float]]:
        words = tokenize(text)
        feats: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words]
        feats += [(f"b:{a}_{b}", 0.7) for a, b in zip(words, words[1:])]
        for w in words:
            padded = f"#{w}#"
            feats += [(f"c:{padded[i:i + 3]}", 0.25) for i in range(len(padded) - 2)]
        return feats

    async def embed(self, texts, input_type="document"):
        out = []
        for text in texts:
            vec = [0.0] * self.dims
            for feat, weight in self._features(text):
                h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self.dims
                sign = 1.0 if h[4] & 1 else -1.0
                vec[idx] += sign * weight
            out.append(normalize_vector(vec))
        return out


class OpenAIEmbedder(Embedder):
    name = "openai"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(settings.embedding_dimensions)
        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is required for EMBEDDING_PROVIDER=openai")
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds, transport=transport)

    async def embed(self, texts, input_type="document"):
        payload = {"model": self.settings.embedding_model, "input": texts, "dimensions": self.dims}
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        data = await post_with_retries(self.client, f"{self.settings.openai_base_url}/embeddings",
                                       headers=headers, payload=payload, retries=self.settings.llm_max_retries)
        items = sorted(data["data"], key=lambda d: d["index"])
        return self._check([d["embedding"] for d in items])


class VoyageEmbedder(Embedder):
    name = "voyage"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(settings.embedding_dimensions)
        if not settings.voyage_api_key:
            raise LLMError("VOYAGE_API_KEY is required for EMBEDDING_PROVIDER=voyage")
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds, transport=transport)

    async def embed(self, texts, input_type="document"):
        payload = {"model": self.settings.embedding_model, "input": texts, "input_type": input_type,
                   "output_dimension": self.dims}
        headers = {"Authorization": f"Bearer {self.settings.voyage_api_key}"}
        data = await post_with_retries(self.client, f"{self.settings.voyage_base_url}/embeddings",
                                       headers=headers, payload=payload, retries=self.settings.llm_max_retries)
        items = sorted(data["data"], key=lambda d: d["index"])
        return self._check([d["embedding"] for d in items])


_override: Embedder | None = None
_instance: Embedder | None = None


def set_embedder(embedder: Embedder | None) -> None:
    global _override
    _override = embedder


def get_embedder() -> Embedder:
    global _instance
    if _override is not None:
        return _override
    if _instance is None:
        settings = get_settings()
        if settings.embedding_provider == "openai":
            _instance = OpenAIEmbedder(settings)
        elif settings.embedding_provider == "voyage":
            _instance = VoyageEmbedder(settings)
        else:
            _instance = HashEmbedder(settings.embedding_dimensions)
    return _instance
