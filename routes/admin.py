"""
File: routes/admin.py

Description:
    Admin dashboard blueprint for the TAKBridge application. Provides basic UI views and JSON endpoints
    to monitor system status, such as uptime, application version, number of configured streams and TAK servers,
    and how many streams are actively running. Includes optional admin access control for future use
    and utilities to calculate system uptime and retrieve the application version from metadata or environment.

Key features:
    - `/admin/`: Renders a dashboard view with system and application metrics
    - `/admin/version`: Returns app version and uptime as a JSON response
    - `/admin/about`: Static "About" page for admin interface
    - `get_uptime()`: Calculates server uptime since app startup
    - `get_app_version()`: Retrieves application version from installed package metadata or fallback env var

Author: {{AUTHOR}}
Created: 2025-07-05
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import os
import time
import datetime
import importlib.metadata

# Third-party imports
from flask import Blueprint, render_template, jsonify, current_app, abort


bp = Blueprint('admin', __name__)

# Capture app start time for uptime display
start_time = time.time()


@bp.route('/')
def admin_dashboard():
    import datetime, time, platform
    from models.stream import Stream
    from models.tak_server import TakServer
    from database import db
    from flask import current_app

    # Make sure start_time is defined somewhere globally
    uptime = datetime.timedelta(seconds=int(time.time() - start_time))
    streams_count = db.session.query(Stream).count()
    servers_count = db.session.query(TakServer).count()

    # Use the correct stream_manager instance
    stream_manager = current_app.stream_manager
    running_streams = sum(
        1 for status in stream_manager.get_all_stream_status().values() if status.get("running")
    )

    return render_template(
        'admin/dashboard.html',
        uptime=uptime,
        streams_count=streams_count,
        servers_count=servers_count,
        running_streams=running_streams,
        python_version=platform.python_version(),
        system=platform.system(),
        release=platform.release(),
        version=get_app_version()
    )


@bp.route('/version')
def admin_version():
    version = get_app_version()
    return jsonify(app_version=version, uptime=str(get_uptime()))


@bp.route('/about')
def admin_about():
    return render_template('admin/about.html')


def get_uptime():
    return datetime.timedelta(seconds=int(time.time() - start_time))


def get_app_version():
    try:
        return importlib.metadata.version("takbridge")
    except importlib.metadata.PackageNotFoundError:
        return os.getenv("TAKBRIDGE_VERSION", "0.1.0")