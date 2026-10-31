"""Hybrid memory retrieval: vector search + metadata filters + graph expansion + weighted ranking."""
from __future__ import annotations

import datetime as dt
from typing import Any

from app.core.config import get_settings
from app.core.utils import aggregate_list, as_utc, cosine, normalized_similarity
from app.memory import graph
from app.memory.ranking import Scored, detect_subjects, passes_gate, score_memory


def backend_label() -> str:
    return "mongodb_vector_search" if get_settings().vector_backend == "mongodb" else "local_fallback"


def is_live(doc: dict[str, Any], now: dt.datetime) -> bool:
    """TTL deletion is asynchronous, so expiry is enforced here as well."""
    if doc.get("status") != "active" or doc.get("confirmation") == "rejected":
        return False
    expires = as_utc(doc.get("expires_at"))
    return expires is None or expires > now


def vector_search_pipeline(qvec: list[float], user_id: str, workspace_id: str, limit: int,
                           index: str, status: str = "active") -> list[dict[str, Any]]:
    s = get_settings()
    return [
        {
            "$vectorSearch": {
                "index": index,
                "path": "embedding",
                "queryVector": qvec,
                "numCandidates": max(s.vector_num_candidates, limit * 10),
                "limit": limit,
                "filter": {"user_id": {"$eq": user_id}, "workspace_id": {"$eq": workspace_id},
                           "status": {"$eq": status}},
            }
        },
        {"$addFields": {"_vs_score": {"$meta": "vectorSearchScore"}}},
    ]


async def vector_candidates(db: Any, collection: str, qvec: list[float], user_id: str, workspace_id: str,
                            limit: int, status: str = "active") -> list[tuple[dict[str, Any], float]]:
    s = get_settings()
    if s.vector_backend == "mongodb":
        index = s.memory_vector_index if collection == "memories" else s.episode_vector_index
        docs = await aggregate_list(db[collection], vector_search_pipeline(qvec, user_id, workspace_id, limit, index, status))
        return [(d, float(d.pop("_vs_score", 0.0))) for d in docs]
    # DEVELOPMENT FALLBACK - brute-force cosine in Python. Not Atlas Vector Search.
    docs = await db[collection].find(
        {"user_id": user_id, "workspace_id": workspace_id, "status": status, "embedding": {"$exists": True}}
    ).to_list(5000)
    scored = [(d, normalized_similarity(cosine(qvec, d.get("embedding")))) for d in docs]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:limit]


async def retrieve(db: Any, *, user_id: str, workspace_id: str, query_text: str, qvec: list[float],
                   now: dt.datetime, exclude_ids: set[str], subjects: set[str] | None = None,
                   limit: int = 12) -> list[Scored]:
    subjects = subjects if subjects is not None else detect_subjects(query_text)
    candidates = await vector_candidates(db, "memories", qvec, user_id, workspace_id, limit=limit * 2)
    graph_reasons = await graph.graph_hits_for_text(db, user_id, workspace_id, query_text)
    by_id: dict[str, tuple[dict[str, Any], float]] = {d["_id"]: (d, sim) for d, sim in candidates}
    missing = [mid for mid in graph_reasons if mid not in by_id]
    if missing:
        extra = await db.memories.find({"_id": {"$in": missing}, "user_id": user_id, "workspace_id": workspace_id}).to_list(len(missing))
        for d in extra:
            by_id[d["_id"]] = (d, normalized_similarity(cosine(qvec, d.get("embedding"))))
    results: list[Scored] = []
    for mid, (doc, sim) in by_id.items():
        if mid in exclude_ids or not is_live(doc, now):
            continue
        scored = score_memory(doc, similarity=sim, now=now, subjects=subjects, graph_reason=graph_reasons.get(mid))
        if scored and passes_gate(scored):
            results.append(scored)
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]
