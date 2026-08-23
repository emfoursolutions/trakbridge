# ABOUTME: Marshmallow schemas for OpenAPI 3.1 request/response bodies.
# ABOUTME: Exposes ALL_SCHEMAS consumed by services.openapi_service.
from schemas.common import ErrorSchema, PaginationSchema, SuccessSchema
from schemas.health import (
    ComponentHealthSchema,
    DetailedHealthSchema,
    HealthCheckSchema,
    LivenessSchema,
    ReadinessSchema,
    StatusSchema,
    VersionSchema,
)
from schemas.plugin import (
    PluginAvailableFieldsResponseSchema,
    PluginCategorySchema,
    PluginFieldSchema,
    PluginMetadataSchema,
    PluginSummarySchema,
    PluginsByCategoryEnvelopeSchema,
)
from schemas.stream import (
    CallsignMappingSchema,
    CallsignMappingsEnvelopeSchema,
    DiscoverTrackersRequestSchema,
    DiscoverTrackersResponseSchema,
    DiscoveredTrackerSchema,
    StreamConfigSchema,
    StreamSchema,
    StreamStatsSchema,
    StreamStatusSchema,
    StreamsStatusEnvelopeSchema,
)
from schemas.tak_server import TakServerSchema

ALL_SCHEMAS = [
    # common
    ErrorSchema,
    SuccessSchema,
    PaginationSchema,
    # health / status / version
    HealthCheckSchema,
    DetailedHealthSchema,
    ComponentHealthSchema,
    ReadinessSchema,
    LivenessSchema,
    StatusSchema,
    VersionSchema,
    # tak server
    TakServerSchema,
    # streams
    StreamSchema,
    StreamStatusSchema,
    StreamsStatusEnvelopeSchema,
    StreamStatsSchema,
    StreamConfigSchema,
    CallsignMappingSchema,
    CallsignMappingsEnvelopeSchema,
    DiscoverTrackersRequestSchema,
    DiscoveredTrackerSchema,
    DiscoverTrackersResponseSchema,
    # plugins
    PluginCategorySchema,
    PluginSummarySchema,
    PluginsByCategoryEnvelopeSchema,
    PluginFieldSchema,
    PluginAvailableFieldsResponseSchema,
    PluginMetadataSchema,
]

__all__ = ["ALL_SCHEMAS"] + [s.__name__ for s in ALL_SCHEMAS]
