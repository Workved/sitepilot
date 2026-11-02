from datetime import date
import re
import uuid

from pydantic import BaseModel, field_validator

from app.models import UserRole


def normalize_phone(value: str | None) -> str | None:
    """Vendor phone/WhatsApp numbers in E.164 (`+919876543210`) - the form
    WhatsApp sends to and inbound replies are matched against. Spaces,
    dashes, dots and brackets are stripped; a leading `00` becomes `+`."""
    if value is None or not value.strip():
        return None
    phone = re.sub(r"[\s\-().]", "", value.strip())
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise ValueError("Use an international mobile number with country code, such as +919876543210.")
    return phone



class UserInviteIn(BaseModel):
    """Pre-registers a roster entry with no password and no Supabase identity yet.

    The account activates itself on the person's first Google sign-in
    (see app.auth.current_user's email-match fallback), which links this
    row to the Supabase identity Google creates at that point.
    """
    name: str
    email: str
    phone: str | None = None
    role: UserRole
    employee_code: str | None = None
    designation: str | None = None
    department: str | None = None


class UserUpdateIn(BaseModel):
    name: str
    email: str
    phone: str | None = None
    role: UserRole | None = None
    employee_code: str | None = None
    designation: str | None = None
    department: str | None = None
    reason: str | None = None




class UserLifecycleIn(BaseModel):
    reason: str


class UserDeleteIn(BaseModel):
    reason: str
    confirmation: str

class MyProfileUpdateIn(BaseModel):
    name: str
    phone: str | None = None


class VendorIn(BaseModel):
    name: str
    category: str
    contact_person: str
    phone: str
    whatsapp: str | None = None
    notes: str | None = None

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, value: str) -> str:
        phone = normalize_phone(value)
        if phone is None:
            raise ValueError("Phone number is required.")
        return phone

    @field_validator("whatsapp")
    @classmethod
    def _normalize_whatsapp(cls, value: str | None) -> str | None:
        return normalize_phone(value)


class VendorContactIn(BaseModel):
    vendor_id: uuid.UUID
    name: str
    designation: str | None = None
    phone: str
    whatsapp: str | None = None
    is_primary: bool = False

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, value: str) -> str:
        phone = normalize_phone(value)
        if phone is None:
            raise ValueError("Phone number is required.")
        return phone

    @field_validator("whatsapp")
    @classmethod
    def _normalize_whatsapp(cls, value: str | None) -> str | None:
        return normalize_phone(value)


class VendorCategoryIn(BaseModel):
    # category_type is not user-settable: a new main category defaults to
    # "service", a subcategory always inherits its parent's type (see
    # communication.py's create_category/update_category).
    parent_id: uuid.UUID | None = None
    description: str | None = None
    name: str


class ContractorRelationshipIn(BaseModel):
    main_contractor_id: uuid.UUID
    subcontractor_id: uuid.UUID

class ContractorProfileIn(BaseModel):
    name: str
    engagement_type: str = "main"
    parent_vendor_id: uuid.UUID | None = None
    status: str = "active"
    category_ids: list[uuid.UUID]
    email: str | None = None
    address: str | None = None
    gst_number: str | None = None
    notes: str | None = None

class ProjectIn(BaseModel):
    name: str
    client_name: str
    site_address: str
    start_date: date
    project_manager_id: uuid.UUID | None = None
    supervisor_id: uuid.UUID


class ProjectUpdateIn(BaseModel):
    name: str
    client_name: str
    site_address: str
    status: str
    project_manager_id: uuid.UUID | None = None
    supervisor_id: uuid.UUID


class TaskAdminIn(BaseModel):
    title: str
    category: str
    description: str | None = None
    supervisor_instruction: str | None = None
    pm_instruction: str | None = None
    proof_required: str | None = None
    dependency_note: str | None = None
    due_date: date
    vendor_id: uuid.UUID | None = None
    admin_note: str | None = None


class ReviewIn(BaseModel):
    action: str
    rejection_reason: str | None = None


class ModulePermissionRow(BaseModel):
    role: UserRole
    employee_code: str | None = None
    designation: str | None = None
    department: str | None = None
    module_key: str
    can_view: bool


class ModulePermissionIn(BaseModel):
    permissions: list[ModulePermissionRow]
class ExecutionTemplateTaskIn(BaseModel):
    id: uuid.UUID | None = None
    day_no: int
    title: str
    category: str = "General"
    category_id: uuid.UUID | None = None
    subcategory_id: uuid.UUID | None = None
    priority: str = "medium"
    instructions: str | None = None
    materials_required: str | None = None
    material_reminder: bool = False
    reminder_lead_days: int = 1

class ExecutionTemplateIn(BaseModel):
    name: str
    project_type: str
    duration_days: int = 3
    tasks: list[ExecutionTemplateTaskIn]

class ExecutionTemplateStatusIn(BaseModel):
    active: bool

class ExecutionProjectIn(BaseModel):
    name: str
    client_name: str
    location: str
    project_type: str
    area: str | None = None
    start_date: date
    duration_days: int = 3
    project_manager_id: uuid.UUID | None = None
    supervisor_id: uuid.UUID
    template_id: uuid.UUID | None = None

class ExecutionTaskIn(BaseModel):
    project_id: uuid.UUID
    day_id: uuid.UUID
    title: str
    category: str = "General"
    category_id: uuid.UUID | None = None
    subcategory_id: uuid.UUID | None = None
    instructions: str | None = None
    proof_required: str | None = None
    materials_required: str | None = None
    material_reminder: bool = False
    reminder_lead_days: int = 1
    assigned_supervisor_id: uuid.UUID
    assigned_contractor_id: uuid.UUID | None = None
    assigned_subcontractor_id: uuid.UUID | None = None
    priority: str = "medium"
    assignment_reason: str | None = None


class ExecutionTaskAssignmentIn(BaseModel):
    assigned_contractor_id: uuid.UUID | None = None
    assigned_subcontractor_id: uuid.UUID | None = None
    reason: str | None = None

class ExecutionProjectContractorIn(BaseModel):
    project_id: uuid.UUID
    contractor_id: uuid.UUID
    scope: str | None = None




class ExecutionProjectUpdateIn(BaseModel):
    name: str
    client_name: str
    location: str
    area: str | None = None
    status: str = "active"
    project_manager_id: uuid.UUID
    supervisor_id: uuid.UUID

class ExecutionTaskStatusIn(BaseModel):
    status: str

class ExecutionTaskReviewIn(BaseModel):
    action: str
    rejection_reason: str | None = None

class ExecutionTaskDelayReportIn(BaseModel):
    category: str
    reason: str
    proposed_date: date
class ExecutionTaskRescheduleIn(BaseModel):
    scheduled_date: date
    reason: str


class VendorCategoryUpdateIn(VendorCategoryIn):
    active: bool = True

