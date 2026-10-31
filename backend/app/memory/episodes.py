"""Episodic memory: conversations are segmented into episodes that are summarised, embedded,
linked to the memories they produced (consolidation) and allowed to fade."""
from __future__ import annotations

import datetime as dt
import math
import re
from collections import Counter
from typing import Any

from app.core.config import Settings, get_settings
from app.core.utils import (as_utc, cosine, new_id, normalize_vector,
                            tokenize, truncate)
from app.memory import decay
from app.memory.events import log_event
from app.memory.retrieval import vector_candidates

_CUES = ("new topic", "anyway", "switching to", "different question", "moving on", "change of topic",
         "unrelated", "on another note", "something else")


async def get_active(db: Any, conversation_id: str) -> dict[str, Any] | None:
    return await db.episodes.find_one({"conversation_id": conversation_id, "status": "open"})


async def open_episode(db: Any, *, user_id: str, workspace_id: str, conversation_id: str, now: dt.datetime,
                       first_text: str) -> dict[str, Any]:
    doc = {
        "_id": new_id("ep"), "user_id": user_id, "workspace_id": workspace_id, "conversation_id": conversation_id,
        "status": "open", "title": truncate(first_text, 60), "started_at": now, "last_at": now, "ended_at": None,
        "turns": 0, "message_ids": [], "centroid": None, "subjects": [], "rolling_summary": "",
        "summarized_count": 0, "summary": None, "outcome": None, "topics": [], "consolidated_into": [],
        "strength": 1.0, "decay_lambda": math.log(2) / decay.EPISODE_HALF_LIFE_DAYS, "last_reinforced_at": now,
        "expires_at": None,
    }
    await db.episodes.insert_one(doc)
    return doc


async def add_message(db: Any, episode: dict[str, Any], message_id: str, role: str, now: dt.datetime,
                      embedding: list[float] | None = None, subjects: set[str] | None = None) -> dict[str, Any]:
    update: dict[str, Any] = {"$push": {"message_ids": message_id}, "$set": {"last_at": now}}
    if role == "user":
        n = int(episode.get("turns", 0))
        centroid = episode.get("centroid")
        if embedding:
            if centroid and len(centroid) == len(embedding):
                centroid = normalize_vector([(c * n + e) / (n + 1) for c, e in zip(centroid, embedding)])
            else:
                centroid = embedding
            update["$set"]["centroid"] = centroid
        update["$inc"] = {"turns": 1}
        if subjects:
            update["$addToSet"] = {"subjects": {"$each": sorted(subjects)}}
    await db.episodes.update_one({"_id": episode["_id"]}, update)
    return await db.episodes.find_one({"_id": episode["_id"]})


def boundary_score(embedding: list[float] | None, centroid: list[float] | None, gap_minutes: float, text: str,
                   settings: Settings | None = None) -> tuple[float, dict[str, float]]:
    s = settings or get_settings()
    topic_shift = 1.0 - max(0.0, cosine(embedding, centroid)) if centroid and embedding else 0.0
    time_gap = min(gap_minutes / s.boundary_gap_minutes, 1.0) if gap_minutes > 0 else 0.0
    low = text.lower()
    cue = 1.0 if any(c in low for c in _CUES) else 0.0
    score = 0.5 * topic_shift + 0.3 * time_gap + 0.2 * cue
    return round(score, 4), {"topic_shift": round(topic_shift, 4), "time_gap": round(time_gap, 4), "cue": cue}


def boundary_decision(score: float, episode: dict[str, Any], pending: bool, settings: Settings | None = None,
                      explicit_cue: bool = False) -> str:
    s = settings or get_settings()
    if explicit_cue and int(episode.get("turns", 0)) >= 1:
        return "switch"  # the user said so ("anyway, new topic...")
    if int(episode.get("turns", 0)) < s.min_episode_turns:
        return "stay"
    if score >= s.boundary_threshold:
        return "switch"
    if score >= s.soft_boundary_threshold:
        return "switch" if pending else "soft"
    return "stay"


def make_bridge(episode: dict[str, Any], last_user_text: str | None) -> str:
    bridge = f"Previous episode: \u201c{episode.get('title', 'conversation')}\u201d ({episode.get('turns', 0)} turns)."
    if last_user_text and last_user_text.strip().endswith("?"):
        bridge += f" Last open question: {truncate(last_user_text, 100)}"
    return bridge


def heuristic_summary(messages: list[dict[str, Any]]) -> dict[str, Any]:
    user_msgs = [m["content"] for m in messages if m["role"] == "user" and not m.get("redacted")]
    words = Counter(w for text in user_msgs for w in tokenize(text) if len(w) > 3)
    topics = [w for w, _ in words.most_common(4)]
    summary = " | ".join(truncate(t, 80) for t in user_msgs[:4])
    return {"title": truncate(user_msgs[0], 60) if user_msgs else "Conversation",
            "summary": truncate(summary, 400), "topics": topics, "outcome": "unresolved"}


async def summarise_messages(messages: list[dict[str, Any]], llm: Any) -> dict[str, Any]:
    from app.agents.prompts import EPISODE_SUMMARY_PROMPT
    from app.llm.providers import extract_json

    if llm.is_offline or not messages:
        return heuristic_summary(messages)
    transcript = "\n".join(f"{m['role'].upper()}: {truncate(m['content'], 400)}" for m in messages if not m.get("redacted"))
    try:
        raw = await llm.complete(EPISODE_SUMMARY_PROMPT, [{"role": "user", "content": transcript}],
                                 model=get_settings().extractor_model, max_tokens=400, json_mode=True)
        data = extract_json(raw)
        return {
            "title": truncate(str(data.get("title") or ""), 60) or heuristic_summary(messages)["title"],
            "summary": truncate(str(data.get("summary") or ""), 500),
            "topics": [truncate(str(t), 40) for t in (data.get("topics") or [])][:6],
            "outcome": data.get("outcome") if data.get("outcome") in ("positive", "negative", "neutral", "unresolved") else "neutral",
        }
    except Exception:  # noqa: BLE001 - fall back rather than lose the episode
        return heuristic_summary(messages)


async def close_episode(db: Any, episode_id: str, now: dt.datetime, llm: Any, embedder: Any) -> dict[str, Any] | None:
    episode = await db.episodes.find_one({"_id": episode_id})
    if not episode or episode["status"] == "closed":
        return episode
    messages = await db.messages.find({"_id": {"$in": episode.get("message_ids", [])}}).sort("created_at", 1).to_list(500)
    info = await summarise_messages(messages, llm)
    embedding = await embedder.embed_one(f"{info['title']}. {info['summary']}", "document") if info["summary"] else None
    consolidated = await db.memories.find(
        {"user_id": episode["user_id"], "evidence_message_ids": {"$in": episode.get("message_ids", [])}}, {"_id": 1}
    ).to_list(100)
    retention = get_settings().episode_retention_days
    update = {
        "status": "closed", "ended_at": episode.get("ended_at") or now, "title": info["title"], "summary": info["summary"],
        "topics": info["topics"], "outcome": info["outcome"], "consolidated_into": [m["_id"] for m in consolidated],
        "expires_at": now + dt.timedelta(days=retention) if retention > 0 else None,
    }
    if embedding:
        update["embedding"] = embedding
    await db.episodes.update_one({"_id": episode_id}, {"$set": update})
    await log_event(db, user_id=episode["user_id"], workspace_id=episode["workspace_id"], action="episode_closed",
                    now=now, memory_ids=update["consolidated_into"],
                    reason=f"Episode \u201c{info['title']}\u201d closed and summarised; consolidated into "
                           f"{len(update['consolidated_into'])} memories",
                    details={"episode_id": episode_id, "turns": episode.get("turns", 0)})
    return await db.episodes.find_one({"_id": episode_id})


async def update_rolling_summary(db: Any, episode_id: str, llm: Any, window: int) -> None:
    """Compress turns that fell out of the verbatim window into the episode's rolling summary."""
    from app.agents.prompts import ROLLING_SUMMARY_PROMPT

    episode = await db.episodes.find_one({"_id": episode_id})
    if not episode or episode["status"] != "open":
        return
    messages = await db.messages.find({"_id": {"$in": episode.get("message_ids", [])}}).sort("created_at", 1).to_list(500)
    older = messages[: max(0, len(messages) - window)]
    if len(older) <= int(episode.get("summarized_count", 0)):
        return
    if llm.is_offline:
        text = " | ".join(truncate(m["content"], 60) for m in older if m["role"] == "user" and not m.get("redacted"))
        summary = truncate(text, 600)
    else:
        transcript = "\n".join(f"{m['role'].upper()}: {truncate(m['content'], 300)}" for m in older if not m.get("redacted"))
        prior = episode.get("rolling_summary") or ""
        summary = truncate(await llm.complete(ROLLING_SUMMARY_PROMPT, [{"role": "user", "content": f"Previous summary: {prior}\n\nNew turns:\n{transcript}"}],
                                              model=get_settings().extractor_model, max_tokens=250), 900)
    await db.episodes.update_one({"_id": episode_id}, {"$set": {"rolling_summary": summary, "summarized_count": len(older)}})


async def search_closed(db: Any, user_id: str, workspace_id: str, qvec: list[float], now: dt.datetime,
                        limit: int = 2) -> list[tuple[dict[str, Any], float]]:
    candidates = await vector_candidates(db, "episodes", qvec, user_id, workspace_id, limit=limit * 3, status="closed")
    out = []
    for ep, sim in candidates:
        strength = decay.strength_at(ep, now)
        expires = as_utc(ep.get("expires_at"))
        if expires and expires <= now:
            continue
        out.append((ep, round(sim * (0.6 + 0.4 * strength), 4)))
    out.sort(key=lambda x: x[1], reverse=True)
    return out[:limit]
