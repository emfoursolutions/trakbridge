"""
File: database.py

Description:
Core database configuration module that provides SQLAlchemy setup and common database mixins
for the streaming application. Establishes database connection settings and reusable model
components for consistent timestamp management across all database models.

Key features:
- SQLAlchemy instance configuration with session management
- TimestampMixin for automatic created_at and updated_at field handling
- Consistent UTC timestamp generation for all models
- Session configuration to prevent commit expiration issues
- Reusable database components for model inheritance

Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
from datetime import datetime

# Third-party imports
from flask_sqlalchemy import SQLAlchemy

# Create the SQLAlchemy instance here
db = SQLAlchemy(session_options={"expire_on_commit": False})


class TimestampMixin:
    """Mixin to add created_at and updated_at timestamps to models"""

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
