"""Summarise context_logs for the presentation: memory-context tokens vs. the full conversation.

    python scripts/context_report.py <conversation_id>
Only reports what was actually logged by the running system."""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.chdir(ROOT)

from app.core.config import get_settings  # noqa: E402
from app.database import mongo  # noqa: E402


async def main(conversation_id: str) -> None:
    db = await mongo.connect(get_settings())
    logs = await db.context_logs.find({"conversation_id": conversation_id}).sort("created_at", 1).to_list(None)
    if not logs:
        print("No context logs for that conversation.")
        return
    print(f"{'turn':>4} {'memory ctx':>10} {'full history':>12} {'switch':>6}")
    for i, log in enumerate(logs, 1):
        t = log["tokens"]
        print(f"{i:>4} {t['total']:>10} {t['full_history']:>12} {'yes' if log.get('episode_switched') else '':>6}")
    last = logs[-1]["tokens"]
    print(f"\nLast turn: {last['total']} tokens of memory context vs {last['full_history']} tokens of conversation history.")
    await mongo.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
