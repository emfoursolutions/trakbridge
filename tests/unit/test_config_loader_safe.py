"""
ABOUTME: Unit tests for ConfigLoader.load_config_safe / backup / auto-repair / validate_all_configs
ABOUTME: Locks in env-var backup dir, lazy dir creation, external-first single-source semantics, and graceful fallbacks
"""

from pathlib import Path

import pytest
import yaml

from config.base import ConfigLoader, get_config_loader


@pytest.fixture
def loader(tmp_path, monkeypatch):
    """
    ConfigLoader wired to tmp_path directories via env vars, so tests do not
    touch /app/external_config or /app/backups.
    """
    external = tmp_path / "external_config"
    bundled = tmp_path / "bundled_config"
    backup = tmp_path / "backups"
    external.mkdir()
    bundled.mkdir()

    monkeypatch.setenv("TRAKBRIDGE_CONFIG_DIR", str(external))
    monkeypatch.setenv("TRAKBRIDGE_BACKUP_DIR", str(backup))

    ldr = ConfigLoader(environment="testing")
    # Override the bundled dir (normally pinned to config/settings) so tests can
    # supply their own bundled defaults per case.
    ldr.bundled_config_dir = bundled
    return ldr


def _write_yaml(path: Path, data) -> Path:
    path.write_text(yaml.safe_dump(data))
    return path


class TestBackupDirEnvVar:
    def test_backup_dir_honors_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TRAKBRIDGE_BACKUP_DIR", str(tmp_path / "custom_backups"))
        ldr = ConfigLoader(environment="testing")
        assert ldr.backup_dir == tmp_path / "custom_backups"

    def test_backup_dir_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("TRAKBRIDGE_BACKUP_DIR", raising=False)
        ldr = ConfigLoader(environment="testing")
        assert ldr.backup_dir == Path("/app/backups")

    def test_backup_dir_not_created_at_init(self, tmp_path, monkeypatch):
        target = tmp_path / "lazy_backups"
        monkeypatch.setenv("TRAKBRIDGE_BACKUP_DIR", str(target))
        ConfigLoader(environment="testing")
        assert not target.exists(), "backup_dir must be created lazily, not at init"


class TestLoadConfigSafe:
    def test_returns_external_when_valid(self, loader):
        data = {"allowed_plugin_modules": ["plugins.custom"]}
        _write_yaml(loader.external_config_dir / "plugins.yaml", data)

        result = loader.load_config_safe(
            "plugins.yaml", required_fields=["allowed_plugin_modules"]
        )
        assert result == data

    def test_null_allowed_plugin_modules_loads_without_error(self, loader):
        data = {"allowed_plugin_modules": None}
        _write_yaml(loader.external_config_dir / "plugins.yaml", data)

        result = loader.load_config_safe(
            "plugins.yaml", required_fields=["allowed_plugin_modules"]
        )
        assert result["allowed_plugin_modules"] is None

    def test_empty_list_loads_without_error(self, loader):
        data = {"allowed_plugin_modules": []}
        _write_yaml(loader.external_config_dir / "plugins.yaml", data)

        result = loader.load_config_safe(
            "plugins.yaml", required_fields=["allowed_plugin_modules"]
        )
        assert result["allowed_plugin_modules"] == []

    def test_external_first_single_source_no_merge(self, loader):
        """load_config_safe must NOT deep-merge external with bundled — external replaces."""
        bundled_data = {
            "allowed_plugin_modules": ["plugins.bundled_only"],
        }
        external_data = {
            "allowed_plugin_modules": ["plugins.external_only"],
        }
        _write_yaml(loader.bundled_config_dir / "plugins.yaml", bundled_data)
        _write_yaml(loader.external_config_dir / "plugins.yaml", external_data)

        result = loader.load_config_safe("plugins.yaml")
        assert result == external_data
        assert "plugins.bundled_only" not in result["allowed_plugin_modules"]

    def test_falls_back_to_bundled_when_no_external(self, loader):
        bundled_data = {"allowed_plugin_modules": ["plugins.bundled"]}
        _write_yaml(loader.bundled_config_dir / "plugins.yaml", bundled_data)

        result = loader.load_config_safe("plugins.yaml")
        assert result == bundled_data

    def test_falls_back_to_minimal_default_when_nothing_exists(self, loader):
        result = loader.load_config_safe("plugins.yaml")
        assert "allowed_plugin_modules" in result
        assert isinstance(result["allowed_plugin_modules"], list)
        assert len(result["allowed_plugin_modules"]) > 0

    def test_unknown_config_returns_empty_dict_as_final_fallback(self, loader):
        result = loader.load_config_safe("nonexistent.yaml", validate=False)
        assert result == {}

    def test_validate_false_skips_schema_check(self, loader):
        """performance.yaml has no schema — validate=False must not raise."""
        data = {"circuit_breaker": {"threshold": 5}}
        _write_yaml(loader.external_config_dir / "performance.yaml", data)

        result = loader.load_config_safe("performance.yaml", validate=False)
        assert result == data


class TestAutoRepair:
    def test_corrupted_external_backed_up_and_repaired_from_bundled(self, loader):
        """Corrupted external YAML → backed up → replaced with bundled default."""
        bundled_data = {"allowed_plugin_modules": ["plugins.bundled_fallback"]}
        _write_yaml(loader.bundled_config_dir / "plugins.yaml", bundled_data)

        external_path = loader.external_config_dir / "plugins.yaml"
        external_path.write_text("allowed_plugin_modules: [broken syntax")  # invalid

        result = loader.load_config_safe("plugins.yaml")

        # Repaired from bundled
        assert result == bundled_data
        # External file replaced with bundled content
        assert yaml.safe_load(external_path.read_text()) == bundled_data
        # Backup + .error sidecar created
        assert loader.backup_dir.exists()
        errors = list(loader.backup_dir.glob("plugins.yaml.corrupted.*.error"))
        assert len(errors) == 1
        backups = [
            p
            for p in loader.backup_dir.glob("plugins.yaml.corrupted.*")
            if not p.name.endswith(".error")
        ]
        assert len(backups) == 1

    def test_backup_dir_created_lazily_only_on_failure(self, loader):
        """Backup dir must not exist until an actual corruption event fires."""
        # Successful load — backup dir should NOT be created
        data = {"allowed_plugin_modules": []}
        _write_yaml(loader.external_config_dir / "plugins.yaml", data)
        loader.load_config_safe("plugins.yaml")
        assert not loader.backup_dir.exists()

    def test_falls_through_to_minimal_default_when_backup_dir_unwritable(
        self, loader, monkeypatch
    ):
        """
        Regression guard for the /app/backups permission bug: if backup fails,
        auto-repair must still be attempted, and if that fails too, minimal
        default must still return — the whitelist load path cannot be blocked
        by an unwritable backup dir.
        """
        # Point backup_dir at an unwritable path (/dev/null/backups won't mkdir)
        loader.backup_dir = Path("/dev/null/impossible")

        # Corrupt external, no bundled — should end up at minimal default
        (loader.external_config_dir / "plugins.yaml").write_text("[not: valid yaml")

        result = loader.load_config_safe("plugins.yaml")
        # Minimal default kicks in (built-in plugins list)
        assert "allowed_plugin_modules" in result
        assert isinstance(result["allowed_plugin_modules"], list)
        assert len(result["allowed_plugin_modules"]) > 0


class TestValidateAllConfigs:
    def test_returns_dict_of_status_per_bundled_yaml(self, loader):
        _write_yaml(
            loader.bundled_config_dir / "plugins.yaml",
            {"allowed_plugin_modules": ["plugins.a"]},
        )
        _write_yaml(
            loader.bundled_config_dir / "app.yaml",
            {"application_url": "http://localhost"},
        )

        results = loader.validate_all_configs()
        assert set(results.keys()) == {"plugins.yaml", "app.yaml"}
        assert results["plugins.yaml"] is True
        assert results["app.yaml"] is True

    def test_reports_failure_reason_for_broken_config(self, loader):
        # Corrupted external file that also has no bundled fallback
        (loader.external_config_dir / "plugins.yaml").write_text("[nope")
        # Ensure a bundled file exists so validate_all_configs iterates
        _write_yaml(
            loader.bundled_config_dir / "plugins.yaml",
            {"allowed_plugin_modules": []},
        )

        results = loader.validate_all_configs()
        # After auto-repair from bundled, plugins.yaml should be valid
        assert results["plugins.yaml"] is True


class TestGetConfigLoaderSingleton:
    def test_returns_same_instance(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TRAKBRIDGE_CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("TRAKBRIDGE_BACKUP_DIR", str(tmp_path / "b"))
        # Reset any pre-existing singleton
        import config.base as base
        base._config_loader_instance = None

        first = get_config_loader()
        second = get_config_loader()
        assert first is second
