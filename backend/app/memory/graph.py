"""Knowledge graph layer stored in MongoDB (entities + relationships collections).

Memories are the source of truth; every graph edge carries the memory_ids that support it, so
removing or superseding a memory updates the graph deterministically."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from pymongo.errors import DuplicateKeyError

from app.core.utils import new_id, truncate

USER_NORM = "__user__"
RELATION_BY_TYPE = {
    "preference": "prefers", "interest": "learning", "knowledge": "knows",
    "learning_difficulty": "struggles_with", "goal": "wants_to", "decision": "decided",
    "constraint": "has_constraint", "experience": "experienced", "feedback": "gave_feedback",
    "strategy": "responds_well_to", "fact": "has_fact",
}
KIND_BY_TYPE = {
    "preference": "preference", "interest": "topic", "knowledge": "skill", "learning_difficulty": "difficulty",
    "goal": "goal", "decision": "decision", "constraint": "constraint", "experience": "experience",
    "feedback": "feedback", "strategy": "strategy", "fact": "fact",
}
_PREFIX = re.compile(
    r"^(?:user\s+)?(?:prefers|likes|wants to|wants|is learning|is studying|is interested in|struggles with|"
    r"finds|knows|has decided to|decided to|has|is|learns well with|responds well to|does not want|"
    r"has built|built|worked on|experienced)\s+",
    re.I,
)


def norm_name(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9+#\- ]", " ", name.lower()).split())


def object_label(content: str) -> str:
    label = _PREFIX.sub("", content.strip().rstrip("."))
    label = re.split(r"\s+(?:for|with|because|when|so that)\s+", label, maxsplit=1)[0] if len(label) > 40 else label
    return truncate(label, 48)


async def ensure_user_node(db: Any, user_id: str, workspace_id: str, display: str, now: dt.datetime) -> str:
    existing = await db.entities.find_one({"user_id": user_id, "workspace_id": workspace_id, "norm": USER_NORM})
    if existing:
        return existing["_id"]
    doc = {"_id": new_id("ent"), "user_id": user_id, "workspace_id": workspace_id, "name": display,
           "norm": USER_NORM, "kind": "user", "memory_ids": [], "created_at": now, "updated_at": now}
    try:
        await db.entities.insert_one(doc)
        return doc["_id"]
    except DuplicateKeyError:
        found = await db.entities.find_one({"user_id": user_id, "workspace_id": workspace_id, "norm": USER_NORM})
        return found["_id"]


async def upsert_entity(db: Any, user_id: str, workspace_id: str, name: str, kind: str,
                        memory_ids: Iterable[str], now: dt.datetime) -> str:
    norm = norm_name(name)
    ids = list(memory_ids)
    existing = await db.entities.find_one({"user_id": user_id, "workspace_id": workspace_id, "norm": norm})
    if existing:
        update: dict[str, Any] = {"$set": {"updated_at": now}}
        if ids:
            update["$addToSet"] = {"memory_ids": {"$each": ids}}
        await db.entities.update_one({"_id": existing["_id"]}, update)
        return existing["_id"]
    doc = {"_id": new_id("ent"), "user_id": user_id, "workspace_id": workspace_id, "name": truncate(name, 60),
           "norm": norm, "kind": kind, "memory_ids": ids, "created_at": now, "updated_at": now}
    try:
        await db.entities.insert_one(doc)
        return doc["_id"]
    except DuplicateKeyError:
        return await upsert_entity(db, user_id, workspace_id, name, kind, ids, now)


async def upsert_relationship(db: Any, user_id: str, workspace_id: str, source_id: str, relation: str,
                              target_id: str, memory_ids: Iterable[str], now: dt.datetime) -> str:
    query = {"user_id": user_id, "workspace_id": workspace_id, "source_id": source_id,
             "relation": relation, "target_id": target_id}
    ids = list(memory_ids)
    existing = await db.relationships.find_one(query)
    if existing:
        await db.relationships.update_one(
            {"_id": existing["_id"]},
            {"$set": {"status": "active", "updated_at": now}, "$addToSet": {"memory_ids": {"$each": ids}}},
        )
        return existing["_id"]
    doc = {"_id": new_id("rel"), **query, "memory_ids": ids, "status": "active", "created_at": now, "updated_at": now}
    try:
        await db.relationships.insert_one(doc)
        return doc["_id"]
    except DuplicateKeyError:
        return await upsert_relationship(db, user_id, workspace_id, source_id, relation, target_id, ids, now)


async def link_memory(db: Any, memory: dict[str, Any], entities: list[dict[str, str]], user_display: str,
                      now: dt.datetime) -> list[str]:
    """Create User -[relation]-> object, plus object -[about]-> topic edges for a memory."""
    uid, ws, mid = memory["user_id"], memory["workspace_id"], memory["_id"]
    user_node = await ensure_user_node(db, uid, ws, user_display, now)
    kind = KIND_BY_TYPE.get(memory["type"], "concept")
    primary = next((e for e in entities if e.get("kind") not in ("topic",)), None)
    obj_name = primary["name"] if primary else object_label(memory["content"])
    obj_id = await upsert_entity(db, uid, ws, obj_name, kind, [mid], now)
    await upsert_relationship(db, uid, ws, user_node, RELATION_BY_TYPE.get(memory["type"], "related_to"), obj_id, [mid], now)
    entity_ids = [obj_id]
    topics = [e for e in entities if e is not primary]
    scope = memory.get("scope", "global")
    if scope.startswith("topic:"):
        topics.append({"name": scope.split(":", 1)[1], "kind": "topic"})
    for topic in topics:
        if norm_name(topic["name"]) == norm_name(obj_name):
            continue
        tid = await upsert_entity(db, uid, ws, topic["name"], topic.get("kind", "topic"), [mid], now)
        await upsert_relationship(db, uid, ws, obj_id, "about", tid, [mid], now)
        entity_ids.append(tid)
    await db.memories.update_one({"_id": mid}, {"$set": {"entity_ids": entity_ids}})
    return entity_ids


async def link_relationships(db: Any, user_id: str, workspace_id: str, relationships: list[dict[str, str]],
                             memory_ids: list[str], now: dt.datetime) -> int:
    count = 0
    for rel in relationships:
        if not memory_ids:
            break
        src = await upsert_entity(db, user_id, workspace_id, rel["source"], "concept", memory_ids, now)
        tgt = await upsert_entity(db, user_id, workspace_id, rel["target"], "concept", memory_ids, now)
        if src != tgt:
            await upsert_relationship(db, user_id, workspace_id, src, rel["relation"], tgt, memory_ids, now)
            count += 1
    return count


async def unlink_memory(db: Any, user_id: str, memory_id: str, mode: str, now: dt.datetime) -> None:
    """mode="supersede": keep history edges, marked superseded. mode="delete": remove all traces."""
    if mode == "supersede":
        await db.relationships.update_many(
            {"user_id": user_id, "memory_ids": [memory_id]}, {"$set": {"status": "superseded", "updated_at": now}}
        )
        await db.relationships.update_many(
            {"user_id": user_id, "memory_ids": memory_id, "memory_ids.1": {"$exists": True}},
            {"$pull": {"memory_ids": memory_id}},
        )
        return
    await db.relationships.update_many({"user_id": user_id, "memory_ids": memory_id}, {"$pull": {"memory_ids": memory_id}})
    await db.relationships.delete_many({"user_id": user_id, "memory_ids": {"$size": 0}})
    await db.entities.update_many({"user_id": user_id, "memory_ids": memory_id}, {"$pull": {"memory_ids": memory_id}})
    orphans = await db.entities.find(
        {"user_id": user_id, "memory_ids": {"$size": 0}, "norm": {"$ne": USER_NORM}}, {"_id": 1}
    ).to_list(None)
    for ent in orphans:
        used = await db.relationships.find_one(
            {"user_id": user_id, "$or": [{"source_id": ent["_id"]}, {"target_id": ent["_id"]}]}
        )
        if not used:
            await db.entities.delete_one({"_id": ent["_id"]})


async def export_graph(db: Any, user_id: str, workspace_id: str, include_superseded: bool = False) -> dict[str, Any]:
    rel_query: dict[str, Any] = {"user_id": user_id, "workspace_id": workspace_id}
    if not include_superseded:
        rel_query["status"] = "active"
    rels = await db.relationships.find(rel_query).to_list(2000)
    entities = await db.entities.find({"user_id": user_id, "workspace_id": workspace_id}).to_list(2000)
    used = {r["source_id"] for r in rels} | {r["target_id"] for r in rels}
    nodes = [
        {"id": e["_id"], "label": e["name"], "kind": e["kind"], "memory_ids": e.get("memory_ids", [])}
        for e in entities
        if e["_id"] in used or e["norm"] == USER_NORM
    ]
    edges = [
        {"id": r["_id"], "source": r["source_id"], "target": r["target_id"], "relation": r["relation"],
         "status": r.get("status", "active"), "memory_ids": r.get("memory_ids", [])}
        for r in rels
    ]
    return {"nodes": nodes, "edges": edges}


async def graph_hits_for_text(db: Any, user_id: str, workspace_id: str, text: str, limit: int = 10) -> dict[str, str]:
    """Entities named in the query, expanded one hop. Returns memory_id -> explanation."""
    normalized = f" {norm_name(text)} "
    entities = await db.entities.find(
        {"user_id": user_id, "workspace_id": workspace_id, "norm": {"$ne": USER_NORM}}
    ).to_list(1000)
    hit = [e for e in entities if len(e["norm"]) >= 3 and f" {e['norm']} " in normalized]
    if not hit:
        return {}
    by_id = {e["_id"]: e for e in entities}
    reasons: dict[str, str] = {}
    for e in hit:
        for mid in e.get("memory_ids", []):
            reasons.setdefault(mid, f"Mentions \u201c{e['name']}\u201d from your knowledge graph")
    hit_ids = [e["_id"] for e in hit]
    rels = await db.relationships.find(
        {"user_id": user_id, "workspace_id": workspace_id, "status": "active",
         "$or": [{"source_id": {"$in": hit_ids}}, {"target_id": {"$in": hit_ids}}]}
    ).to_list(200)
    for r in rels:
        src, tgt = by_id.get(r["source_id"]), by_id.get(r["target_id"])
        if not src or not tgt:
            continue
        path = f"{src['name']} \u2013{r['relation']}\u2192 {tgt['name']}"
        for mid in r.get("memory_ids", []):
            reasons.setdefault(mid, f"Linked in knowledge graph: {path}")
        for neighbour in (src, tgt):
            if neighbour["norm"] == USER_NORM:
                continue
            for mid in neighbour.get("memory_ids", []):
                reasons.setdefault(mid, f"Linked in knowledge graph: {path}")
    return dict(list(reasons.items())[:limit])
