# ABOUTME: End-to-end tests for OutboundMQTT using plugin_manager discovery and a real broker.
# ABOUTME: Validates plugin discovery, mixed-batch processing, and buffer-overflow semantics.

import asyncio
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time

import pytest

# ---------------------------------------------------------------------------
# Sample CoT XML fixtures
# ---------------------------------------------------------------------------

FRIENDLY_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-G-U-C" uid="ANDROID-e2e-mqtt-friendly"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
  <detail>
    <contact callsign="FRIENDLY-MQTT"/>
  </detail>
</event>"""

HOSTILE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-h-G" uid="hostile-e2e-mqtt"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="h-e">
  <point lat="39.0" lon="-76.0" hae="100" ce="50" le="50"/>
  <detail>
    <contact callsign="HOSTILE-MQTT"/>
  </detail>
</event>"""

DRONE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-A-M-F-U" uid="DRONE-e2e-mqtt-001"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.9" lon="-77.0" hae="100" ce="5" le="5"/>
  <detail>
    <contact callsign="DRONE-MQTT"/>
  </detail>
</event>"""


def _make_cot_xml(uid: str, cot_type: str = "a-f-G-U-C") -> bytes:
    """Generate a CoT XML bytes for a given UID and type."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<event version="2.0" type="{cot_type}" uid="{uid}"'
        f' time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"'
        f' stale="2026-04-11T12:05:00Z" how="m-g">'
        f'<point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>'
        f'<detail><contact callsign="{uid}"/></detail>'
        f"</event>"
    ).encode()


# ---------------------------------------------------------------------------
# Mosquitto broker fixture (self-contained, no shared fixture dependency)
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _MosquittoFixture:
    def __init__(self, port: int):
        self.port = port
        self._process = None
        self._tmpdir = tempfile.mkdtemp()
        self._config_path = os.path.join(self._tmpdir, "mosquitto.conf")
        with open(self._config_path, "w") as f:
            f.write(
                f"listener {port} 127.0.0.1\n"
                "allow_anonymous true\n"
            )

    def start(self):
        mosquitto = shutil.which("mosquitto")
        if not mosquitto:
            raise RuntimeError("mosquitto not found in PATH")
        self._process = subprocess.Popen(
            [mosquitto, "-c", self._config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError(f"mosquitto did not start on port {self.port}")

    def stop(self):
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
        shutil.rmtree(self._tmpdir, ignore_errors=True)


@pytest.fixture
def e2e_broker():
    port = _free_port()
    broker = _MosquittoFixture(port)
    broker.start()
    yield broker
    broker.stop()


# ---------------------------------------------------------------------------
# Subscriber helper
# ---------------------------------------------------------------------------


class _MqttSubscriber:
    def __init__(self, host: str, port: int, topic: str):
        self.host = host
        self.port = port
        self.topic = topic
        self.received: list = []
        self._client = None

    def start(self):
        import paho.mqtt.client as paho_mqtt
        self._client = paho_mqtt.Client(client_id="e2e-subscriber")

        def on_message(client, userdata, msg):
            self.received.append(msg)

        self._client.on_message = on_message
        self._client.connect(self.host, self.port, keepalive=10)
        self._client.subscribe(self.topic, qos=0)
        self._client.loop_start()

    def stop(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()


async def _wait_for(sub: _MqttSubscriber, count: int, timeout: float = 4.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while len(sub.received) < count:
        if asyncio.get_event_loop().time() >= deadline:
            break
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Plugin discovery
# ---------------------------------------------------------------------------


def test_plugin_manager_discovers_outbound_mqtt():
    """plugin_manager.load_plugins_from_directory must find outbound_mqtt."""
    from plugins.plugin_manager import PluginManager

    manager = PluginManager()
    manager.load_plugins_from_directory("plugins")

    registered_names = list(manager.plugins.keys())
    assert "outbound_mqtt" in registered_names, (
        f"outbound_mqtt not found. Registered: {registered_names}"
    )


# ---------------------------------------------------------------------------
# Mixed-batch E2E tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_batch_only_matching_events_reach_broker(e2e_broker):
    """
    Batch of 20 events: friendly, hostile, drone, duplicates, out-of-geofence.
    Verify only the expected subset is published to the broker.
    """
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", e2e_broker.port, "cot/e2e/#")
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{e2e_broker.port}",
        "topic": "cot/e2e/{uid}",
        "output_format": "json",
        "dedup_enabled": "true",
        "dedup_ttl_seconds": "60",
        "message_rules": [
            # Only forward friendly CoT types
            {
                "cot_type_pattern": "a-f-*",
                "enabled": True,
                "format_template": "",
            },
        ],
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    # 20-event batch:
    # 5 unique friendly → should pass (5)
    # 5 duplicate friendly → dedup drops (5)
    # 5 hostile → rules drop (5)
    # 5 drone uid (friendly type) → should pass (5)
    unique_friendly = [_make_cot_xml(f"ANDROID-e2e-{i}") for i in range(5)]
    unique_drones = [
        _make_cot_xml(f"DRONE-e2e-{i}", "a-f-A-M-F-U") for i in range(5)
    ]
    hostile_events = [_make_cot_xml(f"hostile-e2e-{i}", "a-h-G") for i in range(5)]

    for xml in unique_friendly:
        await plugin.handle_cot_message(xml, tak_server_id=1)
    for xml in unique_friendly:  # duplicates
        await plugin.handle_cot_message(xml, tak_server_id=1)
    for xml in hostile_events:
        await plugin.handle_cot_message(xml, tak_server_id=1)
    for xml in unique_drones:
        await plugin.handle_cot_message(xml, tak_server_id=1)

    await _wait_for(sub, 10, timeout=5.0)
    sub.stop()
    await plugin.cleanup()

    stats = plugin.get_health_stats()
    # 10 messages published (5 friendly + 5 drone)
    assert stats["events_sent"] == 10, f"Got stats: {stats}"
    # 10 dropped (5 duplicates + 5 hostile)
    assert stats["events_dropped"] == 10, f"Got stats: {stats}"
    assert len(sub.received) == 10


@pytest.mark.asyncio
async def test_dedup_across_formats(e2e_broker):
    """Duplicate UID+type combination is only delivered once regardless of format."""
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", e2e_broker.port, "cot/dedup")
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{e2e_broker.port}",
        "topic": "cot/dedup",
        "output_format": "json",
        "dedup_enabled": "true",
        "dedup_ttl_seconds": "60",
        "message_rules": [
            {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
        ],
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    # Send same event three times
    for _ in range(3):
        await plugin.handle_cot_message(FRIENDLY_COT_XML, tak_server_id=1)

    await _wait_for(sub, 1)
    sub.stop()
    await plugin.cleanup()

    assert len(sub.received) == 1
    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 1
    assert stats["events_dropped"] == 2


@pytest.mark.asyncio
async def test_geofence_filters_outside_events(e2e_broker):
    """Events outside the geofence are dropped; events inside pass."""
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", e2e_broker.port, "cot/geo")
    sub.start()
    await asyncio.sleep(0.2)

    # Tight box covering only the FRIENDLY position (~38.897, -77.036)
    # HOSTILE at 39.0, -76.0 is outside
    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{e2e_broker.port}",
        "topic": "cot/geo",
        "output_format": "json",
        "dedup_enabled": "false",
        "global_geofence": {
            "enabled": True,
            "bounds": {
                "north": 38.95,
                "south": 38.85,
                "east": -76.9,
                "west": -77.1,
            },
        },
        "message_rules": [
            {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            {"cot_type_pattern": "a-h-*", "enabled": True, "format_template": ""},
        ],
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    await plugin.handle_cot_message(FRIENDLY_COT_XML, tak_server_id=1)  # inside
    await plugin.handle_cot_message(HOSTILE_COT_XML, tak_server_id=1)   # outside

    await _wait_for(sub, 1)
    sub.stop()
    await plugin.cleanup()

    assert len(sub.received) == 1
    body = json.loads(sub.received[0].payload.decode())
    assert body["cot"]["uid"] == "ANDROID-e2e-mqtt-friendly"

    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 1
    assert stats["events_dropped"] == 1


@pytest.mark.asyncio
async def test_message_rules_filter_by_cot_type(e2e_broker):
    """Message rules restrict publishing to the matched CoT type pattern."""
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", e2e_broker.port, "cot/rules")
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{e2e_broker.port}",
        "topic": "cot/rules",
        "output_format": "json",
        "dedup_enabled": "false",
        "message_rules": [
            # Only friendly ground tracks
            {"cot_type_pattern": "a-f-G-*", "enabled": True, "format_template": ""},
        ],
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    await plugin.handle_cot_message(FRIENDLY_COT_XML, tak_server_id=1)  # a-f-G-U-C → pass
    await plugin.handle_cot_message(DRONE_COT_XML, tak_server_id=1)     # a-f-A-M → drop
    await plugin.handle_cot_message(HOSTILE_COT_XML, tak_server_id=1)   # a-h-G → drop

    await _wait_for(sub, 1)
    sub.stop()
    await plugin.cleanup()

    assert len(sub.received) == 1
    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 1
    assert stats["events_dropped"] == 2


@pytest.mark.asyncio
async def test_buffer_overflow_drops_oldest(e2e_broker):
    """When buffer is full, each new event drops the oldest and counts it dropped."""
    from plugins.outbound_mqtt import OutboundMQTT

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{e2e_broker.port}",
        "topic": "cot/overflow",
        "output_format": "json",
        "stream_buffer_size": "3",
        "dedup_enabled": "false",
        "message_rules": [
            {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
        ],
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    # Force writer to stall: mark disconnected so writer re-enqueues rather than publishes
    plugin._connected = False

    # First 3 fill the queue; events 4-6 each cause one drop
    for i in range(6):
        xml = _make_cot_xml(f"ANDROID-overflow-{i}")
        await plugin.handle_cot_message(xml, tak_server_id=1)
        # Yield control so writer can observe disconnect and put items back
        await asyncio.sleep(0)

    # Allow the writer loop one tick to re-enqueue items it pulled while disconnected
    await asyncio.sleep(0.1)

    stats = plugin.get_health_stats()
    # Events 4, 5, 6 each triggered an overflow drop
    assert stats["events_dropped"] >= 3, f"Got stats: {stats}"
    await plugin.cleanup()


@pytest.mark.asyncio
async def test_max_rate_throttles_publish(e2e_broker):
    """With max_rate=1, a rapid burst drops all but the first event."""
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", e2e_broker.port, "cot/rate")
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{e2e_broker.port}",
        "topic": "cot/rate",
        "output_format": "json",
        "max_rate": "1",  # 1 event/sec max
        "dedup_enabled": "false",
        "message_rules": [
            {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
        ],
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    # Send 5 events instantly — only 1 should pass rate limiter
    for i in range(5):
        xml = _make_cot_xml(f"ANDROID-rate-{i}")
        await plugin.handle_cot_message(xml, tak_server_id=1)

    await _wait_for(sub, 1, timeout=3.0)
    sub.stop()
    await plugin.cleanup()

    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 1, f"Got stats: {stats}"
    assert stats["events_dropped"] == 4, f"Got stats: {stats}"
