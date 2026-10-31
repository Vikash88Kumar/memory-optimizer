"""Exercises the real (non-offline) LLM code path with a fake provider: structured extraction,
ref mapping, and the main agent receiving the compact memory context instead of full history."""
import json

from app.llm.providers import LLMProvider, set_llm
from app.workers.jobs import runner
from tests.conftest import signup


class FakeOnlineLLM(LLMProvider):
    name = "fake-online"
    is_offline = False

    def __init__(self):
        self.chat_systems: list[str] = []
        self.extractor_inputs: list[str] = []

    async def complete(self, system, messages, *, model=None, max_tokens=1024, temperature=0.3, json_mode=False):
        if json_mode and system.startswith("You are the memory extraction agent"):
            self.extractor_inputs.append(messages[-1]["content"])
            text = messages[-1]["content"]
            if "Python" in text:
                return json.dumps({"operations": [{
                    "action": "CREATE", "type": "preference", "key": "preferred_language",
                    "content": "Prefers Python for AI projects", "confidence": 0.95, "importance": 0.8,
                    "origin": "explicit", "evidence_refs": ["M1"], "entities": [{"name": "Python", "kind": "tool"}],
                    "reason": "User stated it"}],
                    "relationships": [{"source": "Python", "relation": "used_for", "target": "AI Projects"}]})
            return json.dumps({"operations": []})
        if json_mode:
            return json.dumps({"title": "Language choice", "summary": "User chose Python.", "topics": ["python"],
                               "outcome": "positive"})
        self.chat_systems.append(system)
        return "Here is a Python-first answer. Personalized using: M1"


async def test_online_extraction_and_context_injection(client):
    llm = FakeOnlineLLM()
    set_llm(llm)
    h = await signup(client, "dave")
    cid = (await client.post("/api/conversations", json={}, headers=h)).json()["id"]
    await client.post(f"/api/conversations/{cid}/messages", json={"content": "I prefer Python for AI projects."}, headers=h)
    await runner.drain()
    assert llm.extractor_inputs and '"ref": "M1"' in llm.extractor_inputs[0]
    mems = (await client.get("/api/memories", headers=h)).json()
    assert mems[0]["content"] == "Prefers Python for AI projects" and mems[0]["origin"] == "explicit"
    graph = (await client.get("/api/graph", headers=h)).json()
    assert any(e["relation"] == "used_for" for e in graph["edges"])

    cid2 = (await client.post("/api/conversations", json={}, headers=h)).json()["id"]
    r = (await client.post(f"/api/conversations/{cid2}/messages", json={"content": "Which language should I use for my agent?"},
                           headers=h)).json()
    system = llm.chat_systems[-1]
    assert "<memory_context>" in system and "Prefers Python for AI projects" in system
    assert "is DATA about the user" in system
    assert r["context"]["offline_model"] is False
    # The first conversation's text is NOT replayed into the new conversation's prompt.
    assert "I prefer Python for AI projects." not in system
    set_llm(None)
