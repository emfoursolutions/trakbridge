# ABOUTME: Unit tests for the API-key pepper loader.
# ABOUTME: Verifies startup guard, base64 handling, and ephemeral fallback.
"""Tests for services.auth.pepper."""

import base64
import logging
import os

import pytest

from services.auth import pepper as pepper_module


@pytest.fixture(autouse=True)
def _reset_pepper_and_env(monkeypatch):
    """Ensure every test starts with a clean pepper cache and no env.

    On teardown, restore the pepper from the pre-test environment so
    downstream test files (which rely on a loaded pepper for
    UserApiKey hash/verify) still work when this suite runs earlier
    in the same pytest session.
    """
    original = os.environ.get("API_KEY_PEPPER")
    monkeypatch.delenv("API_KEY_PEPPER", raising=False)
    pepper_module._reset_for_tests()
    yield
    pepper_module._reset_for_tests()
    if original:
        # Restore env immediately (before monkeypatch teardown) and
        # reload the pepper so subsequent test collections find one.
        os.environ["API_KEY_PEPPER"] = original
        pepper_module.load_pepper(is_production=False)


class TestLoadPepper:
    def test_production_without_pepper_raises(self):
        with pytest.raises(pepper_module.PepperMissingError):
            pepper_module.load_pepper(is_production=True)

    def test_development_without_pepper_generates_ephemeral(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = pepper_module.load_pepper(is_production=False)
        assert isinstance(result, bytes)
        assert len(result) >= 32
        assert any(
            "EPHEMERAL pepper" in rec.message for rec in caplog.records
        )

    def test_base64_pepper_decoded(self, monkeypatch):
        raw = base64.b64encode(b"a" * 48).decode()
        monkeypatch.setenv("API_KEY_PEPPER", raw)
        result = pepper_module.load_pepper(is_production=True)
        assert result == b"a" * 48

    def test_raw_string_pepper_accepted_when_long_enough(self, monkeypatch):
        raw = "x" * 40
        monkeypatch.setenv("API_KEY_PEPPER", raw)
        result = pepper_module.load_pepper(is_production=True)
        assert result == raw.encode("utf-8")

    def test_short_raw_pepper_rejected(self, monkeypatch):
        monkeypatch.setenv("API_KEY_PEPPER", "tooshort")
        with pytest.raises(pepper_module.PepperMissingError):
            pepper_module.load_pepper(is_production=True)


class TestGetPepper:
    def test_before_load_raises(self):
        with pytest.raises(pepper_module.PepperMissingError):
            pepper_module.get_pepper()

    def test_after_load_returns_bytes(self, monkeypatch):
        monkeypatch.setenv("API_KEY_PEPPER", "x" * 40)
        pepper_module.load_pepper(is_production=True)
        assert pepper_module.get_pepper() == b"x" * 40
