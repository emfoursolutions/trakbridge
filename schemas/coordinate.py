# ABOUTME: Marshmallow schemas for coordinate conversion endpoints.
# ABOUTME: Wraps the two /api/convert-* utilities for lat/lon <-> MGRS.
from marshmallow import Schema, fields


class LatLonRequestSchema(Schema):
    """Request body for POST /api/convert-latlon-to-mgrs."""

    lat = fields.Float(
        required=True,
        metadata={"description": "Latitude in decimal degrees (-90 to 90)."},
    )
    lon = fields.Float(
        required=True,
        metadata={
            "description": "Longitude in decimal degrees (-180 to 180)."
        },
    )


class LatLonResponseSchema(Schema):
    """Successful response for POST /api/convert-latlon-to-mgrs."""

    success = fields.Boolean(required=True)
    mgrs = fields.String(
        required=True,
        metadata={"description": "MGRS coordinate string (e.g. '38SMB4484')."},
    )


class MgrsRequestSchema(Schema):
    """Request body for POST /api/convert-mgrs-to-latlon."""

    mgrs = fields.String(
        required=True,
        metadata={
            "description": "MGRS coordinate string (e.g. '38SMB4484')."
        },
    )


class MgrsResponseSchema(Schema):
    """Successful response for POST /api/convert-mgrs-to-latlon."""

    success = fields.Boolean(required=True)
    lat = fields.Float(
        required=True,
        metadata={"description": "Latitude in decimal degrees."},
    )
    lon = fields.Float(
        required=True,
        metadata={"description": "Longitude in decimal degrees."},
    )


class CoordinateErrorSchema(Schema):
    """Failure envelope used by both coordinate conversion routes.

    Distinct from the shared ErrorSchema because these routes wrap
    every failure in ``{success: false, error: ...}`` rather than
    the ``{error, message, status}`` envelope used elsewhere.
    """

    success = fields.Boolean(required=True)
    error = fields.String(required=True)
