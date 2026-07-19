"""
ABOUTME: Re-export shim for the plugin base classes, which now live in trakbridge_sdk.
ABOUTME: Wires core services into the SDK runtime registry on first import.

Author: Emfour Solutions
Created: 2025-07-05
"""

from trakbridge_sdk import (
    BaseGPSPlugin,
    BaseInboundPlugin,
    BaseOutputPlugin,
    CallsignMappable,
    FieldMetadata,
    PluginConfigField,
    PluginConfigMixin,
    PluginCustomComponent,
)

from plugins.sdk_wiring import configure_sdk

# Register core providers (encryption, plugin metadata, circuit breaker,
# CoT service) before any plugin class is used. Every plugin module imports
# this shim first, so the registry is always populated in time.
configure_sdk()

# Lazy import to avoid circular dependency
_logger_instance = None


def get_logger():
    """Get the module logger, initializing lazily to avoid circular imports"""
    global _logger_instance
    if _logger_instance is None:
        from services.logging_service import get_module_logger

        _logger_instance = get_module_logger(__name__)
    return _logger_instance


# For backwards compatibility - provide logger as module attribute
class _LoggerProxy:
    """Proxy that forwards all attribute access to the lazy logger"""

    def __getattr__(self, name):
        return getattr(get_logger(), name)


logger = _LoggerProxy()

__all__ = [
    "BaseGPSPlugin",
    "BaseInboundPlugin",
    "BaseOutputPlugin",
    "CallsignMappable",
    "FieldMetadata",
    "PluginConfigField",
    "PluginConfigMixin",
    "PluginCustomComponent",
    "get_logger",
    "logger",
]
