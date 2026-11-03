"""Request and response bodies of the organization API."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic_core import PydanticCustomError

from src.auth.schemas import Address, Phone, ShortText, TaxCode, field_errors
from src.organizations.gallery_items import MAX_GALLERY_ITEMS
from src.validation import Uuid7, multi_line, single_line

OrgRole = Literal["owner", "admin", "member"]
OrgType = Literal["organization", "club", "group", "business"]
JoinPolicy = Literal["open", "invite"]


def normalize_website(value: str) -> str:
    """Accept only public http(s) URLs, because clients render this value as a link.

    Credentials are rejected too, since they can disguise where a link really goes.
    """
    compact = value.strip()
    invalid = PydanticCustomError("website_invalid", "Website must be an http(s) URL")
    try:
        parts = urlsplit(compact)
        host = parts.hostname
    except ValueError as exc:
        raise invalid from exc
    if (
        parts.scheme not in ("http", "https")
        or not host
        or "." not in host
        or parts.username
        or parts.password
        or any(character.isspace() for character in compact)
    ):
        raise invalid
    return compact


def check_organization_name(value: str) -> str:
    """A name needs a letter or digit, so "!!!" cannot become an organization."""
    if not any(character.isalnum() for character in value):
        raise PydanticCustomError(
            "organization_name_invalid", "Name needs a letter or a digit"
        )
    return value


OrganizationName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=120),
    AfterValidator(single_line),
    AfterValidator(check_organization_name),
]
Description = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
    AfterValidator(multi_line),
]
City = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    AfterValidator(single_line),
]
Website = Annotated[str, Field(max_length=300), AfterValidator(normalize_website)]
ApplicationMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
    AfterValidator(multi_line),
]


class StrictRequest(BaseModel):
    """Unknown fields are errors, so owner_id or slug cannot be sent by mistake."""

    model_config = ConfigDict(extra="forbid")


class OrganizationCreateRequest(StrictRequest):
    """Pictures and gallery files are uploads from POST /media, sent by their asset id."""

    name: OrganizationName
    description: Description
    org_type: OrgType = "organization"
    join_policy: JoinPolicy = "invite"
    email: EmailStr
    phone: Phone
    website: Website | None = None
    address: Address | None = None
    city: City
    legal_name: ShortText | None = None
    tax_code: TaxCode | None = None
    license_number: ShortText | None = None
    legal_rep_name: ShortText | None = None
    legal_rep_position: ShortText | None = None
    logo_asset_id: Uuid7 | None = None
    cover_asset_id: Uuid7 | None = None
    gallery_asset_ids: list[Uuid7] = Field(
        default_factory=list, max_length=MAX_GALLERY_ITEMS
    )


class OrganizationUpdateRequest(StrictRequest):
    """Only the fields present in the body change. Null clears an optional field."""

    name: OrganizationName | None = None
    description: Description | None = None
    org_type: OrgType | None = None
    join_policy: JoinPolicy | None = None
    email: EmailStr | None = None
    phone: Phone | None = None
    website: Website | None = None
    address: Address | None = None
    city: City | None = None
    legal_name: ShortText | None = None
    tax_code: TaxCode | None = None
    license_number: ShortText | None = None
    legal_rep_name: ShortText | None = None
    legal_rep_position: ShortText | None = None
    logo_asset_id: Uuid7 | None = None
    cover_asset_id: Uuid7 | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> Self:
        errors: dict[str, tuple[str, str]] = {
            field: ("required", "This field cannot be empty")
            for field in (
                "name",
                "org_type",
                "join_policy",
                "description",
                "email",
                "phone",
                "city",
            )
            if field in self.model_fields_set and getattr(self, field) is None
        }
        if errors:
            raise field_errors("OrganizationUpdateRequest", errors)
        return self


class JoinRequest(StrictRequest):
    message: ApplicationMessage | None = None


class MemberRoleRequest(StrictRequest):
    role: Literal["admin", "member"]


class OrganizationSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    org_type: str
    join_policy: str
    member_count: int
    created_at: datetime
    # Relative paths served by GET /media/{id}/file, or null. Read from the row itself.
    logo_url: str | None
    cover_url: str | None


class OrganizationPage(BaseModel):
    items: list[OrganizationSummary]
    next_offset: int | None
    total: int


class ViewerMembership(BaseModel):
    """What the caller is to this organization. All empty for anonymous visitors."""

    status: str | None = None
    role: OrgRole | None = None
    can_manage: bool = False
    # Set while a rejected applicant has to wait before applying again.
    reapply_after: datetime | None = None


class OrganizationDetail(OrganizationSummary):
    email: str | None
    phone: str | None
    website: str | None
    address: str | None
    city: str | None
    legal_name: str | None
    tax_code: str | None
    license_number: str | None
    legal_rep_name: str | None
    legal_rep_position: str | None
    legal_status: str
    owner_name: str
    # Published activities and approved hours, for the header.
    activity_count: int
    volunteer_hours: float
    viewer: ViewerMembership


class MyOrganization(OrganizationSummary):
    status: str
    role: OrgRole | None


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    full_name: str
    role: OrgRole
    joined_at: datetime | None


class MemberPage(BaseModel):
    items: list[MemberResponse]
    next_offset: int | None
    total: int


class ApplicationResponse(BaseModel):
    user_id: uuid.UUID
    full_name: str
    message: str | None
    submitted_at: datetime | None


class ApplicationPage(BaseModel):
    items: list[ApplicationResponse]
    next_offset: int | None
    total: int
