import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectManualTaskCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    phase: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    planned_start_day: int = Field(ge=1)
    planned_end_day: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    # Admin only: also publish a new template version with this task.
    add_to_template: bool = False

    @field_validator("title", "phase", "category", "reason")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_day_order(self):
        if self.planned_start_day > self.planned_end_day:
            raise ValueError("Planned start day cannot exceed planned end day.")
        return self


class ProjectManualTaskCreateOut(BaseModel):
    project_id: uuid.UUID
    task_id: uuid.UUID
    code: str
    sequence: int
    title: str
    phase: str
    category: str
    planned_start_day: int
    planned_end_day: int
    duration_days: int
    source_type: str
    lifecycle_status: str
    included: bool
    decision_state: str
    audit_event_id: uuid.UUID
    # Set when add_to_template was asked for: what happened on the template.
    template: dict | None = None


class RunningProjectTaskAddIn(BaseModel):
    """A task added to a project that has already started."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    phase: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    planned_start_date: date
    planned_end_date: date
    evidence_required: bool = False
    after_task_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)
    add_to_template: bool = False

    @field_validator("title", "phase", "category", "reason")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @model_validator(mode="after")
    def validate_date_order(self):
        if self.planned_start_date > self.planned_end_date:
            raise ValueError("The task can't finish before it starts.")
        return self
