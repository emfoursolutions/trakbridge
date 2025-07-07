# Standard library imports
import atexit
import logging
import os
import signal
import threading
import time

# Third-party imports
import click
from dotenv import load_dotenv
from flask import Flask, has_app_context, render_template
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.pool import Pool

# Local application imports
from config.environments import get_config
from database import db

# Initialize extensions
migrate = Migrate()

load_dotenv()

# Set up logger
logger = logging.getLogger(__name__)


def create_app(config_name=None):
    app = Flask(__name__)

    def app_context_factory():
        return app.app_context()

    # Store the factory on the app for easy access
    app.app_context_factory = app_context_factory

    # Determine environment and get configuration
    flask_env = config_name or os.environ.get('FLASK_ENV', 'development')

    # Get configuration instance using the new system
    config_instance = get_config(flask_env)

    # Configure Flask app with the new configuration system
    configure_flask_app(app, config_instance)  # type: ignore[attr-defined]

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

        # Initialize encryption service and attach to Flask app
        from services.encryption_service import EncryptionService
        app.encryption_service = EncryptionService()

    # Set up database event listeners
    setup_database_events()

    # Set up logging
    setup_logging(app)

    # Register cleanup handlers
    setup_cleanup_handlers()

    # Register blueprints
    from routes.main import bp as main_bp
    from routes.streams import bp as streams_bp
    from routes.tak_servers import bp as tak_servers_bp
    from routes.admin import bp as admin_bp
    from routes.api import bp as api_bp
    from routes.cot_types import bp as cot_types_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(streams_bp, url_prefix='/streams')
    app.register_blueprint(tak_servers_bp, url_prefix='/tak-servers')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(cot_types_bp, url_prefix='/admin')
    app.register_blueprint(api_bp, url_prefix='/api')

    # Add context processors and error handlers
    setup_template_helpers(app)
    setup_error_handlers(app)

    return app


def configure_flask_app(app, config_instance):
    """Configure Flask app with the configuration system."""

    # Core Flask settings
    app.config['SECRET_KEY'] = config_instance.SECRET_KEY
    app.config['DEBUG'] = config_instance.DEBUG
    app.config['TESTING'] = config_instance.TESTING

    # SQLAlchemy settings
    app.config['SQLALCHEMY_DATABASE_URI'] = config_instance.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config_instance.SQLALCHEMY_TRACK_MODIFICATIONS
    app.config['SQLALCHEMY_RECORD_QUERIES'] = config_instance.SQLALCHEMY_RECORD_QUERIES
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = config_instance.SQLALCHEMY_ENGINE_OPTIONS
    app.config['SQLALCHEMY_SESSION_OPTIONS'] = config_instance.SQLALCHEMY_SESSION_OPTIONS

    # Application-specific settings
    app.config['MAX_WORKER_THREADS'] = config_instance.MAX_WORKER_THREADS
    app.config['DEFAULT_POLL_INTERVAL'] = config_instance.DEFAULT_POLL_INTERVAL
    app.config['MAX_CONCURRENT_STREAMS'] = config_instance.MAX_CONCURRENT_STREAMS
    app.config['HTTP_TIMEOUT'] = config_instance.HTTP_TIMEOUT
    app.config['HTTP_MAX_CONNECTIONS'] = config_instance.HTTP_MAX_CONNECTIONS
    app.config['HTTP_MAX_CONNECTIONS_PER_HOST'] = config_instance.HTTP_MAX_CONNECTIONS_PER_HOST
    app.config['ASYNC_TIMEOUT'] = config_instance.ASYNC_TIMEOUT

    # Logging settings
    app.config['LOG_LEVEL'] = config_instance.LOG_LEVEL
    app.config['LOG_DIR'] = config_instance.LOG_DIR

    # Store the config instance for later use
    app.config_instance = config_instance

    # Log configuration info
    logger.info(f"Configured Flask app for environment: {config_instance.environment}")

    # Validate configuration
    issues = config_instance.validate_config()
    if issues:
        logger.warning(f"Configuration issues found: {issues}")
        if config_instance.environment == 'production':
            raise ValueError(f"Configuration validation failed: {issues}")


def start_active_streams():
    """Start all active streams with proper error handling and timing"""
    from flask import current_app

    stream_manager = getattr(current_app, "stream_manager", None)

    if stream_manager is None:
        logger.error("Stream manager not initialized")
        return

    from models.stream import Stream

    try:
        # Wait for stream manager to be fully ready with longer timeout
        logger.info("Waiting for stream manager to be ready...")
        max_wait = 200  # 20 seconds - increased timeout
        wait_count = 0

        while wait_count < max_wait:
            time.sleep(0.1)
            wait_count += 1
            if (
                    hasattr(stream_manager, '_loop') and
                    stream_manager.loop and
                    stream_manager.loop.is_running() and
                    hasattr(stream_manager, 'session_manager') and
                    stream_manager.session_manager and
                    getattr(stream_manager.session_manager, 'session', None)
            ):
                break

        if wait_count >= max_wait:
            logger.error("Stream manager not ready after extended wait")
            return

        logger.info("Stream manager ready, fetching active streams")

        # Fetch active streams with proper error handling
        try:
            active_streams = Stream.query.filter_by(is_active=True).all()
            logger.info(f"Found {len(active_streams)} active streams to start")
        except Exception as db_e:
            logger.error(f"Failed to fetch active streams from database: {db_e}")
            return

        if not active_streams:
            logger.info("No active streams found to start")
            return

        # Start streams with longer delays and better error handling
        started_count = 0
        for stream in active_streams:
            try:
                logger.info(f"Starting stream {stream.id} ({stream.name})...")

                # Add longer timeout for startup and retry logic
                max_retries = 3
                retry_count = 0
                success = False

                while retry_count < max_retries and not success:
                    try:
                        success = stream_manager.start_stream_sync(stream.id)
                        if success:
                            logger.info(f"Successfully started stream {stream.id} ({stream.name})")
                            # Clear any previous error on successful start
                            fresh_stream = db.session.get(Stream, stream.id)
                            fresh_stream.last_error = None  # or "" if you prefer empty string
                            db.session.commit()
                            started_count += 1
                            break
                        else:
                            retry_count += 1
                            if retry_count < max_retries:
                                logger.warning(
                                    f"Failed to start stream {stream.id}, retrying ({retry_count}/{max_retries})")
                                time.sleep(2)  # Wait before retry
                            else:
                                logger.error(f"Failed to start stream {stream.id} after {max_retries} attempts")

                    except Exception as start_e:
                        retry_count += 1
                        if retry_count < max_retries:
                            logger.warning(
                                f"Exception starting stream {stream.id}, "
                                f"retrying ({retry_count}/{max_retries}): {start_e}"
                            )
                            time.sleep(2)
                        else:
                            logger.error(
                                f"Exception starting stream {stream.id} after {max_retries} attempts: {start_e}")
                            success = False

                # Update stream status if failed
                if not success:
                    try:
                        # Refresh the stream object to avoid session issues
                        fresh_stream = Stream.query.get(stream.id)
                        if fresh_stream:
                            fresh_stream.is_active = False
                            fresh_stream.last_error = "Failed to start during app startup"
                            db.session.commit()
                            logger.info(f"Marked stream {stream.id} as inactive due to startup failure")
                    except Exception as db_e:
                        logger.error(f"Failed to update stream {stream.id} status: {db_e}")
                        try:
                            db.session.rollback()
                        except Exception as rollback_e:
                            logger.error(
                                f"Failed to rollback session after error updating stream {stream.id}: {rollback_e}"
                            )

                # Longer delay between starts to prevent overwhelming
                time.sleep(3)

            except Exception as e:
                logger.error(f"Unexpected error starting stream {stream.id}: {e}", exc_info=True)
                # Mark stream as inactive
                try:
                    fresh_stream = Stream.query.get(stream.id)
                    if fresh_stream:
                        fresh_stream.is_active = False
                        fresh_stream.last_error = f"Startup error: {str(e)}"
                        db.session.commit()
                except Exception as db_e:
                    logger.error(f"Failed to update stream {stream.id} status: {db_e}")
                    try:
                        db.session.rollback()
                    except Exception as rollback_e:
                        logger.error(
                            f"Failed to rollback session after error updating stream {stream.id}: {rollback_e}"
                        )

        logger.info(f"Startup complete: {started_count}/{len(active_streams)} streams started successfully")

    except Exception as e:
        logger.error(f"Error in start_active_streams: {e}", exc_info=True)


def setup_database_events():
    """Set up database event listeners for better connection handling"""

    @event.listens_for(Pool, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """Set SQLite pragmas for better performance and concurrency"""
        if 'sqlite' in str(dbapi_conn):
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


def setup_logging(app):
    """Set up application logging"""

    # Create logs directory if it doesn't exist
    log_dir = app.config.get('LOG_DIR', 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Set up file handler
    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO'))

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(log_dir, 'app.log')),
            logging.StreamHandler()
        ]
    )

    # Set specific logger levels
    logging.getLogger('sqlalchemy.engine').setLevel(
        logging.INFO if app.config.get('SQLALCHEMY_RECORD_QUERIES') else logging.WARNING
    )
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)


def setup_cleanup_handlers():
    """Set up cleanup handlers for graceful shutdown"""

    def cleanup():
        """Clean up resources on application shutdown"""
        try:
            # Try to get current_app, but handle case where context is not available
            try:
                from flask import current_app
                stream_manager = getattr(current_app, "stream_manager", None)
                if hasattr(current_app, 'stream_manager') and stream_manager is not None:
                    current_app.stream_manager.shutdown()
                    logger.info("Stream manager shutdown completed")
            except RuntimeError as e:
                if "Working outside of application context" in str(e):
                    logger.debug("Application context not available during shutdown, skipping stream manager cleanup")
                else:
                    logger.error(f"Error during stream cleanup: {e}")
            except Exception as e:
                logger.error(f"Error during stream cleanup: {e}")

            # Close database connections
            try:
                db.session.remove()
                db.engine.dispose()
                logger.info("Database connections closed")
            except Exception as e:
                logger.error(f"Error closing database connections: {e}")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

        logger.info("Application cleanup completed")

    def safe_stream_manager_shutdown():
        """Safely shutdown stream manager during application exit"""
        try:
            # Try to get current_app, but handle case where context is not available
            try:
                from flask import current_app
                stream_manager = getattr(current_app, "stream_manager", None)
                if hasattr(current_app, 'stream_manager') and stream_manager is not None:
                    current_app.stream_manager.shutdown()
            except RuntimeError as e:
                if "Working outside of application context" in str(e):
                    logger.info("Application context not available during shutdown, skipping stream manager shutdown")
                else:
                    logger.error(f"Error during stream manager shutdown: {e}")
            except Exception as e:
                logger.error(f"Error during stream manager shutdown: {e}")
        except Exception as e:
            logger.error(f"Error during stream manager shutdown: {e}")

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
        return dict(
            enumerate=enumerate,
            len=len,
            str=str
        )


def setup_error_handlers(app):
    """Set up error handlers"""

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500

    @app.errorhandler(503)
    def service_unavailable_error(error):
        db.session.rollback()
        return render_template('errors/503.html'), 503

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Handle uncaught exceptions"""
        logging.error(f"Unhandled exception: {e}", exc_info=True)
        db.session.rollback()

        if app.debug:
            raise e

        return render_template('errors/500.html'), 500


# Create the application instance
app = create_app()


# Delayed startup function that runs in a separate thread
def delayed_startup():
    """Run startup tasks after Flask is fully initialized"""
    # Wait a bit for Flask to fully initialize
    time.sleep(5)

    with app.app_context():
        logger.info("Running delayed startup tasks...")
        start_active_streams()


# Call start_active_streams ONCE during application startup
if __name__ == "__main__" or not hasattr(start_active_streams, '_called'):
    start_active_streams._called = True

    # Run startup in a separate thread to avoid blocking Flask initialization
    startup_thread = threading.Thread(target=delayed_startup, daemon=True, name="StartupThread")
    startup_thread.start()

if __name__ == '__main__':
    # Create tables within app context
    with app.app_context():
        db.create_all()

    app.run(debug=False, port=8080, threaded=True)

