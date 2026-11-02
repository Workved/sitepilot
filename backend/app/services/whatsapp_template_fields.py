"""Readable WhatsApp template fields, derived at dispatch time.

Outbox payloads carry ids (`task_id`, `project_id`, `assignment_id`, ...) -
the durable record of what happened. A WhatsApp template needs what a
person can read and reply with: "T003 - Flooring", "Project Futurex",
"In progress", the 8-character reply code `inbound_message.py` accepts.

`template_fields` adds those as extra keys on a copy of the payload, which
`message_templates.TEMPLATE_REGISTRY` entries then name in their
`variable_order`. Same rule as `telegram_render.py`: it only reads
records, never mutates, and a missing record degrades to a placeholder
instead of raising.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.execution_models import Task
from app.project_models import V2Project
from app.vendor_models import V2Vendor


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def reply_ref(value: object) -> str | None:
    """The 8-character code inbound WhatsApp commands use to name an
    assignment or approval (`ACCEPT <ref>`, `GATEACCEPT <ref>`)."""
    resolved = _uuid_or_none(value)
    return resolved.hex[:8].upper() if resolved else None


def readable_label(value: object) -> str | None:
    """`in_progress` -> `In progress`."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().replace("_", " ")
    return text[:1].upper() + text[1:]


def readable_date(value: object) -> str | None:
    """ISO date/datetime -> `05 Nov 2026`; anything else is passed through."""
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%d %b %Y")
    try:
        return datetime.fromisoformat(str(value)).strftime("%d %b %Y")
    except ValueError:
        return str(value)


def template_fields(db: Session, payload: dict) -> dict:
    """A copy of `payload` with readable keys added for every id it holds.
    Keys already present (e.g. `project_name` on gate events) win."""
    fields = dict(payload)

    task = None
    task_id = _uuid_or_none(payload.get("task_id"))
    if task_id is not None:
        task = db.get(Task, task_id)
    if task is not None:
        fields.setdefault("task_code", task.original_code)
        fields.setdefault("task_label", f"{task.original_code} - {task.title}")
    elif task_id is not None:
        fields.setdefault("task_label", "Unknown task")

    project_id = _uuid_or_none(payload.get("project_id")) or (task.project_id if task is not None else None)
    if project_id is not None and not fields.get("project_name"):
        project = db.get(V2Project, project_id)
        fields["project_name"] = project.name if project else "Unknown project"

    vendor_id = _uuid_or_none(payload.get("vendor_id"))
    if vendor_id is not None:
        vendor = db.get(V2Vendor, vendor_id)
        fields.setdefault("vendor_name", vendor.name if vendor else "Unknown vendor")

    if payload.get("assignment_id"):
        fields.setdefault("assignment_ref", reply_ref(payload["assignment_id"]))
    if payload.get("approval_id"):
        fields.setdefault("approval_ref", reply_ref(payload["approval_id"]))

    for key in ("before_status", "target_status", "lifecycle_status", "decision", "type", "responsibility_type"):
        if key in payload:
            fields.setdefault(f"{key}_label", readable_label(payload[key]))
    for key in ("planned_start_date", "planned_end_date", "due_date", "due_at"):
        if key in payload:
            fields.setdefault(f"{key}_label", readable_date(payload[key]))

    return fields
