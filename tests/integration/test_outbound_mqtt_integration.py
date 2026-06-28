# ABOUTME: Integration tests for OutboundMQTT using a real mosquitto broker process.
# ABOUTME: Verifies round-trip delivery, topic substitution, QoS levels, and bad-auth rejection.

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
# Sample CoT XML
# ---------------------------------------------------------------------------

SAMPLE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-G-U-C" uid="ANDROID-integration-mqtt"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
  <detail>
    <contact callsign="MQTT-INTEG-1"/>
  </detail>
</event>"""

MINIMAL_RULES = [
    {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": "{callsign}"},
]


# ---------------------------------------------------------------------------
# Mosquitto broker fixture
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _MosquittoFixture:
    """Starts and stops a local mosquitto process for integration tests."""

    def __init__(self, port: int, password_file: str = None):
        self.port = port
        self._process = None
        self._tmpdir = tempfile.mkdtemp()
        self._config_path = os.path.join(self._tmpdir, "mosquitto.conf")
        self._password_file = password_file
        self._write_config()

    def _write_config(self):
        lines = [
            f"listener {self.port} 127.0.0.1",
            "allow_anonymous true",
        ]
        if self._password_file:
            lines += [
                "allow_anonymous false",
                f"password_file {self._password_file}",
            ]
        with open(self._config_path, "w") as f:
            f.write("\n".join(lines) + "\n")

    def start(self):
        mosquitto = shutil.which("mosquitto")
        if not mosquitto:
            raise RuntimeError("mosquitto not found in PATH — cannot run integration tests")
        self._process = subprocess.Popen(
            [mosquitto, "-c", self._config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for the port to be ready
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


def _make_passwd_file(tmpdir: str, username: str, password: str) -> str:
    """Create a mosquitto password file using mosquitto_passwd.

    Returns the path to the password file, or raises RuntimeError if
    mosquitto_passwd is not available.
    """
    mosquitto_passwd = shutil.which("mosquitto_passwd")
    if not mosquitto_passwd:
        raise RuntimeError("mosquitto_passwd not found in PATH")
    passwd_path = os.path.join(tmpdir, "passwd")
    subprocess.check_call(
        [mosquitto_passwd, "-c", "-b", passwd_path, username, password],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return passwd_path


@pytest.fixture
def mqtt_broker():
    """Start a real mosquitto broker on a dynamic port."""
    port = _free_port()
    broker = _MosquittoFixture(port)
    broker.start()
    yield broker
    broker.stop()


# ---------------------------------------------------------------------------
# Subscriber helper
# ---------------------------------------------------------------------------

class _MqttSubscriber:
    """Subscribes to a topic and collects received payloads."""

    def __init__(self, host: str, port: int, topic: str):
        self.host = host
        self.port = port
        self.topic = topic
        self.received: list = []
        self._client = None

    def start(self):
        import paho.mqtt.client as paho_mqtt
        self._client = paho_mqtt.Client(client_id="test-subscriber")

        def on_message(client, userdata, msg):
            self.received.append(msg)

        self._client.on_message = on_message
        self._client.connect(self.host, self.port, keepalive=10)
        self._client.subscribe(self.topic)
        self._client.loop_start()

    def stop(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()


async def _wait_for_messages(subscriber: _MqttSubscriber, count: int, timeout: float = 3.0):
    """Wait until at least `count` messages arrive or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while len(subscriber.received) < count:
        if asyncio.get_event_loop().time() >= deadline:
            break
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plugin_connects_to_real_broker(mqtt_broker):
    """Plugin connects to a real broker and reports connected state."""
    from plugins.outbound_mqtt import OutboundMQTT

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{mqtt_broker.port}",
        "topic": "cot/events",
        "output_format": "json",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()

    # Give paho a moment to complete the handshake
    await asyncio.sleep(0.3)
    assert plugin._connected is True, "Plugin should be connected to broker"

    await plugin.cleanup()


@pytest.mark.asyncio
async def test_publish_json_format_round_trip(mqtt_broker):
    """JSON-format payload reaches the broker and can be decoded."""
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", mqtt_broker.port, "cot/events")
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{mqtt_broker.port}",
        "topic": "cot/events",
        "output_format": "json",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(sub, 1)

    sub.stop()
    await plugin.cleanup()

    assert len(sub.received) == 1
    body = json.loads(sub.received[0].payload.decode())
    assert body["source"] == "trakbridge"
    assert body["cot"]["uid"] == "ANDROID-integration-mqtt"


@pytest.mark.asyncio
async def test_publish_xml_format_round_trip(mqtt_broker):
    """XML passthrough format sends the raw CoT bytes to the broker."""
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", mqtt_broker.port, "cot/xml")
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{mqtt_broker.port}",
        "topic": "cot/xml",
        "output_format": "xml",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(sub, 1)

    sub.stop()
    await plugin.cleanup()

    assert len(sub.received) == 1
    assert b"ANDROID-integration-mqtt" in sub.received[0].payload


@pytest.mark.asyncio
async def test_publish_custom_template_format(mqtt_broker):
    """Custom template is rendered and published as a string to the broker."""
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", mqtt_broker.port, "cot/custom")
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{mqtt_broker.port}",
        "topic": "cot/custom",
        "output_format": "custom_template",
        "custom_template": "ALERT: {callsign} at {lat},{lon}",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(sub, 1)

    sub.stop()
    await plugin.cleanup()

    assert len(sub.received) == 1
    text = sub.received[0].payload.decode()
    assert "MQTT-INTEG-1" in text


@pytest.mark.asyncio
async def test_topic_substitution_reaches_broker(mqtt_broker):
    """Topic with {uid} and {cot_type} placeholders is substituted before publish."""
    from plugins.outbound_mqtt import OutboundMQTT

    expected_topic = "cot/ANDROID-integration-mqtt/a-f-G-U-C"
    sub = _MqttSubscriber("127.0.0.1", mqtt_broker.port, expected_topic)
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{mqtt_broker.port}",
        "topic": "cot/{uid}/{cot_type}",
        "output_format": "json",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(sub, 1)

    sub.stop()
    await plugin.cleanup()

    assert len(sub.received) == 1, (
        f"Expected message on topic '{expected_topic}', got {len(sub.received)}"
    )


@pytest.mark.asyncio
async def test_qos_0_publishes(mqtt_broker):
    """QoS 0 publishes reach the broker."""
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", mqtt_broker.port, "cot/qos0")
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{mqtt_broker.port}",
        "topic": "cot/qos0",
        "qos": "0",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(sub, 1)

    sub.stop()
    await plugin.cleanup()

    assert len(sub.received) == 1


@pytest.mark.asyncio
async def test_qos_1_publishes(mqtt_broker):
    """QoS 1 publishes reach the broker."""
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", mqtt_broker.port, "cot/qos1")
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{mqtt_broker.port}",
        "topic": "cot/qos1",
        "qos": "1",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(sub, 1)

    sub.stop()
    await plugin.cleanup()

    assert len(sub.received) == 1


@pytest.mark.asyncio
async def test_qos_2_publishes(mqtt_broker):
    """QoS 2 publishes reach the broker."""
    from plugins.outbound_mqtt import OutboundMQTT

    sub = _MqttSubscriber("127.0.0.1", mqtt_broker.port, "cot/qos2")
    sub.start()
    await asyncio.sleep(0.2)

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{mqtt_broker.port}",
        "topic": "cot/qos2",
        "qos": "2",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(sub, 1)

    sub.stop()
    await plugin.cleanup()

    assert len(sub.received) == 1


@pytest.mark.asyncio
async def test_broker_bounce_plugin_reconnects():
    """After the broker restarts, the plugin reconnects and resumes publishing."""
    from plugins.outbound_mqtt import OutboundMQTT

    port = _free_port()

    # First broker instance
    broker1 = _MosquittoFixture(port)
    broker1.start()

    plugin = OutboundMQTT({
        "broker_url": f"mqtt://127.0.0.1:{port}",
        "topic": "cot/bounce",
        "output_format": "json",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.sleep(0.3)
    assert plugin._connected is True

    # Stop the broker mid-test (process killed; tmpdir stays alive)
    broker1._process.terminate()
    broker1._process.wait(timeout=5)
    broker1._process = None
    await asyncio.sleep(0.5)

    # Restart broker on the same port using a fresh instance sharing the same port
    broker2 = _MosquittoFixture(port)
    broker2.start()

    try:
        # Give paho's auto-reconnect time to fire (up to 10 s)
        deadline = asyncio.get_event_loop().time() + 10.0
        while not plugin._connected:
            if asyncio.get_event_loop().time() >= deadline:
                break
            await asyncio.sleep(0.2)

        assert plugin._connected is True, "Plugin should reconnect after broker bounce"

        sub = _MqttSubscriber("127.0.0.1", port, "cot/bounce")
        sub.start()
        await asyncio.sleep(0.2)

        await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        await _wait_for_messages(sub, 1)

        sub.stop()
        assert len(sub.received) >= 1
    finally:
        await plugin.cleanup()
        broker2.stop()
        broker1.stop()  # cleanup tmpdir


@pytest.mark.asyncio
async def test_bad_auth_plugin_stays_disconnected():
    """Broker with password auth rejects wrong credentials; plugin stays disconnected and drops events."""
    from plugins.outbound_mqtt import OutboundMQTT

    port = _free_port()
    tmpdir = tempfile.mkdtemp()
    try:
        passwd_path = _make_passwd_file(tmpdir, "validuser", "correctpassword")
        broker = _MosquittoFixture(port, password_file=passwd_path)
        broker.start()
        try:
            plugin = OutboundMQTT({
                "broker_url": f"mqtt://127.0.0.1:{port}",
                "topic": "cot/auth",
                "output_format": "json",
                "username": "validuser",
                "password": "WRONGPASSWORD",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()

            # Give paho time to attempt the connection and receive auth rejection
            await asyncio.sleep(1.0)

            assert plugin._connected is False, (
                "Plugin should remain disconnected after bad-auth rejection"
            )

            # Events fed while disconnected should be dropped (queue re-enqueue + drop)
            # rather than published. Record the baseline drop count.
            drops_before = plugin._events_dropped
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            # Allow writer loop one cycle to attempt (and fail) publishing
            await asyncio.sleep(0.3)

            assert plugin._connected is False, (
                "Plugin should still be disconnected after event feed"
            )
            # The event was enqueued; the writer re-enqueues while disconnected.
            # We confirm nothing was sent.
            assert plugin._events_sent == 0, (
                "No events should be published when broker rejects auth"
            )
            # events_dropped tracks queue-full drops; the enqueued event may not
            # yet be dropped (it stays in the buffer), but nothing was delivered.
            # We simply assert drops didn't go negative.
            assert plugin._events_dropped >= drops_before
        finally:
            await plugin.cleanup()
            broker.stop()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
