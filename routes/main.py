"""
File: routes/main.py

Description:
    Main dashboard blueprint providing the primary user interface for the TrakBridge application.
    This module serves as the entry point for users accessing the web interface, rendering the
    main dashboard with real-time system overview including stream statistics, TAK server status,
    and operational metrics. The route aggregates data from multiple sources to provide a
    comprehensive system overview in a single view.

Key features:
    - Main dashboard route serving as the application's homepage
    - Real-time system statistics aggregation (streams, TAK servers, workers)
    - Stream status monitoring with active/inactive counts
    - TAK server inventory and status display
    - Worker thread monitoring for operational visibility
    - Template rendering with dynamic data injection
    - Circular import prevention with strategic model imports
    - Integration with stream manager for live operational data

Author: Emfour Solutions
Created: 18-Jul-2025
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports

# Third-party imports
from flask import Blueprint, render_template

# Authentication imports
from services.auth import require_auth
# Module-level logger
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

bp = Blueprint("main", __name__)


@bp.route("/")
@require_auth
def index():
    """Main dashboard page"""
    from flask import current_app

    # Import models inside the route to avoid circular imports
    from models.stream import Stream
    from models.tak_server import TakServer

    # Handle stream_manager import carefully
    stream_manager = getattr(current_app, "stream_manager", None)
    running_workers = len(stream_manager.workers)

    streams = Stream.query.all()
    tak_servers = TakServer.query.all()

    active_streams = sum(1 for s in streams if s.is_active)

    return render_template(
        "index.html",
        streams=streams,
        tak_servers=tak_servers,
        active_streams=active_streams,
        total_streams=len(streams),
    )
