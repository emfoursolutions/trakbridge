"""
File: services/stream_config_service.py

Description:
    Advanced stream configuration management service providing comprehensive plugin
    metadata handling, security validation, and configuration export capabilities.
    This service manages stream configurations with focus on security, validation,
    and metadata-driven configuration management for the TrakBridge application.

Key features:
    - Comprehensive plugin configuration security validation with sensitive field
      detection
    - Advanced security analysis including weak password detection and default
      credential identification
    - Plugin metadata management with serialization support for JSON API responses
    - Stream configuration export functionality with selective sensitive data
      inclusion
    - Security status reporting across all stream configurations with issue
      categorization
    - Plugin configuration extraction from HTTP request data with validation
    - Encrypted field detection and tracking for security compliance monitoring
    - Stream display preparation with plugin metadata enrichment
    - Configuration field validation with type checking and format verification
    - Comprehensive error handling with detailed logging and fallback mechanisms

Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import logging
from typing import Any, Dict, Optional

# Local application imports
from models.stream import Stream

logger = logging.getLogger(__name__)


class StreamConfigService:
    """Service for managing stream configurations and plugin metadata"""

    def __init__(self, plugin_manager: Any) -> None:
        self.plugin_manager = plugin_manager

    def validate_plugin_config_security(
        self, plugin_type: str, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate plugin configuration for security issues"""
        try:
            validation_result: Dict[str, Any] = {
                "valid": True,
                "warnings": [],
                "errors": [],
                "security_issues": [],
            }

            # Get plugin metadata to identify sensitive fields
            metadata = self.plugin_manager.get_plugin_metadata(plugin_type)
            if not metadata:
                validation_result["errors"].append(
                    f"Plugin type '{plugin_type}' not found"
                )
                validation_result["valid"] = False
                return validation_result

            # Check for sensitive fields that should be encrypted
            sensitive_fields = []
            for field_data in metadata.get("config_fields", []):
                if isinstance(field_data, dict) and field_data.get("sensitive"):
                    sensitive_fields.append(field_data["name"])
                elif hasattr(field_data, "sensitive") and field_data.sensitive:
                    sensitive_fields.append(field_data.name)

            # Validate sensitive fields
            for field_name in sensitive_fields:
                if field_name in config:
                    value = config[field_name]
                    if isinstance(value, str) and len(value) < 8:
                        validation_result["warnings"].append(
                            f"Password '{field_name}' is very short (less than 8 characters)"
                        )
                    if isinstance(value, str) and value.lower() in [
                        "password",
                        "123456",
                        "admin",
                    ]:
                        validation_result["security_issues"].append(
                            f"Password '{field_name}' appears to be weak"
                        )

            # Check for common security issues
            for key, value in config.items():
                if isinstance(value, str):
                    if "password" in key.lower() and value == "password":
                        validation_result["security_issues"].append(
                            f"Field '{key}' contains default password value"
                        )
                    if "url" in key.lower() and not value.startswith(
                        ("http://", "https://")
                    ):
                        validation_result["warnings"].append(
                            f"URL field '{key}' may not be properly formatted"
                        )

            return validation_result

        except Exception as e:
            logger.error(f"Error validating plugin config security: {e}")
            return {
                "valid": False,
                "warnings": [],
                "errors": [f"Validation error: {str(e)}"],
                "security_issues": [],
            }

    @staticmethod
    def extract_plugin_config_from_request(data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract plugin configuration from request data"""
        plugin_config: Dict[str, Any] = {}

        for key, value in data.items():
            if key.startswith("plugin_"):
                # Remove 'plugin_' prefix
                config_key = key[7:]
                plugin_config[config_key] = value

        return plugin_config

    @staticmethod
    def export_stream_config(
        stream_id: int, include_sensitive: bool = False
    ) -> Dict[str, Any]:
        """Export stream configuration for backup or migration"""
        try:
            stream = Stream.query.get_or_404(stream_id)

            export_data: Dict[str, Any] = {
                "stream_id": stream.id,
                "name": stream.name,
                "plugin_type": stream.plugin_type,
                "configuration": {
                    "poll_interval": stream.poll_interval,
                    "cot_type": stream.cot_type,
                    "cot_stale_time": stream.cot_stale_time,
                    "tak_server_id": stream.tak_server_id,
                    "is_active": stream.is_active,
                },
                "plugin_config": stream.to_dict(include_sensitive=include_sensitive)[
                    "plugin_config"
                ],
                "metadata": {
                    "created_at": (
                        stream.created_at.isoformat() if stream.created_at else None
                    ),
                    "updated_at": (
                        stream.updated_at.isoformat() if stream.updated_at else None
                    ),
                    "total_messages_sent": stream.total_messages_sent,
                },
            }

            # Add TAK server information if available
            if stream.tak_server:
                export_data["tak_server"] = {
                    "id": stream.tak_server.id,
                    "name": stream.tak_server.name,
                    "host": stream.tak_server.host,
                    "port": stream.tak_server.port,
                }

            return export_data

        except Exception as e:
            logger.error(f"Error exporting stream config for {stream_id}: {e}")
            return {"error": str(e), "stream_id": stream_id}

    def get_security_status(self) -> Dict[str, Any]:
        """Get security status of all stream configurations"""
        try:
            streams = Stream.query.all()
            security_status: Dict[str, Any] = {
                "total_streams": len(streams),
                "streams_with_issues": 0,
                "encrypted_fields": 0,
                "weak_passwords": 0,
                "default_passwords": 0,
                "stream_details": [],
            }

            for stream in streams:
                stream_security = self._analyze_stream_security(stream)
                security_status["stream_details"].append(stream_security)

                if stream_security["has_issues"]:
                    security_status["streams_with_issues"] += 1

                security_status["encrypted_fields"] += stream_security[
                    "encrypted_fields"
                ]
                security_status["weak_passwords"] += stream_security["weak_passwords"]
                security_status["default_passwords"] += stream_security[
                    "default_passwords"
                ]

            return security_status

        except Exception as e:
            logger.error(f"Error getting security status: {e}")
            return {
                "error": str(e),
                "total_streams": 0,
                "streams_with_issues": 0,
                "encrypted_fields": 0,
                "weak_passwords": 0,
                "default_passwords": 0,
                "stream_details": [],
            }

    def get_plugin_metadata(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific plugin"""
        try:
            return self.plugin_manager.get_plugin_metadata(plugin_name)
        except Exception as e:
            logger.error(f"Error getting plugin metadata for {plugin_name}: {e}")
            return None

    def get_all_plugin_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Get metadata for all available plugins"""
        try:
            return self.plugin_manager.get_all_plugin_metadata()
        except Exception as e:
            logger.error(f"Error getting all plugin metadata: {e}")
            return {}

    @staticmethod
    def serialize_plugin_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize plugin metadata for JSON response"""
        try:
            serialized: Dict[str, Any] = {
                "display_name": metadata.get("display_name", ""),
                "description": metadata.get("description", ""),
                "icon": metadata.get("icon", ""),
                "category": metadata.get("category", ""),
                "config_fields": [],
            }

            # Serialize config fields
            for field in metadata.get("config_fields", []):
                if hasattr(field, "to_dict"):
                    serialized["config_fields"].append(field.to_dict())
                elif isinstance(field, dict):
                    serialized["config_fields"].append(field)
                else:
                    logger.warning(f"Unexpected field type: {type(field)}")

            # Serialize help sections
            if "help_sections" in metadata:
                serialized["help_sections"] = metadata["help_sections"]

            return serialized

        except Exception as e:
            logger.error(f"Error serializing plugin metadata: {e}")
            return {
                "error": str(e),
                "display_name": "",
                "description": "",
                "icon": "",
                "category": "",
                "config_fields": [],
            }

    def prepare_stream_for_display(self, stream: Stream) -> Stream:
        """Prepare a stream object for display with additional metadata"""
        try:
            # Add plugin metadata
            metadata = self.get_plugin_metadata(stream.plugin_type)
            if metadata:
                # Add metadata as a property to the stream object
                setattr(stream, "_plugin_metadata", metadata)
                setattr(
                    stream,
                    "plugin_display_name",
                    metadata.get("display_name", stream.plugin_type),
                )
                setattr(stream, "plugin_description", metadata.get("description", ""))
                setattr(stream, "plugin_icon", metadata.get("icon", ""))
                setattr(stream, "plugin_category", metadata.get("category", ""))

            return stream

        except Exception as e:
            logger.error(f"Error preparing stream for display: {e}")
            return stream

    def _analyze_stream_security(self, stream: Stream) -> Dict[str, Any]:
        """Analyze security of a single stream configuration"""
        try:
            analysis: Dict[str, Any] = {
                "stream_id": stream.id,
                "stream_name": stream.name,
                "plugin_type": stream.plugin_type,
                "has_issues": False,
                "encrypted_fields": 0,
                "weak_passwords": 0,
                "default_passwords": 0,
                "issues": [],
            }

            # Get plugin metadata
            metadata = self.get_plugin_metadata(stream.plugin_type)
            if not metadata:
                analysis["issues"].append("Plugin metadata not found")
                analysis["has_issues"] = True
                return analysis

            # Check for encrypted fields
            raw_config = stream.get_raw_plugin_config()
            for key, value in raw_config.items():
                if isinstance(value, str) and value.startswith("ENC:"):
                    analysis["encrypted_fields"] += 1

            # Check for weak passwords
            sensitive_fields = []
            for field_data in metadata.get("config_fields", []):
                if isinstance(field_data, dict) and field_data.get("sensitive"):
                    sensitive_fields.append(field_data["name"])
                elif hasattr(field_data, "sensitive") and field_data.sensitive:
                    sensitive_fields.append(field_data.name)

            decrypted_config = stream.get_plugin_config()
            for field_name in sensitive_fields:
                if field_name in decrypted_config:
                    value = decrypted_config[field_name]
                    if isinstance(value, str):
                        if len(value) < 8:
                            analysis["weak_passwords"] += 1
                            analysis["issues"].append(
                                f"Weak password in field '{field_name}'"
                            )
                        if value.lower() in ["password", "123456", "admin"]:
                            analysis["default_passwords"] += 1
                            analysis["issues"].append(
                                f"Default password in field '{field_name}'"
                            )

            analysis["has_issues"] = len(analysis["issues"]) > 0
            return analysis

        except Exception as e:
            logger.error(f"Error analyzing stream security for {stream.id}: {e}")
            return {
                "stream_id": stream.id,
                "stream_name": stream.name,
                "plugin_type": stream.plugin_type,
                "has_issues": True,
                "encrypted_fields": 0,
                "weak_passwords": 0,
                "default_passwords": 0,
                "issues": [f"Analysis error: {str(e)}"],
            }
