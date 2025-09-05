"""
File: routes/admin.py

Description:
   Admin dashboard blueprint for the TrakBridge application. Provides comprehensive administrative
   interface with system monitoring, key rotation management, and application status endpoints.
   Displays real-time metrics including uptime, stream counts, server statistics, and system
   information. Features secure key rotation capabilities with backup options and status tracking.

Key features:
   - `/admin/`: Main dashboard with system metrics, stream/server counts, and platform info
   - `/admin/version`: JSON endpoint returning app version and uptime information
   - `/admin/about`: Static about page for administrative interface
   - `/admin/key-rotation`: Key rotation management interface with system status
   - `/admin/key-rotation/start`: POST endpoint to initiate key rotation process
   - `/admin/key-rotation/status`: Real-time key rotation status monitoring
   - `/admin/key-rotation/restart-info`: Application restart information endpoint
   - `get_uptime()`: Calculates server uptime since application startup
   - `get_app_version()`: Retrieves version from package metadata or environment fallback

Author: Emfour Solutions
Created: 2025-07-05
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import datetime

# Third-party imports
import platform
import time

# Third-party imports
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

# Authentication imports
from services.auth import admin_required

# Local application imports
from services.key_rotation_service import get_key_rotation_service

# Module-level logger
from services.logging_service import get_module_logger
from services.version import get_version

logger = get_module_logger(__name__)

bp = Blueprint("admin", __name__)

# Capture app start time for uptime display
start_time = time.time()


@bp.route("/system_info")
@admin_required
def admin_dashboard():
    from database import db
    from models.stream import Stream
    from models.tak_server import TakServer

    # Make sure start_time is defined somewhere globally
    uptime = datetime.timedelta(seconds=int(time.time() - start_time))
    streams_count = db.session.query(Stream).count()
    servers_count = db.session.query(TakServer).count()

    # Use the correct stream_manager instance
    stream_manager = getattr(current_app, "stream_manager", None)
    running_streams = sum(
        1 for status in stream_manager.get_all_stream_status().values() if status.get("running")
    )

    return render_template(
        "admin/dashboard.html",
        uptime=uptime,
        streams_count=streams_count,
        servers_count=servers_count,
        running_streams=running_streams,
        python_version=platform.python_version(),
        system=platform.system(),
        release=platform.release(),
        version=get_version(),
    )


@bp.route("/about")
@admin_required
def admin_about():
    return render_template("admin/about.html")


@bp.route("/key-rotation")
@admin_required
def key_rotation_page():
    """Key rotation management page"""
    try:
        key_rotation_service = get_key_rotation_service()

        # Get current system information
        db_info = key_rotation_service.get_database_info()
        storage_info = key_rotation_service.get_key_storage_info()
        rotation_status = key_rotation_service.get_rotation_status()

        return render_template(
            "admin/key_rotation.html",
            db_info=db_info,
            storage_info=storage_info,
            rotation_status=rotation_status,
        )
    except Exception as e:
        flash(f"Error loading key rotation page: {e}", "error")
        return redirect(url_for("admin.admin_dashboard"))


@bp.route("/key-rotation/start", methods=["POST"])
@admin_required
def start_key_rotation():
    """Start key rotation process"""
    try:
        data = request.get_json()
        new_key = data.get("new_key")
        create_backup = data.get("create_backup", True)

        if not new_key:
            return jsonify({"success": False, "error": "New key is required"}), 400

        key_rotation_service = get_key_rotation_service()
        result = key_rotation_service.start_rotation(new_key, create_backup, current_app)

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/key-rotation/status")
@admin_required
def get_rotation_status():
    """Get current rotation status"""
    try:
        key_rotation_service = get_key_rotation_service()
        status = key_rotation_service.get_rotation_status()
        return jsonify(status)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/key-rotation/restart-info")
@admin_required
def get_restart_info():
    """Get application restart information"""
    try:
        key_rotation_service = get_key_rotation_service()
        restart_info = key_rotation_service.restart_application()
        return jsonify(restart_info)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_uptime():
    return datetime.timedelta(seconds=int(time.time() - start_time))
