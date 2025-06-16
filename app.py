# =============================================================================
# app.py - Enhanced Flask Application Optimized for Gunicorn
# =============================================================================
from flask import Flask, render_template, g
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
import multiprocessing

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

# Global flag to track if worker has been initialized
_worker_initialized = False

# Track startup state per worker
_startup_complete = False


def is_gunicorn():
    """Check if we're running under Gunicorn"""
    return (
            "gunicorn" in os.environ.get("SERVER_SOFTWARE", "") or
            "GUNICORN_WORKER_ID" in os.environ or
            hasattr(os, 'getppid') and 'gunicorn' in str(os.getppid())
    )


def get_worker_id():
    """Get the current worker ID"""
    # Try multiple methods to get worker ID
    worker_id = os.environ.get('GUNICORN_WORKER_ID')
    if worker_id:
        return int(worker_id)

    # Fallback: use process ID modulo for pseudo-worker-id
    return os.getpid() % 1000


def is_main_worker():
    """Check if this is the main worker process that should start streams"""
    if not is_gunicorn():
        return True  # In development, always start streams

    # In Gunicorn, only the first worker should start streams
    worker_id = get_worker_id()
    return worker_id == int(os.environ.get('GUNICORN_WORKER_ID', '1'))


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

    # Configure scoped sessions for thread safety - CRITICAL for Gunicorn
    with app.app_context():
        # Make sessions thread-local and worker-local
        db.session = scoped_session(db.session)

        # Import models AFTER db.init_app to avoid circular imports
        from models.tak_server import TakServer
        from models.stream import Stream

        # Register models with SQLAlchemy
        try:
            db.Model.metadata.create_all(bind=db.engine)
        except Exception as e:
            logger.warning(f"Could not create tables (may already exist): {e}")

        # Initialize stream manager after models are loaded
        if stream_manager is None:
            from services.stream_manager import get_stream_manager
            stream_manager = get_stream_manager()
            logger.info(f"Stream manager initialized in worker {get_worker_id()}")

    # Set up database event listeners
    setup_database_events()

    # Set up logging
    setup_logging(app)

    # Register cleanup handlers (Gunicorn-safe)
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

    # Set up modern Flask initialization (replaces @app.before_first_request)
    setup_modern_worker_initialization(app)

    logger.info(f"App created for worker {get_worker_id()}, Gunicorn: {is_gunicorn()}, Main worker: {is_main_worker()}")

    return app


def setup_modern_worker_initialization(app):
    """Set up modern Flask worker initialization using before_request"""

    @app.before_request
    def initialize_worker():
        """Initialize worker-specific resources (runs once per worker)"""
        global stream_manager, _worker_initialized

        # Only run once per worker
        if _worker_initialized:
            return

        _worker_initialized = True
        worker_id = get_worker_id()

        logger.info(f"Initializing worker {worker_id} - PID: {os.getpid()}")

        # Set up event loop for this worker
        setup_worker_event_loop()

        # Initialize stream manager for this worker
        if stream_manager and hasattr(stream_manager, 'ensure_worker_ready'):
            try:
                stream_manager.ensure_worker_ready()
                logger.info(f"Stream manager initialized for worker {worker_id}")
            except Exception as e:
                logger.error(f"Failed to initialize stream manager for worker {worker_id}: {e}")

        # Only start streams in the designated main worker
        if is_main_worker():
            logger.info(f"Worker {worker_id} is main worker - will start streams")
            # Use a longer delay for Gunicorn to ensure all workers are ready
            delay = 15 if is_gunicorn() else 5

            # Use threading.Timer for delayed startup
            startup_timer = threading.Timer(
                delay,
                lambda: start_streams_in_background(app)
            )
            startup_timer.daemon = True
            startup_timer.start()

            logger.info(f"Scheduled stream startup in {delay}s for worker {worker_id}")
        else:
            logger.info(f"Worker {worker_id} is not main worker - skipping stream startup")


def setup_worker_event_loop():
    """Set up event loop for worker process"""
    try:
        # Try to get existing event loop
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Event loop is closed")
        logger.debug(f"Using existing event loop in worker {get_worker_id()}")
    except RuntimeError:
        # Create new event loop for this worker
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            logger.info(f"Created new event loop for worker {get_worker_id()}")
        except Exception as e:
            logger.error(f"Failed to create event loop for worker {get_worker_id()}: {e}")


def start_streams_in_background(app):
    """Start streams in background thread with proper context"""

    def startup_worker():
        try:
            with app.app_context():
                logger.info(f"Starting stream startup process in worker {get_worker_id()}")
                start_active_streams_gunicorn_safe()
        except Exception as e:
            logger.error(f"Error in background stream startup: {e}", exc_info=True)

    # Create background thread for stream startup
    startup_thread = threading.Thread(
        target=startup_worker,
        name=f"StreamStartup-Worker-{get_worker_id()}",
        daemon=True
    )
    startup_thread.start()


def start_active_streams_gunicorn_safe():
    """Start all active streams with Gunicorn-specific optimizations"""
    global stream_manager, _startup_complete

    if _startup_complete:
        logger.info("Stream startup already completed")
        return

    if stream_manager is None:
        logger.error("Stream manager not initialized")
        return

    from models.stream import Stream

    try:
        worker_id = get_worker_id()
        logger.info(f"Worker {worker_id}: Waiting for stream manager readiness...")

        # Extended wait for Gunicorn workers
        max_wait_seconds = 60
        wait_interval = 0.5
        max_iterations = int(max_wait_seconds / wait_interval)

        for i in range(max_iterations):
            try:
                # Check multiple readiness conditions
                if (hasattr(stream_manager, '_loop') and
                        stream_manager._loop and
                        not stream_manager._loop.is_closed()):

                    # Try to access the event loop
                    try:
                        current_loop = asyncio.get_event_loop()
                        if not current_loop.is_closed():
                            logger.info(f"Worker {worker_id}: Stream manager ready after {i * wait_interval:.1f}s")
                            break
                    except RuntimeError:
                        # Create event loop if needed
                        setup_worker_event_loop()
                        break

            except Exception as e:
                logger.debug(f"Worker {worker_id}: Stream manager not ready (attempt {i + 1}): {e}")

            time.sleep(wait_interval)
        else:
            logger.error(f"Worker {worker_id}: Stream manager not ready after {max_wait_seconds}s")
            return

        logger.info(f"Worker {worker_id}: Fetching active streams...")

        # Fetch active streams with retry logic
        active_streams = None
        for attempt in range(3):
            try:
                active_streams = db.session.query(Stream).filter_by(is_active=True).all()
                logger.info(f"Worker {worker_id}: Found {len(active_streams)} active streams")
                break
            except Exception as db_e:
                logger.warning(f"Worker {worker_id}: DB attempt {attempt + 1} failed: {db_e}")
                if attempt < 2:
                    time.sleep(2)
                    # Try to refresh the session
                    try:
                        db.session.rollback()
                    except:
                        pass
                else:
                    logger.error(f"Worker {worker_id}: Failed to fetch streams after 3 attempts")
                    return

        if not active_streams:
            logger.info(f"Worker {worker_id}: No active streams to start")
            _startup_complete = True
            return

        # Start streams with Gunicorn-optimized settings
        started_count = 0
        failed_count = 0

        for stream in active_streams:
            try:
                logger.info(f"Worker {worker_id}: Starting stream {stream.id} ({stream.name})...")

                success = False
                try:
                    # Prefer sync method if available
                    if hasattr(stream_manager, 'start_stream_sync'):
                        success = stream_manager.start_stream_sync(stream.id)
                    else:
                        # Use async method with proper timeout for Gunicorn
                        loop = asyncio.get_event_loop()
                        future = asyncio.run_coroutine_threadsafe(
                            stream_manager.start_stream(stream.id),
                            loop
                        )
                        # Longer timeout for Gunicorn workers
                        success = future.result(timeout=120)

                except asyncio.TimeoutError:
                    logger.error(f"Worker {worker_id}: Timeout starting stream {stream.id}")
                    success = False
                except Exception as start_e:
                    logger.error(f"Worker {worker_id}: Error starting stream {stream.id}: {start_e}")
                    success = False

                # Update stream status
                try:
                    fresh_stream = db.session.get(Stream, stream.id)
                    if fresh_stream:
                        if success:
                            fresh_stream.last_error = None
                            started_count += 1
                            logger.info(f"Worker {worker_id}: Successfully started stream {stream.id}")
                        else:
                            fresh_stream.is_active = False
                            fresh_stream.last_error = "Failed to start during app startup"
                            failed_count += 1
                            logger.error(f"Worker {worker_id}: Failed to start stream {stream.id}")

                        db.session.commit()
                except Exception as db_e:
                    logger.warning(f"Worker {worker_id}: Failed to update stream {stream.id} status: {db_e}")

                # Longer delay between starts for Gunicorn stability
                time.sleep(8 if is_gunicorn() else 3)

            except Exception as e:
                failed_count += 1
                logger.error(f"Worker {worker_id}: Unexpected error with stream {stream.id}: {e}", exc_info=True)

                try:
                    fresh_stream = db.session.get(Stream, stream.id)
                    if fresh_stream:
                        fresh_stream.is_active = False
                        fresh_stream.last_error = f"Startup error: {str(e)}"
                        db.session.commit()
                except Exception as db_e:
                    logger.error(f"Worker {worker_id}: Failed to update stream {stream.id} error: {db_e}")

        _startup_complete = True
        logger.info(f"Worker {worker_id}: Startup complete - {started_count} started, {failed_count} failed")

    except Exception as e:
        logger.error(f"Worker {get_worker_id()}: Critical error in stream startup: {e}", exc_info=True)


def configure_flask_app(app, config_instance):
    """Configure Flask app with the new configuration system."""

    # Core Flask settings
    app.config['SECRET_KEY'] = config_instance.SECRET_KEY
    app.config['DEBUG'] = config_instance.DEBUG
    app.config['TESTING'] = config_instance.TESTING

    # SQLAlchemy settings with Gunicorn optimizations
    app.config['SQLALCHEMY_DATABASE_URI'] = config_instance.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config_instance.SQLALCHEMY_TRACK_MODIFICATIONS
    app.config['SQLALCHEMY_RECORD_QUERIES'] = config_instance.SQLALCHEMY_RECORD_QUERIES

    # Enhanced engine options for Gunicorn
    engine_options = config_instance.SQLALCHEMY_ENGINE_OPTIONS.copy()
    if is_gunicorn():
        # Optimize for multiple workers
        engine_options.update({
            'pool_size': 5,  # Smaller pool per worker
            'max_overflow': 10,
            'pool_timeout': 30,
            'pool_recycle': 3600,  # Recycle connections hourly
            'pool_pre_ping': True,  # Validate connections
        })

    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
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
    logger.info(f"Configured Flask app for environment: {config_instance.environment} (Gunicorn: {is_gunicorn()})")

    # Validate configuration
    issues = config_instance.validate_config()
    if issues:
        logger.warning(f"Configuration issues found: {issues}")
        if config_instance.environment == 'production':
            raise ValueError(f"Configuration validation failed: {issues}")


def setup_database_events():
    """Set up database event listeners optimized for Gunicorn"""

    @event.listens_for(Pool, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """Set SQLite pragmas optimized for multi-worker environment"""
        if 'sqlite' in str(dbapi_conn):
            cursor = dbapi_conn.cursor()
            # WAL mode is critical for multiple workers
            cursor.execute("PRAGMA journal_mode=WAL")
            # Longer busy timeout for worker contention
            cursor.execute("PRAGMA busy_timeout=60000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            # Additional optimizations for Gunicorn
            if is_gunicorn():
                cursor.execute("PRAGMA cache_size=10000")  # Larger cache
                cursor.execute("PRAGMA temp_store=memory")  # Memory temp storage
            cursor.close()

    @event.listens_for(Pool, "checkout")
    def receive_checkout(dbapi_conn, connection_record, connection_proxy):
        """Log connection checkouts in debug mode"""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Worker {get_worker_id()}: Connection checked out: {id(dbapi_conn)}")

    @event.listens_for(Pool, "checkin")
    def receive_checkin(dbapi_conn, connection_record):
        """Log connection checkins in debug mode"""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Worker {get_worker_id()}: Connection checked in: {id(dbapi_conn)}")


def setup_logging(app):
    """Set up application logging optimized for Gunicorn"""

    # Create logs directory if it doesn't exist
    log_dir = app.config.get('LOG_DIR', 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Set up file handler with worker ID in filename for Gunicorn
    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO'))

    # Different log file per worker in Gunicorn
    if is_gunicorn():
        log_filename = f'app-worker-{get_worker_id()}.log'
    else:
        log_filename = 'app.log'

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=f'%(asctime)s [%(levelname)s] Worker-{get_worker_id()} %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(log_dir, log_filename)),
            logging.StreamHandler()
        ]
    )

    # Set specific logger levels
    logging.getLogger('sqlalchemy.engine').setLevel(
        logging.INFO if app.config.get('SQLALCHEMY_RECORD_QUERIES') else logging.WARNING
    )
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)


def setup_cleanup_handlers():
    """Set up Gunicorn-safe cleanup handlers"""

    def cleanup():
        """Clean up resources on shutdown"""
        global stream_manager

        worker_id = get_worker_id()
        logger.info(f"Worker {worker_id}: Starting cleanup...")

        try:
            if stream_manager is not None:
                stream_manager.shutdown()
                logger.info(f"Worker {worker_id}: Stream manager shutdown completed")
        except Exception as e:
            logger.error(f"Worker {worker_id}: Error during stream cleanup: {e}")

        try:
            from routes.streams import cleanup_executor
            cleanup_executor()
        except ImportError:
            pass

        try:
            db.session.remove()
            db.engine.dispose()
            logger.info(f"Worker {worker_id}: Database cleanup completed")
        except Exception as e:
            logger.error(f"Worker {worker_id}: Database cleanup error: {e}")

        logger.info(f"Worker {worker_id}: Cleanup completed")

    # Register cleanup for various shutdown scenarios
    atexit.register(cleanup)

    # Gunicorn-safe signal handlers
    def cleanup_handler(signum, frame):
        logger.info(f"Worker {get_worker_id()}: Received signal {signum}")
        cleanup()
        sys.exit(0)

    # Only register signal handlers if we're in the main thread
    # Gunicorn workers should handle this properly
    try:
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, cleanup_handler)
            signal.signal(signal.SIGINT, cleanup_handler)
            logger.debug(f"Worker {get_worker_id()}: Signal handlers registered")
    except (ValueError, OSError) as e:
        # Will fail if not in main thread or if signals not supported
        logger.debug(f"Worker {get_worker_id()}: Signal handlers not registered: {e}")


def setup_template_helpers(app):
    """Add context processors for templates"""

    @app.context_processor
    def utility_processor():
        """Add utility functions to template context"""
        return dict(
            enumerate=enumerate,
            len=len,
            str=str,
            worker_id=get_worker_id()  # Add worker ID to templates
        )


def setup_error_handlers(app):
    """Set up error handlers"""

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        try:
            db.session.rollback()
        except Exception as e:
            logger.error(f"Error during rollback: {e}")
        return render_template('errors/500.html'), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Handle uncaught exceptions"""
        worker_id = get_worker_id()
        logger.error(f"Worker {worker_id}: Unhandled exception: {e}", exc_info=True)

        try:
            db.session.rollback()
        except Exception as rollback_e:
            logger.error(f"Worker {worker_id}: Error during rollback: {rollback_e}")

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