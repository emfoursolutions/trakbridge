# ABOUTME: Marshmallow schemas for inbound stream API request/response bodies.
# ABOUTME: Covers push data ingestion, preview capture, and remap operations.
from marshmallow import Schema, fields


class InboundLocationSchema(Schema):
    """A single location extracted from an inbound payload.

    Plugins produce their own fields; ``lat``, ``lon``, and one of
    ``identifier``/``uid``/``name`` are common but not universal.
    Additional plugin-specific keys are permitted.
    """

    identifier = fields.String()
    name = fields.String()
    uid = fields.String()
    lat = fields.Float(
        metadata={"description": "Latitude in decimal degrees (-90 to 90)."}
    )
    lon = fields.Float(
        metadata={"description": "Longitude in decimal degrees (-180 to 180)."}
    )
    timestamp = fields.String(
        metadata={"description": "ISO 8601 UTC timestamp for the fix."}
    )


class InboundPayloadSchema(Schema):
    """Request body for POST /api/inbound/{stream_id}/data.

    The exact shape depends on the stream's plugin — JSON receiver
    plugins accept dicts of ``{locations: [...]}``, XML/HTTP
    receivers accept the wire format directly. This schema is the
    JSON case; XML consumers should refer to the plugin's docs.
    """

    locations = fields.List(fields.Nested(InboundLocationSchema))


class InboundAckSchema(Schema):
    """Response body for a successful inbound data submission."""

    status = fields.String(
        required=True,
        metadata={
            "description": (
                "'accepted' when locations were queued for CoT "
                "dispatch; 'preview' when the stream is in preview "
                "mode and locations were buffered instead."
            )
        },
    )
    locations_received = fields.Integer(required=True)
    events_created = fields.Integer(
        metadata={"description": "CoT events created (live mode only)."}
    )
    mapped_result = fields.List(
        fields.Nested(InboundLocationSchema),
        metadata={
            "description": "Parsed locations returned in preview mode."
        },
    )
    servers = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        metadata={
            "description": (
                "Per-TAK-server delivery outcome (live mode only)."
            )
        },
    )


class PreviewEntrySchema(Schema):
    """A single captured payload from an inbound stream's buffer."""

    raw_body = fields.String(
        metadata={
            "description": (
                "Original request body decoded as UTF-8 if possible; "
                "otherwise base64-encoded bytes."
            )
        },
    )
    content_type = fields.String()
    headers = fields.Dict(keys=fields.String(), values=fields.String())
    source_ip = fields.String()
    received_at = fields.String(
        metadata={"description": "ISO 8601 UTC capture timestamp."}
    )
    mapped_result = fields.List(fields.Nested(InboundLocationSchema))


class PreviewResponseSchema(Schema):
    """Response body for GET /api/inbound/{stream_id}/preview."""

    stream_id = fields.Integer(required=True)
    preview_mode = fields.Boolean(
        required=True,
        metadata={
            "description": "Whether preview mode is currently enabled."
        },
    )
    payloads = fields.List(fields.Nested(PreviewEntrySchema))


class PreviewClearedSchema(Schema):
    """Response body for DELETE /api/inbound/{stream_id}/preview."""

    status = fields.String(
        required=True,
        metadata={"description": "Always 'cleared' on success."},
    )


class RemapRequestSchema(Schema):
    """Request body for POST /api/inbound/{stream_id}/preview/remap.

    ``plugin_config`` overrides are merged over the stream's stored
    config for the duration of the remap only — nothing is persisted.
    """

    plugin_config = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        metadata={
            "description": (
                "Alternate plugin config values merged over the "
                "stream's stored config for this remap."
            )
        },
    )


class RemapResultEntrySchema(Schema):
    """One remap outcome per captured payload."""

    received_at = fields.String()
    mapped_result = fields.Raw(
        metadata={
            "description": (
                "List of locations on success, or an error object "
                "of the form {'error': '<message>'} on failure."
            )
        },
    )


class RemapResponseSchema(Schema):
    """Response body for POST /api/inbound/{stream_id}/preview/remap."""

    results = fields.List(fields.Nested(RemapResultEntrySchema))
