"""Time-aware memory strength - an SSM-inspired, continuous-time linear recurrence.

    ds/dt = -lambda * s + beta * u(t)      (u = reinforcement impulse when a memory is used)
    s_k   = exp(-lambda * dt_k) * s_{k-1} + beta * (1 - s_{k-1}) * u_k

alpha_k = exp(-lambda * dt_k) depends on the real time elapsed (zero-order-hold discretisation),
not on the number of steps. lambda is *selective*: it depends on memory type and importance.
Strength is evaluated lazily at read time from (strength, last_reinforced_at), so no background
job has to touch every memory."""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

from app.core.utils import as_utc

# Base half-lives in days. None = does not decay (stable facts).
HALF_LIFE_DAYS: dict[str, float | None] = {
    "preference": 120, "interest": 60, "knowledge": 180, "learning_difficulty": 45, "goal": 60,
    "decision": 90, "constraint": 5, "experience": 90, "feedback": 21, "strategy": 90, "fact": None,
}
EPISODE_HALF_LIFE_DAYS = 7.0
REINFORCE_BETA = 0.25


def decay_lambda(memory_type: str, importance: float) -> float:
    half_life = HALF_LIFE_DAYS.get(memory_type, 60)
    if half_life is None:
        return 0.0
    half_life *= 0.5 + max(0.0, min(1.0, importance))  # important memories fade more slowly
    return math.log(2) / half_life


def initial_strength(importance: float) -> float:
    return round(max(0.3, min(1.0, importance)), 4)


def strength_at(doc: dict[str, Any], now: dt.datetime) -> float:
    strength = float(doc.get("strength", 1.0))
    lam = float(doc.get("decay_lambda", 0.0))
    last = as_utc(doc.get("last_reinforced_at") or doc.get("created_at"))
    if last is None or lam == 0:
        return strength
    days = max(0.0, (now - last).total_seconds() / 86400)
    return strength * math.exp(-lam * days)


def reinforced(doc: dict[str, Any], now: dt.datetime, beta: float = REINFORCE_BETA) -> float:
    s = strength_at(doc, now)
    return round(s + beta * (1.0 - s), 4)
