# This file makes the models directory a Python package
# and helps with import ordering

from app import db

# Import all models here to ensure they're registered with SQLAlchemy
from database import TimestampMixin
from .tak_server import TakServer
from .stream import Stream  # Assuming you have a Stream model

__all__ = ['db', 'TimestampMixin', 'TakServer', 'Stream']