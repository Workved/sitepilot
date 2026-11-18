"""Reference material and "what proof is needed?" instructions on a project.

Nothing is copied onto the project: a project task reaches its template task
through task -> baseline task -> project task -> template task, and an
approval reaches its template gate through approval -> project gate ->
template gate. Those template rows belong to the version the project is
pinned to, which is published and never edited, so a later template version
can never change what an existing project shows. Manually added project
tasks and gates have no template row and so no material.

Downloads follow the same visibility as the task and approval views: Admins
and active project members, except that an Internal Employee only reaches
work they are assigned to (mirroring `get_project_task` and
`ProjectGateDecisionService.list_for_project`).
"""
from __future__ import annotations

import uuid
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import BaselineTask, FileObject, ProjectExternalApproval, Task, TaskSupportAssignment
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectExternalGate, V2ProjectTask
from app.repositories.template_reference_repository import (
    ReferenceTarget,
    reference_files_by_owner,
    reference_link_model,
    reference_owner_column,
)
from app.services.template_reference_files import read_reference_bytes
from app.template_models import V2TemplateExternalGate, V2TemplateTask

NO_MATERIAL = {"evidence_instructions": None, "reference_files": []}


def template_material(db: Session, target: ReferenceTarget, template_ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, dict]:
    """Instructions and reference files for many template tasks or gates, in two queries."""
    ids = [template_id for template_id in set(template_ids) if template_id is not None]
    if not ids:
        return {}
    model = V2TemplateTask if target == "task" else V2TemplateExternalGate
    instructions = dict(db.execute(select(model.id, model.evidence_instructions).where(model.id.in_(ids))).all())
    references = reference_files_by_owner(db, target, ids)
    return {
        template_id: {"evidence_instructions": instructions.get(template_id), "reference_files": references.get(template_id, [])}
        for template_id in ids
    }


def template_task_id_for(db: Session, task: Task) -> uuid.UUID | None:
    return db.scalar(
        select(V2ProjectTask.template_task_id)
        .join(BaselineTask, BaselineTask.project_task_id == V2ProjectTask.id)
        .where(BaselineTask.id == task.baseline_task_id)
    )


def material_for_task(db: Session, task: Task) -> dict:
    """Template material plus any reference files added on the project."""
    from app.services.project_task_references import project_files_by_task

    template_task_id = template_task_id_for(db, task)
    material = template_material(db, "task", [template_task_id]).get(template_task_id, NO_MATERIAL)
    added = project_files_by_task(db, [task.id]).get(task.id, [])
    if not added:
        return material
    return {**material, "reference_files": [*material["reference_files"], *added]}


def material_for_gates(db: Session, gates: Iterable[V2ProjectExternalGate]) -> dict[uuid.UUID, dict]:
    """Keyed by project gate id."""
    gates = list(gates)
    by_template = template_material(db, "gate", [gate.template_gate_id for gate in gates])
    return {gate.id: by_template.get(gate.template_gate_id, NO_MATERIAL) for gate in gates}


def _employee_id(db: Session, actor: User) -> uuid.UUID | None:
    return db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == actor.id))


def _file(db: Session, target: ReferenceTarget, template_id: uuid.UUID | None, reference_id: uuid.UUID) -> tuple[FileObject, bytes]:
    model, owner = reference_link_model(target), reference_owner_column(target)
    row = None
    if template_id is not None:
        row = db.execute(
            select(model, FileObject)
            .join(FileObject, FileObject.id == model.file_id)
            .where(model.id == reference_id, owner == template_id)
        ).first()
    if row is None:
        raise HTTPException(404, "Reference file not found.")
    return row[1], read_reference_bytes(row[1])


def task_reference_file(db: Session, project: V2Project, task_id: uuid.UUID, reference_id: uuid.UUID, actor: User) -> tuple[FileObject, bytes]:
    """`project` must already have passed the project visibility check."""
    task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project.id))
    if task is None:
        raise HTTPException(404, "Task not found.")
    if actor.role == UserRole.internal_employee:
        employee_id = _employee_id(db, actor)
        assigned = employee_id is not None and db.scalar(select(TaskSupportAssignment.id).where(
            TaskSupportAssignment.task_id == task.id,
            TaskSupportAssignment.employee_id == employee_id,
            TaskSupportAssignment.status == "active",
            TaskSupportAssignment.ends_at.is_(None),
        ).limit(1))
        if not assigned:
            raise HTTPException(403, "You can only view tasks you are actively assigned to support.")
    from app.services.project_task_references import project_reference_link

    added = project_reference_link(db, task, reference_id)
    if added is not None:
        return added, read_reference_bytes(added)
    return _file(db, "task", template_task_id_for(db, task), reference_id)


def approval_reference_file(db: Session, project: V2Project, approval_id: uuid.UUID, reference_id: uuid.UUID, actor: User) -> tuple[FileObject, bytes]:
    """`project` must already have passed the project visibility check."""
    approval = db.scalar(select(ProjectExternalApproval).where(
        ProjectExternalApproval.id == approval_id, ProjectExternalApproval.project_id == project.id,
    ))
    if approval is None:
        raise HTTPException(404, "External approval not found for this project.")
    if actor.role == UserRole.internal_employee and approval.assigned_to_user_id != actor.id:
        raise HTTPException(403, "You can only view external approvals assigned to you.")
    gate = db.get(V2ProjectExternalGate, approval.project_gate_id)
    return _file(db, "gate", gate.template_gate_id if gate else None, reference_id)
