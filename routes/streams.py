"""
File: routes/streams.py

Description:
    Stream management blueprint providing comprehensive CRUD operations and real-time control
    for GPS data streams in the TrakBridge application. This module serves as the primary
    interface for managing stream configurations, monitoring stream status, and performing
    operational tasks such as starting, stopping, and testing stream connections. The blueprint
    integrates with multiple service layers to provide a complete stream management experience
    through both web interface and API endpoints.

Key features:
    - Complete stream lifecycle management (create, read, update, delete)
    - Real-time stream operations (start, stop, restart) with status monitoring
    - Plugin-based stream configuration with dynamic metadata handling
    - Connection testing for both new and existing stream configurations
    - Stream listing with aggregated statistics and plugin metadata
    - Detailed stream view with operational status and configuration display
    - Form-based and JSON API support for flexible client integration
    - Integration with TAK server management for stream deployment
    - CoT (Cursor on Target) type configuration and management
    - Comprehensive error handling and user feedback systems
    - Service layer abstraction for maintainable architecture
    - Runtime service resolution for proper Flask application context

Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import logging

# Third-party imports
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    current_app,
)

# Local application imports
from database import db
from models.tak_server import TakServer
from services.stream_display_service import StreamDisplayService
from services.stream_config_service import StreamConfigService
from services.stream_operations_service import StreamOperationsService
from services.connection_test_service import ConnectionTestService
from services.stream_status_service import StreamStatusService
from services.cot_type_service import cot_type_service
from utils.app_helpers import get_plugin_manager

# Module-level logger
logger = logging.getLogger(__name__)

bp = Blueprint("streams", __name__)


def get_display_service():
    """Get the display service with current app context"""
    return StreamDisplayService(get_plugin_manager())


def get_config_service():
    """Get the config service with current app context"""
    return StreamConfigService(get_plugin_manager())


def get_stream_services():
    app_context_factory = getattr(current_app, "app_context_factory", None)
    if app_context_factory is None:
        # Fallback to the default Flask app context method
        app_context_factory = current_app.app_context
    stream_manager = getattr(current_app, "stream_manager", None)
    if stream_manager is None:
        raise ValueError("Stream manager not found in current_app")
    return {
        "operations_service": StreamOperationsService(stream_manager, db),
        "test_service": ConnectionTestService(get_plugin_manager(), stream_manager),
        "status_service": StreamStatusService(stream_manager),
    }


@bp.route("/")
def list_streams():
    """Display list of all streams"""
    try:
        streams = get_display_service().get_streams_for_listing()
        plugin_stats, plugin_metadata = (
            get_display_service().calculate_plugin_statistics(streams)
        )
        # Serialize all plugin metadata for JSON
        plugin_metadata = {
            k: get_config_service().serialize_plugin_metadata(v)
            for k, v in plugin_metadata.items()
        }

        return render_template(
            "streams.html",
            streams=streams,
            plugin_stats=plugin_stats,
            plugin_metadata=plugin_metadata,
        )

    except Exception as e:
        logger.error(f"Error loading streams: {e}")
        flash("Error loading streams", "error")
        return render_template("streams.html", streams=[])


@bp.route("/create", methods=["GET", "POST"])
def create_stream():
    """Create a new stream"""
    if request.method == "GET":
        return _render_create_form()

    # Handle POST request
    try:
        # Get the correct operations_service at runtime
        services = get_stream_services()
        operations_service = services["operations_service"]

        data = request.get_json() if request.is_json else request.form
        result = operations_service.create_stream(data)

        if request.is_json:
            return jsonify(result)
        else:
            flash(result["message"], "success" if result["success"] else "error")
            if result["success"]:
                return redirect(
                    url_for("streams.view_stream", stream_id=result["stream_id"])
                )
            else:
                return redirect(url_for("streams.create_stream"))

    except Exception as e:
        logger.error(f"Error creating stream: {e}")
        if request.is_json:
            return jsonify({"success": False, "error": str(e)}), 400
        else:
            flash(f"Error creating stream: {str(e)}", "error")
            return redirect(url_for("streams.create_stream"))


def _render_create_form():
    """Render the create stream form"""
    tak_servers = TakServer.query.all()
    cot_types = cot_type_service.get_template_data()
    plugin_metadata = get_config_service().get_all_plugin_metadata()
    # Serialize all plugin metadata for JSON
    plugin_metadata = {
        k: get_config_service().serialize_plugin_metadata(v)
        for k, v in plugin_metadata.items()
    }

    return render_template(
        "create_stream.html",
        tak_servers=tak_servers,
        plugin_metadata=plugin_metadata,
        cot_types=cot_types["cot_types"],
        default_cot_type=cot_types["default_cot_type"],
    )


@bp.route("/test-connection", methods=["POST"])
def test_connection():
    """Test connection to a GPS provider without saving"""

    # Get the correct test_service at runtime
    services = get_stream_services()
    test_service = services["test_service"]

    try:
        data = request.get_json()
        plugin_type = data.get("plugin_type")

        if not plugin_type:
            return jsonify({"success": False, "error": "Plugin type required"}), 400

        plugin_config = get_config_service().extract_plugin_config_from_request(data)
        result = test_service.test_plugin_connection_sync(plugin_type, plugin_config)

        return jsonify(result), 200 if result["success"] else 400

    except Exception as e:
        logger.error(f"Error testing connection: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/<int:stream_id>")
def view_stream(stream_id):
    """View stream details"""
    try:
        stream = get_display_service().get_stream_for_detail_view(stream_id)
        return render_template("stream_detail.html", stream=stream)

    except Exception as e:
        logger.error(f"Error viewing stream {stream_id}: {e}")
        flash("Error loading stream details", "error")
        return redirect(url_for("streams.list_streams"))


@bp.route("/<int:stream_id>/start", methods=["POST"])
def start_stream(stream_id):
    """Start a stream - enables it if disabled, then starts it"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services["operations_service"]

    try:
        result = operations_service.start_stream_with_enable(stream_id)
        return jsonify(result), 200 if result["success"] else 400

    except Exception as e:
        logger.error(f"Error starting stream {stream_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/<int:stream_id>/stop", methods=["POST"])
def stop_stream(stream_id):
    """Stop a stream"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services["operations_service"]

    try:
        result = operations_service.stop_stream_with_disable(stream_id)
        return jsonify(result), 200 if result["success"] else 400

    except Exception as e:
        logger.error(f"Error stopping stream {stream_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/<int:stream_id>/restart", methods=["POST"])
def restart_stream(stream_id):
    """Restart a stream"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services["operations_service"]

    try:
        result = operations_service.restart_stream(stream_id)
        return jsonify(result), 200 if result["success"] else 400

    except Exception as e:
        logger.error(f"Error restarting stream {stream_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/<int:stream_id>/test", methods=["POST"])
def test_stream(stream_id):
    """Test an existing stream's connection"""

    # Get the correct test_service at runtime
    services = get_stream_services()
    test_service = services["test_service"]

    try:
        result = test_service.test_stream_connection_sync(stream_id)
        return jsonify(result), 200 if result["success"] else 400

    except Exception as e:
        logger.error(f"Error testing stream {stream_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/<int:stream_id>/delete", methods=["DELETE"])
def delete_stream(stream_id):
    """Delete a stream"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services["operations_service"]

    try:
        result = operations_service.delete_stream(stream_id)
        return jsonify(result), 200 if result["success"] else 500

    except Exception as e:
        logger.error(f"Error deleting stream {stream_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/<int:stream_id>/edit", methods=["GET", "POST"])
def edit_stream(stream_id):
    """Edit an existing stream"""

    # Get the correct operations_service at runtime
    services = get_stream_services()
    operations_service = services["operations_service"]

    if request.method == "GET":
        return _render_edit_form(stream_id)

    # Handle POST request
    try:
        data = request.get_json() if request.is_json else request.form
        result = operations_service.update_stream_safely(stream_id, data)

        if request.is_json:
            return jsonify(result), 200 if result["success"] else 400
        else:
            flash(result["message"], "success" if result["success"] else "error")
            if result["success"]:
                return redirect(url_for("streams.view_stream", stream_id=stream_id))
            else:
                return redirect(url_for("streams.edit_stream", stream_id=stream_id))

    except Exception as e:
        logger.error(f"Error updating stream {stream_id}: {e}")
        if request.is_json:
            return jsonify({"success": False, "error": str(e)}), 400
        else:
            flash(f"Error updating stream: {str(e)}", "error")
            return redirect(url_for("streams.edit_stream", stream_id=stream_id))


def _render_edit_form(stream_id):
    """Render the edit stream form"""
    stream = get_display_service().get_stream_for_edit_form(stream_id)
    tak_servers = TakServer.query.all()
    plugin_metadata = get_config_service().get_all_plugin_metadata()
    # Serialize all plugin metadata for JSON
    plugin_metadata = {
        k: get_config_service().serialize_plugin_metadata(v)
        for k, v in plugin_metadata.items()
    }
    cot_types = cot_type_service.get_template_data()

    return render_template(
        "edit_stream.html",
        stream=stream,
        tak_servers=tak_servers,
        plugin_metadata=plugin_metadata,
        cot_types=cot_types["cot_types"],
        default_cot_type=cot_types["default_cot_type"],
    )


@bp.route("/test-config", methods=["POST"])
def test_stream_config():
    """Test stream configuration without saving to database"""
    try:
        data = request.get_json()
        logger.info(f"Received test-config data: {data}")
        logger.info(
            f"Plugin config type: {type(data.get('plugin_config'))}, value: {data.get('plugin_config')}"
        )

        # Validate required fields
        if "plugin_type" not in data or not data["plugin_type"]:
            logger.error("Missing required field: plugin_type")
            return (
                jsonify(
                    {"success": False, "error": "Missing required field: plugin_type"}
                ),
                400,
            )

        # plugin_config can be empty for testing, but must be present
        if "plugin_config" not in data:
            logger.error("Missing required field: plugin_config")
            return (
                jsonify(
                    {"success": False, "error": "Missing required field: plugin_config"}
                ),
                400,
            )

        # Test the connection using the plugin
        from plugins.plugin_manager import get_plugin_manager

        plugin_manager = get_plugin_manager()

        # Get plugin instance
        plugin_instance = plugin_manager.get_plugin(
            data["plugin_type"], data["plugin_config"]
        )
        if not plugin_instance:
            logger.error(
                f"Plugin type not found or failed to create: {data['plugin_type']}"
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f'Plugin type not found: {data["plugin_type"]}',
                    }
                ),
                400,
            )

        logger.info(
            f"Created plugin instance for {data['plugin_type']} with config: {data['plugin_config']}"
        )

        # Test connection
        import asyncio

        try:
            logger.info("Starting connection test...")
            # Run the test connection
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(plugin_instance.test_connection())
            loop.close()

            logger.info(f"Connection test result: {result}")
            return jsonify(result)

        except Exception as e:
            logger.error(f"Connection test failed with exception: {e}", exc_info=True)
            return (
                jsonify(
                    {"success": False, "error": f"Connection test failed: {str(e)}"}
                ),
                500,
            )

    except Exception as e:
        logger.error(f"Test config failed with exception: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
