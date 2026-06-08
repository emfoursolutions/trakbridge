"""
ABOUTME: Service for processing inbound push data into CoT events and distributing
ABOUTME: them to configured TAK servers via the existing queue infrastructure.
"""

import logging
from typing import Any, Dict, List

from services.cot_service_integration import get_queued_cot_service

logger = logging.getLogger(__name__)


class InboundCOTService:
    """
    Converts inbound location data to CoT XML and distributes to TAK servers.

    Reuses the existing QueuedCOTService for CoT creation and queue management,
    ensuring inbound data flows through the same pipeline as poll-based streams.
    """

    async def process_inbound_locations(
        self,
        locations: List[Dict[str, Any]],
        stream,
        cot_type: str = None,
        cot_stale_time: int = None,
    ) -> Dict[str, Any]:
        """
        Process inbound locations into CoT events and enqueue for TAK distribution.

        Args:
            locations: List of location dictionaries from plugin transform_payload
            stream: Stream model instance with CoT config and TAK server associations

        Returns:
            Result dict with keys: success, events_created, servers, error (on failure)
        """
        if not locations:
            return {"success": False, "error": "Empty location list"}

        target_servers = stream.get_active_tak_servers()
        if not target_servers:
            return {"success": False, "error": "No TAK servers configured for stream"}

        # Create CoT events from locations
        cot_service = get_queued_cot_service()
        try:
            cot_events = await cot_service.create_cot_events(
                locations,
                cot_type or stream.cot_type,
                cot_stale_time or stream.cot_stale_time,
                stream.cot_type_mode,
            )
        except Exception as e:
            logger.error(
                f"CoT creation failed for stream {stream.id}: {e}", exc_info=True
            )
            return {"success": False, "error": f"CoT creation failed: {e}"}

        if not cot_events:
            return {"success": False, "error": "No CoT events generated from locations"}

        # Distribute to all configured TAK servers with failure isolation
        server_results = {}
        for server in target_servers:
            server_results[server.name] = await self._enqueue_for_server(
                cot_service, cot_events, server
            )

        any_success = any(r["success"] for r in server_results.values())

        return {
            "success": any_success,
            "events_created": len(cot_events),
            "servers": server_results,
        }

    async def _enqueue_for_server(
        self, cot_service, cot_events: List[bytes], server
    ) -> Dict[str, Any]:
        """
        Ensure worker is running and enqueue events for a single TAK server.

        Args:
            cot_service: QueuedCOTService instance
            cot_events: List of CoT XML bytes
            server: TakServer model instance

        Returns:
            Dict with success status and events_enqueued count
        """
        try:
            await cot_service.start_worker(server)

            enqueued = 0
            for event in cot_events:
                if await cot_service.enqueue_event(event, server.id):
                    enqueued += 1

            return {"success": True, "events_enqueued": enqueued}

        except Exception as e:
            logger.error(
                f"Failed to enqueue events for TAK server {server.name} "
                f"(ID: {server.id}): {e}",
                exc_info=True,
            )
            return {"success": False, "events_enqueued": 0, "error": str(e)}
