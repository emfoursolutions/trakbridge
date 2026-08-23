# ABOUTME: Marshmallow schema for the monitoring dashboard endpoint.
# ABOUTME: Payload is deeply nested and dynamic; modeled with top-level keys.
from marshmallow import Schema, fields


class QueueMetricsSchema(Schema):
    """Per-TAK-server queue metrics entry.

    Keyed by ``server_{id}`` inside ``dashboard.queues``. Fields
    match the QueueMonitoringService metrics DTO where possible;
    unknown metrics are permitted so future additions do not
    require a schema bump.
    """

    name = fields.String()
    size = fields.Integer()
    throughput = fields.Float()
    errors = fields.Integer()
    health_score = fields.Float()
    utilization = fields.Float()
    batches_per_second = fields.Float()
    overflow_rate = fields.Float()


class DashboardSchema(Schema):
    """Response body for GET /api/monitoring/dashboard.

    Top-level structure is fixed (timestamp + five sub-sections)
    but each sub-section is heterogeneous and evolves per release.
    Consumers should treat every sub-section as best-effort and
    tolerate missing keys.
    """

    timestamp = fields.String(
        required=True,
        metadata={"description": "ISO 8601 UTC snapshot timestamp."},
    )
    queues = fields.Dict(
        keys=fields.String(),
        values=fields.Nested(QueueMetricsSchema),
        metadata={
            "description": (
                "Per-TAK-server queue metrics keyed by "
                "'server_{id}'."
            )
        },
    )
    streams = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        metadata={"description": "Per-stream health and throughput."},
    )
    performance = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        metadata={"description": "Aggregate performance metrics."},
    )
    circuit_breakers = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        metadata={"description": "Circuit breaker state per component."},
    )
    recovery = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        metadata={"description": "Recovery service state snapshot."},
    )
