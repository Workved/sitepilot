from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.database import get_db
from app.models import User, UserAccountEvent, UserRole
from app.services.supabase_auth import SupabaseAuthError

PREREGISTERED_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
SUPABASE_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")


class _NaiveUtcNow(datetime):
    """SQLite can't round-trip tzinfo on DateTime columns - a value written
    tz-aware comes back naive the moment a fresh session re-reads it (Postgres,
    which production runs on, has no such gap). Patching app.auth's clock to
    also hand back naive UTC keeps 'now vs. stored' comparisons apples-to-apples
    in this harness, the same way they'd already be on Postgres."""

    @classmethod
    def now(cls, tz=None):
        return datetime.now(timezone.utc).replace(tzinfo=None)


def identity(
    sub: str | uuid.UUID = SUPABASE_ID,
    email: str | None = "user@example.com",
    provider: str = "google",
    siteops_user_id: uuid.UUID | None = None,
) -> dict:
    payload = {"id": str(sub), "app_metadata": {"provider": provider, "providers": [provider]}}
    if siteops_user_id is not None:
        payload["app_metadata"]["siteops_user_id"] = str(siteops_user_id)
    if email is not None:
        payload["email"] = email
    return payload


class CurrentUserAuthTests(unittest.TestCase):
    """Exercises app.auth.current_user() directly through a real HTTP request,
    rather than via a dependency_override - every other test suite in this repo
    fakes the logged-in user, so this is the only place this function actually
    runs end to end."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        for table in (User.__table__, UserAccountEvent.__table__):
            table.create(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        app = FastAPI()

        @app.get("/whoami")
        def whoami(user: User = Depends(current_user)):
            return {"id": str(user.id), "email": user.email, "role": user.role.value}

        def override_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

        clock_patcher = patch("app.auth.datetime", _NaiveUtcNow)
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _seed_user(self, **overrides) -> uuid.UUID:
        user_id = overrides.pop("id", uuid.uuid4())
        defaults = dict(
            id=user_id,
            name="Test User",
            email="user@example.com",
            role=UserRole.supervisor,
            active=True,
            supabase_user_id=SUPABASE_ID,
        )
        defaults.update(overrides)
        with self.Session.begin() as session:
            session.add(User(**defaults))
        return user_id

    def _get_user(self, user_id: uuid.UUID) -> User:
        with self.Session() as session:
            return session.get(User, user_id)

    def _call(self, token: str = "token"):
        return self.client.get("/whoami", headers={"Authorization": f"Bearer {token}"})

    # -- credential / token verification failures --------------------------

    def test_missing_authorization_header_is_rejected(self):
        response = self.client.get("/whoami")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Login required.")

    @patch("app.auth.verify_access_token")
    def test_supabase_outage_surfaces_as_its_own_status_and_message(self, mock_verify):
        mock_verify.side_effect = SupabaseAuthError("Supabase Auth is temporarily unavailable.", 503)
        response = self._call()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Supabase Auth is temporarily unavailable.")

    @patch("app.auth.verify_access_token")
    def test_rejected_token_is_reported_as_expired_session(self, mock_verify):
        mock_verify.side_effect = SupabaseAuthError("invalid JWT", 401)
        response = self._call()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Session expired. Please login again.")

    @patch("app.auth.verify_access_token")
    def test_identity_payload_missing_id_is_treated_as_expired_session(self, mock_verify):
        mock_verify.return_value = {"email": "user@example.com"}
        response = self._call()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Session expired. Please login again.")

    @patch("app.auth.verify_access_token")
    def test_identity_payload_with_malformed_id_is_treated_as_expired_session(self, mock_verify):
        mock_verify.return_value = {"id": "not-a-uuid", "email": "user@example.com"}
        response = self._call()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Session expired. Please login again.")

    # -- already-linked user: the ordinary login path -----------------------

    @patch("app.auth.verify_access_token")
    def test_known_supabase_identity_logs_in_directly(self, mock_verify):
        user_id = self._seed_user()
        mock_verify.return_value = identity()
        response = self._call()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], str(user_id))

    # -- first-login account linking by email --------------------------------

    @patch("app.auth.verify_access_token")
    def test_preregistered_email_links_on_first_google_sign_in(self, mock_verify):
        user_id = self._seed_user(id=PREREGISTERED_ID, supabase_user_id=None, email="new.hire@example.com")
        mock_verify.return_value = identity(sub=SUPABASE_ID, email="new.hire@example.com")

        response = self._call()

        self.assertEqual(response.status_code, 200, response.text)
        user = self._get_user(user_id)
        self.assertEqual(user.supabase_user_id, SUPABASE_ID)
        with self.Session() as session:
            events = list(session.scalars(select(UserAccountEvent).where(UserAccountEvent.user_id == user_id)))
        linked = [e for e in events if e.event_type == "ACCOUNT_LINKED"]
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0].actor_id, user_id)
        self.assertEqual(linked[0].to_role, "supervisor")

    @patch("app.auth.verify_access_token")
    def test_account_linking_matches_email_case_insensitively(self, mock_verify):
        user_id = self._seed_user(id=PREREGISTERED_ID, supabase_user_id=None, email="New.Hire@Example.com")
        mock_verify.return_value = identity(sub=SUPABASE_ID, email="new.hire@example.com")

        response = self._call()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._get_user(user_id).supabase_user_id, SUPABASE_ID)

    @patch("app.auth.verify_access_token")
    def test_repeat_login_after_linking_does_not_create_a_second_link_event(self, mock_verify):
        user_id = self._seed_user(id=PREREGISTERED_ID, supabase_user_id=None, email="new.hire@example.com")
        mock_verify.return_value = identity(sub=SUPABASE_ID, email="new.hire@example.com")

        first = self._call()
        second = self._call()

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        with self.Session() as session:
            events = list(session.scalars(
                select(UserAccountEvent).where(
                    UserAccountEvent.user_id == user_id,
                    UserAccountEvent.event_type == "ACCOUNT_LINKED",
                )
            ))
        self.assertEqual(len(events), 1)

    @patch("app.auth.verify_access_token")
    def test_email_match_is_ignored_when_that_row_is_already_linked_to_someone_else(self, mock_verify):
        # supabase_user_id is already set (not NULL), so this row must not be
        # claimed by a different Supabase identity that merely shares its email.
        self._seed_user(email="shared@example.com", supabase_user_id=uuid.uuid4())
        mock_verify.return_value = identity(sub=SUPABASE_ID, email="shared@example.com")

        response = self._call()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "This account isn't set up in SiteOps yet. Contact your administrator.")

    @patch("app.auth.verify_access_token")
    def test_no_matching_supabase_id_or_email_is_rejected_as_unregistered(self, mock_verify):
        mock_verify.return_value = identity(sub=SUPABASE_ID, email="nobody@example.com")
        response = self._call()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "This account isn't set up in SiteOps yet. Contact your administrator.")

    @patch("app.auth.verify_access_token")
    def test_missing_identity_email_cannot_be_used_to_link(self, mock_verify):
        self._seed_user(id=PREREGISTERED_ID, supabase_user_id=None, email="new.hire@example.com")
        mock_verify.return_value = identity(sub=SUPABASE_ID, email=None)
        response = self._call()
        self.assertEqual(response.status_code, 403)

    @patch("app.auth.local_dev_login_available", return_value=False)
    @patch("app.auth.verify_access_token")
    def test_a_self_registered_email_identity_cannot_claim_a_preregistered_row(self, mock_verify, _dev):
        # With email/password sign-in on, anyone can register a Supabase
        # identity for any address - a bare email match must not hand them
        # the roster row an Admin pre-registered for someone else.
        user_id = self._seed_user(id=PREREGISTERED_ID, supabase_user_id=None, email="new.hire@example.com")
        mock_verify.return_value = identity(sub=SUPABASE_ID, email="new.hire@example.com", provider="email")

        response = self._call()

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self._get_user(user_id).supabase_user_id)

    @patch("app.auth.local_dev_login_available", return_value=False)
    @patch("app.auth.verify_access_token")
    def test_an_admin_created_password_identity_links_to_its_own_row(self, mock_verify, _dev):
        user_id = self._seed_user(id=PREREGISTERED_ID, supabase_user_id=None, email="new.hire@example.com")
        mock_verify.return_value = identity(
            sub=SUPABASE_ID, email="new.hire@example.com", provider="email", siteops_user_id=PREREGISTERED_ID,
        )

        response = self._call()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._get_user(user_id).supabase_user_id, SUPABASE_ID)

    @patch("app.auth.local_dev_login_available", return_value=False)
    @patch("app.auth.verify_access_token")
    def test_a_password_identity_tagged_for_another_row_does_not_link(self, mock_verify, _dev):
        self._seed_user(id=PREREGISTERED_ID, supabase_user_id=None, email="new.hire@example.com")
        mock_verify.return_value = identity(
            sub=SUPABASE_ID, email="new.hire@example.com", provider="email", siteops_user_id=uuid.uuid4(),
        )

        self.assertEqual(self._call().status_code, 403)

    @patch("app.auth.local_dev_login_available", return_value=True)
    @patch("app.auth.verify_access_token")
    def test_local_dev_login_identities_still_link_against_a_local_stack(self, mock_verify, _dev):
        user_id = self._seed_user(id=PREREGISTERED_ID, supabase_user_id=None, email="new.hire@example.com")
        mock_verify.return_value = identity(sub=SUPABASE_ID, email="new.hire@example.com", provider="email")

        self.assertEqual(self._call().status_code, 200)
        self.assertEqual(self._get_user(user_id).supabase_user_id, SUPABASE_ID)

    # -- active / inactive gate ----------------------------------------------

    @patch("app.auth.verify_access_token")
    def test_inactive_account_is_rejected_even_with_a_valid_token(self, mock_verify):
        self._seed_user(active=False)
        mock_verify.return_value = identity()
        response = self._call()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "This account is inactive. Contact your Admin or Super Admin.")

    # -- activation timestamp -------------------------------------------------

    @patch("app.auth.verify_access_token")
    def test_first_authenticated_session_sets_activated_at_and_logs_it(self, mock_verify):
        user_id = self._seed_user(activated_at=None)
        mock_verify.return_value = identity()

        response = self._call()

        self.assertEqual(response.status_code, 200, response.text)
        user = self._get_user(user_id)
        self.assertIsNotNone(user.activated_at)
        with self.Session() as session:
            events = list(session.scalars(
                select(UserAccountEvent).where(
                    UserAccountEvent.user_id == user_id,
                    UserAccountEvent.event_type == "ACCOUNT_ACTIVATED",
                )
            ))
        self.assertEqual(len(events), 1)

    @patch("app.auth.verify_access_token")
    def test_already_activated_account_does_not_get_reactivated_or_re_logged(self, mock_verify):
        original = datetime(2026, 1, 1, tzinfo=timezone.utc)
        user_id = self._seed_user(activated_at=original)
        mock_verify.return_value = identity()

        response = self._call()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._get_user(user_id).activated_at, original.replace(tzinfo=None))
        with self.Session() as session:
            events = list(session.scalars(
                select(UserAccountEvent).where(
                    UserAccountEvent.user_id == user_id,
                    UserAccountEvent.event_type == "ACCOUNT_ACTIVATED",
                )
            ))
        self.assertEqual(len(events), 0)

    # -- last_login_at throttling ---------------------------------------------

    @patch("app.auth.verify_access_token")
    def test_last_login_at_is_stamped_on_first_login(self, mock_verify):
        user_id = self._seed_user(last_login_at=None)
        mock_verify.return_value = identity()
        self._call()
        self.assertIsNotNone(self._get_user(user_id).last_login_at)

    @patch("app.auth.verify_access_token")
    def test_last_login_at_is_not_bumped_within_the_five_minute_window(self, mock_verify):
        recent = datetime.now(timezone.utc) - timedelta(minutes=1)
        user_id = self._seed_user(last_login_at=recent)
        mock_verify.return_value = identity()

        self._call()

        # SQLite stores naive datetimes; compare as naive to avoid a tz mismatch.
        self.assertEqual(self._get_user(user_id).last_login_at.replace(tzinfo=None), recent.replace(tzinfo=None))

    @patch("app.auth.verify_access_token")
    def test_last_login_at_is_bumped_once_the_five_minute_window_has_passed(self, mock_verify):
        stale = datetime.now(timezone.utc) - timedelta(minutes=10)
        user_id = self._seed_user(last_login_at=stale)
        mock_verify.return_value = identity()

        self._call()

        refreshed = self._get_user(user_id).last_login_at.replace(tzinfo=timezone.utc)
        self.assertGreater(refreshed, stale)


if __name__ == "__main__":
    unittest.main()
