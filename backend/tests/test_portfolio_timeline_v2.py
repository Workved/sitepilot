"""Portfolio timeline rows (GET /api/v2/projects/timeline): dates, progress,
forecast, days late, health, approval markers and visibility. Reuses the
add-task harness: project Futurex Fitout, start 2026-08-01, handover
2026-09-14, one task T001 planned for day 1."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from app.models import User, UserRole
from app.project_models import V2Project
from app.routes.project_read_models_v2 import router as read_models_router

# Imported as a module so pytest doesn't collect the parent's tests here.
from tests import test_project_task_addition_v2 as addition

URL = "/api/v2/projects/timeline"


class PortfolioTimelineTests(addition.ProjectTaskAdditionTests):
    def setUp(self):
        super().setUp()
        # Must sit before projects_v2's GET /{project_id}, like in app.main.
        self.app.include_router(read_models_router)
        added = [route for route in self.app.router.routes if getattr(route, "path", "") == URL]
        for route in added:
            self.app.router.routes.remove(route)
            self.app.router.routes.insert(0, route)

    def row(self):
        rows = self.client.get(URL).json()
        return next(r for r in rows if r["project_id"] == self.project["id"])

    def test_late_project_shows_forecast_days_late_and_delayed(self):
        self.act_as_admin()
        row = self.row()
        today = datetime.now(timezone.utc).date()
        self.assertEqual((row["start_date"], row["target_handover_date"], row["pm_name"]), ("2026-08-01", "2026-09-14", "PM"))
        self.assertEqual((row["task_count"], row["completed_count"], row["progress_pct"]), (1, 0, 0))
        # T001 was due on day 1 and isn't done, so it finishes today at best.
        self.assertEqual(row["overdue_count"], 1)
        self.assertEqual(row["forecast_finish_date"], today.isoformat())
        self.assertEqual(row["days_late"], max(0, (today - date(2026, 9, 14)).days))
        self.assertEqual(row["health"], "delayed")

    def test_future_task_keeps_the_project_on_track_and_progress_counts(self):
        self.act_as_admin()
        later = (datetime.now(timezone.utc).date() + timedelta(days=10)).isoformat()
        self.add(planned_start_date=later, planned_end_date=later)
        with self.Session.begin() as session:
            project = session.get(V2Project, uuid.UUID(self.project["id"]))
            project.target_handover_date = date.today() + timedelta(days=60)
            for task in session.scalars(addition.select(addition.Task).where(addition.Task.original_code == "T001")):
                task.lifecycle_status = "completed"
                task.actual_finish_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
        row = self.row()
        self.assertEqual((row["task_count"], row["completed_count"], row["progress_pct"]), (2, 1, 50))
        self.assertEqual((row["days_late"], row["overdue_count"], row["health"]), (0, 0, "on_track"))
        self.assertEqual(row["forecast_finish_date"], later)

    def test_completed_project_is_completed_not_late(self):
        with self.Session.begin() as session:
            session.get(V2Project, uuid.UUID(self.project["id"])).status = "completed"
        self.act_as_admin()
        row = self.row()
        self.assertEqual((row["health"], row["days_late"]), ("completed", 0))

    def test_members_see_their_projects_outsiders_see_none(self):
        self.act_as_pm()
        self.assertEqual(len(self.client.get(URL).json()), 1)
        self.act_as(addition.SUPERVISOR)
        self.assertEqual(len(self.client.get(URL).json()), 1)
        self.act_as(User(id=uuid.uuid4(), name="Nobody", email="n@example.com", role=UserRole.project_manager, active=True))
        self.assertEqual(self.client.get(URL).json(), [])


for _name in dir(addition.ProjectTaskAdditionTests):
    if _name.startswith("test_") and _name not in PortfolioTimelineTests.__dict__:
        setattr(PortfolioTimelineTests, _name, None)
