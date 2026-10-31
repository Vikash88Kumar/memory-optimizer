"""Guards applied before anything becomes a memory or enters a prompt."""
from __future__ import annotations

import re

_SECRET = [
    re.compile(p, re.I)
    for p in (
        r"\bpass(?:word|code|phrase)\b",
        r"\b(?:api[_ -]?key|secret[_ -]?key|access[_ -]?token|auth[_ -]?token|private[_ -]?key|client[_ -]?secret)\b",
        r"\bsk-[A-Za-z0-9_\-]{16,}",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bgh[pousr]_[A-Za-z0-9]{20,}",
        r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"\b(?:\d[ -]?){13,19}\b",  # card-like digit runs
        r"\b(?:otp|cvv|pin)\s*(?:is|:)\s*\d+",
    )
]
_INJECTION = [
    re.compile(p, re.I)
    for p in (
        r"ignore (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions|rules|messages)",
        r"\bsystem prompt\b",
        r"\byou are now\b",
        r"\bdisregard (?:the|your|all|any)\b",
        r"\bact as (?:an? )?(?:admin|administrator|developer|system|root)\b",
        r"\b(?:always|never) (?:say|respond|reply|answer|reveal)\b",
        r"\bnew instructions?\b",
        r"</?(?:system|assistant|instructions?|memory_context)>",
        r"\boverride (?:your|the) (?:rules|instructions|safety)\b",
    )
]
_HYPOTHETICAL = re.compile(
    r"^\s*(?:if|suppose|supposing|imagine|hypothetically|what if|let'?s say|assume|pretend)\b|\bwould i\b|\bif i were\b",
    re.I,
)


def contains_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET)


def looks_like_injection(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION)


def is_hypothetical(text: str) -> bool:
    return bool(_HYPOTHETICAL.search(text))


def sanitize_for_prompt(text: str, limit: int = 300) -> str:
    """Neutralise markup and collapse whitespace so stored data cannot pose as prompt structure."""
    text = re.sub(r"<[^>]{0,80}>", " ", text)
    text = " ".join(text.split())
    return text[:limit]
