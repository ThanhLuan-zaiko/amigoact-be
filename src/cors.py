"""Which browser origins may talk to the API, read from `CORS_ORIGINS` in `.env`.

The value is a comma-separated list of exact origins, such as
`http://localhost:3000,https://amigoact.example`. Empty means no origin is
allowed, which is the strictest choice. A wildcard is refused, because the API
carries user data.

The list drives two things:
- CORS headers on HTTP responses (FastAPI's CORSMiddleware).
- The chat socket, which refuses a browser whose Origin is not on the list.
  CORS does not cover WebSockets, so the socket checks it itself.
"""

import re
from functools import lru_cache

from pydantic import field_validator

from src.config import DotenvSettings

# scheme://host[:port], no path, no trailing slash.
_ORIGIN = re.compile(r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$")


def parse_origins(text: str) -> list[str]:
    """Split, trim, and check every origin. Raises ValueError on a bad entry."""
    origins = [part.strip() for part in text.split(",") if part.strip()]
    for origin in origins:
        if not _ORIGIN.fullmatch(origin):
            raise ValueError(f"CORS_ORIGINS has an invalid origin: {origin!r}")
    return origins


class CorsSettings(DotenvSettings):
    cors_origins: str = ""

    @field_validator("cors_origins")
    @classmethod
    def _valid_origins(cls, value: str) -> str:
        parse_origins(value)
        return value

    @property
    def origins(self) -> list[str]:
        return parse_origins(self.cors_origins)


@lru_cache
def get_cors_settings() -> CorsSettings:
    return CorsSettings()


def origin_allowed(origin: str | None, allowed: list[str]) -> bool:
    """A request without Origin is not from a browser page, so it passes here.

    Such callers still need a ticket (socket) or the internal key (HTTP).
    """
    return origin is None or origin in allowed
