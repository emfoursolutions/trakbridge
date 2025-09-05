"""
File: config/monitor.py

Description:
    Loads the configuration monitor. Enables the dynamic reloading of configuration changes.

Author: Emfour Solutions
Created: 2025-07-05
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import logging
import os
import time
from pathlib import Path

# Third-party imports
from typing import Any, Callable, Dict, List, Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class ConfigFileHandler(FileSystemEventHandler):
    """Handle configuration file changes."""

    def __init__(self, config_monitor):
        self.config_monitor = config_monitor
        self.last_modified: Dict[str, float] = {}

    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return

        if not event.src_path.endswith((".yaml", ".yml", ".env")):
            return

        # Debounce rapid file changes
        current_time = time.time()
        if (
            event.src_path in self.last_modified
            and current_time - self.last_modified[event.src_path] < 1.0
        ):
            return

        self.last_modified[event.src_path] = current_time

        logger.info(f"Configuration file changed: {event.src_path}")
        self.config_monitor.reload_config()


class ConfigMonitor:
    """Monitor configuration files for changes and reload when needed."""

    def __init__(self, config_instance, config_dir: str = None):
        self.config_instance = config_instance
        self.config_dir = Path(config_dir) if config_dir else Path(__file__).parent / "settings"
        self.observer = None
        self.is_monitoring = False
        self.reload_callbacks: List[Callable] = []
        self.file_hashes: Dict[str, str] = {}

        # Validate config directory exists
        if not self.config_dir.exists():
            logger.warning(f"Configuration directory does not exist: {self.config_dir}")
            return

    def start_monitoring(self):
        """Start monitoring configuration files for changes."""
        if self.is_monitoring:
            logger.warning("Configuration monitoring is already running")
            return

        if not self.config_dir.exists():
            logger.error(
                f"Cannot start monitoring: config directory does not exist: {self.config_dir}"
            )
            return

        try:
            self.observer = Observer()
            event_handler = ConfigFileHandler(self)

            # Monitor the config directory
            self.observer.schedule(event_handler, str(self.config_dir), recursive=False)

            # Also monitor .env file if it exists
            env_file = Path(".env")
            if env_file.exists():
                self.observer.schedule(event_handler, str(env_file.parent), recursive=False)

            self.observer.start()
            self.is_monitoring = True

            logger.info(f"Started monitoring configuration files in: {self.config_dir}")

        except Exception as e:
            logger.error(f"Failed to start configuration monitoring: {e}")

    def stop_monitoring(self):
        """Stop monitoring configuration files."""
        if not self.is_monitoring or not self.observer:
            return

        try:
            self.observer.stop()
            self.observer.join()
            self.is_monitoring = False
            logger.info("Stopped configuration monitoring")
        except Exception as e:
            logger.error(f"Error stopping configuration monitoring: {e}")

    def add_reload_callback(self, callback: Callable):
        """Add a callback to be executed when configuration is reloaded."""
        self.reload_callbacks.append(callback)

    def remove_reload_callback(self, callback: Callable):
        """Remove a reload callback."""
        if callback in self.reload_callbacks:
            self.reload_callbacks.remove(callback)

    def reload_config(self):
        """Reload configuration and notify callbacks."""
        try:
            logger.info("Reloading configuration...")

            # Reload the configuration instance
            if hasattr(self.config_instance, "reload_config"):
                self.config_instance.reload_config()
            else:
                logger.warning("Configuration instance does not support reloading")
                return

            # Execute reload callbacks
            for callback in self.reload_callbacks:
                try:
                    callback(self.config_instance)
                except Exception as e:
                    logger.error(f"Error in configuration reload callback: {e}")

            logger.info("Configuration reload completed")

        except Exception as e:
            logger.error(f"Failed to reload configuration: {e}")

    def get_config_status(self) -> Dict[str, Any]:
        """Get the current status of configuration monitoring."""
        config_files = []

        if self.config_dir.exists():
            for file_path in self.config_dir.glob("*.yaml"):
                config_files.append(
                    {
                        "name": file_path.name,
                        "path": str(file_path),
                        "exists": file_path.exists(),
                        "size": file_path.stat().st_size if file_path.exists() else 0,
                        "modified": (file_path.stat().st_mtime if file_path.exists() else 0),
                    }
                )

        return {
            "is_monitoring": self.is_monitoring,
            "config_directory": str(self.config_dir),
            "config_files": config_files,
            "reload_callbacks_count": len(self.reload_callbacks),
        }


class ConfigHealthChecker:
    """Check the health and validity of configuration."""

    def __init__(self, config_instance):
        self.config_instance = config_instance

    def check_config_health(self) -> Dict[str, Any]:
        """Perform comprehensive configuration health check."""
        health_status = {
            "status": "healthy",
            "checks": {},
            "issues": [],
            "warnings": [],
        }

        # Check database configuration
        db_health = self._check_database_config()
        health_status["checks"]["database"] = db_health
        if db_health["status"] != "healthy":
            health_status["status"] = "unhealthy"
            health_status["issues"].extend(db_health["issues"])

        # Check application configuration
        app_health = self._check_app_config()
        health_status["checks"]["application"] = app_health
        if app_health["status"] != "healthy":
            health_status["status"] = "unhealthy"
            health_status["issues"].extend(app_health["issues"])

        # Check security configuration
        security_health = self._check_security_config()
        health_status["checks"]["security"] = security_health
        if security_health["status"] != "healthy":
            health_status["status"] = "unhealthy"
            health_status["issues"].extend(security_health["issues"])

        # Check logging configuration
        logging_health = self._check_logging_config()
        health_status["checks"]["logging"] = logging_health
        if logging_health["status"] != "healthy":
            health_status["status"] = "unhealthy"
            health_status["issues"].extend(logging_health["issues"])

        # Add warnings
        for check in health_status["checks"].values():
            health_status["warnings"].extend(check.get("warnings", []))

        return health_status

    def _check_database_config(self) -> Dict[str, Any]:
        """Check database configuration health."""
        health = {"status": "healthy", "issues": [], "warnings": []}

        try:
            db_uri = self.config_instance.SQLALCHEMY_DATABASE_URI
            if not db_uri:
                health["status"] = "unhealthy"
                health["issues"].append("Database URI is not configured")
                return health

            # Check if it's a file-based database
            if "sqlite" in db_uri and ":memory:" not in db_uri:
                db_path = db_uri.replace("sqlite:///", "")
                if db_path and not Path(db_path).parent.exists():
                    health["status"] = "unhealthy"
                    health["issues"].append(
                        f"Database directory does not exist: {Path(db_path).parent}"
                    )

            # Check engine options
            engine_options = self.config_instance.SQLALCHEMY_ENGINE_OPTIONS
            if engine_options:
                if engine_options.get("pool_size", 0) > 100:
                    health["warnings"].append("Database pool size is very large (>100)")

        except Exception as e:
            health["status"] = "unhealthy"
            health["issues"].append(f"Database configuration error: {e}")

        return health

    def _check_app_config(self) -> Dict[str, Any]:
        """Check application configuration health."""
        health = {"status": "healthy", "issues": [], "warnings": []}

        try:
            # Check worker threads
            max_workers = self.config_instance.MAX_WORKER_THREADS
            if max_workers < 1:
                health["status"] = "unhealthy"
                health["issues"].append("MAX_WORKER_THREADS must be at least 1")
            elif max_workers > 100:
                health["warnings"].append("MAX_WORKER_THREADS is very large (>100)")

            # Check concurrent streams
            max_streams = self.config_instance.MAX_CONCURRENT_STREAMS
            if max_streams < 1:
                health["status"] = "unhealthy"
                health["issues"].append("MAX_CONCURRENT_STREAMS must be at least 1")
            elif max_streams > 1000:
                health["warnings"].append("MAX_CONCURRENT_STREAMS is very large (>1000)")

            # Check timeouts
            timeouts = [
                ("HTTP_TIMEOUT", self.config_instance.HTTP_TIMEOUT),
                ("ASYNC_TIMEOUT", self.config_instance.ASYNC_TIMEOUT),
                ("DEFAULT_POLL_INTERVAL", self.config_instance.DEFAULT_POLL_INTERVAL),
            ]

            for name, value in timeouts:
                if value < 1:
                    health["status"] = "unhealthy"
                    health["issues"].append(f"{name} must be at least 1")
                elif value > 3600:
                    health["warnings"].append(f"{name} is very large (>1 hour)")

        except Exception as e:
            health["status"] = "unhealthy"
            health["issues"].append(f"Application configuration error: {e}")

        return health

    def _check_security_config(self) -> Dict[str, Any]:
        """Check security configuration health."""
        health = {"status": "healthy", "issues": [], "warnings": []}

        try:
            secret_key = self.config_instance.SECRET_KEY
            if not secret_key:
                health["status"] = "unhealthy"
                health["issues"].append("SECRET_KEY is required")
            elif len(secret_key) < 16:
                health["status"] = "unhealthy"
                health["issues"].append("SECRET_KEY must be at least 16 characters long")
            elif secret_key == "dev-secret-key-change-in-production":
                if self.config_instance.environment == "production":
                    health["status"] = "unhealthy"
                    health["issues"].append("SECRET_KEY must be changed from default in production")
                else:
                    health["warnings"].append("Using default SECRET_KEY - change for production")

        except Exception as e:
            health["status"] = "unhealthy"
            health["issues"].append(f"Security configuration error: {e}")

        return health

    def _check_logging_config(self) -> Dict[str, Any]:
        """Check logging configuration health."""
        health = {"status": "healthy", "issues": [], "warnings": []}

        try:
            log_level = self.config_instance.LOG_LEVEL
            valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            if log_level not in valid_levels:
                health["status"] = "unhealthy"
                health["issues"].append(f"LOG_LEVEL must be one of: {', '.join(valid_levels)}")

            log_dir = self.config_instance.LOG_DIR
            if log_dir:
                log_path = Path(log_dir)
                if not log_path.exists():
                    try:
                        log_path.mkdir(parents=True, exist_ok=True)
                    except Exception as e:
                        health["status"] = "unhealthy"
                        health["issues"].append(f"Cannot create log directory {log_dir}: {e}")
                elif not os.access(log_path, os.W_OK):
                    health["status"] = "unhealthy"
                    health["issues"].append(f"Log directory is not writable: {log_dir}")

        except Exception as e:
            health["status"] = "unhealthy"
            health["issues"].append(f"Logging configuration error: {e}")

        return health


def create_config_monitor(
    config_instance, enable_monitoring: bool = True
) -> Optional[ConfigMonitor]:
    """Create and optionally start a configuration monitor."""
    if not enable_monitoring:
        return None

    try:
        monitor = ConfigMonitor(config_instance)
        if enable_monitoring:
            monitor.start_monitoring()
        return monitor
    except Exception as e:
        logger.error(f"Failed to create configuration monitor: {e}")
        return None
