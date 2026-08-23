"""
ABOUTME: Integration test for PluginManager whitelist loading via ConfigLoader
ABOUTME: Regression guard for the /app/backups permission bug — proves whitelist loads even when backup dir is unwritable
"""

from pathlib import Path

import pytest
import yaml

from plugins.plugin_manager import PluginManager


def _write_plugins_yaml(external_dir: Path, modules):
    external_dir.mkdir(parents=True, exist_ok=True)
    (external_dir / "plugins.yaml").write_text(
        yaml.safe_dump({"allowed_plugin_modules": modules})
    )


@pytest.fixture(autouse=True)
def _reset_config_loader_singleton():
    """Force a fresh ConfigLoader per test so env-var monkeypatching applies."""
    import config.base as base
    base._config_loader_instance = None
    yield
    base._config_loader_instance = None


def test_external_plugin_modules_added_to_whitelist(tmp_path, monkeypatch):
    """External plugins.yaml with external_plugins.* entries must land in _allowed_modules."""
    external = tmp_path / "external_config"
    _write_plugins_yaml(
        external,
        [
            "external_plugins.adsb",
            "external_plugins.ais_digitraffic",
            "external_plugins.lightnings_fmi",
        ],
    )
    monkeypatch.setenv("TRAKBRIDGE_CONFIG_DIR", str(external))
    monkeypatch.setenv("TRAKBRIDGE_BACKUP_DIR", str(tmp_path / "backups"))

    mgr = PluginManager()

    assert "external_plugins.adsb" in mgr._allowed_modules
    assert "external_plugins.ais_digitraffic" in mgr._allowed_modules
    assert "external_plugins.lightnings_fmi" in mgr._allowed_modules
    # Built-ins still present
    assert "plugins.garmin_plugin" in mgr._allowed_modules


def test_whitelist_loads_when_backup_dir_unwritable(tmp_path, monkeypatch):
    """
    The original bug: /app/backups is root-owned so the backup step fails,
    the whole safe-load path errors, and the whitelist never loads. Guard:
    even with an unwritable backup dir AND a corrupted external file, the
    whitelist load path must complete via the bundled+minimal fallback.
    """
    external = tmp_path / "external_config"
    external.mkdir()
    # Corrupt external plugins.yaml — forces the backup-and-repair path
    (external / "plugins.yaml").write_text("allowed_plugin_modules: [broken")

    monkeypatch.setenv("TRAKBRIDGE_CONFIG_DIR", str(external))
    # Unwritable backup dir simulates the /app/backups root-ownership case
    monkeypatch.setenv("TRAKBRIDGE_BACKUP_DIR", "/dev/null/impossible")

    # Must not raise; PluginManager falls back to built-in modules only
    mgr = PluginManager()

    assert "plugins.garmin_plugin" in mgr._allowed_modules
    assert "plugins.spot_plugin" in mgr._allowed_modules


def test_missing_external_config_uses_bundled_defaults(tmp_path, monkeypatch):
    """No external plugins.yaml → PluginManager loads bundled defaults; built-ins present."""
    empty_dir = tmp_path / "external_config"
    empty_dir.mkdir()
    monkeypatch.setenv("TRAKBRIDGE_CONFIG_DIR", str(empty_dir))
    monkeypatch.setenv("TRAKBRIDGE_BACKUP_DIR", str(tmp_path / "backups"))

    mgr = PluginManager()

    assert "plugins.garmin_plugin" in mgr._allowed_modules
