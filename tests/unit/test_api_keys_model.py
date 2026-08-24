# ABOUTME: Unit tests for the UserApiKey model.
# ABOUTME: Verifies HMAC roundtrip, validity state matrix, and scope handling.
"""Tests for models.user.UserApiKey."""

from datetime import datetime, timedelta, timezone

import pytest

from database import db
from models.user import (
    API_KEY_PREFIX_LEN,
    API_KEY_TOKEN_PREFIX,
    AccountStatus,
    AuthProvider,
    User,
    UserApiKey,
    UserRole,
)


@pytest.fixture
def local_user(app, db_session):
    """A local-provider active user we can attach keys to."""
    user = User(
        username="apikey_user",
        email="apikey_user@example.com",
        auth_provider=AuthProvider.LOCAL,
        role=UserRole.USER,
        status=AccountStatus.ACTIVE,
    )
    user.set_password("Correct-Horse-Battery-9!")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def key_pair(local_user, db_session):
    """Return (key, plaintext) for an active USER-role key with one scope."""
    key, plaintext = UserApiKey.generate(
        user=local_user,
        name="test key",
        scopes=["streams:read"],
    )
    return key, plaintext


class TestTokenShape:
    def test_plaintext_starts_with_prefix(self, key_pair):
        _key, plaintext = key_pair
        assert plaintext.startswith(API_KEY_TOKEN_PREFIX)

    def test_plaintext_carries_256_bit_entropy(self, key_pair):
        _key, plaintext = key_pair
        # secrets.token_urlsafe(32) yields ~43 base64url chars.
        body = plaintext[len(API_KEY_TOKEN_PREFIX):]
        assert len(body) >= 40

    def test_stored_prefix_matches_leading_plaintext(self, key_pair):
        key, plaintext = key_pair
        assert key.token_prefix == plaintext[:API_KEY_PREFIX_LEN]
        assert len(key.token_prefix) == API_KEY_PREFIX_LEN

    def test_hash_and_salt_stored_not_plaintext(self, key_pair):
        key, plaintext = key_pair
        # Nothing about the plaintext body should leak into hash/salt.
        body = plaintext[len(API_KEY_TOKEN_PREFIX):]
        assert body not in key.token_hash
        assert body not in key.token_salt
        assert len(key.token_hash) == 64  # sha256 hex
        assert len(key.token_salt) == 32  # 16 bytes hex


class TestVerify:
    def test_correct_plaintext_verifies(self, key_pair):
        key, plaintext = key_pair
        assert key.verify(plaintext) is True

    def test_wrong_plaintext_rejected(self, key_pair):
        key, _plaintext = key_pair
        assert key.verify(API_KEY_TOKEN_PREFIX + "not-a-real-token") is False

    def test_tampered_salt_breaks_verification(self, key_pair, db_session):
        key, plaintext = key_pair
        original = key.token_salt
        # Flip one hex char to a valid different hex char.
        key.token_salt = ("f" if original[0] != "f" else "0") + original[1:]
        assert key.verify(plaintext) is False

    def test_two_keys_with_same_scope_have_distinct_hashes(self, local_user):
        # Different salts guarantee distinct hashes even for identical
        # scopes — protects against rainbow-table attacks on the pepper.
        k1, t1 = UserApiKey.generate(local_user, "k1", ["streams:read"])
        k2, t2 = UserApiKey.generate(local_user, "k2", ["streams:read"])
        assert k1.token_hash != k2.token_hash
        assert k1.token_salt != k2.token_salt
        assert t1 != t2


class TestIsValid:
    def test_fresh_key_is_valid(self, key_pair):
        key, _plaintext = key_pair
        assert key.is_valid() is True

    def test_revoked_key_is_invalid(self, key_pair, db_session):
        key, _plaintext = key_pair
        key.revoke()
        db_session.commit()
        assert key.is_valid() is False

    def test_inactive_flag_makes_key_invalid(self, key_pair, db_session):
        key, _plaintext = key_pair
        key.is_active = False
        db_session.commit()
        assert key.is_valid() is False

    def test_expired_key_is_invalid(self, key_pair, db_session):
        key, _plaintext = key_pair
        key.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db_session.commit()
        assert key.is_valid() is False

    def test_future_expiry_is_valid(self, key_pair, db_session):
        key, _plaintext = key_pair
        key.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        db_session.commit()
        assert key.is_valid() is True

    def test_disabled_owner_makes_key_invalid(self, key_pair, db_session):
        key, _plaintext = key_pair
        key.user.status = AccountStatus.DISABLED
        db_session.commit()
        assert key.is_valid() is False

    def test_naive_expires_at_treated_as_utc(self, key_pair, db_session):
        # SQLite strips tzinfo on read; the model must tolerate that.
        key, _plaintext = key_pair
        key.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db_session.commit()
        assert key.is_valid() is False


class TestRevoke:
    def test_revoke_sets_timestamp_and_deactivates(self, key_pair, db_session):
        key, _plaintext = key_pair
        assert key.revoked_at is None
        assert key.is_active is True
        key.revoke()
        db_session.commit()
        assert key.revoked_at is not None
        assert key.is_active is False

    def test_revoke_is_idempotent(self, key_pair, db_session):
        key, _plaintext = key_pair
        key.revoke()
        first_ts = key.revoked_at
        key.revoke()  # second call should not shift the timestamp
        assert key.revoked_at == first_ts


class TestScopes:
    def test_scope_list_parses_json(self, local_user):
        key, _ = UserApiKey.generate(
            local_user, "k", ["streams:read", "plugins:read"]
        )
        assert set(key.scope_list()) == {"streams:read", "plugins:read"}

    def test_has_scope_true_for_declared(self, local_user):
        key, _ = UserApiKey.generate(local_user, "k", ["streams:read"])
        assert key.has_scope("streams", "read") is True

    def test_has_scope_false_for_undeclared(self, local_user):
        key, _ = UserApiKey.generate(local_user, "k", ["streams:read"])
        assert key.has_scope("streams", "write") is False

    def test_empty_scopes_grants_nothing(self, local_user):
        key, _ = UserApiKey.generate(local_user, "k", [])
        assert key.has_scope("streams", "read") is False

    def test_corrupted_scopes_returns_empty(self, key_pair):
        key, _plaintext = key_pair
        key.scopes = "not json at all"
        assert key.scope_list() == []


class TestToDict:
    def test_never_leaks_hash_or_salt(self, key_pair):
        key, _plaintext = key_pair
        data = key.to_dict()
        assert "token_hash" not in data
        assert "token_salt" not in data
        # Nor under any innocent-looking alias.
        assert not any("hash" in k.lower() for k in data)
        assert not any("salt" in k.lower() for k in data)

    def test_exposes_expected_fields(self, key_pair):
        key, _plaintext = key_pair
        data = key.to_dict()
        for field in (
            "id",
            "name",
            "prefix",
            "scopes",
            "expires_at",
            "last_used_at",
            "revoked_at",
            "is_active",
            "is_valid",
            "created_at",
            "updated_at",
        ):
            assert field in data


class TestOwnerRelationship:
    def test_cascade_delete_removes_keys(self, local_user, db_session):
        UserApiKey.generate(local_user, "k1", ["streams:read"])
        UserApiKey.generate(local_user, "k2", ["streams:read"])
        assert (
            db_session.query(UserApiKey)
            .filter_by(user_id=local_user.id)
            .count()
            == 2
        )
        db_session.delete(local_user)
        db_session.commit()
        assert (
            db_session.query(UserApiKey)
            .filter_by(user_id=local_user.id)
            .count()
            == 0
        )
