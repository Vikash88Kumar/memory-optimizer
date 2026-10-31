"""Per-user clock. Demo tools can shift a user's clock forward to show decay and expiry live."""
import datetime as dt
from typing import Any

from app.core.utils import utcnow


def now_for(user: dict[str, Any]) -> dt.datetime:
    offset = float(user.get("clock_offset_seconds") or 0)
    return utcnow() + dt.timedelta(seconds=offset)
