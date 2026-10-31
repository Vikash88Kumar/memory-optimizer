"""Memory extraction agent: turns a slice of conversation into validated memory operations."""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from pydantic import ValidationError

from app.agents.heuristic_extractor import heuristic_extract
from app.agents.prompts import EXTRACTOR_SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.utils import truncate
from app.llm.embeddings import Embedder
from app.llm.providers import LLMError, LLMProvider, extract_json
from app.memory.retrieval import vector_candidates
from app.memory.safety import sanitize_for_prompt
from app.models.extraction import ExtractionInput, ExtractionMessage, ExtractionResult

_CUE = re.compile(
    r"\b(?:prefer|like|love|hate|enjoy|want|need|struggl|find\b.*\b(?:hard|difficult|confusing)|learning|studying|goal|"
    r"plan|exam|test|quiz|deadline|interview|forget|remember|no longer|anymore|instead|actually|from now on|decided|"
    r"working on|built|weak|good at|bad at|confus|helped|worked for me|my name|i am a|i'm a)",
    re.I,
)
_FIRST_PERSON = re.compile(r"\b(i|i'm|i've|i'd|my|me|mine)\b", re.I)


class ExtractionError(RuntimeError):
    pass


def should_extract(text: str) -> bool:
    """Cheap gate so the extraction LLM is not called for messages with nothing to remember."""
    if len(text.strip()) < 6:
        return False
    return bool(_FIRST_PERSON.search(text) and _CUE.search(text))


async def build_extraction_input(db: Any, *, user_id: str, workspace_id: str, conversation_id: str,
                                 message_ids: list[str], now: dt.datetime, embedder: Embedder) -> ExtractionInput:
    pending = await db.messages.find({"_id": {"$in": message_ids}, "user_id": user_id}).sort("created_at", 1).to_list(50)
    if not pending:
        return ExtractionInput(messages=[], existing=[], conversation_id=conversation_id, now_iso=now.isoformat())
    start = pending[0]["created_at"]
    window = await db.messages.find(
        {"conversation_id": conversation_id, "user_id": user_id, "created_at": {"$gte": start}}
    ).sort("created_at", 1).to_list(40)
    pending_ids = {m["_id"] for m in pending}
    messages = []
    for m in window:
        if m.get("redacted"):
            continue
        if m["role"] == "user" and m["_id"] not in pending_ids:
            continue
        messages.append(ExtractionMessage(ref=f"M{len(messages) + 1}", id=m["_id"], role=m["role"],
                                          content=truncate(m["content"], 1200), created_at=m["created_at"]))
    user_text = " ".join(m.content for m in messages if m.role == "user")
    qvec = await embedder.embed_one(user_text, "query")
    similar = [d for d, _ in await vector_candidates(db, "memories", qvec, user_id, workspace_id, limit=12)]
    slots = await db.memories.find(
        {"user_id": user_id, "workspace_id": workspace_id, "status": "active",
         "type": {"$in": ["preference", "constraint", "goal", "learning_difficulty"]}}
    ).sort("updated_at", -1).to_list(20)
    existing: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in similar + slots:
        if d["_id"] in seen:
            continue
        seen.add(d["_id"])
        existing.append({"ref": f"E{len(existing) + 1}", **d})
    return ExtractionInput(messages=messages, existing=existing, conversation_id=conversation_id, now_iso=now.isoformat())


def _render_input(inp: ExtractionInput) -> str:
    existing = [
        {"ref": e["ref"], "type": e["type"], "key": e.get("key"), "scope": e.get("scope"),
         "content": sanitize_for_prompt(e["content"], 200), "temporary": bool(e.get("temporary"))}
        for e in inp.existing
    ]
    msgs = [{"ref": m.ref, "role": m.role, "content": sanitize_for_prompt(m.content, 1200)} for m in inp.messages]
    return (f"Current date and time (UTC): {inp.now_iso}\n\n"
            f"EXISTING MEMORIES (data):\n{json.dumps(existing, ensure_ascii=False)}\n\n"
            f"CONVERSATION SLICE (data):\n{json.dumps(msgs, ensure_ascii=False)}\n\n"
            "Return the JSON object now.")


async def run_extractor(inp: ExtractionInput, llm: LLMProvider) -> ExtractionResult:
    if not inp.messages:
        return ExtractionResult()
    if llm.is_offline:
        return heuristic_extract(inp)
    settings = get_settings()
    prompt = _render_input(inp)
    messages = [{"role": "user", "content": prompt}]
    last_error: Exception | None = None
    for attempt in range(2):
        raw = await llm.complete(EXTRACTOR_SYSTEM_PROMPT, messages, model=settings.extractor_model,
                                 max_tokens=1500, temperature=0.0, json_mode=True)
        try:
            return ExtractionResult.model_validate(extract_json(raw))
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            messages = messages + [
                {"role": "assistant", "content": raw[:4000]},
                {"role": "user", "content": f"That output was invalid: {str(exc)[:600]}. Return a corrected JSON object only."},
            ]
    raise ExtractionError(f"Extractor output failed validation twice: {last_error}")


__all__ = ["should_extract", "build_extraction_input", "run_extractor", "ExtractionError", "LLMError"]
