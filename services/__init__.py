"""
File: services/__init__.py

Description:
    Service layer package initialization module providing centralized access to core business
    logic services in the TrakBridge application. This module serves as the primary entry point
    for the service layer architecture, exposing key management services that handle stream
    operations, database interactions, worker thread management, and session handling. The
    package follows a service-oriented architecture pattern to separate business logic from
    presentation and data access layers.

Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Local application imports
from .stream_manager import StreamManager, get_stream_manager
from .database_manager import DatabaseManager
from .stream_worker import StreamWorker
from .session_manager import SessionManager

__all__ = [
    "StreamManager",
    "get_stream_manager",
    "DatabaseManager",
    "StreamWorker",
    "SessionManager",
]
