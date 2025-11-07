"""
ABOUTME: Integration layer for COT service to use the new queue management system
ABOUTME: providing optimized performance while maintaining backward compatibility

File: services/cot_service_integration.py

Description:
    Integration layer that updates the COT service to use the new dedicated
    queue management and monitoring services. This provides better separation
    of concerns, improved performance monitoring, and enhanced queue operations
    while maintaining full backward compatibility.

Key features:
    - Integration with dedicated QueueManager service
    - Enhanced monitoring through QueueMonitoringService
    - Optimized batch transmission using queue manager
    - Configuration change detection and handling
    - Performance optimization while maintaining test compliance
    - Comprehensive logging and metrics collection

Author: TrakBridge Development Team
Created: 2025-09-17
"""

import asyncio
import logging
import os
import ssl
import tempfile
import yaml
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from lxml import etree
from services.logging_service import get_module_logger
from services.queue_manager import get_queue_manager, reset_queue_manager
from services.queue_monitoring import get_queue_monitoring_service
from services.device_state_manager import DeviceStateManager

# Cryptography imports for P12 certificate handling
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

# PyTAK imports
try:
    import pytak

    PYTAK_AVAILABLE = True
except ImportError:
    PYTAK_AVAILABLE = False
    # Note: logger not yet initialized at module level

logger = get_module_logger(__name__)


class QueuedCOTService:
    """
    COT service with advanced queue management.

    This class provides all the functionality of the original COT service
    but uses the new QueueManager and QueueMonitoringService for improved
    performance, monitoring, and maintainability.
    """

    _instance = None
    _workers: Dict[int, asyncio.Task] = {}  # Class-level worker tracking
    _connections: Dict[int, Any] = {}  # Class-level connection tracking

    def __init__(
        self,
        queue_config: Optional[Dict[str, Any]] = None,
        _bypass_singleton_check: bool = False,
    ):
        """
        Initialize queued COT service with queue management integration.

        Args:
            queue_config: Queue configuration dictionary
            _bypass_singleton_check: Internal parameter to bypass singleton enforcement
        """
        if not _bypass_singleton_check and QueuedCOTService._instance is not None:
            error_msg = (
                f"QueuedCOTService is a singleton. Use get_cot_service() instead of direct instantiation. "
                f"Existing instance: {id(QueuedCOTService._instance)}, attempted at {datetime.now()}"
            )
            logger.error(f"Singleton violation detected: {error_msg}")
            logger.debug(
                f"Singleton enforcement: existing_instance_id={id(QueuedCOTService._instance)}"
            )
            raise RuntimeError(error_msg)
        QueuedCOTService._instance = self

        # Use class-level attributes instead of instance attributes
        self.workers = QueuedCOTService._workers
        self.connections = QueuedCOTService._connections
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = True

        # Device state managers for queue replacement functionality
        self.device_state_managers: Dict[int, DeviceStateManager] = {}

        # Configuration tracking for change detection
        self.last_config_hash = None
        self.config_change_count = 0
        self.last_config_change_timestamp = None

        # Phase 1: Initialize performance configuration with defaults
        self.parallel_config = self._get_default_performance_config()
        self._load_performance_config()

        # Initialize queue management services after performance config is loaded
        # Extract queue configuration from performance config if not provided
        if queue_config is None:
            queue_config = self.parallel_config.get("queue", {})

        # Log configuration for debugging
        logger.info(f"COT Service initialising with queue config: {queue_config}")
        logger.debug(f"Full parallel config: {self.parallel_config}")

        # Reset the queue manager singleton to ensure fresh configuration
        reset_queue_manager()
        logger.debug("Reset queue manager singleton for fresh configuration")

        self.queue_manager = get_queue_manager(queue_config)
        self.monitoring_service = get_queue_monitoring_service()

        # Validate configuration was applied correctly
        actual_batch_size = self.queue_manager.config.get("batch_size", "not set")
        logger.info(f"QueueManager created with batch_size: {actual_batch_size}")

        logger.debug(f"COT Service singleton instance created at {datetime.now()}")
        logger.debug(
            f"Singleton instance tracking: _instance set to {id(self)} at {datetime.now()}"
        )
        logger.info("COT Service initialised with queue management integration")

        # Initialize fallback tracking for TDD tests
        self._fallback_stats = {
            "total_fallbacks": 0,
            "fallback_reasons": {},
            "fallback_rate": 0.0,
        }
        self._parallel_health_failures = 0
        self._parallel_health_successes = 0

        # Circuit breaker state
        self._circuit_breaker_failures = 0
        self._circuit_breaker_open = False
        self._circuit_breaker_open_time = None

    @property
    def queues(self):
        """
        Backward compatibility property to access queues.

        Returns:
            Dict[int, asyncio.Queue]: Dictionary of TAK server ID to queue mappings
        """
        return self.queue_manager.queues

    # Phase 1: Configuration methods extracted from EnhancedCOTService

    def _get_default_performance_config(self) -> Dict[str, Any]:
        """Get default performance configuration values"""
        return {
            "enabled": True,
            "batch_size_threshold": 10,
            "max_concurrent_tasks": 50,
            "fallback_on_error": True,
            "processing_timeout": 30.0,
            "enable_performance_logging": True,
            "circuit_breaker": {
                "enabled": True,
                "failure_threshold": 3,
                "recovery_timeout": 60.0,
            },
            # Phase 2: Queue management defaults
            "queue": {
                "max_size": 500,
                "batch_size": 20,  # Changed from 8 to 20 to match performance.yaml
                "overflow_strategy": "drop_oldest",
                "flush_on_config_change": True,
            },
            "transmission": {
                "batch_timeout_ms": 100,
                "queue_check_interval_ms": 100,
            },
            "monitoring": {
                "log_queue_stats": True,
                "queue_warning_threshold": 400,
            },
        }

    def get_config_file_search_paths(self) -> List[str]:
        """Get list of paths to search for configuration files"""
        return [
            "config/settings/performance.yaml",
            "/etc/trakbridge/performance.yaml",
            "~/.trakbridge/performance.yaml",
        ]

    def load_performance_config(
        self, config_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Load performance configuration from YAML file

        Args:
            config_path: Optional path to config file. If None, uses default paths.

        Returns:
            Configuration dictionary
        """
        if config_path:
            config_paths = [config_path]
        else:
            config_paths = self.get_config_file_search_paths()

        config = {}
        for path in config_paths:
            try:
                expanded_path = os.path.expanduser(path)
                if os.path.exists(expanded_path):
                    with open(expanded_path, "r") as f:
                        file_config = yaml.safe_load(f) or {}
                        if "parallel_processing" in file_config:
                            # Load the full configuration structure
                            config = file_config.copy()

                            logger.debug(
                                f"Loaded performance configuration from {expanded_path}"
                            )
                            break
                        elif (
                            file_config
                        ):  # File exists but no parallel_processing section
                            logger.warning(
                                f"Configuration file {expanded_path} missing 'parallel_processing' section"
                            )
            except Exception as e:
                logger.warning(f"Failed to load configuration from {path}: {e}")
                continue

        # If no config found, return the full structure expected by tests
        if not config:
            return {"parallel_processing": self._get_default_performance_config()}

        return config

    def load_performance_config_with_env_override(self) -> Dict[str, Any]:
        """Load configuration overrides from environment variables"""
        env_config = {}

        # Boolean environment variables
        if "TRAKBRIDGE_PARALLEL_ENABLED" in os.environ:
            env_config["enabled"] = (
                os.environ["TRAKBRIDGE_PARALLEL_ENABLED"].lower() == "true"
            )

        if "TRAKBRIDGE_FALLBACK_ON_ERROR" in os.environ:
            env_config["fallback_on_error"] = (
                os.environ["TRAKBRIDGE_FALLBACK_ON_ERROR"].lower() == "true"
            )

        # Numeric environment variables
        for env_var, config_key in [
            ("TRAKBRIDGE_BATCH_SIZE_THRESHOLD", "batch_size_threshold"),
            ("TRAKBRIDGE_MAX_CONCURRENT_TASKS", "max_concurrent_tasks"),
        ]:
            if env_var in os.environ:
                try:
                    env_config[config_key] = int(os.environ[env_var])
                except ValueError:
                    logger.warning(
                        f"Invalid value for {env_var}: {os.environ[env_var]}"
                    )

        # Phase 2: Queue configuration environment overrides
        queue_config = {}
        if "QUEUE_MAX_SIZE" in os.environ:
            try:
                queue_config["max_size"] = int(os.environ["QUEUE_MAX_SIZE"])
            except ValueError:
                logger.warning(
                    f"Invalid QUEUE_MAX_SIZE: {os.environ['QUEUE_MAX_SIZE']}"
                )

        if "QUEUE_BATCH_SIZE" in os.environ:
            try:
                queue_config["batch_size"] = int(os.environ["QUEUE_BATCH_SIZE"])
            except ValueError:
                logger.warning(
                    f"Invalid QUEUE_BATCH_SIZE: {os.environ['QUEUE_BATCH_SIZE']}"
                )

        if "QUEUE_OVERFLOW_STRATEGY" in os.environ:
            strategy = os.environ["QUEUE_OVERFLOW_STRATEGY"]
            if strategy in ["drop_oldest", "drop_newest", "block"]:
                queue_config["overflow_strategy"] = strategy
            else:
                logger.warning(f"Invalid QUEUE_OVERFLOW_STRATEGY: {strategy}")

        if "QUEUE_FLUSH_ON_CONFIG_CHANGE" in os.environ:
            queue_config["flush_on_config_change"] = (
                os.environ["QUEUE_FLUSH_ON_CONFIG_CHANGE"].lower() == "true"
            )

        if queue_config:
            env_config["queue"] = queue_config

        # Transmission configuration
        transmission_config = {}
        if "TRANSMISSION_BATCH_TIMEOUT_MS" in os.environ:
            try:
                transmission_config["batch_timeout_ms"] = int(
                    os.environ["TRANSMISSION_BATCH_TIMEOUT_MS"]
                )
            except ValueError:
                logger.warning(
                    f"Invalid TRANSMISSION_BATCH_TIMEOUT_MS: {os.environ['TRANSMISSION_BATCH_TIMEOUT_MS']}"
                )

        if "TRANSMISSION_QUEUE_CHECK_INTERVAL_MS" in os.environ:
            try:
                transmission_config["queue_check_interval_ms"] = int(
                    os.environ["TRANSMISSION_QUEUE_CHECK_INTERVAL_MS"]
                )
            except ValueError:
                logger.warning(
                    f"Invalid TRANSMISSION_QUEUE_CHECK_INTERVAL_MS: {os.environ['TRANSMISSION_QUEUE_CHECK_INTERVAL_MS']}"
                )

        if transmission_config:
            env_config["transmission"] = transmission_config

        # Monitoring configuration
        monitoring_config = {}
        if "MONITORING_LOG_QUEUE_STATS" in os.environ:
            monitoring_config["log_queue_stats"] = (
                os.environ["MONITORING_LOG_QUEUE_STATS"].lower() == "true"
            )

        if "MONITORING_QUEUE_WARNING_THRESHOLD" in os.environ:
            try:
                monitoring_config["queue_warning_threshold"] = int(
                    os.environ["MONITORING_QUEUE_WARNING_THRESHOLD"]
                )
            except ValueError:
                logger.warning(
                    f"Invalid MONITORING_QUEUE_WARNING_THRESHOLD: {os.environ['MONITORING_QUEUE_WARNING_THRESHOLD']}"
                )

        if monitoring_config:
            env_config["monitoring"] = monitoring_config

        return env_config

    def validate_performance_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and sanitize performance configuration

        Args:
            config: Raw configuration dictionary

        Returns:
            Validated configuration with defaults for missing values
        """
        defaults = self._get_default_performance_config()
        validated = {}

        # Validate boolean values
        for key in ["enabled", "fallback_on_error", "enable_performance_logging"]:
            value = config.get(key, defaults[key])
            validated[key] = (
                bool(value) if isinstance(value, (bool, str)) else defaults[key]
            )

        # Validate positive integers
        for key in ["batch_size_threshold", "max_concurrent_tasks"]:
            value = config.get(key, defaults[key])
            if isinstance(value, (int, float)) and value > 0:
                validated[key] = int(value)
            else:
                validated[key] = defaults[key]
                logger.warning(f"Invalid {key}: {value}, using default {defaults[key]}")

        # Validate timeout (allow 0 for no timeout)
        timeout = config.get("processing_timeout", defaults["processing_timeout"])
        if isinstance(timeout, (int, float)) and timeout >= 0:
            validated["processing_timeout"] = float(timeout)
        else:
            validated["processing_timeout"] = defaults["processing_timeout"]

        # Validate circuit breaker config
        cb_config = config.get("circuit_breaker", defaults["circuit_breaker"])
        if isinstance(cb_config, dict):
            validated["circuit_breaker"] = {
                "enabled": bool(
                    cb_config.get("enabled", defaults["circuit_breaker"]["enabled"])
                ),
                "failure_threshold": max(
                    1,
                    int(
                        cb_config.get(
                            "failure_threshold",
                            defaults["circuit_breaker"]["failure_threshold"],
                        )
                    ),
                ),
                "recovery_timeout": max(
                    1.0,
                    float(
                        cb_config.get(
                            "recovery_timeout",
                            defaults["circuit_breaker"]["recovery_timeout"],
                        )
                    ),
                ),
            }
        else:
            validated["circuit_breaker"] = defaults["circuit_breaker"]

        # Phase 2: Validate queue configuration
        queue_config = config.get("queue", defaults["queue"])
        if isinstance(queue_config, dict):
            validated["queue"] = {}

            # Validate max_size (must be positive)
            max_size = queue_config.get("max_size", defaults["queue"]["max_size"])
            if isinstance(max_size, (int, float)) and max_size > 0:
                validated["queue"]["max_size"] = int(max_size)
            else:
                validated["queue"]["max_size"] = defaults["queue"]["max_size"]
                logger.warning(
                    f"Invalid queue max_size: {max_size}, using default {defaults['queue']['max_size']}"
                )

            # Validate batch_size (must be positive)
            batch_size = queue_config.get("batch_size", defaults["queue"]["batch_size"])
            if isinstance(batch_size, (int, float)) and batch_size > 0:
                validated["queue"]["batch_size"] = int(batch_size)
            else:
                validated["queue"]["batch_size"] = defaults["queue"]["batch_size"]
                logger.warning(
                    f"Invalid queue batch_size: {batch_size}, using default {defaults['queue']['batch_size']}"
                )

            # Validate overflow_strategy
            strategy = queue_config.get(
                "overflow_strategy", defaults["queue"]["overflow_strategy"]
            )
            if strategy in ["drop_oldest", "drop_newest", "block"]:
                validated["queue"]["overflow_strategy"] = strategy
            else:
                validated["queue"]["overflow_strategy"] = defaults["queue"][
                    "overflow_strategy"
                ]
                logger.warning(
                    f"Invalid overflow_strategy: {strategy}, using default {defaults['queue']['overflow_strategy']}"
                )

            # Validate flush_on_config_change
            flush_on_change = queue_config.get(
                "flush_on_config_change", defaults["queue"]["flush_on_config_change"]
            )
            validated["queue"]["flush_on_config_change"] = bool(flush_on_change)
        else:
            validated["queue"] = defaults["queue"]

        # Validate transmission configuration
        transmission_config = config.get("transmission", defaults["transmission"])
        if isinstance(transmission_config, dict):
            validated["transmission"] = {}

            # Validate timeouts (must be non-negative)
            for key in ["batch_timeout_ms", "queue_check_interval_ms"]:
                value = transmission_config.get(key, defaults["transmission"][key])
                if isinstance(value, (int, float)) and value >= 0:
                    validated["transmission"][key] = int(value)
                else:
                    validated["transmission"][key] = defaults["transmission"][key]
                    logger.warning(
                        f"Invalid transmission {key}: {value}, using default {defaults['transmission'][key]}"
                    )
        else:
            validated["transmission"] = defaults["transmission"]

        # Validate monitoring configuration
        monitoring_config = config.get("monitoring", defaults["monitoring"])
        if isinstance(monitoring_config, dict):
            validated["monitoring"] = {}

            # Validate log_queue_stats
            log_stats = monitoring_config.get(
                "log_queue_stats", defaults["monitoring"]["log_queue_stats"]
            )
            validated["monitoring"]["log_queue_stats"] = bool(log_stats)

            # Validate queue_warning_threshold (must be positive)
            threshold = monitoring_config.get(
                "queue_warning_threshold",
                defaults["monitoring"]["queue_warning_threshold"],
            )
            if isinstance(threshold, (int, float)) and threshold > 0:
                validated["monitoring"]["queue_warning_threshold"] = int(threshold)
            else:
                validated["monitoring"]["queue_warning_threshold"] = defaults[
                    "monitoring"
                ]["queue_warning_threshold"]
                logger.warning(
                    f"Invalid queue_warning_threshold: {threshold}, using default {defaults['monitoring']['queue_warning_threshold']}"
                )
        else:
            validated["monitoring"] = defaults["monitoring"]

        return validated

    def _deep_merge_config(
        self, base_config: Dict[str, Any], update_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Deep merge configuration dictionaries to handle nested structures properly"""
        result = base_config.copy()

        for key, value in update_config.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                # Recursively merge nested dictionaries
                result[key] = self._deep_merge_config(result[key], value)
            else:
                # Override with new value
                result[key] = value

        return result

    def _load_performance_config(self):
        """Load and apply performance configuration with environment overrides"""
        # Load from file
        file_config = self.load_performance_config()

        # Apply file configuration over defaults with deep merge
        if file_config:
            self.parallel_config = self._deep_merge_config(
                self.parallel_config, file_config
            )

        # Apply environment variable overrides with deep merge
        env_config = self.load_performance_config_with_env_override()
        if env_config:
            self.parallel_config = self._deep_merge_config(
                self.parallel_config, env_config
            )

        # Validate configuration
        self.parallel_config = self.validate_performance_config(self.parallel_config)

    # Phase 1: Critical methods for plugins - extracted from EnhancedCOTService

    async def create_cot_events(
        self,
        locations: List[Dict[str, Any]],
        cot_type: str = "a-f-G-U-C",
        stale_time: int = 300,
        cot_type_mode: str = "stream",
    ) -> List[bytes]:
        """
        Create COT events from location data with parallel processing support

        Args:
            locations: List of location dictionaries
            cot_type: COT type identifier (used when cot_type_mode is "stream")
            stale_time: Time in seconds before event becomes stale
            cot_type_mode: "stream" or "per_point" to determine COT type source

        Returns:
            List of COT events as XML bytes
        """
        logger.debug(
            f"create_cot_events called with: cot_type_mode='{cot_type_mode}', cot_type='{cot_type}', locations={len(locations)}"
        )

        # Check if parallel processing is enabled
        if not self.parallel_config.get("enabled", True):
            logger.debug("Parallel processing disabled, using serial processing")
            if PYTAK_AVAILABLE:
                return await self._create_pytak_events(
                    locations, cot_type, stale_time, cot_type_mode
                )
            else:
                return await QueuedCOTService._create_custom_events(
                    locations, cot_type, stale_time, cot_type_mode
                )

        # Use parallel processing for larger datasets to improve performance
        threshold = self.parallel_config.get("batch_size_threshold", 10)
        fallback_on_error = self.parallel_config.get("fallback_on_error", True)

        if len(locations) >= threshold:
            # Check circuit breaker before attempting parallel processing
            if self.is_circuit_breaker_open():
                logger.debug(
                    f"Circuit breaker is open, skipping parallel processing for {len(locations)} locations"
                )
                if PYTAK_AVAILABLE:
                    return await self._create_pytak_events(
                        locations, cot_type, stale_time, cot_type_mode
                    )
                else:
                    return await QueuedCOTService._create_custom_events(
                        locations, cot_type, stale_time, cot_type_mode
                    )

            logger.debug(
                f"Using parallel processing for {len(locations)} locations (threshold: {threshold})"
            )
            if PYTAK_AVAILABLE:
                try:
                    return await self._create_parallel_pytak_events(
                        locations, cot_type, stale_time, cot_type_mode
                    )
                except Exception as e:
                    if fallback_on_error:
                        logger.warning(
                            f"Parallel processing failed, falling back to serial: {e}"
                        )
                        self._record_circuit_breaker_failure()
                        return await self._create_pytak_events(
                            locations, cot_type, stale_time, cot_type_mode
                        )
                    else:
                        self._record_circuit_breaker_failure()
                        raise
            else:
                return await QueuedCOTService._create_custom_events(
                    locations, cot_type, stale_time, cot_type_mode
                )
        else:
            logger.debug(
                f"Using serial processing for {len(locations)} locations (below threshold: {threshold})"
            )
            if PYTAK_AVAILABLE:
                return await self._create_pytak_events(
                    locations, cot_type, stale_time, cot_type_mode
                )
            else:
                return await QueuedCOTService._create_custom_events(
                    locations, cot_type, stale_time, cot_type_mode
                )

    async def send_to_tak_server(self, events: List[bytes], tak_server) -> bool:
        """
        Send COT events to TAK server using appropriate method

        Args:
            events: List of COT events as XML bytes
            tak_server: TAK server configuration

        Returns:
            bool: Success status
        """
        # Phase 1: Always use PyTAK (no fallback complexity)
        if PYTAK_AVAILABLE:
            return await self._send_with_pytak(events, tak_server)
        else:
            return await QueuedCOTService._send_with_custom(events, tak_server)

    @staticmethod
    async def _create_pytak_events(
        locations: List[Dict[str, Any]],
        cot_type: str,
        stale_time: int,
        cot_type_mode: str = "stream",
    ) -> List[bytes]:
        """Create COT events using PyTAK's XML generation"""
        events = []

        for location in locations:
            try:
                # Check for error responses from plugins
                if "_error" in location:
                    error_code = location.get("_error", "unknown")
                    error_message = location.get("_error_message", "Unknown error")
                    logger.warning(
                        f"Skipping error response from plugin: {error_code} - {error_message}"
                    )
                    continue

                # Validate and clean location data first
                cleaned_location = QueuedCOTService._validate_location_data(location)

                # Parse timestamp - ensure we get a proper datetime object
                if "timestamp" in cleaned_location and cleaned_location["timestamp"]:
                    if isinstance(cleaned_location["timestamp"], str):
                        try:
                            event_time = datetime.fromisoformat(
                                cleaned_location["timestamp"].replace("Z", "+00:00")
                            )
                            # Remove timezone info to avoid issues
                            if event_time.tzinfo is not None:
                                event_time = event_time.replace(tzinfo=None)
                        except (ValueError, TypeError) as e:
                            logger.warning(
                                f"Invalid timestamp format: {cleaned_location['timestamp']}, error: {e}"
                            )
                            event_time = datetime.now()
                    elif isinstance(cleaned_location["timestamp"], datetime):
                        event_time = cleaned_location["timestamp"]
                        # Remove timezone info to avoid issues
                        if event_time.tzinfo is not None:
                            event_time = event_time.replace(tzinfo=None)
                    else:
                        logger.warning(
                            f"Unexpected timestamp type: {type(cleaned_location['timestamp'])}"
                        )
                        event_time = datetime.now()
                else:
                    event_time = datetime.now()

                # Determine COT type
                if cot_type_mode == "per_point":
                    point_cot_type = cleaned_location.get("cot_type", cot_type)
                else:
                    point_cot_type = cot_type

                # Handle field mapping - plugins use lat/lon/uid/name, not latitude/longitude/id/callsign
                uid_value = cleaned_location.get(
                    "uid", cleaned_location.get("id", "unknown")
                )
                lat_value = float(
                    cleaned_location.get("lat", cleaned_location.get("latitude", 0.0))
                )
                lon_value = float(
                    cleaned_location.get("lon", cleaned_location.get("longitude", 0.0))
                )
                # Plugins use 'name' field for callsign/device name
                callsign_value = cleaned_location.get(
                    "name", cleaned_location.get("callsign", "")
                )

                # Build event data for proper COT generation
                event_data = {
                    "uid": uid_value,
                    "type": point_cot_type,
                    "time": event_time,
                    "start": event_time,
                    "stale": event_time + timedelta(seconds=stale_time),
                    "how": "h-g-i-g-o",
                    "lat": lat_value,
                    "lon": lon_value,
                    "hae": float(
                        cleaned_location.get(
                            "altitude", cleaned_location.get("hae", 0.0)
                        )
                    ),
                    "ce": float(
                        cleaned_location.get(
                            "accuracy", cleaned_location.get("ce", 10.0)
                        )
                    ),
                    "le": float(
                        cleaned_location.get(
                            "linear_error", cleaned_location.get("le", 10.0)
                        )
                    ),
                    "callsign": callsign_value,
                }

                # Check for team member configuration in additional_data
                additional_data = cleaned_location.get("additional_data", {})
                if additional_data.get("team_member_enabled"):
                    # Override COT type for team members
                    event_data["type"] = "a-f-G-U-C"
                    event_data["how"] = "h-e"  # Team member how attribute

                    # Add team member metadata to event_data
                    event_data["team_member_enabled"] = True
                    # Handle None values - convert to empty string
                    event_data["team_role"] = additional_data.get("team_role") or ""
                    event_data["team_color"] = additional_data.get("team_color") or ""

                # Add optional fields
                if "speed" in cleaned_location:
                    try:
                        event_data["speed"] = float(cleaned_location["speed"])
                    except (ValueError, TypeError):
                        pass

                if "course" in cleaned_location or "heading" in cleaned_location:
                    try:
                        course_val = cleaned_location.get(
                            "course", cleaned_location.get("heading")
                        )
                        if course_val is not None:
                            event_data["course"] = float(course_val)
                    except (ValueError, TypeError):
                        pass

                if "description" in cleaned_location:
                    event_data["remarks"] = str(cleaned_location["description"])

                # Generate complete COT XML using old logic
                event_xml = QueuedCOTService._generate_cot_xml(event_data)
                events.append(event_xml)

            except Exception as e:
                logger.error(f"Failed to create COT event for location {location}: {e}")
                continue

        logger.debug(
            f"Created {len(events)} COT events from {len(locations)} locations"
        )
        return events

    async def _create_parallel_pytak_events(
        self,
        locations: List[Dict[str, Any]],
        cot_type: str,
        stale_time: int,
        cot_type_mode: str = "stream",
    ) -> List[bytes]:
        """
        Create COT events using PyTAK with parallel processing for improved performance.

        This method processes locations concurrently to improve performance for large datasets
        while properly handling per-point CoT type mode functionality.
        """
        if not locations:
            return []

        try:
            # Get parallel processing configuration
            max_concurrent_tasks = self.parallel_config.get("max_concurrent_tasks", 50)
            processing_timeout = self.parallel_config.get("processing_timeout", 30.0)
            fallback_on_error = self.parallel_config.get("fallback_on_error", True)

            logger.debug(
                f"Parallel processing: {len(locations)} locations with "
                f"max_concurrent_tasks={max_concurrent_tasks}, "
                f"timeout={processing_timeout}s, fallback_enabled={fallback_on_error}"
            )

            # Split locations into chunks for concurrent processing
            import math

            chunk_size = max(1, math.ceil(len(locations) / max_concurrent_tasks))
            chunks = [
                locations[i : i + chunk_size]
                for i in range(0, len(locations), chunk_size)
            ]

            logger.debug(
                f"Split {len(locations)} locations into {len(chunks)} chunks of "
                f"~{chunk_size} each"
            )

            async def process_chunk(chunk: List[Dict[str, Any]]) -> List[bytes]:
                """Process a chunk of locations using the existing serial method"""
                try:
                    # Use the existing _create_pytak_events method for each chunk
                    # This ensures per-point CoT type logic is preserved
                    return await QueuedCOTService._create_pytak_events(
                        chunk, cot_type, stale_time, cot_type_mode
                    )
                except Exception as e:
                    logger.error(
                        f"Error processing chunk of {len(chunk)} locations: {e}"
                    )
                    if fallback_on_error:
                        logger.debug(
                            "Using fallback serial processing for failed chunk"
                        )
                        return await QueuedCOTService._create_pytak_events(
                            chunk, cot_type, stale_time, cot_type_mode
                        )
                    else:
                        raise

            # Process chunks concurrently with timeout
            try:
                if processing_timeout > 0:
                    chunk_tasks = [process_chunk(chunk) for chunk in chunks]
                    chunk_results = await asyncio.wait_for(
                        asyncio.gather(*chunk_tasks, return_exceptions=True),
                        timeout=processing_timeout,
                    )
                else:
                    chunk_results = await asyncio.gather(
                        *[process_chunk(chunk) for chunk in chunks],
                        return_exceptions=True,
                    )
            except asyncio.TimeoutError:
                logger.error(
                    f"Parallel processing timed out after {processing_timeout}s"
                )
                if fallback_on_error:
                    logger.info("Falling back to serial processing due to timeout")
                    return await self._create_pytak_events(
                        locations, cot_type, stale_time, cot_type_mode
                    )
                else:
                    raise

            # Combine results and handle any exceptions
            all_events = []
            failed_chunks = 0

            for i, result in enumerate(chunk_results):
                if isinstance(result, Exception):
                    failed_chunks += 1
                    logger.error(f"Chunk {i} processing failed: {result}")
                    if fallback_on_error:
                        logger.debug(
                            f"Processing failed chunk {i} with serial fallback"
                        )
                        try:
                            fallback_events = (
                                await QueuedCOTService._create_pytak_events(
                                    chunks[i], cot_type, stale_time, cot_type_mode
                                )
                            )
                            all_events.extend(fallback_events)
                        except Exception as fallback_error:
                            logger.error(
                                f"Fallback processing also failed for chunk {i}: {fallback_error}"
                            )
                    else:
                        raise result
                else:
                    all_events.extend(result)

            if failed_chunks > 0:
                logger.warning(
                    f"Parallel processing completed with "
                    f"{failed_chunks}/{len(chunks)} failed chunks"
                )
            else:
                logger.debug(
                    f"Parallel processing completed successfully: "
                    f"{len(all_events)} total events created"
                )

            # Record successful parallel processing for circuit breaker
            self._record_circuit_breaker_success()
            return all_events

        except Exception as e:
            logger.error(f"Parallel processing failed: {e}")
            self._record_circuit_breaker_failure()
            if fallback_on_error:
                logger.info(
                    "Falling back to serial processing due to parallel processing failure"
                )
                return await self._create_pytak_events(
                    locations, cot_type, stale_time, cot_type_mode
                )
            else:
                raise

    async def _send_with_pytak(self, events: List[bytes], tak_server) -> bool:
        """Send events using PyTAK"""
        try:
            # For now, delegate to the existing PyTAK transmission in the worker
            # This is a simplified implementation for Phase 1
            for event in events:
                await self.enqueue_event(event, tak_server.id)
            return True
        except Exception as e:
            logger.error(f"Failed to send events via PyTAK: {e}")
            return False

    async def start_worker(self, tak_server) -> bool:
        """
        Start a persistent PyTAK worker for a given TAK server.

        Args:
            tak_server: TAK server configuration object

        Returns:
            True if successful, False otherwise
        """
        tak_server_id = tak_server.id

        # Clean up any dead workers before checking status
        if tak_server_id in self.workers:
            task = self.workers[tak_server_id]
            if task.done() or task.cancelled():
                logger.info(
                    f"Cleaning up dead worker for TAK server {tak_server_id}: "
                    f"done={task.done()}, cancelled={task.cancelled()}"
                )
                del self.workers[tak_server_id]
                if tak_server_id in self.connections:
                    del self.connections[tak_server_id]
            else:
                # Worker exists and is healthy
                logger.debug(
                    f"Healthy worker for TAK server {tak_server_id} already running - skipping creation"
                )
                return True

        try:
            logger.debug(
                f"Starting worker for TAK server {tak_server.name} (ID: {tak_server_id}) at {datetime.now()}"
            )
            logger.debug(
                f"Worker creation context: total_existing_workers={len(self.workers)}, singleton_instance_id={id(self)}"
            )

            # Create queue through queue manager
            queue_created = await self.queue_manager.create_queue(tak_server_id)
            if not queue_created:
                logger.error(f"Failed to create queue for TAK server {tak_server_id}")
                return False

            # Create device state manager for this server
            self.device_state_managers[tak_server_id] = DeviceStateManager()

            # Start the transmission worker
            worker_task = asyncio.create_task(
                self._enhanced_transmission_worker(tak_server_id, tak_server)
            )
            self.workers[tak_server_id] = worker_task
            logger.debug(
                f"Worker-to-server mapping updated: TAK_server_{tak_server_id} -> worker_{id(worker_task)}"
            )
            logger.debug(
                f"Updated worker mappings: {[(k, id(v)) for k, v in self.workers.items()]}"
            )

            logger.debug(
                f"Worker registry state: {list(self.workers.keys())} active workers"
            )
            logger.debug(
                f"New worker task created: task_id={id(worker_task)}, task_name={worker_task.get_name()}, for_server={tak_server_id}"
            )
            logger.info(f"Started worker for TAK server {tak_server.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to start worker for TAK server {tak_server_id}: {e}")
            logger.debug(
                f"Worker creation failure context: existing_workers={list(self.workers.keys())}, singleton_id={id(self)}"
            )
            return False

    async def _enhanced_transmission_worker(self, tak_server_id: int, tak_server):
        """
        Enhanced transmission worker using queue manager for batch processing.

        Args:
            tak_server_id: TAK server identifier
            tak_server: TAK server configuration object
        """
        try:
            logger.info(
                f"Enhanced transmission worker started for TAK server {tak_server.name}"
            )
            logger.debug(
                f"Worker thread started: server_id={tak_server_id}, server_name={tak_server.name}, timestamp={datetime.now()}"
            )

            # Create PyTAK connection (reusing existing logic)
            connection = await self._create_pytak_connection(tak_server)
            if not connection:
                logger.error(
                    f"Failed to create connection for TAK server {tak_server.name}"
                )
                return

            self.connections[tak_server_id] = connection
            logger.debug(
                f"Connection mapping established: TAK_server_{tak_server_id} -> connection_{id(connection)}"
            )

            # Main transmission loop
            batch_count = 0
            while self._running:
                try:
                    # Get batch of events from queue manager
                    batch = await self.queue_manager.get_batch(tak_server_id)

                    if not batch:
                        # No events to process, longer sleep to reduce CPU usage
                        # Use the configured queue_check_interval from performance.yaml
                        check_interval_ms = self.parallel_config.get(
                            "transmission", {}
                        ).get("queue_check_interval_ms", 1000)
                        await asyncio.sleep(check_interval_ms / 1000.0)
                        # Log periodic status every 10 iterations with no events (reduced frequency)
                        batch_count += 1
                        if batch_count % 10 == 0:
                            queue_size = (
                                self.queue_manager.get_queue_status(tak_server_id).get(
                                    "size", 0
                                )
                                if self.queue_manager.get_queue_status(tak_server_id)
                                else 0
                            )
                            logger.debug(
                                f"Worker {tak_server_id} idle: checked {batch_count} times, queue_size={queue_size}"
                            )
                        continue  # Skip transmission when no events

                    # We have events to process
                    batch_count = 0  # Reset counter when we have events
                    logger.debug(
                        f"Worker {tak_server_id} processing batch of {len(batch)} events"
                    )

                    # Transmit batch
                    success = await self._transmit_batch(batch, connection, tak_server)

                    if success:
                        if len(batch) > 0:  # Only log when actually transmitted events
                            logger.debug(
                                f"Successfully transmitted {len(batch)} events to {tak_server.name}"
                            )
                    else:
                        logger.warning(
                            f"Failed to transmit batch of {len(batch)} events to {tak_server.name}"
                        )

                        # On failure, could implement retry logic here
                        # For now, events are lost (already dequeued)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(
                        f"Error in transmission worker for {tak_server.name}: {e}"
                    )
                    await asyncio.sleep(1)  # Brief pause before retry

        except Exception as e:
            logger.error(
                f"Enhanced transmission worker failed for TAK server {tak_server_id}: {e}"
            )
        finally:
            logger.debug(
                f"Worker cleanup starting for TAK server {tak_server_id} at {datetime.now()}"
            )
            # Cleanup connection
            if tak_server_id in self.connections:
                try:
                    await self._cleanup_connection(self.connections[tak_server_id])
                except Exception as e:
                    logger.error(
                        f"Failed to cleanup connection for {tak_server_id}: {e}"
                    )
                del self.connections[tak_server_id]
                logger.debug(
                    f"Connection cleanup completed for TAK server {tak_server_id}"
                )
                logger.debug(
                    f"Connection mapping removed: TAK_server_{tak_server_id} connection deleted"
                )

    def _get_tak_circuit_breaker(self, tak_server_id: int):
        """Get or create circuit breaker for TAK server connection"""
        try:
            from services.circuit_breaker import (
                get_circuit_breaker_manager,
                CircuitBreakerConfig,
            )

            # Load circuit breaker configuration from performance config or defaults
            cb_config = {}
            try:
                if hasattr(self, "performance_config") and self.performance_config:
                    cb_config = self.performance_config.get("circuit_breaker", {})
                else:
                    # Load performance config if not available
                    perf_config = self.load_performance_config()
                    cb_config = perf_config.get("circuit_breaker", {})
            except Exception as e:
                logger.debug(
                    f"Could not load circuit breaker config: {e}, using defaults"
                )
                cb_config = {}

            # Create circuit breaker config for TAK connections
            circuit_config = CircuitBreakerConfig(
                failure_threshold=cb_config.get("failure_threshold", 3),
                recovery_timeout=cb_config.get("recovery_timeout", 60.0),
                timeout=cb_config.get("timeout", 30.0),
                half_open_max_calls=cb_config.get("half_open_max_calls", 3),
                success_threshold=cb_config.get("success_threshold", 2),
                health_check_interval=cb_config.get("health_check_interval", 30.0),
            )

            # Get circuit breaker for this TAK server
            manager = get_circuit_breaker_manager()
            service_name = f"tak_server_{tak_server_id}"

            if service_name not in manager.circuit_breakers:
                circuit_breaker = manager.get_circuit_breaker(
                    service_name, circuit_config
                )
                # Set up health check for this TAK server (but only if we have an event loop)
                try:
                    import asyncio

                    asyncio.get_running_loop()
                    circuit_breaker.set_health_check(
                        lambda: self._tak_health_check(tak_server_id)
                    )
                except RuntimeError:
                    # No event loop running, skip health check setup for now
                    logger.debug(
                        f"No event loop available, skipping health check setup for TAK server {tak_server_id}"
                    )
                logger.info(
                    f"Circuit breaker initialized for TAK server {tak_server_id}"
                )

            return manager.get_circuit_breaker(service_name, circuit_config)

        except Exception as e:
            logger.error(
                f"Failed to initialize circuit breaker for TAK server {tak_server_id}: {e}"
            )
            return None

    async def _tak_health_check(self, tak_server_id: int) -> bool:
        """Health check for TAK server connectivity"""
        try:
            # Simple connectivity test - try to create a connection
            from models.tak_server import TakServer

            tak_server = TakServer.query.get(tak_server_id)
            if not tak_server:
                return False

            # Try to create a test connection with short timeout
            test_config = await self._create_pytak_config(tak_server)
            test_connection = await asyncio.wait_for(
                pytak.protocol_factory(test_config),
                timeout=5.0,  # Short timeout for health check
            )

            # Clean up test connection
            if test_connection:
                await self._cleanup_connection(test_connection)
                return True

            return False

        except Exception as e:
            logger.debug(f"TAK server {tak_server_id} health check failed: {e}")
            return False

    async def _create_pytak_connection(self, tak_server):
        """
        Create PyTAK connection with circuit breaker protection.
        """
        if not PYTAK_AVAILABLE:
            logger.error("PyTAK not available. Cannot create connection.")
            return None

        # Get circuit breaker for this TAK server
        circuit_breaker = self._get_tak_circuit_breaker(tak_server.id)

        async def _do_connection():
            logger.info(f"Creating PyTAK connection for {tak_server.name}")

            # Create PyTAK configuration
            config = await self._create_pytak_config(tak_server)

            # Create connection using PyTAK's protocol factory with timeout
            logger.debug(
                f"Attempting to connect to TAK server {tak_server.name} "
                f"at {tak_server.host}:{tak_server.port}"
            )

            # Add timeout to prevent hanging
            connection_result = await asyncio.wait_for(
                pytak.protocol_factory(config),
                timeout=30.0,  # 30 second timeout
            )
            return connection_result

        try:
            if circuit_breaker:
                # Use circuit breaker to protect connection attempt
                connection_result = await circuit_breaker.call(_do_connection)
            else:
                # Fallback to direct connection if circuit breaker not available
                logger.debug(
                    f"Circuit breaker not available for TAK server {tak_server.id}, using direct connection"
                )
                connection_result = await _do_connection()

            # Handle the connection result (might be a tuple for TCP)
            if isinstance(connection_result, tuple) and len(connection_result) == 2:
                reader, writer = connection_result
                logger.info(
                    f"Received (reader, writer) tuple for TAK server {tak_server.name}"
                )
                return (reader, writer)
            else:
                logger.info(
                    f"Received single connection object for TAK server {tak_server.name}"
                )
                return connection_result

        except asyncio.TimeoutError:
            error_msg = f"Timeout connecting to TAK server {tak_server.name}"
            logger.error(error_msg)
            return None
        except Exception as e:
            error_msg = f"Failed to connect to TAK server {tak_server.name}: {e}"
            logger.error(error_msg)
            return None

    async def _create_pytak_config(self, tak_server):
        """Create PyTAK configuration from TAK server settings"""
        from configparser import ConfigParser

        config = ConfigParser(interpolation=None)
        config.add_section("pytak")

        # Determine protocol
        protocol = "tls" if tak_server.protocol.lower() in ["tls", "ssl"] else "tcp"
        config.set(
            "pytak", "COT_URL", f"{protocol}://{tak_server.host}:{tak_server.port}"
        )

        # Add TLS configuration if needed
        if protocol == "tls":
            config.set(
                "pytak", "PYTAK_TLS_DONT_VERIFY", str(not tak_server.verify_ssl).lower()
            )

            # Handle P12 certificate if available
            if tak_server.cert_p12 and len(tak_server.cert_p12) > 0:
                try:
                    cert_pem, key_pem = QueuedCOTService._extract_p12_certificate(
                        tak_server.cert_p12, tak_server.get_cert_password()
                    )
                    cert_path, key_path = QueuedCOTService._create_temp_cert_files(
                        cert_pem, key_pem
                    )
                    config.set("pytak", "PYTAK_TLS_CLIENT_CERT", cert_path)
                    config.set("pytak", "PYTAK_TLS_CLIENT_KEY", key_path)
                except Exception as e:
                    logger.error(f"Failed to configure P12 certificate: {e}")

        logger.debug(
            f"Created PyTAK config for {tak_server.name}: {dict(config['pytak'])}"
        )
        return config["pytak"]

    async def _transmit_batch(self, batch: List[bytes], connection, tak_server) -> bool:
        """
        Transmit a batch of events to the TAK server with circuit breaker protection.

        Args:
            batch: List of COT event bytes
            connection: PyTAK connection object
            tak_server: TAK server configuration

        Returns:
            True if transmission successful
        """
        if not batch:
            return True

        # Get circuit breaker for this TAK server
        circuit_breaker = self._get_tak_circuit_breaker(tak_server.id)

        async def _do_transmission():
            # Handle the case where connection might be a tuple (reader, writer)
            if isinstance(connection, tuple) and len(connection) == 2:
                reader, writer = connection
                use_writer = True
            else:
                reader = connection
                writer = None
                use_writer = False

            # Transmit all events in the batch
            batch_success = True
            for i, event in enumerate(batch):
                try:
                    # Send the event using the appropriate method
                    if use_writer and writer:
                        # Use writer for TCP connections
                        writer.write(event)
                        await writer.drain()
                    elif hasattr(reader, "send"):
                        # Use reader.send for other connection types
                        await reader.send(event)
                    else:
                        logger.error(
                            f"No suitable send method found for TAK server '{tak_server.name}'. "
                            f"Event {i + 1} not transmitted."
                        )
                        batch_success = False

                except Exception as e:
                    logger.error(
                        f"Error transmitting event {i + 1} to TAK server '{tak_server.name}': {e}"
                    )
                    batch_success = False

            if batch_success:
                logger.debug(
                    f"Successfully transmitted batch of {len(batch)} events to TAK server '{tak_server.name}'"
                )
            else:
                logger.warning(
                    f"Some events in batch failed transmission to TAK server '{tak_server.name}'"
                )

            return batch_success

        try:
            if circuit_breaker:
                # Use circuit breaker to protect transmission
                return await circuit_breaker.call(_do_transmission)
            else:
                # Fallback to direct transmission if circuit breaker not available
                logger.debug(
                    f"Circuit breaker not available for TAK server {tak_server.id}, using direct transmission"
                )
                return await _do_transmission()

        except Exception as e:
            from services.circuit_breaker import CircuitOpenError

            if isinstance(e, CircuitOpenError):
                logger.warning(
                    f"Circuit breaker is OPEN for TAK server {tak_server.name}: {e}"
                )
                return False
            else:
                logger.error(f"Failed to transmit batch to {tak_server.name}: {e}")
                return False

    async def _cleanup_connection(self, connection):
        """Cleanup PyTAK connection"""
        try:
            # Handle the case where connection might be a tuple (reader, writer)
            if isinstance(connection, tuple) and len(connection) == 2:
                reader, writer = connection
                try:
                    writer.close()
                    await writer.wait_closed()
                    logger.debug("Closed writer connection")
                except Exception as e:
                    logger.debug(f"Error closing writer: {e}")
            elif hasattr(connection, "close"):
                try:
                    await connection.close()
                    logger.debug("Closed reader connection")
                except Exception as e:
                    logger.debug(f"Error closing reader: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up connection: {e}")

    async def enqueue_event(self, event: bytes, tak_server_id: int) -> bool:
        """
        Enqueue a COT event using the queue manager.

        Args:
            event: COT event bytes
            tak_server_id: TAK server identifier

        Returns:
            True if successfully enqueued
        """
        # Ensure queue exists before enqueueing
        await self.queue_manager.create_queue(tak_server_id)
        return await self.queue_manager.enqueue_event(tak_server_id, event)

    async def enqueue_with_replacement(
        self, events: List[bytes], tak_server_id: int
    ) -> bool:
        """
        Enqueue events with replacement logic for same devices.

        Args:
            events: List of COT events
            tak_server_id: TAK server identifier

        Returns:
            True if successfully processed
        """
        try:
            # Get device state manager
            device_manager = self.device_state_managers.get(tak_server_id)
            if not device_manager:
                logger.debug(f"No device state manager for TAK server {tak_server_id}")
                device_manager = None

            # Process each event and build processing plan
            processed_events = 0
            removed_events = 0
            uids_to_remove = []
            events_to_enqueue = []

            for event in events:
                # Extract UID and timestamp from event
                uid = self.extract_uid_from_cot_event(event)
                timestamp = self.extract_timestamp_from_cot_event(event)

                if not uid:
                    logger.warning("Event without UID, skipping replacement logic")
                    events_to_enqueue.append(event)
                    processed_events += 1
                    continue

                # Check if we should update this device
                should_update = True
                if device_manager and hasattr(device_manager, "should_update_device"):
                    should_update = device_manager.should_update_device(uid, timestamp)

                if should_update:
                    # Always mark for removal if we're updating (removes any stale events)
                    uids_to_remove.append(uid)
                    events_to_enqueue.append(event)
                    processed_events += 1
                else:
                    # Skip older events
                    logger.debug(f"Skipping older event for device {uid}")
                    continue

            # Remove old events for devices that will be updated
            if uids_to_remove:
                removed_count = await self.remove_events_by_uid(
                    tak_server_id, uids_to_remove
                )
                removed_events += removed_count

            # Add new events
            for event in events_to_enqueue:
                await self.queue_manager.enqueue_event(tak_server_id, event)

            # Log replacement statistics
            if processed_events > 0 or removed_events > 0:
                logger.debug(
                    f"Enqueue with replacement statistics: "
                    f"{processed_events} events processed, {removed_events} old events removed"
                )

            return True

        except Exception as e:
            logger.error(
                f"Failed to enqueue events with replacement for TAK server {tak_server_id}: {e}"
            )
            return False

    async def flush_queue(self, tak_server_id: int) -> int:
        """
        Flush all events from a TAK server's queue.

        Args:
            tak_server_id: TAK server identifier

        Returns:
            Number of events flushed
        """
        return await self.queue_manager.flush_queue(tak_server_id)

    def get_queue_status(self, tak_server_id: int) -> Dict[str, Any]:
        """
        Get comprehensive queue status for a TAK server.

        Args:
            tak_server_id: TAK server identifier

        Returns:
            Dictionary containing queue status and metrics
        """
        base_status = self.queue_manager.get_queue_status(tak_server_id)

        # Add worker status
        base_status["worker_running"] = tak_server_id in self.workers
        base_status["connection_active"] = tak_server_id in self.connections

        # Add monitoring metrics if available
        metrics = self.monitoring_service.get_queue_metrics(tak_server_id)
        if metrics:
            base_status["health_score"] = metrics.health_score
            base_status["trend_direction"] = metrics.trend_direction
            base_status["events_per_second"] = metrics.events_per_second
            base_status["average_wait_time"] = metrics.average_wait_time

        return base_status

    async def get_queue_metrics(self, tak_server_id: int) -> Dict[str, Any]:
        """
        Get queue metrics for a TAK server.

        Args:
            tak_server_id: TAK server identifier

        Returns:
            Dictionary containing queue metrics and status
        """
        # Ensure queue exists before getting metrics
        await self.queue_manager.create_queue(tak_server_id)

        # Get comprehensive queue status which includes metrics
        status = self.get_queue_status(tak_server_id)

        # Add queue_size key for test compatibility
        if "size" in status:
            status["queue_size"] = status["size"]

        return status

    def get_worker_status(self, tak_server_id: int) -> Dict[str, Any]:
        """Get status information for a specific worker with health validation"""
        # Check if worker exists and validate its health
        worker_healthy = False
        worker_exists = tak_server_id in self.workers

        if worker_exists:
            task = self.workers[tak_server_id]
            worker_healthy = not task.done() and not task.cancelled()

            # Additional health check: verify event loop is active
            try:
                if hasattr(task, "_loop") and task._loop and task._loop.is_closed():
                    worker_healthy = False
                    logger.debug(f"Worker {tak_server_id} has closed event loop")
            except Exception as e:
                logger.debug(f"Error checking worker {tak_server_id} event loop: {e}")
                worker_healthy = False

        status = {
            "worker_running": worker_healthy,  # Only True if worker exists AND is healthy
            "worker_exists": worker_exists,
            "connection_exists": tak_server_id in self.connections,
            "queue_size": 0,
        }

        # Get queue size from queue manager
        queue_status = self.queue_manager.get_queue_status(tak_server_id)
        if queue_status:
            status["queue_size"] = queue_status.get("size", 0)

        if worker_exists:
            task = self.workers[tak_server_id]
            status["worker_done"] = task.done()
            status["worker_cancelled"] = task.cancelled()

            # Log unhealthy worker detection
            if not worker_healthy:
                logger.warning(
                    f"Detected unhealthy worker for TAK server {tak_server_id}: "
                    f"done={task.done()}, cancelled={task.cancelled()}"
                )

        return status

    async def start_monitoring(self):
        """Start the queue monitoring service"""
        await self.monitoring_service.start_monitoring()

    async def stop_monitoring(self):
        """Stop the queue monitoring service"""
        await self.monitoring_service.stop_monitoring()

    async def on_configuration_change(self, new_config: Dict[str, Any]):
        """
        Handle configuration changes by notifying queue manager.

        Args:
            new_config: New configuration dictionary
        """
        try:
            logger.info("Configuration change detected in COT service")
            logger.debug(
                f"Configuration change tracking - active workers before: {list(self.workers.keys())}"
            )
            logger.debug(f"Configuration change timestamp: {datetime.now()}")
            logger.debug(
                f"Configuration change context: singleton_id={id(self)}, worker_count={len(self.workers)}"
            )

            # Log configuration changes that might affect workers
            affected_servers = []
            for tak_server_id in self.workers.keys():
                logger.debug(
                    f"Configuration change detected for TAK server {tak_server_id}, stopping existing workers"
                )
                affected_servers.append(tak_server_id)

            if affected_servers:
                logger.debug(
                    f"Configuration change will affect {len(affected_servers)} TAK servers: {affected_servers}"
                )
            else:
                logger.debug(
                    "Configuration change detected but no active workers to affect"
                )

            # Update configuration tracking
            self.config_change_count += 1
            self.last_config_change_timestamp = datetime.now()

            # Update queue manager configuration
            await self.queue_manager.on_configuration_change(new_config)

            # Log configuration change
            logger.debug(
                f"Configuration change tracking - active workers after: {list(self.workers.keys())}"
            )
            logger.debug(
                f"Configuration change #{self.config_change_count} processing completed at {self.last_config_change_timestamp}"
            )
            logger.info("Queue configuration updated due to configuration change")

        except Exception as e:
            logger.error(f"Failed to handle configuration change: {e}")

    async def stop_worker(self, tak_server_id: int):
        """
        Enhanced worker cleanup with verification.

        Args:
            tak_server_id: TAK server identifier
        """
        logger.debug(
            f"Stopping worker for TAK server {tak_server_id} at {datetime.now()}"
        )
        logger.debug(
            f"Pre-stop worker registry state: {list(self.workers.keys())} active workers"
        )

        # Cancel worker task with verification
        if tak_server_id in self.workers:
            task = self.workers[tak_server_id]
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            del self.workers[tak_server_id]
            logger.debug(
                f"Worker task stopped and removed from registry for TAK server {tak_server_id} at {datetime.now()}"
            )
            logger.debug(
                f"Worker mapping removed: TAK_server_{tak_server_id} no longer mapped"
            )
            logger.debug(
                f"Remaining worker mappings: {[(k, id(v)) for k, v in self.workers.items()]}"
            )

        # Remove queue and cleanup
        await self.queue_manager.remove_queue(tak_server_id)

        # Cleanup device state manager
        if tak_server_id in self.device_state_managers:
            del self.device_state_managers[tak_server_id]

        logger.debug(
            f"Complete cleanup finished for TAK server {tak_server_id} at {datetime.now()}"
        )
        logger.debug(
            f"Post-cleanup worker registry state: {list(self.workers.keys())} active workers"
        )

    async def stop_all_workers_for_server(self, tak_server_id: int):
        """
        Comprehensive cleanup for all workers associated with a TAK server.

        Args:
            tak_server_id: TAK server identifier
        """
        # Get TAK server name for better logging
        from models.tak_server import TakServer
        tak_server_name = "Unknown"
        try:
            tak_server = TakServer.query.get(tak_server_id)
            if tak_server:
                tak_server_name = tak_server.name or f"TAK Server {tak_server_id}"
        except Exception:
            tak_server_name = f"TAK Server {tak_server_id}"

        logger.debug(
            f"Comprehensive worker cleanup for TAK server {tak_server_id} ({tak_server_name}) at {datetime.now()}"
        )
        logger.debug(
            f"Pre-comprehensive-cleanup worker registry: {list(self.workers.keys())}"
        )

        # Force stop any remaining workers
        tasks_to_cancel = []
        for worker_id, task in list(self.workers.items()):
            if worker_id == tak_server_id:
                tasks_to_cancel.append(task)

        if tasks_to_cancel:
            logger.warning(
                f"Found {len(tasks_to_cancel)} workers to force-stop for TAK server '{tak_server_name}'"
            )
            logger.debug(
                f"Force-stopping tasks: {[id(task) for task in tasks_to_cancel]}"
            )
            for task in tasks_to_cancel:
                task.cancel()

            # Wait for all cancellations
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            logger.debug(
                f"Force-cancelled worker mappings for TAK server '{tak_server_name}'"
            )

        # Ensure cleanup
        await self.stop_worker(tak_server_id)
        logger.debug(
            f"Comprehensive cleanup completed - final worker mappings: {[(k, id(v)) for k, v in self.workers.items()]}"
        )

    def extract_uid_from_cot_event(self, event: bytes) -> Optional[str]:
        """
        Extract UID from COT event XML.

        Args:
            event: COT event as XML bytes

        Returns:
            UID string if found, None otherwise
        """
        try:
            # Parse XML and extract uid attribute
            root = ET.fromstring(event)
            uid = root.get("uid")
            return uid
        except Exception as e:
            logger.error(f"Failed to extract UID from COT event: {e}")
            return None

    def extract_timestamp_from_cot_event(self, event: bytes) -> Optional[datetime]:
        """
        Extract timestamp from COT event XML.

        Args:
            event: COT event as XML bytes

        Returns:
            Datetime object if found, None otherwise
        """
        try:
            # Parse XML and extract time attribute
            root = ET.fromstring(event)
            time_str = root.get("time")
            if time_str:
                # Parse ISO format timestamp
                if time_str.endswith("Z"):
                    time_str = time_str[:-1] + "+00:00"
                timestamp = datetime.fromisoformat(time_str)
                # Ensure timezone aware
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                return timestamp
            return None
        except Exception as e:
            logger.error(f"Failed to extract timestamp from COT event: {e}")
            return None

    async def _transmit_events_batch(self, events: List[bytes], tak_server) -> bool:
        """
        Transmit a batch of events to TAK server.

        Args:
            events: List of COT events
            tak_server: TAK server configuration (can be None for testing)

        Returns:
            True if successful
        """
        try:
            # This is a mock implementation for testing
            # In production, this would send events to the actual TAK server
            server_info = f" to server {tak_server.id}" if tak_server else ""
            logger.debug(f"Transmitting batch of {len(events)} events{server_info}")
            return True
        except Exception as e:
            logger.error(f"Failed to transmit events batch: {e}")
            return False

    async def _process_transmission_batches(
        self, tak_server_id: int, tak_server=None
    ) -> bool:
        """
        Process transmission batches for a TAK server.

        Args:
            tak_server_id: TAK server identifier
            tak_server: Optional TAK server object (for unit testing)

        Returns:
            True if successful
        """
        try:
            # Use provided tak_server or query from database
            if tak_server is None:
                from models.tak_server import TakServer

                tak_server = TakServer.query.get(tak_server_id)
                if not tak_server:
                    logger.error(f"TAK server {tak_server_id} not found")
                    return False

            # Process batches until queue is empty
            batches_processed = 0
            while True:
                # Get batch from queue manager
                batch = await self.queue_manager.get_batch(tak_server_id)
                if not batch:
                    break

                # Transmit the batch
                await self._transmit_events_batch(batch, tak_server)
                batches_processed += 1

                # Prevent infinite loop
                if batches_processed > 100:
                    logger.warning(
                        f"Processed {batches_processed} batches, stopping to prevent infinite loop"
                    )
                    break

            return batches_processed > 0
        except Exception as e:
            logger.error(f"Failed to process transmission batches: {e}")
            return False

    async def remove_events_by_uid(
        self, tak_server_id: int, uids_to_remove: List[str]
    ) -> int:
        """
        Remove events from queue by UID.

        Args:
            tak_server_id: TAK server identifier
            uids_to_remove: List of UIDs to remove

        Returns:
            Number of events removed
        """
        if tak_server_id not in self.queues:
            logger.error(f"Queue {tak_server_id} does not exist")
            return 0

        try:
            queue = self.queues[tak_server_id]
            removed_count = 0
            events_to_keep = []

            # Drain the queue and check each event
            while not queue.empty():
                try:
                    event = queue.get_nowait()
                    uid = self.extract_uid_from_cot_event(event)
                    if uid not in uids_to_remove:
                        events_to_keep.append(event)
                    else:
                        removed_count += 1
                except asyncio.QueueEmpty:
                    break

            # Put back the events we want to keep
            for event in events_to_keep:
                await queue.put(event)

            logger.debug(f"Removed {removed_count} events from queue {tak_server_id}")
            return removed_count

        except Exception as e:
            logger.error(
                f"Failed to remove events by UID from queue {tak_server_id}: {e}"
            )
            return 0

    async def shutdown(self):
        """Shutdown the COT service and all workers"""
        try:
            self._running = False

            # Stop all workers
            worker_mappings_before = [(k, id(v)) for k, v in self.workers.items()]
            logger.debug(
                f"Shutdown: stopping all workers with mappings: {worker_mappings_before}"
            )
            for tak_server_id in list(self.workers.keys()):
                await self.stop_worker(tak_server_id)
            logger.debug(
                f"Shutdown: all worker mappings cleared, final state: {[(k, id(v)) for k, v in self.workers.items()]}"
            )

            # Stop monitoring
            await self.stop_monitoring()

            logger.info("Enhanced COT service shutdown complete")

        except Exception as e:
            logger.error(f"Error during COT service shutdown: {e}")

    def log_comprehensive_status(self):
        """Log comprehensive status of the COT service"""
        try:
            active_workers = len(self.workers)
            active_connections = len(self.connections)

            logger.info(
                f"Enhanced COT Service Status: {active_workers} workers, "
                f"{active_connections} connections"
            )

            # Log queue manager status
            self.queue_manager.log_comprehensive_status()

            # Log individual queue status
            for tak_server_id in self.workers.keys():
                status = self.get_queue_status(tak_server_id)
                logger.debug(f"TAK Server {tak_server_id} status: {status}")

        except Exception as e:
            logger.error(f"Failed to log comprehensive status: {e}")

    # TDD Fallback mechanism methods (basic implementation for tests)
    def get_fallback_statistics(self) -> Dict[str, Any]:
        """Get fallback statistics for monitoring"""
        return self._fallback_stats.copy()

    def record_fallback_event(self, reason: str, error_message: str) -> None:
        """Record a fallback event for statistics"""
        self._fallback_stats["total_fallbacks"] += 1
        if reason not in self._fallback_stats["fallback_reasons"]:
            self._fallback_stats["fallback_reasons"][reason] = 0
        self._fallback_stats["fallback_reasons"][reason] += 1

        # Update fallback rate (simple calculation)
        total_attempts = (
            self._fallback_stats["total_fallbacks"] + self._parallel_health_successes
        )
        self._fallback_stats["fallback_rate"] = self._fallback_stats[
            "total_fallbacks"
        ] / max(1, total_attempts)

        # Track health for circuit breaker
        self._parallel_health_failures += 1
        if self._parallel_health_failures >= 3:
            self._circuit_breaker_open = True

    def record_successful_parallel_processing(self) -> None:
        """Record successful parallel processing for health tracking"""
        self._parallel_health_successes += 1
        # Reset failure count on successful processing
        if self._parallel_health_successes >= 3:
            self._parallel_health_failures = 0
            self._circuit_breaker_open = False

    def is_parallel_processing_healthy(self) -> bool:
        """Check if parallel processing is considered healthy"""
        return self._parallel_health_failures < 3

    def is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker is open (blocking parallel processing)"""
        # Check if circuit breaker should be closed due to recovery timeout
        if self._circuit_breaker_open and self._circuit_breaker_open_time:
            circuit_config = self.parallel_config.get("circuit_breaker", {})
            recovery_timeout = circuit_config.get("recovery_timeout", 60.0)
            if (
                datetime.now() - self._circuit_breaker_open_time
            ).total_seconds() > recovery_timeout:
                self._circuit_breaker_open = False
                self._circuit_breaker_failures = 0
                self._circuit_breaker_open_time = None
                logger.info("Circuit breaker closed after recovery timeout")

        return self._circuit_breaker_open

    def _record_circuit_breaker_failure(self):
        """Record a circuit breaker failure and potentially open the circuit"""
        circuit_config = self.parallel_config.get("circuit_breaker", {})
        if not circuit_config.get("enabled", True):
            return

        self._circuit_breaker_failures += 1
        failure_threshold = circuit_config.get("failure_threshold", 3)

        if (
            self._circuit_breaker_failures >= failure_threshold
            and not self._circuit_breaker_open
        ):
            self._circuit_breaker_open = True
            self._circuit_breaker_open_time = datetime.now()
            logger.warning(
                f"Circuit breaker opened after {self._circuit_breaker_failures} failures"
            )

    def _record_circuit_breaker_success(self):
        """Record a successful operation and reset failure count"""
        if self._circuit_breaker_failures > 0:
            self._circuit_breaker_failures = 0
            logger.debug(
                "Circuit breaker failure count reset after successful operation"
            )

    # Static utility methods moved from EnhancedCOTService
    @staticmethod
    def _safe_float_convert(value: Any, default: float = 0.0) -> float:
        """Safely convert a value to float, handling various input types"""
        if value is None:
            return default

        # Handle datetime objects (return default)
        if isinstance(value, datetime):
            logger.warning(
                f"Datetime object passed where float expected: {value}, using default {default}"
            )
            return default

        try:
            return float(value)
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Could not convert {value} (type: {type(value)}) to float: {e}, "
                f"using default {default}"
            )
            return default

    @staticmethod
    def _generate_cot_xml(event_data: Dict[str, Any]) -> bytes:
        """Generate COT XML using proper detailed format"""
        try:
            # Always use manual formatting to avoid PyTAK time conversion issues
            # PyTAK's cot_time() function may have issues with datetime objects
            time_str = event_data["time"].strftime("%Y-%m-%dT%H:%M:%SZ")
            start_str = event_data["start"].strftime("%Y-%m-%dT%H:%M:%SZ")
            stale_str = event_data["stale"].strftime("%Y-%m-%dT%H:%M:%SZ")

            # Create COT event element
            cot_event = etree.Element("event")
            cot_event.set("version", "2.0")
            cot_event.set("uid", event_data["uid"])
            cot_event.set("type", event_data["type"])
            cot_event.set("time", time_str)
            cot_event.set("start", start_str)
            cot_event.set("stale", stale_str)
            cot_event.set("how", event_data["how"])

            # Add point element with proper attribute order and safe conversions
            point_attr = {
                "lat": f"{event_data['lat']:.8f}",
                "lon": f"{event_data['lon']:.8f}",
                "hae": f"{event_data['hae']:.2f}",  # Ensure float formatting
                "ce": f"{event_data['ce']:.2f}",  # Ensure float formatting
                "le": f"{event_data['le']:.2f}",  # Ensure float formatting
            }
            etree.SubElement(cot_event, "point", attrib=point_attr)

            # Add detail element
            detail = etree.SubElement(cot_event, "detail")

            # Add platform info (takv element)
            takv = etree.SubElement(detail, "takv")
            takv.set("os", "34")
            takv.set("version", "TrakBridge")
            takv.set("device", "TrakBridge")
            takv.set("platform", "TrakBridge")

            # Check if this is a team member and add appropriate elements
            is_team_member = event_data.get("team_member_enabled", False)

            # Add contact info with endpoint (important for TAK Server)
            contact = etree.SubElement(detail, "contact")
            contact.set("callsign", event_data["callsign"])

            if is_team_member:
                # Team member specific contact format
                contact.set("endpoint", "*:-1:stcp")
                # Note: Team members do NOT have xmppUsername attribute

                # Add uid element for team members (Droid attribute)
                uid = etree.SubElement(detail, "uid")
                uid.set("Droid", event_data["callsign"])

                # Add precisionlocation element
                precision = etree.SubElement(detail, "precisionlocation")
                precision.set("altsrc", "DTED0")
                precision.set("geopointsrc", "USER")

                # Add __group element with role and color
                group = etree.SubElement(detail, "__group")
                group.set("role", event_data.get("team_role", ""))
                group.set("name", event_data.get("team_color", ""))

                # Add status element (battery)
                status = etree.SubElement(detail, "status")
                status.set("battery", "49")  # Static battery value as per spec

            # Add track information if available or for team members
            if "speed" in event_data or "course" in event_data or is_team_member:
                track = etree.SubElement(detail, "track")
                if "speed" in event_data:
                    track.set("speed", f"{event_data['speed']:.2f}")
                elif is_team_member:
                    track.set("speed", "0.0")  # Default speed for team members

                if "course" in event_data:
                    track.set("course", f"{event_data['course']:.2f}")
                elif is_team_member:
                    track.set("course", "335.92489054527624")  # Default course as per spec

            # Add remarks if available
            if "remarks" in event_data:
                remarks = etree.SubElement(detail, "remarks")
                remarks.text = event_data["remarks"]

            return etree.tostring(cot_event, pretty_print=False, xml_declaration=False)

        except Exception as e:
            logger.error(f"Error generating COT XML: {e}")
            raise

    @staticmethod
    def _validate_location_data(location: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and clean location data to prevent type errors"""
        cleaned_location = {}

        for key, value in location.items():
            if isinstance(value, datetime) and key not in ["timestamp"]:
                logger.warning(
                    f"Found datetime object in unexpected field '{key}': {value}"
                )
                # Convert datetime to timestamp if it's not in timestamp field
                if key in [
                    "lat",
                    "lon",
                    "altitude",
                    "hae",
                    "accuracy",
                    "ce",
                    "linear_error",
                    "le",
                    "speed",
                    "heading",
                    "course",
                ]:
                    cleaned_location[key] = 0.0  # Use default for numeric fields
                else:
                    cleaned_location[key] = str(
                        value
                    )  # Convert to string for other fields
            else:
                cleaned_location[key] = value

        return cleaned_location

    @staticmethod
    async def _create_custom_events(
        locations: List[Dict[str, Any]],
        cot_type: str,
        stale_time: int,
        cot_type_mode: str = "stream",
    ) -> List[bytes]:
        """Create COT events using custom XML generation (fallback)"""
        cot_events = []

        for location in locations:
            try:
                # Check for error responses from plugins
                if "_error" in location:
                    error_code = location.get("_error", "unknown")
                    error_message = location.get("_error_message", "Unknown error")
                    logger.warning(
                        f"Skipping error response from plugin: {error_code} - {error_message}"
                    )
                    continue

                # Use existing logic from your current implementation
                if "timestamp" in location and location["timestamp"]:
                    if isinstance(location["timestamp"], str):
                        try:
                            event_time = datetime.fromisoformat(
                                location["timestamp"].replace("Z", "+00:00")
                            ).replace(tzinfo=None)
                        except ValueError:
                            event_time = datetime.now(timezone.utc)
                    else:
                        event_time = location["timestamp"]
                else:
                    event_time = datetime.now(timezone.utc)

                time_str = event_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                stale_str = (event_time + timedelta(seconds=stale_time)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

                uid = location["uid"]

                # Determine COT type based on mode
                if cot_type_mode == "per_point" and "cot_type" in location:
                    point_cot_type = location["cot_type"]
                    logger.debug(
                        f"Custom: Using per-point CoT type: {point_cot_type} (mode: {cot_type_mode})"
                    )
                else:
                    point_cot_type = cot_type
                    logger.debug(
                        f"Custom: Using stream CoT type: {point_cot_type} (mode: {cot_type_mode}, has cot_type: {'cot_type' in location})"
                    )

                # Create COT event element
                cot_event = etree.Element("event")
                cot_event.set("version", "2.0")
                cot_event.set("uid", uid)
                cot_event.set("type", point_cot_type)
                cot_event.set("time", time_str)
                cot_event.set("start", time_str)
                cot_event.set("stale", stale_str)
                cot_event.set("how", "h-g-i-g-o")  # Use standard PyTAK "how" value

                # Add point element with proper attribute structure and safe conversions
                # Extract the conversions first, then format with bounds checking
                lat_val = max(
                    -90.0,
                    min(90.0, QueuedCOTService._safe_float_convert(location["lat"])),
                )
                lon_val = max(
                    -180.0,
                    min(180.0, QueuedCOTService._safe_float_convert(location["lon"])),
                )
                hae_val = QueuedCOTService._safe_float_convert(
                    location.get("altitude", location.get("hae", 0.0))
                )
                ce_val = QueuedCOTService._safe_float_convert(
                    location.get("accuracy", location.get("ce", 999999)), 999999
                )
                le_val = QueuedCOTService._safe_float_convert(
                    location.get("linear_error", location.get("le", 999999)), 999999
                )

                point_attr = {
                    "lat": f"{lat_val:.8f}",
                    "lon": f"{lon_val:.8f}",
                    "hae": f"{hae_val:.2f}",
                    "ce": f"{ce_val:.2f}",
                    "le": f"{le_val:.2f}",
                }
                etree.SubElement(cot_event, "point", attrib=point_attr)

                # Add detail element
                detail = etree.SubElement(cot_event, "detail")

                # Add contact with endpoint (important for TAK Server recognition)
                contact = etree.SubElement(detail, "contact")
                contact.set("callsign", str(location.get("name", "Unknown")))
                contact.set("endpoint", "*:-1:stcp")

                # Add track information with safe conversions
                if (
                    location.get("speed")
                    or location.get("heading")
                    or location.get("course")
                ):
                    track = etree.SubElement(detail, "track")

                    speed_val = max(
                        0.0,
                        QueuedCOTService._safe_float_convert(
                            location.get("speed", 0.0)
                        ),
                    )
                    course_val = (
                        QueuedCOTService._safe_float_convert(
                            location.get("heading", location.get("course", 0.0))
                        )
                        % 360.0
                    )

                    track.set("speed", f"{speed_val:.2f}")
                    track.set("course", f"{course_val:.2f}")

                # Add remarks if available
                if location.get("description"):
                    remarks = etree.SubElement(detail, "remarks")
                    remarks.text = str(location["description"])

                cot_events.append(
                    etree.tostring(cot_event, pretty_print=False, xml_declaration=False)
                )

            except Exception as e:
                logger.error(f"Error creating custom COT event: {e}")
                continue

        return cot_events

    @staticmethod
    async def _send_with_custom(events: List[bytes], tak_server) -> bool:
        """Send events using custom implementation"""
        return await QueuedCOTService._send_cot_to_tak_server_direct(events, tak_server)

    @staticmethod
    async def _send_cot_to_tak_server_direct(
        cot_events: List[bytes], tak_server
    ) -> bool:
        """Direct send implementation without PyTAK"""
        if not cot_events:
            logger.warning("No COT events to send")
            return True

        reader = None
        writer = None
        cert_path = None
        key_path = None

        try:
            ssl_context = None
            if tak_server.protocol.lower() in ["tls", "ssl"]:
                ssl_context = QueuedCOTService._create_ssl_context(tak_server)

                if tak_server.cert_p12 and len(tak_server.cert_p12) > 0:
                    try:
                        cert_pem, key_pem = QueuedCOTService._extract_p12_certificate(
                            tak_server.cert_p12, tak_server.get_cert_password()
                        )
                        cert_path, key_path = QueuedCOTService._create_temp_cert_files(
                            cert_pem, key_pem
                        )
                        ssl_context.load_cert_chain(
                            certfile=cert_path, keyfile=key_path
                        )
                        logger.debug(
                            f"Loaded client certificate for TAK server '{tak_server.name}'"
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to load P12 certificate for TAK server '{tak_server.name}': {e}"
                        )
                        raise

            logger.info(
                f"Connecting to {tak_server.host}:{tak_server.port} "
                f"using {'TLS' if ssl_context else 'TCP'}"
            )

            # Open connection
            if ssl_context:
                reader, writer = await asyncio.open_connection(
                    tak_server.host,
                    tak_server.port,
                    ssl=ssl_context,
                )
            else:
                reader, writer = await asyncio.open_connection(
                    tak_server.host, tak_server.port
                )

            # Send all events
            events_sent = 0
            for event in cot_events:
                writer.write(event)
                await writer.drain()
                events_sent += 1

            logger.info(
                f"Sent {events_sent} COT events to TAK server '{tak_server.name}'"
            )
            return True

        except Exception as e:
            logger.error(
                f"Failed to send COT events to TAK server '{tak_server.name}': {e}"
            )
            return False

        finally:
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception as e:
                    logger.warning(f"Error closing writer: {e}")

            # Clean up temporary certificate files
            if cert_path:
                QueuedCOTService._cleanup_temp_files(cert_path)
            if key_path:
                QueuedCOTService._cleanup_temp_files(key_path)

    @staticmethod
    def _create_ssl_context(tak_server):
        """Create SSL context for TAK server connection"""
        ssl_context = ssl.create_default_context()

        # Configure certificate verification based on server settings
        if not tak_server.verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            logger.warning(
                f"SSL certificate verification disabled for TAK server '{tak_server.name}'"
            )

        return ssl_context

    @staticmethod
    def _extract_p12_certificate(
        p12_data: bytes, password: Optional[str] = None
    ) -> Tuple[bytes, bytes]:
        """Extract certificate and key from P12 data"""
        try:
            password_bytes = password.encode("utf-8") if password else None
            private_key, certificate, additional_certificates = (
                pkcs12.load_key_and_certificates(p12_data, password_bytes)
            )

            cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
            key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )

            return cert_pem, key_pem

        except Exception as e:
            raise Exception(f"P12 certificate extraction failed: {str(e)}")

    @staticmethod
    def _create_temp_cert_files(cert_pem: bytes, key_pem: bytes) -> Tuple[str, str]:
        """Create temporary certificate files"""
        cert_fd, cert_path = tempfile.mkstemp(suffix=".pem", prefix="tak_cert_")
        key_fd, key_path = tempfile.mkstemp(suffix=".pem", prefix="tak_key_")

        try:
            with os.fdopen(cert_fd, "wb") as cert_file:
                cert_file.write(cert_pem)
            with os.fdopen(key_fd, "wb") as key_file:
                key_file.write(key_pem)
            return cert_path, key_path
        except Exception as e:
            try:
                os.close(cert_fd)
                os.close(key_fd)
                os.unlink(cert_path)
                os.unlink(key_path)
            except Exception as cleanup_error:
                logger.error(
                    f"Error cleaning up temporary Certificate Files: {cleanup_error}"
                )
            logger.error(f"Error creating temporary Certificate Files: {e}")
            raise

    @staticmethod
    def _cleanup_temp_files(*file_paths):
        """Clean up temporary files"""
        for path in file_paths:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                    logger.debug(f"Cleaned up temporary file: {path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temporary file {path}: {e}")


# Global queued service instance
_queued_service = None


def get_queued_cot_service(
    queue_config: Optional[Dict[str, Any]] = None
) -> QueuedCOTService:
    """
    Get the global queued COT service instance (singleton pattern).

    DEPRECATED: Use get_cot_service() from services.cot_service instead.
    This function is maintained for backward compatibility but will trigger
    singleton enforcement to prevent duplicate instances.

    Args:
        queue_config: Queue configuration dictionary (only used on first call)

    Returns:
        QueuedCOTService instance
    """
    global _queued_service
    if _queued_service is None:
        # Create new instance with bypass for compatibility
        logger.debug(
            f"Creating legacy queued COT service instance via get_queued_cot_service() at {datetime.now()}"
        )
        _queued_service = QueuedCOTService(queue_config, _bypass_singleton_check=True)
    return _queued_service


def reset_queued_cot_service():
    """Reset the global queued COT service (mainly for testing)"""
    global _queued_service
    if _queued_service is not None:
        logger.debug(
            f"Resetting legacy queued COT service instance {id(_queued_service)} at {datetime.now()}"
        )
    _queued_service = None
    # Also reset the singleton instance
    if QueuedCOTService._instance is not None:
        logger.debug(
            f"Resetting singleton instance {id(QueuedCOTService._instance)} at {datetime.now()}"
        )
        QueuedCOTService._instance = None
