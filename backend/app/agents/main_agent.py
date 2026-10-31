"""Main conversational agent: answers using the compact working-memory context, never the full history."""
from __future__ import annotations

from app.agents.prompts import CHAT_SYSTEM_PROMPT
from app.core.config import get_settings
from app.llm.providers import LLMProvider
from app.memory.working_memory import TurnContext


async def generate_reply(llm: LLMProvider, ctx: TurnContext, user_text: str) -> str:
    settings = get_settings()
    system = f"{CHAT_SYSTEM_PROMPT}\n\n{ctx.system_context}"
    messages = ctx.history + [{"role": "user", "content": user_text}]
    return await llm.complete(system, messages, model=settings.chat_model, max_tokens=settings.chat_max_tokens,
                              temperature=0.4)
