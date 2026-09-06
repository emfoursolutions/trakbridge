# ABOUTME: Shared marshmallow schemas for common OpenAPI structures.
# ABOUTME: Error/Success/Pagination envelopes reused across API responses.
from marshmallow import Schema, fields


class ErrorSchema(Schema):
    error = fields.String(
        required=True,
        metadata={"description": "Short error identifier."},
    )
    message = fields.String(
        metadata={"description": "Human-readable error detail."}
    )
    status = fields.Integer(
        metadata={"description": "HTTP status code."}
    )


class SuccessSchema(Schema):
    success = fields.Boolean(required=True)
    message = fields.String()


class PaginationSchema(Schema):
    total = fields.Integer(required=True)
    page = fields.Integer(required=True)
    per_page = fields.Integer(required=True)
    pages = fields.Integer(required=True)
