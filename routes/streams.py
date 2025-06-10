# =============================================================================
# routes/streams.py - Stream Management Routes with Async Support
# Updated to use the proper StreamManager from services/stream_manager.py
# FIXED: datetime object subscriptable error
# FIXED: SQLAlchemy session issues with lazy loading
# =============================================================================

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from models.stream import Stream
from models.tak_server import TakServer
from services.stream_manager import stream_manager
from plugins.plugin_manager import plugin_manager
from app import db
import asyncio
import json
import aiohttp
import logging
from concurrent.futures import ThreadPoolExecutor
import functools
from datetime import datetime
from sqlalchemy.orm import joinedload

bp = Blueprint('streams', __name__)
logger = logging.getLogger(__name__)

# Thread pool for handling async operations
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="StreamRoute")


def prepare_stream_for_display(stream):
    """Prepare stream data for display, masking sensitive fields"""
    # Get plugin metadata to identify sensitive fields
    plugin_class = plugin_manager.plugins.get(stream.plugin_type)
    if not plugin_class:
        return stream

    try:
        temp_instance = plugin_class({})
        metadata = serialize_plugin_metadata(temp_instance.plugin_metadata)

        # Get sensitive field names
        sensitive_fields = []
        for field_data in metadata.get("config_fields", []):
            if isinstance(field_data, dict) and field_data.get("sensitive"):
                sensitive_fields.append(field_data["name"])

        # Use the new to_dict method that masks sensitive data
        stream.display_config = stream.to_dict(include_sensitive=False)['plugin_config']
        stream.plugin_metadata = metadata

        return stream

    except Exception as e:
        logger.warning(f"Could not prepare stream {stream.id} for display: {e}")
        return stream


def validate_plugin_config_security(plugin_type, config):
    """Validate that sensitive fields are properly handled"""
    from plugins.plugin_manager import plugin_manager

    metadata = plugin_manager.get_plugin_metadata(plugin_type)
    if not metadata:
        return True, []

    warnings = []

    # Check for sensitive fields that might be exposed
    for field_data in metadata.get("config_fields", []):
        if isinstance(field_data, dict) and field_data.get("sensitive"):
            field_name = field_data["name"]
            if field_name in config:
                value = config[field_name]
                # Warn if sensitive data doesn't appear to be encrypted
                if value and not str(value).startswith("ENC:"):
                    warnings.append(f"Sensitive field '{field_name}' may not be encrypted")

    return len(warnings) == 0, warnings


def cleanup_executor():
    """Clean up the executor"""
    executor.shutdown(wait=True)


def serialize_plugin_metadata(metadata):
    """Convert plugin metadata to JSON-serializable format"""
    if isinstance(metadata, dict):
        result = {}
        for key, value in metadata.items():
            result[key] = serialize_plugin_metadata(value)
        return result
    elif isinstance(metadata, list):
        return [serialize_plugin_metadata(item) for item in metadata]
    elif hasattr(metadata, '__dict__'):
        # This is likely a PluginConfigField or similar object
        # Convert to dictionary
        result = {}
        for attr_name in dir(metadata):
            if not attr_name.startswith('_'):  # Skip private attributes
                try:
                    attr_value = getattr(metadata, attr_name)
                    # Skip methods
                    if not callable(attr_value):
                        result[attr_name] = serialize_plugin_metadata(attr_value)
                except:
                    pass  # Skip attributes that can't be accessed
        return result
    else:
        # Return as-is for basic types (str, int, bool, etc.)
        return metadata


def safe_get_stream_status(stream_id):
    """Safely get stream status, ensuring it returns a dict"""
    try:
        status = stream_manager.get_stream_status(stream_id)
        # Ensure status is always a dictionary
        if not isinstance(status, dict):
            logger.warning(f"Stream status for {stream_id} is not a dict: {type(status)} - {status}")
            # If it's a datetime object, it might be last_poll time - convert appropriately
            if isinstance(status, datetime):
                return {
                    'running': False,
                    'last_poll': status.isoformat(),
                    'error': None
                }
            else:
                return {'running': False, 'error': 'Invalid status format'}
        return status
    except Exception as e:
        logger.error(f"Error getting status for stream {stream_id}: {e}")
        return {'running': False, 'error': str(e)}


@bp.route('/')
def list_streams():
    """Display list of all streams"""
    try:
        # FIXED: Use joinedload to eagerly load the tak_server relationship
        streams = Stream.query.options(joinedload(Stream.tak_server)).all()

        # Add plugin metadata and running status for display
        for stream in streams:
            try:
                plugin_class = plugin_manager.plugins.get(stream.plugin_type)
                if plugin_class:
                    temp_instance = plugin_class({})
                    stream.plugin_metadata = serialize_plugin_metadata(temp_instance.plugin_metadata)
                else:
                    stream.plugin_metadata = None
            except Exception as e:
                logger.warning(f"Could not load metadata for plugin {stream.plugin_type}: {e}")
                stream.plugin_metadata = None

            # Get running status from stream manager - FIXED: Use safe wrapper
            stream.running_status = safe_get_stream_status(stream.id)

            # FIXED: Format last_poll datetime for template display
            if stream.last_poll and isinstance(stream.last_poll, datetime):
                stream.last_poll_date = stream.last_poll.strftime('%Y-%m-%d')
                stream.last_poll_time = stream.last_poll.strftime('%H:%M:%S')
                stream.last_poll_iso = stream.last_poll.isoformat()
            else:
                stream.last_poll_date = None
                stream.last_poll_time = None
                stream.last_poll_iso = None

        # Calculate plugin statistics
        plugin_stats = {}
        plugin_metadata = {}

        for stream in streams:
            plugin_type = stream.plugin_type
            plugin_stats[plugin_type] = plugin_stats.get(plugin_type, 0) + 1

            if stream.plugin_metadata:
                plugin_metadata[plugin_type] = stream.plugin_metadata

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
        tak_servers = TakServer.query.all()
        available_plugins = plugin_manager.list_plugins()

        # Convert plugin list to metadata format expected by template
        plugin_metadata = {}
        for plugin_name in available_plugins:
            plugin_class = plugin_manager.plugins.get(plugin_name)
            if plugin_class:
                # Create temporary instance to get metadata
                temp_instance = plugin_class({})
                metadata = temp_instance.plugin_metadata

                # Convert to JSON-serializable format
                plugin_metadata[plugin_name] = serialize_plugin_metadata(metadata)

        return render_template('create_stream.html',
                               tak_servers=tak_servers,
                               plugin_metadata=plugin_metadata)

    # Handle POST request
    data = request.get_json() if request.is_json else request.form

    try:
        stream = Stream(
            name=data['name'],
            plugin_type=data['plugin_type'],
            poll_interval=int(data.get('poll_interval', 120)),
            cot_type=data.get('cot_type', 'a-f-G-U-C'),
            cot_stale_time=int(data.get('cot_stale_time', 300)),
            tak_server_id=int(data['tak_server_id'])
        )

        # Set plugin configuration
        plugin_config = {}
        for key, value in data.items():
            if key.startswith('plugin_'):
                plugin_config[key[7:]] = value  # Remove 'plugin_' prefix

        stream.set_plugin_config(plugin_config)

        db.session.add(stream)
        db.session.commit()

        # Auto-start if requested
        if data.get('auto_start'):
            try:
                success = stream_manager.start_stream_sync(stream.id)
                if success:
                    message = 'Stream created and started successfully'
                else:
                    message = 'Stream created but failed to start automatically'
            except Exception as e:
                logger.error(f"Error auto-starting stream: {e}")
                message = 'Stream created but failed to start automatically'
        else:
            message = 'Stream created successfully'

        if request.is_json:
            return jsonify({'success': True, 'stream_id': stream.id, 'message': message})
        else:
            flash(message, 'success')
            return redirect(url_for('streams.view_stream', stream_id=stream.id))

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating stream: {e}")
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        else:
            flash(f'Error creating stream: {str(e)}', 'error')
            return redirect(url_for('streams.create_stream'))


@bp.route('/test-connection', methods=['POST'])
def test_connection():
    """Test connection to a GPS provider without saving"""
    try:
        data = request.get_json()
        plugin_type = data.get('plugin_type')

        if not plugin_type:
            return jsonify({'success': False, 'error': 'Plugin type required'}), 400

        # Extract plugin configuration
        plugin_config = {}
        for key, value in data.items():
            if key.startswith('plugin_'):
                plugin_config[key[7:]] = value  # Remove 'plugin_' prefix

        # Get plugin instance
        plugin_instance = plugin_manager.get_plugin(plugin_type, plugin_config)
        if not plugin_instance:
            return jsonify({'success': False, 'error': 'Failed to create plugin instance'}), 400

        # Test connection asynchronously using the stream manager's session
        async def test_async():
            """Test function that uses the shared session manager"""
            try:
                # Use the stream manager's session manager
                session = stream_manager._session_manager.session
                if not session:
                    # If session not available, create a temporary one
                    timeout = aiohttp.ClientTimeout(total=30)
                    async with aiohttp.ClientSession(timeout=timeout) as temp_session:
                        # First test basic connection
                        connection_ok = await plugin_instance.test_connection()
                        if not connection_ok:
                            return False, 0

                        # Then try to fetch sample data
                        locations = await plugin_instance.fetch_locations(temp_session)
                        device_count = len(locations) if locations else 0
                        return True, device_count
                else:
                    # Use shared session
                    # First test basic connection
                    connection_ok = await plugin_instance.test_connection()
                    if not connection_ok:
                        return False, 0

                    # Then try to fetch sample data
                    locations = await plugin_instance.fetch_locations(session)
                    device_count = len(locations) if locations else 0
                    return True, device_count

            except Exception as e:
                logger.error(f"Error in test_async: {e}")
                return False, 0

        # Use the stream manager's background loop to run the test
        try:
            future = asyncio.run_coroutine_threadsafe(test_async(), stream_manager._loop)
            success, device_count = future.result(timeout=30)
        except Exception as e:
            logger.error(f"Error running test in background loop: {e}")
            return jsonify({'success': False, 'error': f'Test execution failed: {str(e)}'}), 500

        if success:
            return jsonify({
                'success': True,
                'message': 'Connection successful',
                'device_count': device_count
            })
        else:
            return jsonify({'success': False, 'error': 'Connection test failed'}), 400

    except asyncio.TimeoutError:
        return jsonify({'success': False, 'error': 'Connection test timed out'}), 408
    except Exception as e:
        logger.error(f"Error testing connection: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>')
def view_stream(stream_id):
    """View stream details"""
    try:
        # FIXED: Use joinedload to eagerly load the tak_server relationship
        stream = Stream.query.options(joinedload(Stream.tak_server)).filter_by(id=stream_id).first_or_404()

        # Add plugin metadata
        try:
            plugin_class = plugin_manager.plugins.get(stream.plugin_type)
            if plugin_class:
                temp_instance = plugin_class({})
                stream.plugin_metadata = serialize_plugin_metadata(temp_instance.plugin_metadata)
            else:
                stream.plugin_metadata = None
        except Exception as e:
            logger.warning(f"Could not load metadata for plugin {stream.plugin_type}: {e}")
            stream.plugin_metadata = None

        # Get current running status from stream manager - FIXED: Use safe wrapper
        stream.running_status = safe_get_stream_status(stream_id)

        return render_template('stream_detail.html', stream=stream)

    except Exception as e:
        logger.error(f"Error viewing stream {stream_id}: {e}")
        flash('Error loading stream details', 'error')
        return redirect(url_for('streams.list_streams'))


@bp.route('/<int:stream_id>/start', methods=['POST'])
def start_stream(stream_id):
    """Start a stream - enables it if disabled, then starts it"""
    try:
        # First, ensure the stream is enabled in the database
        stream = Stream.query.get_or_404(stream_id)

        # Enable the stream if it's not already enabled
        if not stream.is_active:
            stream.is_active = True
            db.session.commit()
            logger.info(f"Enabled stream {stream_id} ({stream.name})")

        # Now start the stream through StreamManager using the sync wrapper
        success = stream_manager.start_stream_sync(stream_id)

        if success:
            logger.info(f"Stream {stream_id} started successfully")
            return jsonify({'success': True, 'message': 'Stream started successfully'})
        else:
            logger.error(f"Failed to start stream {stream_id}")
            return jsonify({'success': False, 'error': 'Failed to start stream'}), 400

    except Exception as e:
        logger.error(f"Error starting stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/stop', methods=['POST'])
def stop_stream(stream_id):
    """Stop a stream"""
    try:
        # Update database status
        stream = Stream.query.get_or_404(stream_id)
        stream.is_active = False
        db.session.commit()
        logger.info(f"Disabled stream {stream_id} ({stream.name})")

        # Stop the stream through StreamManager using the sync wrapper
        success = stream_manager.stop_stream_sync(stream_id)

        if success:
            logger.info(f"Stream {stream_id} stopped successfully")
            return jsonify({'success': True, 'message': 'Stream stopped successfully'})
        else:
            logger.error(f"Failed to stop stream {stream_id}")
            return jsonify({'success': False, 'error': 'Failed to stop stream'}), 400

    except Exception as e:
        logger.error(f"Error stopping stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/restart', methods=['POST'])
def restart_stream(stream_id):
    """Restart a stream"""
    try:
        # Use the stream manager's sync wrapper for restart
        success = stream_manager.restart_stream_sync(stream_id)

        if success:
            logger.info(f"Stream {stream_id} restarted successfully")
            return jsonify({'success': True, 'message': 'Stream restarted successfully'})
        else:
            logger.error(f"Failed to restart stream {stream_id}")
            return jsonify({'success': False, 'error': 'Failed to restart stream'}), 400

    except Exception as e:
        logger.error(f"Error restarting stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/test', methods=['POST'])
def test_stream(stream_id):
    """Test an existing stream's connection"""
    try:
        stream = Stream.query.get_or_404(stream_id)

        # Get plugin configuration from the stream
        plugin_config = stream.get_plugin_config()
        plugin_type = stream.plugin_type

        # Get plugin instance
        plugin_instance = plugin_manager.get_plugin(plugin_type, plugin_config)
        if not plugin_instance:
            return jsonify({'success': False, 'error': 'Failed to create plugin instance'}), 400

        # Test connection asynchronously using the stream manager's session
        async def test_async():
            """Test function that uses the shared session manager"""
            try:
                # Use the stream manager's session manager
                session = stream_manager._session_manager.session
                if not session:
                    # If session not available, create a temporary one
                    timeout = aiohttp.ClientTimeout(total=30)
                    async with aiohttp.ClientSession(timeout=timeout) as temp_session:
                        # First test basic connection
                        connection_ok = await plugin_instance.test_connection()
                        if not connection_ok:
                            return False, 0

                        # Then try to fetch sample data
                        locations = await plugin_instance.fetch_locations(temp_session)
                        device_count = len(locations) if locations else 0
                        return True, device_count
                else:
                    # Use shared session
                    # First test basic connection
                    connection_ok = await plugin_instance.test_connection()
                    if not connection_ok:
                        return False, 0

                    # Then try to fetch sample data
                    locations = await plugin_instance.fetch_locations(session)
                    device_count = len(locations) if locations else 0
                    return True, device_count

            except Exception as e:
                logger.error(f"Error in test_async: {e}")
                return False, 0

        # Use the stream manager's background loop to run the test
        try:
            future = asyncio.run_coroutine_threadsafe(test_async(), stream_manager._loop)
            success, device_count = future.result(timeout=30)
        except Exception as e:
            logger.error(f"Error running test in background loop: {e}")
            return jsonify({'success': False, 'error': f'Test execution failed: {str(e)}'}), 500

        if success:
            return jsonify({
                'success': True,
                'message': 'Connection successful',
                'device_count': device_count
            })
        else:
            return jsonify({'success': False, 'error': 'Connection test failed'}), 400

    except asyncio.TimeoutError:
        return jsonify({'success': False, 'error': 'Connection test timed out'}), 408
    except Exception as e:
        logger.error(f"Error testing stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/delete', methods=['DELETE'])
def delete_stream(stream_id):
    """Delete a stream"""
    try:
        stream = Stream.query.get_or_404(stream_id)

        # Stop the stream if it's running
        if stream.is_active:
            try:
                stream_manager.stop_stream_sync(stream_id)
            except Exception as e:
                logger.warning(f"Error stopping stream before deletion: {e}")

        # Delete from database
        db.session.delete(stream)
        db.session.commit()

        logger.info(f"Stream {stream_id} deleted successfully")
        return jsonify({'success': True, 'message': 'Stream deleted successfully'})

    except Exception as e:
        logger.error(f"Error deleting stream {stream_id}: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/edit', methods=['GET', 'POST'])
def edit_stream(stream_id):
    """Edit an existing stream"""
    # FIXED: Use joinedload for both GET and POST methods
    stream = Stream.query.options(joinedload(Stream.tak_server)).filter_by(id=stream_id).first_or_404()

    if request.method == 'GET':
        tak_servers = TakServer.query.all()
        available_plugins = plugin_manager.list_plugins()

        # Convert plugin list to metadata format expected by template
        plugin_metadata = {}
        for plugin_name in available_plugins:
            plugin_class = plugin_manager.plugins.get(plugin_name)
            if plugin_class:
                # Create temporary instance to get metadata
                temp_instance = plugin_class({})
                metadata = temp_instance.plugin_metadata

                # Convert to JSON-serializable format
                plugin_metadata[plugin_name] = serialize_plugin_metadata(metadata)

        return render_template('edit_stream.html',
                               stream=stream,
                               tak_servers=tak_servers,
                               plugin_metadata=plugin_metadata)

    # Handle POST request
    data = request.get_json() if request.is_json else request.form

    try:
        # Check if the stream is currently running - FIXED: Use safe wrapper
        stream_status = safe_get_stream_status(stream_id)
        was_running = stream_status.get('running', False)

        # Stop the stream if it's running (we'll restart it after update)
        if was_running:
            stream_manager.stop_stream_sync(stream_id)

        # Update stream properties
        stream.name = data['name']
        stream.plugin_type = data['plugin_type']
        stream.poll_interval = int(data.get('poll_interval', 120))
        stream.cot_type = data.get('cot_type', 'a-f-G-U-C')
        stream.cot_stale_time = int(data.get('cot_stale_time', 300))
        stream.tak_server_id = int(data['tak_server_id'])

        # Update plugin configuration
        plugin_config = {}
        for key, value in data.items():
            if key.startswith('plugin_'):
                plugin_config[key[7:]] = value  # Remove 'plugin_' prefix

        stream.set_plugin_config(plugin_config)

        db.session.commit()

        # Restart the stream if it was running before
        if was_running:
            stream_manager.start_stream_sync(stream_id)

        if request.is_json:
            return jsonify({'success': True, 'stream_id': stream.id})
        else:
            flash('Stream updated successfully', 'success')
            return redirect(url_for('streams.view_stream', stream_id=stream.id))

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating stream {stream_id}: {e}")
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        else:
            flash(f'Error updating stream: {str(e)}', 'error')
            return redirect(url_for('streams.edit_stream', stream_id=stream_id))


@bp.route('/api/stats')
def api_stats():
    """Get statistics for all streams"""
    try:
        # FIXED: Use joinedload to eagerly load the tak_server relationship
        streams = Stream.query.options(joinedload(Stream.tak_server)).all()

        # Get running status with error handling
        try:
            running_status = stream_manager.get_all_stream_status()
        except Exception as e:
            logger.error(f"Error getting stream manager status: {e}")
            running_status = {}

        # FIXED: Safely handle the running_status which might contain non-dict values
        safe_running_status = {}
        if isinstance(running_status, dict):
            for stream_id, status in running_status.items():
                if isinstance(status, dict):
                    safe_running_status[stream_id] = status
                elif isinstance(status, datetime):
                    # Handle datetime objects (might be last_poll time)
                    safe_running_status[stream_id] = {
                        'running': False,
                        'last_poll': status.isoformat(),
                        'error': None
                    }
                else:
                    logger.warning(f"Invalid status format for stream {stream_id}: {type(status)}")
                    safe_running_status[stream_id] = {'running': False}
        else:
            logger.warning(f"Invalid running_status format: {type(running_status)}")

        stats = {
            'total_streams': len(streams),
            'active_streams': len([s for s in streams if s.is_active]),
            'running_streams': len([s for s in safe_running_status.values() if s.get('running', False)]),
            'error_streams': len([s for s in streams if s.last_error]),
            'total_messages': sum(s.total_messages_sent or 0 for s in streams),
            'by_plugin': {}
        }

        # Group by plugin type
        for stream in streams:
            plugin_type = stream.plugin_type
            if plugin_type not in stats['by_plugin']:
                stats['by_plugin'][plugin_type] = {
                    'count': 0,
                    'active': 0,
                    'running': 0,
                    'messages': 0
                }
            stats['by_plugin'][plugin_type]['count'] += 1
            if stream.is_active:
                stats['by_plugin'][plugin_type]['active'] += 1
            if safe_running_status.get(stream.id, {}).get('running', False):
                stats['by_plugin'][plugin_type]['running'] += 1
            stats['by_plugin'][plugin_type]['messages'] += stream.total_messages_sent or 0

        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': 'Failed to get statistics'}), 500


@bp.route('/api/status')
def api_status():
    """Get detailed status of all streams"""
    try:
        # FIXED: Use joinedload to eagerly load the tak_server relationship
        streams = Stream.query.options(joinedload(Stream.tak_server)).all()

        # Get all stream status from stream manager
        try:
            running_status = stream_manager.get_all_stream_status()
        except Exception as e:
            logger.error(f"Error getting stream manager status: {e}")
            running_status = {}

        # FIXED: Safely handle the running_status which might contain non-dict values
        safe_running_status = {}
        if isinstance(running_status, dict):
            for stream_id, status in running_status.items():
                if isinstance(status, dict):
                    safe_running_status[stream_id] = status
                elif isinstance(status, datetime):
                    # Handle datetime objects (might be last_poll time)
                    safe_running_status[stream_id] = {
                        'running': False,
                        'last_poll': status.isoformat(),
                        'error': None
                    }
                else:
                    logger.warning(f"Invalid status format for stream {stream_id}: {type(status)}")
                    safe_running_status[stream_id] = {'running': False}
        else:
            logger.warning(f"Invalid running_status format: {type(running_status)}")

        status_data = []
        for stream in streams:
            stream_status = safe_running_status.get(stream.id, {'running': False})

            # Handle last_poll datetime safely
            last_poll_iso = None
            if stream.last_poll:
                try:
                    if isinstance(stream.last_poll, datetime):
                        last_poll_iso = stream.last_poll.isoformat()
                    else:
                        last_poll_iso = str(stream.last_poll)
                except Exception as e:
                    logger.warning(f"Error formatting last_poll for stream {stream.id}: {e}")
                    last_poll_iso = None

            status_data.append({
                'id': stream.id,
                'name': stream.name,
                'plugin_type': stream.plugin_type,
                'is_active': stream.is_active,
                'running': stream_status.get('running', False),
                'last_poll': last_poll_iso,
                'last_error': stream.last_error,
                'total_messages_sent': stream.total_messages_sent or 0,
                'tak_server': stream.tak_server.name if stream.tak_server else None
            })

        return jsonify({'streams': status_data})

    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'error': 'Failed to get status'}), 500


@bp.route('/api/plugins/<plugin_name>/config')
def get_plugin_config(plugin_name):
    """Get plugin configuration metadata"""
    try:
        plugin_class = plugin_manager.plugins.get(plugin_name)
        if plugin_class:
            # Create temporary instance to get metadata
            temp_instance = plugin_class({})
            return jsonify(serialize_plugin_metadata(temp_instance.plugin_metadata))
        return jsonify({"error": "Plugin not found"}), 404

    except Exception as e:
        logger.error(f"Error getting plugin config for {plugin_name}: {e}")
        return jsonify({"error": "Failed to get plugin configuration"}), 500


@bp.route('/<int:stream_id>/export-config')
def export_stream_config(stream_id):
    """Export stream configuration (sensitive fields masked)"""
    try:
        stream = Stream.query.get_or_404(stream_id)

        # Export with sensitive fields masked
        export_data = {
            'name': stream.name,
            'plugin_type': stream.plugin_type,
            'plugin_config': stream.to_dict(include_sensitive=False)['plugin_config'],
            'poll_interval': stream.poll_interval,
            'cot_type': stream.cot_type,
            'cot_stale_time': stream.cot_stale_time,
            'exported_at': datetime.utcnow().isoformat(),
            'note': 'Sensitive fields have been masked for security'
        }

        return jsonify(export_data)

    except Exception as e:
        logger.error(f"Error exporting stream config {stream_id}: {e}")
        return jsonify({'error': 'Failed to export configuration'}), 500


@bp.route('/security-status')
def security_status():
    """Get security status of all streams"""
    try:
        streams = Stream.query.all()
        status = {
            'total_streams': len(streams),
            'encrypted_streams': 0,
            'warnings': []
        }

        for stream in streams:
            config = stream.get_raw_plugin_config()
            is_secure, warnings = validate_plugin_config_security(stream.plugin_type, config)

            if is_secure:
                status['encrypted_streams'] += 1
            else:
                status['warnings'].extend([
                    f"Stream '{stream.name}': {warning}" for warning in warnings
                ])

        status['encryption_percentage'] = (
            (status['encrypted_streams'] / status['total_streams'] * 100)
            if status['total_streams'] > 0 else 100
        )

        return jsonify(status)

    except Exception as e:
        logger.error(f"Error getting security status: {e}")
        return jsonify({'error': 'Failed to get security status'}), 500


@bp.route('/health-check', methods=['POST'])
def health_check():
    """Trigger a health check on all streams"""
    try:
        # Run health check in the background event loop
        future = asyncio.run_coroutine_threadsafe(
            stream_manager.health_check(),
            stream_manager._loop
        )
        future.result(timeout=30)

        return jsonify({'success': True, 'message': 'Health check completed'})

    except Exception as e:
        logger.error(f"Error during health check: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/start-all', methods=['POST'])
def start_all_streams():
    """Start all active streams"""
    try:
        active_streams = Stream.query.filter_by(is_active=True).all()
        started_count = 0
        failed_count = 0

        for stream in active_streams:
            try:
                success = stream_manager.start_stream_sync(stream.id)
                if success:
                    started_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.error(f"Error starting stream {stream.id}: {e}")
                failed_count += 1

        return jsonify({
            'success': True,
            'message': f'Started {started_count} streams, {failed_count} failed',
            'started': started_count,
            'failed': failed_count
        })

    except Exception as e:
        logger.error(f"Error starting all streams: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/stop-all', methods=['POST'])
def stop_all_streams():
    """Stop all running streams"""
    try:
        # Get running status with error handling
        try:
            running_status = stream_manager.get_all_stream_status()
        except Exception as e:
            logger.error(f"Error getting stream manager status: {e}")
            running_status = {}

        # Find running streams with improved error handling
        running_streams = []
        if isinstance(running_status, dict):
            for stream_id, status in running_status.items():
                if isinstance(status, dict) and status.get('running', False):
                    running_streams.append(stream_id)
                # Skip non-dict status values as they're likely not running

        stopped_count = 0
        failed_count = 0

        for stream_id in running_streams:
            try:
                success = stream_manager.stop_stream_sync(stream_id)
                if success:
                    stopped_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.error(f"Error stopping stream {stream_id}: {e}")
                failed_count += 1

        return jsonify({
            'success': True,
            'message': f'Stopped {stopped_count} streams, {failed_count} failed',
            'stopped': stopped_count,
            'failed': failed_count
        })

    except Exception as e:
        logger.error(f"Error stopping all streams: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500