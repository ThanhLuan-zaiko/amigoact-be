"""URL slugs for organizations, built from the organization name."""

import re
import secrets
import unicodedata

SLUG_MAX_LENGTH = 60
FALLBACK_SLUG = "to-chuc"
# These are fixed paths under /organizations, so no organization may use them.
RESERVED_SLUGS = frozenset({"mine", "new"})
# NFKD does not split the Vietnamese letter d with stroke, so it is mapped by hand.
_STROKED_D = str.maketrans({"\u0111": "d", "\u0110": "D"})
_NOT_SLUG_CHARACTERS = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Turn a name into lowercase ASCII words joined by hyphens."""
    decomposed = unicodedata.normalize("NFKD", name.translate(_STROKED_D))
    ascii_name = decomposed.encode("ascii", "ignore").decode().lower()
    slug = _NOT_SLUG_CHARACTERS.sub("-", ascii_name).strip("-")
    return slug[:SLUG_MAX_LENGTH].strip("-") or FALLBACK_SLUG


def candidate_slug(base: str, attempt: int) -> str:
    """Return the base first, then the base with a random suffix after a collision."""
    if attempt == 0 and base not in RESERVED_SLUGS:
        return base
    return f"{base}-{secrets.token_hex(2)}"
