# ABOUTME: Unit tests for services.auth.api_key_service.
# ABOUTME: Covers header parsing, resolver, and last-used throttling.
"""Tests for the request-path API-key resolver and touch helper."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from database import db
from models.user import (
    AccountStatus,
    AuthProvider,
    User,
    UserApiKey,
    UserRole,
)
from services.auth.api_key_service import (
    LAST_USED_THROTTLE,
    extract_bearer,
    resolve_api_key,
    touch_last_used,
)


@pytest.fixture
def local_user(app, db_session):
    user = User(
        username="apikey_svc_user",
        email="apikey_svc@example.com",
        auth_provider=AuthProvider.LOCAL,
        role=UserRole.USER,
        status=AccountStatus.ACTIVE,
    )
    user.set_password("Correct-Horse-Battery-9!")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def valid_key(local_user):
    key, plaintext = UserApiKey.generate(
        user=local_user,
        name="svc test key",
        scopes=["streams:read"],
    )
    return key, plaintext


class TestExtractBearer:
    def test_none_header(self):
        assert extract_bearer(None) is None

    def test_empty_header(self):
        assert extract_bearer("") is None

    def test_missing_scheme(self):
        assert extract_bearer("tb_pat_abcdefghijklmnop") is None

    def test_wrong_scheme_rejected(self):
        assert extract_bearer("Basic tb_pat_abcdefghijklmnop") is None

    def test_bearer_but_wrong_prefix(self):
        # A well-formed bearer that isn't one of our tokens must be
        # ignored so it can fall through to other auth mechanisms.
        assert extract_bearer("Bearer ghp_abcdefghijklmnop") is None

    def test_correct_shape_returned(self):
        token = "tb_pat_abcdefghijklmnopqrstuvwxyz1234567890"
        assert extract_bearer(f"Bearer {token}") == token

    def test_scheme_case_insensitive(self):
        token = "tb_pat_abcdefghijklmnopqrstuvwxyz1234567890"
        assert extract_bearer(f"bearer {token}") == token


class TestResolveApiKey:
    def test_none_when_header_missing(self, app):
        with app.app_context():
            assert resolve_api_key(None) is None

    def test_none_when_prefix_wrong_no_db_hit(self, app):
        # A wrong-prefix token must fast-reject without ever calling
        # into SQLAlchemy — assert by patching the query out.
        with app.app_context(), patch(
            "services.auth.api_key_service.UserApiKey"
        ) as mock_model:
            resolve_api_key("Bearer ghp_notatrakbridgetoken")
            assert not mock_model.query.filter_by.called

    def test_valid_token_returns_key(self, app, valid_key):
        key, plaintext = valid_key
        with app.app_context():
            resolved = resolve_api_key(f"Bearer {plaintext}")
        assert resolved is not None
        assert resolved.id == key.id

    def test_wrong_body_but_matching_prefix_returns_none(
        self, app, valid_key
    ):
        # Craft a token that shares the 12-char preview but differs in
        # the entropy body — HMAC compare must reject it.
        _key, plaintext = valid_key
        forged = plaintext[:19] + "different-body-completely-different-XXX"
        with app.app_context():
            assert resolve_api_key(f"Bearer {forged}") is None

    def test_revoked_key_returns_none(self, app, valid_key, db_session):
        key, plaintext = valid_key
        key.revoke()
        db_session.commit()
        with app.app_context():
            # revoke() sets is_active=False, so the candidate filter
            # excludes the row entirely — different code path from
            # "matched but not valid".
            assert resolve_api_key(f"Bearer {plaintext}") is None

    def test_expired_key_returns_none_and_logs(
        self, app, valid_key, db_session, caplog
    ):
        key, plaintext = valid_key
        key.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()
        import logging
        with app.app_context(), caplog.at_level(logging.INFO):
            resolved = resolve_api_key(f"Bearer {plaintext}")
        assert resolved is None
        assert any("expiry_hit" in rec.message for rec in caplog.records)

    def test_disabled_owner_returns_none(
        self, app, valid_key, db_session
    ):
        key, plaintext = valid_key
        key.user.status = AccountStatus.DISABLED
        db_session.commit()
        with app.app_context():
            assert resolve_api_key(f"Bearer {plaintext}") is None


class TestTouchLastUsed:
    def test_first_call_writes(self, app, valid_key, db_session):
        key, _plaintext = valid_key
        assert key.last_used_at is None
        touch_last_used(key)
        db_session.refresh(key)
        assert key.last_used_at is not None

    def test_second_call_within_window_is_skipped(
        self, app, valid_key, db_session
    ):
        key, _plaintext = valid_key
        touch_last_used(key)
        first = key.last_used_at
        # Second call inside the window must not update the value.
        touch_last_used(key)
        assert key.last_used_at == first

    def test_second_call_outside_window_writes(
        self, app, valid_key, db_session
    ):
        key, _plaintext = valid_key
        # Simulate a first hit older than the throttle window.
        key.last_used_at = datetime.now(timezone.utc) - (
            LAST_USED_THROTTLE + timedelta(seconds=10)
        )
        db_session.commit()
        old = key.last_used_at
        touch_last_used(key)
        assert key.last_used_at > old

    def test_commit_failure_does_not_raise(
        self, app, valid_key, db_session
    ):
        key, _plaintext = valid_key
        with app.app_context(), patch.object(
            db.session, "commit", side_effect=RuntimeError("db down")
        ):
            # Must not propagate — an unauthenticated 500 on every
            # request after a DB glitch would be a regression.
            touch_last_used(key)

    def test_naive_last_used_treated_as_utc(
        self, app, valid_key, db_session
    ):
        key, _plaintext = valid_key
        key.last_used_at = datetime.utcnow() - (
            LAST_USED_THROTTLE + timedelta(seconds=10)
        )
        db_session.commit()
        with app.app_context():
            # Must not throw a naive-vs-aware comparison error.
            touch_last_used(key)
