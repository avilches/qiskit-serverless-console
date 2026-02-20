"""Time formatting helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def relative_created(value: Any) -> str:
    """Render an ISO timestamp as relative age."""
    raw = str(value or "").strip()
    if not raw:
        return "-"
    try:
        normalized = raw.replace("Z", "+00:00")
        created_dt = datetime.fromisoformat(normalized)
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        delta_seconds = max(
            0, int((datetime.now(timezone.utc) - created_dt).total_seconds())
        )
        if delta_seconds < 60:
            return f"{delta_seconds}s ago"
        if delta_seconds < 3600:
            return f"{delta_seconds // 60} min ago"
        if delta_seconds < 86400:
            return f"{delta_seconds // 3600} hours ago"
        return f"{delta_seconds // 86400} days ago"
    except Exception:  # pylint: disable=broad-exception-caught
        return raw
