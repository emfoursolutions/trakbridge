"""
TAK Stream Management System - Main Application Entry Point

Main Flask application factory providing multi-threaded stream management,
TAK server integration, and plugin architecture for data processing workflows.

Features: Application factory pattern, stream lifecycle management, database
integration, plugin system, encryption services, and production-ready deployment.

Author: Emfour Solutions
Created: 18-Jul-2025
License: GNU General Public License v3.0 (GPLv3)
"""

# Standard library imports
import atexit
from datetime import datetime as dt
import fcntl  # Add this import
import logging
import os
import signal
import tempfile  # Add this import
import threading
import time
from pathlib import Path  # Add this import
from typing import Optional

# Third-party imports
from dotenv import load_dotenv
from flask import Flask, has_app_context, render_template, jsonify
from flask_migrate import Migrate
from sqlalchemy import event, inspect
from sqlalchemy.pool import Pool

# Local application imports
from config.environments import get_config
from database import db
from services.cli.version_commands import register_version_commands
from services.logging_service import log_startup_banner, setup_logging
from services.stream_manager import StreamManager
from services.version import get_version, is_development_build

# Initialize extensions
migrate = Migrate()

# Global reference to stream manager for cleanup
_stream_manager_ref: Optional["StreamManager"] = None

# Global reference for startup splash screen
_startup_complete = False
_startup_error = None
_startup_progress = []

# Global flags to prevent duplicate startup - UPDATED
_startup_banner_logged = False
_startup_thread_started = False
_is_primary_process = None

# Lock for thread safety
_startup_lock = threading.Lock()

load_dotenv()

# Set up logger
logger = logging.getLogger("main")


def set_startup_complete(success=True, error=None):
    """Mark startup as complete"""
    global _startup_complete, _startup_error
    _startup_complete = True
    _startup_error = error if not success else None


def add_startup_progress(message):
    """Add a progress message to startup log"""
    global _startup_progress
    _startup_progress.append({"timestamp": dt.now().isoformat(), "message": message})
    # Keep only last 20 messages
    if len(_startup_progress) > 20:
        _startup_progress = _startup_progress[-20:]


def get_startup_status():
    """Get current startup status"""
    return {
        "complete": _startup_complete,
        "error": _startup_error,
        "progress": _startup_progress,
    }


def initialize_database_safely():
    """
    Initialize database with proper migration handling.
    Handles both first-time setup and existing installations without conflicts.
    """
    from flask_migrate import current, stamp, upgrade
    import os

    try:
        # Check if migrations directory exists
        migrations_dir = os.path.join(os.getcwd(), 'migrations')
        if not os.path.exists(migrations_dir):
            logger.info("No migrations directory found - creating database tables directly")
            db.create_all()
            return

        # Check if database has migration version tracking
        try:
            current_revision = current()

            if current_revision is None:
                # Database exists but no migration version tracked
                inspector = db.inspect(db.engine)
                existing_tables = inspector.get_table_names()

                if existing_tables:
                    logger.info(f"Found existing tables: {existing_tables}")
                    # Stamp database with current migration version (don't run migrations)
                    try:
                        stamp()
                        logger.info("Database stamped with current migration version")
                    except Exception as stamp_error:
                        logger.warning(f"Could not stamp database: {stamp_error}")
                        logger.info("Database tables already exist, skipping creation")
                else:
                    # No tables exist - run migrations
                    logger.info("No tables found - running initial migration")
                    upgrade()
            else:
                # Database is under migration control - run upgrade if needed
                logger.info(f"Current migration revision: {current_revision}")
                logger.info("Running database upgrade (if needed)...")
                upgrade()

        except Exception as migration_error:
            logger.warning(f"Migration system not available: {migration_error}")
            # Fall back to direct table creation only if no tables exist
            try:
                inspector = db.inspect(db.engine)
                existing_tables = inspector.get_table_names()

                if not existing_tables:
                    logger.info("No tables found and migrations unavailable - creating tables directly")
                    db.create_all()
                else:
                    logger.info("Tables exist, skipping database initialization")

            except Exception as fallback_error:
                logger.error(f"Could not inspect database or create tables: {fallback_error}")
                raise

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

def is_primary_process() -> bool:
    """
    Determine if this is the primary process that should handle full startup logging.
    Uses file-based coordination with proper locking.
    """
    global _is_primary_process

    if _is_primary_process is not None:
        return _is_primary_process

    # Create a lock file in the system temp directory
    lock_file_path = Path(tempfile.gettempdir()) / "trakbridge_startup.lock"

    try:
        # Try to create and lock the file
        lock_file = open(lock_file_path, "w")

        try:
            # Try to acquire exclusive lock (non-blocking)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Write our PID to the lock file
            lock_file.write(f"{os.getpid()}\n{time.time()}\n")
            lock_file.flush()

            # We got the lock - we're the primary process
            _is_primary_process = True

            # Register cleanup on exit
            atexit.register(
                lambda: cleanup_startup_coordination(lock_file, lock_file_path)
            )

            return True

        except (IOError, OSError):
            # Lock is already held by another process
            lock_file.close()
            _is_primary_process = False
            return False

    except (IOError, OSError):
        # Couldn't create lock file - default to simple logging
        logger.warning("Could not create startup coordination lock file")
        _is_primary_process = False
        return False


def cleanup_startup_coordination(lock_file=None, lock_file_path=None):
    """Clean up startup coordination resources"""
    try:
        if lock_file:
            lock_file.close()
        if lock_file_path and lock_file_path.exists():
            lock_file_path.unlink()
    except Exception as e:
        logger.debug(f"Error during startup coordination cleanup: {e}")


def log_full_startup_info(app):
    """Log comprehensive startup information for the primary process"""
    try:
        from services.version import (
            format_version,
            get_version_info,
            get_build_info,
        )

        # Log startup banner
        log_startup_banner(app)

        # Log detailed version information
        version_info = get_version_info()
        build_info = get_build_info()

        app.logger.info("=" * 60)
        app.logger.info("VERSION INFORMATION")
        app.logger.info("=" * 60)
        app.logger.info(f"Application: {format_version(include_build_info=True)}")
        app.logger.info(f"Version: {version_info.get('version', 'unknown')}")
        app.logger.info(f"Version Source: {version_info.get('source', 'unknown')}")
        app.logger.info(
            f"Development Build: {'YES' if is_development_build() else 'NO'}"
        )

        if build_info.get("git_commit"):
            app.logger.info(f"Git Commit: {build_info['git_commit']}")

        app.logger.info(
            f"Python Version: {version_info.get('python_version', 'unknown')}"
        )
        app.logger.info(f"Platform: {version_info.get('platform', 'unknown')}")
        app.logger.info(f"Process ID: {os.getpid()}")
        app.logger.info(f"Working Directory: {os.getcwd()}")
        app.logger.info("=" * 60)

    except Exception as e:
        app.logger.warning(f"Could not log detailed version info: {e}")
        # Fallback to basic logging
        try:
            from services.version import format_version

            app.logger.info(f"Starting {format_version(include_build_info=True)}")
        except Exception as fallback_e:
            app.logger.warning(f"Could not log even basic version info: {fallback_e}")


def log_simple_worker_init(app):
    """Log simple initialization message for worker processes"""
    try:
        from services.version import format_version

        app.logger.info(f"Worker process initialized - PID: {os.getpid()}")
        app.logger.debug(f"Application: {format_version(include_build_info=False)}")
    except Exception as e:
        app.logger.info(f"Worker process initialized - PID: {os.getpid()}")
        app.logger.debug(f"Could not log version info: {e}")


def should_run_delayed_startup() -> bool:
    """
    Determine if this process should run the delayed startup tasks.
    Uses a separate coordination mechanism from the logging.
    """
    startup_task_file = Path(tempfile.gettempdir()) / "trakbridge_startup_tasks.lock"

    try:
        # Try to create and lock the file
        with open(startup_task_file, "w") as f:
            try:
                # Try to acquire exclusive lock (non-blocking)
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Write our PID and timestamp
                f.write(f"{os.getpid()}\n{time.time()}\n")
                f.flush()

                # We got the lock - we should run startup tasks
                return True

            except (IOError, OSError):
                # Lock is already held by another process
                return False

    except (IOError, OSError):
        # Couldn't create lock file - default to not running
        logger.warning("Could not create startup tasks coordination lock file")
        return False


def cleanup_all_startup_resources():
    """Clean up all startup coordination resources"""
    temp_dir = Path(tempfile.gettempdir())
    lock_files = ["trakbridge_startup.lock", "trakbridge_startup_tasks.lock"]

    for lock_file in lock_files:
        lock_path = temp_dir / lock_file
        try:
            if lock_path.exists():
                lock_path.unlink()
        except OSError:
            pass  # Ignore cleanup errors


def create_app(config_name=None):
    global _stream_manager_ref

    app = Flask(__name__)

    def app_context_factory():
        return app.app_context()

    # Store the factory on the app for easy access
    app.app_context_factory = app_context_factory

    # Determine environment and get configuration
    flask_env = config_name or os.environ.get("FLASK_ENV", "development")
    app.config['SKIP_DB_INIT'] = os.environ.get('SKIP_DB_INIT', 'false').lower() == 'true'

    # Get configuration instance using the new system
    config_instance = get_config(flask_env)

    # Configure Flask app with the new configuration system
    configure_flask_app(app, config_instance)

    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)

    # Configure scoped sessions for thread safety
    with app.app_context():
        # Make sessions thread-local
        # db.session = scoped_session(db.session)

        # Import models AFTER db.init_app to avoid circular imports
        # Import them individually rather than through the __init__.py
        from models.tak_server import TakServer
        from models.stream import Stream

        # Register models with SQLAlchemy
        db.Model.metadata.create_all(bind=db.engine)

        # Initialize stream manager and attach to Flask app
        from services.stream_manager import StreamManager

        app.stream_manager = StreamManager(app_context_factory=app_context_factory)

        # Initialize plugin manager and attach to Flask app
        from plugins.plugin_manager import PluginManager

        app.plugin_manager = PluginManager()
        app.plugin_manager.load_plugins_from_directory()
        app.plugin_manager.load_external_plugins()

        # Initialize encryption service and attach to Flask app
        from services.encryption_service import EncryptionService

        app.encryption_service = EncryptionService()

        # Store global reference for cleanup
        _stream_manager_ref = app.stream_manager

    # Set up database event listeners
    setup_database_events()

    # Set up logging (only once per app instance)
    setup_logging(app)

    # Add version context processor (only once per app instance)
    setup_version_context_processor(app)

    # Register cleanup handlers
    setup_cleanup_handlers()

    # Register version CLI commands
    register_version_commands(app)

    # Register blueprints
    from routes.main import bp as main_bp
    from routes.streams import bp as streams_bp
    from routes.tak_servers import bp as tak_servers_bp
    from routes.admin import bp as admin_bp
    from routes.api import bp as api_bp
    from routes.cot_types import bp as cot_types_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(streams_bp, url_prefix="/streams")
    app.register_blueprint(tak_servers_bp, url_prefix="/tak-servers")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(cot_types_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")

    # Add context processors and error handlers
    setup_template_helpers(app)
    setup_error_handlers(app)

    # Splash screen routes
    setup_startup_routes(app)

    return app


def setup_version_context_processor(app):
    """Set up version context processor with proper process coordination."""
    global _startup_banner_logged

    with _startup_lock:
        # Only log startup banner once per process
        if not _startup_banner_logged:
            _startup_banner_logged = True

            # Check if we're the primary process
            if is_primary_process():
                log_full_startup_info(app)
            else:
                log_simple_worker_init(app)

    @app.context_processor
    def inject_version_info():
        """Inject version information into all templates."""
        try:
            from services.version import get_version_info, get_build_info

            version_info = get_version_info()
            build_info = get_build_info()

            # Create a simplified version object for templates
            app_version = {
                "version": version_info.get("version", "0.0.0"),
                "is_development": is_development_build(),
                "git_commit": version_info.get("git", {}).get("commit_short"),
                "python_version": (
                    f"{version_info['environment']['python_version_info'].major}."
                    f"{version_info['environment']['python_version_info'].minor}."
                    f"{version_info['environment']['python_version_info'].micro}"
                ),
                "platform": version_info.get("environment", {}).get(
                    "platform", "unknown"
                ),
                "source": version_info.get("source", "unknown"),
            }

            return dict(app_version=app_version)

        except Exception as e:
            # Fallback in case of any errors
            app.logger.warning(f"Failed to inject version info: {e}")
            return dict(
                app_version={
                    "version": "0.0.0",
                    "is_development": True,
                    "git_commit": None,
                    "python_version": "unknown",
                    "platform": "unknown",
                    "source": "error",
                }
            )

    @app.context_processor
    def inject_moment():
        """Inject moment function for date handling in templates."""

        class MomentWrapper:
            def format(self, fmt):
                return dt.now().strftime(fmt)

            def __call__(self):
                return self

        return dict(moment=MomentWrapper())


def configure_flask_app(app, config_instance):
    """Configure Flask app with the configuration system."""

    # Core Flask settings
    app.config["SECRET_KEY"] = config_instance.SECRET_KEY
    app.config["DEBUG"] = config_instance.DEBUG
    app.config["TESTING"] = config_instance.TESTING

    # SQLAlchemy settings
    app.config["SQLALCHEMY_DATABASE_URI"] = config_instance.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = (
        config_instance.SQLALCHEMY_TRACK_MODIFICATIONS
    )
    app.config["SQLALCHEMY_RECORD_QUERIES"] = config_instance.SQLALCHEMY_RECORD_QUERIES
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = config_instance.SQLALCHEMY_ENGINE_OPTIONS
    app.config["SQLALCHEMY_SESSION_OPTIONS"] = (
        config_instance.SQLALCHEMY_SESSION_OPTIONS
    )

    # Application-specific settings
    app.config["MAX_WORKER_THREADS"] = config_instance.MAX_WORKER_THREADS
    app.config["DEFAULT_POLL_INTERVAL"] = config_instance.DEFAULT_POLL_INTERVAL
    app.config["MAX_CONCURRENT_STREAMS"] = config_instance.MAX_CONCURRENT_STREAMS
    app.config["HTTP_TIMEOUT"] = config_instance.HTTP_TIMEOUT
    app.config["HTTP_MAX_CONNECTIONS"] = config_instance.HTTP_MAX_CONNECTIONS
    app.config["HTTP_MAX_CONNECTIONS_PER_HOST"] = (
        config_instance.HTTP_MAX_CONNECTIONS_PER_HOST
    )
    app.config["ASYNC_TIMEOUT"] = config_instance.ASYNC_TIMEOUT

    # Logging settings
    app.config["LOG_LEVEL"] = config_instance.LOG_LEVEL
    app.config["LOG_DIR"] = config_instance.LOG_DIR

    # Import Version
    app.config["VERSION"] = get_version()

    # Store the config instance for later use
    app.config_instance = config_instance

    # Log configuration info (only once)
    if not hasattr(configure_flask_app, "_config_logged"):
        configure_flask_app._config_logged = True
        logger.info(
            f"Configured Flask app for environment: {config_instance.environment}"
        )

        # Validate configuration
        issues = config_instance.validate_config()
        if issues:
            logger.warning(f"Configuration issues found: {issues}")


#            if config_instance.environment == "production":
#               raise ValueError(f"Configuration validation failed: {issues}")


def start_active_streams():
    """Start all active streams with enhanced logging and proper error handling."""
    from flask import current_app
    from services.version import get_version

    stream_manager = getattr(current_app, "stream_manager", None)
    if stream_manager is None:
        logger.error("Stream manager not initialized")
        add_startup_progress("Error: Stream manager not initialized")
        return

    from models.stream import Stream

    try:
        logger.info("Initializing stream startup process...")
        add_startup_progress("Initializing stream startup process...")

        # Wait for stream manager to be ready with longer timeout
        logger.info("Waiting for stream manager to be ready...")
        add_startup_progress("Waiting for stream manager to be ready...")
        max_wait = 200  # 20 seconds
        wait_count = 0

        while wait_count < max_wait:
            time.sleep(0.1)
            wait_count += 1
            if (
                hasattr(stream_manager, "_loop")
                and stream_manager.loop
                and stream_manager.loop.is_running()
                and hasattr(stream_manager, "session_manager")
                and stream_manager.session_manager
                and getattr(stream_manager.session_manager, "session", None)
            ):
                break

        if wait_count >= max_wait:
            logger.error("Stream manager not ready after extended wait")
            add_startup_progress("Error: Stream manager not ready after extended wait")
            return

        logger.info("Stream manager ready, fetching active streams")
        add_startup_progress("Stream manager ready, fetching active streams")

        # Fetch active streams with proper error handling
        try:
            active_streams = Stream.query.filter_by(is_active=True).all()
            logger.info(f"Found {len(active_streams)} active streams to start")
            add_startup_progress(f"Found {len(active_streams)} active streams to start")

            if active_streams:
                for stream in active_streams:
                    logger.info(
                        f"Stream {stream.id}: {stream.name} ({stream.plugin_type})"
                    )

        except Exception as db_e:
            logger.error(f"Failed to fetch active streams from database: {db_e}")
            add_startup_progress(
                f"Error: Failed to fetch active streams from database: {db_e}"
            )
            return

        if not active_streams:
            logger.info("No active streams found to start")
            add_startup_progress("No active streams found to start")
            return

        # Start streams with better logging
        started_count = 0
        failed_count = 0

        for stream in active_streams:
            try:
                logger.info(f"Starting stream {stream.id} ({stream.name})...")
                add_startup_progress(f"Starting stream {stream.id} ({stream.name})...")

                # Add retry logic
                max_retries = 3
                retry_count = 0
                success = False

                while retry_count < max_retries and not success:
                    try:
                        success = stream_manager.start_stream_sync(stream.id)
                        if success:
                            logger.info(
                                f"Successfully started stream {stream.id} ({stream.name})"
                            )
                            add_startup_progress(
                                f"✓ Successfully started stream {stream.id} ({stream.name})"
                            )
                            # Clear any previous error
                            fresh_stream = db.session.get(Stream, stream.id)
                            fresh_stream.last_error = None
                            db.session.commit()
                            started_count += 1
                            break
                        else:
                            retry_count += 1
                            if retry_count < max_retries:
                                logger.warning(
                                    f"Failed to start stream {stream.id}, retrying ({retry_count}/{max_retries})"
                                )
                                add_startup_progress(
                                    f"Failed to start stream {stream.id}, retrying ({retry_count}/{max_retries})"
                                )
                                time.sleep(2)
                            else:
                                logger.error(
                                    f"Failed to start stream {stream.id} after {max_retries} attempts"
                                )
                                add_startup_progress(
                                    f"✗ Failed to start stream {stream.id} after {max_retries} attempts"
                                )
                                failed_count += 1

                    except Exception as start_e:
                        retry_count += 1
                        if retry_count < max_retries:
                            logger.warning(
                                f"Exception starting stream {stream.id}, "
                                f"retrying ({retry_count}/{max_retries}): {start_e}"
                            )
                            add_startup_progress(
                                f"Exception starting stream {stream.id}, "
                                f"retrying ({retry_count}/{max_retries}): {start_e}"
                            )
                            time.sleep(2)
                        else:
                            logger.error(
                                f"Exception starting stream {stream.id} after {max_retries} attempts: {start_e}"
                            )
                            add_startup_progress(
                                f"✗ Exception starting stream {stream.id} after {max_retries} attempts: {start_e}"
                            )
                            failed_count += 1

                # Update stream status if failed
                if not success:
                    try:
                        fresh_stream = Stream.query.get(stream.id)
                        if fresh_stream:
                            fresh_stream.is_active = False
                            fresh_stream.last_error = (
                                "Failed to start during app startup"
                            )
                            db.session.commit()
                            logger.info(
                                f"Marked stream {stream.id} as inactive due to startup failure"
                            )
                    except Exception as db_e:
                        logger.error(
                            f"Failed to update stream {stream.id} status: {db_e}"
                        )
                        try:
                            db.session.rollback()
                        except Exception:
                            pass

                # Delay between starts
                time.sleep(3)

            except Exception as e:
                logger.error(
                    f"Unexpected error starting stream {stream.id}: {e}", exc_info=True
                )
                add_startup_progress(
                    f"✗ Unexpected error starting stream {stream.id}: {e}"
                )
                failed_count += 1

        # Log final results
        logger.info("=" * 50)
        logger.info("Stream Startup Results:")
        logger.info(f"Started: {started_count}")
        logger.info(f" Failed: {failed_count}")
        logger.info(f"  Total: {len(active_streams)}")
        logger.info(f"Success Rate: {(started_count / len(active_streams) * 100):.1f}%")
        logger.info("=" * 50)

        add_startup_progress(
            f"Stream startup complete: {started_count} started, {failed_count} failed"
        )

    except Exception as e:
        logger.error(f"Error in start_active_streams: {e}", exc_info=True)
        add_startup_progress(f"Error in start_active_streams: {e}")


def setup_database_events():
    """Set up database event listeners for better connection handling"""

    @event.listens_for(Pool, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """Set SQLite pragmas for better performance and concurrency"""
        if "sqlite" in str(dbapi_conn):
            cursor = dbapi_conn.cursor()
            # Enable WAL mode for better concurrency
            cursor.execute("PRAGMA journal_mode=WAL")
            # Set busy timeout to 30 seconds
            cursor.execute("PRAGMA busy_timeout=30000")
            # Enable foreign keys
            cursor.execute("PRAGMA foreign_keys=ON")
            # Set synchronous mode for better performance
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    @event.listens_for(Pool, "checkout")
    def receive_checkout(dbapi_conn, connection_record, connection_proxy):
        """Log connection checkouts in debug mode"""
        logging.debug(f"Connection checked out: {id(dbapi_conn)}")

    @event.listens_for(Pool, "checkin")
    def receive_checkin(dbapi_conn, connection_record):
        """Log connection checkins in debug mode"""
        logging.debug(f"Connection checked in: {id(dbapi_conn)}")


def setup_cleanup_handlers():
    """Set up cleanup handlers for graceful shutdown"""

    def cleanup():
        """Clean up resources on application shutdown"""
        global _stream_manager_ref

        try:
            # Use global reference instead of current_app
            if _stream_manager_ref is not None:
                try:
                    _stream_manager_ref.shutdown()
                    logger.info("Stream manager shutdown completed")
                except Exception as e:
                    logger.error(f"Error during stream manager shutdown: {e}")
            else:
                logger.info("No stream manager reference available for cleanup")

            # Close database connections
            try:
                db.session.remove()
                db.engine.dispose()
                logger.info("Database connections closed")
            except Exception as e:
                logger.error(f"Error closing database connections: {e}")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

        # Clean up startup coordination resources
        cleanup_all_startup_resources()

        logger.info("Application cleanup completed")

    def safe_stream_manager_shutdown():
        """Safely shutdown stream manager during application exit"""
        global _stream_manager_ref

        try:
            if _stream_manager_ref is not None:
                try:
                    _stream_manager_ref.shutdown()
                    logger.info("Stream manager shutdown completed via atexit")
                except Exception as e:
                    logger.error(f"Error during stream manager shutdown: {e}")
            else:
                logger.info("No stream manager reference available for atexit cleanup")
        except Exception as e:
            logger.error(f"Error during stream manager shutdown: {e}")

        # Clean up startup coordination resources
        cleanup_all_startup_resources()

    # Register cleanup handlers
    atexit.register(safe_stream_manager_shutdown)

    # For WSGI servers
    def cleanup_handler(signum, frame):
        cleanup()
        exit(0)

    signal.signal(signal.SIGTERM, cleanup_handler)
    signal.signal(signal.SIGINT, cleanup_handler)


def setup_template_helpers(app):
    """Add context processors for templates"""

    @app.context_processor
    def utility_processor():
        """Add utility functions to template context"""
        return dict(enumerate=enumerate, len=len, str=str)


def setup_error_handlers(app):
    """Set up error handlers"""

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    @app.errorhandler(503)
    def service_unavailable_error(error):
        db.session.rollback()
        return render_template("errors/503.html"), 503

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Handle uncaught exceptions"""
        logging.error(f"Unhandled exception: {e}", exc_info=True)
        db.session.rollback()

        if app.debug:
            raise e

        return render_template("errors/500.html"), 500


def setup_startup_routes(app):
    """Set up startup-related routes"""

    @app.route("/startup-status")
    def startup_status():
        """API endpoint to check startup status"""
        return jsonify(get_startup_status())

    @app.route("/startup")
    def startup_page():
        """Display startup/loading page"""
        return render_template("startup.html")

    @app.before_request
    def check_startup():
        """Check if startup is complete before processing requests"""
        from flask import request

        # Allow startup-related routes and static files
        if request.endpoint in ["startup_page", "startup_status", "static"]:
            return None

        # Allow API health checks
        if request.path.startswith("/api/health"):
            return None

        # Redirect to startup page if not ready
        if not _startup_complete and request.endpoint:
            if request.is_json:
                return (
                    jsonify(
                        {
                            "status": "starting",
                            "message": "Application is starting up",
                        }
                    ),
                    503,
                )
            else:
                return render_template("startup.html")

        return None


# Create the application instance
app = create_app()


# Delayed startup function that runs in a separate thread
def delayed_startup():
    """
    Run startup tasks after Flask is fully initialized.
    Only runs in the primary process to prevent duplicate execution.
    """
    global _startup_complete, _startup_error

    # Check if we should run startup tasks
    if not should_run_delayed_startup():
        logger.info("Delayed startup tasks will be handled by another process")
        return

    startup_start_time = dt.now()

    try:
        # Wait a bit for Flask to fully initialize
        add_startup_progress("Flask application initialized, starting services...")
        time.sleep(5)

        with app.app_context():
            logger.info("Running delayed startup tasks (PRIMARY PROCESS)...")
            add_startup_progress("Checking system components...")

            # Log system status
            try:
                logger.info("System Status Check:")
                logger.info(
                    f"Stream Manager: {'Ready' if hasattr(app, 'stream_manager') else 'Not Ready'}"
                )
                logger.info(
                    f"Plugin Manager: {'Ready' if hasattr(app, 'plugin_manager') else 'Not Ready'}"
                )
                logger.info(f"Database: {'Ready' if db.engine else 'Not Ready'}")
                logger.info(
                    f"Encryption Service: {'Ready' if hasattr(app, 'encryption_service') else 'Not Ready'}"
                )

                add_startup_progress("System components verified")
            except Exception as e:
                logger.warning(f"Could not log system status: {e}")
                add_startup_progress(
                    f"Warning: Could not verify all system components: {e}"
                )

            # Start active streams
            add_startup_progress("Starting active streams...")
            start_active_streams()

            # Calculate startup time
            startup_time = (dt.now() - startup_start_time).total_seconds()

            # Log startup completion
            logger.info("=" * 60)
            logger.info("TrakBridge Application Startup Complete!")
            logger.info(f"Total Startup Time: {startup_time:.2f} seconds")
            logger.info(f"Ready at: {dt.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 60)

            add_startup_progress(
                f"Startup complete! Ready in {startup_time:.2f} seconds"
            )
            set_startup_complete(True)

    except Exception as e:
        logger.error(f"Error during startup: {e}", exc_info=True)
        add_startup_progress(f"Startup failed: {str(e)}")
        set_startup_complete(False, str(e))


# Prevent duplicate startup thread creation
def ensure_startup_thread():
    """Ensure startup thread is only created once per process"""
    global _startup_thread_started

    with _startup_lock:
        if not _startup_thread_started:
            _startup_thread_started = True

            # Run startup in a separate thread to avoid blocking Flask initialization
            startup_thread = threading.Thread(
                target=delayed_startup, daemon=True, name=f"StartupThread-{os.getpid()}"
            )
            startup_thread.start()
            logger.info(f"Startup thread initiated for PID {os.getpid()}")


# Only start the startup thread if running directly or in production
if __name__ == "__main__":
    ensure_startup_thread()

    # Initialize database safely within app context
    with app.app_context():
        initialize_database_safely()

    app.run(debug=False, port=8080, threaded=True)
else:
    # For production/WSGI deployment
    ensure_startup_thread()
