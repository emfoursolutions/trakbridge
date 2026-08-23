# ABOUTME: Marshmallow schemas for OpenAPI 3.1 request/response bodies.
# ABOUTME: Exposes ALL_SCHEMAS consumed by services.openapi_service.build_spec().
from schemas.common import ErrorSchema, SuccessSchema, PaginationSchema
from schemas.health import (
    HealthCheckSchema,
    DetailedHealthSchema,
    ComponentHealthSchema,
    ReadinessSchema,
    LivenessSchema,
    StatusSchema,
    VersionSchema,
)

ALL_SCHEMAS = [
    ErrorSchema,
    SuccessSchema,
    PaginationSchema,
    HealthCheckSchema,
    DetailedHealthSchema,
    ComponentHealthSchema,
    ReadinessSchema,
    LivenessSchema,
    StatusSchema,
    VersionSchema,
]

__all__ = ["ALL_SCHEMAS"] + [s.__name__ for s in ALL_SCHEMAS]
