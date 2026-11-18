import uuid

from pydantic import BaseModel, ConfigDict

from app.template_schemas import PaginationMetadata


class ProjectTemplateReviewTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    sequence: int
    title: str
    description: str | None
    schedule_classification: str
    planned_start_day: int | None
    planned_end_day: int | None
    phase: str | None
    category: str | None
    applicability: str
    included: bool
    source: str
    decision_state: str
    # Files added on this project (template files aren't listed here).
    reference_files: list[dict] = []


class ProjectTemplateReviewTaskPage(BaseModel):
    project_id: uuid.UUID
    items: list[ProjectTemplateReviewTaskOut]
    pagination: PaginationMetadata


class ProjectTemplateReviewSummaryOut(BaseModel):
    project_id: uuid.UUID
    total: int
    included: int
    excluded: int
    pending_review: int
    decided: int
    mandatory: int
    conditional: int
