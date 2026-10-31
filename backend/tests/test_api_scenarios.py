"""End-to-end tests of the six required demo scenarios through the HTTP API
(offline mock LLM + heuristic extractor + hash embeddings + local vector fallback)."""
from app.workers.jobs import runner
from tests.conftest import signup


async def _conv(client, h):
    r = await client.post("/api/conversations", json={}, headers=h)
    assert r.status_code == 200
    return r.json()["id"]


async def _say(client, h, cid, text):
    r = await client.post(f"/api/conversations/{cid}/messages", json={"content": text}, headers=h)
    assert r.status_code == 200, r.text
    await runner.drain()  # background extraction finished
    return r.json()


async def _memories(client, h, status="active"):
    r = await client.get(f"/api/memories?status={status}", headers=h)
    assert r.status_code == 200
    return r.json()


async def test_auth_required_and_isolation(client):
    assert (await client.get("/api/memories")).status_code == 401
    h1 = await signup(client, "alice")
    h2 = await signup(client, "bobby")
    cid = await _conv(client, h1)
    await _say(client, h1, cid, "I prefer short explanations.")
    mem = (await _memories(client, h1))[0]
    assert (await client.get(f"/api/memories/{mem['id']}", headers=h2)).status_code == 404
    assert (await client.delete(f"/api/memories/{mem['id']}", headers=h2)).status_code == 404
    assert (await client.get(f"/api/conversations/{cid}/messages", headers=h2)).status_code == 404
    assert (await _memories(client, h2)) == []
    assert (await client.get("/api/memories", headers={**h1, "X-Workspace-Id": "other"})).status_code == 403


async def test_six_demo_scenarios(client, db):
    h = await signup(client)

    # Scenario 1: learning preference is extracted, stored and added to the graph.
    c1 = await _conv(client, h)
    out = await _say(client, h, c1, "I prefer learning algorithms with visual examples.")
    assert out["context"]["extraction_scheduled"] is True
    mems = await _memories(client, h)
    visual = next(m for m in mems if "visual" in m["content"].lower())
    assert visual["type"] == "preference" and visual["evidence_message_ids"] == [out["user_message"]["id"]]
    graph = (await client.get("/api/graph", headers=h)).json()
    assert any(e["relation"] == "prefers" for e in graph["edges"])

    # Scenario 2: a NEW conversation retrieves the preference and shows which memory was used.
    c2 = await _conv(client, h)
    out = await _say(client, h, c2, "Explain binary search.")
    used = out["context"]["memories_used"]
    assert visual["id"] in {u["id"] for u in used}
    assert "visual" in out["assistant_message"]["content"].lower()
    assert all(u["reasons"] for u in used)
    ev = (await client.get(f"/api/memories/{visual['id']}/evidence", headers=h)).json()
    assert ev["evidence"][0]["content"].startswith("I prefer learning algorithms")

    # Scenario 3: correction supersedes the old preference; the next answer follows the new one.
    await _say(client, h, c2, "I no longer want visual explanations. Give me code-first explanations.")
    old = (await client.get(f"/api/memories/{visual['id']}", headers=h)).json()
    assert old["status"] == "superseded"
    active = await _memories(client, h)
    code = next(m for m in active if "code-first" in m["content"])
    assert old["superseded_by"] == code["id"]
    hist = (await client.get(f"/api/memories/{code['id']}/history", headers=h)).json()
    assert any(r["relation"] == "replaced" for r in hist["related"])
    out = await _say(client, h, c2, "Explain quicksort.")
    used_ids = {u["id"] for u in out["context"]["memories_used"]}
    assert code["id"] in used_ids and visual["id"] not in used_ids
    graph = (await client.get("/api/graph", headers=h)).json()
    labels = {n["label"].lower() for n in graph["nodes"]}
    assert "code-first explanations" in labels and "visual examples" not in labels

    # Scenario 4: global and subject-specific preferences coexist; the specific one wins for maths.
    await _say(client, h, c2, "I prefer short explanations.")
    await _say(client, h, c2, "For mathematics, I want detailed explanations.")
    active = await _memories(client, h)
    short = next(m for m in active if m["content"] == "Prefers short explanations")
    detailed = next(m for m in active if "detailed" in m["content"])
    assert detailed["scope"] == "topic:mathematics" and short["status"] == "active"
    c3 = await _conv(client, h)
    out = await _say(client, h, c3, "Explain the chain rule in calculus.")
    used_ids = {u["id"] for u in out["context"]["memories_used"]}
    assert detailed["id"] in used_ids and short["id"] not in used_ids
    assert short["id"] in {o["id"] for o in out["context"]["overridden"]}
    out = await _say(client, h, c3, "Anyway, new topic: explain merge sort.")
    used_ids = {u["id"] for u in out["context"]["memories_used"]}
    assert short["id"] in used_ids and detailed["id"] not in used_ids

    # Scenario 5: temporary memory gets an expiry, a TTL index exists, and expiry removes it from retrieval.
    await _say(client, h, c3, "I have an exam next Monday.")
    exam = next(m for m in await _memories(client, h) if m["type"] == "constraint")
    assert exam["temporary"] is True and exam["expires_at"]
    indexes = await db.memories.index_information()
    assert any(v.get("key") == [("expires_at", 1)] and "expireAfterSeconds" in v for v in indexes.values())
    out = await _say(client, h, c3, "What should I study today?")
    assert exam["id"] in {u["id"] for u in out["context"]["memories_used"]}
    clock = (await client.post("/api/demo/clock", json={"advance_days": 10}, headers=h)).json()
    assert clock["expired"] == 1
    out = await _say(client, h, c3, "What should I study today?")
    assert exam["id"] not in {u["id"] for u in out["context"]["memories_used"]}
    assert exam["id"] in {m["id"] for m in await _memories(client, h, "expired")}
    await client.post("/api/demo/clock", json={"reset": True}, headers=h)

    # Scenario 6: forgetting removes the memory, its graph links, and it is never retrieved again.
    await _say(client, h, c3, "I struggle with recursion.")
    rec = next(m for m in await _memories(client, h) if "recursion" in m["content"].lower())
    await _say(client, h, c3, "Forget that I struggle with recursion.")
    assert not any("recursion" in m["content"].lower() for m in await _memories(client, h))
    deleted = (await client.get(f"/api/memories/{rec['id']}", headers=h)).json()
    assert deleted["status"] == "deleted" and deleted["content"] == "[forgotten]"
    graph = (await client.get("/api/graph?include_superseded=true", headers=h)).json()
    assert not any("recursion" in n["label"].lower() for n in graph["nodes"])
    c4 = await _conv(client, h)
    out = await _say(client, h, c4, "Can you explain recursion?")
    assert rec["id"] not in {u["id"] for u in out["context"]["memories_used"]}

    # The activity timeline recorded every kind of operation with a reason.
    events = (await client.get("/api/activity?limit=500", headers=h)).json()
    actions = {e["action"] for e in events}
    assert {"created", "superseded", "expired", "deleted", "retrieved"} <= actions
    assert all(e["reason"] for e in events)
    logs = (await client.get(f"/api/context-logs?conversation_id={c3}", headers=h)).json()
    assert logs and all("total" in log["tokens"] for log in logs)


async def test_explorer_edit_confirm_delete(client):
    h = await signup(client, "carol")
    cid = await _conv(client, h)
    await _say(client, h, cid, "I want to build AI agents.")
    mem = (await _memories(client, h))[0]
    r = await client.patch(f"/api/memories/{mem['id']}", json={"content": "Wants to build autonomous AI agents"}, headers=h)
    assert r.status_code == 200 and r.json()["confirmation"] == "confirmed"
    assert (await client.patch(f"/api/memories/{mem['id']}", json={"content": "my password is hunter22"}, headers=h)).status_code == 422
    r = await client.post(f"/api/memories/{mem['id']}/confirm", json={"accept": True}, headers=h)
    assert r.json()["confidence"] >= 0.95
    r = await client.delete(f"/api/memories/{mem['id']}", headers=h)
    assert r.json()["forgotten"] == [mem["id"]]
    status = (await client.get("/api/system/status", headers=h)).json()
    assert status["retrieval_backend"] == "local_fallback" and status["llm_offline"] is True


async def test_demo_account_seed_and_reset(client, db):
    from app.demo.seed import ensure_demo_user
    from app.llm.embeddings import get_embedder

    await ensure_demo_user(db, get_embedder())
    r = await client.post("/api/auth/login", json={"username": "demo", "password": "memora-demo"})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    mems = await _memories(client, h)
    assert {m["type"] for m in mems} == {"interest", "goal", "learning_difficulty"} and all(m["seed"] for m in mems)
    graph = (await client.get("/api/graph", headers=h)).json()
    assert any(e["relation"] == "related_to" for e in graph["edges"])
    assert await db.episodes.count_documents({"status": "closed"}) == 1
    cid = await _conv(client, h)
    await _say(client, h, cid, "I prefer short explanations.")
    assert len(await _memories(client, h)) == 4
    assert (await client.post("/api/demo/reset", headers=h)).json() == {"reset": True}
    assert len(await _memories(client, h)) == 3
    h2 = await signup(client, "notdemo")
    assert (await client.post("/api/demo/reset", headers=h2)).status_code == 403
