# routes/admin.py

from flask import Blueprint, render_template, jsonify, current_app, abort
import asyncio

import platform
import os
import time
import datetime
import importlib.metadata
import psutil

bp = Blueprint('admin', __name__)

# Capture app start time for uptime display
start_time = time.time()


# Optional: simple decorator for future admin access control
def admin_required(func):
    def wrapper(*args, **kwargs):
        # Replace with real auth check if needed
        if not current_app.debug:  # Allow unrestricted access only in debug mode
            abort(403)
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


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


@bp.route('/health')
def admin_health_check():
    """Basic system health check (suitable for docker / kubernetes liveness probes)"""
    from database import db
    try:
        db.session.execute('SELECT 1')  # Quick DB ping
        return jsonify(status='healthy', uptime=str(get_uptime())), 200
    except Exception as e:
        return jsonify(status='unhealthy', error=str(e)), 500


@bp.route('/version')
def admin_version():
    version = get_app_version()
    return jsonify(app_version=version, uptime=str(get_uptime()))


@bp.route('/about')
def admin_about():
    return render_template('admin/about.html')


@bp.route('/plugin-health', methods=['GET'])
def plugin_health():
    plugin_manager = getattr(current_app, "plugin_manager", None)
    stream_manager = getattr(current_app, "stream_manager", None)
    if not plugin_manager:
        return jsonify({"error": "Plugin manager not available"}), 500
    if not stream_manager:
        return jsonify({"error": "Stream manager not available"}), 500

    # Use the background event loop from stream_manager
    future = asyncio.run_coroutine_threadsafe(
        plugin_manager.check_all_plugins_health(),
        stream_manager.loop
    )
    health_status = future.result()
    return jsonify(health_status)


def get_uptime():
    return datetime.timedelta(seconds=int(time.time() - start_time))


def get_app_version():
    try:
        return importlib.metadata.version("takbridge")
    except importlib.metadata.PackageNotFoundError:
        return os.getenv("TAKBRIDGE_VERSION", "0.1.0")