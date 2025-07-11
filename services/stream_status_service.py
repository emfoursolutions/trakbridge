"""
File: services/stream_status_service.py

Description:
Service for managing and retrieving comprehensive stream status information across the streaming system.
Provides safe status retrieval, statistics generation, and health monitoring for individual streams
and the entire stream ecosystem.

Key features:
- Safe stream status retrieval with error handling
- Comprehensive statistics aggregation by plugin type and status
- Detailed health monitoring and recent activity tracking
- Time-based formatting for last poll information
- Status validation and error reporting
- Multi-stream overview with categorized counts

Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Local application imports
from models.stream import Stream

logger = logging.getLogger(__name__)


class StreamStatusService:
    """Service for managing and retrieving stream status information"""

    def __init__(self, stream_manager: Any) -> None:
        self.stream_manager = stream_manager

    def get_safe_stream_status(self, stream_id: int) -> Dict[str, Any]:
        """Get stream status safely without raising exceptions"""
        try:
            return self.stream_manager.get_stream_status(stream_id)
        except Exception as e:
            logger.error(f"Error getting stream status for {stream_id}: {e}")
            return {
                "stream_id": stream_id,
                "running": False,
                "status": "error",
                "error": str(e),
                "last_poll": None,
                "total_messages_sent": 0,
            }

    def get_all_streams_status(self) -> Dict[str, Any]:
        """Get status for all streams"""
        try:
            streams = Stream.query.all()
            status_data: Dict[str, Any] = {
                "total_streams": len(streams),
                "active_streams": 0,
                "inactive_streams": 0,
                "running_streams": 0,
                "error_streams": 0,
                "streams": [],
            }

            for stream in streams:
                stream_status = self.get_safe_stream_status(stream.id)

                if stream.is_active:
                    status_data["active_streams"] += 1
                else:
                    status_data["inactive_streams"] += 1

                if stream_status.get("running", False):
                    status_data["running_streams"] += 1

                if stream.last_error:
                    status_data["error_streams"] += 1

                status_data["streams"].append(
                    {
                        "id": stream.id,
                        "name": stream.name,
                        "plugin_type": stream.plugin_type,
                        "is_active": stream.is_active,
                        "running": stream_status.get("running", False),
                        "status": stream_status.get("status", "unknown"),
                        "last_poll": self._format_last_poll(stream),
                        "last_error": stream.last_error,
                        "total_messages_sent": stream.total_messages_sent,
                    }
                )

            return status_data

        except Exception as e:
            logger.error(f"Error getting all streams status: {e}")
            return {
                "error": str(e),
                "total_streams": 0,
                "active_streams": 0,
                "inactive_streams": 0,
                "running_streams": 0,
                "error_streams": 0,
                "streams": [],
            }

    def get_stream_statistics(self) -> Dict[str, Any]:
        """Get comprehensive stream statistics"""
        try:
            streams = Stream.query.all()
            stats: Dict[str, Any] = {
                "total_streams": len(streams),
                "by_plugin_type": {},
                "by_status": {"active": 0, "inactive": 0, "running": 0, "error": 0},
                "message_totals": {"total_messages": 0, "avg_messages_per_stream": 0},
                "recent_activity": {
                    "streams_polled_today": 0,
                    "streams_with_errors": 0,
                },
            }

            total_messages = 0
            today = datetime.now().date()

            for stream in streams:
                # Plugin type statistics
                plugin_type = stream.plugin_type
                if plugin_type not in stats["by_plugin_type"]:
                    stats["by_plugin_type"][plugin_type] = {
                        "count": 0,
                        "active": 0,
                        "running": 0,
                        "total_messages": 0,
                    }

                stats["by_plugin_type"][plugin_type]["count"] += 1
                total_messages += stream.total_messages_sent
                stats["by_plugin_type"][plugin_type][
                    "total_messages"
                ] += stream.total_messages_sent

                # Status statistics
                if stream.is_active:
                    stats["by_status"]["active"] += 1
                    stats["by_plugin_type"][plugin_type]["active"] += 1

                stream_status = self.get_safe_stream_status(stream.id)
                if stream_status.get("running", False):
                    stats["by_status"]["running"] += 1
                    stats["by_plugin_type"][plugin_type]["running"] += 1

                if stream.last_error:
                    stats["by_status"]["error"] += 1
                    stats["recent_activity"]["streams_with_errors"] += 1

                # Recent activity
                if stream.last_poll and stream.last_poll.date() == today:
                    stats["recent_activity"]["streams_polled_today"] += 1

            # Calculate averages
            if streams:
                stats["message_totals"]["total_messages"] = total_messages
                stats["message_totals"]["avg_messages_per_stream"] = (
                    total_messages / len(streams)
                )

            return stats

        except Exception as e:
            logger.error(f"Error getting stream statistics: {e}")
            return {
                "error": str(e),
                "total_streams": 0,
                "by_plugin_type": {},
                "by_status": {"active": 0, "inactive": 0, "running": 0, "error": 0},
                "message_totals": {"total_messages": 0, "avg_messages_per_stream": 0},
                "recent_activity": {
                    "streams_polled_today": 0,
                    "streams_with_errors": 0,
                },
            }

    def get_detailed_stream_status(self, stream_id: int) -> Dict[str, Any]:
        """Get detailed status for a specific stream"""
        try:
            stream = Stream.query.get_or_404(stream_id)
            stream_status = self.get_safe_stream_status(stream_id)

            detailed_status: Dict[str, Any] = {
                "stream_id": stream.id,
                "name": stream.name,
                "plugin_type": stream.plugin_type,
                "is_active": stream.is_active,
                "running": stream_status.get("running", False),
                "status": stream_status.get("status", "unknown"),
                "configuration": {
                    "poll_interval": stream.poll_interval,
                    "cot_type": stream.cot_type,
                    "cot_stale_time": stream.cot_stale_time,
                    "tak_server_id": stream.tak_server_id,
                    "tak_server_name": (
                        stream.tak_server.name if stream.tak_server else None
                    ),
                },
                "statistics": {
                    "total_messages_sent": stream.total_messages_sent,
                    "last_poll": self._format_last_poll(stream),
                    "last_error": stream.last_error,
                    "created_at": (
                        stream.created_at.isoformat() if stream.created_at else None
                    ),
                    "updated_at": (
                        stream.updated_at.isoformat() if stream.updated_at else None
                    ),
                },
                "health": {
                    "has_error": bool(stream.last_error),
                    "is_healthy": not bool(stream.last_error) and stream.is_active,
                    "last_successful_poll": self._get_last_successful_poll(stream),
                },
            }

            return detailed_status

        except Exception as e:
            logger.error(f"Error getting detailed stream status for {stream_id}: {e}")
            return {"error": str(e), "stream_id": stream_id, "status": "error"}

    def get_running_stream_ids(self) -> List[int]:
        """Get list of currently running stream IDs"""
        try:
            streams = Stream.query.filter_by(is_active=True).all()
            running_ids: List[int] = []

            for stream in streams:
                stream_status = self.get_safe_stream_status(stream.id)
                if stream_status.get("running", False):
                    running_ids.append(stream.id)

            return running_ids

        except Exception as e:
            logger.error(f"Error getting running stream IDs: {e}")
            return []

    @staticmethod
    def _format_last_poll(stream: Stream) -> Optional[str]:
        """Format last poll time for display"""
        if not stream.last_poll:
            return None

        now = datetime.now()
        time_diff = now - stream.last_poll

        if time_diff < timedelta(minutes=1):
            return "Just now"
        elif time_diff < timedelta(hours=1):
            minutes = int(time_diff.total_seconds() / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif time_diff < timedelta(days=1):
            hours = int(time_diff.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = time_diff.days
            return f"{days} day{'s' if days != 1 else ''} ago"

    def _get_last_successful_poll(self, stream: Stream) -> Optional[str]:
        """Get last successful poll time"""
        if stream.last_error:
            # If there's an error, look for the last poll before the error
            # This is a simplified implementation
            return self._format_last_poll(stream)
        else:
            return self._format_last_poll(stream)


def format_stream_last_poll(stream: Stream) -> str:
    """Utility function to format stream last poll time"""
    if not stream.last_poll:
        return "Never"

    now = datetime.now()
    time_diff = now - stream.last_poll

    if time_diff < timedelta(minutes=1):
        return "Just now"
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.total_seconds() / 60)
        return f"{minutes}m ago"
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.total_seconds() / 3600)
        return f"{hours}h ago"
    else:
        days = time_diff.days
        return f"{days}d ago"


def validate_stream_status_format(status: Dict[str, Any], stream_id: int) -> bool:
    """Validate that a stream status dictionary has the correct format"""
    required_fields = ["stream_id", "running", "status"]

    for field in required_fields:
        if field not in status:
            logger.error(
                f"Missing required field '{field}' in stream status for {stream_id}"
            )
            return False

    if not isinstance(status["stream_id"], int):
        logger.error(
            f"stream_id must be int, got {type(status['stream_id'])} for {stream_id}"
        )
        return False

    if not isinstance(status["running"], bool):
        logger.error(
            f"running must be bool, got {type(status['running'])} for {stream_id}"
        )
        return False

    if not isinstance(status["status"], str):
        logger.error(
            f"status must be str, got {type(status['status'])} for {stream_id}"
        )
        return False

    return True
