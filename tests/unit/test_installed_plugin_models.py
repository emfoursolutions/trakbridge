# ABOUTME: Tests for models/installed_plugin.py — InstalledPlugin and PluginAuditLog.
# ABOUTME: Verifies fields, defaults, uniqueness, and timestamp mixin behaviour on sqlite.

import pytest

from database import db
from models.installed_plugin import InstalledPlugin, PluginAuditLog


@pytest.fixture
def session(app, db_session):
    return db_session


class TestInstalledPlugin:
    def test_create_with_defaults(self, app, session):
        plugin = InstalledPlugin(plugin_id="adsb", display_name="ADS-B")
        session.add(plugin)
        session.commit()

        row = session.get(InstalledPlugin, plugin.id)
        assert row.plugin_id == "adsb"
        assert row.is_enabled is True
        assert row.is_verified is False
        assert row.tier == "community"
        assert row.package_format == "package"
        assert row.created_at is not None
        assert row.updated_at is not None

    def test_plugin_id_unique(self, app, session):
        session.add(InstalledPlugin(plugin_id="dupe"))
        session.commit()
        session.add(InstalledPlugin(plugin_id="dupe"))
        with pytest.raises(Exception):
            session.commit()
        session.rollback()

    def test_full_field_round_trip(self, app, session):
        plugin = InstalledPlugin(
            plugin_id="sapient",
            display_name="SAPIENT",
            version="1.0.0",
            author="Emfour Solutions",
            description="BSI Flex 335 integration",
            plugin_type="gps",
            package_format="package",
            is_enabled=False,
            is_verified=True,
            tier="pro",
            install_path="sapient",
            installed_by="admin",
            metadata_json='{"id": "sapient"}',
        )
        session.add(plugin)
        session.commit()
        row = InstalledPlugin.query.filter_by(plugin_id="sapient").one()
        assert row.tier == "pro"
        assert row.is_verified is True
        assert row.plugin_type == "gps"


class TestPluginAuditLog:
    def test_create_audit_entry(self, app, session):
        entry = PluginAuditLog(
            plugin_id="adsb",
            action="installed",
            performed_by="admin",
            details='{"verified": true}',
        )
        session.add(entry)
        session.commit()
        row = session.get(PluginAuditLog, entry.id)
        assert row.action == "installed"
        assert row.performed_by == "admin"
        assert row.created_at is not None

    def test_query_by_plugin_id(self, app, session):
        for action in ("installed", "disabled"):
            session.add(
                PluginAuditLog(plugin_id="x", action=action, performed_by="admin")
            )
        session.commit()
        rows = PluginAuditLog.query.filter_by(plugin_id="x").all()
        assert {r.action for r in rows} == {"installed", "disabled"}
