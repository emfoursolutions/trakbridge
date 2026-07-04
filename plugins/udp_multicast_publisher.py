# ABOUTME: UDP multicast output plugin — re-emits CoT events received from a TAK server
# ABOUTME: to a LAN multicast group so local ATAK clients can receive them via Mesh SA.

import socket
from typing import Any, Dict, Optional, Set

import takproto
from takproto import TAKProtoVer

from plugins.base_plugin import BaseOutputPlugin, PluginConfigField

_logger_instance = None


def get_logger():
    global _logger_instance
    if _logger_instance is None:
        from services.logging_service import get_module_logger

        _logger_instance = get_module_logger(__name__)
    return _logger_instance


class _LoggerProxy:
    def __getattr__(self, name):
        return getattr(get_logger(), name)


logger = _LoggerProxy()

# TAK Protocol v1 Mesh SA magic prefix.
_TAKPROTO_MAGIC = b"\xbf\x01\xbf"

# Payload size that crosses typical Ethernet MTU — warn but still send.
_MTU_WARN_THRESHOLD = 1400


class UdpMulticastPublisher(BaseOutputPlugin):
    """
    Outbound plugin that re-emits CoT events received from a TAK server to a
    UDP multicast group. Companion to UdpMulticastListener for bidirectional
    LAN↔WAN bridging.

    Operates send-only — no IGMP join. Local ATAK clients on the LAN receive
    Mesh SA datagrams as normal UDP multicast.
    """

    PLUGIN_NAME = "udp_multicast_publisher"

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        self._socket: Optional[socket.socket] = None
        self._events_sent: int = 0
        self._events_dropped: int = 0
        # UIDs belonging to this TrakBridge instance (populated from TAK server
        # identity at start() time). Used to prevent echo loops when a paired
        # listener forwards packets back into the same host.
        self._own_uids: Set[str] = set()

    # ------------------------------------------------------------------
    # BaseOutputPlugin abstract interface
    # ------------------------------------------------------------------

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @classmethod
    def get_plugin_name(cls) -> str:
        return cls.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "UDP Multicast Publisher",
            "description": (
                "Re-emit CoT events received from a TAK server to a UDP multicast "
                "group. Local ATAK clients on the LAN receive Mesh SA datagrams as "
                "normal UDP multicast. Companion to the UDP Multicast CoT Bridge "
                "inbound plugin for bidirectional bridging."
            ),
            "icon": "fa-broadcast-tower",
            "category": "forwarding",
            "config_fields": [
                PluginConfigField(
                    name="multicast_group",
                    label="Multicast Group",
                    field_type="text",
                    required=True,
                    placeholder="239.2.3.1",
                    help_text="IPv4 multicast address (224.0.0.0/4). Defaults to the ATAK Mesh SA group.",
                    default_value="239.2.3.1",
                ),
                PluginConfigField(
                    name="multicast_port",
                    label="Multicast Port",
                    field_type="number",
                    required=True,
                    min_value=1,
                    max_value=65535,
                    default_value=6969,
                    help_text="Destination UDP port. Defaults to the ATAK Mesh SA port.",
                ),
                PluginConfigField(
                    name="multicast_ttl",
                    label="Multicast TTL",
                    field_type="number",
                    required=False,
                    min_value=1,
                    max_value=255,
                    default_value=1,
                    help_text=(
                        "IP_MULTICAST_TTL hop limit. 1 restricts traffic to the "
                        "local LAN segment (recommended). Increase only for routed "
                        "multicast deployments."
                    ),
                ),
                PluginConfigField(
                    name="bind_interface",
                    label="Bind Interface",
                    field_type="text",
                    required=False,
                    placeholder="0.0.0.0",
                    help_text=(
                        "Local IP of the NIC to send multicast from. Must be set "
                        "explicitly on multi-homed hosts or Docker containers — "
                        "0.0.0.0 lets the kernel pick via the default route, which "
                        "in a container is usually the Docker bridge (wrong interface "
                        "for LAN multicast)."
                    ),
                    default_value="0.0.0.0",
                ),
                PluginConfigField(
                    name="output_format",
                    label="Output Format",
                    field_type="select",
                    required=False,
                    default_value="xml",
                    options=[
                        {"value": "xml", "label": "CoT XML (compatible with all clients)"},
                        {
                            "value": "takproto",
                            "label": "TAK Protocol v1 (ATAK/WinTAK Mesh SA default)",
                        },
                    ],
                    help_text=(
                        "XML is compatible with all TAK clients. TAK Protocol v1 "
                        "(protobuf) is more compact and is the ATAK/WinTAK default "
                        "for Mesh SA, but requires ATAK 4.x+."
                    ),
                ),
                PluginConfigField(
                    name="max_packet_bytes",
                    label="Max Packet Bytes",
                    field_type="number",
                    required=False,
                    min_value=1,
                    max_value=65535,
                    default_value=65535,
                    help_text=(
                        "Events larger than this size (after encoding) are dropped "
                        "with a warning. Hard limit is 65535 (UDP datagram max)."
                    ),
                ),
                PluginConfigField(
                    name="drop_own_uid",
                    label="Drop Own UID (prevent echo loop)",
                    field_type="checkbox",
                    required=False,
                    default_value=True,
                    help_text=(
                        "When enabled, events whose UID matches TrakBridge's own "
                        "identity UID are not published. This prevents an echo loop "
                        "when a UDP Multicast CoT Bridge input plugin and this output "
                        "plugin are both active on the same host."
                    ),
                ),
            ],
            "help_sections": [
                {
                    "title": "Overview",
                    "content": [
                        "Receives CoT events from a TAK server and re-emits them as "
                        "UDP multicast datagrams.",
                        "Local ATAK devices that use LAN Mesh SA can receive positions "
                        "aggregated by the TAK server without needing a persistent TAK "
                        "server subscription.",
                        "Pair with the UDP Multicast CoT Bridge inbound plugin for "
                        "full bidirectional bridging.",
                    ],
                },
                {
                    "title": "Echo Loop Prevention",
                    "content": [
                        "If a UDP Multicast CoT Bridge listener and this publisher are "
                        "both active on the same host and multicast group, events "
                        "forwarded by TrakBridge will be re-received and re-published "
                        "endlessly.",
                        "Enable 'Drop Own UID' to suppress events whose UID matches "
                        "TrakBridge's own TAK server identity UID.",
                    ],
                },
                {
                    "title": "IP_MULTICAST_LOOP",
                    "content": [
                        "By default the kernel loops sent multicast back to the "
                        "sender's own sockets. This means a listener on the same host "
                        "will receive what this publisher sends.",
                        "The 'Drop Own UID' check catches events that originate from "
                        "this TrakBridge instance, preventing the loop in most cases.",
                    ],
                },
            ],
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        config = self.get_decrypted_config()

        # Collect identity UIDs from configured TAK servers to populate the
        # echo-loop filter before the first CoT arrives.
        if self.stream is not None:
            try:
                servers = list(self.stream.get_active_tak_servers() or [])
                for server in servers:
                    uid = getattr(server, "uid", None)
                    if uid:
                        self._own_uids.add(uid)
            except Exception as exc:
                logger.warning(f"UDP multicast publisher: could not load TAK server UIDs: {exc}")

        self._socket = self._open_socket(config)
        logger.info(
            f"UDP multicast publisher ready → "
            f"{config.get('multicast_group')}:{config.get('multicast_port')} "
            f"(format={config.get('output_format', 'xml')}, "
            f"ttl={config.get('multicast_ttl', 1)})"
        )

    async def cleanup(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception as exc:
                logger.debug(f"UDP multicast publisher: socket close error: {exc}")
            self._socket = None
        logger.info(
            f"UDP multicast publisher stopped — "
            f"sent={self._events_sent}, dropped={self._events_dropped}"
        )

    # ------------------------------------------------------------------
    # Socket setup
    # ------------------------------------------------------------------

    def _open_socket(self, config: Dict[str, Any]) -> socket.socket:
        ttl = int(config.get("multicast_ttl", 1))
        bind_iface = str(config.get("bind_interface") or "0.0.0.0")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

        if bind_iface and bind_iface != "0.0.0.0":
            packed_if = socket.inet_aton(bind_iface)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, packed_if)

        sock.setblocking(False)
        return sock

    # ------------------------------------------------------------------
    # CoT handler
    # ------------------------------------------------------------------

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        if self._socket is None:
            # Plugin not started yet — silently skip.
            return

        config = self.config

        # Echo-loop prevention: drop events whose UID matches our own identity.
        if bool(config.get("drop_own_uid", True)):
            uid = self._extract_uid(cot_xml)
            if uid and uid in self._own_uids:
                self._events_dropped += 1
                return

        # Encode the payload.
        output_format = str(config.get("output_format", "xml")).lower()
        payload = self._encode(cot_xml, output_format)
        if payload is None:
            self._events_dropped += 1
            return

        # Size guard.
        max_bytes = int(config.get("max_packet_bytes", 65535) or 65535)
        if len(payload) > max_bytes:
            logger.warning(
                f"UDP multicast publisher: dropping oversized event "
                f"({len(payload)} bytes > {max_bytes})"
            )
            self._events_dropped += 1
            return

        if len(payload) > _MTU_WARN_THRESHOLD:
            logger.debug(
                f"UDP multicast publisher: payload {len(payload)} bytes exceeds "
                f"typical MTU ({_MTU_WARN_THRESHOLD}) — fragmentation possible"
            )

        group = str(config.get("multicast_group", "239.2.3.1"))
        port = int(config.get("multicast_port", 6969))

        try:
            self._socket.sendto(payload, (group, port))
            self._events_sent += 1
        except Exception as exc:
            logger.error(f"UDP multicast publisher: sendto failed: {exc}")
            self._events_dropped += 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _encode(self, cot_xml: bytes, output_format: str) -> Optional[bytes]:
        """Return payload bytes ready for sendto, or None on encoding failure."""
        if output_format == "takproto":
            try:
                result = takproto.xml2proto(cot_xml, TAKProtoVer.MESH)
                return bytes(result)
            except Exception as exc:
                logger.warning(
                    f"UDP multicast publisher: takproto encode failed: {exc}"
                )
                return None
        # XML passthrough (default).
        return cot_xml

    @staticmethod
    def _extract_uid(cot_xml: bytes) -> str:
        """Pull uid attribute from CoT event. Returns '' on any failure."""
        try:
            from defusedxml import ElementTree as ET

            root = ET.fromstring(cot_xml)
            return root.get("uid") or ""
        except Exception:
            return ""
