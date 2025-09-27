"""
ABOUTME: Data Transfer Object (DTO) models for clean data representation across thread boundaries
ABOUTME: Provides type-safe, lightweight alternatives to complex mock objects in database operations

File: models/dto.py

Description:
    Clean data transfer objects that replace complex mock objects used in database
    operations. These DTOs provide type-safe, lightweight alternatives to
    SimpleNamespace objects for passing data across thread boundaries without
    database session dependencies.

Key features:
    - Type-safe data representation with full type hints
    - Immutable data structures for thread safety
    - Clean conversion methods from SQLAlchemy ORM models
    - No database session dependencies for cross-thread usage
    - Comprehensive field coverage for all stream and server data
    - Factory methods for creating DTOs from various sources

Author: Emfour Solutions
Created: 2025-09-26
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional, List


@dataclass(frozen=True)
class TakServerDTO:
    """Clean, immutable data transfer object for TAK server information"""

    id: int
    name: str
    host: str
    port: int
    protocol: str
    enabled: bool = True
    description: Optional[str] = None
    cert_file: Optional[str] = None
    key_file: Optional[str] = None
    ca_file: Optional[str] = None
    verify_ssl: bool = True
    cert_p12: Optional[str] = None
    cert_password: Optional[str] = None
    has_cert_password: bool = False

    @classmethod
    def from_orm(cls, tak_server) -> "TakServerDTO":
        """Convert SQLAlchemy TAK server object to clean DTO"""
        # Get cert password safely
        cert_password = None
        try:
            if hasattr(tak_server, "get_cert_password"):
                cert_password = tak_server.get_cert_password()
        except Exception:
            cert_password = None

        return cls(
            id=tak_server.id,
            name=tak_server.name,
            host=tak_server.host,
            port=tak_server.port,
            protocol=tak_server.protocol,
            enabled=getattr(tak_server, "enabled", True),
            description=getattr(tak_server, "description", None),
            cert_file=getattr(tak_server, "cert_file", None),
            key_file=getattr(tak_server, "key_file", None),
            ca_file=getattr(tak_server, "ca_file", None),
            verify_ssl=getattr(tak_server, "verify_ssl", True),
            cert_p12=getattr(tak_server, "cert_p12", None),
            cert_password=cert_password,
            has_cert_password=getattr(tak_server, "has_cert_password", False),
        )

    def get_cert_password(self) -> Optional[str]:
        """Backward compatibility method for getting certificate password"""
        return self.cert_password


@dataclass(frozen=True)
class StreamDTO:
    """Clean, immutable data transfer object for stream information"""

    id: int
    name: str
    plugin_type: str
    is_active: bool
    last_poll: Optional[datetime]
    last_error: Optional[str]
    poll_interval: int
    cot_type: str
    cot_stale_time: int
    plugin_config: Dict[str, Any]
    total_messages_sent: int = 0

    # Callsign mapping and per-point configuration fields
    cot_type_mode: str = "stream"
    enable_callsign_mapping: bool = False
    callsign_identifier_field: Optional[str] = None
    callsign_error_handling: str = "fallback"

    # TAK server relationships
    tak_server: Optional[TakServerDTO] = None
    tak_servers: List[TakServerDTO] = None

    # Additional fields for backward compatibility
    tak_server_id: Optional[int] = None
    enable_per_callsign_cot_types: bool = False
    config_version: Optional[str] = None

    def __post_init__(self):
        """Ensure tak_servers is always a list and setup compatibility attributes"""
        if self.tak_servers is None:
            object.__setattr__(self, "tak_servers", [])

        # Set tak_server_id for compatibility
        if self.tak_server and not self.tak_server_id:
            object.__setattr__(self, "tak_server_id", self.tak_server.id)

    @classmethod
    def from_orm(cls, stream) -> "StreamDTO":
        """Convert SQLAlchemy stream object to clean DTO"""
        # Convert primary TAK server if present
        tak_server_dto = None
        if hasattr(stream, "tak_server") and stream.tak_server:
            tak_server_dto = TakServerDTO.from_orm(stream.tak_server)

        # Convert all TAK servers if present
        tak_servers_dto = []
        if hasattr(stream, "tak_servers") and stream.tak_servers:
            tak_servers_dto = [
                TakServerDTO.from_orm(server) for server in stream.tak_servers
            ]
        elif tak_server_dto:
            # If only primary TAK server exists, include it in the list
            tak_servers_dto = [tak_server_dto]

        return cls(
            id=stream.id,
            name=stream.name,
            plugin_type=stream.plugin_type,
            is_active=stream.is_active,
            last_poll=stream.last_poll,
            last_error=stream.last_error,
            poll_interval=stream.poll_interval,
            cot_type=stream.cot_type,
            cot_stale_time=stream.cot_stale_time,
            plugin_config=stream.plugin_config,
            total_messages_sent=getattr(stream, "total_messages_sent", 0),
            cot_type_mode=getattr(stream, "cot_type_mode", "stream"),
            enable_callsign_mapping=getattr(stream, "enable_callsign_mapping", False),
            callsign_identifier_field=getattr(
                stream, "callsign_identifier_field", None
            ),
            callsign_error_handling=getattr(
                stream, "callsign_error_handling", "fallback"
            ),
            tak_server=tak_server_dto,
            tak_servers=tak_servers_dto,
            tak_server_id=getattr(stream, "tak_server_id", None),
            enable_per_callsign_cot_types=getattr(
                stream, "enable_per_callsign_cot_types", False
            ),
            config_version=getattr(stream, "config_version", None),
        )

    def get_active_tak_servers(self) -> List[TakServerDTO]:
        """Get list of active TAK servers for this stream"""
        if self.tak_servers:
            return [server for server in self.tak_servers if server.enabled]
        elif self.tak_server and self.tak_server.enabled:
            return [self.tak_server]
        return []

    def has_valid_tak_servers(self) -> bool:
        """Check if stream has at least one valid TAK server"""
        return len(self.get_active_tak_servers()) > 0

    def get_config_hash(self) -> str:
        """Generate a hash of the configuration for caching purposes"""
        import hashlib
        import json

        # Create a deterministic string representation of the config
        config_str = json.dumps(self.plugin_config, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()

    def get_plugin_config(self) -> Dict[str, Any]:
        """Backward compatibility method for getting plugin configuration"""
        return self.plugin_config or {}
