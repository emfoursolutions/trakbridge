# =============================================================================
# models/database.py - Database Setup
# =============================================================================

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime

# Create database instance
db = SQLAlchemy()
migrate = Migrate()


class TimestampMixin:
    """Mixin to add created_at and updated_at timestamps to models"""
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

