# =============================================================================
# app.py - Main Flask Application
# =============================================================================

from flask import Flask
from database import db, migrate
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # Import models AFTER db.init_app to avoid circular imports
    with app.app_context():
        # Import models here to register them with SQLAlchemy
        import models.tak_server
        import models.stream

    # Register blueprints AFTER models are imported
    from routes.main import bp as main_bp
    from routes.streams import bp as streams_bp
    from routes.tak_servers import bp as tak_servers_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(streams_bp, url_prefix='/streams')
    app.register_blueprint(tak_servers_bp, url_prefix='/tak-servers')

    return app


if __name__ == '__main__':
    app = create_app()

    # Create tables within app context
    with app.app_context():
        db.create_all()

    app.run(debug=True, port=8080)