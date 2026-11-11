"""Request and response bodies of the attendance API."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    Field,
    StringConstraints,
    model_validator,
)

from src.activities.schemas import ShiftTitle
from src.auth.schemas import field_errors
from src.organizations.schemas import StrictRequest
from src.validation import StrictDecimal, StrictInt, Uuid7, multi_line

MIN_SESSION_MINUTES = 5
MAX_SESSION_MINUTES = 24 * 60
DEFAULT_SESSION_MINUTES = 120


def normalize_code(value: object) -> object:
    """People type codes in any case, with stray spaces around them."""
    return value.strip().upper() if isinstance(value, str) else value


Reason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=5, max_length=1000),
    AfterValidator(multi_line),
]
ManualCode = Annotated[
    str, BeforeValidator(normalize_code), Field(pattern=r"^[0-9A-Z]{6}$")
]
QrToken = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{20,64}$")]
Delta = Annotated[StrictDecimal, Field(ge=-1000, le=1000, decimal_places=2)]
Multiplier = Annotated[StrictDecimal, Field(ge=Decimal("0.1"), le=10, decimal_places=3)]
CapHours = Annotated[StrictDecimal, Field(gt=0, le=9999, decimal_places=2)]


class SessionCreateRequest(StrictRequest):
    # Required when the activity has shifts, and not allowed when it has none.
    shift_id: Uuid7 | None = None
    title: ShiftTitle | None = None
    minutes: Annotated[
        StrictInt, Field(ge=MIN_SESSION_MINUTES, le=MAX_SESSION_MINUTES)
    ] = DEFAULT_SESSION_MINUTES


class CheckInRequest(StrictRequest):
    """Send the token from a scanned QR, or the code typed by hand. Never both."""

    token: QrToken | None = None
    code: ManualCode | None = None

    @model_validator(mode="after")
    def require_exactly_one(self) -> Self:
        if (self.token is None) == (self.code is None):
            raise field_errors(
                "CheckInRequest",
                {"code": ("checkin_input_required", "Send a token or a code")},
            )
        return self


class ManualRecordRequest(StrictRequest):
    registration_id: Uuid7


class AppealRequest(StrictRequest):
    reason: Reason


class AppealApproveRequest(StrictRequest):
    # Needed only when the volunteer has several shifts without attendance.
    registration_id: Uuid7 | None = None


class AdjustmentRequest(StrictRequest):
    user_id: Uuid7
    delta_hours: Delta
    reason: Reason

    @model_validator(mode="after")
    def reject_zero(self) -> Self:
        if self.delta_hours == 0:
            raise field_errors(
                "AdjustmentRequest",
                {"delta_hours": ("delta_zero", "The change cannot be zero")},
            )
        return self


class HourRuleRequest(StrictRequest):
    multiplier: Multiplier = Decimal(1)
    cap_hours: CapHours | None = None


class SessionResponse(BaseModel):
    id: uuid.UUID
    title: str | None
    shift_id: uuid.UUID | None
    shift_title: str | None
    is_open: bool
    opens_at: datetime | None
    closes_at: datetime | None
    # Both secrets are left out once the session has closed.
    manual_code: str | None
    qr_token: str | None
    checked_in_count: int
    pending_count: int


class RosterEntry(BaseModel):
    registration_id: uuid.UUID
    full_name: str
    record_id: uuid.UUID | None
    method: str | None
    scanned_at: datetime | None
    verified: bool


class CheckInResult(BaseModel):
    # 'accepted' counts at once. 'pending_review' waits for a manager.
    status: str
    activity_id: uuid.UUID
    activity_title: str
    session_title: str | None


class AppealRegistration(BaseModel):
    registration_id: uuid.UUID
    shift_title: str | None


class AppealResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    reason: str | None
    status: str
    created_at: datetime
    resolved_at: datetime | None
    # What approving would mark as attended.
    registrations: list[AppealRegistration]


class HourEntry(BaseModel):
    id: uuid.UUID
    hours: float
    source: str
    term: str | None
    note: str | None
    recorded_at: datetime
    activity_id: uuid.UUID | None
    activity_title: str | None
    organization_name: str | None


class TermHours(BaseModel):
    term: str
    hours: float


class MyHours(BaseModel):
    total: float
    by_term: list[TermHours]
    entries: list[HourEntry]


class ActivityHoursEntry(BaseModel):
    user_id: uuid.UUID
    full_name: str
    hours: float


class HourRuleResponse(BaseModel):
    multiplier: float
    cap_hours: float | None
