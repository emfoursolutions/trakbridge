# ABOUTME: Wires core services into the trakbridge_sdk runtime provider registry.
# ABOUTME: configure_sdk() is idempotent and runs when plugins/base_plugin.py is first imported.

from typing import Any, Dict, Optional

_configured = False


def _make_encryption_service():
    from services.encryption_service import EncryptionService

    return EncryptionService()


def _lookup_plugin_metadata(plugin_type: str) -> Optional[Dict[str, Any]]:
    from plugins.plugin_manager import get_plugin_manager

    return get_plugin_manager().get_plugin_metadata(plugin_type)


def _lookup_cot_service():
    from services.cot_service import get_cot_service

    return get_cot_service()


def _make_circuit_breaker(plugin_name: str, health_check: Any) -> Any:
    # Imported lazily: importing anything from services at shim-import time
    # triggers services/__init__ -> stream_worker -> plugin_manager, a cycle
    from services.plugin_circuit_breaker import make_plugin_circuit_breaker

    return make_plugin_circuit_breaker(plugin_name, health_check)


def configure_sdk() -> None:
    """Register core providers with the SDK. Safe to call multiple times."""
    global _configured
    if _configured:
        return

    import trakbridge_sdk

    trakbridge_sdk.configure(
        encryption=_make_encryption_service,
        plugin_metadata=_lookup_plugin_metadata,
        circuit_breaker=_make_circuit_breaker,
        cot_service=_lookup_cot_service,
    )
    _configured = True
