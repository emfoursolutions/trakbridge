# =============================================================================
# app.py - Enhanced Flask Application with Fixed Startup for Gunicorn
# =============================================================================
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
import logging
import atexit
import asyncio
import threading
from sqlalchemy.orm import scoped_session
from sqlalchemy import event
from sqlalchemy.pool import Pool
import signal
import time
from dotenv import load_dotenv
import sys
import subprocess

# Import config system
from config.environments import get_config
from database import db  # Import db from database.py

# Initialize extensions
migrate = Migrate()

load_dotenv()

# Set up logger
logger = logging.getLogger(__name__)

# Global stream manager instance (will be initialized after app creation)
stream_manager = None


# Track if we're running under Gunicorn
def is_gunicorn():
    """Check if we're running under Gunicorn"""
    return "gunicorn" in os.environ.get("SERVER_SOFTWARE", "")


def is_main_worker():
    """Check if this is the main worker process"""
    # In Gunicorn, only start streams in the first worker
    worker_id = os.environ.get('GUNICORN_WORKER_ID', '0')
    return worker_id == '0' or worker_id == '1'  # First worker


def create_app(config_name=None):
    global stream_manager

    app = Flask(__name__)

    # Determine environment and get configuration
    flask_env = config_name or os.environ.get('FLASK_ENV', 'development')

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
        db.session = scoped_session(db.session)

        # Import models AFTER db.init_app to avoid circular imports
        from models.tak_server import TakServer
        from models.stream import Stream

        # Register models with SQLAlchemy
        db.Model.metadata.create_all(bind=db.engine)

        # Initialize stream manager after models are loaded
        if stream_manager is None:
            from services.stream_manager import get_stream_manager
            stream_manager = get_stream_manager()

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
    from routes.health import bp as health_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(streams_bp, url_prefix='/streams')
    app.register_blueprint(tak_servers_bp, url_prefix='/tak-servers')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(health_bp, url_prefix='/api')

    # Add context processors and error handlers
    setup_template_helpers(app)
    setup_error_handlers(app)

    # Set up proper initialization based on environment
    setup_worker_initialization(app)

    return app


def setup_worker_initialization(app):
    """Set up proper worker initialization for different environments"""

    @app.before_first_request
    def initialize_worker():
        """Initialize worker-specific resources"""
        global stream_manager

        logger.info(f"Initializing worker - PID: {os.getpid()}")

        # Ensure event loop is available for this worker
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("Event loop is closed")
        except RuntimeError:
            # Create new event loop for this worker
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            logger.info(f"Created new event loop for worker {os.getpid()}")

        # Initialize stream manager for this worker if needed
        if stream_manager and hasattr(stream_manager, 'ensure_worker_ready'):
            try:
                stream_manager.ensure_worker_ready()
                logger.info("Stream manager initialized for worker")
            except Exception as e:
                logger.error(f"Failed to initialize stream manager for worker: {e}")

        # Start streams only in development or in the main worker
        if not is_gunicorn() or is_main_worker():
            # Delay stream startup to ensure everything is ready
            startup_thread = threading.Thread(
                target=delayed_startup_worker_safe,
                daemon=True,
                name=f"StartupThread-{os.getpid()}"
            )
            startup_thread.start()
            logger.info("Started delayed stream startup thread")
        else:
            logger.info("Skipping stream startup - not main worker")


def delayed_startup_worker_safe():
    """Worker-safe delayed startup"""
    try:
        # Wait longer for Gunicorn workers to be fully ready
        delay = 10 if is_gunicorn() else 5
        logger.info(f"Waiting {delay}s before starting streams...")
        time.sleep(delay)

        # Use app context for database operations
        with app.app_context():
            logger.info("Running delayed startup tasks...")
            start_active_streams_safe()

    except Exception as e:
        logger.error(f"Error in delayed startup: {e}", exc_info=True)


def configure_flask_app(app, config_instance):
    """Configure Flask app with the new configuration system."""

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


def start_active_streams_safe():
    """Start all active streams with improved Gunicorn safety"""
    global stream_manager

    if stream_manager is None:
        logger.error("Stream manager not initialized")
        return

    from models.stream import Stream

    try:
        # Extended wait for stream manager readiness in Gunicorn
        logger.info("Waiting for stream manager to be ready...")
        max_wait = 300 if is_gunicorn() else 200  # Longer wait for Gunicorn
        wait_count = 0

        while wait_count < max_wait:
            try:
                # Check if stream manager is ready
                if (hasattr(stream_manager, '_loop') and
                        stream_manager._loop and
                        not stream_manager._loop.is_closed() and
                        hasattr(stream_manager, '_session_manager') and
                        stream_manager._session_manager):

                    # Additional check - try to get event loop
                    try:
                        current_loop = asyncio.get_event_loop()
                        if not current_loop.is_closed():
                            break
                    except RuntimeError:
                        # Create event loop if needed
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        logger.info("Created event loop during stream startup")
                        break

            except Exception as e:
                logger.debug(f"Stream manager not ready yet: {e}")

            time.sleep(0.1)
            wait_count += 1

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

        # Start streams with improved error handling for Gunicorn
        started_count = 0
        for stream in active_streams:
            try:
                logger.info(f"Starting stream {stream.id} ({stream.name})...")

                # Use the safer stream operations service if available
                success = False
                try:
                    # Try using the improved sync method
                    if hasattr(stream_manager, 'start_stream_sync'):
                        success = stream_manager.start_stream_sync(stream.id)
                    else:
                        # Fallback to async method with proper event loop handling
                        loop = asyncio.get_event_loop()
                        future = asyncio.run_coroutine_threadsafe(
                            stream_manager.start_stream(stream.id),
                            loop
                        )
                        success = future.result(timeout=60)  # Longer timeout for Gunicorn

                except Exception as start_e:
                    logger.error(f"Error starting stream {stream.id}: {start_e}")
                    success = False

                if success:
                    logger.info(f"Successfully started stream {stream.id} ({stream.name})")
                    try:
                        fresh_stream = db.session.get(Stream, stream.id)
                        if fresh_stream:
                            fresh_stream.last_error = None
                            db.session.commit()
                    except Exception as db_e:
                        logger.warning(f"Failed to clear error for stream {stream.id}: {db_e}")
                    started_count += 1
                else:
                    logger.error(f"Failed to start stream {stream.id}")
                    try:
                        fresh_stream = Stream.query.get(stream.id)
                        if fresh_stream:
                            fresh_stream.is_active = False
                            fresh_stream.last_error = "Failed to start during app startup"
                            db.session.commit()
                    except Exception as db_e:
                        logger.error(f"Failed to update stream {stream.id} status: {db_e}")

                # Longer delay between starts in Gunicorn
                time.sleep(5 if is_gunicorn() else 3)

            except Exception as e:
                logger.error(f"Unexpected error starting stream {stream.id}: {e}", exc_info=True)
                try:
                    fresh_stream = Stream.query.get(stream.id)
                    if fresh_stream:
                        fresh_stream.is_active = False
                        fresh_stream.last_error = f"Startup error: {str(e)}"
                        db.session.commit()
                except Exception as db_e:
                    logger.error(f"Failed to update stream {stream.id} status: {db_e}")

        logger.info(f"Startup complete: {started_count}/{len(active_streams)} streams started successfully")

    except Exception as e:
        logger.error(f"Error in start_active_streams_safe: {e}", exc_info=True)


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
        """Clean up resources on shutdown"""
        global stream_manager

        try:
            if stream_manager is not None:
                stream_manager.shutdown()
                logger.info("Stream manager shutdown completed")

        except Exception as e:
            logger.error(f"Error during stream cleanup: {e}")

        try:
            from routes.streams import cleanup_executor
            cleanup_executor()
        except ImportError:
            pass

        try:
            db.session.remove()
            db.engine.dispose()
        except:
            pass

        logger.info("Application cleanup completed")

    # Register cleanup for various shutdown scenarios
    atexit.register(cleanup)

    def safe_stream_manager_shutdown():
        global stream_manager
        if stream_manager is not None:
            stream_manager.shutdown()

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

if __name__ == '__main__':
    # Create tables within app context
    with app.app_context():
        db.create_all()

    app.run(debug=False, port=8080, threaded=True)