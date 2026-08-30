# ABOUTME: Marshmallow schema for TAK server entities.
# ABOUTME: Mirrors TakServerDTO in models/dto.py; sensitive fields omitted.
from marshmallow import Schema, fields


class TakServerSchema(Schema):
    """Public representation of a TAK server.

    Sensitive fields (cert_password, private key contents) are never
    serialised; ``has_cert_password`` is a boolean indicator only.
    """

    id = fields.Integer(required=True)
    name = fields.String(required=True)
    host = fields.String(required=True)
    port = fields.Integer(required=True)
    protocol = fields.String(
        required=True,
        metadata={"description": "One of: tcp, ssl."},
    )
    enabled = fields.Boolean()
    description = fields.String(allow_none=True)
    cert_file = fields.String(allow_none=True)
    key_file = fields.String(allow_none=True)
    ca_file = fields.String(allow_none=True)
    verify_ssl = fields.Boolean()
    cert_p12 = fields.String(allow_none=True)
    has_cert_password = fields.Boolean()

    enable_rx = fields.Boolean(
        metadata={"description": "Receive CoT from this TAK server."}
    )
    identity_enabled = fields.Boolean()
    identity_callsign = fields.String(allow_none=True)
    identity_role = fields.String(allow_none=True)
    identity_team_color = fields.String(allow_none=True)
    identity_location_mgrs = fields.String(allow_none=True)
    identity_uid_suffix = fields.String(allow_none=True)
