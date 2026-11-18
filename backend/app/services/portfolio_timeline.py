"""Portfolio timeline: one row per project for the calendar's portfolio view.

Same visibility as the Projects list (`ProjectReadModelService.visible_projects`):
Admin and Super Admin see every non-archived project; everyone else sees the
projects they're an active member of.

Per project:
* start date, target handover, PM name;
* progress = completed / all non-cancelled tasks;
* forecast finish = the latest of each task's finish - its actual finish when
  done, otherwise its planned end, or today if that planned end has passed;
* days late = forecast finish past the target handover (0 if not);
* health: completed / delayed (days late > 0, or any task past its planned
  end) / at risk (blocked work or a pending approval due within 7 days or
  already overdue) / on track;
* approval markers: external approvals with a due date, and their status.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import ProjectExternalApproval, Task
from app.models import EmployeeProfile, User
from app.project_models import V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.project_read_models import ProjectReadModelService
from app.services.task_readiness import TaskReadinessService

DONE = {"completed"}
CANCELLED = {"cancelled"}
APPROVAL_DONE = {"approved"}


def _health(project: V2Project, days_late: int, overdue_tasks: int, blocked_tasks: int, approvals_at_risk: int) -> str:
    if project.status == "completed":
        return "completed"
    if days_late > 0 or overdue_tasks > 0:
        return "delayed"
    if blocked_tasks > 0 or approvals_at_risk > 0:
        return "at_risk"
    return "on_track"


class PortfolioTimelineService:
    def __init__(self, db: Session):
        self.db = db

    def rows(self, actor: User) -> list[dict]:
        projects = ProjectReadModelService(self.db).visible_projects(actor)
        if not projects:
            return []
        ids = [project.id for project in projects]
        today = datetime.now(timezone.utc).date()

        tasks_by_project: dict = {}
        for task in self.db.scalars(select(Task).where(Task.project_id.in_(ids))).all():
            tasks_by_project.setdefault(task.project_id, []).append(task)

        pm_names = dict(self.db.execute(
            select(V2ProjectMembership.project_id, User.name)
            .join(EmployeeProfile, EmployeeProfile.id == V2ProjectMembership.employee_id)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(V2ProjectMembership.project_id.in_(ids), V2ProjectMembership.project_role == "project_manager",
                   V2ProjectMembership.ends_at.is_(None))
        ).all())

        approvals_by_project: dict = {}
        for approval, name in self.db.execute(
            select(ProjectExternalApproval, V2ProjectExternalGate.approval_name)
            .join(V2ProjectExternalGate, V2ProjectExternalGate.id == ProjectExternalApproval.project_gate_id)
            .where(ProjectExternalApproval.project_id.in_(ids), ProjectExternalApproval.due_at.is_not(None))
            .order_by(ProjectExternalApproval.due_at)
        ).all():
            approvals_by_project.setdefault(approval.project_id, []).append((approval, name))

        readiness = TaskReadinessService(self.db)
        results = []
        for project in projects:
            tasks = [task for task in tasks_by_project.get(project.id, []) if task.lifecycle_status not in CANCELLED]
            completed = sum(1 for task in tasks if task.lifecycle_status in DONE)
            finishes: list[date] = []
            overdue = 0
            for task in tasks:
                if task.lifecycle_status in DONE:
                    if task.actual_finish_at:
                        finishes.append(task.actual_finish_at.date())
                    elif task.planned_end_date:
                        finishes.append(task.planned_end_date)
                elif task.planned_end_date:
                    if task.planned_end_date < today:
                        overdue += 1
                        finishes.append(today)
                    else:
                        finishes.append(task.planned_end_date)
            blocked = 0
            if project.status in {"active", "on_hold"} and tasks:
                states = readiness.for_project(project.id).tasks
                blocked = sum(1 for task in tasks if task.lifecycle_status not in DONE
                              and getattr(states.get(task.id), "state", None) == "blocked")
            forecast = max(finishes) if finishes else None
            handover = project.target_handover_date
            days_late = max(0, (forecast - handover).days) if (forecast and handover and project.status != "completed") else 0

            approvals = []
            at_risk = 0
            for approval, name in approvals_by_project.get(project.id, []):
                pending = approval.status not in APPROVAL_DONE
                if pending and approval.due_at <= today + timedelta(days=7):
                    at_risk += 1
                approvals.append({"name": name, "due_date": approval.due_at.isoformat(), "status": approval.status,
                                  "overdue": pending and approval.due_at < today})

            results.append({
                "project_id": str(project.id),
                "code": project.code,
                "name": project.name,
                "client_name": project.client_name,
                "status": project.status,
                "start_date": project.start_date.isoformat() if project.start_date else None,
                "target_handover_date": handover.isoformat() if handover else None,
                "forecast_finish_date": forecast.isoformat() if forecast else None,
                "pm_name": pm_names.get(project.id),
                "progress_pct": round(100 * completed / len(tasks)) if tasks else 0,
                "task_count": len(tasks),
                "completed_count": completed,
                "overdue_count": overdue,
                "blocked_count": blocked,
                "days_late": days_late,
                "health": _health(project, days_late, overdue, blocked, at_risk),
                "approvals": approvals,
            })
        return results
