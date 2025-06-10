# =============================================================================
# database.py - Database configuration and mixins
# =============================================================================

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Create the SQLAlchemy instance here
db = SQLAlchemy(session_options={"expire_on_commit": False})


class TimestampMixin:
    """Mixin to add created_at and updated_at timestamps to models"""
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

