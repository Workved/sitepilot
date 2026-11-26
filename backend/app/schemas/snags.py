"""Request bodies for the project snag list."""

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

MAX_TITLE = 200


def _clean(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class SnagCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    area: str | None = None
    notes: str | None = None
    due_date: date | None = None
    urgent: bool = False
    assignee_user_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("Give the snag a short title.")
        if len(value) > MAX_TITLE:
            raise ValueError(f"Keep the title under {MAX_TITLE} characters; put detail in the notes.")
        return value

    @field_validator("area", "notes", mode="before")
    @classmethod
    def _blank(cls, value):
        return _clean(value)


class SnagUpdateIn(BaseModel):
    """Partial update: only the fields sent are changed, and sending null
    clears a field (e.g. untagging)."""
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    area: str | None = None
    notes: str | None = None
    due_date: date | None = None
    urgent: bool | None = None
    assignee_user_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Give the snag a short title.")
        if len(value) > MAX_TITLE:
            raise ValueError(f"Keep the title under {MAX_TITLE} characters; put detail in the notes.")
        return value

    @field_validator("area", "notes", mode="before")
    @classmethod
    def _blank(cls, value):
        return _clean(value)


class SnagStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "done"]
    closing_note: str | None = None

    @field_validator("closing_note", mode="before")
    @classmethod
    def _blank(cls, value):
        return _clean(value)
