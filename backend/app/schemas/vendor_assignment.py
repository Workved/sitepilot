"""Phase 2 U2/U3: request/response schemas for project-vendor mapping, task
vendor delegation, vendor acknowledgement, and vendor activity/incident
capture (R2/R3/R4/R5). Follows the style established in
`app.schemas.execution_tasks`."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectVendorMapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor_id: uuid.UUID


class ProjectVendorOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    vendor_id: uuid.UUID
    mapped_by: uuid.UUID
    created_at: datetime
    ends_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectVendorRemoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=4)


class TaskVendorUnassignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=4)


class V2VendorOut(BaseModel):
    """Read surface for the vendor picker (ProjectVendorPanel) - an active
    V2 vendor plus its capability category names, so the picker can show
    what a vendor is qualified for before it's mapped to a project."""

    id: uuid.UUID
    name: str
    engagement_type: str
    parent_vendor_id: uuid.UUID | None
    status: str
    contact_person: str
    phone: str
    whatsapp: str | None
    capability_categories: list[str] = Field(default_factory=list)
    capability_category_ids: list[uuid.UUID] = Field(default_factory=list)


class CapabilityCategoryOut(BaseModel):
    id: uuid.UUID
    name: str

    model_config = ConfigDict(from_attributes=True)


class VendorCapabilitiesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category_ids: list[uuid.UUID] = Field(default_factory=list)


class ProjectContactAttachmentOut(BaseModel):
    """One active attachment of a vendor contact to this project."""

    id: uuid.UUID
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    note: str | None = None


class ProjectVendorContactOut(BaseModel):
    """A vendor's contact as seen from one project: who they are, and what
    they are attached to on this project (empty = not attached here)."""

    id: uuid.UUID
    name: str
    designation: str | None = None
    phone: str
    whatsapp: str | None = None
    is_primary: bool = False
    attachments: list[ProjectContactAttachmentOut] = Field(default_factory=list)


class ProjectVendorMappingOut(BaseModel):
    """Read surface for "list current mappings" (ProjectVendorPanel) and
    the vendor picker inside TaskVendorDelegationForm, which must only
    offer vendors already mapped to the project."""

    id: uuid.UUID
    project_id: uuid.UUID
    vendor_id: uuid.UUID
    vendor_name: str
    engagement_type: str
    parent_vendor_id: uuid.UUID | None
    mapped_by: uuid.UUID
    created_at: datetime
    ends_at: datetime | None = None
    acknowledged_at: datetime | None = None
    contacts: list[ProjectVendorContactOut] = Field(default_factory=list)


class TaskVendorAssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor_id: uuid.UUID
    # Optional point person: a contact of `vendor_id`.
    contact_id: uuid.UUID | None = None


class TaskVendorContactIn(BaseModel):
    """Change (or clear, with null) a task assignment's point person."""

    model_config = ConfigDict(extra="forbid")
    contact_id: uuid.UUID | None = None


class VendorContactProjectIn(BaseModel):
    """Attach a vendor contact to this project. One row per category; an
    empty `category_ids` means all of the vendor's work on the project."""

    model_config = ConfigDict(extra="forbid")
    contact_id: uuid.UUID
    category_ids: list[uuid.UUID] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=500)


class VendorContactProjectOut(BaseModel):
    id: uuid.UUID
    contact_id: uuid.UUID
    project_id: uuid.UUID
    category_id: uuid.UUID | None = None
    note: str | None = None
    assigned_by: uuid.UUID | None = None
    created_at: datetime
    ends_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskVendorAssignmentOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    vendor_id: uuid.UUID
    status: str
    assigned_by: uuid.UUID
    created_at: datetime
    ends_at: datetime | None = None
    contact_id: uuid.UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class VendorAcknowledgementIn(BaseModel):
    """Phase 2 U3: R4 - a PM-submitted, portal-channel acknowledgement
    recorded on the vendor's behalf. `channel` defaults to 'portal' since
    that is the only channel this unit's route accepts; the field exists so
    the underlying log can later carry WhatsApp-sourced responses without a
    shape change."""

    model_config = ConfigDict(extra="forbid")
    response: Literal["accepted", "declined", "clarification_requested"]
    channel: Literal["portal", "whatsapp", "telegram", "system"] = "portal"
    note: str | None = Field(default=None, max_length=2000)


class VendorAcknowledgementOut(BaseModel):
    id: uuid.UUID
    task_vendor_assignment_id: uuid.UUID
    response: str
    channel: str
    note: str | None
    recorded_by: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskVendorAssignmentDetailOut(BaseModel):
    """Read surface for TaskVendorDelegationForm/VendorAcknowledgementForm -
    a task's vendor assignment(s) plus their full acknowledgement history,
    so the UI can render current state without re-deriving it from separate
    list calls."""

    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    vendor_id: uuid.UUID
    vendor_name: str
    status: str
    assigned_by: uuid.UUID
    created_at: datetime
    ends_at: datetime | None = None
    contact_id: uuid.UUID | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_whatsapp: str | None = None
    acknowledgements: list[VendorAcknowledgementOut] = Field(default_factory=list)
