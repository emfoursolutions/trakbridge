# ABOUTME: Marshmallow schemas for team-member option enumeration endpoints.
# ABOUTME: Backs UI dropdowns for role, color, and combined option payloads.
from marshmallow import Schema, fields


class TeamMemberRolesResponseSchema(Schema):
    """Response body for GET /api/team-member/role-options."""

    roles = fields.List(
        fields.String(),
        required=True,
        metadata={
            "description": (
                "Ordered list of role names (e.g. Team Member, "
                "Team Lead, HQ, Sniper, Medic, ...)."
            )
        },
    )


class TeamMemberColorsResponseSchema(Schema):
    """Response body for GET /api/team-member/color-options."""

    colors = fields.List(
        fields.String(),
        required=True,
        metadata={
            "description": (
                "Ordered list of team color names (e.g. Teal, "
                "Green, Blue, ...)."
            )
        },
    )


class TeamMemberOptionsResponseSchema(Schema):
    """Response body for GET /api/team-member-options.

    Combined enumeration of every option list needed to render the
    callsign-mapping / team-member configuration UI in one call.
    """

    success = fields.Boolean(required=True)
    cot_type_options = fields.List(
        fields.String(),
        metadata={
            "description": (
                "CoT type options (Default, Standard Point, Team "
                "Member)."
            )
        },
    )
    team_role_options = fields.List(fields.String())
    team_color_options = fields.List(fields.String())
