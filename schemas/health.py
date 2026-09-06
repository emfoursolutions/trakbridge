# ABOUTME: Marshmallow schemas for health, status, and version endpoints.
# ABOUTME: Mirrors JSON returned by routes/api.py health check handlers.
from marshmallow import Schema, fields


class ComponentHealthSchema(Schema):
    status = fields.String(
        required=True,
        metadata={
            "description": "One of: healthy, degraded, unhealthy, warning."
        },
    )
    message = fields.String()
    error = fields.String()
    error_type = fields.String()
    timestamp = fields.String(
        metadata={"description": "ISO 8601 UTC timestamp."}
    )
    details = fields.Dict(keys=fields.String(), values=fields.Raw())


class HealthCheckSchema(Schema):
    status = fields.String(
        required=True,
        metadata={"description": "One of: healthy, starting, unhealthy."},
    )
    timestamp = fields.String(required=True)
    version = fields.String(required=True)
    service = fields.String(required=True)
    startup = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        metadata={
            "description": "Present only while startup is still in progress."
        },
    )


class DetailedHealthSchema(Schema):
    status = fields.String(required=True)
    timestamp = fields.String(required=True)
    response_time_ms = fields.Float(required=True)
    version = fields.String(required=True)
    service = fields.String(required=True)
    checks = fields.Dict(
        keys=fields.String(),
        values=fields.Nested(ComponentHealthSchema),
    )
    critical_failures = fields.List(fields.String())


class ReadinessSchema(Schema):
    status = fields.String(
        required=True,
        metadata={"description": "One of: ready, not_ready."},
    )
    timestamp = fields.String(required=True)
    failed_check = fields.String()
    error = fields.String()


class LivenessSchema(Schema):
    status = fields.String(
        required=True,
        metadata={"description": "Always 'alive'."},
    )
    timestamp = fields.String(required=True)
    uptime_seconds = fields.Float(required=True)


class StatusSchema(Schema):
    total_streams = fields.Integer(required=True)
    active_streams = fields.Integer(required=True)
    tak_servers = fields.Integer(required=True)
    running_workers = fields.Integer(required=True)


class VersionSchema(Schema):
    version = fields.String(
        required=True,
        metadata={"description": "Current TrakBridge version string."},
    )
