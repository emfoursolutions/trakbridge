# Third-party imports

from flask import current_app
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from plugins.plugin_manager import PluginManager
    from services.stream_manager import StreamManager


def get_plugin_manager():
    """Get plugin manager from current app with error handling"""
    plugin_manager = getattr(current_app, 'plugin_manager', None)
    if plugin_manager is None:
        raise ValueError("Plugin manager not initialized in current_app")
    return plugin_manager


def get_stream_manager():
    """Get stream manager from current app with error handling"""
    stream_manager = getattr(current_app, 'stream_manager', None)
    if stream_manager is None:
        raise ValueError("Stream manager not initialized in current_app")
    return stream_manager
