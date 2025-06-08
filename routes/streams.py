# =============================================================================
# routes/streams.py - Stream Management Routes with Async Support
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

bp = Blueprint('streams', __name__)
logger = logging.getLogger(__name__)

# Thread pool for handling async operations
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="StreamRoute")


def cleanup_executor():
    """Clean up the executor"""
    executor.shutdown(wait=True)


def run_async_in_loop(coro):
    """Helper to run async function in the app's event loop"""
    loop = current_app.config.get('ASYNC_LOOP')
    if loop and not loop.is_closed():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=30)  # 30 second timeout
    else:
        # Fallback to creating new event loop if none available
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


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
    """Display list of all streams"""
    try:
        streams = Stream.query.all()

        # Add plugin metadata for display
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
                success = run_async_in_loop(stream_manager.start_stream(stream.id))
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

        # Test connection asynchronously
        async def test_async():
            return await plugin_instance.test_connection()

        # Test connection and fetch sample data
        async def fetch_sample():
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                return await plugin_instance.fetch_locations(session)

        success = run_async_in_loop(test_async())

        if success:
            locations = run_async_in_loop(fetch_sample())
            device_count = len(locations) if locations else 0

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
        stream = Stream.query.get_or_404(stream_id)

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

        # Now start the stream through StreamManager
        success = run_async_in_loop(stream_manager.start_stream(stream_id))

        if success:
            logger.info(f"Stream {stream_id} started successfully")
            return jsonify({'success': True, 'message': 'Stream started successfully'})
        else:
            logger.error(f"Failed to start stream {stream_id}")
            return jsonify({'success': False, 'error': 'Failed to start stream'}), 400

    except asyncio.TimeoutError:
        logger.error(f"Timeout starting stream {stream_id}")
        return jsonify({'success': False, 'error': 'Operation timed out'}), 408
    except Exception as e:
        logger.error(f"Error starting stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/stop', methods=['POST'])
def stop_stream(stream_id):
    try:
        # First, ensure the stream is enabled in the database
        stream = Stream.query.get_or_404(stream_id)

        # Enable the stream if it's not already enabled
        if not stream.is_active:
            stream.is_active = False
            db.session.commit()
            logger.info(f"Disabled stream {stream_id} ({stream.name})")

        # Run the async operation
        success = run_async_in_loop(stream_manager.stop_stream(stream_id))

        if success:
            logger.info(f"Stream {stream_id} stopped successfully")
            return jsonify({'success': True, 'message': 'Stream stopped successfully'})
        else:
            logger.error(f"Failed to stop stream {stream_id}")
            return jsonify({'success': False, 'error': 'Failed to stop stream'}), 400

    except asyncio.TimeoutError:
        logger.error(f"Timeout stopping stream {stream_id}")
        return jsonify({'success': False, 'error': 'Operation timed out'}), 408
    except Exception as e:
        logger.error(f"Error stopping stream {stream_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:stream_id>/restart', methods=['POST'])
def restart_stream(stream_id):
    """Restart a stream"""
    try:
        # Run the async operation
        success = run_async_in_loop(stream_manager.restart_stream(stream_id))

        if success:
            logger.info(f"Stream {stream_id} restarted successfully")
            return jsonify({'success': True, 'message': 'Stream restarted successfully'})
        else:
            logger.error(f"Failed to restart stream {stream_id}")
            return jsonify({'success': False, 'error': 'Failed to restart stream'}), 400

    except asyncio.TimeoutError:
        logger.error(f"Timeout restarting stream {stream_id}")
        return jsonify({'success': False, 'error': 'Operation timed out'}), 408
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

        # Test connection asynchronously
        async def test_async():
            return await plugin_instance.test_connection()

        # Try to fetch a sample of locations to count devices
        async def fetch_sample():
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                return await plugin_instance.fetch_locations(session)

        success = run_async_in_loop(test_async())

        if success:
            locations = run_async_in_loop(fetch_sample())
            device_count = len(locations) if locations else 0

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
                run_async_in_loop(stream_manager.stop_stream(stream_id))
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

    # Handle POST request
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

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': 'Failed to get statistics'}), 500


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


# Keep your existing StreamManager and StreamWorker classes at the bottom
class StreamManager:
    def __init__(self):
        self.workers = {}
        self.shutdown_event = asyncio.Event()

    def get_stream_data(self, stream_id):
        """Get stream data in a session-safe way"""
        from app import app, db
        from models.stream import Stream

        with app.app_context():
            stream = db.session.get(Stream, stream_id)
            if not stream:
                return None

            # Convert to dict to avoid session binding issues
            return {
                'id': stream.id,
                'name': stream.name,
                'plugin_type': stream.plugin_type,
                'plugin_config': stream.get_plugin_config(),
                'poll_interval': stream.poll_interval,
                'cot_type': stream.cot_type,
                'cot_stale_time': stream.cot_stale_time,
                'tak_server_id': stream.tak_server_id
            }

    def update_stream_status(self, stream_id, is_active=None, last_error=None, messages_sent=None):
        """Update stream status in a session-safe way"""
        from app import app, db
        from models.stream import Stream

        with app.app_context():
            stream = db.session.get(Stream, stream_id)
            if stream:
                if is_active is not None:
                    stream.is_active = is_active
                if last_error is not None:
                    stream.last_error = last_error
                if messages_sent is not None:
                    stream.total_messages_sent = (stream.total_messages_sent or 0) + messages_sent

                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print(f"Error updating stream status: {e}")

    async def start_stream(self, stream_id):
        """Start a stream with proper session handling"""
        try:
            # Get stream data in a session-safe way
            stream_data = self.get_stream_data(stream_id)
            if not stream_data:
                return False

            if stream_id in self.workers:
                return True  # Already running

            # Create and start worker
            worker = StreamWorker(stream_data, self)
            self.workers[stream_id] = worker

            # Start the worker task
            task = asyncio.create_task(worker.run())
            worker.task = task

            # Update status
            self.update_stream_status(stream_id, is_active=True, last_error=None)

            return True

        except Exception as e:
            print(f"Error starting stream {stream_id}: {e}")
            self.update_stream_status(stream_id, is_active=False, last_error=str(e))
            return False

    async def stop_stream(self, stream_id):
        """Stop a stream with proper session handling"""
        try:
            if stream_id not in self.workers:
                return True  # Not running

            worker = self.workers[stream_id]
            await worker.stop()

            # Remove from workers
            del self.workers[stream_id]

            # Update status
            self.update_stream_status(stream_id, is_active=False)

            return True

        except Exception as e:
            print(f"Error stopping stream {stream_id}: {e}")
            return False

    async def restart_stream(self, stream_id):
        """Restart a stream"""
        try:
            # Stop first
            await self.stop_stream(stream_id)
            # Small delay to ensure cleanup
            await asyncio.sleep(1)
            # Start again
            return await self.start_stream(stream_id)
        except Exception as e:
            logger.error(f"Error restarting stream {stream_id}: {e}")
            return False


class StreamWorker:
    def __init__(self, stream_data, manager):
        self.stream_data = stream_data
        self.manager = manager
        self.running = False
        self.task = None

    async def run(self):
        """Main worker loop"""
        self.running = True

        try:
            while self.running:
                try:
                    # Your streaming logic here
                    # Use self.stream_data instead of accessing database objects
                    await self.fetch_and_send_data()

                    # Sleep for poll interval
                    await asyncio.sleep(self.stream_data['poll_interval'])

                except Exception as e:
                    print(f"Error in stream worker {self.stream_data['id']}: {e}")
                    self.manager.update_stream_status(
                        self.stream_data['id'],
                        last_error=str(e)
                    )
                    await asyncio.sleep(30)  # Wait before retry

        except asyncio.CancelledError:
            print(f"Stream worker {self.stream_data['id']} cancelled")
        finally:
            self.running = False

    async def stop(self):
        """Stop the worker"""
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def fetch_and_send_data(self):
        """Fetch data and send to TAK server"""
        # Your existing logic here, but use self.stream_data
        # instead of accessing database objects directly
        pass