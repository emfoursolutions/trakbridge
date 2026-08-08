# ABOUTME: Tests for the plugin install validation chain in services/plugin_admin_service.py.
# ABOUTME: Every rejection path must clean up and leave no DB/whitelist/filesystem trace.

import base64
import io
import sys
import zipfile
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).parent.parent / "fixtures"))
from plugin_package_builder import (
    build_package_dir,
    build_plugin_zip,
    zip_package_dir,
)  # noqa: E402

from models.installed_plugin import InstalledPlugin, PluginAuditLog  # noqa: E402
from services.license_service import reset_license_service  # noqa: E402
from services.plugin_admin_service import (  # noqa: E402
    PluginInstallError,
    install_plugin,
    update_whitelist_file,
)


@pytest.fixture
def signing_keypair(monkeypatch):
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
def install_dirs(tmp_path, monkeypatch):
    """Isolated external_plugins dir and whitelist file for each test."""
    external = tmp_path / "external_plugins"
    external.mkdir()
    whitelist = tmp_path / "plugins.yaml"
    whitelist.write_text("allowed_plugin_modules: []\n")
    monkeypatch.setenv("TRAKBRIDGE_LICENSE_FILE", str(tmp_path / "no_license.json"))
    reset_license_service()
    yield external, whitelist
    reset_license_service()


def do_install(data, external, whitelist, filename="pkg.zip", username="admin"):
    return install_plugin(
        data,
        filename,
        username,
        external_dir=external,
        whitelist_path=whitelist,
    )


def assert_no_trace(external, whitelist, app):
    assert list(external.iterdir()) == []
    assert yaml.safe_load(whitelist.read_text())["allowed_plugin_modules"] == []
    assert InstalledPlugin.query.count() == 0


class TestInstallHappyPaths:
    def test_unsigned_package_installs_unverified(
        self, app, db_session, install_dirs, tmp_path, signing_keypair
    ):
        external, whitelist = install_dirs
        data = build_plugin_zip(tmp_path, "acme_tracker")
        result = do_install(data, external, whitelist)

        assert result["plugin_id"] == "acme_tracker"
        assert result["verified"] is False
        assert (external / "acme_tracker" / "plugin.yaml").is_file()
        row = InstalledPlugin.query.filter_by(plugin_id="acme_tracker").one()
        assert row.is_verified is False
        assert row.tier == "community"
        assert row.installed_by == "admin"
        assert (
            "external_plugins.acme_tracker"
            in yaml.safe_load(whitelist.read_text())["allowed_plugin_modules"]
        )
        audit = PluginAuditLog.query.filter_by(plugin_id="acme_tracker").one()
        assert audit.action == "installed"

    def test_signed_package_installs_verified(
        self, app, db_session, install_dirs, tmp_path, signing_keypair
    ):
        external, whitelist = install_dirs
        data = build_plugin_zip(tmp_path, "signed_tracker", sign_key=signing_keypair)
        result = do_install(data, external, whitelist)
        assert result["verified"] is True
        row = InstalledPlugin.query.filter_by(plugin_id="signed_tracker").one()
        assert row.is_verified is True

    def test_flat_zip_without_top_level_dir(
        self, app, db_session, install_dirs, tmp_path, signing_keypair
    ):
        external, whitelist = install_dirs
        pkg = build_package_dir(tmp_path / "src", "flat_tracker")
        data = zip_package_dir(pkg, top_level=False)
        result = do_install(data, external, whitelist)
        assert result["plugin_id"] == "flat_tracker"


class TestInstallRejections:
    def test_bad_extension(self, app, db_session, install_dirs, tmp_path):
        external, whitelist = install_dirs
        with pytest.raises(PluginInstallError, match="zip"):
            do_install(b"x", external, whitelist, filename="pkg.rar")
        assert_no_trace(external, whitelist, app)

    def test_oversized_archive(self, app, db_session, install_dirs):
        external, whitelist = install_dirs
        with pytest.raises(PluginInstallError, match="large"):
            do_install(b"0" * (10 * 1024 * 1024 + 1), external, whitelist)
        assert_no_trace(external, whitelist, app)

    def test_path_traversal_entry(self, app, db_session, install_dirs):
        external, whitelist = install_dirs
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.py", "x = 1")
        with pytest.raises(PluginInstallError, match="unsafe"):
            do_install(buf.getvalue(), external, whitelist)
        assert_no_trace(external, whitelist, app)

    def test_absolute_path_entry(self, app, db_session, install_dirs):
        external, whitelist = install_dirs
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/evil.py", "x = 1")
        with pytest.raises(PluginInstallError, match="unsafe"):
            do_install(buf.getvalue(), external, whitelist)

    def test_symlink_entry(self, app, db_session, install_dirs):
        external, whitelist = install_dirs
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("pkg/link.py")
            info.external_attr = 0o120777 << 16  # symlink mode
            zf.writestr(info, "target")
        with pytest.raises(PluginInstallError, match="unsafe"):
            do_install(buf.getvalue(), external, whitelist)

    def test_zip_bomb_rejected(self, app, db_session, install_dirs):
        external, whitelist = install_dirs
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("pkg/huge.bin", b"\0" * (51 * 1024 * 1024))
        with pytest.raises(PluginInstallError, match="decompressed"):
            do_install(buf.getvalue(), external, whitelist)

    def test_missing_manifest(self, app, db_session, install_dirs):
        external, whitelist = install_dirs
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("pkg/code.py", "x = 1")
        with pytest.raises(PluginInstallError, match="plugin.yaml"):
            do_install(buf.getvalue(), external, whitelist)

    def test_invalid_plugin_id(self, app, db_session, install_dirs, tmp_path):
        external, whitelist = install_dirs
        data = build_plugin_zip(tmp_path, "badid", manifest_overrides={"id": "Bad-Id!"})
        with pytest.raises(PluginInstallError, match="id"):
            do_install(data, external, whitelist)

    def test_unknown_tier(self, app, db_session, install_dirs, tmp_path):
        external, whitelist = install_dirs
        data = build_plugin_zip(tmp_path, "weird_tier", tier="platinum")
        with pytest.raises(PluginInstallError, match="tier"):
            do_install(data, external, whitelist)

    def test_min_version_too_high(self, app, db_session, install_dirs, tmp_path):
        external, whitelist = install_dirs
        data = build_plugin_zip(
            tmp_path,
            "future_plugin",
            manifest_overrides={"min_trakbridge_version": "99.0.0"},
        )
        with pytest.raises(PluginInstallError, match="or newer"):
            do_install(data, external, whitelist)

    def test_tier_above_licence_refused(self, app, db_session, install_dirs, tmp_path):
        external, whitelist = install_dirs
        data = build_plugin_zip(tmp_path, "premium_thing", tier="pro")
        with pytest.raises(PluginInstallError, match="licence|license|tier"):
            do_install(data, external, whitelist)
        assert_no_trace(external, whitelist, app)

    def test_tampered_signature_refused(
        self, app, db_session, install_dirs, tmp_path, signing_keypair
    ):
        external, whitelist = install_dirs
        pkg = build_package_dir(tmp_path / "src", "tampered", sign_key=signing_keypair)
        entry = pkg / "tampered.py"
        entry.write_text(entry.read_text() + "\n# evil\n")
        data = zip_package_dir(pkg)
        with pytest.raises(PluginInstallError, match="signature"):
            do_install(data, external, whitelist)
        assert_no_trace(external, whitelist, app)

    def test_dangerous_code_rejected(self, app, db_session, install_dirs, tmp_path):
        external, whitelist = install_dirs
        data = build_plugin_zip(
            tmp_path,
            "sneaky",
            extra_files={"helper.py": "import os\nos.system('rm -rf /')\n"},
        )
        with pytest.raises(PluginInstallError, match="dangerous"):
            do_install(data, external, whitelist)
        assert_no_trace(external, whitelist, app)

    def test_sdk_imports_allowed(
        self, app, db_session, install_dirs, tmp_path, signing_keypair
    ):
        external, whitelist = install_dirs
        data = build_plugin_zip(
            tmp_path,
            "sdk_importer",
            extra_files={"helper.py": "from trakbridge_sdk import PluginConfigField\n"},
        )
        result = do_install(data, external, whitelist)
        assert result["plugin_id"] == "sdk_importer"

    def test_class_not_plugin_subclass(self, app, db_session, install_dirs, tmp_path):
        external, whitelist = install_dirs
        data = build_plugin_zip(
            tmp_path,
            "not_a_plugin",
            code="class NotAPluginPlugin:\n    pass\n",
        )
        with pytest.raises(PluginInstallError, match="base class"):
            do_install(data, external, whitelist)

    def test_plugin_name_id_mismatch(self, app, db_session, install_dirs, tmp_path):
        external, whitelist = install_dirs
        data = build_plugin_zip(tmp_path, "declared_id", reported_name="different_name")
        with pytest.raises(PluginInstallError, match="plugin_name"):
            do_install(data, external, whitelist)

    def test_builtin_name_conflict(self, app, db_session, install_dirs, tmp_path):
        external, whitelist = install_dirs
        data = build_plugin_zip(tmp_path, "garmin", reported_name="garmin")
        with pytest.raises(PluginInstallError, match="built-in"):
            do_install(data, external, whitelist)

    def test_already_installed_rejected(self, app, db_session, install_dirs, tmp_path):
        external, whitelist = install_dirs
        data = build_plugin_zip(tmp_path, "twice_installed")
        do_install(data, external, whitelist)
        with pytest.raises(PluginInstallError, match="uninstall"):
            do_install(data, external, whitelist)

    def test_temp_dir_cleaned_on_rejection(
        self, app, db_session, install_dirs, tmp_path, monkeypatch
    ):
        import tempfile as tempfile_mod

        external, whitelist = install_dirs
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        real_mkdtemp = tempfile_mod.mkdtemp
        monkeypatch.setattr(
            "services.plugin_admin_service.tempfile.mkdtemp",
            lambda **kw: real_mkdtemp(dir=scratch),
        )
        data = build_plugin_zip(tmp_path, "cleanup_check", tier="platinum")
        with pytest.raises(PluginInstallError):
            do_install(data, external, whitelist)
        assert list(scratch.iterdir()) == []


class TestSignatureTierEnforcement:
    """Unsigned plugins are rejected only when the PLUGIN'S declared tier is
    pro/enterprise — the deployment tier does not restrict community plugins.
    A Pro or Enterprise deployment can still install unsigned community plugins
    with the UNVERIFIED warning; the signed-only guarantee applies only to
    premium plugins that claim Pro/Enterprise capability."""

    def test_unsigned_pro_plugin_rejected(
        self, app, db_session, install_dirs, tmp_path, signing_keypair, monkeypatch
    ):
        """A plugin manifesting tier=pro without a valid signature is refused,
        even if the deployment is Pro-licensed."""
        external, whitelist = install_dirs
        monkeypatch.setattr(
            "services.license_service.get_license_service",
            lambda: type("_LS", (), {"is_tier_allowed": lambda self, t: True, "get_tier": lambda self: "pro"})(),
        )
        data = build_plugin_zip(tmp_path, "unsigned_pro_plugin", tier="pro")
        with pytest.raises(PluginInstallError, match="[Uu]nsigned|signature"):
            do_install(data, external, whitelist)
        assert_no_trace(external, whitelist, app)

    def test_unsigned_enterprise_plugin_rejected(
        self, app, db_session, install_dirs, tmp_path, signing_keypair, monkeypatch
    ):
        """A plugin manifesting tier=enterprise without a valid signature is refused."""
        external, whitelist = install_dirs
        monkeypatch.setattr(
            "services.license_service.get_license_service",
            lambda: type("_LS", (), {"is_tier_allowed": lambda self, t: True, "get_tier": lambda self: "enterprise"})(),
        )
        data = build_plugin_zip(tmp_path, "unsigned_ent_plugin", tier="enterprise")
        with pytest.raises(PluginInstallError, match="[Uu]nsigned|signature"):
            do_install(data, external, whitelist)
        assert_no_trace(external, whitelist, app)

    def test_unsigned_community_plugin_allowed_on_pro_deployment(
        self, app, db_session, install_dirs, tmp_path, signing_keypair, monkeypatch
    ):
        """Regression: a Pro deployment can still install unsigned community
        plugins. The signed-only rule binds premium plugins, not paying customers."""
        external, whitelist = install_dirs
        monkeypatch.setattr(
            "services.license_service.get_license_service",
            lambda: type("_LS", (), {"is_tier_allowed": lambda self, t: True, "get_tier": lambda self: "pro"})(),
        )
        data = build_plugin_zip(tmp_path, "community_on_pro")
        result = do_install(data, external, whitelist)
        assert result["verified"] is False

    def test_unsigned_community_plugin_allowed_on_community_deployment(
        self, app, db_session, install_dirs, tmp_path, signing_keypair
    ):
        """Regression: unchanged behaviour for community deployment + community plugin."""
        external, whitelist = install_dirs
        data = build_plugin_zip(tmp_path, "unsigned_community_plugin")
        result = do_install(data, external, whitelist)
        assert result["verified"] is False

    def test_signed_pro_plugin_allowed_on_pro_deployment(
        self, app, db_session, install_dirs, tmp_path, signing_keypair, monkeypatch
    ):
        """Sanity: a properly signed Pro plugin installs on a Pro deployment."""
        external, whitelist = install_dirs
        monkeypatch.setattr(
            "services.license_service.get_license_service",
            lambda: type("_LS", (), {"is_tier_allowed": lambda self, t: True, "get_tier": lambda self: "pro"})(),
        )
        data = build_plugin_zip(tmp_path, "signed_pro_plugin", tier="pro", sign_key=signing_keypair)
        result = do_install(data, external, whitelist)
        assert result["verified"] is True


class TestUpdateWhitelistFile:
    def test_add_and_remove(self, tmp_path):
        path = tmp_path / "plugins.yaml"
        path.write_text("allowed_plugin_modules: []\nother_key: keepme\n")
        update_whitelist_file(add=["external_plugins.a"], path=path)
        update_whitelist_file(add=["external_plugins.b"], path=path)
        data = yaml.safe_load(path.read_text())
        assert sorted(data["allowed_plugin_modules"]) == [
            "external_plugins.a",
            "external_plugins.b",
        ]
        assert data["other_key"] == "keepme"

        update_whitelist_file(remove=["external_plugins.a"], path=path)
        data = yaml.safe_load(path.read_text())
        assert data["allowed_plugin_modules"] == ["external_plugins.b"]

    def test_idempotent_add(self, tmp_path):
        path = tmp_path / "plugins.yaml"
        path.write_text("allowed_plugin_modules: []\n")
        update_whitelist_file(add=["external_plugins.a"], path=path)
        update_whitelist_file(add=["external_plugins.a"], path=path)
        data = yaml.safe_load(path.read_text())
        assert data["allowed_plugin_modules"] == ["external_plugins.a"]

    def test_file_mode_is_0600_after_write(self, tmp_path):
        """Written whitelist file must be owner-read/write only (mode 0o600)."""
        import os

        path = tmp_path / "plugins.yaml"
        path.write_text("allowed_plugin_modules: []\n")
        update_whitelist_file(add=["external_plugins.a"], path=path)
        mode = os.stat(path).st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:o}"

    def test_symlink_at_target_path_is_rejected(self, tmp_path):
        """If the whitelist path is a symlink, update_whitelist_file must raise PermissionError."""
        real_file = tmp_path / "real_plugins.yaml"
        real_file.write_text("allowed_plugin_modules: []\n")
        link_path = tmp_path / "plugins.yaml"
        link_path.symlink_to(real_file)
        original_content = real_file.read_text()

        with pytest.raises(PermissionError):
            update_whitelist_file(add=["external_plugins.a"], path=link_path)

        # The pointed-to file must not be modified
        assert real_file.read_text() == original_content

    def test_symlink_at_parent_dir_is_rejected(self, tmp_path):
        """If the parent directory of the whitelist path is a symlink, raise PermissionError."""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        link_dir = tmp_path / "link_dir"
        link_dir.symlink_to(real_dir)
        path_inside_link = link_dir / "plugins.yaml"

        with pytest.raises(PermissionError):
            update_whitelist_file(add=["external_plugins.a"], path=path_inside_link)

    def test_regression_add_remove_non_symlink(self, tmp_path):
        """Non-symlink path must still correctly add and remove entries."""
        path = tmp_path / "plugins.yaml"
        path.write_text("allowed_plugin_modules: []\n")
        update_whitelist_file(add=["external_plugins.x"], path=path)
        data = yaml.safe_load(path.read_text())
        assert "external_plugins.x" in data["allowed_plugin_modules"]

        update_whitelist_file(remove=["external_plugins.x"], path=path)
        data = yaml.safe_load(path.read_text())
        assert "external_plugins.x" not in data["allowed_plugin_modules"]
