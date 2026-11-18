"""U1: Baseline lock and execution-layer task/dependency instantiation.

`ProjectBaselineService.lock_and_instantiate` is the single service both
`POST /{project_id}/status` (draft->active branch) and
`POST /{project_id}/activate` must call, inside the same transaction as the
draft->active status flip, so no activation code path can produce an active
project without a locked baseline and instantiated tasks.

U8 adds external approvals to what activation instantiates, via
`ProjectApprovalInstantiationService` below. Activation is the one moment the
execution layer is allowed to read the planning layer, and it copies across
everything readiness will later need - coverage, blocking, prose - precisely
so readiness never has to go back for it (KTD8).
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution_models import (
    BaselineTask,
    ProjectBaseline,
    ProjectExternalApproval,
    ProjectExternalApprovalTask,
    Task,
    TaskDependency,
)
from app.models import User
from app.services.project_gate_due_date import resolve_gate_due_at
from app.services.project_schedule_dates import resolve_planned_dates
from app.project_models import (
    V2AuditEvent,
    V2Project,
    V2ProjectExternalGate,
    V2ProjectExternalGateTask,
    V2ProjectTask,
    V2ProjectTaskDependency,
)


def _content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProjectBaselineService:
    def __init__(self, db: Session):
        self.db = db

    def lock_and_instantiate(self, project: V2Project, actor: User) -> ProjectBaseline | None:
        """Lock the project's baseline and instantiate execution tasks.

        Must be called before the caller flips `project.status` to "active"
        and before that caller commits, so both live in one transaction.
        Idempotent: if a baseline already exists for this project, returns it
        unchanged and creates nothing new (re-activation guard).
        """
        existing = self.db.scalar(
            select(ProjectBaseline).where(ProjectBaseline.project_id == project.id)
        )
        if existing:
            return existing

        # "Included" here matches the codebase's existing authoritative flag
        # for baseline participation (V2ProjectTask.included), the same
        # field already used by the read-only /execution-tasks placeholder
        # endpoint's included/excluded counts. decision_state tracks review
        # provenance (pending_review vs. an explicit included/excluded
        # decision) but included=True is the actual "is part of the plan"
        # signal - mandatory tasks stay decision_state='pending_review'
        # forever (never becoming 'included') while still being included.
        included_tasks = list(self.db.scalars(
            select(V2ProjectTask)
            .where(V2ProjectTask.project_id == project.id, V2ProjectTask.included.is_(True))
            .order_by(V2ProjectTask.template_sequence.asc(), V2ProjectTask.original_code.asc())
        ).all())
        if not included_tasks:
            raise HTTPException(409, "Project activation requires at least one included task to lock a baseline.")

        included_dependencies = list(self.db.scalars(
            select(V2ProjectTaskDependency)
            .where(
                V2ProjectTaskDependency.project_id == project.id,
                V2ProjectTaskDependency.predecessor_project_task_id.in_([t.id for t in included_tasks]),
                V2ProjectTaskDependency.successor_project_task_id.in_([t.id for t in included_tasks]),
            )
            .order_by(V2ProjectTaskDependency.template_sequence.asc())
        ).all())

        gate_count = len(list(self.db.scalars(
            select(V2ProjectExternalGate.id)
            .where(V2ProjectExternalGate.project_id == project.id, V2ProjectExternalGate.applicability_state == "applicable")
        ).all()))

        baseline = ProjectBaseline(
            project_id=project.id,
            task_count=len(included_tasks),
            dependency_count=len(included_dependencies),
            gate_count=gate_count,
            locked_by=actor.id,
        )
        self.db.add(baseline)
        self.db.flush()

        baseline_task_by_project_task_id: dict[uuid.UUID, BaselineTask] = {}
        for task in included_tasks:
            snapshot_fields = {
                "original_code": task.original_code,
                "template_sequence": task.template_sequence,
                "title": task.title,
                "description": task.description,
                "schedule_classification": task.schedule_classification,
                "planned_start_day": task.planned_start_day,
                "planned_end_day": task.planned_end_day,
                "phase": task.phase,
                "category": task.category,
                "applicability": task.applicability,
                "task_class": task.task_class,
                "task_kind": task.task_kind,
                "evidence_required": task.evidence_required,
                "duration_days": task.duration_days,
            }
            baseline_task = BaselineTask(
                baseline_id=baseline.id,
                project_id=project.id,
                project_task_id=task.id,
                content_hash=_content_hash(snapshot_fields),
                **snapshot_fields,
            )
            self.db.add(baseline_task)
            baseline_task_by_project_task_id[task.id] = baseline_task
        self.db.flush()

        task_by_baseline_task_id: dict[uuid.UUID, Task] = {}
        for project_task_id, baseline_task in baseline_task_by_project_task_id.items():
            # U9: resolve the template's day offsets into real calendar dates
            # as the task is built, so an activated project is dated from the
            # moment it exists rather than by a later pass. The day offsets
            # themselves are copied through untouched - they stay the frozen
            # baseline that variance is measured against (R13).
            planned_start_date, planned_end_date = resolve_planned_dates(
                project.start_date,
                baseline_task.schedule_classification,
                baseline_task.planned_start_day,
                baseline_task.planned_end_day,
            )
            execution_task = Task(
                project_id=project.id,
                baseline_id=baseline.id,
                baseline_task_id=baseline_task.id,
                original_code=baseline_task.original_code,
                template_sequence=baseline_task.template_sequence,
                title=baseline_task.title,
                description=baseline_task.description,
                schedule_classification=baseline_task.schedule_classification,
                planned_start_day=baseline_task.planned_start_day,
                planned_end_day=baseline_task.planned_end_day,
                planned_start_date=planned_start_date,
                planned_end_date=planned_end_date,
                phase=baseline_task.phase,
                category=baseline_task.category,
                applicability=baseline_task.applicability,
                task_class=baseline_task.task_class,
                task_kind=baseline_task.task_kind,
                evidence_required=baseline_task.evidence_required,
                duration_days=baseline_task.duration_days,
                lifecycle_status="planned",
                created_from_baseline=True,
            )
            self.db.add(execution_task)
            task_by_baseline_task_id[baseline_task.id] = execution_task
        self.db.flush()

        task_by_project_task_id = {
            project_task_id: task_by_baseline_task_id[baseline_task.id]
            for project_task_id, baseline_task in baseline_task_by_project_task_id.items()
        }
        # Reference files added to draft tasks follow them onto the live tasks.
        from app.services.project_task_references import link_draft_files_to_live_tasks

        link_draft_files_to_live_tasks(self.db, task_by_project_task_id)

        for dependency in included_dependencies:
            predecessor = task_by_project_task_id.get(dependency.predecessor_project_task_id)
            successor = task_by_project_task_id.get(dependency.successor_project_task_id)
            if not predecessor or not successor:
                continue
            self.db.add(TaskDependency(
                project_id=project.id,
                baseline_id=baseline.id,
                project_dependency_id=dependency.id,
                predecessor_task_id=predecessor.id,
                successor_task_id=successor.id,
                dependency_type=dependency.dependency_type,
                blocking=dependency.blocking,
                rule_text=dependency.rule_text,
                created_from_baseline=True,
            ))
        self.db.flush()

        # U8: the applicable external approvals become runtime records in the
        # same transaction, reusing the map above rather than re-deriving it.
        ProjectApprovalInstantiationService(self.db).instantiate_for_project(
            project, task_by_project_task_id=task_by_project_task_id,
        )

        self.db.add(V2AuditEvent(
            actor_user_id=actor.id,
            action="PROJECT_BASELINE_LOCKED",
            entity_type="project_baseline",
            entity_id=baseline.id,
            project_id=project.id,
            source="portal",
            before_json={"task_count": 0, "dependency_count": 0},
            after_json={
                "task_count": baseline.task_count,
                "dependency_count": baseline.dependency_count,
                "gate_count": baseline.gate_count,
                "locked_at": datetime.now(timezone.utc).isoformat(),
            },
            reason="Project baseline locked at activation; execution tasks instantiated.",
        ))
        self.db.flush()

        return baseline


class ProjectApprovalInstantiationService:
    """U8: turn a project's applicable planning-layer gates into the runtime
    approval records readiness decides on.

    Never commits - the caller owns the transaction, so activation's approvals
    land or roll back with its tasks, matching `ProjectScheduleDateService`.

    Coverage is resolved from the template's *explicit* task references only.
    A gate classified `broad_text` describes its coverage in prose and a gate
    classified `unmapped` names nothing at all; neither is parsed, guessed at,
    expanded to every task or quietly reduced to none. Both produce an
    approval marked `unresolved`, carrying whatever prose there was, for U12
    to put in front of a human (R10).
    """

    def __init__(self, db: Session):
        self.db = db

    def instantiate_for_project(
        self,
        project: V2Project,
        *,
        task_by_project_task_id: dict[uuid.UUID, Task] | None = None,
    ) -> dict:
        """Create the missing approvals (and their coverage links) for one project.

        `task_by_project_task_id` lets activation hand over the map it already
        built while instantiating tasks; the backfill omits it and the map is
        rebuilt from the execution layer instead. Gates that already have an
        approval are skipped whole - their status may since have been decided,
        and re-deriving it would overwrite a real decision - which is what
        makes this safe to re-run.
        """
        gates = list(self.db.scalars(
            select(V2ProjectExternalGate)
            .where(
                V2ProjectExternalGate.project_id == project.id,
                V2ProjectExternalGate.applicability_state == "applicable",
            )
            .order_by(V2ProjectExternalGate.template_sequence.asc(), V2ProjectExternalGate.original_code.asc())
        ).all())

        already_instantiated = set(self.db.scalars(
            select(ProjectExternalApproval.project_gate_id)
            .where(ProjectExternalApproval.project_id == project.id)
        ).all())
        pending_gates = [gate for gate in gates if gate.id not in already_instantiated]

        report = {
            "gates_scanned": len(gates),
            "approvals_created": 0,
            "coverage_links_created": 0,
            "unresolved_count": 0,
        }
        if not pending_gates:
            return report

        if task_by_project_task_id is None:
            task_by_project_task_id = self._task_by_project_task_id(project.id)

        links_by_gate: dict[uuid.UUID, list[V2ProjectExternalGateTask]] = {}
        for link in self.db.scalars(
            select(V2ProjectExternalGateTask)
            .where(V2ProjectExternalGateTask.project_gate_id.in_([gate.id for gate in pending_gates]))
            .order_by(V2ProjectExternalGateTask.project_task_id.asc())
        ).all():
            links_by_gate.setdefault(link.project_gate_id, []).append(link)

        for gate in pending_gates:
            resolved = gate.mapping_classification == "exact"
            # Linked tasks in this project's plan - for coverage and for a
            # `before_linked_tasks` due date.
            linked_tasks = [
                task for link in (links_by_gate.get(gate.id, []) if resolved else [])
                if (task := task_by_project_task_id.get(link.project_task_id)) is not None
            ]
            linked_starts = [task.planned_start_date for task in linked_tasks if task.planned_start_date]
            approval = ProjectExternalApproval(
                project_id=project.id,
                project_gate_id=gate.id,
                status="unassigned",
                # The PM's blocking decision travels with the approval. A
                # non-blocking gate that arrived here as blocking would stop
                # every task it covers, which is the opposite of what was set.
                blocking=gate.blocking,
                coverage_state="exact" if resolved else "unresolved",
                coverage_text=None if resolved else gate.broad_mapping_text,
                # Phase 5: resolved from the gate's required_by_type/value -
                # "date" direct, "project_day" via the same day-offset
                # resolver used for Task.planned_start_date/end_date above.
                # None (never invented) when the gate carries no rule, or a
                # project_day rule with no project.start_date yet.
                due_at=resolve_gate_due_at(
                    gate.required_by_type, gate.required_by_value, project.start_date,
                    earliest_linked_start=min(linked_starts, default=None),
                ),
            )
            self.db.add(approval)
            self.db.flush()
            report["approvals_created"] += 1
            if not resolved:
                report["unresolved_count"] += 1
                continue

            # A named task excluded from the baseline has no execution row to
            # block, so it is absent from linked_tasks. Coverage stays `exact`:
            # the template was explicit and nothing is being guessed - the task
            # simply is not part of this project's plan.
            for task in linked_tasks:
                self.db.add(ProjectExternalApprovalTask(
                    project_id=project.id,
                    approval_id=approval.id,
                    task_id=task.id,
                ))
                report["coverage_links_created"] += 1
        self.db.flush()
        return report

    def _task_by_project_task_id(self, project_id: uuid.UUID) -> dict[uuid.UUID, Task]:
        """Rebuild activation's project-task -> execution-task map for a
        project that was activated before this unit existed.

        `BaselineTask` is the hop that makes this possible without reading the
        planning tasks themselves: it froze `project_task_id` at activation.
        """
        rows = self.db.execute(
            select(BaselineTask.project_task_id, Task)
            .join(BaselineTask, Task.baseline_task_id == BaselineTask.id)
            .where(Task.project_id == project_id)
        ).all()
        return {project_task_id: task for project_task_id, task in rows}

    def backfill(self, *, project_id: uuid.UUID | None = None) -> dict:
        """Instantiate approvals for projects activated before this unit.

        Scoped to projects that already hold a locked baseline, since a draft
        has no execution layer to attach approvals to and will get them at its
        own activation. Idempotent by construction: `instantiate_for_project`
        skips gates that already have an approval, so a second run creates
        nothing.
        """
        statement = select(V2Project).where(
            V2Project.id.in_(select(ProjectBaseline.project_id))
        ).order_by(V2Project.id)
        if project_id is not None:
            statement = statement.where(V2Project.id == project_id)

        projects = list(self.db.scalars(statement).all())
        totals = {
            "projects_scanned": len(projects),
            "projects_updated": 0,
            "approvals_created": 0,
            "coverage_links_created": 0,
            "unresolved_count": 0,
        }
        for project in projects:
            result = self.instantiate_for_project(project)
            if result["approvals_created"]:
                totals["projects_updated"] += 1
            for key in ("approvals_created", "coverage_links_created", "unresolved_count"):
                totals[key] += result[key]
        return totals
