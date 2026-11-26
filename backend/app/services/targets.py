"""Task and project targets, plus the schedule-change history the calendar
draws ("Moved +6d").

A target is a commitment date on top of the plan; it never moves the plan,
so delay variance stays measured against the plan.

* Task target: one active per task. Setting another marks the previous one
  'replaced' (history kept). Status: met (finished on/before the date),
  missed (finished after, or not finished and the date has passed),
  due_soon (not finished, date within 2 days), open.
* Project target: a titled date, optionally linked to tasks. With tasks it
  is met when all linked (non-cancelled) tasks finished by the date; with
  none it is met when someone marks it achieved on/before the date.

Who: see/list - anyone who can view the project. Set - anyone with an active
membership, and admins. Change/clear/mark achieved - whoever set it, the
project's PM or Supervisor, and admins. Archived projects are read-only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.execution_models import Task, TaskSupportAssignment
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services.outbox import OutboxService
from app.target_models import ProjectTarget, ProjectTargetTask

ADMIN_ROLES = {UserRole.super_admin, UserRole.admin}
DUE_SOON_DAYS = 2


def _now():
    return datetime.now(timezone.utc)


def _today():
    return datetime.now(timezone.utc).date()


def _finish_day(task: Task) -> date | None:
    return task.actual_finish_at.date() if task.actual_finish_at else None


def task_target_status(target_date: date, task: Task | None, today: date) -> dict:
    """Status of a target against one task (also used per linked task)."""
    if task is not None and task.lifecycle_status == "completed":
        finished = _finish_day(task) or today
        days = (finished - target_date).days
        return {"state": "met" if days <= 0 else "missed", "days": abs(days), "finished_on": finished.isoformat()}
    if task is not None and task.lifecycle_status == "cancelled":
        return {"state": "cancelled", "days": 0, "finished_on": None}
    remaining = (target_date - today).days
    if remaining < 0:
        return {"state": "missed", "days": -remaining, "finished_on": None}
    return {"state": "due_soon" if remaining <= DUE_SOON_DAYS else "open", "days": remaining, "finished_on": None}


class TargetService:
    def __init__(self, db: Session):
        self.db = db

    # ---- access ------------------------------------------------------------

    def _roles(self, project_id: uuid.UUID, actor: User) -> set[str]:
        return set(self.db.scalars(
            select(V2ProjectMembership.project_role)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .where(EmployeeProfile.user_id == actor.id, V2ProjectMembership.project_id == project_id, V2ProjectMembership.ends_at.is_(None))
        ).all())

    def _project(self, project_id: uuid.UUID, actor: User) -> tuple[V2Project, set[str]]:
        project = self.db.get(V2Project, project_id)
        if not project:
            raise HTTPException(404, "Project not found.")
        roles = self._roles(project.id, actor)
        if actor.role not in ADMIN_ROLES and not roles:
            raise HTTPException(403, "You do not have access to this project.")
        return project, roles

    def _can_manage(self, target: ProjectTarget, actor: User, roles: set[str]) -> bool:
        return actor.role in ADMIN_ROLES or target.created_by == actor.id or bool(roles & {"project_manager", "site_supervisor"})

    @staticmethod
    def _require_writable(project: V2Project) -> None:
        if project.status == "archived":
            raise HTTPException(409, "This project is archived; its targets are read-only.")

    def _target(self, target_id: uuid.UUID, actor: User, *, manage: bool) -> tuple[ProjectTarget, V2Project, set[str]]:
        target = self.db.get(ProjectTarget, target_id)
        if not target:
            raise HTTPException(404, "Target not found.")
        project, roles = self._project(target.project_id, actor)
        if manage:
            self._require_writable(project)
            if target.status != "active":
                raise HTTPException(409, "This target was already replaced or cleared.")
            if not self._can_manage(target, actor, roles):
                raise HTTPException(403, "Only whoever set this target, the project's PM or Supervisor, or an admin can change it.")
        return target, project, roles

    def _tasks(self, project_id: uuid.UUID, task_ids) -> list[Task]:
        ids = list(dict.fromkeys(task_ids))
        if not ids:
            return []
        tasks = self.db.scalars(select(Task).where(Task.id.in_(ids), Task.project_id == project_id)).all()
        if len(tasks) != len(ids):
            raise HTTPException(422, "Every linked task must belong to this project.")
        return tasks

    # ---- serialisation -----------------------------------------------------

    def _status(self, target: ProjectTarget, linked: list[Task], task: Task | None, today: date) -> dict:
        if target.kind == "task":
            return task_target_status(target.target_date, task, today)
        counted = [item for item in linked if item.lifecycle_status != "cancelled"]
        if counted:
            done = [item for item in counted if item.lifecycle_status == "completed"]
            if len(done) == len(counted):
                last = max((_finish_day(item) or today) for item in done)
                days = (last - target.target_date).days
                return {"state": "met" if days <= 0 else "missed", "days": abs(days), "finished_on": last.isoformat(), "done": len(done), "total": len(counted)}
            base = task_target_status(target.target_date, None, today)
            return {**base, "done": len(done), "total": len(counted)}
        if target.achieved_at:
            achieved = target.achieved_at.date()
            days = (achieved - target.target_date).days
            return {"state": "met" if days <= 0 else "missed", "days": abs(days), "finished_on": achieved.isoformat()}
        return task_target_status(target.target_date, None, today)

    def serialize_many(self, targets: list[ProjectTarget], actor: User, roles: set[str], project: V2Project) -> list[dict]:
        today = _today()
        links = self.db.execute(select(ProjectTargetTask).where(ProjectTargetTask.target_id.in_([t.id for t in targets]))).scalars().all() if targets else []
        linked_ids: dict[uuid.UUID, list[uuid.UUID]] = {}
        for link in links:
            linked_ids.setdefault(link.target_id, []).append(link.task_id)
        task_ids = {t.task_id for t in targets if t.task_id} | {tid for ids in linked_ids.values() for tid in ids}
        tasks = {task.id: task for task in self.db.scalars(select(Task).where(Task.id.in_(task_ids))).all()} if task_ids else {}
        user_ids = {uid for t in targets for uid in (t.created_by, t.ended_by, t.achieved_by) if uid}
        names = dict(self.db.execute(select(User.id, User.name).where(User.id.in_(user_ids))).all()) if user_ids else {}
        writable = project.status != "archived"
        out = []
        for target in targets:
            task = tasks.get(target.task_id) if target.task_id else None
            linked = [tasks[tid] for tid in linked_ids.get(target.id, []) if tid in tasks]
            out.append({
                "id": str(target.id), "project_id": str(target.project_id), "kind": target.kind,
                "task_id": str(target.task_id) if target.task_id else None,
                "task_label": f"{task.original_code} · {task.title}" if task else None,
                "title": target.title, "target_date": target.target_date.isoformat(), "note": target.note,
                "status": target.status,
                "linked_task_ids": [str(item.id) for item in linked],
                "linked_tasks": [{"id": str(item.id), "label": f"{item.original_code} · {item.title}", "lifecycle_status": item.lifecycle_status} for item in linked],
                "achieved_at": target.achieved_at.isoformat() if target.achieved_at else None,
                "achieved_by_name": names.get(target.achieved_by),
                "created_by": str(target.created_by) if target.created_by else None,
                "created_by_name": names.get(target.created_by) or "Former user",
                "created_at": target.created_at.isoformat() if target.created_at else None,
                "ended_at": target.ended_at.isoformat() if target.ended_at else None,
                "ended_by_name": names.get(target.ended_by),
                "outcome": self._status(target, linked, task, today) if target.status == "active" else None,
                "can_manage": writable and target.status == "active" and self._can_manage(target, actor, roles),
            })
        return out

    # ---- audit / notify ----------------------------------------------------

    def _audit(self, actor, project, action, target, reason, before=None, after=None):
        self.db.add(V2AuditEvent(actor_user_id=actor.id, action=action, entity_type="target", entity_id=target.id,
                                 project_id=project.id, before_json=before, after_json=after, reason=reason))

    def _responsible_user_ids(self, project: V2Project, task: Task) -> set[uuid.UUID]:
        """The task's Site Supervisor(s) and actively assigned support staff."""
        employee_ids = set(self.db.scalars(select(V2ProjectMembership.employee_id).where(
            V2ProjectMembership.project_id == project.id, V2ProjectMembership.project_role == "site_supervisor", V2ProjectMembership.ends_at.is_(None))).all())
        employee_ids |= set(self.db.scalars(select(TaskSupportAssignment.employee_id).where(
            TaskSupportAssignment.task_id == task.id, TaskSupportAssignment.status == "active")).all())
        if not employee_ids:
            return set()
        return set(self.db.scalars(select(EmployeeProfile.user_id).where(EmployeeProfile.id.in_(employee_ids))).all())

    def _notify_set(self, target: ProjectTarget, project: V2Project, task: Task, actor: User) -> None:
        if not settings.target_whatsapp_enabled:
            return
        for user_id in self._responsible_user_ids(project, task) - {actor.id}:
            OutboxService(self.db).emit(
                event_type="target.set", aggregate_type="user", aggregate_id=user_id,
                payload={"user_id": str(user_id), "target_id": str(target.id), "set_by": actor.name,
                         "task_label": f"{task.original_code} - {task.title}", "project_name": project.name,
                         "target_date": target.target_date.strftime("%d %b %Y")},
                idempotency_key=f"target.set:{target.id}:{user_id}",
            )

    # ---- reads -------------------------------------------------------------

    def list(self, project_id: uuid.UUID, actor: User) -> dict:
        project, roles = self._project(project_id, actor)
        targets = self.db.scalars(select(ProjectTarget).where(ProjectTarget.project_id == project.id)
                                  .order_by(ProjectTarget.target_date, ProjectTarget.created_at)).all()
        return {"project_id": str(project.id), "can_add": project.status != "archived",
                "items": self.serialize_many(targets, actor, roles, project)}

    def schedule_changes(self, project_id: uuid.UUID, actor: User) -> list[dict]:
        """Per rescheduled task: the original plan (the 'before' of its first
        reschedule), how many times it moved, and the latest reason."""
        project, _ = self._project(project_id, actor)
        events = self.db.scalars(select(V2AuditEvent).where(
            V2AuditEvent.project_id == project.id, V2AuditEvent.action == "TASK_RESCHEDULED")
            .order_by(V2AuditEvent.occurred_at, V2AuditEvent.id)).all()
        grouped: dict[uuid.UUID, list[V2AuditEvent]] = {}
        for event in events:
            grouped.setdefault(event.entity_id, []).append(event)
        user_ids = {event.actor_user_id for event in events if event.actor_user_id}
        names = dict(self.db.execute(select(User.id, User.name).where(User.id.in_(user_ids))).all()) if user_ids else {}
        out = []
        for task_id, items in grouped.items():
            first, last = items[0], items[-1]
            out.append({
                "task_id": str(task_id),
                "original_start": (first.before_json or {}).get("planned_start_date"),
                "original_end": (first.before_json or {}).get("planned_end_date"),
                "times_moved": len(items),
                "last_reason": last.reason, "last_by": names.get(last.actor_user_id),
                "last_at": last.occurred_at.isoformat() if last.occurred_at else None,
            })
        return out

    # ---- writes ------------------------------------------------------------

    def create(self, project_id: uuid.UUID, actor: User, data: dict) -> dict:
        project, roles = self._project(project_id, actor)
        self._require_writable(project)
        task = None
        if data["kind"] == "task":
            task = self._tasks(project.id, [data["task_id"]])[0]
            if task.lifecycle_status in ("completed", "cancelled"):
                raise HTTPException(409, "This task is already finished; it can't get a new target.")
            previous = self.db.scalar(select(ProjectTarget).where(ProjectTarget.task_id == task.id, ProjectTarget.status == "active"))
            if previous:
                previous.status, previous.ended_at, previous.ended_by = "replaced", _now(), actor.id
                self.db.flush()
            target = ProjectTarget(project_id=project.id, kind="task", task_id=task.id, title=None,
                                   target_date=data["target_date"], note=data.get("note"), created_by=actor.id)
            self.db.add(target)
            self.db.flush()
            self._audit(actor, project, "TARGET_SET", target, f"Target set for {task.original_code}: {target.target_date.isoformat()}",
                        before={"target_date": previous.target_date.isoformat()} if previous else None,
                        after={"target_date": target.target_date.isoformat(), "note": target.note})
            self._notify_set(target, project, task, actor)
        else:
            linked = self._tasks(project.id, data.get("task_ids") or [])
            target = ProjectTarget(project_id=project.id, kind="project", title=data["title"],
                                   target_date=data["target_date"], note=data.get("note"), created_by=actor.id)
            self.db.add(target)
            self.db.flush()
            for item in linked:
                self.db.add(ProjectTargetTask(target_id=target.id, task_id=item.id))
            self._audit(actor, project, "TARGET_SET", target, f"Project target set: {target.title} by {target.target_date.isoformat()}",
                        after={"title": target.title, "target_date": target.target_date.isoformat(), "task_count": len(linked)})
        self.db.commit()
        self.db.refresh(target)
        return self.serialize_many([target], actor, roles, project)[0]

    def update(self, target_id: uuid.UUID, actor: User, changes: dict) -> dict:
        target, project, roles = self._target(target_id, actor, manage=True)
        if target.kind == "task" and "target_date" in changes and changes["target_date"] != target.target_date:
            raise HTTPException(409, "Set a new target to change a task's date, so the old one stays in history.")
        if target.kind == "task" and ("title" in changes or "task_ids" in changes):
            raise HTTPException(422, "A task target has no title or linked tasks.")
        if target.kind == "project" and "title" in changes and not changes["title"]:
            raise HTTPException(422, "Give the project target a short title.")
        before = {"target_date": target.target_date.isoformat(), "title": target.title, "note": target.note}
        # Title and date only change when a value is sent; a note may be
        # cleared by sending null.
        for key in ("title", "target_date"):
            if changes.get(key) is not None:
                setattr(target, key, changes[key])
        if "note" in changes:
            target.note = changes["note"]
        if target.kind == "project" and changes.get("task_ids") is not None:
            linked = self._tasks(project.id, changes["task_ids"])
            for link in self.db.scalars(select(ProjectTargetTask).where(ProjectTargetTask.target_id == target.id)).all():
                self.db.delete(link)
            self.db.flush()
            for item in linked:
                self.db.add(ProjectTargetTask(target_id=target.id, task_id=item.id))
        self._audit(actor, project, "TARGET_UPDATED", target, "Target updated", before=before,
                    after={"target_date": target.target_date.isoformat(), "title": target.title, "note": target.note})
        self.db.commit()
        self.db.refresh(target)
        return self.serialize_many([target], actor, roles, project)[0]

    def clear(self, target_id: uuid.UUID, actor: User) -> dict:
        target, project, roles = self._target(target_id, actor, manage=True)
        target.status, target.ended_at, target.ended_by = "cleared", _now(), actor.id
        self._audit(actor, project, "TARGET_CLEARED", target, "Target cleared", before={"target_date": target.target_date.isoformat()})
        self.db.commit()
        self.db.refresh(target)
        return self.serialize_many([target], actor, roles, project)[0]

    def set_achieved(self, target_id: uuid.UUID, actor: User, achieved: bool) -> dict:
        target, project, roles = self._target(target_id, actor, manage=True)
        if target.kind != "project":
            raise HTTPException(422, "A task target is met when the task is finished.")
        if self.db.scalar(select(ProjectTargetTask.task_id).where(ProjectTargetTask.target_id == target.id).limit(1)):
            raise HTTPException(409, "This target follows its linked tasks; it is met when they are all done.")
        target.achieved_at, target.achieved_by = (_now(), actor.id) if achieved else (None, None)
        self._audit(actor, project, "TARGET_ACHIEVED" if achieved else "TARGET_REOPENED", target, "Target marked achieved" if achieved else "Target reopened")
        self.db.commit()
        self.db.refresh(target)
        return self.serialize_many([target], actor, roles, project)[0]
