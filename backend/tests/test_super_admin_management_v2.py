from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import can_create_role, current_user
from app.database import get_db
from app.execution_models import OutboxEvent
from app.models import EmployeeProfile, User, UserAccountEvent, UserRole
from app.project_models import V2Project, V2ProjectMembership
from app.routes.users import router as users_router
from app.services.access_control import manageable_roles
from app.template_models import V2Template, V2TemplateVersion

SUPER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
OTHER_SUPER_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")
ADMIN_ID = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc3")


class SuperAdminManagementTests(unittest.TestCase):
    """More than one Super Admin: a Super Admin can add, promote, edit and
    offboard other Super Admins, but never manage their own account through
    these routes - which is also what keeps at least one active Super Admin.
    A Super Admin sets their own employee details via PUT /me/profile."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (
            User.__table__,
            EmployeeProfile.__table__,
            UserAccountEvent.__table__,
            OutboxEvent.__table__,
            V2Template.__table__,
            V2TemplateVersion.__table__,
            V2Project.__table__,
            V2ProjectMembership.__table__,
        ):
            table.create(self.engine)

        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.Session.begin() as session:
            session.add_all([
                User(id=SUPER_ID, name="First Super", email="first@example.com", role=UserRole.super_admin, active=True),
                User(id=OTHER_SUPER_ID, name="Second Super", email="second@example.com", role=UserRole.super_admin, active=True),
                User(id=ADMIN_ID, name="An Admin", email="admin@example.com", role=UserRole.admin, active=True),
            ])
            session.add(EmployeeProfile(user_id=ADMIN_ID, employee_code="ADM-1", designation="Admin"))
            session.add(EmployeeProfile(user_id=OTHER_SUPER_ID, employee_code="SA-2", designation="CTO"))

        self.actor_id = SUPER_ID
        app = FastAPI()
        app.include_router(users_router)

        def override_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        # Like app.auth.current_user, load the actor in the request's own
        # session, so changes made to it are committed with the request.
        def override_actor(db=Depends(get_db)):
            return db.get(User, self.actor_id)

        app.dependency_overrides[current_user] = override_actor
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _user(self, user_id) -> User:
        with self.Session() as session:
            return session.get(User, user_id)

    def _profile(self, user_id) -> EmployeeProfile | None:
        with self.Session() as session:
            return session.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_id))

    def _edit(self, user_id, **overrides):
        target = self._user(user_id)
        payload = {
            "name": target.name, "email": target.email, "role": target.role.value,
            "employee_code": "CODE-9", "designation": "Staff", **overrides,
        }
        return self.client.put(f"/api/users/{user_id}", json=payload)

    def test_only_a_super_admin_can_grant_super_admin(self):
        self.assertTrue(can_create_role(UserRole.super_admin, UserRole.super_admin))
        self.assertFalse(can_create_role(UserRole.admin, UserRole.super_admin))
        self.assertNotIn(UserRole.super_admin, manageable_roles(UserRole.admin))
        # Pickers default to the first entry, so it must not be Super Admin.
        self.assertNotEqual(manageable_roles(UserRole.super_admin)[0], UserRole.super_admin)

    def test_super_admin_invites_another_super_admin(self):
        response = self.client.post("/api/users/invite", json={
            "name": "Third Super", "email": "third@example.com", "role": "super_admin",
            "employee_code": "sa-3", "designation": "Platform lead",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["role"], "super_admin")

    def test_admin_cannot_invite_a_super_admin(self):
        self.actor_id = ADMIN_ID
        response = self.client.post("/api/users/invite", json={
            "name": "Sneaky", "email": "sneaky@example.com", "role": "super_admin",
            "employee_code": "X-1", "designation": "Nope",
        })
        self.assertEqual(response.status_code, 403)

    def test_super_admin_promotes_an_admin_with_a_reason(self):
        response = self._edit(ADMIN_ID, role="super_admin", reason="Takes over platform ops")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._user(ADMIN_ID).role, UserRole.super_admin)
        with self.Session() as session:
            change = session.scalar(select(UserAccountEvent).where(UserAccountEvent.event_type == "ROLE_CHANGED"))
        self.assertEqual((change.from_role, change.to_role), ("admin", "super_admin"))

    def test_super_admin_edits_and_offboards_another_super_admin(self):
        self.assertEqual(self._edit(OTHER_SUPER_ID, role="admin", reason="Stepping back").status_code, 200)
        self._edit(ADMIN_ID, role="super_admin", reason="Promote")
        response = self.client.post(f"/api/users/{ADMIN_ID}/offboard", json={"reason": "Left the company"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(self._user(ADMIN_ID).active)

    def test_admin_cannot_touch_a_super_admin(self):
        self.actor_id = ADMIN_ID
        self.assertEqual(self._edit(OTHER_SUPER_ID).status_code, 403)
        self.assertEqual(self.client.post(f"/api/users/{OTHER_SUPER_ID}/offboard", json={"reason": "Nope nope"}).status_code, 403)

    def test_super_admin_cannot_demote_offboard_or_delete_themselves(self):
        self.assertEqual(self._edit(SUPER_ID, role="admin", reason="Oops").status_code, 403)
        self.assertEqual(self.client.post(f"/api/users/{SUPER_ID}/offboard", json={"reason": "Leaving now"}).status_code, 403)
        delete = self.client.request("DELETE", f"/api/users/{SUPER_ID}", json={"reason": "Cleanup", "confirmation": "first@example.com"})
        self.assertEqual(delete.status_code, 403)
        self.assertEqual(self._user(SUPER_ID).role, UserRole.super_admin)
        self.assertTrue(self._user(SUPER_ID).active)

    def test_super_admin_sees_other_super_admins_history(self):
        self.assertEqual(self.client.get(f"/api/users/{OTHER_SUPER_ID}/events").status_code, 200)

    def test_super_admin_sets_their_own_employee_details(self):
        response = self.client.put("/api/users/me/profile", json={
            "name": "First Super", "phone": "+919800000001",
            "employee_code": "sa-1", "designation": "Founder", "department": "Leadership",
        })
        self.assertEqual(response.status_code, 200, response.text)
        profile = self._profile(SUPER_ID)
        self.assertEqual((profile.employee_code, profile.designation, profile.department), ("SA-1", "Founder", "Leadership"))
        self.assertEqual(self._user(SUPER_ID).phone, "+919800000001")

    def test_super_admin_without_profile_still_gets_a_default_one(self):
        response = self.client.put("/api/users/me/profile", json={"name": "First Super"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self._profile(SUPER_ID).employee_code.startswith("SUPERADMIN-"))

    def test_duplicate_own_employee_code_is_a_conflict(self):
        response = self.client.put("/api/users/me/profile", json={"name": "First Super", "employee_code": "adm-1", "designation": "x"})
        self.assertEqual(response.status_code, 409)

    def test_admin_cannot_set_their_own_employee_details(self):
        self.actor_id = ADMIN_ID
        response = self.client.put("/api/users/me/profile", json={"name": "An Admin", "employee_code": "HACK", "designation": "CEO"})
        self.assertEqual(response.status_code, 200, response.text)
        profile = self._profile(ADMIN_ID)
        self.assertEqual((profile.employee_code, profile.designation), ("ADM-1", "Admin"))

    def test_updating_supabase_metadata_is_skipped_for_unlinked_accounts(self):
        with patch("app.routes.users.admin_update_user") as mock_update:
            self.client.put("/api/users/me/profile", json={"name": "First Super"})
        mock_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
