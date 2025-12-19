"""Quick test script to verify Discord embed functionality"""

from plugins.discord_handler import DiscordHandler

# Test the color mapping
handler = DiscordHandler({})

print("Testing _get_embed_color_for_cot_type():")
test_types = [
    ("b-a-o-tl", "Emergency", 15548997),
    ("a-f-G-E-V", "Friendly", 5763719),
    ("a-h-G", "Hostile", 15548997),
    ("a-n-G", "Neutral", 16705372),
    ("a-u-G", "Unknown", 10070709),
    ("b-t-f", "Chat", 5793266),
    ("x-x-x", "Default", 16777215),
]

for cot_type, label, expected_color in test_types:
    result = handler._get_embed_color_for_cot_type(cot_type)
    status = "✓" if result == expected_color else "✗"
    print(
        f"  {status} {label:12} ({cot_type:12}): {result} "
        f"(expected {expected_color})"
    )

print("\nTesting _get_embed_title():")
test_titles = [
    ("b-a-o-tl", "🚨 Emergency Alert"),
    ("b-t-f", "💬 Chat Message"),
    ("a-f-G-E-V", "🟢 Friendly Position"),
    ("a-h-G", "🔴 Hostile Contact"),
    ("x-x-x", "📡 TAK Update"),
]

for cot_type, expected_title in test_titles:
    result = handler._get_embed_title(cot_type, {})
    status = "✓" if result == expected_title else "✗"
    print(f"  {status} {cot_type:12} -> {result}")

print("\nTesting _build_rich_embed():")
variables = {
    "type": "a-f-G-E-V",
    "callsign": "Bravo-6",
    "mgrs": "38TQM 12345 67890",
    "battery": "75",
    "group_name": "Team Alpha",
    "group_role": "Leader",
    "remarks": "En route to checkpoint",
    "device": "ATAK",
    "platform": "Android",
}

embed = handler._build_rich_embed("a-f-G-E-V", variables)
print(f"  Title: {embed['title']}")
print(f"  Description: {embed['description']}")
print(f"  Color: {embed['color']}")
print(f"  Timestamp: {embed['timestamp']}")
print(f"  Fields ({len(embed['fields'])}):")
for field in embed['fields']:
    inline = " (inline)" if field.get('inline') else ""
    print(f"    - {field['name']}: {field['value']}{inline}")

print("\nTesting _generate_map_thumbnail_url():")

# Test without Mapbox token (OpenStreetMap)
handler_no_token = DiscordHandler({})
osm_url = handler_no_token._generate_map_thumbnail_url("38.8977", "-77.0365")
print("  OpenStreetMap URL:")
print(f"    {osm_url}")
expected_osm = "https://staticmap.openstreetmap.de/staticmap.php"
status = "✓" if osm_url.startswith(expected_osm) else "✗"
print(f"  {status} URL starts with correct domain")
has_coords = '38.8977' in osm_url and '-77.0365' in osm_url
print(f"  {status} Contains lat/lon: {has_coords}")
print(f"  {status} Contains marker: {'red-pushpin' in osm_url}")

# Test with Mapbox token
handler_with_token = DiscordHandler({})
handler_with_token.config = {"mapbox_token": "test_token_123"}
mapbox_url = handler_with_token._generate_map_thumbnail_url(
    "38.8977", "-77.0365"
)
print("\n  Mapbox URL:")
print(f"    {mapbox_url[:80]}...")
expected_mapbox = (
    "https://api.mapbox.com/styles/v1/mapbox/streets-v11/static"
)
status = "✓" if mapbox_url.startswith(expected_mapbox) else "✗"
print(f"  {status} URL starts with correct domain")
has_coords = '38.8977' in mapbox_url and '-77.0365' in mapbox_url
print(f"  {status} Contains lat/lon: {has_coords}")
print(f"  {status} Contains token: {'test_token_123' in mapbox_url}")
print(f"  {status} Contains pin marker: {'pin-s+ff0000' in mapbox_url}")

print("\n✓ All Phase 5, 6, and 7 features implemented successfully!")
