"""Token budgeting for the working memory controller."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from app.core.utils import estimate_tokens

T = TypeVar("T")


@dataclass
class BudgetItem(Generic[T]):
    value: float
    tokens: int
    payload: T


def pack(items: list[BudgetItem[Any]], budget: int, min_value: float = 0.0) -> tuple[list[BudgetItem[Any]], int]:
    """Greedy knapsack by value per token. Never fills the budget with low-value items."""
    eligible = [i for i in items if i.value >= min_value and i.tokens > 0]
    eligible.sort(key=lambda i: i.value / i.tokens, reverse=True)
    chosen, used = [], 0
    for item in eligible:
        if used + item.tokens <= budget:
            chosen.append(item)
            used += item.tokens
    chosen.sort(key=lambda i: i.value, reverse=True)
    return chosen, used


def fit_recent(lines: list[str], budget: int) -> tuple[list[str], int]:
    """Keep the most recent lines that fit (lines are oldest-first)."""
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        t = estimate_tokens(line)
        if used + t > budget:
            break
        kept.append(line)
        used += t
    kept.reverse()
    return kept, used
