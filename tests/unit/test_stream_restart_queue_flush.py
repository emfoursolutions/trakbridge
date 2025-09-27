"""Unit tests for stream restart queue flushing functionality."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from services.stream_manager import StreamManager


class TestStreamRestartQueueFlush:
    """Test stream restart queue flushing functionality."""

    @pytest.fixture
    def mock_db_manager(self):
        """Create a mock database manager."""
        db_manager = Mock()
        db_manager.get_stream_with_relationships = Mock()
        return db_manager

    @pytest.fixture
    def mock_cot_service(self):
        """Create a mock COT service with flush_queue method."""
        cot_service = AsyncMock()
        cot_service.flush_queue = AsyncMock()
        return cot_service

    @pytest.fixture
    def mock_stream_single_server(self):
        """Create a mock stream with single TAK server."""
        stream = Mock()
        stream.id = 1
        stream.name = "Test Stream"

        # Single server configuration
        tak_server = Mock()
        tak_server.id = 100
        tak_server.name = "TAK Server 1"
        stream.tak_server = tak_server
        stream.tak_servers = []  # Empty multi-server

        return stream

    @pytest.fixture
    def mock_stream_multi_server(self):
        """Create a mock stream with multiple TAK servers."""
        stream = Mock()
        stream.id = 2
        stream.name = "Multi-Server Stream"

        # Multi-server configuration
        tak_server1 = Mock()
        tak_server1.id = 200
        tak_server1.name = "TAK Server 1"

        tak_server2 = Mock()
        tak_server2.id = 201
        tak_server2.name = "TAK Server 2"

        stream.tak_server = None  # No single server
        stream.tak_servers = [tak_server1, tak_server2]

        return stream

    @pytest.fixture
    def mock_stream_manager(self, mock_db_manager):
        """Create a StreamManager instance with mocked dependencies."""
        with (
            patch(
                "services.stream_manager.DatabaseManager", return_value=mock_db_manager
            ),
            patch("services.stream_manager.SessionManager"),
            patch.object(StreamManager, "_start_background_loop"),
        ):

            manager = StreamManager()
            # Mock the has_tak_servers_configured method
            manager._has_tak_servers_configured = Mock(return_value=True)
            # Mock async methods
            manager.stop_stream = AsyncMock(return_value=True)
            manager.start_stream = AsyncMock(return_value=True)
            return manager

    @patch("services.stream_manager.get_cot_service")
    @pytest.mark.asyncio
    async def test_restart_stream_single_server_queue_flush(
        self,
        mock_get_cot_service,
        mock_stream_manager,
        mock_stream_single_server,
        mock_cot_service,
    ):
        """Test restart_stream flushes queue for single TAK server."""
        # Setup
        mock_get_cot_service.return_value = mock_cot_service
        mock_cot_service.flush_queue.return_value = 5  # 5 events flushed

        # Mock database call to return our test stream
        mock_stream_manager.db_manager.get_stream_with_relationships.return_value = (
            mock_stream_single_server
        )

        # Execute
        result = await mock_stream_manager.restart_stream(1)

        # Verify
        assert result is True
        mock_cot_service.flush_queue.assert_called_once_with(100)  # TAK server ID
        mock_stream_manager.stop_stream.assert_called_once_with(1)
        mock_stream_manager.start_stream.assert_called_once_with(1)

    @patch("services.stream_manager.get_cot_service")
    @pytest.mark.asyncio
    async def test_restart_stream_multi_server_queue_flush(
        self,
        mock_get_cot_service,
        mock_stream_manager,
        mock_stream_multi_server,
        mock_cot_service,
    ):
        """Test restart_stream flushes queues for multiple TAK servers."""
        # Setup
        mock_get_cot_service.return_value = mock_cot_service
        mock_cot_service.flush_queue.side_effect = [3, 7]  # Different flush counts

        # Mock database call to return our test stream
        mock_stream_manager.db_manager.get_stream_with_relationships.return_value = (
            mock_stream_multi_server
        )

        # Execute
        result = await mock_stream_manager.restart_stream(2)

        # Verify
        assert result is True
        assert mock_cot_service.flush_queue.call_count == 2
        mock_cot_service.flush_queue.assert_any_call(200)  # First TAK server
        mock_cot_service.flush_queue.assert_any_call(201)  # Second TAK server
        mock_stream_manager.stop_stream.assert_called_once_with(2)
        mock_stream_manager.start_stream.assert_called_once_with(2)

    @patch("services.stream_manager.get_cot_service")
    @pytest.mark.asyncio
    async def test_restart_stream_queue_flush_error_continues_restart(
        self,
        mock_get_cot_service,
        mock_stream_manager,
        mock_stream_single_server,
        mock_cot_service,
    ):
        """Test restart continues even if queue flush fails."""
        # Setup
        mock_get_cot_service.return_value = mock_cot_service
        mock_cot_service.flush_queue.side_effect = Exception("Queue flush failed")

        # Mock database call to return our test stream
        mock_stream_manager.db_manager.get_stream_with_relationships.return_value = (
            mock_stream_single_server
        )

        # Execute
        result = await mock_stream_manager.restart_stream(1)

        # Verify
        assert result is True  # Should still succeed despite flush error
        mock_cot_service.flush_queue.assert_called_once_with(100)
        mock_stream_manager.stop_stream.assert_called_once_with(1)
        mock_stream_manager.start_stream.assert_called_once_with(1)

    @patch("services.stream_manager.get_cot_service")
    @pytest.mark.asyncio
    async def test_restart_stream_no_tak_servers_configured(
        self, mock_get_cot_service, mock_stream_manager, mock_cot_service
    ):
        """Test restart continues when no TAK servers are configured."""
        # Setup
        mock_get_cot_service.return_value = mock_cot_service

        # Create stream with no TAK servers
        stream_no_servers = Mock()
        stream_no_servers.id = 3
        stream_no_servers.tak_server = None
        stream_no_servers.tak_servers = []

        mock_stream_manager.db_manager.get_stream_with_relationships.return_value = (
            stream_no_servers
        )
        mock_stream_manager._has_tak_servers_configured.return_value = False

        # Execute
        result = await mock_stream_manager.restart_stream(3)

        # Verify
        assert result is True
        mock_cot_service.flush_queue.assert_not_called()  # No flush attempted
        mock_stream_manager.stop_stream.assert_called_once_with(3)
        mock_stream_manager.start_stream.assert_called_once_with(3)

    @patch("services.stream_manager.get_cot_service")
    @pytest.mark.asyncio
    async def test_restart_stream_database_error_continues_restart(
        self, mock_get_cot_service, mock_stream_manager, mock_cot_service
    ):
        """Test restart continues even if database lookup fails."""
        # Setup
        mock_get_cot_service.return_value = mock_cot_service

        # Mock database error
        mock_stream_manager.db_manager.get_stream_with_relationships.side_effect = (
            Exception("DB Error")
        )

        # Execute
        result = await mock_stream_manager.restart_stream(1)

        # Verify
        assert result is True  # Should still succeed despite DB error
        mock_cot_service.flush_queue.assert_not_called()  # No flush attempted due to DB error
        mock_stream_manager.stop_stream.assert_called_once_with(1)
        mock_stream_manager.start_stream.assert_called_once_with(1)
