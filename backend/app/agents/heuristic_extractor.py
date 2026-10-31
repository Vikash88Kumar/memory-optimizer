"""OFFLINE FALLBACK extractor used when no LLM is configured (LLM_PROVIDER=mock) and in tests.

It recognises common first-person patterns (preferences, corrections, scopes, difficulties, goals,
interests, temporary events, forget requests) and emits the SAME validated ExtractionResult schema
as the LLM extractor, so the downstream consolidation path is identical. Coverage is intentionally
limited; configure a real LLM for open-ended conversations."""
from __future__ import annotations

import datetime as dt
import re

from app.core.config import get_settings
from app.core.utils import slugify, truncate
from app.memory.safety import is_hypothetical
from app.models.extraction import EntityRef, ExtractionInput, ExtractionResult, MemoryOperation

_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
STYLE_WORDS = {
    "visual": "visual examples", "diagram": "diagrams", "picture": "visual examples", "code-first": "code-first explanations",
    "code first": "code-first explanations", "code": "code examples", "analog": "analogies", "step-by-step": "step-by-step explanations",
    "step by step": "step-by-step explanations", "example": "worked examples", "intuition": "intuitive explanations",
}
LENGTH_WORDS = {
    "short": "short explanations", "brief": "short explanations", "concise": "short explanations",
    "detailed": "detailed explanations", "in-depth": "detailed explanations", "thorough": "detailed explanations",
    "long": "detailed explanations",
}
LANGUAGES = ["python", "java", "javascript", "typescript", "c++", "rust", "go", "kotlin", "swift", "c#"]
ALGO_WORDS = ("algorithm", "algorithms", "data structures", "dsa")
EVENT_WORDS = r"(exam|test|quiz|interview|deadline|presentation|assignment|submission|hackathon|viva|midterm|mid-sem|final)"


def _subject_scope(low: str) -> str | None:
    aliases = get_settings().subject_aliases
    m = re.search(r"\b(?:for|in|with|when it comes to|during)\s+([a-z][a-z+#\- ]{1,30}?)(?:\s+(?:questions|topics|problems|class|classes))?\s*[,.]?\s*(?:$|i\b|,|give|please|explain)", low)
    candidates = [m.group(1).strip()] if m else []
    words = re.findall(r"[a-z]+", low)
    for canonical, alias_list in aliases.items():
        if canonical in words or any(a in words for a in alias_list):
            return canonical
    for c in candidates:
        for canonical, alias_list in aliases.items():
            if c == canonical or c in alias_list:
                return canonical
    return None


def _style_object(low: str) -> tuple[str | None, str | None]:
    for word, label in LENGTH_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            return "explanation_length", label
    for word, label in STYLE_WORDS.items():
        if word in low:
            return "explanation_style", label
    return None, None


def _event_expiry(low: str, now: dt.datetime) -> tuple[float, str]:
    today = now.date()
    target: dt.date | None = None
    m = re.search(r"\bin (\d{1,3}) days?\b", low)
    if "tomorrow" in low:
        target = today + dt.timedelta(days=1)
    elif "today" in low or "tonight" in low:
        target = today
    elif m:
        target = today + dt.timedelta(days=int(m.group(1)))
    elif "next week" in low:
        target = today + dt.timedelta(days=7)
    else:
        for i, day in enumerate(_WEEKDAYS):
            if re.search(rf"\b{day}\b", low):
                delta = (i - today.weekday()) % 7 or 7
                target = today + dt.timedelta(days=delta)
                break
    if target is None:
        return 7.0, ""
    end = dt.datetime.combine(target, dt.time(23, 59, 59), tzinfo=dt.timezone.utc)
    days = max((end - now).total_seconds() / 86400, 0.01)
    return round(days, 4), target.isoformat()


def _op(**kw) -> MemoryOperation:
    return MemoryOperation(**kw)


def heuristic_extract(inp: ExtractionInput) -> ExtractionResult:
    now = dt.datetime.fromisoformat(inp.now_iso)
    ops: list[MemoryOperation] = []
    rels: list[dict] = []
    for msg in inp.messages:
        if msg.role != "user":
            continue
        sentences = [s.strip() for s in _SPLIT.split(msg.content) if s.strip()]
        positive_style_keys = set()
        pending_negations: list[tuple[str, str]] = []
        for sent in sentences:
            low = sent.lower().strip().rstrip(".!")
            ev = [msg.ref]
            if is_hypothetical(low):
                continue

            m = re.match(r"^(?:please\s+|can you\s+|could you\s+)?forget\s+(?:that\s+|about\s+|what\s+i\s+said\s+about\s+)?(.+)$", low)
            if m:
                desc = re.sub(r"^(i\s+|my\s+)", "", m.group(1)).strip()
                ops.append(_op(action="DELETE", content=truncate(desc, 200), evidence_refs=ev,
                               reason="User explicitly asked to forget this"))
                continue
            if sent.endswith("?"):
                continue

            m = re.search(r"\b(?:i\s+)?(?:no longer|don't|do not|stop)\s+(?:want|like|prefer|need|give me|giving me|use)\s+(.+)", low)
            if m:
                key, label = _style_object(m.group(1))
                if key:
                    pending_negations.append((key, label))
                    continue

            key, label = _style_object(low)
            pref = re.search(r"\b(?:i\s+(?:really\s+)?(?:prefer|like|love|enjoy)|give me|i want|i'd like|i would like|i need|"
                             r"i learn (?:best|better) (?:with|through|from)|i understand (?:best|better) (?:with|through|from))\b", low)
            if pref and key:
                subject = _subject_scope(low)
                topic = "algorithms" if any(w in low for w in ALGO_WORDS) else None
                content = f"Prefers {label}" + (f" for {subject}" if subject else "") + (f" when learning {topic}" if topic and not subject else "")
                corrective = bool(re.search(r"\b(no longer|instead|from now on|actually|anymore)\b", msg.content.lower()))
                ents = [EntityRef(name=label, kind="preference")]
                if topic:
                    ents.append(EntityRef(name=topic.title(), kind="topic"))
                ops.append(_op(action="CREATE", type="preference", key=key, content=content,
                               scope=f"topic:{subject}" if subject else "global", confidence=0.95, importance=0.8,
                               origin="explicit", evidence_refs=ev, entities=ents,
                               reason=("Correction of an earlier preference" if corrective else "User stated a preference")))
                positive_style_keys.add(key)
                continue
            if pref:
                lang = next((l for l in LANGUAGES if re.search(rf"(?<![a-z]){re.escape(l)}(?![a-z])", low)), None)
                if lang and re.search(r"\b(prefer|like|love)\b", low):
                    ops.append(_op(action="CREATE", type="preference", key="preferred_language",
                                   content=f"Prefers {lang.title()}" + (" for AI projects" if " ai" in f" {low}" else ""),
                                   confidence=0.9, importance=0.7, evidence_refs=ev,
                                   entities=[EntityRef(name=lang.title(), kind="tool")], reason="User stated a language preference"))
                    continue

            m = (re.search(r"\bi\s+(?:really\s+|still\s+)?(?:struggle|have trouble|have difficulty|am struggling|'m struggling)\s+(?:with\s+)?(.+)", low)
                 or re.search(r"\bi\s+(?:find|found)\s+(.+?)\s+(?:hard|difficult|confusing|tough|tricky)", low)
                 or re.search(r"\bi(?:'m| am)\s+(?:weak|bad|not good)\s+(?:in|at)\s+(.+)", low))
            if m:
                obj = truncate(re.split(r"\s*(?:,| because| since| and the| but)\s*", m.group(1))[0].strip(), 50)
                ops.append(_op(action="CREATE", type="learning_difficulty", key=f"difficulty_{slugify(obj, 30)}",
                               content=f"Struggles with {obj}", confidence=0.9, importance=0.7, evidence_refs=ev,
                               entities=[EntityRef(name=obj.title() if len(obj) < 30 else obj, kind="difficulty")],
                               reason="User described a learning difficulty"))
                continue

            m = re.search(rf"\b(?:i have|i've got|i got|there is|there's|i'm writing|i am writing|i have got)\s+(?:an?\s+|my\s+|the\s+)?(?:[a-z]+\s+)?{EVENT_WORDS}\b(.*)", low)
            if m:
                days, date_iso = _event_expiry(low, now)
                event = m.group(1)
                subject = _subject_scope(low)
                when = f" on {date_iso}" if date_iso else ""
                first = subject or event
                content = f"Has {'an' if first[0] in 'aeiou' else 'a'} {subject + ' ' if subject else ''}{event}{when}"
                ops.append(_op(action="CREATE", type="constraint", key=f"event_{event}_{date_iso or 'soon'}",
                               content=content, confidence=0.9, importance=0.7, temporary=True, expires_in_days=days,
                               evidence_refs=ev, entities=[EntityRef(name=event.title(), kind="constraint")],
                               reason="Time-bound event: stored as a temporary memory"))
                continue

            m = re.search(r"\b(?:i want to|i'd like to|my goal is to|i plan to|i aim to|i hope to)\s+(build|learn|become|crack|master|create|make|get into|work on|land)\s+(.+)", low)
            if m:
                obj = truncate(m.group(2).strip(), 60)
                ops.append(_op(action="CREATE", type="goal", key=f"goal_{slugify(obj, 30)}",
                               content=f"Wants to {m.group(1)} {obj}", confidence=0.9, importance=0.8, evidence_refs=ev,
                               entities=[EntityRef(name=obj.title() if len(obj) < 30 else obj, kind="goal")],
                               reason="User stated a goal"))
                continue

            m = re.search(r"\bi(?:'m| am)\s+(?:currently\s+|now\s+)?(?:learning|studying|interested in|into|getting into)\s+(.+)", low)
            if m:
                obj = truncate(re.split(r"\s*(?:,| these days| right now| and )\s*", m.group(1))[0].strip(), 50)
                ops.append(_op(action="CREATE", type="interest", key=f"interest_{slugify(obj, 30)}",
                               content=f"Is learning {obj}", confidence=0.85, importance=0.6, evidence_refs=ev,
                               entities=[EntityRef(name=obj.upper() if len(obj) <= 4 else obj.title(), kind="topic")],
                               reason="User mentioned what they are learning"))
                continue

            m = re.search(r"\bi(?:'ve| have)?\s+decided\s+to\s+(.+)", low)
            if m:
                obj = truncate(m.group(1), 80)
                ops.append(_op(action="CREATE", type="decision", key=f"decision_{slugify(obj, 30)}",
                               content=f"Decided to {obj}", confidence=0.9, importance=0.7, evidence_refs=ev,
                               reason="User stated a decision"))
                continue

            m = re.search(r"^(.+?)\s+(?:really\s+)?(?:works|worked|helps|helped)\s+(?:well\s+|better\s+)?for me", low)
            if m:
                obj = truncate(m.group(1).strip(), 60)
                ops.append(_op(action="CREATE", type="strategy", key=f"strategy_{slugify(obj, 30)}",
                               content=f"Learns well with {obj}", confidence=0.85, importance=0.75, evidence_refs=ev,
                               reason="User reported what works for them"))
                continue

            m = re.search(r"\bi(?:'ve| have)\s+(?:built|made|created|completed|shipped)\s+(.+)", low)
            if m:
                obj = truncate(m.group(1), 80)
                ops.append(_op(action="CREATE", type="experience", key=f"experience_{slugify(obj, 30)}",
                               content=f"Has built {obj}", confidence=0.85, importance=0.5, evidence_refs=ev,
                               reason="User described past experience"))
                continue

        for key, label in pending_negations:
            if key in positive_style_keys:
                continue  # the positive statement in the same message supersedes the old preference
            ops.append(_op(action="CREATE", type="preference", key=key, content=f"Does not want {label}",
                           confidence=0.9, importance=0.7, evidence_refs=[msg.ref],
                           entities=[EntityRef(name=f"no {label}", kind="preference")],
                           reason="User withdrew an earlier preference"))
    for op in ops:
        if op.action == "CREATE" and op.type == "preference" and "algorithms" in (op.content or "").lower():
            rels.append({"source": next((e.name for e in op.entities if e.kind == "preference"), "Preference"),
                         "relation": "used_for", "target": "Algorithms"})
    return ExtractionResult(operations=ops[:12], relationships=rels[:20],
                            reasoning_summary=f"Offline heuristic extractor produced {len(ops)} operation(s).")
