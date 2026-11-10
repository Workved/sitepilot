"""Email/password sign-in set by an Admin: `PUT /api/users/{id}/password`
and the optional `password` on `POST /api/users/invite`.

Supabase Auth's admin API is mocked at `app.routes.users`; the password
must only ever reach it, never the SiteOps database.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.execution_models import OutboxEvent
from app.models import EmployeeProfile, User, UserAccountEvent, UserRole
from app.routes.users import router as users_router
from app.services.supabase_auth import SupabaseAuthError

ACTOR_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
NEW_IDENTITY_ID = "cccccccc-cccc-4ccc-8ccc-ccccccccccc3"
PASSWORD = "Site-Ops-2026"


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


class UserPasswordTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def attach_schema(dbapi_connection, _connection_record):
            dbapi_connection.execute("ATTACH DATABASE ':memory:' AS siteops_v2")

        for table in (User.__table__, EmployeeProfile.__table__, UserAccountEvent.__table__, OutboxEvent.__table__):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.actor_role = UserRole.super_admin
        with self.Session.begin() as session:
            session.add(User(
                id=ACTOR_ID, name="Admin", email="admin@example.com",
                role=UserRole.super_admin, active=True, supabase_user_id=uuid.uuid4(),
            ))

        app = FastAPI()
        app.include_router(users_router)

        def override_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[current_user] = self._actor
        self.client = TestClient(app)

        self.supabase = {}
        for name in ("admin_create_user", "admin_update_user", "admin_find_user_by_email", "admin_delete_user"):
            patcher = patch(f"app.routes.users.{name}")
            self.supabase[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.supabase["admin_create_user"].return_value = {"id": NEW_IDENTITY_ID}
        self.supabase["admin_find_user_by_email"].return_value = None

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _actor(self) -> User:
        with self.Session() as session:
            actor = session.get(User, ACTOR_ID)
            actor.role = self.actor_role
            return actor

    def _seed_user(self, **overrides) -> uuid.UUID:
        user_id = overrides.pop("id", uuid.uuid4())
        values = dict(id=user_id, name="Site Lead", email="lead@example.com", role=UserRole.supervisor, active=True, supabase_user_id=None)
        values.update(overrides)
        with self.Session.begin() as session:
            session.add(User(**values))
        return user_id

    def _user(self, user_id) -> User:
        with self.Session() as session:
            return session.get(User, uuid.UUID(str(user_id)))

    def _event_types(self, user_id) -> list[str]:
        with self.Session() as session:
            return [row.event_type for row in session.scalars(select(UserAccountEvent).where(UserAccountEvent.user_id == uuid.UUID(str(user_id))))]

    def _invite(self, **overrides):
        body = {
            "name": "New Employee", "email": "new.employee@example.com", "role": UserRole.internal_employee.value,
            "employee_code": "EMP100", "designation": "Site Engineer",
        }
        body.update(overrides)
        return self.client.post("/api/users/invite", json=body)

    # -- invite --------------------------------------------------------------

    def test_inviting_with_a_password_creates_a_tagged_login_and_links_it(self):
        response = self._invite(password=PASSWORD)

        self.assertEqual(response.status_code, 200, response.text)
        user_id = response.json()["id"]
        kwargs = self.supabase["admin_create_user"].call_args.kwargs
        self.assertEqual(kwargs["email"], "new.employee@example.com")
        self.assertEqual(kwargs["password"], PASSWORD)
        self.assertEqual(kwargs["app_metadata"], {"siteops_user_id": user_id})
        user = self._user(user_id)
        self.assertEqual(str(user.supabase_user_id), NEW_IDENTITY_ID)
        self.assertIsNone(user.password_hash)
        self.assertIn("PASSWORD_SET", self._event_types(user_id))

    def test_inviting_without_a_password_creates_no_login(self):
        response = self._invite(password="")

        self.assertEqual(response.status_code, 200, response.text)
        self.supabase["admin_create_user"].assert_not_called()
        self.assertIsNone(self._user(response.json()["id"]).supabase_user_id)

    def test_a_short_invite_password_is_rejected_before_anything_is_saved(self):
        response = self._invite(password="short")

        self.assertEqual(response.status_code, 422)
        self.supabase["admin_create_user"].assert_not_called()
        with self.Session() as session:
            self.assertIsNone(session.scalar(select(User).where(User.email == "new.employee@example.com")))

    def test_a_supabase_failure_leaves_no_roster_row(self):
        self.supabase["admin_create_user"].side_effect = SupabaseAuthError("Password is too weak", 409)

        response = self._invite(password=PASSWORD)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Password is too weak")
        with self.Session() as session:
            self.assertIsNone(session.scalar(select(User).where(User.email == "new.employee@example.com")))

    # -- set / reset password -----------------------------------------------

    def test_setting_a_password_on_a_linked_account_updates_its_login(self):
        identity_id = uuid.uuid4()
        user_id = self._seed_user(supabase_user_id=identity_id)

        response = self.client.put(f"/api/users/{user_id}/password", json={"password": PASSWORD})

        self.assertEqual(response.status_code, 200, response.text)
        self.supabase["admin_update_user"].assert_called_once_with(str(identity_id), {
            "password": PASSWORD,
            "email_confirm": True,
            "app_metadata": {"siteops_user_id": str(user_id)},
        })
        self.supabase["admin_create_user"].assert_not_called()
        self.assertEqual(self._event_types(user_id), ["PASSWORD_SET"])

    def test_an_unlinked_account_adopts_an_existing_login_for_its_email(self):
        existing_id = uuid.uuid4()
        self.supabase["admin_find_user_by_email"].return_value = {"id": str(existing_id), "email": "lead@example.com"}
        user_id = self._seed_user()

        response = self.client.put(f"/api/users/{user_id}/password", json={"password": PASSWORD})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.supabase["admin_update_user"].call_args.args[0], str(existing_id))
        self.assertEqual(self._user(user_id).supabase_user_id, existing_id)

    def test_an_unlinked_account_with_no_login_gets_a_new_one(self):
        user_id = self._seed_user()

        response = self.client.put(f"/api/users/{user_id}/password", json={"password": PASSWORD})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(str(self._user(user_id).supabase_user_id), NEW_IDENTITY_ID)

    def test_a_login_already_linked_to_another_account_is_refused(self):
        taken_id = uuid.uuid4()
        self._seed_user(email="other@example.com", supabase_user_id=taken_id)
        self.supabase["admin_find_user_by_email"].return_value = {"id": str(taken_id), "email": "lead@example.com"}
        user_id = self._seed_user()

        response = self.client.put(f"/api/users/{user_id}/password", json={"password": PASSWORD})

        self.assertEqual(response.status_code, 409)
        self.supabase["admin_update_user"].assert_not_called()
        self.assertIsNone(self._user(user_id).supabase_user_id)

    def test_a_short_password_is_rejected(self):
        user_id = self._seed_user()

        response = self.client.put(f"/api/users/{user_id}/password", json={"password": "1234567"})

        self.assertEqual(response.status_code, 422)
        self.supabase["admin_create_user"].assert_not_called()

    def test_an_offboarded_account_cannot_get_a_password(self):
        user_id = self._seed_user(active=False)

        response = self.client.put(f"/api/users/{user_id}/password", json={"password": PASSWORD})

        self.assertEqual(response.status_code, 409)

    def test_an_admin_cannot_set_another_admins_password(self):
        self.actor_role = UserRole.admin
        user_id = self._seed_user(role=UserRole.admin)

        response = self.client.put(f"/api/users/{user_id}/password", json={"password": PASSWORD})

        self.assertEqual(response.status_code, 403)
        self.supabase["admin_update_user"].assert_not_called()

    def test_nobody_can_set_the_super_admins_password_here(self):
        response = self.client.put(f"/api/users/{ACTOR_ID}/password", json={"password": PASSWORD})

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
