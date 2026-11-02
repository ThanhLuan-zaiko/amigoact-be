"""Request and response bodies of certificate templates."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from src.organizations.schemas import StrictRequest
from src.validation import Uuid7, single_line

TemplateName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=120),
    AfterValidator(single_line),
]


class Placement(StrictRequest):
    """Where one text sits on the page, as a percentage of the page size."""

    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    size: int = Field(ge=8, le=72)


def _placement(x: float, y: float, size: int) -> Placement:
    return Placement(x=x, y=y, size=size)


class Layout(StrictRequest):
    """The five texts a certificate shows. Unknown keys are refused."""

    name: Placement = Field(default_factory=lambda: _placement(50, 45, 28))
    activity: Placement = Field(default_factory=lambda: _placement(50, 55, 18))
    hours: Placement = Field(default_factory=lambda: _placement(50, 62, 14))
    date: Placement = Field(default_factory=lambda: _placement(50, 70, 12))
    serial: Placement = Field(default_factory=lambda: _placement(50, 92, 10))


class TemplateCreate(StrictRequest):
    name: TemplateName
    background_asset_id: Uuid7 | None = None
    layout: Layout = Field(default_factory=Layout)


class TemplateUpdate(StrictRequest):
    """Only the fields that are sent change. Send null for background_asset_id to remove it."""

    name: TemplateName | None = None
    background_asset_id: Uuid7 | None = None
    layout: Layout | None = None
    is_active: bool | None = None


class TemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    # Relative to the API, like every media URL.
    background_url: str | None
    layout: Layout
    created_at: datetime


class TemplateList(BaseModel):
    items: list[TemplateResponse]
