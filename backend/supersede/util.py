"""Small shared helpers."""

from __future__ import annotations

import difflib
import re
import uuid
from datetime import date, datetime, timezone

_WORD = re.compile(r"[a-z0-9]+")


def new_id(prefix: str) -> str:
    """Short readable unique id, for example ``run_3f9a1c2b``."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_day(value: str | None) -> date | None:
    """Parse ``YYYY-MM-DD`` (or a full ISO timestamp) into a date."""
    if not value:
        return None
    return date.fromisoformat(value[:10])


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def similarity(a: str, b: str) -> float:
    """0..1 text similarity, used to decide whether a claim changed."""
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def rough_token_count(text: str) -> int:
    """Approximate token count for the mock client (about 4 characters per token)."""
    return max(1, len(text) // 4)
