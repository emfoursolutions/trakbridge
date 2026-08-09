# ABOUTME: Tests for plugin lifecycle functions — enable/disable/uninstall/sync/list.
# ABOUTME: Covers stream-in-use blocking, tier re-checks, and filesystem/DB reconciliation.

import base64
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).parent.parent / "fixtures"))
from plugin_package_builder import build_package_dir, build_plugin_zip  # noqa: E402

from models.installed_plugin import InstalledPlugin, PluginAuditLog  # noqa: E402
from models.stream import Stream  # noqa: E402
from services.license_service import reset_license_service  # noqa: E402
from services.plugin_admin_service import (  # noqa: E402
    PluginInstallError,
    disable_plugin,
    enable_plugin,
    install_plugin,
    list_all_plugins,
    sync_plugin_registry,
    uninstall_plugin,
)


@pytest.fixture
def signing_keypair(monkeypatch):
    """Emfour signing keypair for tests that need to build a signed plugin
    package (required for pro/enterprise tier plugins post-2.1.0)."""
    key = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    monkeypatch.setattr(
        "services.license_service.EMBEDDED_LICENSE_PUBLIC_KEY", public_b64
    )
    return key


@pytest.fixture
def env(tmp_path, monkeypatch, app, db_session):
    external = tmp_path / "external_plugins"
    external.mkdir()
    whitelist = tmp_path / "plugins.yaml"
    whitelist.write_text("allowed_plugin_modules: []\n")
    monkeypatch.setenv("TRAKBRIDGE_LICENSE_FILE", str(tmp_path / "none.json"))
    reset_license_service()
    yield external, whitelist
    reset_license_service()


def install(tmp_path, external, whitelist, plugin_id="lifecycle_plugin", **kwargs):
    data = build_plugin_zip(tmp_path, plugin_id, **kwargs)
    return install_plugin(
        data, "pkg.zip", "admin", external_dir=external, whitelist_path=whitelist
    )


def whitelist_modules(whitelist):
    return yaml.safe_load(whitelist.read_text())["allowed_plugin_modules"]


class TestDisableEnable:
    def test_disable_clears_flag_whitelist_and_registry(self, env, tmp_path):
        external, whitelist = env
        install(tmp_path, external, whitelist)
        disable_plugin("lifecycle_plugin", "admin", whitelist_path=whitelist)

        row = InstalledPlugin.query.filter_by(plugin_id="lifecycle_plugin").one()
        assert row.is_enabled is False
        assert "external_plugins.lifecycle_plugin" not in whitelist_modules(whitelist)
        actions = [
            a.action
            for a in PluginAuditLog.query.filter_by(plugin_id="lifecycle_plugin").all()
        ]
        assert "disabled" in actions

    def test_enable_restores_flag_and_whitelist(self, env, tmp_path):
        external, whitelist = env
        install(tmp_path, external, whitelist)
        disable_plugin("lifecycle_plugin", "admin", whitelist_path=whitelist)
        enable_plugin(
            "lifecycle_plugin",
            "admin",
            whitelist_path=whitelist,
            external_dir=external,
        )
        row = InstalledPlugin.query.filter_by(plugin_id="lifecycle_plugin").one()
        assert row.is_enabled is True
        assert "external_plugins.lifecycle_plugin" in whitelist_modules(whitelist)

    def test_disable_blocked_when_stream_uses_plugin(self, env, tmp_path, db_session):
        external, whitelist = env
        install(tmp_path, external, whitelist)
        db_session.add(Stream(name="s1", plugin_type="lifecycle_plugin"))
        db_session.commit()
        with pytest.raises(PluginInstallError, match="stream"):
            disable_plugin("lifecycle_plugin", "admin", whitelist_path=whitelist)

    def test_enable_refused_when_tier_above_licence(
        self, env, tmp_path, signing_keypair
    ):
        external, whitelist = env
        with patch(
            "services.license_service.LicenseService.is_tier_allowed",
            return_value=True,
        ):
            # Pro-tier plugin must be signed post-2.1.0 — sign the setup package.
            install(
                tmp_path,
                external,
                whitelist,
                "premium_one",
                tier="pro",
                sign_key=signing_keypair,
            )
            disable_plugin("premium_one", "admin", whitelist_path=whitelist)
        # licence back to community now
        with pytest.raises(PluginInstallError, match="tier|licen"):
            enable_plugin(
                "premium_one",
                "admin",
                whitelist_path=whitelist,
                external_dir=external,
            )

    def test_unknown_plugin_raises(self, env):
        external, whitelist = env
        with pytest.raises(PluginInstallError, match="not installed"):
            disable_plugin("ghost", "admin", whitelist_path=whitelist)


class TestUninstall:
    def test_uninstall_removes_everything(self, env, tmp_path):
        external, whitelist = env
        install(tmp_path, external, whitelist, "shortlived")
        uninstall_plugin(
            "shortlived", "admin", whitelist_path=whitelist, external_dir=external
        )
        assert not (external / "shortlived").exists()
        assert InstalledPlugin.query.filter_by(plugin_id="shortlived").count() == 0
        assert "external_plugins.shortlived" not in whitelist_modules(whitelist)
        actions = [
            a.action
            for a in PluginAuditLog.query.filter_by(plugin_id="shortlived").all()
        ]
        assert "uninstalled" in actions

    def test_uninstall_blocked_when_stream_uses_plugin(self, env, tmp_path, db_session):
        external, whitelist = env
        install(tmp_path, external, whitelist, "in_use")
        db_session.add(Stream(name="s1", plugin_type="in_use"))
        db_session.commit()
        with pytest.raises(PluginInstallError, match="stream"):
            uninstall_plugin(
                "in_use", "admin", whitelist_path=whitelist, external_dir=external
            )
        assert (external / "in_use").exists()


class TestSyncPluginRegistry:
    def test_new_package_dir_gets_db_row_and_whitelist(self, env, tmp_path):
        external, whitelist = env
        build_package_dir(external, "dropped_in", tier="community")
        sync_plugin_registry(external_dir=external, whitelist_path=whitelist)
        row = InstalledPlugin.query.filter_by(plugin_id="dropped_in").one()
        assert row.package_format == "package"
        assert row.installed_by == "system-sync"
        assert "external_plugins.dropped_in" in whitelist_modules(whitelist)

    def test_missing_dir_removes_db_row(self, env, tmp_path, db_session):
        external, whitelist = env
        db_session.add(InstalledPlugin(plugin_id="vanished"))
        db_session.commit()
        sync_plugin_registry(external_dir=external, whitelist_path=whitelist)
        assert InstalledPlugin.query.filter_by(plugin_id="vanished").count() == 0

    def test_legacy_flat_file_recorded(self, env, tmp_path):
        external, whitelist = env
        (external / "old_style.py").write_text(
            "from plugins.base_plugin import BaseGPSPlugin\n"
        )
        sync_plugin_registry(external_dir=external, whitelist_path=whitelist)
        row = InstalledPlugin.query.filter_by(plugin_id="old_style").one()
        assert row.package_format == "legacy"
        assert "external_plugins.old_style" in whitelist_modules(whitelist)

    def test_sync_is_idempotent(self, env, tmp_path):
        external, whitelist = env
        build_package_dir(external, "steady")
        sync_plugin_registry(external_dir=external, whitelist_path=whitelist)
        sync_plugin_registry(external_dir=external, whitelist_path=whitelist)
        assert InstalledPlugin.query.filter_by(plugin_id="steady").count() == 1


class TestListAllPlugins:
    def test_merges_builtin_and_external(self, env, tmp_path):
        external, whitelist = env
        install(tmp_path, external, whitelist, "merged_ext")
        plugins = {p["plugin_id"]: p for p in list_all_plugins()}
        assert plugins["merged_ext"]["source"] == "external"
        assert plugins["merged_ext"]["is_enabled"] is True
        assert "garmin" in plugins
        assert plugins["garmin"]["source"] == "builtin"
