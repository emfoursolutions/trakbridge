# ABOUTME: Marshmallow schemas for plugin metadata, categories, and fields.
# ABOUTME: Response shapes returned by routes/api.py plugin endpoints.
from marshmallow import Schema, fields


class PluginCategorySchema(Schema):
    """Category descriptor returned by /api/plugins/categories."""

    key = fields.String(required=True)
    display_name = fields.String(required=True)
    description = fields.String()
    icon = fields.String(allow_none=True)
    plugin_count = fields.Integer()


class PluginSummarySchema(Schema):
    """Summary of a single plugin (as returned in category listings)."""

    key = fields.String(required=True)
    display_name = fields.String(required=True)
    description = fields.String()
    icon = fields.String(allow_none=True)
    category = fields.String()


class PluginsByCategoryEnvelopeSchema(Schema):
    """Response body for /api/plugins/by-category/{category}."""

    category = fields.String(required=True)
    plugins = fields.List(fields.Nested(PluginSummarySchema))


class PluginFieldSchema(Schema):
    """Available identifier field descriptor for a plugin."""

    name = fields.String(required=True)
    display_name = fields.String()
    type = fields.String()
    recommended = fields.Boolean()
    description = fields.String()


class PluginAvailableFieldsResponseSchema(Schema):
    """Response body for /api/plugins/{plugin_type}/available-fields."""

    success = fields.Boolean(required=True)
    plugin_type = fields.String(required=True)
    available_fields = fields.List(fields.Nested(PluginFieldSchema))
    supports_callsign_mapping = fields.Boolean()


class PluginMetadataSchema(Schema):
    """Serialised plugin metadata.

    Plugins carry rich metadata (display name, config fields, help
    text, category, icon, capabilities). The shape is plugin-specific
    so this schema is intentionally open; ``config_fields`` is the
    only field guaranteed by every plugin.
    """

    display_name = fields.String()
    description = fields.String()
    icon = fields.String(allow_none=True)
    category = fields.String()
    config_fields = fields.List(fields.Dict())
    capabilities = fields.Dict(
        keys=fields.String(),
        values=fields.Raw(),
        metadata={"description": "Plugin capability flags and hints."},
    )
