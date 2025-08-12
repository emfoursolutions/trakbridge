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

# Local application imports
from services.version import (
    get_build_info,
    get_version,
    get_version_info,
    is_development_build,
)

logger = logging.getLogger(__name__)


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
    log_filename = 'trakbridge.log'
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

    app.logger.info(f"Enhanced logging configured - Version: {version}")


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
