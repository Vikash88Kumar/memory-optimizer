"""Working memory controller.

Builds the per-turn context from tiers with separate token budgets:
  T1 core profile (cached per session, invalidated when memories change)
  T2 bridge from the previous episode (decays out after a few turns)
  T3 current episode state (rolling summary + recent verbatim turns of THIS episode only)
  T4 retrieved memories (delta retrieval + per-turn activation decay + value-per-token packing)
  T5 episodic evidence (only when the gate fires)
It also detects episode boundaries and swaps the episode tiers when the user moves on."""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.utils import as_utc, combine_vectors, cosine, estimate_tokens, new_id, normalized_similarity, truncate
from app.memory import episodes
from app.memory.budget import BudgetItem, fit_recent, pack
from app.memory.evidence import needs_episodic_evidence, resolve_evidence
from app.memory.ranking import Scored, detect_subjects, passes_gate, resolve_scope_overrides, score_memory
from app.memory.retrieval import backend_label, is_live, retrieve
from app.memory.safety import sanitize_for_prompt

TRIVIAL = re.compile(
    r"^\s*(ok(ay)?|k|thanks?( you)?( so much)?|thx|ty|cool|got it|nice|great|sure|yes|no|yep|nope|hmm+|alright|perfect|awesome)[\s.!]*$",
    re.I,
)
PROFILE_TYPES = ["preference", "goal", "constraint", "strategy"]


@dataclass
class TurnContext:
    system_context: str
    history: list[dict[str, str]]
    used: list[dict[str, Any]]
    used_docs: list[dict[str, Any]]
    overridden: list[dict[str, Any]]
    episode: dict[str, Any]
    tokens: dict[str, int]
    evidence: list[dict[str, Any]] = field(default_factory=list)
    evidence_reason: str = ""
    retrieval_backend: str = "local_fallback"
    closed_episode_id: str | None = None
    trivial: bool = False
    boundary: dict[str, Any] | None = None


def is_trivial(text: str) -> bool:
    return bool(TRIVIAL.match(text))


async def get_session(db: Any, user_id: str, workspace_id: str, conversation_id: str, now: dt.datetime) -> dict[str, Any]:
    session = await db.sessions.find_one({"_id": conversation_id, "user_id": user_id})
    if session:
        return session
    session = {
        "_id": conversation_id, "user_id": user_id, "workspace_id": workspace_id, "created_at": now,
        "last_turn_at": None, "profile_version": -1, "profile_ids": [], "wm_items": [], "bridge": None,
        "bridge_turns_left": 0, "pending_boundary": False, "h_fast": None, "pending_extraction": [],
    }
    await db.sessions.insert_one(session)
    return session


async def load_core_profile(db: Any, user_id: str, workspace_id: str, now: dt.datetime) -> list[dict[str, Any]]:
    s = get_settings()
    docs = await db.memories.find({
        "user_id": user_id, "workspace_id": workspace_id, "status": "active", "type": {"$in": PROFILE_TYPES},
        "confirmation": {"$in": ["not_required", "confirmed"]}, "confidence": {"$gte": s.pinned_min_confidence},
    }).sort("importance", -1).to_list(20)
    return [d for d in docs if is_live(d, now)]


def render_line(ref: str, mem: dict[str, Any]) -> str:
    line = f"{ref} {mem['type']}: {sanitize_for_prompt(mem['content'], 220)}"
    scope = mem.get("scope") or "global"
    if scope.startswith("topic:"):
        line += f" [only for {scope.split(':', 1)[1]}]"
    if mem.get("confirmation") == "pending":
        line += " (unconfirmed)"
    expires = as_utc(mem.get("expires_at"))
    if expires:
        line += f" [until {expires:%Y-%m-%d}]"
    return line


def _update_state(prev: list[float] | None, e: list[float], hours: float, tau_hours: float, gain: float) -> list[float]:
    if not prev or len(prev) != len(e):
        return e
    a = math.exp(-max(0.0, hours) / tau_hours)
    return combine_vectors([(prev, a), (e, gain)]) or e


def _alternate(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    """Providers expect user/assistant alternation starting with a user turn."""
    out: list[dict[str, str]] = []
    for t in turns:
        if not out and t["role"] != "user":
            continue
        if out and out[-1]["role"] == t["role"]:
            out[-1] = {"role": t["role"], "content": out[-1]["content"] + "\n\n" + t["content"]}
        else:
            out.append(dict(t))
    if out and out[-1]["role"] == "user":
        out.pop()  # the current user message is appended by the agent
    return out


async def build_turn_context(db: Any, *, user: dict[str, Any], workspace_id: str, conversation: dict[str, Any],
                             user_message: dict[str, Any], now: dt.datetime) -> TurnContext:
    s = get_settings()
    uid, cid = user["_id"], conversation["_id"]
    text = user_message["content"]
    e = user_message.get("embedding")
    session = await get_session(db, uid, workspace_id, cid, now)
    trivial = is_trivial(text)
    last_turn = as_utc(session.get("last_turn_at"))
    gap_min = (now - last_turn).total_seconds() / 60 if last_turn else 0.0

    # ---- Episode boundary detection and switching ---------------------------------------
    episode = await episodes.get_active(db, cid)
    closed_id: str | None = None
    boundary: dict[str, Any] | None = None
    switched = False
    if episode is None:
        episode = await episodes.open_episode(db, user_id=uid, workspace_id=workspace_id, conversation_id=cid,
                                              now=now, first_text=text)
    elif not trivial:
        score, parts = episodes.boundary_score(e, episode.get("centroid"), gap_min, text)
        decision = episodes.boundary_decision(score, episode, bool(session.get("pending_boundary")),
                                              explicit_cue=parts["cue"] == 1.0)
        boundary = {"score": score, **parts, "decision": decision}
        if decision == "switch":
            last_user = await db.messages.find_one(
                {"episode_id": episode["_id"], "role": "user"}, sort=[("created_at", -1)]
            )
            session["bridge"] = episodes.make_bridge(episode, last_user["content"] if last_user else None)
            session["bridge_turns_left"] = s.bridge_turns
            await db.episodes.update_one({"_id": episode["_id"]}, {"$set": {"status": "closing", "ended_at": now}})
            closed_id = episode["_id"]
            episode = await episodes.open_episode(db, user_id=uid, workspace_id=workspace_id, conversation_id=cid,
                                                  now=now, first_text=text)
            session["h_fast"] = None
            for item in session.get("wm_items", []):
                item["activation"] = round(item["activation"] * 0.3, 4)
            session["pending_boundary"] = False
            switched = True
        else:
            session["pending_boundary"] = decision == "soft"

    subjects_now = detect_subjects(text)
    episode = await episodes.add_message(db, episode, user_message["_id"], "user", now, e, subjects_now)
    await db.messages.update_one({"_id": user_message["_id"]}, {"$set": {"episode_id": episode["_id"]}})
    subjects = subjects_now | set(episode.get("subjects", []))

    # ---- Fast (episode) and slow (user) state vectors -----------------------------------
    hours = gap_min / 60
    h_fast = _update_state(session.get("h_fast"), e, hours, tau_hours=2.0, gain=0.5) if e else session.get("h_fast")
    slow_prev = (user.get("state") or {}).get("h_slow")
    slow_last = as_utc((user.get("state") or {}).get("h_slow_at"))
    slow_hours = (now - slow_last).total_seconds() / 3600 if slow_last else 0.0
    h_slow = _update_state(slow_prev, e, slow_hours, tau_hours=24 * 14, gain=0.05) if e else slow_prev
    await db.users.update_one({"_id": uid}, {"$set": {"state": {"h_slow": h_slow, "h_slow_at": now}}})
    qvec = combine_vectors([(e, 1.0), (h_fast, 0.3), (h_slow, 0.1)]) or e

    # ---- T1 core profile (cached per session) -----------------------------------------------
    version = int(user.get("memory_version", 0))
    if session.get("profile_version") != version:
        profile_docs = await load_core_profile(db, uid, workspace_id, now)
        session["profile_ids"] = [d["_id"] for d in profile_docs]
        session["profile_version"] = version
    else:
        ids = session.get("profile_ids", [])
        profile_docs = [d for d in await db.memories.find({"_id": {"$in": ids}, "user_id": uid}).to_list(len(ids) or 1)
                        if is_live(d, now)] if ids else []
    profile_scored: list[Scored] = []
    for d in profile_docs:
        sc = score_memory(d, similarity=normalized_similarity(cosine(qvec, d.get("embedding"))), now=now,
                          subjects=subjects, pinned=True)
        if sc:
            profile_scored.append(sc)

    # ---- T4 working-memory items: rescore existing, delta-retrieve new ------------------------
    wm_items = session.get("wm_items", [])
    wm_ids = [i["id"] for i in wm_items]
    wm_docs = {d["_id"]: d for d in await db.memories.find({"_id": {"$in": wm_ids}, "user_id": uid}).to_list(len(wm_ids) or 1)} if wm_ids else {}
    pool: dict[str, tuple[Scored, float]] = {}
    for item in wm_items:
        doc = wm_docs.get(item["id"])
        sc = None
        if doc and is_live(doc, now):
            sc = score_memory(doc, similarity=normalized_similarity(cosine(qvec, doc.get("embedding"))), now=now, subjects=subjects)
            if sc and not passes_gate(sc):
                sc_val = 0.0
            else:
                sc_val = sc.score if sc else 0.0
        else:
            sc_val = 0.0
        activation = item["activation"] if trivial else s.activation_gamma * item["activation"] + (1 - s.activation_gamma) * sc_val
        if sc and activation >= s.activation_evict:
            pool[item["id"]] = (sc, round(activation, 4))
    evicted = [i for i in wm_ids if i not in pool]
    new_items: list[Scored] = []
    if not trivial and qvec:
        exclude = set(pool) | {p.id for p in profile_scored}
        new_items = await retrieve(db, user_id=uid, workspace_id=workspace_id, query_text=text, qvec=qvec,
                                   now=now, exclude_ids=exclude, subjects=subjects)
        for sc in new_items:
            pool[sc.id] = (sc, sc.score)

    kept, overridden = resolve_scope_overrides(profile_scored + [sc for sc, _ in pool.values()])
    kept_ids = {k.id for k in kept}

    # Pack T1 then T4 into their budgets.
    core_items = [BudgetItem(value=p.score, tokens=estimate_tokens(render_line("M00", p.memory)), payload=p)
                  for p in profile_scored if p.id in kept_ids]
    core_chosen, core_tokens = pack(core_items, s.budget_core)
    mem_items = [BudgetItem(value=act, tokens=estimate_tokens(render_line("M00", sc.memory)), payload=sc)
                 for sc, act in pool.values() if sc.id in kept_ids]
    mem_chosen, mem_tokens = pack(mem_items, s.budget_memories, min_value=s.activation_evict)
    session["wm_items"] = [{"id": c.payload.id, "activation": c.value, "tokens": c.tokens} for c in mem_chosen]
    evicted += [sc.id for sc, _ in pool.values() if sc.id not in {c.payload.id for c in mem_chosen} and sc.id in wm_ids]

    used: list[dict[str, Any]] = []
    core_lines, mem_lines = [], []
    for tier, chosen, lines in (("core", core_chosen, core_lines), ("retrieved", mem_chosen, mem_lines)):
        for c in chosen:
            sc: Scored = c.payload
            ref = f"M{len(used) + 1}"
            lines.append(render_line(ref, sc.memory))
            used.append({
                "ref": ref, "id": sc.id, "tier": tier, "type": sc.memory["type"], "content": sc.memory["content"],
                "scope": sc.memory.get("scope", "global"), "confidence": sc.memory.get("confidence"),
                "importance": sc.memory.get("importance"), "score": sc.score, "similarity": round(sc.similarity, 4),
                "strength": sc.strength, "activation": c.value if tier == "retrieved" else None,
                "reasons": sc.reasons, "evidence_message_ids": sc.memory.get("evidence_message_ids", []),
                "confirmation": sc.memory.get("confirmation"), "expires_at": sc.memory.get("expires_at"),
            })
    used_docs = [c.payload.memory for c in core_chosen + mem_chosen]

    # ---- T5 episodic evidence (gated) -----------------------------------------------------
    evidence_lines: list[str] = []
    evidence: list[dict[str, Any]] = []
    need, why = needs_episodic_evidence(text, used_docs) if not trivial else (False, "")
    if need and qvec:
        for ep, sim in await episodes.search_closed(db, uid, workspace_id, qvec, now, limit=2):
            if ep.get("summary") and not str(ep["summary"]).startswith("[summary removed"):
                evidence_lines.append(f"Episode \u201c{sanitize_for_prompt(ep['title'], 60)}\u201d "
                                      f"({as_utc(ep['started_at']):%Y-%m-%d}): {sanitize_for_prompt(ep['summary'], 300)}")
                evidence.append({"kind": "episode", "episode_id": ep["_id"], "title": ep["title"], "score": sim})
                quotes = [q for q in await resolve_evidence(db, uid, ep.get("message_ids", [])[:6], limit=6)
                          if q.get("role") == "user" and not q.get("missing") and not q.get("redacted")][:2]
                for q in quotes:
                    evidence_lines.append(f"  user said: \u201c{sanitize_for_prompt(q['content'], 160)}\u201d")
                    evidence.append({"kind": "message", "message_id": q["message_id"], "conversation_id": q["conversation_id"]})
        for doc in used_docs:
            if float(doc.get("confidence", 1)) < 0.6:
                for q in await resolve_evidence(db, uid, doc.get("evidence_message_ids", []), limit=2):
                    if not q.get("missing") and not q.get("redacted"):
                        evidence_lines.append(f"  evidence for {doc['content'][:40]}: \u201c{sanitize_for_prompt(q['content'], 160)}\u201d")
                        evidence.append({"kind": "message", "message_id": q["message_id"], "conversation_id": q["conversation_id"]})
    evidence_lines, ev_tokens = fit_recent(evidence_lines, s.budget_evidence) if evidence_lines else ([], 0)

    # ---- T2 bridge and T3 current episode ---------------------------------------------------
    bridge = session.get("bridge") if session.get("bridge_turns_left", 0) > 0 else None
    bridge_tokens = min(estimate_tokens(bridge), s.budget_bridge) if bridge else 0
    if bridge and not switched:
        session["bridge_turns_left"] = max(0, int(session.get("bridge_turns_left", 0)) - 1)
        if session["bridge_turns_left"] == 0:
            session["bridge"] = None
    summary = truncate(episode.get("rolling_summary") or "", s.budget_episode_summary * 4)
    recent_docs = await db.messages.find(
        {"conversation_id": cid, "episode_id": episode["_id"], "_id": {"$ne": user_message["_id"]}}
    ).sort("created_at", -1).limit(s.recent_turn_window).to_list(s.recent_turn_window)
    recent_docs.reverse()
    turn_lines = [f"{m['role']}\u0001{m['content']}" for m in recent_docs if not m.get("redacted")]
    kept_lines, recent_tokens = fit_recent(turn_lines, s.budget_recent_turns)
    history = _alternate([{"role": ln.split("\u0001", 1)[0], "content": ln.split("\u0001", 1)[1]} for ln in kept_lines])

    # ---- Render ------------------------------------------------------------------------------
    parts = [f"Current date: {now:%Y-%m-%d}"]
    if core_lines:
        parts += ["[CORE PROFILE]"] + core_lines
    if bridge:
        parts += ["[PREVIOUS EPISODE]", sanitize_for_prompt(bridge, s.budget_bridge * 4)]
    parts += ["[CURRENT EPISODE]", f"Topic: {sanitize_for_prompt(episode.get('title') or '', 80)}"]
    if summary:
        parts.append(f"Earlier in this episode: {sanitize_for_prompt(summary, s.budget_episode_summary * 4)}")
    if mem_lines:
        parts += ["[RELEVANT MEMORIES]"] + mem_lines
    if evidence_lines:
        parts += ["[EVIDENCE FROM PAST CONVERSATIONS]"] + evidence_lines
    system_context = "<memory_context>\n" + "\n".join(parts) + "\n</memory_context>"

    tokens = {
        "core": core_tokens, "bridge": bridge_tokens, "episode": estimate_tokens(summary) + recent_tokens,
        "memories": mem_tokens, "evidence": ev_tokens,
    }
    tokens["total"] = sum(tokens.values())
    tokens["full_history"] = int(conversation.get("total_tokens", 0))

    session["last_turn_at"] = now
    session["h_fast"] = h_fast
    await db.sessions.replace_one({"_id": cid}, session, upsert=True)
    await db.context_logs.insert_one({
        "_id": new_id("ctx"), "user_id": uid, "workspace_id": workspace_id, "conversation_id": cid,
        "message_id": user_message["_id"], "episode_id": episode["_id"], "tokens": tokens,
        "boundary": boundary, "episode_switched": switched, "evicted": evicted,
        "retrieved_new": [sc.id for sc in new_items], "evidence_gate": need, "trivial": trivial, "created_at": now,
    })
    return TurnContext(
        system_context=system_context, history=history, used=used, used_docs=used_docs, overridden=overridden,
        episode={"id": episode["_id"], "title": episode.get("title"), "turns": episode.get("turns"),
                 "switched": switched, "bridge": session.get("bridge") if switched else None,
                 "closed_episode_id": closed_id},
        tokens=tokens, evidence=evidence, evidence_reason=why if need else "", retrieval_backend=backend_label(),
        closed_episode_id=closed_id, trivial=trivial, boundary=boundary,
    )
