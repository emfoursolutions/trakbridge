# =============================================================================
# routes/main.py - Main Routes
# =============================================================================

from flask import Blueprint, render_template, jsonify
import logging

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    """Main dashboard page"""
    from flask import current_app
    
    # Import models inside the route to avoid circular imports
    from models.stream import Stream
    from models.tak_server import TakServer

    # Handle stream_manager import carefully
    stream_manager = current_app.stream_manager
    running_workers = len(stream_manager.workers)

    streams = Stream.query.all()
    tak_servers = TakServer.query.all()

    active_streams = sum(1 for s in streams if s.is_active)

    return render_template('index.html',
                           streams=streams,
                           tak_servers=tak_servers,
                           active_streams=active_streams,
                           total_streams=len(streams))


@bp.route('/api/status')
def api_status():
    """API endpoint for system status"""
    # Import models inside the route to avoid circular imports
    from models.stream import Stream
    from models.tak_server import TakServer

    streams = Stream.query.all()

    # Handle stream_manager import carefully
    try:
        from services.stream_manager import stream_manager
        running_workers = len(stream_manager.workers)
    except ImportError:
        running_workers = 0

    return jsonify({
        'total_streams': len(streams),
        'active_streams': sum(1 for s in streams if s.is_active),
        'tak_servers': TakServer.query.count(),
        'running_workers': running_workers
    })


