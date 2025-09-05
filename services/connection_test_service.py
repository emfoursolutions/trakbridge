"""
File: services/connection_test_service.py

Description:
    Connection testing service providing comprehensive validation and testing capabilities
    for stream connections in the TrakBridge application. This service handles
    both synchronous and asynchronous connection testing operations, supporting plugin-based
    architecture for various stream providers.

Key features:
    - Asynchronous and synchronous connection testing for plugin configurations
    - Individual and batch connection testing with concurrent execution support
    - Comprehensive validation of plugin configurations before testing
    - Integration with shared session manager for efficient resource utilization
    - Detailed connection test reporting with recommendations and diagnostics
    - Proper timeout handling and error management for robust operation
    - Thread pool executor for handling synchronous wrapper operations
    - Support for both new plugin configurations and existing stream testing
    - Device count reporting for successful connections to assess data availability
    - Clean resource management with proper cleanup and destructor patterns
    - Extensive logging and error handling for troubleshooting and monitoring
    - Flexible architecture supporting multiple plugin types and configurations

Author: Emfour Solutions
Created: 18-Jul-2025
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

import asyncio

# Standard library imports
import logging
from concurrent.futures import ThreadPoolExecutor

import aiohttp

# Module level logging
logger = logging.getLogger(__name__)


class ConnectionTestService:
    """Service for handling connection testing operations"""

    def __init__(self, plugin_manager, stream_manager):
        self.plugin_manager = plugin_manager
        self.stream_manager = stream_manager
        # Thread pool for handling async operations if needed
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ConnTest")

    async def test_plugin_connection(self, plugin_type, plugin_config):
        """Test connection for a plugin configuration"""
        try:
            if not plugin_type:
                return False, 0, "Plugin type required"

            # Get plugin instance
            plugin_instance = self.plugin_manager.get_plugin(plugin_type, plugin_config)
            if not plugin_instance:
                return False, 0, "Failed to create plugin instance"

            # Test connection using the shared session manager
            session = self.stream_manager.session_manager.session
            if not session:
                # If session not available, create a temporary one
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as temp_session:
                    success, device_count, error = (
                        await ConnectionTestService._perform_connection_test(
                            plugin_instance, temp_session
                        )
                    )
                    return success, device_count, error
            else:
                # Use shared session
                success, device_count, error = await ConnectionTestService._perform_connection_test(
                    plugin_instance, session
                )
                return success, device_count, error

        except asyncio.TimeoutError:
            logger.error(f"Connection test timed out for plugin {plugin_type}")
            return False, 0, "Connection test timed out"
        except Exception as e:
            logger.error(f"Error testing plugin connection for {plugin_type}: {e}")
            return False, 0, str(e)

    async def test_stream_connection(self, stream_id):
        """Test connection for an existing stream"""
        try:
            # Import here to avoid circular imports
            from models.stream import Stream

            stream = Stream.query.get(stream_id)
            if not stream:
                return False, 0, "Stream not found"

            # Get plugin configuration from the stream
            plugin_config = stream.get_plugin_config()
            plugin_type = stream.plugin_type

            # Use the plugin connection test method
            return await self.test_plugin_connection(plugin_type, plugin_config)

        except Exception as e:
            logger.error(f"Error testing stream connection for {stream_id}: {e}")
            return False, 0, str(e)

    @staticmethod
    async def _perform_connection_test(plugin_instance, session):
        """Perform the actual connection test with the plugin instance"""
        try:
            # Test connection using the plugin's enhanced test_connection method
            result = await plugin_instance.test_connection()

            if not result.get("success", False):
                # Return failure with error message
                error_msg = result.get("error", "Unknown connection error")
                return False, 0, error_msg

            # If successful, return success with device count
            device_count = result.get("device_count", 0)
            return True, device_count, None

        except Exception as e:
            logger.error(f"Error in connection test: {e}")
            return False, 0, str(e)

    def test_plugin_connection_sync(self, plugin_type, plugin_config, timeout=30):
        """Synchronous wrapper for testing plugin connections"""
        try:
            # Use the stream manager's background loop to run the test
            future = asyncio.run_coroutine_threadsafe(
                self.test_plugin_connection(plugin_type, plugin_config),
                self.stream_manager._loop,
            )
            success, device_count, error = future.result(timeout=timeout)

            # Return dictionary instead of tuple
            return {"success": success, "device_count": device_count, "error": error}

        except asyncio.TimeoutError:
            logger.error(f"Connection test timed out for plugin {plugin_type}")
            return {
                "success": False,
                "device_count": 0,
                "error": "Connection test timed out",
            }
        except Exception as e:
            logger.error(f"Error running sync connection test for {plugin_type}: {e}")
            return {
                "success": False,
                "device_count": 0,
                "error": f"Test execution failed: {str(e)}",
            }

    def discover_plugin_trackers_sync(self, plugin_type, plugin_config, timeout=30):
        """Synchronous method to discover actual tracker data for callsign mapping"""
        try:
            # Use the stream manager's background loop to run the discovery
            future = asyncio.run_coroutine_threadsafe(
                self.discover_plugin_trackers(plugin_type, plugin_config),
                self.stream_manager._loop,
            )
            result = future.result(timeout=timeout)
            return result

        except asyncio.TimeoutError:
            logger.error(f"Tracker discovery timed out for plugin {plugin_type}")
            return {
                "success": False,
                "tracker_data": [],
                "device_count": 0,
                "error": "Tracker discovery timed out",
            }
        except Exception as e:
            logger.error(f"Error running sync tracker discovery for {plugin_type}: {e}")
            return {
                "success": False,
                "tracker_data": [],
                "device_count": 0,
                "error": f"Tracker discovery failed: {str(e)}",
            }

    async def discover_plugin_trackers(self, plugin_type, plugin_config):
        """Discover actual tracker data for callsign mapping configuration"""
        try:
            if not plugin_type:
                return {
                    "success": False,
                    "tracker_data": [],
                    "device_count": 0,
                    "error": "Plugin type required",
                }

            # Get plugin instance
            plugin_instance = self.plugin_manager.get_plugin(plugin_type, plugin_config)
            if not plugin_instance:
                return {
                    "success": False,
                    "tracker_data": [],
                    "device_count": 0,
                    "error": "Failed to create plugin instance",
                }

            # Fetch actual location data using the shared session manager
            session = self.stream_manager.session_manager.session
            if not session:
                # If session not available, create a temporary one
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as temp_session:
                    tracker_data = await plugin_instance.fetch_locations(temp_session)
            else:
                # Use shared session
                tracker_data = await plugin_instance.fetch_locations(session)

            # Handle None response from plugin
            if tracker_data is None:
                return {
                    "success": False,
                    "tracker_data": [],
                    "device_count": 0,
                    "error": "No data returned from plugin",
                }

            # Empty list is valid (no trackers currently active)
            if not tracker_data:
                return {
                    "success": True,
                    "tracker_data": [],
                    "device_count": 0,
                    "error": None,
                }

            # Check for error data from plugin
            if (
                len(tracker_data) == 1
                and isinstance(tracker_data[0], dict)
                and tracker_data[0].get("_error")
            ):
                error_data = tracker_data[0]
                return {
                    "success": False,
                    "tracker_data": [],
                    "device_count": 0,
                    "error": error_data.get(
                        "_error_message", f"Plugin error: {error_data.get('_error')}"
                    ),
                }

            # Success - return the actual tracker data
            return {
                "success": True,
                "tracker_data": tracker_data,
                "device_count": len(tracker_data),
                "error": None,
            }

        except asyncio.TimeoutError:
            logger.error(f"Tracker discovery timed out for plugin {plugin_type}")
            return {
                "success": False,
                "tracker_data": [],
                "device_count": 0,
                "error": "Tracker discovery timed out",
            }
        except Exception as e:
            logger.error(f"Error discovering trackers for {plugin_type}: {e}")
            return {
                "success": False,
                "tracker_data": [],
                "device_count": 0,
                "error": str(e),
            }

    def test_stream_connection_sync(self, stream_id, timeout=30):
        """Synchronous wrapper for testing stream connections"""
        try:
            # Use the stream manager's background loop to run the test
            future = asyncio.run_coroutine_threadsafe(
                self.test_stream_connection(stream_id), self.stream_manager._loop
            )
            success, device_count, error = future.result(timeout=timeout)

            # Return dictionary instead of tuple
            return {"success": success, "device_count": device_count, "error": error}

        except asyncio.TimeoutError:
            logger.error(f"Connection test timed out for stream {stream_id}")
            return {
                "success": False,
                "device_count": 0,
                "error": "Connection test timed out",
            }
        except Exception as e:
            logger.error(f"Error running sync connection test for stream {stream_id}: {e}")
            return {
                "success": False,
                "device_count": 0,
                "error": f"Test execution failed: {str(e)}",
            }

    async def batch_test_connections(self, test_configs):
        """Test multiple connections in parallel"""
        try:
            tasks = []
            for config in test_configs:
                if "stream_id" in config:
                    # Test existing stream
                    task = self.test_stream_connection(config["stream_id"])
                else:
                    # Test plugin configuration
                    task = self.test_plugin_connection(
                        config["plugin_type"], config["plugin_config"]
                    )
                tasks.append(task)

            # Run all tests concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed_results.append(
                        {
                            "success": False,
                            "device_count": 0,
                            "error": str(result),
                            "config_index": i,
                        }
                    )
                else:
                    # result is now a 3-tuple: (success, device_count, error)
                    success, device_count, error = result
                    processed_results.append(
                        {
                            "success": success,
                            "device_count": device_count,
                            "error": error,
                            "config_index": i,
                        }
                    )

            return processed_results

        except Exception as e:
            logger.error(f"Error in batch connection test: {e}")
            return [
                {
                    "success": False,
                    "device_count": 0,
                    "error": str(e),
                    "config_index": i,
                }
                for i in range(len(test_configs))
            ]

    def validate_plugin_config(self, plugin_type, plugin_config):
        """Validate plugin configuration before testing"""
        try:
            metadata = self.plugin_manager.get_plugin_metadata(plugin_type)
            if not metadata:
                return False, ["Plugin metadata not found"]

            errors = []
            config_fields = metadata.get("config_fields", [])

            for field_data in config_fields:
                if isinstance(field_data, dict):
                    field_name = field_data.get("name")
                    required = field_data.get("required", False)

                    if required and (
                        field_name not in plugin_config or not plugin_config[field_name]
                    ):
                        errors.append(f"Required field '{field_name}' is missing or empty")

            return len(errors) == 0, errors

        except Exception as e:
            logger.error(f"Error validating plugin config for {plugin_type}: {e}")
            return False, [f"Validation error: {str(e)}"]

    def get_connection_test_report(self, plugin_type, plugin_config):
        """Generate a comprehensive connection test report"""
        try:
            report = {
                "plugin_type": plugin_type,
                "timestamp": asyncio.get_event_loop().time(),
                "validation_passed": False,
                "validation_errors": [],
                "connection_test_passed": False,
                "device_count": 0,
                "connection_error": None,
                "recommendations": [],
            }

            # First validate configuration
            valid, validation_errors = self.validate_plugin_config(plugin_type, plugin_config)
            report["validation_passed"] = valid
            report["validation_errors"] = validation_errors

            if not valid:
                report["recommendations"].append(
                    "Fix configuration validation errors before testing connection"
                )
                return report

            # Test connection
            result = self.test_plugin_connection_sync(plugin_type, plugin_config)
            report["connection_test_passed"] = result["success"]
            report["device_count"] = result["device_count"]
            report["connection_error"] = result["error"]

            # Add recommendations based on results
            if not result["success"]:
                report["recommendations"].extend(
                    [
                        "Check network connectivity to the data source",
                        "Verify authentication credentials are correct",
                        "Ensure the data source is accessible and responding",
                    ]
                )
            elif result["device_count"] == 0:
                report["recommendations"].append(
                    "Connection successful but no devices found - check data source configuration"
                )
            else:
                report["recommendations"].append(
                    f'Connection successful with {result["device_count"]} devices found'
                )

            return report

        except Exception as e:
            logger.error(f"Error generating connection test report: {e}")
            return {
                "plugin_type": plugin_type,
                "timestamp": asyncio.get_event_loop().time(),
                "validation_passed": False,
                "validation_errors": [f"Report generation error: {str(e)}"],
                "connection_test_passed": False,
                "device_count": 0,
                "connection_error": str(e),
                "recommendations": ["Fix the underlying error and try again"],
            }

    def cleanup(self):
        """Clean up resources"""
        try:
            self.executor.shutdown(wait=True)
            logger.info("ConnectionTestService cleanup completed")
        except Exception as e:
            logger.error(f"Error during ConnectionTestService cleanup: {e}")

    def __del__(self):
        """Destructor to ensure cleanup"""
        try:
            self.cleanup()
        except Exception as e:
            logger.debug(f"Destructor completed {e}")
