"""Configurable LLM providers. All calls go through retries with exponential backoff."""
from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import log


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences or surrounding prose."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


async def post_with_retries(client: httpx.AsyncClient, url: str, *, headers: dict, payload: dict,
                            retries: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = LLMError(f"Provider returned HTTP {resp.status_code}")
            elif resp.status_code >= 400:
                raise LLMError(f"Provider rejected the request: HTTP {resp.status_code} {resp.text[:200]}")
            else:
                return resp.json()
        except httpx.TransportError as exc:
            last_error = exc
        if attempt < retries:
            await asyncio.sleep(0.5 * (2**attempt))
    raise LLMError(f"Provider request failed after {retries + 1} attempts: {last_error}")


class LLMProvider(ABC):
    name: str = "base"
    is_offline: bool = False

    @abstractmethod
    async def complete(self, system: str, messages: list[dict[str, str]], *, model: str | None = None,
                       max_tokens: int = 1024, temperature: float = 0.3, json_mode: bool = False) -> str:
        ...


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds, transport=transport)

    async def complete(self, system, messages, *, model=None, max_tokens=1024, temperature=0.3, json_mode=False):
        if json_mode:
            system = system + "\n\nRespond with a single valid JSON object only. No prose, no code fences."
        payload = {
            "model": model or self.settings.chat_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        }
        headers = {
            "x-api-key": self.settings.anthropic_api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        data = await post_with_retries(self.client, f"{self.settings.anthropic_base_url}/v1/messages",
                                       headers=headers, payload=payload, retries=self.settings.llm_max_retries)
        return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")


class OpenAIProvider(LLMProvider):
    """OpenAI Chat Completions API (also works with OpenAI-compatible endpoints via OPENAI_BASE_URL)."""
    name = "openai"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds, transport=transport)

    async def complete(self, system, messages, *, model=None, max_tokens=1024, temperature=0.3, json_mode=False):
        if json_mode and "json" not in system.lower():
            system = system + "\n\nRespond with a single valid JSON object."
        payload: dict[str, Any] = {
            "model": model or self.settings.chat_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}] + messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}", "content-type": "application/json"}
        data = await post_with_retries(self.client, f"{self.settings.openai_base_url}/chat/completions",
                                       headers=headers, payload=payload, retries=self.settings.llm_max_retries)
        return data["choices"][0]["message"]["content"] or ""


class MockProvider(LLMProvider):
    """OFFLINE FALLBACK for development and tests. It does not generate real answers: it reports
    the question and the personalisation a real model would receive, so the memory pipeline can be
    exercised without credentials. The UI labels responses from this provider as offline."""
    name = "mock"
    is_offline = True

    async def complete(self, system, messages, *, model=None, max_tokens=1024, temperature=0.3, json_mode=False):
        if json_mode:
            raise LLMError("The offline mock provider does not produce structured output")
        question = messages[-1]["content"] if messages else ""
        lines: list[str] = []
        block = re.search(r"<memory_context>(.*?)</memory_context>", system, flags=re.S)
        if block:
            for line in block.group(1).splitlines():
                line = line.strip()
                if re.match(r"^M\d+ ", line):
                    lines.append(line)
        out = [
            "Offline demo model: no LLM provider is configured, so this is not a generated answer.",
            f"Your question: \u201c{question.strip()[:300]}\u201d",
        ]
        if lines:
            out.append("A configured model would personalise the answer with:")
            out.extend(f"\u2022 {line}" for line in lines)
            refs = ", ".join(line.split(" ", 1)[0] for line in lines)
            out.append(f"Personalized using: {refs}")
        else:
            out.append("No stored memories were relevant to this question.")
        return "\n".join(out)


_llm_override: LLMProvider | None = None
_llm_instance: LLMProvider | None = None


def set_llm(provider: LLMProvider | None) -> None:
    global _llm_override
    _llm_override = provider


def get_llm() -> LLMProvider:
    global _llm_instance
    if _llm_override is not None:
        return _llm_override
    if _llm_instance is None:
        settings = get_settings()
        if settings.llm_provider == "anthropic":
            _llm_instance = AnthropicProvider(settings)
        elif settings.llm_provider == "openai":
            _llm_instance = OpenAIProvider(settings)
        else:
            log.warning("LLM_PROVIDER=mock: running with the OFFLINE fallback (no real model answers)")
            _llm_instance = MockProvider()
    return _llm_instance
