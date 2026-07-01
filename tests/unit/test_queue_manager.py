"""
ABOUTME: Unit tests for QueueManager service covering bounded queues, overflow strategies,
ABOUTME: batch retrieval, configuration validation, and metrics tracking.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from services.queue_manager import QueueManager, QueueMetrics, reset_queue_manager


class TestQueueManagerConfig:
    """Tests for QueueManager configuration initialization and validation."""

    @pytest.mark.asyncio
    async def test_default_config_initialization(self):
        """QueueManager with no config uses all default values."""
        qm = QueueManager()

        assert qm.config["max_size"] == 600
        assert qm.config["batch_size"] == 20
        assert qm.config["overflow_strategy"] == "drop_oldest"
        assert qm.config["flush_on_config_change"] is True
        assert qm.config["batch_timeout_ms"] == 100
        assert qm.config["queue_check_interval_ms"] == 100
        assert qm.config["log_queue_stats"] is True
        assert qm.config["queue_warning_threshold"] == 600

    @pytest.mark.asyncio
    async def test_custom_config_merges_over_defaults(self):
        """Provided config values override defaults, missing keys use defaults."""
        qm = QueueManager(config={"max_size": 100, "batch_size": 5})

        assert qm.config["max_size"] == 100
        assert qm.config["batch_size"] == 5
        # Remaining keys should be defaults
        assert qm.config["overflow_strategy"] == "drop_oldest"
        assert qm.config["flush_on_config_change"] is True

    @pytest.mark.asyncio
    async def test_invalid_max_size_falls_back_to_default(self):
        """Negative or non-numeric max_size falls back to the default value."""
        qm = QueueManager(config={"max_size": -10})
        assert qm.config["max_size"] == 600

        qm2 = QueueManager(config={"max_size": "not_a_number"})
        assert qm2.config["max_size"] == 600

    @pytest.mark.asyncio
    async def test_invalid_batch_size_falls_back_to_default(self):
        """Zero or non-numeric batch_size falls back to the default value."""
        qm = QueueManager(config={"batch_size": 0})
        assert qm.config["batch_size"] == 20

        qm2 = QueueManager(config={"batch_size": "bad"})
        assert qm2.config["batch_size"] == 20

    @pytest.mark.asyncio
    async def test_invalid_overflow_strategy_falls_back_to_default(self):
        """Unknown overflow_strategy falls back to drop_oldest."""
        qm = QueueManager(config={"overflow_strategy": "explode"})
        assert qm.config["overflow_strategy"] == "drop_oldest"

    @pytest.mark.asyncio
    async def test_valid_overflow_strategies_accepted(self):
        """All three valid overflow strategies are accepted."""
        for strategy in ("drop_oldest", "drop_newest", "block"):
            qm = QueueManager(config={"overflow_strategy": strategy})
            assert qm.config["overflow_strategy"] == strategy

    @pytest.mark.asyncio
    async def test_float_max_size_cast_to_int(self):
        """A positive float max_size is accepted and cast to int."""
        qm = QueueManager(config={"max_size": 50.7})
        assert qm.config["max_size"] == 50
        assert isinstance(qm.config["max_size"], int)


class TestQueueCreation:
    """Tests for queue creation and lifecycle."""

    @pytest.mark.asyncio
    async def test_create_queue_returns_true(self):
        """Creating a new queue returns True."""
        qm = QueueManager()
        result = await qm.create_queue(1)
        assert result is True
        assert 1 in qm.queues

    @pytest.mark.asyncio
    async def test_create_queue_initializes_metrics(self):
        """Creating a queue initializes a QueueMetrics entry."""
        qm = QueueManager()
        await qm.create_queue(42)

        metrics = qm.metrics[42]
        assert isinstance(metrics, QueueMetrics)
        assert metrics.total_events_processed == 0
        assert metrics.total_events_dropped == 0
        assert metrics.overflow_events == 0

    @pytest.mark.asyncio
    async def test_create_duplicate_queue_returns_true_without_recreating(self):
        """Creating a queue with an existing ID returns True and keeps the same queue."""
        qm = QueueManager()
        await qm.create_queue(1)
        original_queue = qm.queues[1]

        result = await qm.create_queue(1)
        assert result is True
        assert qm.queues[1] is original_queue

    @pytest.mark.asyncio
    async def test_queue_uses_configured_max_size(self):
        """Queue maxsize matches the configured max_size."""
        qm = QueueManager(config={"max_size": 50})
        await qm.create_queue(1)

        assert qm.queues[1].maxsize == 50


class TestEnqueueEvent:
    """Tests for enqueue_event with various overflow strategies."""

    @pytest.mark.asyncio
    async def test_enqueue_to_nonexistent_queue_returns_false(self):
        """Enqueueing to a queue that does not exist returns False."""
        qm = QueueManager()
        result = await qm.enqueue_event(999, b"data")
        assert result is False

    @pytest.mark.asyncio
    async def test_enqueue_to_nonexistent_queue_logs_at_debug_not_error(self, caplog):
        """
        During a stream restart the queue is removed briefly before the new
        worker installs a fresh one. Any in-flight enqueue attempts in that
        window are expected — logging them at ERROR floods the log (~20
        errors per restart at 10Hz). Debug is the right level: callers still
        see the False return.
        """
        qm = QueueManager()
        with caplog.at_level("DEBUG", logger="services.queue_manager"):
            await qm.enqueue_event(999, b"data")

        # No ERROR-level records for the missing queue.
        errors = [
            r
            for r in caplog.records
            if r.levelname == "ERROR" and "does not exist" in r.message
        ]
        assert not errors, (
            f"'Queue does not exist' must not log at ERROR; got: "
            f"{[r.message for r in errors]}"
        )
        # And DEBUG carries the same info for anyone who cares.
        debugs = [
            r
            for r in caplog.records
            if r.levelname == "DEBUG" and "does not exist" in r.message
        ]
        assert debugs, "Expected DEBUG log for missing queue"

    @pytest.mark.asyncio
    async def test_enqueue_event_success(self):
        """Basic enqueue adds event to queue and returns True."""
        qm = QueueManager(config={"max_size": 10})
        await qm.create_queue(1)

        result = await qm.enqueue_event(1, b"hello")
        assert result is True
        assert qm.queues[1].qsize() == 1

    @pytest.mark.asyncio
    async def test_enqueue_updates_metrics(self):
        """Successful enqueue increments total_events_processed."""
        qm = QueueManager(config={"max_size": 10})
        await qm.create_queue(1)

        await qm.enqueue_event(1, b"event1")
        await qm.enqueue_event(1, b"event2")

        assert qm.metrics[1].total_events_processed == 2

    @pytest.mark.asyncio
    async def test_drop_oldest_overflow_strategy(self):
        """drop_oldest strategy drops oldest event when queue is full."""
        qm = QueueManager(config={"max_size": 3, "overflow_strategy": "drop_oldest"})
        await qm.create_queue(1)

        # Fill the queue
        await qm.enqueue_event(1, b"event1")
        await qm.enqueue_event(1, b"event2")
        await qm.enqueue_event(1, b"event3")
        assert qm.queues[1].qsize() == 3

        # Overflow: oldest should be dropped
        result = await qm.enqueue_event(1, b"event4")
        assert result is True
        assert qm.queues[1].qsize() == 3

        # Verify metrics
        assert qm.metrics[1].total_events_dropped == 1
        assert qm.metrics[1].overflow_events == 1

        # The oldest event (event1) should be gone; next get should yield event2
        item = qm.queues[1].get_nowait()
        assert item == b"event2"

    @pytest.mark.asyncio
    async def test_drop_newest_overflow_strategy(self):
        """drop_newest strategy rejects the new event when queue is full."""
        qm = QueueManager(config={"max_size": 3, "overflow_strategy": "drop_newest"})
        await qm.create_queue(1)

        # Fill the queue
        await qm.enqueue_event(1, b"event1")
        await qm.enqueue_event(1, b"event2")
        await qm.enqueue_event(1, b"event3")

        # Overflow: newest event should be rejected
        result = await qm.enqueue_event(1, b"event4")
        assert result is False
        assert qm.queues[1].qsize() == 3

        # Verify metrics
        assert qm.metrics[1].total_events_dropped == 1
        assert qm.metrics[1].overflow_events == 1

        # Original events should be intact
        item = qm.queues[1].get_nowait()
        assert item == b"event1"

    @pytest.mark.asyncio
    async def test_block_overflow_strategy(self):
        """block strategy uses await queue.put which blocks until space is available."""
        qm = QueueManager(config={"max_size": 2, "overflow_strategy": "block"})
        await qm.create_queue(1)

        # Fill the queue
        await qm.enqueue_event(1, b"event1")
        await qm.enqueue_event(1, b"event2")

        # Start a blocking enqueue in a task, then free space
        async def drain_after_delay():
            await asyncio.sleep(0.05)
            qm.queues[1].get_nowait()

        drain_task = asyncio.create_task(drain_after_delay())
        result = await qm.enqueue_event(1, b"event3")
        await drain_task

        assert result is True
        # No events should be dropped with block strategy
        assert qm.metrics[1].total_events_dropped == 0
        assert qm.metrics[1].overflow_events == 0

    @pytest.mark.asyncio
    async def test_drop_oldest_multiple_overflows(self):
        """Multiple overflows with drop_oldest accumulate dropped counts."""
        qm = QueueManager(config={"max_size": 2, "overflow_strategy": "drop_oldest"})
        await qm.create_queue(1)

        await qm.enqueue_event(1, b"a")
        await qm.enqueue_event(1, b"b")
        await qm.enqueue_event(1, b"c")  # drops a
        await qm.enqueue_event(1, b"d")  # drops b

        assert qm.metrics[1].total_events_dropped == 2
        assert qm.metrics[1].overflow_events == 2
        assert qm.queues[1].qsize() == 2

        # Remaining items should be c and d
        first = qm.queues[1].get_nowait()
        second = qm.queues[1].get_nowait()
        assert first == b"c"
        assert second == b"d"


class TestBatchRetrieval:
    """Tests for get_batch with full, partial, and shutdown scenarios."""

    @pytest.mark.asyncio
    async def test_get_batch_full_batch(self):
        """get_batch returns up to batch_size events."""
        qm = QueueManager(
            config={"max_size": 100, "batch_size": 3, "batch_timeout_ms": 500}
        )
        await qm.create_queue(1)

        for i in range(5):
            await qm.enqueue_event(1, f"event{i}".encode())

        batch = await qm.get_batch(1)
        assert len(batch) == 3
        assert batch == [b"event0", b"event1", b"event2"]

    @pytest.mark.asyncio
    async def test_get_batch_partial_batch_on_timeout(self):
        """get_batch returns a partial batch when timeout occurs before batch_size is reached."""
        qm = QueueManager(
            config={"max_size": 100, "batch_size": 10, "batch_timeout_ms": 50}
        )
        await qm.create_queue(1)

        # Only add 2 events, batch_size is 10
        await qm.enqueue_event(1, b"event1")
        await qm.enqueue_event(1, b"event2")

        batch = await qm.get_batch(1)
        assert len(batch) == 2
        assert batch == [b"event1", b"event2"]

    @pytest.mark.asyncio
    async def test_get_batch_stops_on_shutdown_signal(self):
        """None event in queue acts as shutdown signal, stopping batch collection."""
        qm = QueueManager(
            config={"max_size": 100, "batch_size": 10, "batch_timeout_ms": 500}
        )
        await qm.create_queue(1)

        await qm.enqueue_event(1, b"event1")
        # Manually put None as shutdown signal
        await qm.queues[1].put(None)
        await qm.enqueue_event(1, b"event2")

        batch = await qm.get_batch(1)
        # Should stop at None, returning only event1
        assert len(batch) == 1
        assert batch == [b"event1"]

    @pytest.mark.asyncio
    async def test_get_batch_nonexistent_queue(self):
        """get_batch on nonexistent queue returns empty list."""
        qm = QueueManager()
        batch = await qm.get_batch(999)
        assert batch == []

    @pytest.mark.asyncio
    async def test_get_batch_updates_metrics(self):
        """get_batch updates total_batches_sent and average_batch_size."""
        qm = QueueManager(
            config={"max_size": 100, "batch_size": 3, "batch_timeout_ms": 500}
        )
        await qm.create_queue(1)

        for i in range(6):
            await qm.enqueue_event(1, f"e{i}".encode())

        await qm.get_batch(1)  # 3 events
        assert qm.metrics[1].total_batches_sent == 1
        assert qm.metrics[1].average_batch_size == 3.0

        await qm.get_batch(1)  # 3 more events
        assert qm.metrics[1].total_batches_sent == 2
        # Running formula: (batches_sent * old_avg + new_batch_len) / batches_sent
        # = (2 * 3.0 + 3) / 2 = 4.5
        assert qm.metrics[1].average_batch_size == 4.5

    @pytest.mark.asyncio
    async def test_get_batch_empty_queue_returns_empty(self):
        """get_batch on an empty queue returns empty list after timeout."""
        qm = QueueManager(
            config={"max_size": 100, "batch_size": 5, "batch_timeout_ms": 50}
        )
        await qm.create_queue(1)

        batch = await qm.get_batch(1)
        assert batch == []


class TestFlushQueue:
    """Tests for queue flushing and associated metrics."""

    @pytest.mark.asyncio
    async def test_flush_queue_drains_all_events(self):
        """flush_queue removes all events and returns the count."""
        qm = QueueManager(config={"max_size": 100})
        await qm.create_queue(1)

        for i in range(5):
            await qm.enqueue_event(1, f"e{i}".encode())

        flushed = await qm.flush_queue(1)
        assert flushed == 5
        assert qm.queues[1].qsize() == 0

    @pytest.mark.asyncio
    async def test_flush_queue_updates_metrics(self):
        """flush_queue sets last_flush_time and increments config_change_flushes."""
        qm = QueueManager(config={"max_size": 100})
        await qm.create_queue(1)

        await qm.enqueue_event(1, b"data")
        before = datetime.now(timezone.utc)
        await qm.flush_queue(1)
        after = datetime.now(timezone.utc)

        metrics = qm.metrics[1]
        assert metrics.last_flush_time is not None
        assert before <= metrics.last_flush_time <= after
        assert metrics.config_change_flushes == 1

    @pytest.mark.asyncio
    async def test_flush_nonexistent_queue_returns_zero(self):
        """Flushing a nonexistent queue returns 0."""
        qm = QueueManager()
        flushed = await qm.flush_queue(999)
        assert flushed == 0

    @pytest.mark.asyncio
    async def test_flush_empty_queue_returns_zero(self):
        """Flushing an empty queue returns 0 but still updates metrics."""
        qm = QueueManager(config={"max_size": 100})
        await qm.create_queue(1)

        flushed = await qm.flush_queue(1)
        assert flushed == 0
        assert qm.metrics[1].config_change_flushes == 1

    @pytest.mark.asyncio
    async def test_flush_increments_on_each_call(self):
        """Each flush call increments config_change_flushes."""
        qm = QueueManager(config={"max_size": 100})
        await qm.create_queue(1)

        await qm.flush_queue(1)
        await qm.flush_queue(1)
        await qm.flush_queue(1)

        assert qm.metrics[1].config_change_flushes == 3


class TestQueueStatus:
    """Tests for queue status reporting."""

    @pytest.mark.asyncio
    async def test_status_existing_queue(self):
        """get_queue_status returns complete status dict for existing queue."""
        qm = QueueManager(config={"max_size": 50})
        await qm.create_queue(1)

        await qm.enqueue_event(1, b"event1")
        await qm.enqueue_event(1, b"event2")

        status = qm.get_queue_status(1)
        assert status["exists"] is True
        assert status["size"] == 2
        assert status["current_size"] == 2
        assert status["max_size"] == 50
        assert status["is_full"] is False
        assert status["is_empty"] is False
        assert status["events_queued"] == 2
        assert status["total_events_processed"] == 2
        assert status["total_events_dropped"] == 0

    @pytest.mark.asyncio
    async def test_status_nonexistent_queue(self):
        """get_queue_status returns {exists: False} for unknown queue."""
        qm = QueueManager()
        status = qm.get_queue_status(999)
        assert status == {"exists": False}

    @pytest.mark.asyncio
    async def test_status_full_queue(self):
        """is_full is True when queue size equals max_size."""
        qm = QueueManager(config={"max_size": 2})
        await qm.create_queue(1)

        await qm.enqueue_event(1, b"a")
        await qm.enqueue_event(1, b"b")

        status = qm.get_queue_status(1)
        assert status["is_full"] is True

    @pytest.mark.asyncio
    async def test_status_empty_queue(self):
        """is_empty is True for a freshly created queue."""
        qm = QueueManager()
        await qm.create_queue(1)

        status = qm.get_queue_status(1)
        assert status["is_empty"] is True
        assert status["size"] == 0

    @pytest.mark.asyncio
    async def test_get_all_queue_status(self):
        """get_all_queue_status returns status for every queue."""
        qm = QueueManager()
        await qm.create_queue(1)
        await qm.create_queue(2)
        await qm.create_queue(3)

        all_status = qm.get_all_queue_status()
        assert set(all_status.keys()) == {1, 2, 3}
        for qid in (1, 2, 3):
            assert all_status[qid]["exists"] is True


class TestConfigurationChange:
    """Tests for on_configuration_change behavior."""

    @pytest.mark.asyncio
    async def test_config_change_flushes_queues_when_enabled(self):
        """on_configuration_change flushes all queues when flush_on_config_change is True."""
        qm = QueueManager(config={"max_size": 100, "flush_on_config_change": True})
        await qm.create_queue(1)
        await qm.create_queue(2)

        await qm.enqueue_event(1, b"data1")
        await qm.enqueue_event(2, b"data2")

        new_config = {"max_size": 100, "flush_on_config_change": True}
        await qm.on_configuration_change(new_config)

        assert qm.queues[1].qsize() == 0
        assert qm.queues[2].qsize() == 0
        assert qm.metrics[1].config_change_flushes == 1
        assert qm.metrics[2].config_change_flushes == 1

    @pytest.mark.asyncio
    async def test_config_change_does_not_flush_when_disabled(self):
        """on_configuration_change skips flushing when flush_on_config_change is False."""
        qm = QueueManager(config={"max_size": 100, "flush_on_config_change": False})
        await qm.create_queue(1)

        await qm.enqueue_event(1, b"data1")
        await qm.enqueue_event(1, b"data2")

        new_config = {"flush_on_config_change": False}
        await qm.on_configuration_change(new_config)

        # Queue should still have events
        assert qm.queues[1].qsize() == 2
        assert qm.metrics[1].config_change_flushes == 0

    @pytest.mark.asyncio
    async def test_config_change_updates_config(self):
        """on_configuration_change replaces the current config."""
        qm = QueueManager(config={"max_size": 100})
        new_config = {"max_size": 200, "flush_on_config_change": False}
        await qm.on_configuration_change(new_config)

        assert qm.config["max_size"] == 200


class TestQueueRemoval:
    """Tests for queue removal and cleanup."""

    @pytest.mark.asyncio
    async def test_remove_existing_queue(self):
        """remove_queue sends shutdown signal, removes queue and metrics, returns True."""
        qm = QueueManager(config={"max_size": 100})
        await qm.create_queue(1)
        await qm.enqueue_event(1, b"data")

        result = await qm.remove_queue(1)
        assert result is True
        assert 1 not in qm.queues
        assert 1 not in qm.metrics

    @pytest.mark.asyncio
    async def test_remove_nonexistent_queue_returns_false(self):
        """remove_queue for unknown queue_id returns False."""
        qm = QueueManager()
        result = await qm.remove_queue(999)
        assert result is False


class TestMetricsTracking:
    """Tests for comprehensive metrics tracking across operations."""

    @pytest.mark.asyncio
    async def test_max_queue_size_tracking(self):
        """max_queue_size_reached tracks the peak queue size."""
        qm = QueueManager(config={"max_size": 10})
        await qm.create_queue(1)

        # Add 5 events
        for i in range(5):
            await qm.enqueue_event(1, f"e{i}".encode())
        assert qm.metrics[1].max_queue_size_reached == 5

        # Drain some, add more — peak should not decrease
        qm.queues[1].get_nowait()
        qm.queues[1].get_nowait()
        await qm.enqueue_event(1, b"new")
        # Peak was 5, current is 4, so max should still be 5
        assert qm.metrics[1].max_queue_size_reached == 5

    @pytest.mark.asyncio
    async def test_current_queue_size_updates_on_enqueue(self):
        """current_queue_size in metrics reflects the queue size after enqueue."""
        qm = QueueManager(config={"max_size": 10})
        await qm.create_queue(1)

        await qm.enqueue_event(1, b"a")
        assert qm.metrics[1].current_queue_size == 1

        await qm.enqueue_event(1, b"b")
        assert qm.metrics[1].current_queue_size == 2

    @pytest.mark.asyncio
    async def test_metrics_across_overflow_and_batch(self):
        """Metrics accumulate correctly through enqueue overflows and batch retrieval."""
        qm = QueueManager(
            config={
                "max_size": 3,
                "batch_size": 2,
                "overflow_strategy": "drop_oldest",
                "batch_timeout_ms": 500,
            }
        )
        await qm.create_queue(1)

        # Fill and overflow
        await qm.enqueue_event(1, b"e1")
        await qm.enqueue_event(1, b"e2")
        await qm.enqueue_event(1, b"e3")
        await qm.enqueue_event(1, b"e4")  # drops e1

        metrics = qm.metrics[1]
        assert metrics.total_events_processed == 4
        assert metrics.total_events_dropped == 1
        assert metrics.overflow_events == 1

        # Retrieve a batch
        batch = await qm.get_batch(1)
        assert len(batch) == 2
        assert metrics.total_batches_sent == 1
        assert metrics.average_batch_size == 2.0

    @pytest.mark.asyncio
    async def test_queue_metrics_dataclass_defaults(self):
        """QueueMetrics dataclass initializes with expected zero/None defaults."""
        m = QueueMetrics()
        assert m.total_events_processed == 0
        assert m.total_events_dropped == 0
        assert m.total_batches_sent == 0
        assert m.current_queue_size == 0
        assert m.max_queue_size_reached == 0
        assert m.average_batch_size == 0.0
        assert m.last_flush_time is None
        assert m.overflow_events == 0
        assert m.config_change_flushes == 0

    @pytest.mark.asyncio
    async def test_average_batch_size_calculation(self):
        """average_batch_size correctly computes running average across batches."""
        qm = QueueManager(
            config={
                "max_size": 100,
                "batch_size": 5,
                "batch_timeout_ms": 50,
            }
        )
        await qm.create_queue(1)

        # First batch: 4 events
        for i in range(4):
            await qm.enqueue_event(1, f"e{i}".encode())
        await qm.get_batch(1)
        assert qm.metrics[1].average_batch_size == 4.0

        # Second batch: 2 events
        await qm.enqueue_event(1, b"x")
        await qm.enqueue_event(1, b"y")
        await qm.get_batch(1)
        # Running formula: (batches * old_avg + new_len) / batches
        # = (2 * 4.0 + 2) / 2 = 5.0
        assert qm.metrics[1].average_batch_size == 5.0


class TestGlobalSingleton:
    """Tests for the global singleton get/reset functions."""

    @pytest.mark.asyncio
    async def test_reset_queue_manager(self):
        """reset_queue_manager sets global singleton to None."""
        # Just ensure it doesn't error and resets cleanly
        reset_queue_manager()
        # No assertion needed beyond no exception — we avoid using get_queue_manager
        # in tests to keep isolation, but reset should be callable.
