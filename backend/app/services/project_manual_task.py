import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import EmployeeProfile, User
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership, V2ProjectTask
from app.schemas.project_manual_task import ProjectManualTaskCreateIn, ProjectManualTaskCreateOut
from app.services.project_task_addition import TemplateTaskPromotion, require_task_adder, require_template_adder
from app.template_models import V2TemplateVersion


MANUAL_CODE_PATTERN = re.compile(r"^MANUAL-(\d+)$")


class ProjectManualTaskService:
    def __init__(self, db: Session):
        self.db = db

    def _require_draft_access(self, project_id: uuid.UUID, actor: User) -> V2Project:
        project = self.db.scalar(
            select(V2Project).where(V2Project.id == project_id).with_for_update()
        )
        if not project:
            raise HTTPException(404, "Project not found.")
        # Admin, or the project's own PM / Supervisor (the same rule as
        # adding a task once the project is running).
        require_task_adder(self.db, project, actor)
        if project.status != "draft":
            raise HTTPException(409, "Project-specific tasks can only be added while the project is Draft.")
        if not project.template_version_id:
            raise HTTPException(409, "Attach a published template before adding a project-specific task.")
        return project

    def _next_code_and_sequence(self, project_id: uuid.UUID) -> tuple[str, int]:
        rows = self.db.execute(
            select(V2ProjectTask.original_code, V2ProjectTask.template_sequence)
            .where(V2ProjectTask.project_id == project_id)
        ).all()
        used_numbers = set()
        maximum_sequence = 0
        for code, sequence in rows:
            maximum_sequence = max(maximum_sequence, int(sequence))
            match = MANUAL_CODE_PATTERN.fullmatch(code or "")
            if match:
                used_numbers.add(int(match.group(1)))
        manual_number = 1
        while manual_number in used_numbers:
            manual_number += 1
        return f"MANUAL-{manual_number:03d}", maximum_sequence + 1

    def create(
        self,
        project_id: uuid.UUID,
        actor: User,
        payload: ProjectManualTaskCreateIn,
    ) -> ProjectManualTaskCreateOut:
        try:
            project = self._require_draft_access(project_id, actor)
            promotion = TemplateTaskPromotion(self.db)
            if payload.add_to_template:
                require_template_adder(actor)
                promotion.check(project, payload.planned_start_day, payload.planned_end_day)
            template_duration = self.db.scalar(
                select(V2TemplateVersion.duration_days).where(
                    V2TemplateVersion.id == project.template_version_id
                )
            )
            if not template_duration:
                raise HTTPException(409, "The project's template version is unavailable.")
            if payload.planned_end_day > template_duration:
                raise HTTPException(
                    422,
                    f"Planned days must be within the configured {template_duration}-day duration.",
                )

            code, sequence = self._next_code_and_sequence(project.id)
            task = V2ProjectTask(
                project_id=project.id,
                template_version_id=project.template_version_id,
                template_task_id=None,
                original_code=code,
                template_sequence=sequence,
                title=payload.title,
                description=None,
                schedule_classification="execution",
                planned_start_day=payload.planned_start_day,
                planned_end_day=payload.planned_end_day,
                phase=payload.phase,
                category=payload.category,
                applicability="mandatory",
                task_class=None,
                task_kind=None,
                evidence_required=False,
                duration_days=payload.planned_end_day - payload.planned_start_day + 1,
                source_type="project_manual",
                lifecycle_status="draft",
                included=True,
                decision_state="included",
                added_by=actor.id,
            )
            self.db.add(task)
            self.db.flush()
            audit = V2AuditEvent(
                actor_user_id=actor.id,
                action="PROJECT_MANUAL_TASK_CREATED",
                entity_type="project_task",
                entity_id=task.id,
                project_id=project.id,
                source="portal",
                before_json=None,
                after_json={
                    "code": task.original_code,
                    "title": task.title,
                    "phase": task.phase,
                    "category": task.category,
                    "planned_start_day": task.planned_start_day,
                    "planned_end_day": task.planned_end_day,
                    "source_type": task.source_type,
                },
                reason=payload.reason,
                occurred_at=datetime.now(timezone.utc),
            )
            self.db.add(audit)
            self.db.flush()
            self.db.commit()
        except HTTPException:
            self.db.rollback()
            raise
        except IntegrityError as exc:
            self.db.rollback()
            raise HTTPException(409, "A project task with this generated code already exists. Retry the request.") from exc
        except Exception:
            self.db.rollback()
            raise

        template_result = None
        if payload.add_to_template:
            template_result = promotion.add(
                actor, project, title=task.title, description=None, phase=task.phase, category=task.category,
                start_day=task.planned_start_day, end_day=task.planned_end_day, evidence_required=False, reason=payload.reason,
            )
        return ProjectManualTaskCreateOut(
            project_id=project.id,
            task_id=task.id,
            code=task.original_code,
            sequence=task.template_sequence,
            title=task.title,
            phase=task.phase,
            category=task.category,
            planned_start_day=task.planned_start_day,
            planned_end_day=task.planned_end_day,
            duration_days=task.duration_days,
            source_type=task.source_type,
            lifecycle_status=task.lifecycle_status,
            included=task.included,
            decision_state=task.decision_state,
            audit_event_id=audit.id,
            template=template_result,
        )
