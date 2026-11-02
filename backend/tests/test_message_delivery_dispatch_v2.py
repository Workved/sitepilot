from __future__ import annotations

import inspect
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.message_dispatch as message_dispatch_module
from app.execution_models import (
    MessageDelivery,
    OutboxEvent,
    ProjectExternalApproval,
    Task,
    TaskSupportAssignment,
)
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2AuditEvent, V2Project, V2ProjectExternalGate, V2ProjectMembership
from app.services.message_dispatch import MessageDispatchService
from app.services.message_templates import DEFAULT_TEMPLATE, TemplateSpec, render_components, resolve
from app.template_models import V2Template, V2TemplateVersion
from app.vendor_models import ProjectVendor, TaskVendorAssignment, V2Vendor, V2VendorContact


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


PM_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
SUPERVISOR_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")
ADMIN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
INTERNAL_EMPLOYEE_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd4")


class MessageDeliveryDispatchTests(unittest.TestCase):
    """Phase 2 U5: message delivery tracking + sandbox provider adapter (R7).

    Exercises `MessageDispatchService.process_pending` directly against a
    SQLite in-memory harness (ATTACHed `siteops_v2` schema), following the
    same pattern established in test_outbox_emission_v2.py. This unit's
    entry point (`process_pending`) is an internal dispatch process, not a
    user-facing route, so tests call the service directly rather than via
    the FastAPI TestClient.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")
            # V2ProjectExternalGate's broad_mapping_text CHECK constraint
            # calls btrim() (a Postgres-ism) - SQLite has no such builtin,
            # so it must be registered here, same as
            # test_project_gate_assignment_v2.py / test_inbound_message_matching_v2.py.
            dbapi_connection.create_function("btrim", 1, lambda value: value.strip() if value is not None else None)

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
            V2ProjectExternalGate.__table__,
            ProjectExternalApproval.__table__,
            Task.__table__,
            OutboxEvent.__table__,
            MessageDelivery.__table__,
            V2Vendor.__table__,
            V2VendorContact.__table__,
            ProjectVendor.__table__,
            TaskVendorAssignment.__table__,
            TaskSupportAssignment.__table__,
            V2AuditEvent.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

    def tearDown(self):
        self.engine.dispose()

    # ---- seeding ---------------------------------------------------------

    def _seed(self):
        with self.Session.begin() as session:
            pm = User(
                id=PM_ID, name="PM", email="pm@example.com", phone="9000000010",
                role=UserRole.project_manager, active=True,
            )
            supervisor = User(
                id=SUPERVISOR_ID, name="Supervisor", email="supervisor@example.com", phone="9000000020",
                role=UserRole.supervisor, active=True,
            )
            admin = User(
                id=ADMIN_ID, name="Admin", email="admin@example.com", phone="9000000050",
                role=UserRole.admin, active=True,
            )
            internal_employee = User(
                id=INTERNAL_EMPLOYEE_ID, name="Internal", email="internal@example.com", phone="9000000060",
                role=UserRole.internal_employee, active=True,
            )
            session.add_all([pm, supervisor, admin, internal_employee])
            session.flush()

            pm_employee = EmployeeProfile(user_id=PM_ID, employee_code="PM-001", designation="PM", availability="available")
            supervisor_employee = EmployeeProfile(
                user_id=SUPERVISOR_ID, employee_code="SUP-001", designation="Supervisor", availability="available",
            )
            admin_employee = EmployeeProfile(
                user_id=ADMIN_ID, employee_code="ADM-001", designation="Admin", availability="available",
            )
            internal_employee_profile = EmployeeProfile(
                user_id=INTERNAL_EMPLOYEE_ID, employee_code="INT-001", designation="Internal Employee", availability="available",
            )
            session.add_all([pm_employee, supervisor_employee, admin_employee, internal_employee_profile])
            session.flush()
            self.pm_employee_id = pm_employee.id
            self.supervisor_employee_id = supervisor_employee.id
            self.admin_employee_id = admin_employee.id
            self.internal_employee_employee_id = internal_employee_profile.id

            project = V2Project(
                code="PRJ-001", name="Test Project", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=PM_ID,
            )
            session.add(project)
            session.flush()
            self.project_id = project.id

            session.add_all([
                V2ProjectMembership(
                    project_id=project.id, employee_id=pm_employee.id, project_role="project_manager",
                    assigned_by=PM_ID, assignment_reason="seed",
                ),
                V2ProjectMembership(
                    project_id=project.id, employee_id=supervisor_employee.id, project_role="site_supervisor",
                    assigned_by=PM_ID, assignment_reason="seed",
                ),
                V2ProjectMembership(
                    project_id=project.id, employee_id=internal_employee_profile.id, project_role="internal_employee",
                    assigned_by=PM_ID, assignment_reason="seed",
                ),
            ])

            # A second project with ONLY a PM membership - used to isolate
            # the retry test to exactly one recipient.
            project2 = V2Project(
                code="PRJ-002", name="Test Project 2", client_name="Client", site_address="Site",
                start_date=date(2026, 8, 1), status="active", created_by=PM_ID,
            )
            session.add(project2)
            session.flush()
            self.project2_id = project2.id
            session.add(V2ProjectMembership(
                project_id=project2.id, employee_id=pm_employee.id, project_role="project_manager",
                assigned_by=PM_ID, assignment_reason="seed",
            ))

            task = Task(
                project_id=project.id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T001", template_sequence=1, title="Task 1",
                schedule_classification="execution", applicability="mandatory",
                evidence_required=False, lifecycle_status="planned",
            )
            session.add(task)
            session.flush()
            self.task_id = task.id

            vendor = V2Vendor(
                name="Electrical Co", contact_person="Ravi", phone="9000000030",
                status="active", engagement_type="main",
            )
            session.add(vendor)
            session.flush()
            self.vendor_id = vendor.id

            contact = V2VendorContact(vendor_id=vendor.id, name="Ravi", phone="9000000040", is_primary=True)
            session.add(contact)
            session.flush()
            self.vendor_contact_id = contact.id

    # ---- helpers -----------------------------------------------------

    def _create_event(
        self, session, *, event_type, aggregate_type, aggregate_id, payload=None, key=None, created_at=None,
    ) -> uuid.UUID:
        ev = OutboxEvent(
            event_type=event_type, aggregate_type=aggregate_type, aggregate_id=aggregate_id,
            payload=payload or {}, idempotency_key=key or f"test:{uuid.uuid4()}", status="pending",
        )
        if created_at is not None:
            # SQLite's server-side now() has one-second resolution; ordering
            # tests need distinct, explicit times.
            ev.created_at = created_at
        session.add(ev)
        session.flush()
        return ev.id

    def _deliveries_for(self, event_id: uuid.UUID) -> list[MessageDelivery]:
        with self.Session() as session:
            return list(session.scalars(
                select(MessageDelivery).where(MessageDelivery.outbox_event_id == event_id)
            ).all())

    def _make_gate_approval(self, *, assigned_to_user_id=None) -> uuid.UUID:
        with self.Session.begin() as session:
            gate = V2ProjectExternalGate(
                project_id=self.project_id, original_code="E001", template_sequence=1,
                approval_name="Fire NOC", mapping_classification="exact",
                applicability_state="applicable", blocking=True,
                accountable_pm_user_id=PM_ID, source_type="project_manual",
            )
            session.add(gate)
            session.flush()
            approval = ProjectExternalApproval(
                project_id=self.project_id, project_gate_id=gate.id,
                status="assigned" if assigned_to_user_id else "unassigned",
                assigned_to_user_id=assigned_to_user_id,
                assigned_by=ADMIN_ID if assigned_to_user_id else None,
            )
            session.add(approval)
            session.flush()
            return approval.id

    def _set_phone(self, user_id: uuid.UUID, phone: str | None) -> None:
        with self.Session() as session:
            user = session.get(User, user_id)
            user.phone = phone
            session.add(user)
            session.commit()

    def _make_vendor_assignment(self, *, status: str = "pending_ack") -> uuid.UUID:
        with self.Session.begin() as session:
            assignment = TaskVendorAssignment(
                task_id=self.task_id, project_id=self.project_id, vendor_id=self.vendor_id,
                status=status, assigned_by=PM_ID,
            )
            session.add(assignment)
            session.flush()
            return assignment.id

    def _make_support_assignment(self, *, status: str = "active") -> uuid.UUID:
        from datetime import datetime, timezone

        with self.Session.begin() as session:
            assignment = TaskSupportAssignment(
                task_id=self.task_id, project_id=self.project_id, employee_id=self.internal_employee_employee_id,
                responsibility="Assist supervisor", status=status, assigned_by=PM_ID,
                ends_at=datetime.now(timezone.utc) if status == "ended" else None,
            )
            session.add(assignment)
            session.flush()
            return assignment.id

    # ---- 1. happy path: task event -> PM + Supervisor both dispatched -----

    def test_task_event_dispatches_to_pm_and_supervisor(self):
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:1",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 2)
        for delivery in deliveries:
            self.assertEqual(delivery.status, "sent")
            self.assertIsNotNone(delivery.provider_message_id)
            self.assertEqual(delivery.attempt_count, 1)
            # `MessageDelivery.template` now stores the registry-mapped Meta
            # template name, not the raw `event_type` string (Phase 1a).
            self.assertEqual(delivery.template, "task_status_update")
        recipient_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(recipient_ids, {self.pm_employee_id, self.supervisor_employee_id})

    # ---- 2. happy path: vendor_assigned adds the vendor's primary contact -

    def test_vendor_assigned_event_adds_vendor_contact_recipient(self):
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.vendor_assigned", aggregate_type="task",
                aggregate_id=self.task_id,
                payload={
                    "task_id": str(self.task_id), "project_id": str(self.project_id),
                    "assignment_id": str(uuid.uuid4()), "vendor_id": str(self.vendor_id),
                },
                key="test:2",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 3)

        vendor_rows = [d for d in deliveries if d.recipient_vendor_contact_id is not None]
        self.assertEqual(len(vendor_rows), 1)
        self.assertEqual(vendor_rows[0].recipient_vendor_contact_id, self.vendor_contact_id)
        self.assertEqual(vendor_rows[0].recipient_phone, "9000000040")
        self.assertEqual(vendor_rows[0].status, "sent")

        employee_rows = [d for d in deliveries if d.recipient_employee_id is not None]
        self.assertEqual({d.recipient_employee_id for d in employee_rows}, {self.pm_employee_id, self.supervisor_employee_id})

    # ---- 3. edge case: retry after a failed delivery ----------------------

    def test_retry_after_missing_phone_corrected_increments_attempt_count_single_row(self):
        self._set_phone(PM_ID, "")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project.role_change_requested", aggregate_type="project",
                aggregate_id=self.project2_id, payload={}, key="test:3",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].status, "failed")
        self.assertEqual(deliveries[0].attempt_count, 1)
        self.assertEqual(deliveries[0].failure_code, "missing_phone")

        with self.Session() as session:
            outbox_event = session.get(OutboxEvent, event_id)
            self.assertEqual(outbox_event.status, "dispatched")

        # Correct the phone, then run process_pending() again - the event
        # is 'dispatched' but still carries a 'failed' delivery, so it is
        # re-selected for retry.
        self._set_phone(PM_ID, "9000000099")

        with self.Session() as session:
            processed_again = MessageDispatchService(session).process_pending()
        self.assertEqual(processed_again, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 1, "retry must update the existing row, not create a second one")
        self.assertEqual(deliveries[0].attempt_count, 2)
        self.assertEqual(deliveries[0].status, "sent")
        self.assertIsNotNone(deliveries[0].provider_message_id)
        self.assertEqual(deliveries[0].recipient_phone, "9000000099")

    # ---- 4. error path: one recipient's missing phone doesn't block others

    def test_recipient_without_phone_does_not_block_other_recipients(self):
        self._set_phone(SUPERVISOR_ID, None)

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:4",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 2)

        by_employee = {d.recipient_employee_id: d for d in deliveries}
        supervisor_delivery = by_employee[self.supervisor_employee_id]
        pm_delivery = by_employee[self.pm_employee_id]

        self.assertEqual(supervisor_delivery.status, "failed")
        self.assertEqual(supervisor_delivery.failure_code, "missing_phone")
        self.assertIsNotNone(supervisor_delivery.failure_reason)

        self.assertEqual(pm_delivery.status, "sent")
        self.assertIsNotNone(pm_delivery.provider_message_id)

    # ---- 5. Super Admin can never be selected as a recipient --------------

    def test_super_admin_role_string_never_used_as_an_included_recipient_filter(self):
        """Structural proof (BR-004/R7): `_resolve_recipients` (and its
        helpers) only ever query
        `V2ProjectMembership.project_role in (project_manager,
        site_supervisor)`. `project_role` itself can never hold
        `'super_admin'` (see app.project_models.V2ProjectMembership), so a
        Super Admin - who acts on projects without being a project member -
        structurally cannot be resolved as a notification recipient.

        This is asserted two ways: (a) by inspecting `_ACCOUNTABLE_ROLES`,
        the sole role allow-list `_resolve_pm_supervisor_recipients` uses,
        and (b) by grepping the module source to confirm 'super_admin'
        never appears as an included filter value (only ever, if at all,
        in prose/comments)."""
        self.assertEqual(
            set(message_dispatch_module._ACCOUNTABLE_ROLES), {"project_manager", "site_supervisor"},
        )
        self.assertNotIn("super_admin", message_dispatch_module._ACCOUNTABLE_ROLES)

        source = inspect.getsource(message_dispatch_module)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "super_admin" in line:
                # The only place 'super_admin' may appear in code (not a
                # comment/docstring line) is inside a string literal used
                # purely for prose - never as a `==`/`in (...)` filter
                # value compared against project_role. Fail loudly if a
                # code line uses it as a filter.
                self.assertNotRegex(
                    line, r"project_role\s*(==|in)\s*.*super_admin",
                    f"'super_admin' used as a project_role filter: {line!r}",
                )

        # End-to-end: even though a super_admin actor drives most of this
        # codebase's mutation routes, they are never themselves resolved as
        # a message recipient because they hold no V2ProjectMembership row
        # with project_role in ('project_manager', 'site_supervisor').
        with self.Session() as session:
            recipients = MessageDispatchService(session)._resolve_pm_supervisor_recipients(self.project_id)
        self.assertTrue(all(r.employee_id in (self.pm_employee_id, self.supervisor_employee_id) for r in recipients))

    # ---- 6. verification: dispatched events are a safe no-op to reprocess -

    def test_process_pending_marks_dispatched_and_rerun_is_a_safe_no_op(self):
        with self.Session() as session:
            event_id_1 = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:6a",
            )
            event_id_2 = self._create_event(
                session, event_type="project.role_change_requested", aggregate_type="project",
                aggregate_id=self.project_id, payload={}, key="test:6b",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 2)

        with self.Session() as session:
            for event_id in (event_id_1, event_id_2):
                outbox_event = session.get(OutboxEvent, event_id)
                self.assertEqual(outbox_event.status, "dispatched")

        rows_after_first_run = len(self._deliveries_for(event_id_1)) + len(self._deliveries_for(event_id_2))

        with self.Session() as session:
            processed_again = MessageDispatchService(session).process_pending()
        self.assertEqual(processed_again, 0, "already-dispatched events with no failed deliveries must not be re-selected")

        rows_after_second_run = len(self._deliveries_for(event_id_1)) + len(self._deliveries_for(event_id_2))
        self.assertEqual(rows_after_first_run, rows_after_second_run)

    # ---- 7. Phase 1a: template registry fallback + component rendering ----

    def test_unmapped_event_type_falls_back_to_default_template_not_the_raw_string(self):
        spec = resolve("some.event.type.nobody.registered")
        self.assertEqual(spec, DEFAULT_TEMPLATE)
        self.assertEqual(spec.meta_template_name, "generic_notification")
        self.assertNotEqual(spec.meta_template_name, "some.event.type.nobody.registered")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="some.event.type.nobody.registered", aggregate_type="project",
                aggregate_id=self.project_id, payload={}, key="test:7a",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertTrue(deliveries)
        for delivery in deliveries:
            self.assertEqual(delivery.template, "generic_notification")

    def test_render_components_builds_meta_body_parameters_shape_from_payload(self):
        spec = TemplateSpec("sample_template", "en", ("task_id", "target_status"))
        payload = {"task_id": "T001", "target_status": "ready", "unused_key": "ignored"}

        components = render_components(spec, payload)

        self.assertEqual(
            components,
            [{"type": "body", "parameters": [
                {"type": "text", "text": "T001"},
                {"type": "text", "text": "ready"},
            ]}],
        )

    def test_render_components_missing_or_blank_payload_value_renders_as_dash(self):
        # Meta rejects empty-string template parameters.
        spec = TemplateSpec("sample_template", "en", ("missing_key", "none_key", "blank_key"))
        components = render_components(spec, {"none_key": None, "blank_key": "  "})
        self.assertEqual(components, [{"type": "body", "parameters": [{"type": "text", "text": "-"}] * 3}])

    def test_render_components_template_without_placeholders_sends_no_components(self):
        self.assertEqual(render_components(TemplateSpec("sample_template", "en", ()), {"x": 1}), [])

    # ---- WhatsApp gate workflow plan (U14): new event-type registry entries

    NEW_EVENT_TYPE_PAYLOADS = {
        "project.activated": {"project_id": "p1", "project_name": "Futurex"},
        "project.member_added": {"project_id": "p1", "employee_id": "e1", "project_role": "internal_employee"},
        "project.vendor_mapped": {"project_id": "p1", "vendor_id": "v1"},
        "project_external_approval.accepted": {
            "approval_id": "a1", "project_id": "p1", "response": "accepted", "note": "ok",
        },
        "project_external_approval.declined": {
            "approval_id": "a1", "project_id": "p1", "response": "declined", "note": "ok",
        },
        "user.created": {"user_id": "u1", "name": "Field Hand"},
        "user.offboarded": {"user_id": "u1", "name": "Field Hand"},
        "gate_confirmation.accepted": {"actor_user_id": "u1", "gate_name": "NOC", "project_name": "Futurex"},
        "gate_confirmation.declined": {"actor_user_id": "u1", "gate_name": "NOC", "project_name": "Futurex"},
        "gate_confirmation.status_recorded": {
            "actor_user_id": "u1", "gate_name": "NOC", "project_name": "Futurex", "health": "on_track",
        },
        "gate_confirmation.session_opened": {"actor_user_id": "u1", "gate_name": "NOC", "project_name": "Futurex"},
        "gate_confirmation.session_closed": {"actor_user_id": "u1", "gate_name": "NOC", "project_name": "Futurex"},
        "gate_confirmation.decided": {
            "actor_user_id": "u1", "gate_name": "NOC", "project_name": "Futurex", "decision": "approved",
        },
    }

    def test_every_new_event_type_resolves_to_a_tbd_placeholder_template(self):
        for event_type in self.NEW_EVENT_TYPE_PAYLOADS:
            with self.subTest(event_type=event_type):
                spec = resolve(event_type)
                self.assertNotEqual(spec, DEFAULT_TEMPLATE)
                self.assertTrue(
                    spec.meta_template_name.startswith("TBD_"),
                    f"{event_type} resolved to {spec.meta_template_name!r}, expected a TBD_ placeholder",
                )

    def test_every_new_event_type_renders_one_body_parameter_per_variable(self):
        for event_type, payload in self.NEW_EVENT_TYPE_PAYLOADS.items():
            with self.subTest(event_type=event_type):
                spec = resolve(event_type)
                components = render_components(spec, payload)
                self.assertEqual(len(components[0]["parameters"]), len(spec.variable_order))

    def test_widened_gate_assignment_spec_renders_five_body_parameters(self):
        spec = resolve("project_external_approval.assigned")
        payload = {
            "approval_id": "a1", "assigned_to_user_id": "u1",
            "gate_name": "Fire NOC", "project_name": "Futurex", "due_date": "2026-12-25",
        }

        components = render_components(spec, payload)

        parameters = components[0]["parameters"]
        self.assertEqual(len(parameters), 5)
        rendered_text = [p["text"] for p in parameters]
        self.assertIn("Fire NOC", rendered_text)
        self.assertIn("Futurex", rendered_text)
        self.assertIn("2026-12-25", rendered_text)

    def test_widened_gate_reassignment_spec_also_renders_five_body_parameters(self):
        spec = resolve("project_external_approval.reassigned")
        payload = {
            "approval_id": "a1", "assigned_to_user_id": "u2",
            "gate_name": "Fire NOC", "project_name": "Futurex", "due_date": "No due date set",
        }
        components = render_components(spec, payload)
        self.assertEqual(len(components[0]["parameters"]), 5)

    # ---- 8. Phase 1b: project_external_approval recipient resolution ------

    def test_project_external_approval_assigned_event_resolves_admin_and_assignee(self):
        approval_id = self._make_gate_approval(assigned_to_user_id=INTERNAL_EMPLOYEE_ID)

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project_external_approval.assigned", aggregate_type="project_external_approval",
                aggregate_id=approval_id,
                payload={"approval_id": str(approval_id), "assigned_to_user_id": str(INTERNAL_EMPLOYEE_ID)},
                key="test:8a",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        recipient_employee_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(recipient_employee_ids, {self.internal_employee_employee_id, self.admin_employee_id})
        for delivery in deliveries:
            self.assertEqual(delivery.status, "sent")

    def test_project_external_approval_unassigned_gate_resolves_only_admin(self):
        # No assignee yet - `_resolve_gate_assignee_recipient` returns []
        # (genuinely unresolvable), so only Admin is a recipient.
        approval_id = self._make_gate_approval()

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project_external_approval.submitted", aggregate_type="project_external_approval",
                aggregate_id=approval_id, payload={"approval_id": str(approval_id)}, key="test:8b",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        recipient_employee_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(recipient_employee_ids, {self.admin_employee_id})

    def test_task_approval_recorded_event_resolves_admin_as_cc_alongside_pm_supervisor(self):
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.approval_recorded", aggregate_type="task",
                aggregate_id=self.task_id, payload={"decision": "approved"}, key="test:8c",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        recipient_employee_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(
            recipient_employee_ids,
            {self.pm_employee_id, self.supervisor_employee_id, self.admin_employee_id},
        )

    # ---- event selection: new events are never starved by retries ----------

    def _make_failing_events(self, count: int) -> list[uuid.UUID]:
        """`count` older events whose only recipient (project 2's PM, no
        phone) fails every attempt, left 'dispatched' with a failed delivery
        - the retry set that used to fill the whole batch."""
        self._set_phone(PM_ID, None)
        oldest = datetime.now(timezone.utc) - timedelta(hours=1)
        with self.Session() as session:
            ids = [
                self._create_event(
                    session, event_type="project.activated", aggregate_type="project",
                    aggregate_id=self.project2_id, payload={}, key=f"test:failing-{i}",
                    created_at=oldest + timedelta(seconds=i),
                )
                for i in range(count)
            ]
            session.commit()
        with self.Session() as session:
            MessageDispatchService(session).process_pending(limit=count)
        for event_id in ids:
            self.assertEqual([d.status for d in self._deliveries_for(event_id)], ["failed"])
        return ids

    def test_new_event_is_not_starved_by_a_full_batch_of_failing_retries(self):
        self._make_failing_events(50)

        with self.Session() as session:
            new_event_id = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:new-after-failures",
                created_at=datetime.now(timezone.utc),  # newer than every failing event
            )
            session.commit()

        with self.Session() as session:
            MessageDispatchService(session).process_pending(limit=50)

        with self.Session() as session:
            self.assertEqual(session.get(OutboxEvent, new_event_id).status, "dispatched")
        # The Supervisor (who has a phone) was actually delivered to; the PM
        # copy fails only because this test removed the PM's phone.
        statuses = {d.recipient_employee_id: d.status for d in self._deliveries_for(new_event_id)}
        self.assertEqual(statuses[self.supervisor_employee_id], "sent")

    def test_retries_still_run_with_spare_capacity(self):
        failing_ids = self._make_failing_events(3)
        self._set_phone(PM_ID, "9000000010")  # the failure is fixed

        with self.Session() as session:
            new_event_id = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:new-with-retries",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending(limit=50)

        self.assertEqual(processed, 4)  # the new event plus all three retries
        self.assertTrue(all(d.status == "sent" for d in self._deliveries_for(new_event_id)))
        for event_id in failing_ids:
            self.assertEqual([d.status for d in self._deliveries_for(event_id)], ["sent"])

    def test_pending_events_are_selected_before_retries_oldest_first(self):
        failing_ids = self._make_failing_events(2)
        self._set_phone(PM_ID, "9000000010")  # reachable again, so the retries are eligible
        now = datetime.now(timezone.utc)
        with self.Session() as session:
            first = self._create_event(session, event_type="task.status_changed", aggregate_type="task",
                                       aggregate_id=self.task_id, payload={}, key="test:p1", created_at=now)
            second = self._create_event(session, event_type="task.status_changed", aggregate_type="task",
                                        aggregate_id=self.task_id, payload={}, key="test:p2",
                                        created_at=now + timedelta(seconds=1))
            session.commit()

        with self.Session() as session:
            selected = [e.id for e in MessageDispatchService(session)._select_events(limit=3)]

        self.assertEqual(selected, [first, second, failing_ids[0]])

    # ---- retries: unreachable recipients, reconnects, fewest attempts first --

    def test_unreachable_recipient_is_not_retried_while_still_unreachable(self):
        failing_ids = self._make_failing_events(3)

        with self.Session() as session:
            self.assertEqual(MessageDispatchService(session)._select_events(limit=50), [])
            processed = MessageDispatchService(session).process_pending(limit=50)

        self.assertEqual(processed, 0)
        for event_id in failing_ids:
            [delivery] = self._deliveries_for(event_id)
            self.assertEqual((delivery.status, delivery.failure_code, delivery.attempt_count),
                             ("failed", "missing_phone", 1))

    def _set_telegram(self, employee_id: uuid.UUID, chat_id: str | None) -> None:
        with self.Session() as session:
            profile = session.get(EmployeeProfile, employee_id)
            profile.active_channel = "telegram"
            profile.telegram_chat_id = chat_id
            session.commit()

    def test_missed_telegram_messages_are_delivered_once_the_recipient_links_telegram(self):
        from unittest.mock import MagicMock, patch

        from app.config import settings

        self._set_telegram(self.pm_employee_id, None)
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project.activated", aggregate_type="project",
                aggregate_id=self.project2_id, payload={}, key="test:missed-telegram",
            )
            session.commit()
        with self.Session() as session:
            MessageDispatchService(session).process_pending(limit=50)
        [delivery] = self._deliveries_for(event_id)
        self.assertEqual((delivery.status, delivery.failure_code), ("failed", "missing_chat_id"))

        with self.Session() as session:  # not linked yet: left alone
            self.assertEqual(MessageDispatchService(session).process_pending(limit=50), 0)

        self._set_telegram(self.pm_employee_id, "777000")
        response = MagicMock(status_code=200)
        response.json.return_value = {"ok": True, "result": {"message_id": 42}}
        original_token = settings.telegram_access_token
        settings.telegram_access_token = "test-token"
        try:
            with patch("app.services.telegram_provider.httpx.post", return_value=response) as post:
                with self.Session() as session:
                    self.assertEqual(MessageDispatchService(session).process_pending(limit=50), 1)
        finally:
            settings.telegram_access_token = original_token

        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "777000")
        [delivery] = self._deliveries_for(event_id)
        self.assertEqual((delivery.status, delivery.channel, delivery.attempt_count), ("sent", "telegram", 2))

    def test_newly_reachable_recipient_is_not_starved_by_repeatedly_failing_retries(self):
        # 50 older events whose deliveries keep failing for a non-address
        # reason and have already been retried several times.
        stuck_ids = self._make_failing_events(50)

        # A newer event whose recipient (the Supervisor) had no phone and has
        # since been given one.
        self._set_phone(SUPERVISOR_ID, None)
        with self.Session() as session:
            newer_id = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:newly-reachable",
                created_at=datetime.now(timezone.utc),
            )
            session.commit()
        with self.Session() as session:
            MessageDispatchService(session).process_pending(limit=50)
        self._set_phone(SUPERVISOR_ID, "9000000020")

        with self.Session() as session:
            for delivery in session.scalars(
                select(MessageDelivery).where(MessageDelivery.outbox_event_id.in_(stuck_ids))
            ):
                delivery.failure_code = "network_error"
                delivery.attempt_count = 3
            session.commit()

        with self.Session() as session:
            selected = [e.id for e in MessageDispatchService(session)._select_events(limit=50)]

        self.assertEqual(len(selected), 50)
        self.assertEqual(selected[0], newer_id)  # fewest attempts first, despite being newest

    def _fail_deliveries(self, event_ids, *, failure_code: str, attempt_count: int) -> None:
        with self.Session() as session:
            for delivery in session.scalars(
                select(MessageDelivery).where(MessageDelivery.outbox_event_id.in_(event_ids))
            ):
                delivery.failure_code = failure_code
                delivery.attempt_count = attempt_count
            session.commit()

    def test_delivery_is_not_retried_after_max_attempts(self):
        stuck_ids = self._make_failing_events(2)
        self._set_phone(PM_ID, "9000000021")
        self._fail_deliveries(stuck_ids, failure_code="network_error", attempt_count=message_dispatch_module._MAX_DELIVERY_ATTEMPTS)

        with self.Session() as session:
            self.assertEqual(MessageDispatchService(session)._select_events(limit=50), [])
            MessageDispatchService(session).process_pending(limit=50)
        for event_id in stuck_ids:
            [delivery] = self._deliveries_for(event_id)
            self.assertEqual((delivery.status, delivery.attempt_count), ("failed", message_dispatch_module._MAX_DELIVERY_ATTEMPTS))

    def test_template_rejection_is_never_retried(self):
        stuck_ids = self._make_failing_events(2)
        self._set_phone(PM_ID, "9000000021")
        for code in ("template_unapproved", "132001"):
            self._fail_deliveries(stuck_ids, failure_code=code, attempt_count=1)
            with self.Session() as session:
                self.assertEqual(MessageDispatchService(session)._select_events(limit=50), [], code)

    def test_transient_failure_below_the_cap_is_still_retried(self):
        stuck_ids = self._make_failing_events(1)
        self._set_phone(PM_ID, "9000000021")
        self._fail_deliveries(stuck_ids, failure_code="network_error", attempt_count=1)

        with self.Session() as session:
            MessageDispatchService(session).process_pending(limit=50)
        [delivery] = self._deliveries_for(stuck_ids[0])
        self.assertEqual((delivery.status, delivery.attempt_count, delivery.provider), ("sent", 2, "sandbox"))

    def test_retrying_one_recipient_does_not_reattempt_a_still_unreachable_one(self):
        self._set_phone(PM_ID, None)
        self._set_phone(SUPERVISOR_ID, None)
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:partial-reachable",
            )
            session.commit()
        with self.Session() as session:
            MessageDispatchService(session).process_pending(limit=50)

        self._set_phone(SUPERVISOR_ID, "9000000020")
        with self.Session() as session:
            MessageDispatchService(session).process_pending(limit=50)

        by_recipient = {d.recipient_employee_id: d for d in self._deliveries_for(event_id)}
        self.assertEqual(by_recipient[self.supervisor_employee_id].status, "sent")
        pm = by_recipient[self.pm_employee_id]
        self.assertEqual((pm.status, pm.failure_code, pm.attempt_count), ("failed", "missing_phone", 1))

    def test_gate_unassigned_reaches_previous_assignee_and_admin(self):
        # By dispatch time the gate has no assignee any more; the employee who
        # lost it is only known from the payload.
        approval_id = self._make_gate_approval(assigned_to_user_id=None)

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project_external_approval.unassigned", aggregate_type="project_external_approval",
                aggregate_id=approval_id,
                payload={"approval_id": str(approval_id), "previous_assignee_id": str(INTERNAL_EMPLOYEE_ID)},
                key="test:gate-unassigned",
            )
            session.commit()

        with self.Session() as session:
            MessageDispatchService(session).process_pending()

        recipient_employee_ids = [d.recipient_employee_id for d in self._deliveries_for(event_id)]
        self.assertCountEqual(recipient_employee_ids, [self.internal_employee_employee_id, self.admin_employee_id])

    def test_gate_reassigned_reaches_new_and_previous_assignee_once_each(self):
        approval_id = self._make_gate_approval(assigned_to_user_id=SUPERVISOR_ID)

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project_external_approval.reassigned", aggregate_type="project_external_approval",
                aggregate_id=approval_id,
                payload={
                    "approval_id": str(approval_id), "assigned_to_user_id": str(SUPERVISOR_ID),
                    "previous_assignee_id": str(INTERNAL_EMPLOYEE_ID),
                },
                key="test:gate-reassigned",
            )
            session.commit()

        with self.Session() as session:
            MessageDispatchService(session).process_pending()

        recipient_employee_ids = [d.recipient_employee_id for d in self._deliveries_for(event_id)]
        self.assertCountEqual(
            recipient_employee_ids,
            [self.supervisor_employee_id, self.internal_employee_employee_id, self.admin_employee_id],
        )

    def test_gate_assigned_does_not_add_a_previous_assignee(self):
        approval_id = self._make_gate_approval(assigned_to_user_id=INTERNAL_EMPLOYEE_ID)

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project_external_approval.assigned", aggregate_type="project_external_approval",
                aggregate_id=approval_id,
                payload={
                    "approval_id": str(approval_id), "assigned_to_user_id": str(INTERNAL_EMPLOYEE_ID),
                    "previous_assignee_id": None,
                },
                key="test:gate-assigned-no-previous",
            )
            session.commit()

        with self.Session() as session:
            MessageDispatchService(session).process_pending()

        recipient_employee_ids = [d.recipient_employee_id for d in self._deliveries_for(event_id)]
        self.assertCountEqual(recipient_employee_ids, [self.internal_employee_employee_id, self.admin_employee_id])

    def test_task_status_changed_event_does_not_resolve_admin(self):
        # task.status_changed is NOT in _ADMIN_CC_TASK_EVENTS - only PM/
        # Supervisor are resolved, same as before Phase 1b.
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.status_changed", aggregate_type="task",
                aggregate_id=self.task_id, payload={"target_status": "ready"}, key="test:8d",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        recipient_employee_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(recipient_employee_ids, {self.pm_employee_id, self.supervisor_employee_id})
        self.assertNotIn(self.admin_employee_id, recipient_employee_ids)

    def test_weekly_summary_generated_event_resolves_admin_alongside_pm_supervisor(self):
        # Plan Phase 8: report.weekly_summary_generated is aggregate_type
        # "project", which _resolve_pm_supervisor_recipients already reaches
        # PM/Supervisor through unchanged - this test is about the new
        # _ADMIN_CC_PROJECT_EVENTS allowlist widening that same branch to
        # also resolve Admin, mirroring _ADMIN_CC_TASK_EVENTS's pattern.
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="report.weekly_summary_generated", aggregate_type="project",
                aggregate_id=self.project_id,
                payload={"project_id": str(self.project_id), "report_snapshot_id": str(uuid.uuid4())},
                key="test:8e",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        recipient_employee_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(
            recipient_employee_ids,
            {self.pm_employee_id, self.supervisor_employee_id, self.admin_employee_id},
        )

    def test_role_change_requested_event_does_not_resolve_admin(self):
        # project.role_change_requested is NOT in _ADMIN_CC_PROJECT_EVENTS -
        # only PM/Supervisor are resolved, proving the allowlist is narrow
        # rather than a blanket "every project.* event reaches Admin" widening.
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project.role_change_requested", aggregate_type="project",
                aggregate_id=self.project_id, payload={}, key="test:8f",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        recipient_employee_ids = {d.recipient_employee_id for d in deliveries}
        self.assertEqual(recipient_employee_ids, {self.pm_employee_id, self.supervisor_employee_id})
        self.assertNotIn(self.admin_employee_id, recipient_employee_ids)

    # ---- 9. Phase 7: vendor + internal-employee resolution on daily prompts

    def _daily_prompt_payload(self) -> dict:
        return {
            "task_id": str(self.task_id),
            "project_id": str(self.project_id),
            "lifecycle_status": "planned",
            "planned_start_date": None,
        }

    def test_vendor_gets_only_the_day_before_reminder(self):
        # Vendors get one task reminder - the day before the task
        # (`task.prestart_warning`) - and none of the daily checks.
        self._make_vendor_assignment(status="pending_ack")

        for idx, event_type in enumerate(
            ("task.readiness_check", "task.start_check", "task.midday_check", "task.prestart_warning")
        ):
            with self.subTest(event_type=event_type):
                with self.Session() as session:
                    event_id = self._create_event(
                        session, event_type=event_type, aggregate_type="task",
                        aggregate_id=self.task_id, payload=self._daily_prompt_payload(),
                        key=f"test:9-vendor-{idx}",
                    )
                    session.commit()

                with self.Session() as session:
                    processed = MessageDispatchService(session).process_pending()
                self.assertEqual(processed, 1)

                deliveries = self._deliveries_for(event_id)
                vendor_rows = [d for d in deliveries if d.recipient_vendor_contact_id is not None]
                if event_type == "task.prestart_warning":
                    self.assertEqual([d.recipient_vendor_contact_id for d in vendor_rows], [self.vendor_contact_id])
                else:
                    self.assertEqual(vendor_rows, [], f"{event_type} must not reach the vendor")

    def test_day_before_reminder_resolves_no_vendor_when_no_assignment(self):
        # No TaskVendorAssignment at all - the Supervisor still resolves, but
        # no vendor recipient.
        for idx, event_type in enumerate(("task.prestart_warning",)):
            with self.subTest(event_type=event_type):
                with self.Session() as session:
                    event_id = self._create_event(
                        session, event_type=event_type, aggregate_type="task",
                        aggregate_id=self.task_id, payload=self._daily_prompt_payload(),
                        key=f"test:9-novendor-{idx}",
                    )
                    session.commit()

                with self.Session() as session:
                    processed = MessageDispatchService(session).process_pending()
                self.assertEqual(processed, 1)

                deliveries = self._deliveries_for(event_id)
                vendor_rows = [d for d in deliveries if d.recipient_vendor_contact_id is not None]
                self.assertEqual(vendor_rows, [])

                employee_ids = {d.recipient_employee_id for d in deliveries if d.recipient_employee_id is not None}
                self.assertIn(self.supervisor_employee_id, employee_ids)

    def test_day_before_reminder_ignores_declined_vendor_assignment(self):
        # A declined assignment means the vendor is no longer involved -
        # must resolve to no vendor recipient, same as "no assignment".
        self._make_vendor_assignment(status="declined")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.prestart_warning", aggregate_type="task",
                aggregate_id=self.task_id, payload=self._daily_prompt_payload(), key="test:9-declined",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        vendor_rows = [d for d in deliveries if d.recipient_vendor_contact_id is not None]
        self.assertEqual(vendor_rows, [])

    def test_eod_check_never_resolves_vendor_even_with_active_assignment(self):
        self._make_vendor_assignment(status="acknowledged")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.eod_check", aggregate_type="task",
                aggregate_id=self.task_id, payload=self._daily_prompt_payload(), key="test:9-eod",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        vendor_rows = [d for d in deliveries if d.recipient_vendor_contact_id is not None]
        self.assertEqual(vendor_rows, [], "task.eod_check must never resolve a vendor recipient")

        # PM/Supervisor and the Internal Employee (EOD is in
        # _EMPLOYEE_ELIGIBLE_TASK_EVENTS too) should still resolve normally.
        employee_ids = {d.recipient_employee_id for d in deliveries if d.recipient_employee_id is not None}
        self.assertIn(self.pm_employee_id, employee_ids)
        self.assertIn(self.supervisor_employee_id, employee_ids)

    def test_internal_employee_resolves_for_readiness_check(self):
        # First real coverage of `_resolve_internal_employee_recipient`
        # actually firing - `_EMPLOYEE_ELIGIBLE_TASK_EVENTS` was empty
        # before Phase 7.
        self._make_support_assignment(status="active")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.readiness_check", aggregate_type="task",
                aggregate_id=self.task_id, payload=self._daily_prompt_payload(), key="test:9-employee",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        employee_ids = {d.recipient_employee_id for d in deliveries if d.recipient_employee_id is not None}
        self.assertIn(self.internal_employee_employee_id, employee_ids)
        # PM/Supervisor still resolve alongside the support-assigned employee.
        self.assertIn(self.pm_employee_id, employee_ids)
        self.assertIn(self.supervisor_employee_id, employee_ids)

    def test_ended_support_assignment_does_not_resolve_internal_employee(self):
        self._make_support_assignment(status="ended")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.readiness_check", aggregate_type="task",
                aggregate_id=self.task_id, payload=self._daily_prompt_payload(), key="test:9-ended",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        employee_ids = {d.recipient_employee_id for d in deliveries if d.recipient_employee_id is not None}
        self.assertNotIn(self.internal_employee_employee_id, employee_ids)

    def test_support_assigned_reaches_the_assigned_employee(self):
        assignment_id = self._make_support_assignment(status="active")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.support_assigned", aggregate_type="task",
                aggregate_id=self.task_id,
                payload={
                    "task_id": str(self.task_id), "project_id": str(self.project_id),
                    "assignment_id": str(assignment_id),
                    "employee_id": str(self.internal_employee_employee_id), "responsibility": "Assist supervisor",
                },
                key="test:support-assigned",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        employee_ids = [d.recipient_employee_id for d in self._deliveries_for(event_id) if d.recipient_employee_id]
        self.assertIn(self.internal_employee_employee_id, employee_ids)
        self.assertIn(self.pm_employee_id, employee_ids)
        self.assertIn(self.supervisor_employee_id, employee_ids)

    def test_support_ended_reaches_previous_employee_after_assignment_is_inactive(self):
        assignment_id = self._make_support_assignment(status="ended")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.support_ended", aggregate_type="task",
                aggregate_id=self.task_id,
                payload={
                    "task_id": str(self.task_id), "project_id": str(self.project_id),
                    "assignment_id": str(assignment_id),
                    "previous_employee_id": str(self.internal_employee_employee_id),
                    "replacement_employee_id": None, "reason_code": "reassigned",
                },
                key="test:support-ended",
            )
            session.commit()

        with self.Session() as session:
            MessageDispatchService(session).process_pending()

        employee_ids = [d.recipient_employee_id for d in self._deliveries_for(event_id) if d.recipient_employee_id]
        self.assertIn(self.internal_employee_employee_id, employee_ids)

    def test_support_assigned_to_supervisor_does_not_duplicate_their_delivery(self):
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.support_assigned", aggregate_type="task",
                aggregate_id=self.task_id,
                payload={
                    "task_id": str(self.task_id), "project_id": str(self.project_id),
                    "assignment_id": str(uuid.uuid4()),
                    "employee_id": str(self.supervisor_employee_id), "responsibility": "Cover",
                },
                key="test:support-assigned-dup",
            )
            session.commit()

        with self.Session() as session:
            MessageDispatchService(session).process_pending()

        employee_ids = [d.recipient_employee_id for d in self._deliveries_for(event_id) if d.recipient_employee_id]
        self.assertEqual(employee_ids.count(self.supervisor_employee_id), 1)

    def test_delay_recorded_reaches_pm_supervisor_support_employee_not_vendor(self):
        # A delay reaches the people doing the work, not only PM/Supervisor:
        # the support-assigned Internal Employee too. A vendor delegated to
        # the task is not told - vendors get only their assignment messages
        # and the day-before reminder.
        self._make_support_assignment(status="active")
        self._make_vendor_assignment(status="pending_ack")

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.delay_recorded", aggregate_type="task",
                aggregate_id=self.task_id,
                payload={"task_id": str(self.task_id), "responsibility_type": "vendor", "impact_days": 2},
                key="test:9-delay",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        employee_ids = {d.recipient_employee_id for d in deliveries if d.recipient_employee_id is not None}
        self.assertEqual(
            {self.pm_employee_id, self.supervisor_employee_id, self.internal_employee_employee_id} & employee_ids,
            {self.pm_employee_id, self.supervisor_employee_id, self.internal_employee_employee_id},
        )
        self.assertEqual([d for d in deliveries if d.recipient_vendor_contact_id is not None], [])

    def test_delay_recorded_with_no_support_or_vendor_still_reaches_pm_supervisor(self):
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="task.delay_recorded", aggregate_type="task",
                aggregate_id=self.task_id,
                payload={"task_id": str(self.task_id), "responsibility_type": "internal", "impact_days": 1},
                key="test:9-delay-bare",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        employee_ids = {d.recipient_employee_id for d in deliveries if d.recipient_employee_id is not None}
        self.assertEqual({self.pm_employee_id, self.supervisor_employee_id} & employee_ids,
                          {self.pm_employee_id, self.supervisor_employee_id})
        self.assertEqual([d for d in deliveries if d.recipient_vendor_contact_id is not None], [])


    # ---- 10. U1: all-project-members + vendor recipient resolver ----------

    def test_resolve_all_project_members_returns_every_role_not_just_pm_supervisor(self):
        # Add a second Internal Employee alongside the seeded PM, Supervisor
        # and first Internal Employee - `_resolve_all_project_members` must
        # return all four, not just the two `_ACCOUNTABLE_ROLES`.
        second_internal_id = uuid.uuid4()
        with self.Session.begin() as session:
            second_internal = User(
                id=second_internal_id, name="Internal 2", email="internal2@example.com",
                phone="9000000070", role=UserRole.internal_employee, active=True,
            )
            session.add(second_internal)
            session.flush()
            second_internal_profile = EmployeeProfile(
                user_id=second_internal_id, employee_code="INT-002",
                designation="Internal Employee 2", availability="available",
            )
            session.add(second_internal_profile)
            session.flush()
            second_internal_employee_id = second_internal_profile.id
            session.add(V2ProjectMembership(
                project_id=self.project_id, employee_id=second_internal_profile.id,
                project_role="internal_employee", assigned_by=PM_ID, assignment_reason="seed",
            ))

        with self.Session() as session:
            recipients = MessageDispatchService(session)._resolve_all_project_members(self.project_id)

        employee_ids = {r.employee_id for r in recipients}
        self.assertEqual(
            employee_ids,
            {
                self.pm_employee_id, self.supervisor_employee_id,
                self.internal_employee_employee_id, second_internal_employee_id,
            },
        )

    def test_resolve_all_project_members_resolves_phoneless_member_not_silently_dropped(self):
        self._set_phone(SUPERVISOR_ID, None)

        with self.Session() as session:
            recipients = MessageDispatchService(session)._resolve_all_project_members(self.project_id)

        by_employee = {r.employee_id: r for r in recipients}
        self.assertIn(self.supervisor_employee_id, by_employee)
        self.assertEqual(by_employee[self.supervisor_employee_id].phone, "")

    def test_resolve_all_project_vendors_skips_vendor_with_no_primary_contact(self):
        with self.Session.begin() as session:
            session.add(ProjectVendor(project_id=self.project_id, vendor_id=self.vendor_id, mapped_by=PM_ID))

            vendor_no_contact = V2Vendor(
                name="Plumbing Co", contact_person="Sam", phone="9000000080",
                status="active", engagement_type="main",
            )
            session.add(vendor_no_contact)
            session.flush()
            session.add(ProjectVendor(project_id=self.project_id, vendor_id=vendor_no_contact.id, mapped_by=PM_ID))

        with self.Session() as session:
            recipients = MessageDispatchService(session)._resolve_all_project_vendors(self.project_id)

        self.assertEqual(len(recipients), 1)
        self.assertEqual(recipients[0].vendor_contact_id, self.vendor_contact_id)

    def test_resolve_all_project_vendors_with_no_mapped_vendors_returns_empty_list(self):
        with self.Session() as session:
            recipients = MessageDispatchService(session)._resolve_all_project_vendors(self.project2_id)

        self.assertEqual(recipients, [])

    def test_project_activated_event_uses_all_members_branch_not_pm_supervisor(self):
        # `project.activated` is in `_ALL_MEMBERS_PROJECT_EVENTS` - the
        # `project` branch must call `_resolve_all_project_members` INSTEAD
        # OF `_resolve_pm_supervisor_recipients`, not both, since the former
        # already includes every PM/Supervisor the latter would find.
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="project.activated", aggregate_type="project",
                aggregate_id=self.project_id, payload={}, key="test:10-activated",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        employee_ids = [d.recipient_employee_id for d in deliveries if d.recipient_employee_id is not None]
        # No duplicate delivery targets from both resolvers firing.
        self.assertEqual(len(employee_ids), len(set(employee_ids)))
        self.assertEqual(
            set(employee_ids),
            {self.pm_employee_id, self.supervisor_employee_id, self.internal_employee_employee_id},
        )

    def test_vendors_hear_only_about_their_own_project_assignment(self):
        # Activation: every mapped vendor. A new team member: no vendor. A
        # vendor mapping: only that vendor, never the other vendors.
        with self.Session() as session:
            session.add(ProjectVendor(project_id=self.project_id, vendor_id=self.vendor_id, mapped_by=PM_ID))
            session.commit()
        cases = (
            ("project.activated", {}, 1),
            ("project.member_added", {"employee_id": str(self.internal_employee_employee_id)}, 0),
            ("project.vendor_mapped", {"vendor_id": str(self.vendor_id)}, 1),
            ("project.vendor_mapped", {"vendor_id": str(uuid.uuid4())}, 0),
        )
        for idx, (event_type, payload, expected) in enumerate(cases):
            with self.subTest(event_type=event_type, expected=expected):
                with self.Session() as session:
                    event_id = self._create_event(
                        session, event_type=event_type, aggregate_type="project",
                        aggregate_id=self.project_id, payload={"project_id": str(self.project_id), **payload},
                        key=f"test:10-vendor-scope-{idx}",
                    )
                    session.commit()
                with self.Session() as session:
                    MessageDispatchService(session).process_pending()
                vendor_rows = [d for d in self._deliveries_for(event_id) if d.recipient_vendor_contact_id is not None]
                self.assertEqual(len(vendor_rows), expected)

    # ---- 11. U13: `user`-aggregate recipient resolution (R13) --------------

    def test_user_created_event_resolves_only_the_named_user_not_the_actor(self):
        # ADMIN_ID stands in for "the actor who performed the invite" here -
        # the resolver must never pick them up just because they also have
        # an EmployeeProfile; the sole recipient is the user named in the
        # payload's `user_id` (INTERNAL_EMPLOYEE_ID).
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="user.created", aggregate_type="user",
                aggregate_id=INTERNAL_EMPLOYEE_ID,
                payload={"user_id": str(INTERNAL_EMPLOYEE_ID), "name": "Internal"},
                key="test:11a",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].recipient_employee_id, self.internal_employee_employee_id)
        self.assertIsNone(deliveries[0].recipient_vendor_contact_id)
        self.assertNotEqual(deliveries[0].recipient_employee_id, self.admin_employee_id)
        self.assertEqual(deliveries[0].status, "sent")

    def test_user_offboarded_event_with_no_phone_on_file_resolves_to_failed_delivery(self):
        # Same resolve-then-fail-visibly discipline as every other resolver
        # in this module: a missing phone must still produce a queryable
        # `failed`/`missing_phone` delivery row, not a silent skip.
        self._set_phone(INTERNAL_EMPLOYEE_ID, None)

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="user.offboarded", aggregate_type="user",
                aggregate_id=INTERNAL_EMPLOYEE_ID,
                payload={"user_id": str(INTERNAL_EMPLOYEE_ID), "name": "Internal"},
                key="test:11b",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].recipient_employee_id, self.internal_employee_employee_id)
        self.assertEqual(deliveries[0].status, "failed")
        self.assertEqual(deliveries[0].failure_code, "missing_phone")

    def test_user_event_with_no_user_id_in_payload_resolves_to_no_recipients(self):
        with self.Session() as session:
            recipients = MessageDispatchService(session)._resolve_user_recipient(
                OutboxEvent(
                    event_type="user.created", aggregate_type="user",
                    aggregate_id=INTERNAL_EMPLOYEE_ID, payload={}, idempotency_key="test:11c",
                )
            )
        self.assertEqual(recipients, [])

    # ---- 12. U15: `gate_command_confirmation`-aggregate recipient resolution --

    def test_gate_command_confirmation_event_resolves_only_the_named_actor_not_admin(self):
        # ADMIN_ID stands in for "Admin, who U5's project_external_approval.*
        # events resolve as a fixed cc" here - this resolver must never pick
        # Admin up just because they exist; the sole recipient is the actor
        # named in the payload's `actor_user_id` (SUPERVISOR_ID, the sender
        # of the WhatsApp gate command being confirmed).
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="gate_confirmation.accepted", aggregate_type="gate_command_confirmation",
                aggregate_id=uuid.uuid4(),
                payload={
                    "actor_user_id": str(SUPERVISOR_ID), "gate_name": "Fire NOC", "project_name": "Test Project",
                },
                key="test:12a",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].recipient_employee_id, self.supervisor_employee_id)
        self.assertIsNone(deliveries[0].recipient_vendor_contact_id)
        self.assertNotEqual(deliveries[0].recipient_employee_id, self.admin_employee_id)
        self.assertEqual(deliveries[0].status, "sent")

    def test_gate_command_confirmation_event_with_no_phone_on_file_resolves_to_failed_delivery(self):
        # Same resolve-then-fail-visibly discipline as every other resolver
        # in this module: a missing phone must still produce a queryable
        # `failed`/`missing_phone` delivery row, not a silent skip.
        self._set_phone(SUPERVISOR_ID, None)

        with self.Session() as session:
            event_id = self._create_event(
                session, event_type="gate_confirmation.session_opened", aggregate_type="gate_command_confirmation",
                aggregate_id=uuid.uuid4(),
                payload={"actor_user_id": str(SUPERVISOR_ID), "gate_name": "Fire NOC", "project_name": "Test Project"},
                key="test:12b",
            )
            session.commit()

        with self.Session() as session:
            processed = MessageDispatchService(session).process_pending()
        self.assertEqual(processed, 1)

        deliveries = self._deliveries_for(event_id)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].recipient_employee_id, self.supervisor_employee_id)
        self.assertEqual(deliveries[0].status, "failed")
        self.assertEqual(deliveries[0].failure_code, "missing_phone")

    def test_gate_command_confirmation_event_with_no_actor_user_id_resolves_to_no_recipients(self):
        with self.Session() as session:
            recipients = MessageDispatchService(session)._resolve_command_actor_recipient(
                OutboxEvent(
                    event_type="gate_confirmation.decided", aggregate_type="gate_command_confirmation",
                    aggregate_id=uuid.uuid4(), payload={}, idempotency_key="test:12c",
                )
            )
        self.assertEqual(recipients, [])

    # ---- Telegram task plan U4: participants, active members, noise rules ----

    def _dispatch_one(self, event_type: str, payload: dict | None = None) -> list[MessageDelivery]:
        with self.Session() as session:
            event_id = self._create_event(
                session, event_type=event_type, aggregate_type="task", aggregate_id=self.task_id,
                payload={"task_id": str(self.task_id), "project_id": str(self.project_id), **(payload or {})},
            )
            session.commit()
        with self.Session() as session:
            MessageDispatchService(session).process_pending()
        return self._deliveries_for(event_id)

    def _recipient_ids(self, deliveries) -> set:
        return {d.recipient_employee_id for d in deliveries}

    def _assign_internal_employee(self) -> None:
        with self.Session.begin() as session:
            session.add(TaskSupportAssignment(
                task_id=self.task_id, project_id=self.project_id, employee_id=self.internal_employee_employee_id,
                responsibility="Execution", assigned_by=SUPERVISOR_ID,
            ))

    def _record_submission_by(self, user_id: uuid.UUID) -> None:
        with self.Session.begin() as session:
            session.add(V2AuditEvent(
                actor_user_id=user_id, action="TASK_STATUS_CHANGED", entity_type="task", entity_id=self.task_id,
                project_id=self.project_id, source="portal", before_json={"lifecycle_status": "in_progress"},
                after_json={"lifecycle_status": "submitted"}, reason="Submitted.",
            ))

    def test_review_outcome_reaches_the_assigned_employee_too(self):
        self._assign_internal_employee()
        for event_type in ("task.status_changed", "task.verification_recorded"):
            with self.subTest(event_type=event_type):
                deliveries = self._dispatch_one(event_type, {"target_status": "submitted", "decision": "rejected"})
                self.assertEqual(
                    self._recipient_ids(deliveries),
                    {self.pm_employee_id, self.supervisor_employee_id, self.internal_employee_employee_id},
                )

    def test_the_submitter_is_told_the_outcome_once_even_when_also_the_supervisor(self):
        self._record_submission_by(SUPERVISOR_ID)
        deliveries = self._dispatch_one("task.verification_recorded", {"decision": "rejected"})
        self.assertEqual(len(deliveries), 2)
        self.assertEqual(self._recipient_ids(deliveries), {self.pm_employee_id, self.supervisor_employee_id})

    def test_an_employee_submitter_is_told_the_outcome_without_an_assignment(self):
        self._record_submission_by(INTERNAL_EMPLOYEE_ID)
        deliveries = self._dispatch_one("task.approval_recorded", {"decision": "rejected"})
        self.assertIn(self.internal_employee_employee_id, self._recipient_ids(deliveries))

    def test_a_submitter_who_is_not_a_project_member_is_not_added(self):
        # An Admin who submitted (no membership) hears nothing as a participant.
        self._record_submission_by(ADMIN_ID)
        deliveries = self._dispatch_one("task.status_changed", {"target_status": "submitted"})
        self.assertEqual(self._recipient_ids(deliveries), {self.pm_employee_id, self.supervisor_employee_id})

    def test_removed_or_deactivated_people_receive_nothing(self):
        self._assign_internal_employee()
        with self.Session.begin() as session:
            membership = session.scalar(select(V2ProjectMembership).where(
                V2ProjectMembership.project_id == self.project_id,
                V2ProjectMembership.employee_id == self.internal_employee_employee_id,
            ))
            membership.ends_at = datetime.now(timezone.utc)
            session.get(User, PM_ID).active = False
        deliveries = self._dispatch_one("task.status_changed", {"target_status": "in_progress"})
        self.assertEqual(self._recipient_ids(deliveries), {self.supervisor_employee_id})

    def test_admin_copy_of_an_approval_is_kept_without_membership(self):
        deliveries = self._dispatch_one("task.approval_recorded", {"decision": "approved"})
        self.assertIn(self.admin_employee_id, self._recipient_ids(deliveries))

    def test_telegram_skips_progress_items_and_decision_status_steps_but_whatsapp_does_not(self):
        self._set_telegram(self.supervisor_employee_id, "555000")
        for event_type, payload in (
            ("task.evidence_submitted", {"progress_update_id": str(uuid.uuid4())}),
            ("task.status_changed", {"target_status": "in_progress", "cause": "decision"}),
        ):
            with self.subTest(event_type=event_type):
                deliveries = self._dispatch_one(event_type, payload)
                # The Telegram Supervisor gets no row at all; the WhatsApp PM
                # still gets it exactly as before.
                self.assertEqual(self._recipient_ids(deliveries), {self.pm_employee_id})

    # ---- Telegram task plan U8 (KTD20): Admin only when nobody eligible can review ----

    def _end_membership(self, employee_id) -> None:
        with self.Session.begin() as session:
            membership = session.scalar(select(V2ProjectMembership).where(
                V2ProjectMembership.project_id == self.project_id, V2ProjectMembership.employee_id == employee_id,
            ))
            membership.ends_at = datetime.now(timezone.utc)

    def _submitted(self, submitter_id) -> list[MessageDelivery]:
        return self._dispatch_one("task.status_changed", {
            "target_status": "submitted", "actor_user_id": str(submitter_id), "submitted_by": str(submitter_id),
            "progress_update_ids": [],
        })

    def test_a_submission_with_an_eligible_verifier_does_not_go_to_admin(self):
        deliveries = self._submitted(INTERNAL_EMPLOYEE_ID)
        self.assertNotIn(self.admin_employee_id, self._recipient_ids(deliveries))

    def test_admin_is_asked_when_the_only_verifier_submitted_the_work_themselves(self):
        # No PM on the project, and the Supervisor executed and submitted it:
        # they may not verify their own work, so nobody on the project can.
        self._end_membership(self.pm_employee_id)
        deliveries = self._submitted(SUPERVISOR_ID)
        self.assertIn(self.admin_employee_id, self._recipient_ids(deliveries))

    def test_an_approval_gate_submission_goes_to_admin_only_without_a_pm(self):
        with self.Session.begin() as session:
            session.get(Task, self.task_id).task_kind = "approval_gate"
        self.assertNotIn(self.admin_employee_id, self._recipient_ids(self._submitted(INTERNAL_EMPLOYEE_ID)))
        self._end_membership(self.pm_employee_id)
        self.assertIn(self.admin_employee_id, self._recipient_ids(self._submitted(INTERNAL_EMPLOYEE_ID)))

    def test_telegram_still_gets_a_status_change_that_no_decision_caused(self):
        from unittest.mock import MagicMock, patch

        from app.config import settings

        self._set_telegram(self.supervisor_employee_id, "555000")
        response = MagicMock(status_code=200)
        response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        original_token = settings.telegram_access_token
        settings.telegram_access_token = "test-token"
        try:
            with patch("app.services.telegram_provider.httpx.post", return_value=response) as post:
                deliveries = self._dispatch_one("task.status_changed", {"target_status": "ready"})
        finally:
            settings.telegram_access_token = original_token
        self.assertIn(self.supervisor_employee_id, self._recipient_ids(deliveries))
        sent_text = post.call_args.kwargs["json"]["text"]
        self.assertIn("<b>Task Ready</b>", sent_text)
        self.assertEqual(post.call_args.kwargs["json"]["parse_mode"], "HTML")

    # ---- Milestone 1 Phase 3 & Phase 4: inactive-user leakage & TBD template guards ----

    def test_project_aggregate_events_exclude_deactivated_users_and_ended_memberships(self):
        # Deactivate PM (stale membership: ends_at is still None) and end Internal Employee membership
        with self.Session.begin() as session:
            session.get(User, PM_ID).active = False
            membership = session.scalar(select(V2ProjectMembership).where(
                V2ProjectMembership.project_id == self.project_id,
                V2ProjectMembership.employee_id == self.internal_employee_employee_id,
            ))
            membership.ends_at = datetime.now(timezone.utc)

        # 1. All-members project event (`project.activated`) only reaches active Supervisor
        with self.Session() as session:
            ev1 = self._create_event(
                session, event_type="project.activated", aggregate_type="project",
                aggregate_id=self.project_id, payload={"project_id": str(self.project_id), "project_name": "P1"},
            )
            # 2. PM/Supervisor project event (`project.role_change_requested`) only reaches active Supervisor
            ev2 = self._create_event(
                session, event_type="project.role_change_requested", aggregate_type="project",
                aggregate_id=self.project_id, payload={"project_id": str(self.project_id)},
            )
            # 3. Admin CC project event (`report.weekly_summary_generated`) reaches active Supervisor + active Admin
            ev3 = self._create_event(
                session, event_type="report.weekly_summary_generated", aggregate_type="project",
                aggregate_id=self.project_id, payload={"project_id": str(self.project_id)},
            )
            session.commit()

        with self.Session() as session:
            MessageDispatchService(session).process_pending()

        self.assertEqual(self._recipient_ids(self._deliveries_for(ev1)), {self.supervisor_employee_id})
        self.assertEqual(self._recipient_ids(self._deliveries_for(ev2)), {self.supervisor_employee_id})
        self.assertEqual(
            self._recipient_ids(self._deliveries_for(ev3)),
            {self.supervisor_employee_id, self.admin_employee_id},
        )

    def test_deactivated_admin_and_deactivated_gate_assignee_do_not_receive_gate_events(self):
        approval_id = self._make_gate_approval(assigned_to_user_id=INTERNAL_EMPLOYEE_ID)
        with self.Session.begin() as session:
            session.get(User, INTERNAL_EMPLOYEE_ID).active = False

        with self.Session() as session:
            ev_id = self._create_event(
                session, event_type="project_external_approval.assigned", aggregate_type="project_external_approval",
                aggregate_id=approval_id,
                payload={"approval_id": str(approval_id), "assigned_to_user_id": str(INTERNAL_EMPLOYEE_ID)},
            )
            session.commit()

        with self.Session() as session:
            MessageDispatchService(session).process_pending()

        # Only active Admin receives the notification; deactivated gate assignee is excluded
        self.assertEqual(self._recipient_ids(self._deliveries_for(ev_id)), {self.admin_employee_id})

    def test_meta_cloud_api_adapter_blocks_unapproved_tbd_placeholder_templates_cleanly(self):
        from unittest.mock import patch

        from app.services.whatsapp_provider import MetaCloudApiAdapter

        adapter = MetaCloudApiAdapter(access_token="token-1", phone_number_id="phone-1")
        with patch("app.services.whatsapp_provider.httpx.post") as mock_post:
            result = adapter.send("+919000000010", "TBD_project_activated", {"language_code": "en", "components": []})

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "template_unapproved")
        self.assertIn("TBD_project_activated", result.failure_reason)
        mock_post.assert_not_called()

    def test_audit_template_registry_classifies_configured_and_tbd_templates(self):
        from app.services.message_templates import TEMPLATE_REGISTRY, audit_template_registry

        inventory = audit_template_registry()
        self.assertEqual(len(inventory), len(TEMPLATE_REGISTRY))
        tbd_entries = [item for item in inventory if item["status"] == "placeholder_tbd"]
        configured_entries = [item for item in inventory if item["status"] == "configured"]
        self.assertEqual(len(tbd_entries), 16)
        self.assertEqual(len(configured_entries), len(TEMPLATE_REGISTRY) - 16)
        for item in tbd_entries:
            self.assertTrue(item["meta_template_name"].startswith("TBD_"))


if __name__ == "__main__":
    unittest.main()
