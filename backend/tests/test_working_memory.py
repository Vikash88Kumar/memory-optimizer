import datetime as dt

from app.core.config import get_settings
from app.core.utils import new_id, utcnow
from app.llm.embeddings import HashEmbedder
from app.memory import episodes, lifecycle
from app.memory.working_memory import build_turn_context, is_trivial
from app.services.chat_service import store_message


async def _conv(db, user):
    conv = {"_id": new_id("conv"), "user_id": user["_id"], "workspace_id": "default", "title": "t", "total_tokens": 0,
            "message_count": 0, "created_at": utcnow(), "updated_at": utcnow()}
    await db.conversations.insert_one(conv)
    return conv


async def _turn(db, user, conv, text, now, embedder):
    emb = await embedder.embed_one(text, "query")
    msg = await store_message(db, user=user, workspace_id="default", conversation_id=conv["_id"], role="user",
                              content=text, now=now, embedding=emb)
    conv = await db.conversations.find_one({"_id": conv["_id"]})
    user = await db.users.find_one({"_id": user["_id"]})
    ctx = await build_turn_context(db, user=user, workspace_id="default", conversation=conv, user_message=msg, now=now)
    await store_message(db, user=user, workspace_id="default", conversation_id=conv["_id"], role="assistant",
                        content=f"answer to {text}", now=now, extra={"episode_id": ctx.episode["id"]})
    ep = await db.episodes.find_one({"_id": ctx.episode["id"]})
    return ctx


def test_trivial_detection():
    assert is_trivial("thanks!") and is_trivial("ok") and not is_trivial("ok so what is recursion?")


def test_boundary_score_components():
    s = get_settings()
    score, parts = episodes.boundary_score([1.0, 0.0], [0.0, 1.0], 45, "anyway, new topic", s)
    assert parts == {"topic_shift": 1.0, "time_gap": 1.0, "cue": 1.0} and score == 1.0
    ep = {"turns": 1}
    assert episodes.boundary_decision(0.9, ep, False, s) == "stay"  # minimum episode length
    ep = {"turns": 3}
    assert episodes.boundary_decision(0.9, ep, False, s) == "switch"
    assert episodes.boundary_decision(0.45, ep, False, s) == "soft"
    assert episodes.boundary_decision(0.45, ep, True, s) == "switch"  # confirmed soft boundary
    assert episodes.boundary_decision(0.2, {"turns": 1}, False, s, explicit_cue=True) == "switch"


async def test_core_profile_budget_and_episode_switch(db, user, embedder):
    now = utcnow()
    await lifecycle.remember(db, user=user, workspace_id="default", mtype="preference", key="explanation_style",
                             content="Prefers code-first explanations", scope="global", confidence=0.95, importance=0.8,
                             origin="explicit", temporary=False, expires_at=None, evidence_ids=[], conversation_id=None,
                             entities=[], requires_confirmation=False, now=now, embedder=embedder, reason="t")
    await lifecycle.remember(db, user=user, workspace_id="default", mtype="learning_difficulty", key="difficulty_recursion",
                             content="Struggles with recursion and the call stack", scope="global", confidence=0.9,
                             importance=0.7, origin="explicit", temporary=False, expires_at=None, evidence_ids=[],
                             conversation_id=None, entities=[], requires_confirmation=False, now=now, embedder=embedder,
                             reason="t")
    conv = await _conv(db, user)
    t = now
    ctx = await _turn(db, user, conv, "Can you explain recursion with the call stack?", t, embedder)
    kinds = {u["tier"]: u for u in ctx.used}
    assert kinds["core"]["content"] == "Prefers code-first explanations"
    assert any("recursion" in u["content"].lower() for u in ctx.used if u["tier"] == "retrieved")
    assert "<memory_context>" in ctx.system_context and "[CORE PROFILE]" in ctx.system_context
    assert ctx.tokens["total"] <= sum([get_settings().budget_core, get_settings().budget_bridge,
                                       get_settings().budget_episode_summary, get_settings().budget_recent_turns,
                                       get_settings().budget_memories, get_settings().budget_evidence])
    first_episode = ctx.episode["id"]
    t += dt.timedelta(minutes=1)
    ctx = await _turn(db, user, conv, "So recursion uses the call stack frames for each call?", t, embedder)
    assert ctx.episode["id"] == first_episode and not ctx.episode["switched"]
    t += dt.timedelta(minutes=50)
    ctx = await _turn(db, user, conv, "Anyway, new topic: help me plan my exam week schedule", t, embedder)
    assert ctx.episode["switched"] and ctx.episode["id"] != first_episode
    assert ctx.closed_episode_id == first_episode and "Previous episode" in (ctx.episode["bridge"] or "")
    assert "[PREVIOUS EPISODE]" in ctx.system_context
    # Only this episode's turns are sent verbatim: none of the recursion turns.
    assert all("recursion" not in h["content"].lower() for h in ctx.history)
    log = await db.context_logs.find_one({"message_id": {"$exists": True}, "episode_switched": True})
    assert log and log["boundary"]["decision"] == "switch"


async def test_closed_episode_retrieved_by_gate(db, user, embedder):
    from app.llm.providers import MockProvider

    now = utcnow()
    conv = await _conv(db, user)
    ctx = await _turn(db, user, conv, "I got 3 out of 10 on my recursion quiz and base cases confused me", now, embedder)
    await _turn(db, user, conv, "The recursion base case part was the hardest", now + dt.timedelta(minutes=1), embedder)
    ep_id = ctx.episode["id"]
    await episodes.close_episode(db, ep_id, now + dt.timedelta(minutes=2), MockProvider(), embedder)
    conv2 = await _conv(db, user)
    ctx2 = await _turn(db, user, conv2, "Back to recursion: what did I get wrong last time on the quiz?",
                       now + dt.timedelta(hours=1), embedder)
    assert ctx2.evidence_reason and any(e["kind"] == "episode" and e["episode_id"] == ep_id for e in ctx2.evidence)
    assert "[EVIDENCE FROM PAST CONVERSATIONS]" in ctx2.system_context


async def test_activation_decay_evicts_stale_items(db, user, embedder):
    now = utcnow()
    await lifecycle.remember(db, user=user, workspace_id="default", mtype="interest", key="interest_graphs",
                             content="Is learning graph algorithms like Dijkstra", scope="global", confidence=0.9,
                             importance=0.5, origin="explicit", temporary=False, expires_at=None, evidence_ids=[],
                             conversation_id=None, entities=[], requires_confirmation=False, now=now, embedder=embedder,
                             reason="t")
    conv = await _conv(db, user)
    ctx = await _turn(db, user, conv, "Explain Dijkstra graph algorithms", now, embedder)
    assert any("Dijkstra" in u["content"] for u in ctx.used)
    t = now
    activations = []
    for q in ["What is a hash map?", "How do hash map collisions work?", "Hash map load factor?",
              "Hash map resizing cost?", "Hash map vs tree map?"]:
        t += dt.timedelta(minutes=1)
        ctx = await _turn(db, user, conv, q, t, embedder)
        activations += [u["activation"] for u in ctx.used if "Dijkstra" in u["content"]]
    assert activations == sorted(activations, reverse=True)  # decays every off-topic turn
    assert not any("Dijkstra" in u["content"] for u in ctx.used)  # ...until evicted from working memory
