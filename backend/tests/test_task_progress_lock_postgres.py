"""`submit_progress` and `transition(submitted)`
serialize on the task row, proven against a real Postgres.

SQLite ignores `SELECT ... FOR UPDATE`, so the rest of the suite cannot show
this. The test is skipped unless SITEOPS_LOCKTEST_ADMIN_URL points at a
Postgres server it may create databases on (e.g. the local Supabase stack).
It builds and drops its own throwaway database, `siteops_u3_locktest`, and
never touches the application's database.

Each case holds the row lock inside one service call (by pausing a call the
service makes while the lock is held), starts the competing call on a second
connection, checks that it is waiting, then releases the first:

- progress first: the submit waits, then sees the committed update and
  succeeds - the update belongs to that submission.
- submit first: the progress call waits, then sees `submitted` and is refused
  with no progress row, file row or stored file left behind.
"""

from __future__ import annotations

import os
import threading
import unittest
import uuid
from datetime import date
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import app.execution_models  # noqa: F401 - registers every table on Base.metadata
import app.template_models  # noqa: F401
import app.vendor_models  # noqa: F401
from app.database import Base
from app.execution_models import FileObject, Task, TaskEvidence, TaskProgressUpdate
from app.models import EmployeeProfile, User, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.services.outbox import OutboxService
from app.services.task_lifecycle import TaskLifecycleService
from app.services.task_progress import TaskProgressService

ADMIN_URL = os.environ.get("SITEOPS_LOCKTEST_ADMIN_URL")
TEST_DB = "siteops_u3_locktest"
WAIT = 15  # seconds; generous so a slow machine never flakes, finite so a bug never hangs

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@unittest.skipUnless(ADMIN_URL, "SITEOPS_LOCKTEST_ADMIN_URL not set - real-Postgres lock test skipped")
class TaskRowLockPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"drop database if exists {TEST_DB} with (force)"))
            connection.execute(text(f"create database {TEST_DB}"))
        admin.dispose()

        cls.engine = create_engine(make_url(ADMIN_URL).set(database=TEST_DB), pool_size=5)
        with cls.engine.begin() as connection:
            connection.execute(text("create schema siteops_v2"))
        Base.metadata.create_all(cls.engine)
        with cls.engine.begin() as connection:
            # Throwaway database only: a task's baseline links are irrelevant
            # to row locking, and seeding a full template -> baseline chain
            # just to satisfy them would bury what this test is about.
            connection.execute(text("alter table siteops_v2.tasks drop constraint if exists tasks_baseline_id_fkey"))
            connection.execute(text("alter table siteops_v2.tasks drop constraint if exists tasks_baseline_task_id_fkey"))
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"drop database if exists {TEST_DB} with (force)"))
        admin.dispose()

    def setUp(self):
        self.stored_files: list[str] = []
        self._patches = [
            patch("app.services.evidence_storage.write", side_effect=lambda key, *_: self.stored_files.append(key)),
            patch("app.services.task_progress.compress_evidence_image", side_effect=lambda data, mime: (data, mime)),
        ]
        for p in self._patches:
            p.start()

        suffix = uuid.uuid4().hex[:8]
        with self.Session.begin() as session:
            self.supervisor = User(
                id=uuid.uuid4(), name="Supervisor", email=f"sup-{suffix}@example.com",
                role=UserRole.supervisor, active=True,
            )
            session.add(self.supervisor)
            session.flush()
            profile = EmployeeProfile(
                user_id=self.supervisor.id, employee_code=f"SUP-{suffix}", designation="Supervisor",
                availability="available",
            )
            session.add(profile)
            session.flush()
            self.project = V2Project(
                code=f"PRJ-{suffix}", name="Lock test", client_name="Client", site_address="Site",
                start_date=date(2026, 9, 1), status="active", created_by=self.supervisor.id,
            )
            session.add(self.project)
            session.flush()
            session.add(V2ProjectMembership(
                project_id=self.project.id, employee_id=profile.id, project_role="site_supervisor",
                assigned_by=self.supervisor.id, assignment_reason="lock test",
            ))
            self.task = Task(
                project_id=self.project.id, baseline_id=uuid.uuid4(), baseline_task_id=uuid.uuid4(),
                original_code="T001", template_sequence=1, title="Lock test task",
                schedule_classification="execution", applicability="mandatory",
                task_kind="work", evidence_required=False, lifecycle_status="in_progress",
            )
            session.add(self.task)

    def tearDown(self):
        for p in self._patches:
            p.stop()

    # ---- helpers ---------------------------------------------------------

    def run_in_thread(self, target) -> tuple[threading.Thread, dict]:
        outcome: dict = {}

        def runner():
            session = self.Session()
            try:
                outcome["result"] = target(session)
            except HTTPException as exc:
                outcome["http_error"] = exc
            except Exception as exc:  # pragma: no cover - surfaced by the assertions below
                outcome["error"] = exc
            finally:
                session.close()

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        return thread, outcome

    def log_progress(self, session, with_file: bool):
        return TaskProgressService(session).submit_progress(
            self.project.id, self.task.id, session.get(User, self.supervisor.id), note="Progress",
            evidence_bytes=TINY_PNG if with_file else None,
            evidence_filename="photo.png" if with_file else None,
            evidence_content_type="image/png" if with_file else None,
        )

    def submit(self, session):
        return TaskLifecycleService(session).transition(
            self.project.id, self.task.id, "submitted", session.get(User, self.supervisor.id),
        )

    def counts(self) -> tuple[int, int, int]:
        with self.Session() as session:
            return (
                session.scalar(select(func.count()).select_from(TaskProgressUpdate).where(TaskProgressUpdate.task_id == self.task.id)),
                session.scalar(select(func.count()).select_from(FileObject)),
                session.scalar(select(func.count()).select_from(TaskEvidence)),
            )

    # ---- cases -----------------------------------------------------------

    def test_progress_holding_the_lock_makes_submit_wait_then_belong_to_it(self):
        progress_locked, release_progress = threading.Event(), threading.Event()
        real_emit = OutboxService.emit

        def pausing_emit(service, **kwargs):
            # submit_progress emits task.evidence_submitted after inserting the
            # update and before committing - i.e. while holding the row lock.
            if kwargs.get("event_type") == "task.evidence_submitted" and not progress_locked.is_set():
                progress_locked.set()
                self.assertTrue(release_progress.wait(WAIT), "progress was never released")
            return real_emit(service, **kwargs)

        with patch.object(OutboxService, "emit", pausing_emit):
            progress_thread, progress = self.run_in_thread(lambda s: self.log_progress(s, with_file=False))
            self.assertTrue(progress_locked.wait(WAIT), "progress call never reached its locked section")

            submit_thread, submitted = self.run_in_thread(self.submit)
            submit_thread.join(1.0)
            self.assertTrue(submit_thread.is_alive(), "submit did not wait for the progress call's row lock")

            release_progress.set()
            progress_thread.join(WAIT)
            submit_thread.join(WAIT)

        self.assertNotIn("error", progress, progress.get("error"))
        self.assertNotIn("error", submitted, submitted.get("error"))
        self.assertNotIn("http_error", progress, getattr(progress.get("http_error"), "detail", None))
        # The ONLY progress update is the one that was mid-flight when submit
        # began: submit succeeding means it waited and then counted it.
        self.assertNotIn("http_error", submitted, getattr(submitted.get("http_error"), "detail", None))
        with self.Session() as session:
            self.assertEqual(session.get(Task, self.task.id).lifecycle_status, "submitted")
            updates = session.scalars(select(TaskProgressUpdate).where(TaskProgressUpdate.task_id == self.task.id)).all()
            self.assertEqual(len(updates), 1)
            self.assertIsNone(updates[0].reviewed_at)

    def test_submit_holding_the_lock_makes_progress_wait_then_be_refused_cleanly(self):
        with self.Session.begin() as session:
            session.add(TaskProgressUpdate(
                task_id=self.task.id, project_id=self.project.id, update_type="note", note="Earlier work",
                submitted_by=self.supervisor.id, source="portal",
            ))
        before = self.counts()

        submit_locked, release_submit = threading.Event(), threading.Event()
        real_emit = OutboxService.emit

        def pausing_emit(service, **kwargs):
            # transition() emits task.status_changed after setting the status
            # and before committing - i.e. while holding the row lock.
            if kwargs.get("event_type") == "task.status_changed" and not submit_locked.is_set():
                submit_locked.set()
                self.assertTrue(release_submit.wait(WAIT), "submit was never released")
            return real_emit(service, **kwargs)

        with patch.object(OutboxService, "emit", pausing_emit):
            submit_thread, submitted = self.run_in_thread(self.submit)
            self.assertTrue(submit_locked.wait(WAIT), "submit never reached its locked section")

            progress_thread, progress = self.run_in_thread(lambda s: self.log_progress(s, with_file=True))
            progress_thread.join(1.0)
            self.assertTrue(progress_thread.is_alive(), "progress did not wait for the submit's row lock")

            release_submit.set()
            submit_thread.join(WAIT)
            progress_thread.join(WAIT)

        self.assertNotIn("error", submitted, submitted.get("error"))
        self.assertNotIn("http_error", submitted, getattr(submitted.get("http_error"), "detail", None))
        self.assertIn("http_error", progress, "progress was accepted after the task was submitted")
        self.assertEqual(progress["http_error"].status_code, 409)
        self.assertIn("currently submitted", progress["http_error"].detail)

        with self.Session() as session:
            self.assertEqual(session.get(Task, self.task.id).lifecycle_status, "submitted")
        self.assertEqual(self.counts(), before, "a refused progress call left a progress/file/evidence row behind")
        self.assertEqual(self.stored_files, [], "a refused progress call stored a file")


if __name__ == "__main__":
    unittest.main()
