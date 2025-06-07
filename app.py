# =============================================================================
# app.py - Enhanced Flask Application with Production Features
# =============================================================================

from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
import logging
import atexit
from sqlalchemy.orm import scoped_session
from sqlalchemy import event
from sqlalchemy.pool import Pool
import signal

# Import your config
from config import Config
from database import db  # Import db from database.py

# Initialize extensions
migrate = Migrate()


def create_app(config_name=None):
    app = Flask(__name__)

    # Determine config - you can extend this to support multiple environments
    if config_name:
        # If you have multiple config classes, handle them here
        app.config.from_object(Config)
    else:
        app.config.from_object(Config)

    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)

    # Configure scoped sessions for thread safety
    with app.app_context():
        # Make sessions thread-local
        db.session = scoped_session(db.session)

        # Import models AFTER db.init_app to avoid circular imports
        # Import them individually rather than through the __init__.py
        from models.tak_server import TakServer
        from models.stream import Stream

        # Register models with SQLAlchemy
        db.Model.metadata.create_all(bind=db.engine)

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

    app.register_blueprint(main_bp)
    app.register_blueprint(streams_bp, url_prefix='/streams')
    app.register_blueprint(tak_servers_bp, url_prefix='/tak-servers')

    # Add context processors and error handlers
    setup_template_helpers(app)
    setup_error_handlers(app)

    return app


def setup_database_events():
    """Set up database event listeners for better connection handling"""

    @event.listens_for(Pool, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """Set SQLite pragmas for better performance and concurrency"""
        if 'sqlite' in str(dbapi_conn):
            cursor = dbapi_conn.cursor()
            # Enable WAL mode for better concurrency
            cursor.execute("PRAGMA journal_mode=WAL")
            # Set busy timeout
            cursor.execute("PRAGMA busy_timeout=30000")
            # Enable foreign keys
            cursor.execute("PRAGMA foreign_keys=ON")
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
        try:
            # Clean up thread pool from streams module
            from routes.streams import cleanup_executor
            cleanup_executor()
        except ImportError:
            pass

        try:
            # Clean up database connections
            db.session.remove()
            db.engine.dispose()
        except:
            pass

        logging.info("Application cleanup completed")

    # Register cleanup for various shutdown scenarios
    atexit.register(cleanup)

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

    app.run(debug=True, port=8080, threaded=True)