"""Request body for a vendor's hand-entered past project (Work history)."""

import re
import uuid
from datetime import date
from decimal import Decimal

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_MONTH = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?$")


class VendorPastProjectIn(BaseModel):
    project_name: str
    client_name: str | None = None
    location: str | None = None
    category_id: uuid.UUID | None = None
    work_description: str | None = None
    # "YYYY-MM" from an <input type="month">; a full ISO date is accepted
    # too. Stored as the first day of that month.
    start_month: date | None = None
    end_month: date | None = None
    approx_value: Decimal | None = None
    notes: str | None = None

    @field_validator("project_name")
    @classmethod
    def _require_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name is required.")
        return value

    @field_validator("client_name", "location", "work_description", "notes", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("category_id", "approx_value", mode="before")
    @classmethod
    def _empty_to_none(cls, value):
        return None if value == "" else value

    @field_validator("start_month", "end_month", mode="before")
    @classmethod
    def _parse_month(cls, value):
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value.replace(day=1)
        match = _MONTH.match(str(value).strip())
        if not match:
            raise ValueError("Use a month like 2024-03.")
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise ValueError("Use a month like 2024-03.")
        return date(year, month, 1)

    @field_validator("approx_value")
    @classmethod
    def _non_negative(cls, value):
        if value is not None and value < 0:
            raise ValueError("Approximate value cannot be negative.")
        return value

    @model_validator(mode="after")
    def _end_after_start(self):
        if self.start_month and self.end_month and self.end_month < self.start_month:
            raise ValueError("End month cannot be before the start month.")
        return self


class VendorFeedbackIn(BaseModel):
    """One reviewer's view of a vendor's work on a finished SiteOps project."""

    rating: int = Field(ge=1, le=5)
    quality: int | None = Field(default=None, ge=1, le=5)
    timeliness: int | None = Field(default=None, ge=1, le=5)
    conduct: int | None = Field(default=None, ge=1, le=5)
    would_rehire: Literal["yes", "conditional", "no"]
    comment: str | None = None

    @field_validator("comment", mode="before")
    @classmethod
    def _blank_comment(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def _low_score_needs_reason(self):
        # A poor review is only useful to the next person with the reason.
        if (self.rating <= 2 or self.would_rehire == "no") and not self.comment:
            raise ValueError("Add a comment explaining a low rating or a 'would not hire again'.")
        return self
