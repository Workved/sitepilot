"""Response contracts for the read-only V2 template API."""
from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TemplateReferenceFileItem(BaseModel):
    """Admin-provided reference material (never execution evidence)."""

    id: uuid.UUID
    file_id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    description: str | None
    created_at: datetime | None = None
    # "template" (copied from the template, can't be removed on a project)
    # or "project" (added on this project).
    source: str = "template"


class TemplateReferenceFileMutationResponse(BaseModel):
    reference: TemplateReferenceFileItem
    revision_token: str


class TemplateReferenceFileDeleteResponse(BaseModel):
    reference_id: uuid.UUID
    deleted: bool
    revision_token: str


class TemplateListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_id: uuid.UUID
    template_code: str
    template_name: str
    template_description: str | None
    version_id: uuid.UUID
    version_no: int
    status: Literal["draft", "published", "archived"]
    is_current_published: bool
    duration_days: int
    task_count: int
    dependency_count: int
    gate_count: int
    created_at: datetime
    published_at: datetime | None


class PaginationMetadata(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    total_pages: int = Field(ge=0)

    @classmethod
    def from_result(cls, *, page: int, page_size: int, total: int) -> "PaginationMetadata":
        return cls(
            page=page,
            page_size=page_size,
            total=total,
            total_pages=math.ceil(total / page_size) if total else 0,
        )


class TemplateListResponse(BaseModel):
    items: list[TemplateListItem]
    pagination: PaginationMetadata
class TemplateVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_id: uuid.UUID
    template_code: str
    template_name: str
    template_description: str | None
    version_id: uuid.UUID
    version_no: int
    status: Literal["draft", "published", "archived"]
    is_current_published: bool
    duration_days: int
    change_note: str | None = None
    task_count: int
    dependency_count: int
    gate_count: int
    created_at: datetime
    published_at: datetime | None
    revision_token: str


class TemplateTaskItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    sequence_no: int | None
    title: str | None
    description: str | None
    schedule_classification: str | None
    planned_start_day: int | None
    planned_end_day: int | None
    phase: str | None
    category: str | None
    applicability: str | None
    task_class: str | None
    task_kind: str | None
    evidence_required: bool
    evidence_instructions: str | None = None
    reference_files: list[TemplateReferenceFileItem] = Field(default_factory=list)
    duration_days: int | None
    validation_state: Literal["valid", "invalid"]
    validation_issues: list[str]


class TemplateTaskListResponse(BaseModel):
    items: list[TemplateTaskItem]
    pagination: PaginationMetadata
class TemplateDependencyTaskReference(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    title: str | None
    phase: str | None
    day: int | None


class TemplateDependencyItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence_no: int
    dependency_type: str
    blocking: bool
    rule_text: str | None
    predecessor: TemplateDependencyTaskReference | None
    successor: TemplateDependencyTaskReference | None
    validation_state: Literal["valid", "invalid"]
    validation_issues: list[str]


class TemplateDependencyCounts(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    finish_to_start: int
    start_to_start: int
    blocking: int
    validation_issues: int


class TemplateDependencyListResponse(BaseModel):
    items: list[TemplateDependencyItem]
    pagination: PaginationMetadata
    summary: TemplateDependencyCounts

class TemplateGateTaskReference(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    title: str | None
    phase: str | None
    day: int | None


class TemplateGateItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    sequence_no: int
    approval_name: str | None
    description: str | None
    external_party: str | None
    required_by_type: str | None
    required_by_value: str | None
    impact: str | None
    evidence_instructions: str | None = None
    reference_files: list[TemplateReferenceFileItem] = Field(default_factory=list)
    mapping_classification: str
    requires_configuration: bool
    broad_mapping_text: str | None
    affected_tasks: list[TemplateGateTaskReference]
    validation_state: Literal["valid", "invalid"]
    validation_issues: list[str]


class TemplateGateListResponse(BaseModel):
    items: list[TemplateGateItem]
    pagination: PaginationMetadata
