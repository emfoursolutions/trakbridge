"""
File: services/logging_service.py

Description:
    Logging service that provides detailed logging functions to the application.
    Configures and sets log files and displays detailed startup banners.

Author: Emfour Solutions
Created: 2025-07-18
Last Modified: 2025-07-27
"""

import datetime

# Standard library imports
import logging
import os
from typing import Optional

# Local application imports
from services.version import (
    get_build_info,
    get_version,
    get_version_info,
    is_development_build,
)

logger = logging.getLogger(__name__)


# Backwards-compatible logging utilities to reduce boilerplate
def get_module_logger(module_name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger for a module. Backwards-compatible replacement for logging.getLogger(__name__).

    Args:
        module_name: Module name (__name__). If None, attempts auto-detection

    Returns:
        Logger instance

    Usage:
        # Instead of: logger = logging.getLogger(__name__)
        # Use:        logger = get_module_logger(__name__)
        # Or:         logger = get_module_logger()  # Auto-detects module
    """
    if module_name is None:
        # Auto-detect calling module for convenience
        import inspect

        frame = inspect.currentframe()
        if frame and frame.f_back:
            calling_module = frame.f_back.f_globals.get("__name__", "unknown")
            module_name = calling_module
        else:
            module_name = "unknown"

    return logging.getLogger(module_name)


def create_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Create a logger instance with automatic module detection.
    Alias for get_module_logger for convenience.

    Args:
        name: Logger name. If None, auto-detects calling module

    Returns:
        Logger instance
    """
    return get_module_logger(name)


def setup_logging(app):
    """Set up application logging with version information."""

    # Create logs directory if it doesn't exist
    log_dir = app.config.get("LOG_DIR", "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Get log level
    log_level = getattr(logging, app.config.get("LOG_LEVEL", "INFO"))

    # Get version for log formatting
    try:
        version = get_version()
    except Exception:
        version = "unknown"

    # Create formatters with version information
    detailed_formatter = logging.Formatter(
        f"%(asctime)s [%(levelname)s] TrakBridge-{version} %(name)s: %(message)s"
    )

    # Set up file handler with version in filename
    log_filename = "trakbridge.log"
    file_handler = logging.FileHandler(os.path.join(log_dir, log_filename))
    file_handler.setFormatter(detailed_formatter)
    file_handler.setLevel(log_level)

    # Set up console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(detailed_formatter)
    console_handler.setLevel(log_level)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add new handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Set specific logger levels
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if app.config.get("SQLALCHEMY_RECORD_QUERIES") else logging.WARNING
    )
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    
    # Configure PyTAK logging level
    pytak_log_level = app.config.get("PYTAK_LOG_LEVEL", "WARNING")
    logging.getLogger("pytak").setLevel(getattr(logging, pytak_log_level, logging.WARNING))

    app.logger.info(f"Logging Service Started - Version: {version}")


def log_startup_banner(app):
    """Log a comprehensive startup banner."""
    try:
        version_info = get_version_info()
        build_info = get_build_info()

        banner_lines = [
            "",
            "=" * 80,
            " TrakBridge Application Starting",
            "=" * 80,
            f" Version: {version_info.get('version', 'unknown')}",
            f"  Build Source: {version_info.get('source', 'unknown')}",
            f" Environment: {os.getenv('FLASK_ENV', 'unknown')}",
            f" Debug Mode: {'ON' if app.debug else 'OFF'}",
            f" Development: {'YES' if is_development_build() else 'NO'}",
            "",
            " System Information:",
            f"   Python: {version_info.get('python_version', 'unknown')}",
            f"   Platform: {version_info.get('platform', 'unknown')}",
            f"   Working Directory: {os.getcwd()}",
            f"   Process ID: {os.getpid()}",
            f"   User: {os.getenv('USER', os.getenv('USERNAME', 'unknown'))}",
        ]

        # Add Git information if available
        if build_info.get("git_commit"):
            banner_lines.append(f"   Git Commit: {build_info['git_commit']}")

        # Add configuration details
        db_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", "not configured"))
        banner_lines.extend(
            [
                "",
                "  Configuration:",
                f"   Database: {db_uri[:50]}...",
                f"   Max Worker Threads: {app.config.get('MAX_WORKER_THREADS', 'not set')}",
                f"   Max Concurrent Streams: {app.config.get('MAX_CONCURRENT_STREAMS', 'not set')}",
                f"   Log Level: {app.config.get('LOG_LEVEL', 'not set')}",
                f"   Log Directory: {app.config.get('LOG_DIR', 'not set')}",
            ]
        )

        # Add timestamp
        banner_lines.extend(
            [
                "",
                f" Started at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "=" * 80,
                "",
            ]
        )

        # Log each line
        for line in banner_lines:
            app.logger.info(line)

    except Exception as e:
        app.logger.error(f"Failed to log startup banner: {e}")
        # Fallback to basic logging
        from services.version import get_version

        app.logger.info(f"TrakBridge starting - Version: {get_version()}")


def log_primary_startup_banner(app, worker_count: Optional[int] = None):
    """
    Log startup banner for primary process with worker count information.
    This replaces log_startup_banner for primary processes to include worker coordination info.

    Args:
        app: Flask application instance
        worker_count: Number of worker processes that will be started
    """
    try:
        version_info = get_version_info()
        build_info = get_build_info()

        banner_lines = [
            "",
            "=" * 80,
            " TrakBridge Application Starting (Primary Process)",
            "=" * 80,
            f" Version: {version_info.get('version', 'unknown')}",
            f"  Build Source: {version_info.get('source', 'unknown')}",
            f" Environment: {os.getenv('FLASK_ENV', 'unknown')}",
            f" Debug Mode: {'ON' if app.debug else 'OFF'}",
            f" Development: {'YES' if is_development_build() else 'NO'}",
            "",
            " System Information:",
            f"   Python: {version_info.get('python_version', 'unknown')}",
            f"   Platform: {version_info.get('platform', 'unknown')}",
            f"   Working Directory: {os.getcwd()}",
            f"   Primary Process ID: {os.getpid()}",
            f"   User: {os.getenv('USER', os.getenv('USERNAME', 'unknown'))}",
        ]

        # Add worker information
        if worker_count and worker_count > 1:
            banner_lines.extend(
                [
                    "",
                    " Worker Configuration:",
                    f"   Total Workers: {worker_count}",
                    f"   Worker processes will log minimal initialization messages",
                ]
            )
        else:
            banner_lines.extend(
                [
                    "",
                    " Worker Configuration:",
                    f"   Single process mode (no additional workers)",
                ]
            )

        # Add Git information if available
        if build_info.get("git_commit"):
            banner_lines.append(f"   Git Commit: {build_info['git_commit']}")

        # Add configuration details
        db_uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", "not configured"))
        banner_lines.extend(
            [
                "",
                "  Configuration:",
                f"   Database: {db_uri[:50]}...",
                f"   Max Worker Threads: {app.config.get('MAX_WORKER_THREADS', 'not set')}",
                f"   Max Concurrent Streams: {app.config.get('MAX_CONCURRENT_STREAMS', 'not set')}",
                f"   Log Level: {app.config.get('LOG_LEVEL', 'not set')}",
                f"   Log Directory: {app.config.get('LOG_DIR', 'not set')}",
            ]
        )

        # Add timestamp
        banner_lines.extend(
            [
                "",
                f" Started at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "=" * 80,
                "",
            ]
        )

        # Log each line
        for line in banner_lines:
            app.logger.info(line)

    except Exception as e:
        app.logger.error(f"Failed to log primary startup banner: {e}")
        # Fallback to basic logging
        app.logger.info(f"TrakBridge Primary Process starting - Version: {get_version()}")
        if worker_count:
            app.logger.info(f"Starting with {worker_count} worker processes")


def log_worker_initialization(app, worker_pid: Optional[int] = None):
    """
    Log minimal worker initialization message.

    Args:
        app: Flask application instance
        worker_pid: Process ID of the worker (defaults to current PID)
    """
    if worker_pid is None:
        worker_pid = os.getpid()

    try:
        from services.version import get_version

        app.logger.info(
            f"Worker process initialized - PID: {worker_pid} - Version: {get_version()}"
        )
    except Exception as e:
        app.logger.info(f"Worker process initialized - PID: {worker_pid} - Version: unknown")
