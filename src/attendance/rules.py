"""Business rules for attendance and hours. Pure functions, so they need no database."""

import secrets
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

# No 0/O or 1/I/L, so a code read aloud or from a screen cannot be mistyped.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 6
QR_TOKEN_BYTES = 24
VIETNAM_OFFSET = timedelta(hours=7)
FIRST_HALF_LAST_MONTH = 6
CENT = Decimal("0.01")


def new_manual_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def new_qr_token() -> str:
    return secrets.token_urlsafe(QR_TOKEN_BYTES)


def session_is_open(*, status: str, closes_at: datetime | None, now: datetime) -> bool:
    return status == "open" and closes_at is not None and now < closes_at


def term_of(moment: datetime | None) -> str:
    """Name the half year in Vietnam time, for example '2026-H1'."""
    local = (moment or datetime.now(UTC)).astimezone(UTC) + VIETNAM_OFFSET
    half = 1 if local.month <= FIRST_HALF_LAST_MONTH else 2
    return f"{local.year}-H{half}"


def duration_hours(start_at: datetime | None, end_at: datetime | None) -> Decimal:
    if start_at is None or end_at is None or end_at <= start_at:
        return Decimal("0.00")
    seconds = (end_at - start_at).total_seconds()
    return (Decimal(str(seconds)) / 3600).quantize(CENT, rounding=ROUND_HALF_UP)


def apply_rule(
    base: Decimal,
    *,
    multiplier: Decimal,
    cap: Decimal | None,
    already_in_term: Decimal,
) -> Decimal:
    """Scale the hours, then keep the total inside the organization's cap for the term."""
    scaled = (base * multiplier).quantize(CENT, rounding=ROUND_HALF_UP)
    if cap is None:
        return scaled
    return max(min(scaled, cap - already_in_term), Decimal("0.00"))
