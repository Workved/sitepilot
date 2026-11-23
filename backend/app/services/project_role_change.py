"""U6: two-step (request + approval) PM/Supervisor reassignment (BR-007/R7).

`ProjectRoleChangeService` replaces today's immediate
`assign_membership()` change for the two accountable roles
(`project_manager`, `site_supervisor`) with an explicit, reason-required,
audited request/approval flow:

- `request_role_change`: creates a `pending` `ProjectRoleChange` record.
  Does NOT touch `V2ProjectMembership` - a pending record never affects
  who is currently accountable (BR-004's derived-accountability model
  reads only active membership rows).
- `approve_role_change`: atomically ends the previous active membership
  (if any) for that role on the project and, for a "replacement" change,
  starts the replacement - reusing the same "end prior active membership
  in the same transaction" shape `assign_membership()`
  (`backend/app/routes/projects_v2.py`) already uses for immediate
  changes. Deliberately re-implemented here rather than imported, to
  avoid a routes<->services circular import (`routes/projects_v2.py`
  needs to call into this service for its new role-change routes).
- `reject_role_change`: marks the record `rejected`; no membership change.

Two `change_type`s:
- "replacement": names a successor up front; approval ends the current
  holder and starts the named replacement in the same step.
- "vacate": "empty the seat now, fill it later" - for the case where an
  accountable role's holder leaves (resigns, is offboarded) with no
  successor lined up yet. Approval ends the current holder and leaves the
  role vacant (surfaced via the project's ordinary "Not assigned" PM/
  Supervisor display) - no replacement_employee_id is stored or required.
  Filling a vacant role later is not a new action: it's the same
  "replacement" request/approve flow, just with no current holder to end
  (already handled - `current` is simply `None` in that case).

Requester/approver hierarchy per BR-007:
- PM replacement: only Admin/Super Admin may request or approve.
- Supervisor replacement: the project's active PM may request or approve;
  Admin/Super Admin is the audited fallback (mirrors BR-007's "if a PM is
  unavailable, Admin assigns the PM replacement or fallback" pattern
  extended to the general fallback authority Admin already has
  elsewhere in this codebase, e.g. `TaskVerificationService`).
- Internal Employee membership changes are NOT gated by this service at
  all - those stay on the existing immediate `assign_membership()` path.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership, ProjectRoleChange
from app.services.outbox import OutboxService

ROLE_TYPES = ("project_manager", "site_supervisor")
ROLE_TO_USER_ROLE = {
    "project_manager": UserRole.project_manager,
    "site_supervisor": UserRole.supervisor,
}


class ProjectRoleChangeService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access / role resolution -----------------------------------

    def _actor_project_roles(self, project_id: uuid.UUID, actor: User) -> set[str]:
        employee = self.db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == actor.id))
        if not employee:
            return set()
        rows = self.db.scalars(
            select(V2ProjectMembership.project_role).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.employee_id == employee.id,
                V2ProjectMembership.ends_at.is_(None),
            )
        )
        return set(rows)

    def _require_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return project
        if self._actor_project_roles(project_id, actor):
            return project
        raise HTTPException(403, "You do not have access to this project.")

    def _require_hierarchy_actor(self, project: V2Project, role_type: str, actor: User) -> None:
        """BR-007's role-specific hierarchy: who may request/approve a
        given role's replacement. Admin/Super Admin can always act (either
        as the PM-replacement authority itself, or as the audited fallback
        for Supervisor replacement)."""
        if actor.role in (UserRole.super_admin, UserRole.admin):
            return
        if role_type == "project_manager":
            raise HTTPException(403, "Only Admin can request or approve a Project Manager replacement.")
        if role_type == "site_supervisor":
            roles = self._actor_project_roles(project.id, actor)
            if "project_manager" in roles:
                return
            raise HTTPException(403, "Only the project's PM, or an Admin, can request or approve a Supervisor replacement.")
        raise HTTPException(422, "Unknown project role.")

    def _active_membership(self, project_id: uuid.UUID, role_type: str) -> V2ProjectMembership | None:
        return self.db.scalar(
            select(V2ProjectMembership).where(
                V2ProjectMembership.project_id == project_id,
                V2ProjectMembership.project_role == role_type,
                V2ProjectMembership.ends_at.is_(None),
            )
        )

    def _require_eligible_replacement(self, role_type: str, employee_id: uuid.UUID) -> EmployeeProfile:
        expected_role = ROLE_TO_USER_ROLE[role_type]
        employee = self.db.get(EmployeeProfile, employee_id)
        user = self.db.get(User, employee.user_id) if employee else None
        if not employee or not user or not user.active or user.role != expected_role:
            raise HTTPException(422, f"Select an active {role_type.replace('_', ' ')} employee.")
        if employee.availability == "unavailable":
            raise HTTPException(409, f"{user.name} is currently unavailable and cannot receive a new project assignment.")
        return employee

    def _add_audit(self, project: V2Project, actor: User, action: str, reason: str, before: dict | None, after: dict | None, entity_id: uuid.UUID) -> None:
        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action=action,
            entity_type="project_role_change",
            entity_id=entity_id,
            project_id=project.id,
            before_json=before,
            after_json=after,
            reason=reason,
        ))

    def _role_change_json(self, change: ProjectRoleChange) -> dict:
        return {
            "id": str(change.id),
            "project_id": str(change.project_id),
            "role_type": change.role_type,
            "previous_membership_id": str(change.previous_membership_id) if change.previous_membership_id else None,
            "replacement_employee_id": str(change.replacement_employee_id) if change.replacement_employee_id else None,
            "change_type": change.change_type,
            "reason_code": change.reason_code,
            "reason_detail": change.reason_detail,
            "status": change.status,
            "requested_by": str(change.requested_by),
            "requested_at": change.requested_at.isoformat(),
            "decided_by": str(change.decided_by) if change.decided_by else None,
            "decided_at": change.decided_at.isoformat() if change.decided_at else None,
        }

    # ---- request -----------------------------------------------------------

    def request_role_change(
        self,
        project_id: uuid.UUID,
        role_type: str,
        replacement_employee_id: uuid.UUID | None,
        reason_code: str,
        actor: User,
        change_type: str = "replacement",
        reason_detail: str | None = None,
    ) -> ProjectRoleChange:
        project = self._require_access(project_id, actor)

        if role_type not in ROLE_TYPES:
            raise HTTPException(422, "Unknown project role.")
        if change_type not in ("replacement", "vacate"):
            raise HTTPException(422, "Unknown role change type.")
        if change_type == "replacement" and replacement_employee_id is None:
            raise HTTPException(422, "Select a replacement employee.")
        if change_type == "vacate" and replacement_employee_id is not None:
            raise HTTPException(422, "A vacate request does not name a replacement.")

        clean_reason_code = (reason_code or "").strip()
        if not clean_reason_code:
            raise HTTPException(422, "A reason is required to request a role change.")

        self._require_hierarchy_actor(project, role_type, actor)

        current = self._active_membership(project.id, role_type)
        if change_type == "vacate":
            if current is None:
                raise HTTPException(422, f"There is no active {role_type.replace('_', ' ')} to vacate.")
        else:
            self._require_eligible_replacement(role_type, replacement_employee_id)
            if current is not None and current.employee_id == replacement_employee_id:
                raise HTTPException(409, "This employee already holds this project role.")

        pending = self.db.scalar(
            select(ProjectRoleChange).where(
                ProjectRoleChange.project_id == project.id,
                ProjectRoleChange.role_type == role_type,
                ProjectRoleChange.status == "pending",
            )
        )
        if pending is not None:
            raise HTTPException(409, "A role change request for this role is already pending on this project.")

        change = ProjectRoleChange(
            project_id=project.id,
            role_type=role_type,
            previous_membership_id=current.id if current else None,
            replacement_employee_id=replacement_employee_id,
            change_type=change_type,
            reason_code=clean_reason_code,
            reason_detail=(reason_detail or "").strip() or None,
            status="pending",
            requested_by=actor.id,
        )
        self.db.add(change)
        self.db.flush()
        self._add_audit(
            project, actor, "PROJECT_ROLE_CHANGE_REQUESTED", clean_reason_code,
            None, self._role_change_json(change), change.id,
        )
        try:
            # Gated to Active projects only, same rule as
            # `project.member_added`/`project.vendor_mapped`
            # (routes/projects_v2.py, project_vendor.py): `set_membership`
            # lets this request flow run during Draft too (see its own
            # comment on why), but a Draft project is still planning/setup
            # - nobody should get an operational WhatsApp ping
            # about a role-change request until the project is live.
            if project.status == "active":
                OutboxService(self.db).emit(
                    event_type="project.role_change_requested",
                    aggregate_type="project",
                    aggregate_id=project.id,
                    payload={
                        "project_id": str(project.id),
                        "change_id": str(change.id),
                        "role_type": role_type,
                        "change_type": change_type,
                        "replacement_employee_id": str(replacement_employee_id) if replacement_employee_id else None,
                        "reason_code": clean_reason_code,
                    },
                    idempotency_key=f"project:{project.id}:project.role_change_requested:{change.id}",
                )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(409, "A role change request for this role is already pending on this project.") from exc
        self.db.refresh(change)
        return change

    # ---- approve -----------------------------------------------------------

    def approve_role_change(self, project_id: uuid.UUID, change_id: uuid.UUID, actor: User) -> V2ProjectMembership:
        project = self._require_access(project_id, actor)

        change = self.db.scalar(
            select(ProjectRoleChange).where(
                ProjectRoleChange.id == change_id, ProjectRoleChange.project_id == project.id,
            ).with_for_update()
        )
        if not change:
            raise HTTPException(404, "Role change request not found.")
        if change.status != "pending":
            raise HTTPException(409, "This role change request has already been decided.")

        self._require_hierarchy_actor(project, change.role_type, actor)
        is_vacate = change.replacement_employee_id is None
        if not is_vacate:
            self._require_eligible_replacement(change.role_type, change.replacement_employee_id)

        now = datetime.now(timezone.utc)
        current = self._active_membership(project.id, change.role_type)
        if is_vacate and current is None:
            # Only reachable if the seat was somehow vacated another way
            # while this request sat pending - request_role_change already
            # requires a current holder to exist at request time.
            raise HTTPException(409, f"There is no active {change.role_type.replace('_', ' ')} left to vacate.")
        if current is not None:
            current.ends_at = now

        if is_vacate:
            result_membership = current
        else:
            result_membership = V2ProjectMembership(
                project_id=project.id,
                employee_id=change.replacement_employee_id,
                project_role=change.role_type,
                assigned_by=actor.id,
                assignment_reason=change.reason_code,
            )
            self.db.add(result_membership)
            self.db.flush()

        change.status = "approved"
        change.decided_by = actor.id
        change.decided_at = now
        change.effective_from = now

        self._add_audit(
            project, actor, "PROJECT_ROLE_CHANGE_APPROVED", change.reason_code,
            self._role_change_json(change), {"membership_id": str(result_membership.id)}, change.id,
        )

        try:
            # Same Draft-mode gate as the request emit above.
            if project.status == "active":
                OutboxService(self.db).emit(
                    event_type="project.role_change_approved",
                    aggregate_type="project",
                    aggregate_id=project.id,
                    payload={
                        "project_id": str(project.id),
                        "change_id": str(change.id),
                        "role_type": change.role_type,
                        "change_type": change.change_type,
                        "membership_id": str(result_membership.id),
                    },
                    idempotency_key=f"project:{project.id}:project.role_change_approved:{change.id}",
                )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(409, "This project role already has an active assignment.") from exc

        self.db.refresh(result_membership)
        return result_membership

    # ---- reject -----------------------------------------------------------

    def reject_role_change(self, project_id: uuid.UUID, change_id: uuid.UUID, actor: User, reason: str) -> ProjectRoleChange:
        project = self._require_access(project_id, actor)

        change = self.db.scalar(
            select(ProjectRoleChange).where(
                ProjectRoleChange.id == change_id, ProjectRoleChange.project_id == project.id,
            ).with_for_update()
        )
        if not change:
            raise HTTPException(404, "Role change request not found.")
        if change.status != "pending":
            raise HTTPException(409, "This role change request has already been decided.")

        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise HTTPException(422, "A reason is required to reject a role change request.")

        self._require_hierarchy_actor(project, change.role_type, actor)

        before = self._role_change_json(change)
        change.status = "rejected"
        change.decided_by = actor.id
        change.decided_at = datetime.now(timezone.utc)

        self._add_audit(project, actor, "PROJECT_ROLE_CHANGE_REJECTED", clean_reason, before, self._role_change_json(change), change.id)

        # Same Draft-mode gate as the request/approve emits above.
        if project.status == "active":
            OutboxService(self.db).emit(
                event_type="project.role_change_rejected",
                aggregate_type="project",
                aggregate_id=project.id,
                payload={
                    "project_id": str(project.id),
                    "change_id": str(change.id),
                    "role_type": change.role_type,
                    "reason": clean_reason,
                },
                idempotency_key=f"project:{project.id}:project.role_change_rejected:{change.id}",
            )

        self.db.commit()
        self.db.refresh(change)
        return change

    # ---- reassignment required query ------------------------------------

    def reassignment_required(self, project_id: uuid.UUID, actor: User) -> list[dict]:
        """BR-007's 'automatic skill-based or silent replacement is
        prohibited' - surfaced instead as a queryable condition: active
        PM/Supervisor memberships whose holder's `EmployeeProfile.availability
        == 'unavailable'`. Never auto-reassigns; never stores a new
        column - purely a read-side query joining current active
        `V2ProjectMembership` rows against `EmployeeProfile.availability`.
        """
        project = self._require_access(project_id, actor)

        rows = self.db.execute(
            select(V2ProjectMembership, EmployeeProfile)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .where(
                V2ProjectMembership.project_id == project.id,
                V2ProjectMembership.ends_at.is_(None),
                V2ProjectMembership.project_role.in_(ROLE_TYPES),
                EmployeeProfile.availability == "unavailable",
            )
        ).all()

        return [
            {
                "membership_id": str(membership.id),
                "project_id": str(project.id),
                "role_type": membership.project_role,
                "employee_id": str(employee.id),
                "availability": employee.availability,
            }
            for membership, employee in rows
        ]
