"""Request and response bodies of the activity API."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic_core import PydanticCustomError

from src.auth.schemas import Address, field_errors
from src.organizations.schemas import City, StrictRequest
from src.posts.rules import TAG_LIMIT, TAG_NAME_MAX
from src.validation import (
    StrictBool,
    StrictDecimal,
    StrictInt,
    Uuid7,
    has_letter,
    multi_line,
    single_line,
)

# The same tag rules as posts: they share one catalog per organization.
TagName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=TAG_NAME_MAX),
    AfterValidator(single_line),
]

MAX_CAPACITY = 100_000
MAX_HOURS = 1000

RegistrationStatus = Literal[
    "pending", "approved", "rejected", "waitlisted", "cancelled", "attended"
]


def check_title(value: str) -> str:
    """A title needs a letter or digit, so "..." cannot become an activity."""
    if not any(character.isalnum() for character in value):
        raise PydanticCustomError("title_invalid", "Title needs a letter or a digit")
    return value


Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=200),
    AfterValidator(single_line),
    AfterValidator(check_title),
    AfterValidator(has_letter),
]
ShiftTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    AfterValidator(single_line),
]
ActivityDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
    AfterValidator(multi_line),
]
Location = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    AfterValidator(single_line),
]
Capacity = Annotated[StrictInt, Field(ge=1, le=MAX_CAPACITY)]
Hours = Annotated[StrictDecimal, Field(ge=0, le=MAX_HOURS, decimal_places=2)]
RegistrationNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    AfterValidator(multi_line),
]


class ActivityCreateRequest(StrictRequest):
    """The create form asks for all of these, so the API refuses a body without them."""

    title: Title
    description: ActivityDescription
    location: Location | None = None
    address: Address | None = None
    city: City
    is_remote: StrictBool = False
    start_at: AwareDatetime
    end_at: AwareDatetime
    registration_deadline: AwareDatetime | None = None
    max_participants: Capacity | None = None
    hours_awarded: Hours
    requires_approval: StrictBool = False
    tags: list[TagName] = Field(default_factory=list, max_length=TAG_LIMIT)

    @model_validator(mode="after")
    def need_a_place_unless_remote(self) -> Self:
        if not self.is_remote and self.location is None:
            raise field_errors(
                "ActivityCreateRequest",
                {"location": ("required", "This field cannot be empty")},
            )
        return self


class ActivityUpdateRequest(StrictRequest):
    """Only the fields present in the body change. Null clears an optional field."""

    title: Title | None = None
    description: ActivityDescription | None = None
    location: Location | None = None
    address: Address | None = None
    city: City | None = None
    is_remote: StrictBool | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    registration_deadline: AwareDatetime | None = None
    max_participants: Capacity | None = None
    hours_awarded: Hours | None = None
    requires_approval: StrictBool | None = None
    # Sent tags replace the old list. Leaving them out keeps it.
    tags: list[TagName] | None = Field(default=None, max_length=TAG_LIMIT)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> Self:
        errors: dict[str, tuple[str, str]] = {
            field: ("required", "This field cannot be empty")
            for field in ("title", "is_remote", "requires_approval")
            if field in self.model_fields_set and getattr(self, field) is None
        }
        if errors:
            raise field_errors("ActivityUpdateRequest", errors)
        return self


class ShiftRequest(StrictRequest):
    title: ShiftTitle
    start_at: AwareDatetime
    end_at: AwareDatetime
    capacity: Capacity


class RegisterRequest(StrictRequest):
    # Required when the activity has shifts, and not allowed when it has none.
    shift_id: Uuid7 | None = None
    note: RegistrationNote | None = None


class ReviewRequest(StrictRequest):
    note: RegistrationNote | None = None


class ActivitySummary(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    start_at: datetime | None
    end_at: datetime | None
    registration_deadline: datetime | None
    location: str | None
    city: str | None
    is_remote: bool
    hours_awarded: float | None
    requires_approval: bool
    # None means no limit. Shifts add up when the activity has them.
    capacity: int | None
    seats_taken: int
    organization_name: str
    organization_slug: str
    tags: list[str] = []


class ActivityPage(BaseModel):
    items: list[ActivitySummary]
    next_offset: int | None
    total: int


class ActivityTrashItem(BaseModel):
    """A deleted draft. Only drafts can be deleted, so every item is one."""

    id: uuid.UUID
    title: str
    start_at: datetime | None
    deleted_at: datetime
    purge_at: datetime
    can_purge: bool


class ActivityTrashPage(BaseModel):
    items: list[ActivityTrashItem]
    next_before: uuid.UUID | None


class ShiftResponse(BaseModel):
    id: uuid.UUID
    title: str | None
    start_at: datetime | None
    end_at: datetime | None
    capacity: int | None
    seats_taken: int


class ViewerRegistration(BaseModel):
    id: uuid.UUID
    shift_id: uuid.UUID | None
    status: str
    review_note: str | None
    waitlist_position: int | None


class ActivityViewer(BaseModel):
    """What the caller is to this activity. Empty for anonymous visitors."""

    can_manage: bool = False
    registrations: list[ViewerRegistration] = []


class ActivityDetail(ActivitySummary):
    description: str | None
    address: str | None
    max_participants: int | None
    published_at: datetime | None
    waitlist_count: int
    registration_open: bool
    can_cancel_registration: bool
    shifts: list[ShiftResponse]
    viewer: ActivityViewer


class RegistrationResult(BaseModel):
    id: uuid.UUID
    status: str
    waitlist_position: int | None


class MyRegistration(BaseModel):
    id: uuid.UUID
    status: str
    note: str | None
    review_note: str | None
    registered_at: datetime
    waitlist_position: int | None
    shift_title: str | None
    can_cancel: bool
    # 'verified', 'pending' while a typed code waits for review, or None.
    attendance: str | None
    can_appeal: bool
    appeal_status: str | None
    activity_id: uuid.UUID
    activity_title: str
    activity_status: str
    start_at: datetime | None
    location: str | None
    organization_name: str


class ActivityRegistration(BaseModel):
    """Contact details stay out of this list, as in the member list."""

    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    status: str
    note: str | None
    review_note: str | None
    shift_id: uuid.UUID | None
    shift_title: str | None
    registered_at: datetime


class RegistrationPage(BaseModel):
    items: list[ActivityRegistration]
    next_offset: int | None
    total: int
