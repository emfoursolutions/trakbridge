"""
ABOUTME: Admin blueprint for the plugin manager — list/detail pages, package upload,
ABOUTME: and enable/disable/uninstall lifecycle endpoints at /admin/plugins.

Author: Emfour Solutions
Created: 2026-07-16
"""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from services.auth import admin_required
from services.auth.decorators import get_current_user
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

bp = Blueprint("plugin_admin", __name__)

MAX_PLUGIN_UPLOAD_BYTES = 10 * 1024 * 1024

# Test seams: unit tests point these at isolated directories. None = defaults.
EXTERNAL_DIR_OVERRIDE = None
WHITELIST_OVERRIDE = None


def _username() -> str:
    return getattr(get_current_user(), "username", "unknown")


@bp.route("/")
@admin_required
def plugin_list():
    from services.license_service import get_license_service
    from services.plugin_admin_service import list_all_plugins

    return render_template(
        "admin/plugins.html",
        plugins=list_all_plugins(),
        current_tier=get_license_service().get_tier(),
    )


@bp.route("/<plugin_id>")
@admin_required
def plugin_detail(plugin_id):
    from services.license_service import get_license_service
    from services.plugin_admin_service import PluginInstallError, get_plugin_details

    try:
        details = get_plugin_details(plugin_id)
    except PluginInstallError:
        return render_template("errors/404.html"), 404
    return render_template(
        "admin/plugin_detail.html",
        plugin=details,
        current_tier=get_license_service().get_tier(),
    )


@bp.route("/upload", methods=["POST"])
@admin_required
def upload_plugin():
    from services.plugin_admin_service import PluginInstallError, install_plugin

    username = _username()
    uploaded = request.files.get("plugin_file")
    if not uploaded or not uploaded.filename:
        flash("No plugin package supplied — choose a .zip or .tar.gz file", "error")
        return redirect(url_for("plugin_admin.plugin_list"))

    data = uploaded.read(MAX_PLUGIN_UPLOAD_BYTES + 1)
    try:
        result = install_plugin(
            data,
            uploaded.filename,
            username,
            external_dir=EXTERNAL_DIR_OVERRIDE,
            whitelist_path=WHITELIST_OVERRIDE,
        )
    except (PluginInstallError, PermissionError) as e:
        logger.warning(
            f"AUDIT: plugin install rejected user={username} "
            f"filename={uploaded.filename} reason={e}"
        )
        flash(f"Plugin rejected: {e}", "error")
        return redirect(url_for("plugin_admin.plugin_list"))

    if result["verified"]:
        flash(
            f"Plugin '{result['plugin_id']}' installed (signature verified)",
            "success",
        )
    else:
        flash(
            f"Plugin '{result['plugin_id']}' installed UNVERIFIED — the package "
            f"carries no valid Emfour signature. Only install plugins from "
            f"sources you trust.",
            "warning",
        )
    return redirect(url_for("plugin_admin.plugin_list"))


def _lifecycle_endpoint(plugin_id, action):
    from services.plugin_admin_service import (
        PluginInstallError,
        disable_plugin,
        enable_plugin,
        uninstall_plugin,
    )

    username = _username()
    try:
        if action == "enable":
            enable_plugin(
                plugin_id,
                username,
                whitelist_path=WHITELIST_OVERRIDE,
                external_dir=EXTERNAL_DIR_OVERRIDE,
            )
        elif action == "disable":
            disable_plugin(plugin_id, username, whitelist_path=WHITELIST_OVERRIDE)
        else:
            uninstall_plugin(
                plugin_id,
                username,
                whitelist_path=WHITELIST_OVERRIDE,
                external_dir=EXTERNAL_DIR_OVERRIDE,
            )
    except (PluginInstallError, PermissionError) as e:
        logger.warning(
            f"AUDIT: plugin {action} rejected user={username} "
            f"plugin_id={plugin_id} reason={e}"
        )
        return jsonify({"success": False, "error": str(e)}), 400

    logger.info(f"AUDIT: plugin {action} user={username} plugin_id={plugin_id}")
    return jsonify({"success": True})


@bp.route("/<plugin_id>/enable", methods=["POST"])
@admin_required
def enable_plugin_route(plugin_id):
    return _lifecycle_endpoint(plugin_id, "enable")


@bp.route("/<plugin_id>/disable", methods=["POST"])
@admin_required
def disable_plugin_route(plugin_id):
    return _lifecycle_endpoint(plugin_id, "disable")


@bp.route("/<plugin_id>/uninstall", methods=["POST"])
@admin_required
def uninstall_plugin_route(plugin_id):
    return _lifecycle_endpoint(plugin_id, "uninstall")
