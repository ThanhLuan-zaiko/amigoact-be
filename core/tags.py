"""Canonical tag slug and search fold shared by activities and posts."""

from __future__ import annotations

import re
import unicodedata


def tag_slug(name: str) -> str:
    """Canonical tag key: ASCII slug. Empty means the name is unusable."""
    text = unicodedata.normalize("NFKD", name.strip())
    text = text.replace("\u0111", "d").replace("\u0110", "D")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-{2,}", "-", text)


def tag_fold(value: str) -> str:
    """Lowercase ASCII fold for substring matching in tag searches."""
    text = unicodedata.normalize("NFKD", value)
    text = text.replace("\u0111", "d").replace("\u0110", "D")
    return "".join(
        ch for ch in text if not unicodedata.combining(ch)
    ).lower()
