"""
File: config/__init__.py

Description:
    Package initialisation for the configuration system

Author: Emfour Solutions
Created: 2025-07-05
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import logging
import os

# Local application imports
from .environments import get_config

logger = logging.getLogger(__name__)

# Get the current environment
FLASK_ENV = os.environ.get("FLASK_ENV", "development")

# Create the configuration instance
try:
    Config = get_config(FLASK_ENV)
    logger.info(f"Loaded configuration for environment: {FLASK_ENV}")

    # Validate configuration
    issues = Config.validate_config()
    if issues:
        logger.warning(f"Configuration issues found: {issues}")
        if FLASK_ENV == "production":
            raise ValueError(f"Configuration validation failed: {issues}")

except Exception as e:
    logger.error(f"Failed to load configuration: {e}")
    # Fallback to development config
    from .environments import DevelopmentConfig

    Config = DevelopmentConfig()
    logger.warning("Using fallback development configuration")

# Export the configuration instance
__all__ = ["Config"]
