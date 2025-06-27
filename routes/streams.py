# =============================================================================
# routes/streams.py - Refactored Stream Management Routes
# Business logic moved to service layer for better separation of concerns
# =============================================================================

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from models.tak_server import TakServer
from services.stream_display_service import StreamDisplayService
from services.stream_config_service import StreamConfigService
from services.stream_operations_service import StreamOperationsService
from services.connection_test_service import ConnectionTestService
from services.stream_status_service import StreamStatusService
from services.cot_type_service import cot_type_service

from database import db
import logging

bp = Blueprint('streams', __name__)
logger = logging.getLogger(__name__)


def get_display_service():
    """Get the display service with current app context"""
    return StreamDisplayService(current_app.plugin_manager)


def get_config_service():
    """Get the config service with current app context"""
    return StreamConfigService(current_app.plugin_manager)


def get_stream_services():
    app_context_factory = getattr(current_app, "app_context_factory", None)
    if app_context_factory is None:
        # Fallback to the default Flask app context method
        app_context_factory = current_app.app_context
    stream_manager = getattr(current_app, "stream_manager", None)
    if stream_manager is None:
        raise ValueError("Stream manager not found in current_app")
    return {
        'operations_service': StreamOperationsService(stream_manager, db),
        'test_service': ConnectionTestService(current_app.plugin_manager, stream_manager),
        'status_service': StreamStatusService(stream_manager),
    }


@bp.route('/')
def list_streams():
    """Display list of all streams"""
    try:
        streams = get_display_service().get_streams_for_listing()
        plugin_stats, plugin_metadata = get_display_service().calculate_plugin_statistics(streams)

        return render_template('streams.html',
                               streams=streams,
                               plugin_stats=plugin_stats,
                               plugin_metadata=plugin_metadata)

    except Exception as e:
        logger.error(f"Error loading streams: {e}")
        flash('Error loading streams', 'error')
        return render_template('streams.html', streams=[])


@bp.route('/create', methods=['GET', 'POST'])
def create_stream():
    """Create a new stream"""
    if request.method == 'GET':
        return _render_create_form()

    # Handle POST request
    try:
        # Get the correct operations_service at runtime
        services = get_stream_services()
        operations_service = services['operations_service']

        data = request.get_json() if request.is_json else request.form
        result = operations_service.create_stream(data)

        if request.is_json:
            return jsonify(result)
        else:
            flash(result['message'], 'success' if result['success'] else 'error')
            if result['success']:
                return redirect(url_for('streams.view_stream', stream_id=result['stream_id']))
            else:
                return redirect(url_for('streams.create_stream'))

    except Exception as e:
        logger.error(f"Error creating stream: {e}")
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        else:
            flash(f'Error creating stream: {str(e)}', 'error')
            return redirect(url_for('streams.create_stream'))


def _render_create_form():
    """Render the create stream form"""
    tak_servers = TakServer.query.all()
    cot_types = cot_type_service.get_template_data()
    plugin_metadata = get_config_service().get_all_plugin_metadata()

    return render_template('create_stream.html',
                           tak_servers=tak_servers,
                           plugin_metadata=plugin_metadata,
                           cot_types=cot_types['cot_types'],
                           default_cot_type=cot_types['default_cot_type'])


@bp.route('/test-connection', methods=['POST'])
def test_connection():
    """Test connection to a GPS provider without saving"""

    # Get the correct test_service at runtime
    services = get_stream_services()
    test_service = services['test_service']

    try:
        data = request.get_json()
        plugin_type = data.get('plugin_type')

        if not plugin_type:
            return jsonify({'success': False, 'error': 'Plugin type required'}), 400

        plugin_config = get_config_service().extract_plugin_config_from_request(data)
        result = test_service.test_plugin_connection_sync(plugin_type, plugin_config)

        return jsonify(result), 200 if result['success'] else 400

    except Exception as e:
        logger.error(f"Error testing connection: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>')
def view_stream(stream_id):
    """View stream details"""
    try:
        stream = get_display_service().get_stream_for_detail_view(stream_id)
        return render_template('stream_detail.html', stream=stream)

    except Exception as e:
        logger.error(f"Error viewing stream {stream_id}: {e}")
        flash('Error loading stream details', 'error')
        return redirect(url_for('streams.list_streams'))


@bp.route('/<int:stream_id>/start', methods=['POST'])
def start_stream(stream_id):
    """Start a stream - enables it if disabled, then starts it"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services['operations_service']

    try:
        result = operations_service.start_stream_with_enable(stream_id)
        return jsonify(result), 200 if result['success'] else 400

    except Exception as e:
        logger.error(f"Error starting stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/stop', methods=['POST'])
def stop_stream(stream_id):
    """Stop a stream"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services['operations_service']

    try:
        result = operations_service.stop_stream_with_disable(stream_id)
        return jsonify(result), 200 if result['success'] else 400

    except Exception as e:
        logger.error(f"Error stopping stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/restart', methods=['POST'])
def restart_stream(stream_id):
    """Restart a stream"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services['operations_service']

    try:
        result = operations_service.restart_stream(stream_id)
        return jsonify(result), 200 if result['success'] else 400

    except Exception as e:
        logger.error(f"Error restarting stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/test', methods=['POST'])
def test_stream(stream_id):
    """Test an existing stream's connection"""

    # Get the correct test_service at runtime
    services = get_stream_services()
    test_service = services['test_service']

    try:
        result = test_service.test_stream_connection_sync(stream_id)
        return jsonify(result), 200 if result['success'] else 400

    except Exception as e:
        logger.error(f"Error testing stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/delete', methods=['DELETE'])
def delete_stream(stream_id):
    """Delete a stream"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services['operations_service']

    try:
        result = operations_service.delete_stream(stream_id)
        return jsonify(result), 200 if result['success'] else 500

    except Exception as e:
        logger.error(f"Error deleting stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/edit', methods=['GET', 'POST'])
def edit_stream(stream_id):
    """Edit an existing stream"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services['operations_service']

    if request.method == 'GET':
        return _render_edit_form(stream_id)

    # Handle POST request
    try:
        data = request.get_json() if request.is_json else request.form
        result = operations_service.update_stream_safely(stream_id, data)

        if request.is_json:
            return jsonify(result), 200 if result['success'] else 400
        else:
            flash(result['message'], 'success' if result['success'] else 'error')
            if result['success']:
                return redirect(url_for('streams.view_stream', stream_id=stream_id))
            else:
                return redirect(url_for('streams.edit_stream', stream_id=stream_id))

    except Exception as e:
        logger.error(f"Error updating stream {stream_id}: {e}")
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        else:
            flash(f'Error updating stream: {str(e)}', 'error')
            return redirect(url_for('streams.edit_stream', stream_id=stream_id))


def _render_edit_form(stream_id):
    """Render the edit stream form"""
    stream = get_display_service().get_stream_for_edit_form(stream_id)
    tak_servers = TakServer.query.all()
    plugin_metadata = get_config_service().get_all_plugin_metadata()
    cot_types = cot_type_service.get_template_data()

    return render_template('edit_stream.html',
                           stream=stream,
                           tak_servers=tak_servers,
                           plugin_metadata=plugin_metadata,
                           cot_types=cot_types['cot_types'],
                           default_cot_type=cot_types['default_cot_type'])


# =============================================================================
# API Routes
# =============================================================================

@bp.route('/api/stats')
def api_stats():
    """Get statistics for all streams"""

    # Get the correct status_service at runtime
    services = get_stream_services()
    status_service = services['status_service']

    try:
        stats = status_service.get_stream_statistics()
        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': 'Failed to get statistics'}), 500


@bp.route('/api/status')
def api_status():
    """Get detailed status of all streams"""

    # Get the correct status_service at runtime
    services = get_stream_services()
    status_service = services['status_service']

    try:
        status_data = status_service.get_all_streams_status()
        return jsonify({'streams': status_data})

    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'error': 'Failed to get status'}), 500


@bp.route('/api/plugins/<plugin_name>/config')
def get_plugin_config(plugin_name):
    """Get plugin configuration metadata"""
    try:
        metadata = get_config_service().get_plugin_metadata(plugin_name)
        if metadata:
            return jsonify(metadata)
        return jsonify({"error": "Plugin not found"}), 404

    except Exception as e:
        logger.error(f"Error getting plugin config for {plugin_name}: {e}")
        return jsonify({"error": "Failed to get plugin configuration"}), 500


@bp.route('/<int:stream_id>/export-config')
def export_stream_config(stream_id):
    """Export stream configuration (sensitive fields masked)"""
    try:
        export_data = get_config_service().export_stream_config(stream_id, include_sensitive=False)
        return jsonify(export_data)

    except Exception as e:
        logger.error(f"Error exporting stream config {stream_id}: {e}")
        return jsonify({'error': 'Failed to export configuration'}), 500


@bp.route('/security-status')
def security_status():
    """Get security status of all streams"""
    try:
        status = get_config_service().get_security_status()
        return jsonify(status)

    except Exception as e:
        logger.error(f"Error getting security status: {e}")
        return jsonify({'error': 'Failed to get security status'}), 500


# =============================================================================
# Bulk Operations
# =============================================================================

@bp.route('/health-check', methods=['POST'])
def health_check():
    """Trigger a health check on all streams"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services['operations_service']

    try:
        result = operations_service.run_health_check()
        return jsonify(result), 200 if result['success'] else 500

    except Exception as e:
        logger.error(f"Error during health check: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/start-all', methods=['POST'])
def start_all_streams():
    """Start all active streams"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services['operations_service']

    try:
        result = operations_service.bulk_start_streams()
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error starting all streams: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/stop-all', methods=['POST'])
def stop_all_streams():
    """Stop all running streams"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services['operations_service']

    try:
        result = operations_service.bulk_stop_streams()
        return jsonify(result)

    except Exception as e:
        logger.error(f"Error stopping all streams: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
