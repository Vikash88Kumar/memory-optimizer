"""Small shared helpers: ids, time, text normalisation, vectors, driver compatibility."""
from __future__ import annotations

import datetime as dt
import inspect
import math
import re
import uuid
from typing import Any, Iterable

UTC = dt.timezone.utc

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "to", "of", "in", "on", "for", "with",
    "at", "by", "from", "as", "is", "are", "was", "were", "be", "been", "being", "i", "me", "my",
    "mine", "you", "your", "we", "our", "it", "its", "this", "that", "these", "those", "do", "does",
    "did", "have", "has", "had", "will", "would", "can", "could", "should", "please", "about", "into",
    "just", "very", "really", "also", "some", "any", "what", "how", "why", "when", "which", "who",
    "am", "not", "no", "up", "out", "user", "there", "their", "them", "they", "he", "she", "him", "her",
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC)


def as_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def estimate_tokens(text: str | None) -> int:
    """Rough token estimate (~4 characters per token). Good enough for budgeting."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def slugify(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:max_len] or "item"


def stem(word: str) -> str:
    for suffix in ("ing", "ies", "ed", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9+#]+", text.lower()) if w not in STOPWORDS]


def term_set(text: str) -> set[str]:
    return set(tokenize(text))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def normalized_similarity(cos: float) -> float:
    """Map cosine (-1..1) to 0..1 the same way Atlas Vector Search reports cosine scores."""
    return (1.0 + cos) / 2.0


def normalize_vector(v: Iterable[float]) -> list[float]:
    v = list(v)
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def combine_vectors(parts: list[tuple[list[float] | None, float]]) -> list[float] | None:
    base: list[float] | None = None
    for vec, weight in parts:
        if not vec or weight == 0:
            continue
        if base is None:
            base = [0.0] * len(vec)
        if len(vec) != len(base):
            continue
        base = [b + weight * x for b, x in zip(base, vec)]
    return normalize_vector(base) if base else None


async def aggregate_list(collection: Any, pipeline: list[dict], length: int | None = None) -> list[dict]:
    """Run an aggregation with either PyMongo's async API (awaitable) or Motor-style cursors."""
    cursor = collection.aggregate(pipeline)
    if inspect.isawaitable(cursor):
        cursor = await cursor
    return await cursor.to_list(length)


def truncate(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"
