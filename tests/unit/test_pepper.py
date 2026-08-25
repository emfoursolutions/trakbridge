# ABOUTME: Unit tests for the API-key pepper loader.
# ABOUTME: Verifies startup guard, base64 handling, and ephemeral fallback.
"""Tests for services.auth.pepper.

The pepper module reads its value via ``config.secrets.get_secret``,
which cascades through environment variables, Docker/K8s secrets,
dotenv files, and the ``_FILE`` convention. These tests patch
``pepper_module.get_secret`` directly to isolate load_pepper's
own logic from whichever provider happens to be first in the
process's real configuration.
"""

import base64
import logging
from unittest.mock import patch

import pytest

from services.auth import pepper as pepper_module


@pytest.fixture(autouse=True)
def _reset_pepper():
    """Every test starts with a clean pepper cache; reload from the
    real provider chain afterwards so downstream test files still
    find a valid pepper for UserApiKey hash/verify."""
    pepper_module._reset_for_tests()
    yield
    pepper_module._reset_for_tests()
    # Attempt to restore for downstream tests. Fall back to ephemeral
    # if the real environment has no pepper — matches dev/test
    # behaviour of load_pepper(is_production=False).
    try:
        pepper_module.load_pepper(is_production=False)
    except Exception:
        pass


def _mock_get_secret(value):
    """Patch pepper_module.get_secret to return ``value``."""
    return patch.object(
        pepper_module, "get_secret", return_value=value
    )


class TestLoadPepper:
    def test_production_without_pepper_raises(self):
        with _mock_get_secret(None):
            with pytest.raises(pepper_module.PepperMissingError):
                pepper_module.load_pepper(is_production=True)

    def test_development_without_pepper_generates_ephemeral(self, caplog):
        with _mock_get_secret(None), caplog.at_level(logging.WARNING):
            result = pepper_module.load_pepper(is_production=False)
        assert isinstance(result, bytes)
        assert len(result) >= 32
        assert any(
            "EPHEMERAL pepper" in rec.message for rec in caplog.records
        )

    def test_base64_pepper_decoded(self):
        raw = base64.b64encode(b"a" * 48).decode()
        with _mock_get_secret(raw):
            result = pepper_module.load_pepper(is_production=True)
        assert result == b"a" * 48

    def test_raw_string_pepper_accepted_when_long_enough(self):
        raw = "x" * 40
        with _mock_get_secret(raw):
            result = pepper_module.load_pepper(is_production=True)
        assert result == raw.encode("utf-8")

    def test_short_raw_pepper_rejected(self):
        with _mock_get_secret("tooshort"):
            with pytest.raises(pepper_module.PepperMissingError):
                pepper_module.load_pepper(is_production=True)

    def test_empty_string_treated_as_missing(self):
        with _mock_get_secret(""):
            with pytest.raises(pepper_module.PepperMissingError):
                pepper_module.load_pepper(is_production=True)


class TestGetPepper:
    def test_before_load_raises(self):
        with pytest.raises(pepper_module.PepperMissingError):
            pepper_module.get_pepper()

    def test_after_load_returns_bytes(self):
        with _mock_get_secret("x" * 40):
            pepper_module.load_pepper(is_production=True)
        assert pepper_module.get_pepper() == b"x" * 40
