"""
ABOUTME: Regression tests ensuring create_stream.html and edit_stream.html share an
ABOUTME: identical JS getCategoryMapping and current plugin category checks.
"""

import re
from pathlib import Path

TEMPLATES = Path(__file__).parent.parent.parent / "templates"


def _extract_category_mapping(template_name):
    """Extract the mapping object literal from getCategoryMapping() as a dict."""
    content = (TEMPLATES / template_name).read_text()
    match = re.search(
        r"function getCategoryMapping\(pluginCategory\)\s*\{\s*"
        r"const mapping = \{(?P<body>.*?)\};",
        content,
        re.DOTALL,
    )
    assert match, f"getCategoryMapping() mapping object not found in {template_name}"
    entries = re.findall(r"'([^']+)':\s*'([^']+)'", match.group("body"))
    return dict(entries)


class TestCategoryMappingConsistency:
    def test_edit_stream_maps_forwarding_category(self):
        """udp_multicast_publisher (category 'forwarding') must not fall back to Other."""
        mapping = _extract_category_mapping("edit_stream.html")
        assert mapping.get("forwarding") == "CoT Forwarding"

    def test_edit_stream_maps_notification_category(self):
        mapping = _extract_category_mapping("edit_stream.html")
        assert mapping.get("notification") == "Notifications"

    def test_edit_stream_has_no_stale_output_category(self):
        """The 'output' category was split in the CoT Forwarding/Notifications refactor."""
        mapping = _extract_category_mapping("edit_stream.html")
        assert "output" not in mapping

    def test_create_and_edit_mappings_identical(self):
        """The duplicated getCategoryMapping() functions must never drift apart."""
        create_mapping = _extract_category_mapping("create_stream.html")
        edit_mapping = _extract_category_mapping("edit_stream.html")
        assert create_mapping == edit_mapping


class TestOutputPluginCheckConsistency:
    def test_edit_stream_output_check_covers_split_categories(self):
        """isOutputPlugin must recognise both 'forwarding' and 'notification'."""
        content = (TEMPLATES / "edit_stream.html").read_text()
        assert (
            "const isOutputPlugin = ['forwarding', 'notification']"
            ".includes(pluginMeta.category?.toLowerCase());" in content
        )

    def test_edit_stream_has_no_stale_output_equality_check(self):
        content = (TEMPLATES / "edit_stream.html").read_text()
        assert "=== 'output'" not in content
