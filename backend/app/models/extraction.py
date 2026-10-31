"""Strict, validated schema for the memory extraction agent's structured output.

The LLM only ever sees short references (M1.. for messages, E1.. for existing memories).
Real database IDs are mapped server-side, so the model can never invent or inject IDs."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import get_settings
from app.core.utils import slugify

MEMORY_TYPES = (
    "preference", "interest", "knowledge", "learning_difficulty", "goal", "decision",
    "constraint", "experience", "feedback", "strategy", "fact",
)
MemoryType = Literal[
    "preference", "interest", "knowledge", "learning_difficulty", "goal", "decision",
    "constraint", "experience", "feedback", "strategy", "fact",
]
ENTITY_KINDS = Literal[
    "topic", "skill", "tool", "preference", "goal", "difficulty", "experience", "strategy",
    "constraint", "concept", "decision", "feedback", "fact", "other",
]
_MSG_REF = re.compile(r"^M\d{1,3}$")
_MEM_REF = re.compile(r"^E\d{1,3}$")


def canonical_scope(value: str | None) -> str:
    if not value:
        return "global"
    v = value.strip().lower()
    if v in ("global", "all", "general", ""):
        return "global"
    subject = v.split(":", 1)[1] if ":" in v else v
    subject = subject.strip()
    aliases = get_settings().subject_aliases
    for canonical, words in aliases.items():
        if subject == canonical or subject in words:
            return f"topic:{canonical}"
    return f"topic:{slugify(subject, 40)}"


class EntityRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=60)
    kind: ENTITY_KINDS = "concept"


class MemoryOperation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: Literal["CREATE", "UPDATE", "SUPERSEDE", "MERGE", "DELETE", "REQUEST_CONFIRMATION", "NOOP"]
    type: MemoryType | None = None
    key: str | None = Field(default=None, max_length=64)
    content: str | None = Field(default=None, max_length=300)
    scope: str = "global"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    origin: Literal["explicit", "inferred", "assistant"] = "explicit"
    temporary: bool = False
    expires_in_days: float | None = Field(default=None, gt=0, le=365)
    target_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    entities: list[EntityRef] = Field(default_factory=list, max_length=4)
    requires_confirmation: bool = False
    reason: str = Field(default="", max_length=300)

    @field_validator("key")
    @classmethod
    def _key(cls, v: str | None) -> str | None:
        return slugify(v) if v else v

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: str) -> str:
        return canonical_scope(v)

    @field_validator("target_refs")
    @classmethod
    def _targets(cls, v: list[str]) -> list[str]:
        return [r for r in v if _MEM_REF.match(r)][:5]

    @field_validator("evidence_refs")
    @classmethod
    def _evidence(cls, v: list[str]) -> list[str]:
        return [r for r in v if _MSG_REF.match(r)][:8]

    @field_validator("content")
    @classmethod
    def _content(cls, v: str | None) -> str | None:
        return " ".join(v.split()) if v else v

    @model_validator(mode="after")
    def _check(self) -> "MemoryOperation":
        a = self.action
        if a in ("CREATE", "SUPERSEDE", "REQUEST_CONFIRMATION"):
            if not self.content or not self.type:
                raise ValueError(f"{a} requires content and type")
            if not self.key:
                self.key = slugify(f"{self.type}_{self.content}")[:48]
        if a in ("UPDATE",) and (not self.target_refs or not self.content):
            raise ValueError("UPDATE requires target_refs and content")
        if a == "SUPERSEDE" and not self.target_refs:
            # A supersede without a target is just a create; conflict detection handles it.
            self.action = "CREATE"
        if a == "MERGE" and len(self.target_refs) < 2:
            raise ValueError("MERGE requires at least two target_refs")
        if a == "DELETE" and not (self.target_refs or self.content):
            raise ValueError("DELETE requires target_refs or a content description")
        if self.temporary and self.expires_in_days is None:
            self.expires_in_days = 7.0
        if not self.temporary:
            self.expires_in_days = None
        return self


class ExtractedRelationship(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str = Field(min_length=1, max_length=60)
    relation: str = Field(min_length=1, max_length=40)
    target: str = Field(min_length=1, max_length=60)

    @field_validator("relation")
    @classmethod
    def _rel(cls, v: str) -> str:
        return slugify(v, 40)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    operations: list[MemoryOperation] = Field(default_factory=list, max_length=12)
    relationships: list[ExtractedRelationship] = Field(default_factory=list, max_length=20)
    reasoning_summary: str = Field(default="", max_length=600)


class ExtractionMessage(BaseModel):
    ref: str
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: object | None = None


class ExtractionInput(BaseModel):
    messages: list[ExtractionMessage]
    existing: list[dict] = Field(default_factory=list)  # each has "ref" plus the memory document
    conversation_id: str
    now_iso: str
