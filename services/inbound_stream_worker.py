"""
ABOUTME: Lifecycle manager for inbound (push-based) streams. Unlike StreamWorker,
ABOUTME: this worker has no poll loop — it ensures TAK workers are running and registers in the active stream registry for fast HTTP endpoint lookups.
"""

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.cot_service import get_cot_service

# Capture buffer limits
_MAX_CAPTURE_ENTRIES = 10
_MAX_CAPTURE_BYTES = 102_400  # ~100KB total raw body size

logger = logging.getLogger(__name__)

# Module-level registry: stream_id → InboundStreamWorker
# Provides O(1) lookup for the inbound HTTP endpoint without a DB query.
_active_inbound_streams: Dict[int, "InboundStreamWorker"] = {}
_registry_lock = threading.Lock()


def get_active_inbound_streams() -> Dict[int, "InboundStreamWorker"]:
    """Return a snapshot of the active inbound stream registry."""
    with _registry_lock:
        return dict(_active_inbound_streams)


class InboundStreamWorker:
    """
    Lifecycle manager for an inbound stream.

    Responsibilities:
        - Ensure persistent TAK workers are running for all target servers
        - Register/deregister in the in-memory active stream registry
        - Provide get_health_status() compatible with StreamManager expectations

    Unlike StreamWorker, this class does NOT run a poll loop. The HTTP endpoint
    (routes/inbound.py) drives data flow; this worker just keeps the downstream
    TAK connections alive.
    """

    def __init__(self, stream, session_manager, db_manager):
        self.stream = stream
        self.session_manager = session_manager
        self.db_manager = db_manager
        self.logger = logging.getLogger(f"inbound_worker.{stream.name}")

        self.running = False
        self.task = None  # No poll task — always None
        self._startup_complete = False
        self._tak_worker_ensured = False
        self._start_lock = asyncio.Lock()

        # Preview capture buffer — ephemeral ring buffer for debugging
        self._capture_buffer: List[Dict[str, Any]] = []
        self._capture_lock = threading.Lock()

    @property
    def startup_complete(self):
        return self._startup_complete

    async def start(self) -> bool:
        """
        Initialize persistent TAK workers and register in the active stream registry.

        Returns True if at least one TAK worker was successfully started.
        """
        async with self._start_lock:
            if self.running and self._startup_complete:
                self.logger.info(
                    f"Inbound stream '{self.stream.name}' is already running"
                )
                return True

            try:
                target_servers = self.stream.get_all_tak_servers()
                if not target_servers:
                    self.logger.error(
                        f"No TAK servers configured for inbound stream '{self.stream.name}'"
                    )
                    return False

                self.logger.info(
                    f"Starting inbound stream '{self.stream.name}' "
                    f"(ID: {self.stream.id}) with {len(target_servers)} TAK server(s)"
                )

                cot_service = get_cot_service()
                workers_initialized = 0

                for server in target_servers:
                    try:
                        success = await cot_service.start_worker(server)
                        if success:
                            workers_initialized += 1
                        else:
                            self.logger.warning(
                                f"Failed to start TAK worker for server {server.name}"
                            )
                    except Exception as e:
                        self.logger.error(
                            f"Error starting TAK worker for server {server.name}: {e}",
                            exc_info=True,
                        )

                if workers_initialized == 0:
                    self.logger.error(
                        f"Failed to initialize any TAK workers for "
                        f"inbound stream '{self.stream.name}'"
                    )
                    return False

                if workers_initialized < len(target_servers):
                    self.logger.warning(
                        f"Only {workers_initialized}/{len(target_servers)} "
                        f"TAK workers initialized for inbound stream '{self.stream.name}'"
                    )

                self.running = True
                self._startup_complete = True
                self._tak_worker_ensured = True

                # Register in the active stream registry
                with _registry_lock:
                    _active_inbound_streams[self.stream.id] = self

                self.logger.info(
                    f"Inbound stream '{self.stream.name}' started successfully"
                )
                return True

            except Exception as e:
                self.logger.error(
                    f"Failed to start inbound stream '{self.stream.name}': {e}",
                    exc_info=True,
                )
                self.running = False
                self._startup_complete = False
                return False

    async def stop(self, skip_db_update=False):
        """
        Deregister from the active stream registry and mark as stopped.

        TAK workers are NOT stopped here — they are shared resources managed
        by the persistent COT service. Other streams may depend on them.
        """
        async with self._start_lock:
            if not self.running:
                self.logger.info(
                    f"Inbound stream '{self.stream.name}' is not running, nothing to stop"
                )
                return

            self.logger.info(
                f"Stopping inbound stream '{self.stream.name}' "
                f"(skip_db_update={skip_db_update})"
            )

            self.running = False
            self._startup_complete = False
            self._tak_worker_ensured = False

            # Deregister from the active stream registry
            with _registry_lock:
                _active_inbound_streams.pop(self.stream.id, None)

            self.clear_captured_payloads()

            self.logger.info(
                f"Inbound stream '{self.stream.name}' stopped successfully"
            )

    # ----- Capture buffer for preview mode -----

    def capture_payload(
        self,
        raw_body: bytes,
        content_type: str,
        headers: Dict[str, str],
        source_ip: str,
        mapped_result: List[Dict[str, Any]],
    ) -> None:
        """
        Store a raw payload and its mapped result in the ring buffer.

        Masks the Authorization header before storing. Evicts oldest
        entries when the buffer exceeds max count or total byte size.
        """
        safe_headers = dict(headers)
        auth = safe_headers.get("Authorization", "")
        if auth:
            # Mask to last 4 chars
            masked = "****" + auth[-4:] if len(auth) > 4 else "****"
            safe_headers["Authorization"] = masked

        entry = {
            "raw_body": raw_body,
            "content_type": content_type,
            "headers": safe_headers,
            "source_ip": source_ip,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "mapped_result": mapped_result,
        }

        with self._capture_lock:
            self._capture_buffer.append(entry)

            # Evict oldest if count exceeds max
            while len(self._capture_buffer) > _MAX_CAPTURE_ENTRIES:
                self._capture_buffer.pop(0)

            # Evict oldest if total raw body size exceeds cap
            while (
                len(self._capture_buffer) > 1
                and sum(
                    len(e["raw_body"]) for e in self._capture_buffer
                ) > _MAX_CAPTURE_BYTES
            ):
                self._capture_buffer.pop(0)

    def get_captured_payloads(self) -> List[Dict[str, Any]]:
        """Return a copy of the capture buffer."""
        with self._capture_lock:
            return list(self._capture_buffer)

    def clear_captured_payloads(self) -> None:
        """Clear the capture buffer."""
        with self._capture_lock:
            self._capture_buffer.clear()

    def get_health_status(self) -> Dict:
        """
        Return health status compatible with StreamManager expectations.

        Includes stream_mode to distinguish from poll-based StreamWorker status.
        Omits poll-specific fields (consecutive_errors, last_successful_poll).
        """
        persistent_worker_status = None
        if self.stream.tak_server:
            try:
                persistent_worker_status = get_cot_service().get_worker_status(
                    self.stream.tak_server.id
                )
            except Exception:
                persistent_worker_status = None

        return {
            "running": self.running,
            "startup_complete": self._startup_complete,
            "tak_worker_ensured": self._tak_worker_ensured,
            "stream_mode": "inbound",
            "task_done": None,  # No poll task
            "task_cancelled": None,  # No poll task
            "persistent_worker_status": persistent_worker_status,
            "total_persistent_workers": len(get_cot_service().workers),
            "total_persistent_queues": len(get_cot_service().queues),
        }
