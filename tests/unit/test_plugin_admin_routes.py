# ABOUTME: Tests for routes/plugin_admin.py — the /admin/plugins blueprint.
# ABOUTME: Covers auth, listing, upload (happy/reject), lifecycle JSON endpoints, and the 12MB cap.

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "fixtures"))
from plugin_package_builder import build_plugin_zip  # noqa: E402

from services.license_service import reset_license_service  # noqa: E402
from tests.conftest import get_csrf_token  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch, app, db_session):
    external = tmp_path / "external_plugins"
    external.mkdir()
    whitelist = tmp_path / "plugins.yaml"
    whitelist.write_text("allowed_plugin_modules: []\n")
    monkeypatch.setenv("TRAKBRIDGE_LICENSE_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr(
        "routes.plugin_admin.EXTERNAL_DIR_OVERRIDE", external, raising=False
    )
    monkeypatch.setattr(
        "routes.plugin_admin.WHITELIST_OVERRIDE", whitelist, raising=False
    )
    reset_license_service()
    yield external, whitelist
    reset_license_service()


def upload(client, data, filename="pkg.zip", app=None):
    """Upload a plugin package. Includes CSRF token if app is provided."""
    headers = {}
    form_data = {"plugin_file": (io.BytesIO(data), filename)}
    if app is not None:
        form_data["csrf_token"] = get_csrf_token(client, app)
    return client.post(
        "/admin/plugins/upload",
        data=form_data,
        content_type="multipart/form-data",
        follow_redirects=True,
        headers=headers,
    )


class TestAuth:
    def test_list_requires_admin(self, client, env):
        assert client.get("/admin/plugins/").status_code in (302, 401, 403)

    def test_upload_requires_admin(self, client, env):
        response = client.post("/admin/plugins/upload", data={})
        # CSRF now fires before auth check for unauthenticated POSTs, so 400 is acceptable
        assert response.status_code in (302, 400, 401, 403)


class TestListPage:
    def test_list_shows_builtin_plugins(self, authenticated_client, env, app):
        client = authenticated_client("admin")
        response = client.get("/admin/plugins/")
        assert response.status_code == 200
        assert b"garmin" in response.data.lower()

    def test_detail_page_for_installed_plugin(
        self, authenticated_client, env, tmp_path, app
    ):
        external, whitelist = env
        client = authenticated_client("admin")
        upload(client, build_plugin_zip(tmp_path, "detail_me"), app=app)
        response = client.get("/admin/plugins/detail_me")
        assert response.status_code == 200
        assert b"detail_me" in response.data

    def test_detail_page_unknown_404(self, authenticated_client, env, app):
        client = authenticated_client("admin")
        assert client.get("/admin/plugins/ghost").status_code == 404


class TestUpload:
    def test_upload_installs_plugin(self, authenticated_client, env, tmp_path, app):
        external, whitelist = env
        client = authenticated_client("admin")
        response = upload(client, build_plugin_zip(tmp_path, "route_installed"), app=app)
        assert response.status_code == 200
        assert (external / "route_installed" / "plugin.yaml").is_file()
        assert b"route_installed" in response.data

    def test_unsigned_upload_flashes_unverified_warning(
        self, authenticated_client, env, tmp_path, app
    ):
        client = authenticated_client("admin")
        response = upload(client, build_plugin_zip(tmp_path, "warn_me"), app=app)
        assert b"UNVERIFIED" in response.data or b"unverified" in response.data

    def test_rejected_upload_flashes_error(self, authenticated_client, env, tmp_path, app):
        external, whitelist = env
        client = authenticated_client("admin")
        response = upload(client, build_plugin_zip(tmp_path, "pro_only", tier="pro"), app=app)
        assert b"rejected" in response.data.lower()
        assert not (external / "pro_only").exists()

    def test_missing_file_flashes_error(self, authenticated_client, env, app):
        client = authenticated_client("admin")
        token = get_csrf_token(client, app)
        response = client.post(
            "/admin/plugins/upload",
            data={"csrf_token": token},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert (
            b"No plugin package" in response.data
            or b"rejected" in response.data.lower()
        )


class TestLifecycleEndpoints:
    def test_disable_enable_round_trip(self, authenticated_client, env, tmp_path, app):
        client = authenticated_client("admin")
        upload(client, build_plugin_zip(tmp_path, "toggle_me"), app=app)

        token = get_csrf_token(client, app)
        response = client.post("/admin/plugins/toggle_me/disable",
                               headers={"X-CSRFToken": token})
        assert response.status_code == 200
        assert response.get_json()["success"] is True

        token = get_csrf_token(client, app)
        response = client.post("/admin/plugins/toggle_me/enable",
                               headers={"X-CSRFToken": token})
        assert response.status_code == 200
        assert response.get_json()["success"] is True

    def test_uninstall(self, authenticated_client, env, tmp_path, app):
        external, whitelist = env
        client = authenticated_client("admin")
        upload(client, build_plugin_zip(tmp_path, "remove_me"), app=app)
        token = get_csrf_token(client, app)
        response = client.post("/admin/plugins/remove_me/uninstall",
                               headers={"X-CSRFToken": token})
        assert response.status_code == 200
        assert response.get_json()["success"] is True
        assert not (external / "remove_me").exists()

    def test_lifecycle_error_returns_400(self, authenticated_client, env, app):
        client = authenticated_client("admin")
        token = get_csrf_token(client, app)
        response = client.post("/admin/plugins/ghost/disable",
                               headers={"X-CSRFToken": token})
        assert response.status_code == 400
        assert response.get_json()["success"] is False


class TestContentLength:
    def test_global_limit_allows_plugin_sized_uploads(self, app):
        assert app.config["MAX_CONTENT_LENGTH"] == 12 * 1024 * 1024

    def test_oversized_plugin_rejected_by_route_cap(self, authenticated_client, env, app):
        client = authenticated_client("admin")
        response = upload(client, b"0" * (10 * 1024 * 1024 + 1), app=app)
        assert b"rejected" in response.data.lower() or b"large" in response.data.lower()
