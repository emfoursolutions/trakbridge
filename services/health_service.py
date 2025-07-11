"""
File: services/health_service.py

Description:
    Comprehensive health monitoring service providing detailed system health checks
    and performance monitoring for the TrakBridge application. This service performs
    database connectivity tests, connection pool monitoring, query performance analysis,
    and resource utilization tracking to ensure optimal system operation.

Key features:
    - Multi-database support with PostgreSQL, MySQL, and SQLite compatibility
    - Database connectivity and response time monitoring with connection pool analysis
    - Query performance tracking with slow query detection and execution time metrics
    - Lock monitoring and long-running transaction detection for database health
    - Database size monitoring with growth tracking and threshold alerting
    - Table-specific health checks for application entities and error detection
    - Aggregated health reporting with status categorization and issue prioritization
    - Real-time performance metrics with timestamp tracking and trend analysis


Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import logging
import time
import os
from datetime import datetime, timezone
from typing import Dict, Any

# Third-party imports
from sqlalchemy import text
from flask import current_app

# Local application imports
from database import db


logger = logging.getLogger(__name__)


class HealthService:
    """Service for performing various health checks"""

    def __init__(self):
        self.db_type = None
        self._init_db_type()

    def _init_db_type(self):
        """Initialize database type from config"""
        try:
            self.db_type = current_app.config_instance.secret_manager.get_secret(
                "DB_TYPE", "sqlite"
            )
        except Exception:
            self.db_type = "sqlite"  # fallback

    @staticmethod
    def check_database_connectivity() -> Dict[str, Any]:
        """Check database connectivity and basic operations (moved from routes/api.py)"""
        try:
            start_time = time.time()

            # Test basic connectivity
            db.session.execute(text("SELECT 1"))

            # Test table access
            from models.stream import Stream
            from models.tak_server import TakServer

            stream_count = Stream.query.count()
            tak_server_count = TakServer.query.count()

            response_time = round((time.time() - start_time) * 1000, 2)

            return {
                "status": "healthy",
                "response_time_ms": response_time,
                "stream_count": stream_count,
                "tak_server_count": tak_server_count,
                "connection_pool": {
                    "size": db.engine.pool.size(),
                    "checked_in": db.engine.pool.checkedin(),
                    "checked_out": db.engine.pool.checkedout(),
                    "overflow": db.engine.pool.overflow(),
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    @staticmethod
    def check_connection_pool_health() -> Dict[str, Any]:
        """Monitor connection pool status and performance"""
        try:
            pool = db.engine.pool
            pool_stats = {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
                "utilization_percent": (
                    round((pool.checkedout() / pool.size()) * 100, 2)
                    if pool.size() > 0
                    else 0
                ),
            }

            # Health assessment
            if pool_stats["utilization_percent"] > 80:
                status = "warning"
                message = "High connection pool utilization"
            elif pool_stats["checked_out"] > pool_stats["size"] * 0.9:
                status = "warning"
                message = "High number of checked out connections"
            else:
                status = "healthy"
                message = "Connection pool healthy"

            return {
                "status": status,
                "message": message,
                "details": pool_stats,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    @staticmethod
    def check_query_performance() -> Dict[str, Any]:
        """Monitor slow queries and performance metrics"""
        try:
            start_time = time.time()

            # Test basic queries
            queries = [
                ("SELECT 1", "basic_connectivity"),
                ("SELECT COUNT(*) FROM streams", "stream_count"),
                ("SELECT COUNT(*) FROM tak_servers", "tak_server_count"),
                ("SELECT COUNT(*) FROM streams WHERE is_active = 1", "active_streams"),
            ]

            results = {}
            total_time = 0

            for query, name in queries:
                query_start = time.time()
                result = db.session.execute(text(query)).scalar()
                query_time = (time.time() - query_start) * 1000  # ms
                total_time += query_time

                results[name] = {
                    "result": result,
                    "execution_time_ms": round(query_time, 2),
                }

            # Performance assessment
            avg_time = total_time / len(queries)
            if avg_time > 100:  # 100ms threshold
                status = "warning"
                message = f"Slow query performance: {avg_time:.2f}ms average"
            else:
                status = "healthy"
                message = f"Query performance good: {avg_time:.2f}ms average"

            return {
                "status": status,
                "message": message,
                "details": {
                    "average_query_time_ms": round(avg_time, 2),
                    "total_time_ms": round(total_time, 2),
                    "query_results": results,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def check_database_locks(self) -> Dict[str, Any]:
        """Check for long-running transactions and locks"""
        try:
            if self.db_type == "postgresql":
                # PostgreSQL specific lock check
                lock_query = """
                SELECT 
                    pid, 
                    usename, 
                    application_name,
                    client_addr,
                    state,
                    query_start,
                    state_change,
                    EXTRACT(EPOCH FROM (now() - query_start)) as duration_seconds
                FROM pg_stat_activity 
                WHERE state = 'active' 
                AND query_start < now() - interval '30 seconds'
                ORDER BY duration_seconds DESC
                LIMIT 10
                """
                locks = db.session.execute(text(lock_query)).fetchall()

            elif self.db_type == "mysql":
                # MySQL specific lock check
                lock_query = """
                SELECT 
                    trx_id, 
                    trx_state, 
                    trx_started, 
                    trx_mysql_thread_id,
                    trx_query,
                    TIMESTAMPDIFF(SECOND, trx_started, NOW()) as duration_seconds
                FROM information_schema.innodb_trx 
                WHERE trx_started < NOW() - INTERVAL 30 SECOND
                ORDER BY duration_seconds DESC
                LIMIT 10
                """
                locks = db.session.execute(text(lock_query)).fetchall()

            else:
                # SQLite doesn't have the same lock monitoring
                locks = []

            long_running = [
                lock for lock in locks if getattr(lock, "duration_seconds", 0) > 60
            ]

            if long_running:
                status = "warning"
                message = f"{len(long_running)} long-running transactions detected"
            else:
                status = "healthy"
                message = "No long-running transactions detected"

            return {
                "status": status,
                "message": message,
                "details": {
                    "long_running_count": len(long_running),
                    "all_locks": len(locks),
                    "long_running_details": [
                        {
                            "duration_seconds": getattr(lock, "duration_seconds", 0),
                            "query": getattr(
                                lock, "trx_query", getattr(lock, "query", "N/A")
                            ),
                        }
                        for lock in long_running
                    ],
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def check_database_size(self) -> Dict[str, Any]:
        """Monitor database size and growth"""
        try:
            if self.db_type == "postgresql":
                size_query = """
                SELECT 
                    pg_size_pretty(pg_database_size(current_database())) as size,
                    pg_database_size(current_database()) as size_bytes
                """
                result = db.session.execute(text(size_query)).fetchone()
                size_bytes = result.size_bytes

            elif self.db_type == "mysql":
                size_query = """
                SELECT 
                    ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) as size_mb,
                    SUM(data_length + index_length) as size_bytes
                FROM information_schema.tables 
                WHERE table_schema = DATABASE()
                """
                result = db.session.execute(text(size_query)).fetchone()
                size_bytes = result.size_bytes

            else:
                # SQLite
                db_uri = current_app.config_instance.SQLALCHEMY_DATABASE_URI
                if ":memory:" not in db_uri:
                    db_path = db_uri.replace("sqlite:///", "")
                    if os.path.exists(db_path):
                        size_bytes = os.path.getsize(db_path)
                    else:
                        size_bytes = 0
                else:
                    size_bytes = 0

            # Size thresholds (adjust as needed)
            size_mb = size_bytes / (1024 * 1024)
            if size_mb > 1000:  # 1GB
                status = "warning"
                message = f"Database size is large: {size_mb:.2f}MB"
            else:
                status = "healthy"
                message = f"Database size: {size_mb:.2f}MB"

            return {
                "status": status,
                "message": message,
                "details": {"size_mb": round(size_mb, 2), "size_bytes": size_bytes},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    @staticmethod
    def check_table_health() -> Dict[str, Any]:
        """Check health of specific application tables"""
        try:
            tables = {
                "streams": "SELECT COUNT(*) FROM streams",
                "tak_servers": "SELECT COUNT(*) FROM tak_servers",
                "active_streams": "SELECT COUNT(*) FROM streams WHERE is_active = 1",
                "error_streams": "SELECT COUNT(*) FROM streams WHERE last_error IS NOT NULL",
            }

            results = {}
            for table_name, query in tables.items():
                try:
                    count = db.session.execute(text(query)).scalar()
                    results[table_name] = {"count": count, "status": "healthy"}
                except Exception as e:
                    results[table_name] = {"error": str(e), "status": "unhealthy"}

            # Check for potential issues
            warnings = []
            if results.get("error_streams", {}).get("count", 0) > 0:
                warnings.append(
                    f"{results['error_streams']['count']} streams with errors"
                )

            if results.get("active_streams", {}).get("count", 0) == 0:
                warnings.append("No active streams")

            status = "warning" if warnings else "healthy"
            message = "; ".join(warnings) if warnings else "All tables healthy"

            return {
                "status": status,
                "message": message,
                "details": results,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def run_all_database_checks(self) -> Dict[str, Any]:
        """Run all database-related health checks"""
        checks = {
            "connectivity": self.check_database_connectivity(),
            "pool": self.check_connection_pool_health(),
            "performance": self.check_query_performance(),
            "locks": self.check_database_locks(),
            "size": self.check_database_size(),
            "tables": self.check_table_health(),
        }

        # Aggregate results
        return self._aggregate_database_health(checks)

    @staticmethod
    def _aggregate_database_health(checks: Dict[str, Any]) -> Dict[str, Any]:
        """Aggregate individual health check results"""
        db_status = "healthy"
        issues = []
        warnings = []

        for check_name, result in checks.items():
            if result.get("status") == "unhealthy":
                db_status = "unhealthy"
                issues.append(f"{check_name}: {result.get('error', 'Unknown error')}")
            elif result.get("status") == "warning":
                if db_status != "unhealthy":
                    db_status = "warning"
                warnings.append(f"{check_name}: {result.get('message', 'Warning')}")

        return {
            "status": db_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "issues": issues,
            "warnings": warnings,
        }


# Global instance for easy access
health_service = HealthService()
