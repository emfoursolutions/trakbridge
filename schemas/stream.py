# ABOUTME: Marshmallow schemas for stream entities, status, stats, and configs.
# ABOUTME: Mirrors StreamDTO in models/dto.py plus API response envelopes.
from marshmallow import Schema, fields

from schemas.tak_server import TakServerSchema


class CallsignMappingSchema(Schema):
    """A single tracker identifier -> callsign mapping."""

    id = fields.Integer()
    stream_id = fields.Integer()
    identifier_value = fields.String(
        required=True,
        metadata={"description": "Value of the plugin's identifier field."},
    )
    custom_callsign = fields.String(
        required=True,
        metadata={"description": "Callsign to emit in CoT for this tracker."},
    )
    cot_type = fields.String(
        allow_none=True,
        metadata={"description": "Per-mapping CoT type override."},
    )
    enabled = fields.Boolean(
        metadata={"description": "Whether this tracker's CoT is emitted."}
    )


class StreamSchema(Schema):
    """Public representation of a stream."""

    id = fields.Integer(required=True)
    name = fields.String(required=True)
    plugin_type = fields.String(required=True)
    is_active = fields.Boolean(required=True)
    last_poll = fields.String(
        allow_none=True,
        metadata={"description": "ISO 8601 UTC timestamp of the last poll."},
    )
    last_error = fields.String(allow_none=True)
    poll_interval = fields.Integer(required=True)
    cot_type = fields.String(required=True)
    cot_stale_time = fields.Integer(required=True)
    plugin_config = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        metadata={"description": "Plugin-specific config; sensitive fields masked."},
    )
    total_messages_sent = fields.Integer()

    cot_type_mode = fields.String()
    enable_callsign_mapping = fields.Boolean()
    callsign_identifier_field = fields.String(allow_none=True)
    callsign_error_handling = fields.String()

    tak_server = fields.Nested(TakServerSchema, allow_none=True)
    tak_servers = fields.List(fields.Nested(TakServerSchema))
    tak_server_id = fields.Integer(allow_none=True)

    enable_per_callsign_cot_types = fields.Boolean()
    config_version = fields.String(allow_none=True)
    stream_mode = fields.String(
        metadata={"description": "One of: poll, push."},
    )


class StreamStatusSchema(Schema):
    """Per-stream runtime status entry returned by /api/streams/status."""

    id = fields.Integer(required=True)
    name = fields.String(required=True)
    plugin_type = fields.String(required=True)
    is_active = fields.Boolean(required=True)
    worker_running = fields.Boolean(
        metadata={"description": "Whether the stream worker is currently running."}
    )
    last_poll = fields.String(allow_none=True)
    last_error = fields.String(allow_none=True)
    total_messages_sent = fields.Integer()
    tak_server_id = fields.Integer(allow_none=True)


class StreamsStatusEnvelopeSchema(Schema):
    streams = fields.List(fields.Nested(StreamStatusSchema))


class StreamStatsSchema(Schema):
    """Aggregate stream statistics from /api/streams/stats."""

    total = fields.Integer()
    active = fields.Integer()
    inactive = fields.Integer()
    with_errors = fields.Integer()
    total_messages_sent = fields.Integer()


class StreamConfigSchema(Schema):
    """Plugin config subset returned by /api/streams/{id}/config.

    Sensitive fields are masked. Values are plugin-specific; the shape
    is fully open (additional properties allowed).
    """

    class Meta:
        additional = tuple()

    _placeholder = fields.Raw(
        dump_default=None,
        metadata={"description": "Plugin-specific config keys."},
    )


class CallsignMappingsEnvelopeSchema(Schema):
    """Response body for GET /api/streams/{id}/callsign-mappings."""

    success = fields.Boolean(required=True)
    stream_id = fields.Integer(required=True)
    enable_callsign_mapping = fields.Boolean()
    callsign_identifier_field = fields.String(allow_none=True)
    callsign_error_handling = fields.String()
    enable_per_callsign_cot_types = fields.Boolean()
    mappings = fields.List(fields.Nested(CallsignMappingSchema))


class DiscoverTrackersRequestSchema(Schema):
    """Request body for POST /api/streams/discover-trackers."""

    plugin_type = fields.String(
        required=True,
        metadata={"description": "Plugin key (e.g. garmin, spot, traccar)."},
    )
    plugin_config = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        metadata={"description": "Plugin-specific config used for discovery."},
    )
    stream_id = fields.Integer(
        allow_none=True,
        metadata={
            "description": "Existing stream id to merge config with (edit mode)."
        },
    )


class DiscoveredTrackerSchema(Schema):
    identifier = fields.String()
    display_name = fields.String()
    enabled = fields.Boolean()


class DiscoverTrackersResponseSchema(Schema):
    success = fields.Boolean()
    tracker_count = fields.Integer()
    trackers = fields.List(fields.Nested(DiscoveredTrackerSchema))
    available_fields = fields.List(fields.Dict())
    cot_type_options = fields.List(fields.Dict())
    team_role_options = fields.List(fields.Dict())
    team_color_options = fields.List(fields.Dict())
