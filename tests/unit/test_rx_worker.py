"""
ABOUTME: Unit tests for the RX worker bidirectional TAK communication
ABOUTME: Tests message extraction, malicious XML detection, and plugin routing
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch

from services.cot_service_integration import QueuedCOTService
from services.cot_service import reset_cot_service
from plugins.base_plugin import BaseOutputPlugin


class TestRXWorkerMessageExtraction:
    """Test CoT message extraction from buffer."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton before and after each test."""
        reset_cot_service()
        yield
        reset_cot_service()

    @pytest.fixture
    def service(self):
        """Create a COT service instance."""
        with (
            patch("services.cot_service_integration.get_queue_manager"),
            patch("services.cot_service_integration.get_queue_monitoring_service"),  # noqa: E501
        ):
            return QueuedCOTService(_bypass_singleton_check=True)

    def test_extract_single_complete_message(self, service):
        """Test extracting a single complete CoT message."""
        buffer = b'<event uid="test" type="a-f-G"><point lat="1" lon="2"/></event>'  # noqa: E501
        messages, remaining = service._extract_cot_messages(buffer)

        assert len(messages) == 1
        assert messages[0] == buffer
        assert remaining == b""

    def test_extract_multiple_complete_messages(self, service):
        """Test extracting multiple complete CoT messages."""
        msg1 = b'<event uid="test1" type="a-f-G"><point lat="1" lon="2"/></event>'  # noqa: E501
        msg2 = b'<event uid="test2" type="a-f-G"><point lat="3" lon="4"/></event>'  # noqa: E501
        buffer = msg1 + msg2

        messages, remaining = service._extract_cot_messages(buffer)

        assert len(messages) == 2
        assert messages[0] == msg1
        assert messages[1] == msg2
        assert remaining == b""

    def test_extract_with_incomplete_message(self, service):
        """Test buffer with incomplete message at end."""
        msg1 = b'<event uid="test1" type="a-f-G"><point lat="1" lon="2"/></event>'  # noqa: E501
        incomplete = b'<event uid="test2" type="a-f-G"><point lat="3"'
        buffer = msg1 + incomplete

        messages, remaining = service._extract_cot_messages(buffer)

        assert len(messages) == 1
        assert messages[0] == msg1
        assert remaining == incomplete

    def test_extract_no_complete_messages(self, service):
        """Test buffer with only incomplete message."""
        buffer = b'<event uid="test" type="a-f-G"><point'

        messages, remaining = service._extract_cot_messages(buffer)

        assert len(messages) == 0
        assert remaining == buffer

    def test_extract_empty_buffer(self, service):
        """Test extraction from empty buffer."""
        buffer = b""

        messages, remaining = service._extract_cot_messages(buffer)

        assert len(messages) == 0
        assert remaining == b""

    def test_extract_with_multiline_message(self, service):
        """Test extracting message with newlines."""
        buffer = b"""<event uid="test" type="a-f-G">
    <point lat="1" lon="2"/>
    <detail>
        <contact callsign="Test"/>
    </detail>
</event>"""

        messages, remaining = service._extract_cot_messages(buffer)

        assert len(messages) == 1
        assert b"<event" in messages[0]
        assert b"</event>" in messages[0]
        assert remaining == b""


class TestRXWorkerMaliciousXMLDetection:
    """Test malicious XML detection."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton before and after each test."""
        reset_cot_service()
        yield
        reset_cot_service()

    @pytest.fixture
    def service(self):
        """Create a COT service instance."""
        with (
            patch("services.cot_service_integration.get_queue_manager"),
            patch("services.cot_service_integration.get_queue_monitoring_service"),  # noqa: E501
        ):
            return QueuedCOTService(_bypass_singleton_check=True)

    def test_valid_cot_xml_not_malicious(self, service):
        """Test that valid CoT XML is not flagged as malicious."""
        cot_xml = b'<event uid="test" type="a-f-G"><point lat="1" lon="2"/></event>'  # noqa: E501

        assert not service._is_malicious_xml(cot_xml)

    def test_xxe_attack_detected(self, service):
        """Test that XXE attack patterns are detected."""
        # XXE attack with ENTITY
        xxe_xml = b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><event>&xxe;</event>'  # noqa: E501

        assert service._is_malicious_xml(xxe_xml)

    def test_doctype_attack_detected(self, service):
        """Test that DOCTYPE declarations are detected."""
        doctype_xml = b'<!DOCTYPE event><event uid="test"/>'

        assert service._is_malicious_xml(doctype_xml)

    def test_billion_laughs_attack_detected(self, service):
        """Test that billion laughs attacks are detected."""
        # Create deeply nested XML (exceeds 1000 tags)
        nested_xml = b"<a>" * 1001 + b"test" + b"</a>" * 1001

        assert service._is_malicious_xml(nested_xml)

    def test_normal_nested_xml_not_malicious(self, service):
        """Test that normal nested XML is not flagged."""
        # Reasonable nesting level
        nested_xml = b"""<event>
    <point lat="1" lon="2"/>
    <detail>
        <contact callsign="Test">
            <custom>
                <field1>value1</field1>
            </custom>
        </contact>
    </detail>
</event>"""

        assert not service._is_malicious_xml(nested_xml)


class TestRXWorkerPluginRouting:
    """Test routing CoT messages to output plugins."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton before and after each test."""
        reset_cot_service()
        yield
        reset_cot_service()

    @pytest.fixture
    def service(self):
        """Create a COT service instance."""
        with (
            patch("services.cot_service_integration.get_queue_manager"),
            patch("services.cot_service_integration.get_queue_monitoring_service"),  # noqa: E501
        ):
            return QueuedCOTService(_bypass_singleton_check=True)

    @pytest.fixture
    def mock_output_plugin(self):
        """Create a mock output plugin."""
        plugin = Mock(spec=BaseOutputPlugin)
        plugin.handle_cot_message = AsyncMock()
        return plugin

    @pytest.fixture
    def mock_gps_plugin(self):
        """Create a mock GPS plugin (should be skipped)."""
        from plugins.base_plugin import BaseGPSPlugin
        plugin = Mock(spec=BaseGPSPlugin)
        return plugin

    @pytest.mark.asyncio
    async def test_route_to_output_plugin(
        self, service, mock_output_plugin
    ):
        """Test routing CoT message to output plugin."""
        cot_xml = b'<event uid="test" type="a-f-G"><point lat="1" lon="2"/></event>'  # noqa: E501
        tak_server_id = 1

        # Mock the stream and plugin manager
        mock_stream = Mock()
        mock_stream.plugin_type = "slack_handler"
        mock_stream.get_config.return_value = {}

        with (
            patch("models.stream.Stream") as mock_stream_class,
            patch("sqlalchemy.or_"),
            patch("plugins.plugin_manager.get_plugin_manager") as mock_pm,
        ):
            mock_stream_class.query.filter.return_value.all.return_value = [mock_stream]  # noqa: E501
            mock_pm.return_value.get_plugin.return_value = mock_output_plugin

            await service._route_cot_to_plugins(cot_xml, tak_server_id)

            # Verify plugin was called
            mock_output_plugin.handle_cot_message.assert_called_once_with(
                cot_xml, tak_server_id
            )

    @pytest.mark.asyncio
    async def test_skip_gps_plugin(self, service, mock_gps_plugin):
        """Test that GPS plugins are skipped during routing."""
        cot_xml = b'<event uid="test" type="a-f-G"><point lat="1" lon="2"/></event>'  # noqa: E501
        tak_server_id = 1

        # Mock the stream and plugin manager
        mock_stream = Mock()
        mock_stream.plugin_type = "traccar_plugin"
        mock_stream.get_config.return_value = {}

        with (
            patch("models.stream.Stream") as mock_stream_class,
            patch("sqlalchemy.or_"),
            patch("plugins.plugin_manager.get_plugin_manager") as mock_pm,
        ):
            mock_stream_class.query.filter.return_value.all.return_value = [
                mock_stream
            ]
            mock_pm.return_value.get_plugin.return_value = mock_gps_plugin

            await service._route_cot_to_plugins(cot_xml, tak_server_id)

            # Verify GPS plugin was NOT called (doesn't have
            # handle_cot_message)
            assert not hasattr(mock_gps_plugin, 'handle_cot_message') or \
                not mock_gps_plugin.handle_cot_message.called

    @pytest.mark.asyncio
    async def test_route_with_plugin_timeout(
        self, service, mock_output_plugin
    ):
        """Test plugin timeout handling."""
        cot_xml = b'<event uid="test" type="a-f-G"><point lat="1" lon="2"/></event>'  # noqa: E501
        tak_server_id = 1

        # Make plugin timeout
        async def slow_handler(*args):
            await asyncio.sleep(15)  # Exceeds 10s timeout

        mock_output_plugin.handle_cot_message = slow_handler

        mock_stream = Mock()
        mock_stream.plugin_type = "slack_handler"
        mock_stream.get_config.return_value = {}

        with (
            patch("models.stream.Stream") as mock_stream_class,
            patch("sqlalchemy.or_"),
            patch("plugins.plugin_manager.get_plugin_manager") as mock_pm,
            patch("services.cot_service_integration.logger") as mock_logger,
        ):
            mock_stream_class.query.filter.return_value.all.return_value = [
                mock_stream
            ]
            mock_pm.return_value.get_plugin.return_value = mock_output_plugin

            # Should not raise, should handle timeout gracefully
            await service._route_cot_to_plugins(cot_xml, tak_server_id)

            # Verify timeout was logged
            assert any(
                'timed out' in str(call)
                for call in mock_logger.warning.call_args_list
            )

    @pytest.mark.asyncio
    async def test_route_with_plugin_error(
        self, service, mock_output_plugin
    ):
        """Test plugin error handling."""
        cot_xml = b'<event uid="test" type="a-f-G"><point lat="1" lon="2"/></event>'  # noqa: E501
        tak_server_id = 1

        # Make plugin raise error
        mock_output_plugin.handle_cot_message.side_effect = Exception(
            "Plugin error"
        )

        mock_stream = Mock()
        mock_stream.plugin_type = "slack_handler"
        mock_stream.get_config.return_value = {}

        with (
            patch("models.stream.Stream") as mock_stream_class,
            patch("sqlalchemy.or_"),
            patch("plugins.plugin_manager.get_plugin_manager") as mock_pm,
            patch("services.cot_service_integration.logger") as mock_logger,
        ):
            mock_stream_class.query.filter.return_value.all.return_value = [
                mock_stream
            ]
            mock_pm.return_value.get_plugin.return_value = mock_output_plugin

            # Should not raise, should handle error gracefully
            await service._route_cot_to_plugins(cot_xml, tak_server_id)

            # Verify error was logged
            assert any(
                'failed' in str(call).lower()
                for call in mock_logger.error.call_args_list
            )


class TestRXWorkerIntegration:
    """Integration tests for RX worker."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton before and after each test."""
        reset_cot_service()
        yield
        reset_cot_service()

    @pytest.fixture
    def service(self):
        """Create a COT service instance."""
        with (
            patch("services.cot_service_integration.get_queue_manager"),
            patch("services.cot_service_integration.get_queue_monitoring_service"),  # noqa: E501
        ):
            service = QueuedCOTService(_bypass_singleton_check=True)
            service._running = True
            return service

    @pytest.mark.asyncio
    async def test_rx_worker_reads_and_routes_messages(self, service):
        """Test RX worker reading and routing messages."""
        # Create mock reader with CoT data
        mock_reader = AsyncMock()
        cot_msg = b'<event uid="test" type="a-f-G"><point lat="1" lon="2"/></event>'  # noqa: E501

        # Simulate receiving message then connection close
        mock_reader.read.side_effect = [
            cot_msg,  # First read returns message
            b"",      # Second read returns empty (connection closed)
        ]

        tak_server_id = 1

        # Mock plugin routing
        with patch.object(service, '_route_cot_to_plugins', new_callable=AsyncMock) as mock_route:  # noqa: E501
            # Run RX worker (will exit when reader returns empty)
            await service._rx_worker(tak_server_id, mock_reader)

            # Verify message was routed
            assert mock_route.called
            call_args = mock_route.call_args[0]
            assert call_args[0] == cot_msg
            assert call_args[1] == tak_server_id

    @pytest.mark.asyncio
    async def test_rx_worker_filters_malicious_xml(self, service):
        """Test RX worker filtering malicious XML."""
        # Create mock reader with malicious XML in CoT wrapper
        mock_reader = AsyncMock()
        # Malicious XML must be a complete CoT event to be extracted
        malicious_xml = b'<event uid="test"><!ENTITY xxe SYSTEM "file:///etc/passwd">&xxe;</event>'  # noqa: E501

        mock_reader.read.side_effect = [
            malicious_xml,
            b"",  # Connection close
        ]

        tak_server_id = 1

        # Mock plugin routing
        with patch.object(service, '_route_cot_to_plugins', new_callable=AsyncMock) as mock_route:  # noqa: E501
            await service._rx_worker(tak_server_id, mock_reader)

            # Verify malicious message was NOT routed
            assert not mock_route.called

    @pytest.mark.asyncio
    async def test_rx_worker_handles_buffer_overflow(self, service):
        """Test RX worker handling buffer overflow."""
        # Create mock reader with oversized data
        mock_reader = AsyncMock()
        oversized_data = b"X" * (1024 * 1024 + 1)  # Exceeds 1MB limit

        mock_reader.read.side_effect = [
            oversized_data,
            b"",  # Connection close
        ]

        tak_server_id = 1

        # Should not crash
        await service._rx_worker(tak_server_id, mock_reader)

    @pytest.mark.asyncio
    async def test_rx_worker_handles_timeout(self, service):
        """Test RX worker handling read timeouts."""
        # Create mock reader that times out
        mock_reader = AsyncMock()

        call_count = 0

        async def read_with_timeout(*args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            return b""  # Connection close after timeout

        mock_reader.read.side_effect = read_with_timeout

        tak_server_id = 1

        # Should handle timeout gracefully
        await service._rx_worker(tak_server_id, mock_reader)


class TestEnhancedTransmissionWorkerBidirectional:
    """Test enhanced transmission worker with RX support."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton before and after each test."""
        reset_cot_service()
        yield
        reset_cot_service()

    @pytest.fixture
    def service(self):
        """Create a COT service instance."""
        with (
            patch("services.cot_service_integration.get_queue_manager"),
            patch("services.cot_service_integration.get_queue_monitoring_service"),  # noqa: E501
        ):
            service = QueuedCOTService(_bypass_singleton_check=True)
            service._running = True
            return service

    @pytest.mark.asyncio
    async def test_worker_starts_both_tx_and_rx_when_enabled(self, service):
        """Test worker starts both TX and RX when enable_rx is True."""
        tak_server = Mock()
        tak_server.name = "Test Server"
        tak_server.enable_rx = True
        tak_server_id = 1

        mock_reader = AsyncMock()
        mock_writer = Mock()

        with (
            patch.object(service, '_create_pytak_connection', return_value=(mock_reader, mock_writer)),  # noqa: E501
            patch.object(service, '_tx_loop', new_callable=AsyncMock) as mock_tx,  # noqa: E501
            patch.object(service, '_rx_worker', new_callable=AsyncMock) as mock_rx,  # noqa: E501
            patch.object(service, '_cleanup_connection', new_callable=AsyncMock),  # noqa: E501
            patch.object(service, '_get_tak_circuit_breaker', return_value=None),  # noqa: E501
        ):
            # Make tasks complete immediately
            mock_tx.return_value = None
            mock_rx.return_value = None

            # Worker has a reconnection loop; run as task and cancel after
            # TX/RX tasks complete and assertions can be checked
            task = asyncio.create_task(
                service._enhanced_transmission_worker(tak_server_id, tak_server)
            )
            # Give the worker time to run one iteration
            await asyncio.sleep(0.1)
            task.cancel()
            await task  # Worker handles CancelledError internally and exits

            # Verify both workers were started
            assert mock_tx.called
            assert mock_rx.called

    @pytest.mark.asyncio
    async def test_worker_starts_only_tx_when_rx_disabled(self, service):
        """Test worker starts only TX when enable_rx is False."""
        tak_server = Mock()
        tak_server.name = "Test Server"
        tak_server.enable_rx = False
        tak_server_id = 1

        mock_reader = AsyncMock()
        mock_writer = Mock()

        with (
            patch.object(service, '_create_pytak_connection', return_value=(mock_reader, mock_writer)),  # noqa: E501
            patch.object(service, '_tx_loop', new_callable=AsyncMock) as mock_tx,  # noqa: E501
            patch.object(service, '_rx_worker', new_callable=AsyncMock) as mock_rx,  # noqa: E501
            patch.object(service, '_cleanup_connection', new_callable=AsyncMock),  # noqa: E501
            patch.object(service, '_get_tak_circuit_breaker', return_value=None),  # noqa: E501
        ):
            mock_tx.return_value = None

            # Worker has a reconnection loop; run as task and cancel after
            # TX task completes and assertions can be checked
            task = asyncio.create_task(
                service._enhanced_transmission_worker(tak_server_id, tak_server)
            )
            await asyncio.sleep(0.1)
            task.cancel()
            await task  # Worker handles CancelledError internally and exits

            # Verify only TX was started
            assert mock_tx.called
            assert not mock_rx.called
