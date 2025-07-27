"""
File: routes/tak_servers.py

Description:
    TAK (Team Awareness Kit) server management blueprint providing comprehensive administration
    capabilities for TAK server configurations in the TrakBridge application. This module handles
    the complete lifecycle of TAK server management including creation, configuration, testing,
    and maintenance of secure connections to TAK servers. The blueprint supports both traditional
    web forms and JSON API endpoints for flexible integration with various client interfaces.

Key features:
    - Complete TAK server lifecycle management (create, read, update, delete)
    - P12 certificate validation and secure storage with encrypted password handling
    - Real-time connection testing using pytak integration for validation
    - Support for multiple TAK protocols (TLS, TCP, UDP) with configurable SSL verification
    - Base64 certificate handling for API integration and file upload support
    - Comprehensive validation of server configurations before persistence
    - Safety checks preventing deletion of servers with active stream associations
    - Dual interface support (web forms and JSON API) for maximum compatibility
    - Detailed error handling and user feedback for troubleshooting
    - Certificate management with validation, storage, and removal capabilities
    - Asynchronous connection testing with proper error handling
    - Service layer integration for maintainable architecture and business logic separation

Author: Emfour Solutions
Created: 18-Jul-2025
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import base64
import logging

# Third-party imports
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
import asyncio

# Local application imports
from database import db
from models.tak_server import TakServer
from services.tak_servers_service import TakServerService

# Authentication imports
from services.auth import require_auth, require_permission, operator_required

# Module-level logger
logger = logging.getLogger(__name__)

bp = Blueprint("tak_servers", __name__)


@bp.route("/validate-certificate", methods=["POST"])
@require_permission('tak_servers', 'write')
def validate_certificate():
    """Validate uploaded P12 certificate"""
    try:
        # Handle file upload
        if "cert_file" not in request.files:
            return (
                jsonify({"success": False, "error": "No certificate file provided"}),
                400,
            )

        cert_file = request.files["cert_file"]
        if not cert_file or not cert_file.filename:
            return (
                jsonify({"success": False, "error": "No certificate file selected"}),
                400,
            )

        # Get password
        password = request.form.get("password", "")

        # Read certificate data
        cert_data = cert_file.read()
        if not cert_data:
            return (
                jsonify({"success": False, "error": "Certificate file is empty"}),
                400,
            )

        # Validate file size (max 5MB)
        if len(cert_data) > 5 * 1024 * 1024:
            return (
                jsonify(
                    {"success": False, "error": "Certificate file too large (max 5MB)"}
                ),
                400,
            )

        # Validate certificate
        result = TakServerService.validate_certificate_data(cert_data, password)

        if result["success"]:
            logger.info(f"Certificate validation successful for {cert_file.filename}")
        else:
            logger.warning(
                f"Certificate validation failed for {cert_file.filename}: {result['error']}"
            )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Certificate validation endpoint error: {str(e)}")
        return jsonify({"success": False, "error": f"Validation failed: {str(e)}"}), 500


@bp.route("/<int:server_id>/validate-certificate", methods=["POST"])
@require_permission('tak_servers', 'write')
def validate_stored_certificate(server_id):
    try:
        server = TakServer.query.get_or_404(server_id)

        # Call the service method
        result = TakServerService.validate_stored_certificate(server)

        if result["success"]:
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        return (
            jsonify(
                {"success": False, "error": f"Certificate validation failed: {str(e)}"}
            ),
            500,
        )


@bp.route("/")
@require_permission('tak_servers', 'read')
def list_tak_servers():
    """List all TAK servers"""
    from models.tak_server import TakServer

    servers = TakServer.query.all()
    return render_template("tak_servers.html", servers=servers)


@bp.route("/create", methods=["GET", "POST"])
@require_permission('tak_servers', 'write')
def create_tak_server():
    """Create a new TAK server"""
    if request.method == "GET":
        return render_template("create_tak_server.html")

    from models.tak_server import TakServer

    try:
        # Handle file upload differently for form vs JSON
        if request.is_json:
            data = request.get_json()
            cert_p12_data = None
            cert_filename = None

            # Handle base64 encoded certificate from JSON
            if data.get("cert_p12_base64"):
                try:
                    cert_p12_data = base64.b64decode(data["cert_p12_base64"])
                    cert_filename = data.get("cert_p12_filename", "certificate.p12")
                    logger.info(f"Decoded certificate data: {len(cert_p12_data)} bytes")
                except Exception as e:
                    logger.error(f"Failed to decode certificate: {str(e)}")
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Invalid certificate data: {str(e)}",
                            }
                        ),
                        400,
                    )
        else:
            data = request.form
            cert_p12_data = None
            cert_filename = None

            # Handle file upload from form
            if "cert_p12_file" in request.files:
                cert_file = request.files["cert_p12_file"]
                if cert_file and cert_file.filename:
                    cert_p12_data = cert_file.read()
                    cert_filename = cert_file.filename
                    logger.info(
                        f"Read certificate file: {cert_filename}, {len(cert_p12_data)} bytes"
                    )

        # Handle verify_ssl for both form data (string) and JSON data (boolean)
        verify_ssl_value = data.get("verify_ssl", True)
        if isinstance(verify_ssl_value, str):
            verify_ssl = verify_ssl_value.lower() in ["true", "on", "1"]
        elif isinstance(verify_ssl_value, bool):
            verify_ssl = verify_ssl_value
        else:
            verify_ssl = True  # Default to True

        # Validate server data using service
        validation_result = TakServerService.validate_server_data(data)
        if not validation_result["success"]:
            # Join all error messages into a single string or handle individually
            error_message = "; ".join(validation_result["errors"])
            raise ValueError(error_message)

        # Validate certificate if provided
        if cert_p12_data:
            cert_password = data.get("cert_password", "")
            validation_result = TakServerService.validate_certificate_data(
                cert_p12_data, cert_password
            )
            if not validation_result["success"]:
                raise ValueError(
                    f"Certificate validation failed: {validation_result['error']}"
                )

        # Log the data being inserted
        logger.info(
            f"Creating TAK server: {data.get('name')} at {data.get('host')}:{data.get('port')}"
        )
        logger.info(
            f"Protocol: {data.get('protocol', 'tls')}, SSL Verify: {verify_ssl}"
        )
        logger.info(f"Certificate: {'Yes' if cert_p12_data else 'No'}")

        server = TakServer(
            name=data["name"],
            host=data["host"],
            port=data["port"],
            protocol=data.get("protocol", "tls"),
            cert_p12=cert_p12_data,
            cert_p12_filename=cert_filename,
            verify_ssl=verify_ssl,
        )

        # Set the certificate password using the encrypted method
        server.set_cert_password(data.get("cert_password", ""))

        # Add to session and attempt commit
        db.session.add(server)
        db.session.flush()  # This will raise an exception if there's a constraint violation
        db.session.commit()

        logger.info(f"Successfully created TAK server with ID: {server.id}")

        if request.is_json:
            return jsonify({"success": True, "server_id": server.id})
        else:
            flash("TAK Server created successfully", "success")
            return redirect(url_for("tak_servers.list_tak_servers"))

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        db.session.rollback()
        if request.is_json:
            return jsonify({"success": False, "error": str(e)}), 400
        else:
            flash(f"Validation error: {str(e)}", "error")
            return redirect(url_for("tak_servers.create_tak_server"))

    except Exception as e:
        logger.error(f"Database error creating TAK server: {str(e)}", exc_info=True)
        db.session.rollback()
        if request.is_json:
            return (
                jsonify({"success": False, "error": f"Database error: {str(e)}"}),
                500,
            )
        else:
            flash(f"Error creating TAK server: {str(e)}", "error")
            return redirect(url_for("tak_servers.create_tak_server"))


@bp.route("/<int:server_id>")
@require_permission('tak_servers', 'read')
def view_tak_server(server_id):
    """View TAK server details"""
    from models.tak_server import TakServer

    server = TakServer.query.get_or_404(server_id)
    return render_template("tak_server_detail.html", server=server)


@bp.route("/<int:server_id>/edit", methods=["GET", "POST"])
@require_permission('tak_servers', 'write')
def edit_tak_server(server_id):
    """Edit TAK server"""
    from models.tak_server import TakServer

    server = TakServer.query.get_or_404(server_id)

    if request.method == "GET":
        return render_template("edit_tak_server.html", server=server)

    try:
        # Handle file upload differently for form vs JSON
        if request.is_json:
            data = request.get_json()
            cert_p12_data = server.cert_p12  # Keep existing if not updated
            cert_filename = server.cert_p12_filename

            # Handle base64 encoded certificate from JSON
            if data.get("cert_p12_base64"):
                try:
                    cert_p12_data = base64.b64decode(data["cert_p12_base64"])
                    cert_filename = data.get("cert_p12_filename", "certificate.p12")
                except Exception as e:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Invalid certificate data: {str(e)}",
                            }
                        ),
                        400,
                    )
            elif data.get("remove_certificate"):
                cert_p12_data = None
                cert_filename = None
        else:
            data = request.form
            cert_p12_data = server.cert_p12  # Keep existing if not updated
            cert_filename = server.cert_p12_filename

            # Handle file upload from form
            if "cert_p12_file" in request.files:
                cert_file = request.files["cert_p12_file"]
                if cert_file and cert_file.filename:
                    cert_p12_data = cert_file.read()
                    cert_filename = cert_file.filename

            # Handle certificate removal
            if data.get("remove_certificate") == "on":
                cert_p12_data = None
                cert_filename = None

        # Handle verify_ssl for both form data (string) and JSON data (boolean)
        verify_ssl_value = data.get("verify_ssl", True)
        if isinstance(verify_ssl_value, str):
            verify_ssl = verify_ssl_value.lower() in ["true", "on", "1"]
        elif isinstance(verify_ssl_value, bool):
            verify_ssl = verify_ssl_value
        else:
            verify_ssl = True  # Default to True

        # Validate server data using service
        validation_result = TakServerService.validate_server_data(data)
        if not validation_result["success"]:
            # Join all error messages into a single string or handle individually
            error_message = "; ".join(validation_result["errors"])
            raise ValueError(error_message)

        # Validate certificate if provided and changed
        if cert_p12_data and cert_p12_data != server.cert_p12:
            cert_password = data.get("cert_password", "")
            validation_result = TakServerService.validate_certificate_data(
                cert_p12_data, cert_password
            )
            if not validation_result["success"]:
                raise ValueError(
                    f"Certificate validation failed: {validation_result['error']}"
                )

        server.name = data["name"]
        server.host = data["host"]
        server.port = data["port"]
        server.protocol = data.get("protocol", "tls")
        server.cert_p12 = cert_p12_data
        server.cert_p12_filename = cert_filename
        server.verify_ssl = verify_ssl

        # Set the certificate password using the encrypted method
        server.set_cert_password(data.get("cert_password", ""))

        db.session.flush()  # Check for constraint violations
        db.session.commit()

        logger.info(f"Successfully updated TAK server ID: {server_id}")

        if request.is_json:
            return jsonify({"success": True})
        else:
            flash("TAK Server updated successfully", "success")
            return redirect(url_for("tak_servers.view_tak_server", server_id=server_id))

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        db.session.rollback()
        if request.is_json:
            return jsonify({"success": False, "error": str(e)}), 400
        else:
            flash(f"Validation error: {str(e)}", "error")
            return redirect(url_for("tak_servers.edit_tak_server", server_id=server_id))

    except Exception as e:
        logger.error(f"Database error updating TAK server: {str(e)}", exc_info=True)
        db.session.rollback()
        if request.is_json:
            return (
                jsonify({"success": False, "error": f"Database error: {str(e)}"}),
                500,
            )
        else:
            flash(f"Error updating TAK server: {str(e)}", "error")
            return redirect(url_for("tak_servers.edit_tak_server", server_id=server_id))


@bp.route("/<int:server_id>/delete", methods=["DELETE"])
@require_permission('tak_servers', 'delete')
def delete_tak_server(server_id):
    """Delete TAK server"""
    try:
        from models.tak_server import TakServer

        server = TakServer.query.get_or_404(server_id)

        if server.streams:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Cannot delete server with associated streams",
                    }
                ),
                400,
            )

        db.session.delete(server)
        db.session.commit()

        logger.info(f"Successfully deleted TAK server ID: {server_id}")
        return jsonify({"success": True, "message": "TAK Server deleted"})

    except Exception as e:
        logger.error(f"Error deleting TAK server: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/<int:server_id>/test", methods=["POST"])
@require_permission('tak_servers', 'write')
def test_tak_server(server_id):
    """Test connection to existing TAK server using pytak"""
    from models.tak_server import TakServer

    try:
        server = TakServer.query.get_or_404(server_id)

        # Call the service method (it handles the async execution internally)
        result = asyncio.run(TakServerService.test_server_connection(server))

        return jsonify(result)

    except Exception as e:
        logger.error(f"Connection test error for server {server_id}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/test-config", methods=["POST"])
@require_permission('tak_servers', 'write')
def test_tak_server_config():
    """Test TAK server configuration without saving to database"""
    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ["name", "host", "port", "protocol"]
        for field in required_fields:
            if not data.get(field):
                return (
                    jsonify(
                        {"success": False, "error": f"Missing required field: {field}"}
                    ),
                    400,
                )

        # Create a temporary server object for testing
        from models.tak_server import TakServer

        temp_server = TakServer(
            name=data["name"],
            host=data["host"],
            port=data["port"],
            protocol=data.get("protocol", "tls"),
            verify_ssl=data.get("verify_ssl", True),
        )

        # Handle certificate data if provided
        if "cert_p12" in data and data["cert_p12"]:
            # Decode base64 certificate data
            import base64

            cert_data = base64.b64decode(data["cert_p12"])
            temp_server.cert_p12 = cert_data

            # Handle certificate password if provided
            if "cert_password" in data and data["cert_password"]:
                temp_server.set_cert_password(data["cert_password"])

        # Test the connection using the existing service
        from services.tak_servers_service import TakServerService

        # Test connection using static method
        result = asyncio.run(TakServerService.test_server_connection(temp_server))

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
