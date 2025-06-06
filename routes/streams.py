# =============================================================================
# routes/streams.py - Stream Management Routes
# =============================================================================

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from models.stream import Stream
from models.tak_server import TakServer
from services.stream_manager import stream_manager
from plugins.plugin_manager import plugin_manager
from app import db
import asyncio
import json
import aiohttp

bp = Blueprint('streams', __name__)

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


@bp.route('/')
def list_streams():
    """List all streams"""
    streams = Stream.query.all()
    return render_template('streams.html', streams=streams)


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

        if request.is_json:
            return jsonify({'success': True, 'stream_id': stream.id})
        else:
            flash('Stream created successfully', 'success')
            return redirect(url_for('streams.list_streams'))

    except Exception as e:
        db.session.rollback()
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

        # Test connection asynchronously
        async def test_async():
            return await plugin_instance.test_connection()

        # Run the async test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            success = loop.run_until_complete(test_async())

            if success:
                # Try to fetch a sample of locations to count devices
                async def fetch_sample():
                    timeout = aiohttp.ClientTimeout(total=30)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        return await plugin_instance.fetch_locations(session)

                locations = loop.run_until_complete(fetch_sample())
                device_count = len(locations) if locations else 0

                return jsonify({
                    'success': True,
                    'message': 'Connection successful',
                    'device_count': device_count
                })
            else:
                return jsonify({'success': False, 'error': 'Connection test failed'}), 400

        finally:
            loop.close()

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>')
def view_stream(stream_id):
    """View stream details"""
    stream = Stream.query.get_or_404(stream_id)
    return render_template('stream_detail.html', stream=stream)


@bp.route('/<int:stream_id>/start', methods=['POST'])
def start_stream(stream_id):
    """Start a stream"""
    try:
        # Run async function in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(stream_manager.start_stream(stream_id))
        loop.close()

        if success:
            return jsonify({'success': True, 'message': 'Stream started'})
        else:
            return jsonify({'success': False, 'error': 'Failed to start stream'}), 500

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/stop', methods=['POST'])
def stop_stream(stream_id):
    """Stop a stream"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(stream_manager.stop_stream(stream_id))
        loop.close()

        if success:
            return jsonify({'success': True, 'message': 'Stream stopped'})
        else:
            return jsonify({'success': False, 'error': 'Failed to stop stream'}), 500

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/delete', methods=['DELETE'])
def delete_stream(stream_id):
    """Delete a stream"""
    try:
        # Stop stream first if running
        if stream_id in stream_manager.workers:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(stream_manager.stop_stream(stream_id))
            loop.close()

        stream = Stream.query.get_or_404(stream_id)
        db.session.delete(stream)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Stream deleted'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/edit', methods=['GET', 'POST'])
def edit_stream(stream_id):
    """Edit an existing stream"""
    stream = Stream.query.get_or_404(stream_id)

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

    # Handle POST request - rest of the method stays the same
    data = request.get_json() if request.is_json else request.form

    try:
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

        if request.is_json:
            return jsonify({'success': True, 'stream_id': stream.id})
        else:
            flash('Stream updated successfully', 'success')
            return redirect(url_for('streams.view_stream', stream_id=stream.id))

    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        else:
            flash(f'Error updating stream: {str(e)}', 'error')
            return redirect(url_for('streams.edit_stream', stream_id=stream_id))


@bp.route('/api/stats')
def api_stats():
    """Get statistics for all streams"""
    streams = Stream.query.all()
    stats = {
        'total_streams': len(streams),
        'active_streams': len([s for s in streams if s.is_active]),
        'error_streams': len([s for s in streams if s.last_error]),
        'total_messages': sum(s.total_messages_sent for s in streams),
        'by_plugin': {}
    }

    # Group by plugin type
    for stream in streams:
        plugin_type = stream.plugin_type
        if plugin_type not in stats['by_plugin']:
            stats['by_plugin'][plugin_type] = {
                'count': 0,
                'active': 0,
                'messages': 0
            }
        stats['by_plugin'][plugin_type]['count'] += 1
        if stream.is_active:
            stats['by_plugin'][plugin_type]['active'] += 1
        stats['by_plugin'][plugin_type]['messages'] += stream.total_messages_sent

    return jsonify(stats)


@bp.route('/api/plugins/<plugin_name>/config')
def get_plugin_config(plugin_name):
    plugin_class = plugin_manager.plugins.get(plugin_name)
    if plugin_class:
        # Create temporary instance to get metadata
        temp_instance = plugin_class({})
        return jsonify(temp_instance.plugin_metadata)
    return jsonify({"error": "Plugin not found"}), 404


# Add this route to your streams.py file, after the existing routes

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

        # Test connection asynchronously
        async def test_async():
            return await plugin_instance.test_connection()

        # Run the async test
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            success = loop.run_until_complete(test_async())

            if success:
                # Try to fetch a sample of locations to count devices
                async def fetch_sample():
                    timeout = aiohttp.ClientTimeout(total=30)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        return await plugin_instance.fetch_locations(session)

                locations = loop.run_until_complete(fetch_sample())
                device_count = len(locations) if locations else 0

                return jsonify({
                    'success': True,
                    'message': 'Connection successful',
                    'device_count': device_count
                })
            else:
                return jsonify({'success': False, 'error': 'Connection test failed'}), 400

        finally:
            loop.close()

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500