"""Readable Telegram messages for internal task execution (Telegram task plan U4,
app/services/telegram_task_render.py).

Every in-scope task event renders as HTML with no raw payload lines and no
ids, and reads differently for the people doing the work than for reviewers
and the rest of the team.
"""

from __future__ import annotations

import re
import unittest
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.execution_models import (
    FileObject,
    Task,
    TaskApprovalDecision,
    TaskBlocker,
    TaskDelayEvent,
    TaskEvidence,
    TaskProgressUpdate,
    TaskSupportAssignment,
    TaskVerification,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectMembership
from app.services.telegram_render import render_telegram
from app.services.telegram_task_render import TASK_RENDERERS
from app.template_models import V2TemplateVersion  # noqa: F401 - FK target for V2Project

UUID_PATTERN = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}", re.I)
PAYLOAD_KEY_LINE = re.compile(r"^[a-z_]+: ", re.M)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class TelegramTaskRenderTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__, EmployeeProfile.__table__, V2Project.__table__, V2ProjectMembership.__table__,
            Task.__table__, TaskSupportAssignment.__table__, V2AuditEvent.__table__, TaskBlocker.__table__,
            TaskDelayEvent.__table__, TaskProgressUpdate.__table__, TaskEvidence.__table__, FileObject.__table__,
            TaskVerification.__table__, TaskApprovalDecision.__table__,
        ):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()

        with self.db.begin():
            self.admin = self._user("Niddhi Admin", UserRole.admin)
            self.pm, self.pm_profile = self._member("Prachit PM", UserRole.project_manager, None)
            self.supervisor, self.supervisor_profile = self._member("Deepak Supervisor", UserRole.supervisor, None)
            self.employee, self.employee_profile = self._member("Rohan Employee", UserRole.internal_employee, None)
            self.project = V2Project(
                code="PRJ-1", name="SIS Interior", client_name="Client", site_address="Site",
                start_date=date(2026, 9, 21), status="active", created_by=self.admin.id,
            )
            self.db.add(self.project)
            self.db.flush()
            for profile, role in (
                (self.pm_profile, "project_manager"),
                (self.supervisor_profile, "site_supervisor"),
                (self.employee_profile, "internal_employee"),
            ):
                self.db.add(V2ProjectMembership(
                    project_id=self.project.id, employee_id=profile.id, project_role=role,
                    assigned_by=self.admin.id, assignment_reason="seed",
                ))
            self.task = self._task("T008", "Formal site handover", task_class="standard", task_kind="work")
            self.class_a = self._task("T020", "Structural check", task_class="class_a", task_kind="work")
            self.gate_task = self._task("T014", "Issue delivery schedule", task_class=None, task_kind="approval_gate")
            self.db.add(TaskSupportAssignment(
                task_id=self.task.id, project_id=self.project.id, employee_id=self.employee_profile.id,
                responsibility="Execution", assigned_by=self.supervisor.id,
            ))

    def tearDown(self):
        self.db.close()

    # ---- fixtures ------------------------------------------------------------

    def _user(self, name, role) -> User:
        user = User(id=uuid.uuid4(), name=name, email=f"{uuid.uuid4().hex[:6]}@example.com", role=role, active=True)
        self.db.add(user)
        self.db.flush()
        return user

    def _member(self, name, role, _unused):
        user = self._user(name, role)
        profile = EmployeeProfile(user_id=user.id, employee_code=f"E-{uuid.uuid4().hex[:6]}", designation=name, availability="available")
        self.db.add(profile)
        self.db.flush()
        return user, profile

    def _task(self, code, title, *, task_class, task_kind) -> Task:
        task = Task(
            project_id=self.project.id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
            original_code=code, template_sequence=1, title=title, schedule_classification="execution",
            applicability="mandatory", task_class=task_class, task_kind=task_kind, lifecycle_status="in_progress",
            planned_start_date=date(2026, 9, 24),
        )
        self.db.add(task)
        self.db.flush()
        return task

    def _submitted_by(self, task: Task, user: User) -> None:
        self.db.add(V2AuditEvent(
            actor_user_id=user.id, action="TASK_STATUS_CHANGED", entity_type="task", entity_id=task.id,
            project_id=self.project.id, source="portal", before_json={"lifecycle_status": "in_progress"},
            after_json={"lifecycle_status": "submitted"}, reason="Submitted.",
        ))
        self.db.commit()

    def _render(self, event_type, payload, recipient_profile=None, task=None):
        task = task or self.task
        full = {"task_id": str(task.id), "project_id": str(self.project.id), **payload}
        return render_telegram(self.db, event_type, full, recipient_profile.id if recipient_profile else None)

    # ---- every in-scope event is readable ---------------------------------------

    def test_every_task_event_renders_readable_html_with_no_ids_or_payload_keys(self):
        blocker = TaskBlocker(task_id=self.task.id, project_id=self.project.id, type="Material", description="Tiles late")
        self.db.add(blocker)
        self.db.flush()
        delay = TaskDelayEvent(
            task_id=self.task.id, project_id=self.project.id, responsibility_type="internal", reason="Truck broke down",
            impact_days=2, recorded_by=self.supervisor.id,
        )
        self.db.add(delay)
        self.db.commit()
        payloads = {
            "task.status_changed": {"before_status": "ready", "target_status": "in_progress", "actor_user_id": str(self.employee.id)},
            "task.verification_recorded": {"decision": "rejected", "remarks": "Gaps", "verified_by": str(self.supervisor.id)},
            "task.approval_recorded": {"decision": "approved", "decided_by": str(self.pm.id)},
            "task.support_assigned": {"employee_id": str(self.employee_profile.id), "responsibility": "Execution"},
            "task.support_ended": {"previous_employee_id": str(self.employee_profile.id), "reason_code": "workload"},
            "task.blocker_created": {"blocker_id": str(blocker.id), "type": "Material", "description": "Tiles late"},
            "task.blocker_resolved": {"blocker_id": str(blocker.id), "resolved_by": str(self.supervisor.id)},
            "task.delay_recorded": {"delay_id": str(delay.id), "responsibility_type": "internal", "impact_days": 2},
            "task.rescheduled": {
                "before_planned_start_date": "2026-09-24", "planned_start_date": "2026-09-28",
                "before_planned_end_date": "2026-09-26", "planned_end_date": "2026-09-30", "reason": "Client delay",
            },
            "task.added": {"planned_start_date": "2026-09-24", "planned_end_date": "2026-09-26", "reason": "Client asked for it"},
            "task.readiness_check": {"lifecycle_status": "planned", "planned_start_date": "2026-09-24"},
            "task.start_check": {"lifecycle_status": "ready", "planned_start_date": "2026-09-24"},
            "task.midday_check": {"lifecycle_status": "in_progress", "planned_start_date": "2026-09-24"},
            "task.eod_check": {"lifecycle_status": "in_progress", "planned_start_date": "2026-09-24"},
            "task.eod_followup_required": {"lifecycle_status": "in_progress", "update_sla_hours": 24},
            "task.escalated_to_admin": {"lifecycle_status": "in_progress", "update_sla_hours": 24},
            "task.prestart_warning": {"lifecycle_status": "planned", "planned_start_date": "2026-09-24"},
            "task.sla_overdue": {"lifecycle_status": "in_progress", "planned_end_date": "2026-09-24"},
            "task.sla_escalated": {"lifecycle_status": "in_progress", "planned_end_date": "2026-09-24"},
            "task.readiness_declared": {"status": "issue", "note": "No power on site"},
        }
        self.assertEqual(set(payloads), set(TASK_RENDERERS))
        for event_type, payload in payloads.items():
            for recipient in (self.employee_profile, self.supervisor_profile, None):
                with self.subTest(event_type=event_type, recipient=getattr(recipient, "designation", None)):
                    message = self._render(event_type, payload, recipient)
                    self.assertEqual(message.parse_mode, "HTML")
                    self.assertTrue(message.text.startswith("<b>"))
                    self.assertIsNone(UUID_PATTERN.search(message.text), message.text)
                    self.assertIsNone(PAYLOAD_KEY_LINE.search(message.text), message.text)
                    self.assertNotIn("STATUS ", message.text)
                    self.assertIn("T008 - Formal site handover", message.text)

    def test_dynamic_values_are_html_escaped(self):
        message = self._render(
            "task.verification_recorded",
            {"decision": "rejected", "remarks": "<script>x</script> & more", "verified_by": str(self.supervisor.id)},
            self.employee_profile,
        )
        self.assertIn("&lt;script&gt;x&lt;/script&gt; &amp; more", message.text)
        self.assertNotIn("<script>", message.text)

    # ---- review outcomes ----------------------------------------------------------

    def test_rejection_tells_the_executor_who_rejected_why_and_what_to_do(self):
        message = self._render(
            "task.verification_recorded",
            {"decision": "rejected", "remarks": "Joint gaps at the door frame", "verified_by": str(self.supervisor.id)},
            self.employee_profile,
        )
        self.assertIn("<b>Rework Required</b>", message.text)
        self.assertIn("Rejected by: Deepak Supervisor", message.text)
        self.assertIn("Reason: Joint gaps at the door frame", message.text)
        self.assertIn("Add new progress and submit the task for review again.", message.text)

    def test_rejection_copy_for_the_pm_is_information_only(self):
        message = self._render(
            "task.verification_recorded",
            {"decision": "rejected", "remarks": "Gaps", "verified_by": str(self.supervisor.id)},
            self.pm_profile,
        )
        self.assertIn("Rework Required", message.text)
        self.assertNotIn("Add new progress", message.text)
        self.assertIn("No action required.", message.text)

    def test_pm_rejection_is_also_rework_required(self):
        message = self._render(
            "task.approval_recorded",
            {"decision": "rejected", "remarks": "Wrong grade", "decided_by": str(self.pm.id)},
            self.employee_profile,
        )
        self.assertIn("<b>Rework Required</b>", message.text)
        self.assertIn("Rejected by: Prachit PM", message.text)

    def test_verified_standard_work_is_completed_for_the_executor(self):
        message = self._render(
            "task.verification_recorded", {"decision": "verified", "verified_by": str(self.supervisor.id)},
            self.employee_profile,
        )
        self.assertIn("<b>Task Completed</b>", message.text)
        self.assertIn("Verified by: Deepak Supervisor", message.text)

    def test_verified_class_a_work_awaits_pm_approval(self):
        self._submitted_by(self.class_a, self.employee)
        payload = self._class_a_verified_by(self.supervisor)
        executor = self._render("task.verification_recorded", payload, self.employee_profile, task=self.class_a)
        self.assertIn("<b>Verified - Awaiting PM Approval</b>", executor.text)
        self.assertIn("waiting for PM approval", executor.text)
        pm = self._render("task.verification_recorded", payload, self.pm_profile, task=self.class_a)
        self.assertIn("<b>Task Ready for Approval</b>", pm.text)
        self.assertIn("Approve it, or reject it with a reason.", pm.text)
        self.assertEqual([b["text"] for row in pm.button_rows() for b in row], ["Approve", "Reject"])

    # ---- submissions (KTD23 routing) -----------------------------------------------

    def test_work_submission_reads_as_a_review_request_for_the_supervisor(self):
        self._submitted_by(self.task, self.employee)
        update = self._update("Done")
        self.task.lifecycle_status = "submitted"
        self.db.commit()
        payload = self._submitted(update)
        supervisor = self._render("task.status_changed", payload, self.supervisor_profile)
        self.assertIn("<b>Task Submitted for Review</b>", supervisor.text)
        self.assertIn("Submitted by: Rohan Employee", supervisor.text)
        self.assertIn("Verify it, or reject it with a reason.", supervisor.text)
        submitter = self._render("task.status_changed", payload, self.employee_profile)
        self.assertIn("<b>Submitted for Review</b>", submitter.text)
        self.assertIn("You will be told the outcome.", submitter.text)

    def test_approval_gate_submission_never_asks_the_supervisor_to_verify(self):
        self._submitted_by(self.gate_task, self.employee)
        update = self._update("Permit filed", task=self.gate_task)
        self.gate_task.lifecycle_status = "submitted"
        self.db.commit()
        payload = self._submitted(update)
        supervisor = self._render("task.status_changed", payload, self.supervisor_profile, task=self.gate_task)
        self.assertIn("<b>Submitted - Awaiting PM Approval</b>", supervisor.text)
        self.assertNotIn("verif", supervisor.text.lower())
        self.assertNotIn("Review it", supervisor.text)
        self.assertIn("No action required.", supervisor.text)
        self.assertEqual(supervisor.button_rows(), [])
        pm = self._render("task.status_changed", payload, self.pm_profile, task=self.gate_task)
        self.assertIn("Approve it, or reject it with a reason.", pm.text)
        self.assertEqual([b["text"] for row in pm.button_rows() for b in row], ["Approve", "Reject"])

    # ---- other status messages -------------------------------------------------------

    def test_early_start_reason_is_shown(self):
        self.task.actual_start_at = datetime.now(timezone.utc)
        self.task.early_start_reason = "Site handed over early"
        self.db.commit()
        message = self._render(
            "task.status_changed",
            {"before_status": "ready", "target_status": "in_progress", "actor_user_id": str(self.employee.id)},
            self.pm_profile,
        )
        self.assertIn("Early start reason: Site handed over early", message.text)

    def test_milestone_completion_is_named_as_such(self):
        milestone = self._task("T099", "Handover milestone", task_class=None, task_kind="milestone")
        self.db.commit()
        message = self._render(
            "task.status_changed", {"before_status": "planned", "target_status": "completed"}, self.pm_profile,
            task=milestone,
        )
        self.assertIn("<b>Milestone Completed</b>", message.text)

    def test_support_assignment_reads_differently_for_the_assignee(self):
        payload = {"employee_id": str(self.employee_profile.id), "responsibility": "Execution"}
        self.assertIn("Task Assigned to You", self._render("task.support_assigned", payload, self.employee_profile).text)
        other = self._render("task.support_assigned", payload, self.pm_profile).text
        self.assertIn("Employee Assigned to Task", other)
        self.assertIn("Employee: Rohan Employee", other)

    # ---- U5 buttons: shown only to people the lifecycle rules would allow -----------

    def _buttons(self, event_type, payload, recipient, task=None) -> list[str]:
        message = self._render(event_type, payload, recipient, task=task)
        return [button["text"] for row in message.button_rows() for button in row]

    def test_start_task_goes_only_to_the_assigned_employee(self):
        self.task.lifecycle_status = "ready"
        self.db.commit()
        payload = {"before_status": "planned", "target_status": "ready"}
        self.assertEqual(self._buttons("task.status_changed", payload, self.employee_profile), ["Start Task"])
        # An employee is assigned, so the Supervisor/PM may not start it.
        self.assertEqual(self._buttons("task.status_changed", payload, self.supervisor_profile), [])
        self.assertEqual(self._buttons("task.status_changed", payload, self.pm_profile), [])

    def test_mark_ready_for_a_planned_task_on_assignment_and_checks(self):
        self.task.lifecycle_status = "planned"
        self.db.commit()
        assigned = {"employee_id": str(self.employee_profile.id), "responsibility": "Execution"}
        self.assertEqual(self._buttons("task.support_assigned", assigned, self.employee_profile), ["Mark Task Ready"])
        self.assertEqual(self._buttons("task.support_assigned", assigned, self.supervisor_profile), ["Mark Task Ready"])
        check = {"lifecycle_status": "planned", "planned_start_date": "2026-09-24"}
        # T3: the readiness check records a readiness declaration instead.
        self.assertEqual(self._buttons("task.readiness_check", check, self.employee_profile), ["Ready", "Need Help", "Issue"])
        # The midday check carries no start buttons - only Report Blocker (U12).
        self.assertEqual(self._buttons("task.midday_check", check, self.employee_profile), ["Report Blocker"])

    def test_unassigned_work_can_be_started_by_the_supervisor(self):
        self.class_a.lifecycle_status = "ready"
        self.db.commit()
        check = {"lifecycle_status": "ready", "planned_start_date": "2026-09-24"}
        self.assertEqual(
            self._buttons("task.start_check", check, self.supervisor_profile, task=self.class_a), ["Start Task", "Report Blocker"],
        )

    def test_nobody_can_self_start_an_unassigned_approval_gate_task(self):
        self.gate_task.lifecycle_status = "ready"
        self.db.commit()
        check = {"lifecycle_status": "ready", "planned_start_date": "2026-09-24"}
        for recipient in (self.supervisor_profile, self.pm_profile):
            # No Start Task; Report Blocker only (T4 adds it to "Task Starts Today").
            self.assertEqual(self._buttons("task.start_check", check, recipient, task=self.gate_task), ["Report Blocker"])

    def test_no_buttons_once_the_task_has_moved_on(self):
        self.task.lifecycle_status = "in_progress"
        self.db.commit()
        payload = {"before_status": "planned", "target_status": "ready"}
        self.assertEqual(self._buttons("task.status_changed", payload, self.employee_profile), [])

    # ---- U7: Add Progress button ----------------------------------------------------------

    def test_add_progress_goes_to_whoever_may_log_progress_while_in_progress(self):
        self.task.lifecycle_status = "in_progress"
        self.db.commit()
        started = {"before_status": "ready", "target_status": "in_progress", "actor_user_id": str(self.employee.id)}
        self.assertEqual(self._buttons("task.status_changed", started, self.employee_profile), ["Add Progress", "Report Blocker"])
        # An employee is assigned, so only they log progress; any member may report a blocker.
        self.assertEqual(self._buttons("task.status_changed", started, self.supervisor_profile), ["Report Blocker"])
        check = {"lifecycle_status": "in_progress", "planned_start_date": "2026-09-24"}
        # T4: the executor can also submit from the checks; EOD offers Report Delay (T7).
        self.assertEqual(
            self._buttons("task.midday_check", check, self.employee_profile),
            ["Add Progress", "Submit for Review", "Report Blocker"],
        )
        self.assertEqual(
            self._buttons("task.eod_check", check, self.employee_profile),
            ["Add Progress", "Submit for Review", "Report Delay", "Report Blocker"],
        )

    def test_add_progress_uses_a_task_button_not_a_typed_command(self):
        self.task.lifecycle_status = "in_progress"
        self.db.commit()
        message = self._render("task.midday_check", {"lifecycle_status": "in_progress"}, self.employee_profile)
        [[button, submit], [report]] = message.button_rows()
        self.assertEqual(button["callback_data"], f"t1:ap:{self.task.id.hex}")
        self.assertEqual(submit["callback_data"], f"t1:sb:{self.task.id.hex}")
        self.assertNotIn("Reply with", message.text_for_buttons())

    def test_no_add_progress_once_submitted(self):
        self.task.lifecycle_status = "submitted"
        self.db.commit()
        check = {"lifecycle_status": "submitted", "planned_start_date": "2026-09-24"}
        # No Add Progress or Submit once submitted; Report Delay and Report Blocker stay.
        self.assertEqual(self._buttons("task.eod_check", check, self.employee_profile), ["Report Delay", "Report Blocker"])

    # ---- U8: review message built from the submission snapshot ------------------------------

    def _update(self, note, *, files=(), by=None, task=None) -> TaskProgressUpdate:
        update = TaskProgressUpdate(
            task_id=(task or self.task).id, project_id=self.project.id, update_type="evidence" if files else "note",
            note=note, submitted_by=(by or self.employee).id, source="telegram",
        )
        self.db.add(update)
        self.db.flush()
        for filename, mime in files:
            file_object = FileObject(
                storage_key=f"{uuid.uuid4().hex}", original_filename=filename, mime_type=mime, size_bytes=10,
                checksum="x", uploaded_by=self.employee.id,
            )
            self.db.add(file_object)
            self.db.flush()
            self.db.add(TaskEvidence(task_progress_update_id=update.id, file_id=file_object.id, evidence_type="photo"))
        self.db.commit()
        return update

    def _submitted(self, *updates) -> dict:
        return {
            "before_status": "in_progress", "target_status": "submitted", "actor_user_id": str(self.employee.id),
            "submitted_by": str(self.employee.id), "progress_update_ids": [str(u.id) for u in updates],
        }

    def test_review_message_shows_the_submission_and_sends_its_files_to_reviewers(self):
        first = self._update("Framing done", files=[("east.jpg", "image/jpeg")])
        second = self._update("Test report attached", files=[("report.pdf", "application/pdf")])
        self.task.lifecycle_status = "submitted"
        self.db.commit()
        payload = self._submitted(first, second)

        review = self._render("task.status_changed", payload, self.supervisor_profile)
        self.assertIn("Latest note: Test report attached", review.text)
        self.assertIn("Evidence: 1 photo, 1 PDF", review.text)
        self.assertIn("Verify it, or reject it with a reason.", review.text)
        self.assertEqual([a.caption for a in review.attachments], ["east.jpg", "report.pdf"])

        own_copy = self._render("task.status_changed", payload, self.employee_profile)
        self.assertIn("<b>Submitted for Review</b>", own_copy.text)
        self.assertEqual(own_copy.attachments, ())

    def test_review_message_uses_the_snapshot_not_the_live_task(self):
        submitted = self._update("What was submitted", files=[("before.jpg", "image/jpeg")])
        payload = self._submitted(submitted)
        # Progress logged later (a later cycle) must not leak into this review.
        self._update("Logged after the submission", files=[("after.jpg", "image/jpeg")])

        review = self._render("task.status_changed", payload, self.pm_profile)
        self.assertIn("Latest note: What was submitted", review.text)
        self.assertEqual([a.caption for a in review.attachments], ["before.jpg"])

    def test_at_most_five_files_are_sent(self):
        update = self._update("Lots of photos", files=[(f"p{i}.jpg", "image/jpeg") for i in range(7)])
        review = self._render("task.status_changed", self._submitted(update), self.supervisor_profile)
        self.assertEqual(len(review.attachments), 5)
        self.assertIn("7 photos (first 5 sent below)", review.text)

    def test_a_submission_without_files_says_so(self):
        update = self._update("Note only")
        review = self._render("task.status_changed", self._submitted(update), self.supervisor_profile)
        self.assertIn("Evidence: No files", review.text)
        self.assertEqual(review.attachments, ())

    # ---- U9: Verify / Reject buttons on the review message --------------------------------------

    def _submitted_task(self, by=None) -> dict:
        by = by or self.employee
        update = self._update("Work done", by=by)
        self.task.lifecycle_status = "submitted"
        self.db.commit()
        payload = self._submitted(update)
        payload["submitted_by"] = payload["actor_user_id"] = str(by.id)
        return payload

    def test_reviewers_get_verify_and_reject_carrying_the_submission_token(self):
        payload = self._submitted_task()
        token = max(uuid.UUID(i) for i in payload["progress_update_ids"]).hex[:8]
        for reviewer in (self.supervisor_profile, self.pm_profile):
            message = self._render("task.status_changed", payload, reviewer)
            [[verify, reject]] = message.button_rows()
            self.assertEqual((verify["text"], reject["text"]), ("Verify", "Reject"))
            self.assertEqual(verify["callback_data"], f"t1:vf:{self.task.id.hex}:{token}")
            self.assertEqual(reject["callback_data"], f"t1:vr:{self.task.id.hex}:{token}")

    def test_a_supervisor_who_did_the_work_gets_no_buttons_but_the_pm_does(self):
        """AE5: nobody verifies their own submission (Admin excepted)."""
        payload = self._submitted_task(by=self.supervisor)
        self.assertEqual(self._buttons("task.status_changed", payload, self.supervisor_profile), [])
        self.assertEqual(self._buttons("task.status_changed", payload, self.pm_profile), ["Verify", "Reject"])

    def test_no_review_buttons_for_an_older_submission_or_a_decided_task(self):
        payload = self._submitted_task()
        # A later cycle: this submission was reviewed (rejected) and a new one
        # is now waiting - the realistic way a review message becomes old.
        for update in self.db.query(TaskProgressUpdate).all():
            update.reviewed_at = datetime.now(timezone.utc)
        self._update("The next cycle's work")
        self.assertEqual(self._buttons("task.status_changed", payload, self.supervisor_profile), [])

        self.db.query(TaskProgressUpdate).delete()
        self.db.commit()
        payload = self._submitted_task()
        self.task.lifecycle_status = "completed"  # decided in the Web App before the message went out
        self.db.commit()
        self.assertEqual(self._buttons("task.status_changed", payload, self.supervisor_profile), [])

    def test_approval_gate_submission_has_no_verify_buttons(self):
        update = self._update("Permit filed")
        self.gate_task.lifecycle_status = "submitted"
        self.db.commit()
        payload = self._submitted(update)
        for recipient in (self.supervisor_profile, self.pm_profile):
            self.assertNotIn("Verify", self._buttons("task.status_changed", payload, recipient, task=self.gate_task))

    # ---- U10: PM approval request -------------------------------------------------------------

    def _class_a_verified_by(self, verifier: User) -> dict:
        """class_a work verified by `verifier` and now awaiting approval."""
        update = self._update("Structural check done", files=[("beam.jpg", "image/jpeg")], task=self.class_a)
        update.reviewed_at = datetime.now(timezone.utc)
        verification = TaskVerification(
            task_id=self.class_a.id, submission_update_id=update.id, decision="verified", verified_by=verifier.id,
        )
        self.db.add(verification)
        self.class_a.lifecycle_status = "verified"
        self.db.commit()
        return {
            "decision": "verified", "verified_by": str(verifier.id), "verification_id": str(verification.id),
            "submitted_by": str(self.employee.id), "progress_update_ids": [str(update.id)],
        }

    def _admin_profile(self) -> EmployeeProfile:
        profile = EmployeeProfile(user_id=self.admin.id, employee_code="E-ADM", designation="Admin", availability="available")
        self.db.add(profile)
        self.db.commit()
        return profile

    def test_approval_request_shows_the_verified_submission_and_its_files(self):
        payload = self._class_a_verified_by(self.supervisor)
        pm = self._render("task.verification_recorded", payload, self.pm_profile, task=self.class_a)
        self.assertIn("Submitted by: Rohan Employee", pm.text)
        self.assertIn("Latest note: Structural check done", pm.text)
        self.assertIn("Evidence: 1 photo", pm.text)
        self.assertEqual([a.caption for a in pm.attachments], ["beam.jpg"])
        [[approve, _]] = pm.button_rows()
        self.assertEqual(approve["callback_data"], f"t1:pa:{self.class_a.id.hex}:{payload['verification_id'].replace('-', '')[:8]}")

    def test_a_pm_who_verified_as_fallback_gets_no_approval_buttons(self):
        payload = self._class_a_verified_by(self.pm)  # the PM is not the Supervisor
        admin = self._admin_profile()
        pm = self._render("task.verification_recorded", payload, self.pm_profile, task=self.class_a)
        self.assertEqual(pm.button_rows(), [])
        self.assertIn("a different PM or an Admin must approve it", pm.text)
        # The Admin may approve this cycle.
        admin_copy = self._render("task.verification_recorded", payload, admin, task=self.class_a)
        self.assertEqual([b["text"] for row in admin_copy.button_rows() for b in row], ["Approve", "Reject"])

    def test_when_nobody_can_approve_the_fallback_pm_is_told_so(self):
        # Only PM verified as fallback; the only Admin is deactivated.
        payload = self._class_a_verified_by(self.pm)
        self.admin.active = False
        self.db.commit()
        pm = self._render("task.verification_recorded", payload, self.pm_profile, task=self.class_a)
        self.assertEqual(pm.button_rows(), [])
        self.assertIn(
            "No one else can approve this yet - an Admin or another PM must be added to the project.", pm.text,
        )

    def test_approval_buttons_disappear_once_decided(self):
        payload = self._class_a_verified_by(self.supervisor)
        self.class_a.lifecycle_status = "completed"
        self.db.commit()
        self.assertEqual(self._buttons("task.verification_recorded", payload, self.pm_profile, task=self.class_a), [])

    # ---- UI clarity patch: Task Type / Approval Flow (display only) ------------------------

    def test_standard_work_review_shows_task_type_without_a_flow_line(self):
        message = self._render("task.status_changed", self._submitted_task(), self.supervisor_profile)
        self.assertIn("Task Type: Standard", message.text)
        self.assertNotIn("Approval Flow", message.text)

    def test_class_a_approval_request_shows_type_and_two_step_flow(self):
        message = self._render(
            "task.verification_recorded", self._class_a_verified_by(self.supervisor), self.pm_profile, task=self.class_a,
        )
        self.assertIn("Task Type: Class A", message.text)
        self.assertIn("Approval Flow: Supervisor Verification → PM Approval", message.text)

    def test_approval_gate_shows_direct_pm_approval_even_with_a_class_a_class(self):
        # Templates seed approval-gate tasks with task_class "class_a"; the
        # backend classifies by task_kind first, and so does the message.
        self.gate_task.task_class = "class_a"
        update = self._update("Permit filed", task=self.gate_task)
        self.gate_task.lifecycle_status = "submitted"
        self.db.commit()
        message = self._render("task.status_changed", self._submitted(update), self.pm_profile, task=self.gate_task)
        self.assertIn("Task Type: Approval Gate", message.text)
        self.assertIn("Approval Flow: Direct PM Approval", message.text)
        self.assertNotIn("Class A", message.text)

    def test_task_type_appears_on_assignment_and_rework_but_not_on_unrelated_messages(self):
        assigned = self._render(
            "task.support_assigned", {"employee_id": str(self.employee_profile.id)}, self.employee_profile,
        )
        self.assertIn("Task Type: Standard", assigned.text)
        self.assertNotIn("Approval Flow", assigned.text)
        rework = self._render(
            "task.verification_recorded", {"decision": "rejected", "remarks": "Redo", "verified_by": str(self.supervisor.id)},
            self.employee_profile,
        )
        self.assertIn("Task Type: Standard", rework.text)
        for event_type, payload in (
            ("task.blocker_created", {"type": "Material", "description": "Late"}),
            ("task.midday_check", {"lifecycle_status": "in_progress"}),
            ("task.status_changed", {"before_status": "planned", "target_status": "ready"}),
        ):
            with self.subTest(event_type=event_type):
                self.assertNotIn("Task Type", self._render(event_type, payload, self.employee_profile).text)

    def test_milestones_get_no_task_type(self):
        milestone = self._task("T099", "Handover milestone", task_class=None, task_kind="milestone")
        self.db.commit()
        message = self._render(
            "task.approval_recorded", {"decision": "approved", "decided_by": str(self.pm.id)}, self.pm_profile, task=milestone,
        )
        self.assertNotIn("Task Type", message.text)

    def test_missing_ids_degrade_to_placeholders(self):
        for event_type in TASK_RENDERERS:
            with self.subTest(event_type=event_type):
                message = render_telegram(self.db, event_type, {"task_id": "not-a-uuid"}, None)
                self.assertIn("Unknown task", message.text)


if __name__ == "__main__":
    unittest.main()
