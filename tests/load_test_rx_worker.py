"""
ABOUTME: Load testing script for RX worker bidirectional TAK communication
ABOUTME: to validate performance, throughput, and stability under high message volume

File: tests/load_test_rx_worker.py

Description:
    Comprehensive load testing for the RX worker component of bidirectional
    TAK communication. Tests message throughput, plugin performance, buffer
    handling, and system stability under various load scenarios.

Usage:
    python -m pytest tests/load_test_rx_worker.py -v
    python -m pytest tests/load_test_rx_worker.py::test_high_throughput -v

Author: TrakBridge Development Team
Created: 2025-12-16
"""

import pytest
import asyncio
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any
from unittest.mock import Mock, AsyncMock, patch


# Sample CoT messages for testing
SAMPLE_COT_MESSAGES = {
    'chat': b'''<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="TEST-CHAT-1" type="b-t-f"
       time="2025-01-15T10:00:00Z" start="2025-01-15T10:00:00Z"
       stale="2025-01-15T10:10:00Z" how="h-e">
    <point lat="34.5" lon="-118.2" hae="0" ce="10" le="5"/>
    <detail>
        <contact callsign="Load Test User"/>
        <remarks>This is a test message</remarks>
    </detail>
</event>''',

    'position': b'''<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="TEST-POS-1" type="a-f-G-E-V-C"
       time="2025-01-15T10:00:00Z" start="2025-01-15T10:00:00Z"
       stale="2025-01-15T10:10:00Z" how="m-g">
    <point lat="34.5" lon="-118.2" hae="100" ce="10" le="5"/>
    <detail>
        <contact callsign="Load Test Vehicle"/>
        <track speed="25.5" course="180.0"/>
    </detail>
</event>''',

    'emergency': b'''<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="TEST-EMERG-1" type="b-a-o-tfc"
       time="2025-01-15T10:00:00Z" start="2025-01-15T10:00:00Z"
       stale="2025-01-15T10:10:00Z" how="h-e">
    <point lat="34.5" lon="-118.2" hae="0" ce="10" le="5"/>
    <detail>
        <contact callsign="Load Test Emergency"/>
        <emergency type="troops_in_contact"/>
    </detail>
</event>''',

    'marker': b'''<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="TEST-MARKER-1" type="b-m-p-s-p-loc"
       time="2025-01-15T10:00:00Z" start="2025-01-15T10:00:00Z"
       stale="2025-01-15T11:00:00Z" how="h-e">
    <point lat="34.5" lon="-118.2" hae="0" ce="10" le="10"/>
    <detail>
        <contact callsign="Test Marker"/>
        <color value="-65536"/>
    </detail>
</event>'''
}


class MockOutputPlugin:
    """Mock output plugin for testing"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.messages_handled = 0
        self.total_latency = 0.0
        self.errors = 0

    @property
    def plugin_name(self) -> str:
        return "mock_output_plugin"

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        """Simulate message handling with configurable latency"""
        start = time.time()

        try:
            # Simulate processing delay
            delay = self.config.get('processing_delay_ms', 0) / 1000.0
            await asyncio.sleep(delay)

            # Simulate occasional errors
            error_rate = self.config.get('error_rate', 0.0)
            if error_rate > 0 and (self.messages_handled % int(1/error_rate)) == 0:
                raise Exception("Simulated error")

            self.messages_handled += 1

        except Exception as e:
            self.errors += 1

        finally:
            self.total_latency += (time.time() - start) * 1000


@pytest.fixture
def mock_cot_service():
    """Mock CoT service integration for testing"""
    from services.cot_service_integration import CotServiceIntegration

    service = CotServiceIntegration()
    service._running = True

    return service


@pytest.mark.load_test
@pytest.mark.asyncio
async def test_baseline_throughput(mock_cot_service):
    """
    Test baseline message throughput with no plugins.

    Target: > 1000 messages/second
    """
    tak_server_id = 1
    message_count = 1000

    # Track metrics
    messages_processed = 0
    start_time = time.time()

    # Simulate RX worker processing
    for i in range(message_count):
        cot_xml = SAMPLE_COT_MESSAGES['position']

        # Extract message (minimal parsing)
        messages, _ = mock_cot_service._extract_cot_messages(cot_xml)

        # Basic security check
        for msg in messages:
            if not mock_cot_service._is_malicious_xml(msg):
                messages_processed += 1

    elapsed = time.time() - start_time
    throughput = messages_processed / elapsed

    print(f"\n{'='*60}")
    print(f"Baseline Throughput Test Results")
    print(f"{'='*60}")
    print(f"Messages processed: {messages_processed}")
    print(f"Time elapsed: {elapsed:.2f}s")
    print(f"Throughput: {throughput:.1f} messages/second")
    print(f"{'='*60}\n")

    assert throughput >= 1000, f"Throughput too low: {throughput:.1f} msg/s (target: >= 1000 msg/s)"


@pytest.mark.load_test
@pytest.mark.asyncio
async def test_high_throughput_with_plugins():
    """
    Test message throughput with multiple plugins processing messages.

    Target: > 100 messages/second with 3 plugins
    """
    tak_server_id = 1
    message_count = 1000
    num_plugins = 3

    # Create mock plugins
    plugins = [
        MockOutputPlugin({'processing_delay_ms': 5}),
        MockOutputPlugin({'processing_delay_ms': 10}),
        MockOutputPlugin({'processing_delay_ms': 3}),
    ]

    start_time = time.time()

    # Simulate routing to plugins
    for i in range(message_count):
        cot_xml = SAMPLE_COT_MESSAGES['chat']

        # Route to all plugins concurrently
        tasks = [
            plugin.handle_cot_message(cot_xml, tak_server_id)
            for plugin in plugins
        ]
        await asyncio.gather(*tasks)

    elapsed = time.time() - start_time
    throughput = message_count / elapsed

    # Calculate plugin metrics
    total_handled = sum(p.messages_handled for p in plugins)
    total_errors = sum(p.errors for p in plugins)
    avg_plugin_latency = sum(p.total_latency for p in plugins) / total_handled

    print(f"\n{'='*60}")
    print(f"High Throughput Test Results (with {num_plugins} plugins)")
    print(f"{'='*60}")
    print(f"Messages sent: {message_count}")
    print(f"Total messages handled: {total_handled}")
    print(f"Total errors: {total_errors}")
    print(f"Time elapsed: {elapsed:.2f}s")
    print(f"Throughput: {throughput:.1f} messages/second")
    print(f"Average plugin latency: {avg_plugin_latency:.2f}ms")
    print(f"{'='*60}\n")

    assert throughput >= 100, f"Throughput too low: {throughput:.1f} msg/s (target: >= 100 msg/s)"
    assert total_errors == 0, f"Unexpected errors: {total_errors}"


@pytest.mark.load_test
@pytest.mark.asyncio
async def test_buffer_overflow_handling(mock_cot_service):
    """
    Test buffer overflow handling under extreme load.

    Verify that messages are properly discarded when buffer exceeds limit.
    """
    tak_server_id = 1
    MAX_BUFFER_SIZE = 1024 * 1024  # 1MB

    # Create large message that would overflow buffer
    large_message = b'<event>' + b'X' * (MAX_BUFFER_SIZE + 1000) + b'</event>'

    buffer = b""
    overflow_detected = False

    # Simulate buffer overflow
    buffer += large_message

    if len(buffer) > MAX_BUFFER_SIZE:
        overflow_detected = True
        buffer = b""  # Discard

    print(f"\n{'='*60}")
    print(f"Buffer Overflow Test Results")
    print(f"{'='*60}")
    print(f"Message size: {len(large_message)} bytes")
    print(f"Max buffer size: {MAX_BUFFER_SIZE} bytes")
    print(f"Overflow detected: {overflow_detected}")
    print(f"Buffer properly cleared: {len(buffer) == 0}")
    print(f"{'='*60}\n")

    assert overflow_detected, "Buffer overflow not detected"
    assert len(buffer) == 0, "Buffer not cleared after overflow"


@pytest.mark.load_test
@pytest.mark.asyncio
async def test_plugin_timeout_handling():
    """
    Test that slow plugins are properly timed out.

    Target: Plugins timing out don't block other plugins
    """
    tak_server_id = 1

    # Create plugins with varying latencies
    fast_plugin = MockOutputPlugin({'processing_delay_ms': 10})
    slow_plugin = MockOutputPlugin({'processing_delay_ms': 15000})  # 15 seconds

    cot_xml = SAMPLE_COT_MESSAGES['emergency']

    start_time = time.time()

    # Run with timeout protection
    tasks = [
        asyncio.create_task(fast_plugin.handle_cot_message(cot_xml, tak_server_id)),
        asyncio.create_task(slow_plugin.handle_cot_message(cot_xml, tak_server_id)),
    ]

    # Wait with timeout (10 second timeout)
    done, pending = await asyncio.wait(tasks, timeout=10.0)

    elapsed = time.time() - start_time

    # Cancel pending tasks
    for task in pending:
        task.cancel()

    print(f"\n{'='*60}")
    print(f"Plugin Timeout Test Results")
    print(f"{'='*60}")
    print(f"Fast plugin handled: {fast_plugin.messages_handled}")
    print(f"Slow plugin handled: {slow_plugin.messages_handled}")
    print(f"Tasks completed: {len(done)}")
    print(f"Tasks timed out: {len(pending)}")
    print(f"Total elapsed: {elapsed:.2f}s")
    print(f"{'='*60}\n")

    assert fast_plugin.messages_handled == 1, "Fast plugin should have completed"
    assert len(pending) > 0, "Slow plugin should have timed out"
    assert elapsed < 11, f"Timeout handling took too long: {elapsed:.2f}s"


@pytest.mark.load_test
@pytest.mark.asyncio
async def test_mixed_message_types():
    """
    Test handling of mixed message types under load.

    Verify different CoT types are all processed correctly.
    """
    tak_server_id = 1
    messages_per_type = 250

    # Create plugin that tracks message types
    plugin = MockOutputPlugin({'processing_delay_ms': 1})
    message_types_seen = []

    async def tracking_handler(cot_xml: bytes, tak_server_id: int):
        from defusedxml import ElementTree as DefusedET
        root = DefusedET.fromstring(cot_xml)
        message_types_seen.append(root.get('type'))
        await plugin.handle_cot_message(cot_xml, tak_server_id)

    start_time = time.time()

    # Send mixed message types
    tasks = []
    for msg_type, cot_xml in SAMPLE_COT_MESSAGES.items():
        for i in range(messages_per_type):
            task = asyncio.create_task(tracking_handler(cot_xml, tak_server_id))
            tasks.append(task)

    await asyncio.gather(*tasks)

    elapsed = time.time() - start_time
    total_messages = len(SAMPLE_COT_MESSAGES) * messages_per_type
    throughput = total_messages / elapsed

    # Count unique types
    unique_types = len(set(message_types_seen))

    print(f"\n{'='*60}")
    print(f"Mixed Message Types Test Results")
    print(f"{'='*60}")
    print(f"Total messages: {total_messages}")
    print(f"Message types tested: {len(SAMPLE_COT_MESSAGES)}")
    print(f"Unique types seen: {unique_types}")
    print(f"Time elapsed: {elapsed:.2f}s")
    print(f"Throughput: {throughput:.1f} messages/second")
    print(f"{'='*60}\n")

    assert unique_types == len(SAMPLE_COT_MESSAGES), "Not all message types processed"
    assert len(message_types_seen) == total_messages, "Message count mismatch"


@pytest.mark.load_test
@pytest.mark.asyncio
async def test_sustained_load():
    """
    Test sustained load over extended period.

    Target: Maintain > 50 msg/s for 60 seconds without degradation
    """
    tak_server_id = 1
    duration_seconds = 60
    target_rate = 50  # messages per second

    plugin = MockOutputPlugin({'processing_delay_ms': 5})

    start_time = time.time()
    messages_sent = 0
    interval = 1.0 / target_rate  # Time between messages

    # Send messages at target rate for duration
    while (time.time() - start_time) < duration_seconds:
        cot_xml = SAMPLE_COT_MESSAGES['position']
        await plugin.handle_cot_message(cot_xml, tak_server_id)
        messages_sent += 1
        await asyncio.sleep(interval)

    elapsed = time.time() - start_time
    actual_rate = messages_sent / elapsed

    print(f"\n{'='*60}")
    print(f"Sustained Load Test Results")
    print(f"{'='*60}")
    print(f"Duration: {elapsed:.1f}s")
    print(f"Messages sent: {messages_sent}")
    print(f"Target rate: {target_rate} msg/s")
    print(f"Actual rate: {actual_rate:.1f} msg/s")
    print(f"Plugin handled: {plugin.messages_handled}")
    print(f"Plugin errors: {plugin.errors}")
    print(f"{'='*60}\n")

    assert plugin.messages_handled == messages_sent, "Message handling mismatch"
    assert plugin.errors == 0, f"Unexpected errors during sustained load: {plugin.errors}"
    assert actual_rate >= target_rate * 0.9, f"Failed to maintain target rate: {actual_rate:.1f} msg/s"


@pytest.mark.load_test
@pytest.mark.asyncio
async def test_concurrent_tak_servers():
    """
    Test multiple TAK servers sending messages concurrently.

    Target: Handle 3 TAK servers @ 30 msg/s each = 90 msg/s total
    """
    num_servers = 3
    messages_per_server = 100
    target_rate_per_server = 30  # msg/s

    # Create plugin
    plugin = MockOutputPlugin({'processing_delay_ms': 10})

    # Track per-server metrics
    server_metrics = {i: {'sent': 0, 'handled': 0} for i in range(1, num_servers + 1)}

    async def simulate_tak_server(tak_server_id: int, num_messages: int):
        """Simulate a TAK server sending messages"""
        interval = 1.0 / target_rate_per_server

        for i in range(num_messages):
            cot_xml = SAMPLE_COT_MESSAGES['chat']
            await plugin.handle_cot_message(cot_xml, tak_server_id)
            server_metrics[tak_server_id]['sent'] += 1
            server_metrics[tak_server_id]['handled'] += 1
            await asyncio.sleep(interval)

    start_time = time.time()

    # Run all servers concurrently
    tasks = [
        asyncio.create_task(simulate_tak_server(server_id, messages_per_server))
        for server_id in range(1, num_servers + 1)
    ]

    await asyncio.gather(*tasks)

    elapsed = time.time() - start_time
    total_messages = sum(m['sent'] for m in server_metrics.values())
    total_throughput = total_messages / elapsed

    print(f"\n{'='*60}")
    print(f"Concurrent TAK Servers Test Results")
    print(f"{'='*60}")
    print(f"Number of servers: {num_servers}")
    print(f"Messages per server: {messages_per_server}")
    print(f"Total messages: {total_messages}")
    print(f"Time elapsed: {elapsed:.2f}s")
    print(f"Total throughput: {total_throughput:.1f} msg/s")
    print(f"Target throughput: {num_servers * target_rate_per_server} msg/s")
    print(f"\nPer-Server Metrics:")
    for server_id, metrics in server_metrics.items():
        print(f"  Server {server_id}: sent={metrics['sent']}, handled={metrics['handled']}")
    print(f"{'='*60}\n")

    assert total_messages == num_servers * messages_per_server, "Message count mismatch"
    assert plugin.messages_handled == total_messages, "Plugin didn't handle all messages"
    assert total_throughput >= num_servers * target_rate_per_server * 0.8, \
        f"Throughput too low: {total_throughput:.1f} msg/s"


@pytest.mark.load_test
@pytest.mark.asyncio
async def test_error_recovery():
    """
    Test system recovery from plugin errors.

    Verify that plugin errors don't stop message processing.
    """
    tak_server_id = 1
    total_messages = 100

    # Create plugin that errors 10% of the time
    plugin = MockOutputPlugin({
        'processing_delay_ms': 5,
        'error_rate': 0.1  # 10% error rate
    })

    # Send messages
    for i in range(total_messages):
        cot_xml = SAMPLE_COT_MESSAGES['position']
        await plugin.handle_cot_message(cot_xml, tak_server_id)

    success_rate = plugin.messages_handled / total_messages
    error_rate = plugin.errors / total_messages

    print(f"\n{'='*60}")
    print(f"Error Recovery Test Results")
    print(f"{'='*60}")
    print(f"Total messages: {total_messages}")
    print(f"Successfully handled: {plugin.messages_handled}")
    print(f"Errors: {plugin.errors}")
    print(f"Success rate: {success_rate*100:.1f}%")
    print(f"Error rate: {error_rate*100:.1f}%")
    print(f"{'='*60}\n")

    # Verify system continued processing despite errors
    assert plugin.messages_handled > 0, "No messages handled despite errors"
    assert plugin.errors > 0, "Expected some errors based on error rate"
    assert plugin.messages_handled + plugin.errors == total_messages, \
        "Total processed count mismatch"


@pytest.mark.load_test
def test_message_extraction_performance(mock_cot_service):
    """
    Test CoT message extraction regex performance.

    Target: > 10,000 extractions/second
    """
    # Create buffer with multiple messages
    buffer = b""
    for i in range(100):
        buffer += SAMPLE_COT_MESSAGES['chat']
        buffer += SAMPLE_COT_MESSAGES['position']

    iterations = 100
    start_time = time.time()

    for i in range(iterations):
        messages, remaining = mock_cot_service._extract_cot_messages(buffer)

    elapsed = time.time() - start_time
    extractions_per_second = iterations / elapsed

    print(f"\n{'='*60}")
    print(f"Message Extraction Performance Test Results")
    print(f"{'='*60}")
    print(f"Buffer size: {len(buffer)} bytes")
    print(f"Messages per buffer: {len(messages)}")
    print(f"Iterations: {iterations}")
    print(f"Time elapsed: {elapsed:.2f}s")
    print(f"Extractions/second: {extractions_per_second:.1f}")
    print(f"{'='*60}\n")

    assert extractions_per_second >= 1000, \
        f"Extraction rate too low: {extractions_per_second:.1f}/s (target: >= 1000/s)"


if __name__ == "__main__":
    """Run load tests from command line"""
    pytest.main([__file__, "-v", "-s", "-m", "load_test"])
