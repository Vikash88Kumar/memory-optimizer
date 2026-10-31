import datetime as dt

import pytest
from pydantic import ValidationError

from app.agents.heuristic_extractor import heuristic_extract
from app.agents.memory_extractor import run_extractor, should_extract
from app.core.utils import utcnow
from app.llm.providers import LLMProvider
from app.models.extraction import ExtractionInput, ExtractionMessage, ExtractionResult, MemoryOperation


def _inp(*texts, now=None):
    now = now or utcnow()
    msgs = [ExtractionMessage(ref=f"M{i + 1}", id=f"msg_{i}", role="user", content=t, created_at=now) for i, t in enumerate(texts)]
    return ExtractionInput(messages=msgs, existing=[], conversation_id="conv_1", now_iso=now.isoformat())


def test_schema_validation_rules():
    with pytest.raises(ValidationError):
        MemoryOperation(action="CREATE", content="x")  # missing type
    with pytest.raises(ValidationError):
        MemoryOperation(action="MERGE", target_refs=["E1"])
    op = MemoryOperation(action="CREATE", type="preference", content="Prefers maths detail", scope="maths",
                         target_refs=["E1", "mem_123", "E2; drop"], evidence_refs=["M1", "msg_999"])
    assert op.scope == "topic:mathematics"
    assert op.target_refs == ["E1"] and op.evidence_refs == ["M1"]  # invented ids are discarded
    temp = MemoryOperation(action="CREATE", type="constraint", content="Exam soon", temporary=True)
    assert temp.expires_in_days == 7.0


def test_should_extract_gate():
    assert should_extract("I prefer learning algorithms with visual examples.")
    assert should_extract("I struggle with recursion.") and should_extract("Recursion confuses me, I think")
    assert not should_extract("Explain binary search.")
    assert not should_extract("ok")


def test_heuristic_preference_correction_scope_temporary_forget():
    now = dt.datetime(2026, 10, 31, 12, tzinfo=dt.timezone.utc)  # a Saturday
    r = heuristic_extract(_inp("I prefer learning algorithms with visual examples.", now=now))
    op = r.operations[0]
    assert op.type == "preference" and op.key == "explanation_style" and "visual" in op.content.lower()

    r = heuristic_extract(_inp("I no longer want visual explanations. Give me code-first explanations.", now=now))
    assert len(r.operations) == 1 and "code-first" in r.operations[0].content

    r = heuristic_extract(_inp("For mathematics, I want detailed explanations.", now=now))
    assert r.operations[0].scope == "topic:mathematics" and r.operations[0].key == "explanation_length"

    r = heuristic_extract(_inp("I have an exam next Monday.", now=now))
    op = r.operations[0]
    assert op.temporary and op.type == "constraint" and "2026-11-02" in op.content
    assert 2 < op.expires_in_days < 3

    r = heuristic_extract(_inp("Forget that I struggle with recursion.", now=now))
    assert r.operations[0].action == "DELETE" and "recursion" in r.operations[0].content

    assert heuristic_extract(_inp("If I were a teacher I would prefer slides.")).operations == []
    assert heuristic_extract(_inp("Explain binary search.")).operations == []


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    async def complete(self, system, messages, **kw):
        self.calls += 1
        return self.outputs.pop(0)


async def test_llm_extractor_repairs_invalid_output_once():
    good = '{"operations":[{"action":"CREATE","type":"goal","content":"Wants to build AI agents","evidence_refs":["M1"]}]}'
    llm = ScriptedLLM(['{"operations": [{"action": "CREATE"}]}', "```json\n" + good + "\n```"])
    result = await run_extractor(_inp("I want to build AI agents"), llm)
    assert llm.calls == 2 and result.operations[0].type == "goal"


async def test_llm_extractor_gives_up_after_two_invalid_outputs():
    from app.agents.memory_extractor import ExtractionError
    llm = ScriptedLLM(["not json", '{"operations": [{"action": "MERGE"}]}'])
    with pytest.raises(ExtractionError):
        await run_extractor(_inp("I want to build AI agents"), llm)
