"""Request bodies for task and project targets."""

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


def _clean(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class TargetCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["task", "project"]
    target_date: date
    task_id: uuid.UUID | None = None
    title: str | None = None
    note: str | None = None
    task_ids: list[uuid.UUID] = []

    @field_validator("title", "note", mode="before")
    @classmethod
    def _blank(cls, value):
        return _clean(value)

    @model_validator(mode="after")
    def _shape(self):
        if self.kind == "task" and not self.task_id:
            raise ValueError("Pick the task this target is for.")
        if self.kind == "project" and not self.title:
            raise ValueError("Give the project target a short title.")
        if self.title and len(self.title) > 200:
            raise ValueError("Keep the title under 200 characters.")
        return self


class TargetUpdateIn(BaseModel):
    """Note, title, linked tasks. A task target's date is changed by setting
    a new target (so the old promise stays in history)."""
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    note: str | None = None
    target_date: date | None = None
    task_ids: list[uuid.UUID] | None = None

    @field_validator("title", "note", mode="before")
    @classmethod
    def _blank(cls, value):
        return _clean(value)


class TargetAchievedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    achieved: bool
