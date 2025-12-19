"""Debug script to test thumbnail generation"""

from plugins.discord_handler import DiscordHandler

# Simulate config with thumbnails enabled
handler = DiscordHandler({})
handler.config = {
    "use_embeds": "true",
    "use_map_thumbnails": "true",
}

# Test variables with coordinates
variables = {
    "type": "b-a-o-tl",
    "callsign": "Emfour-Alert",
    "lat": "31.9466",
    "lon": "21.0000",
    "mgrs": "31NAA6621000000",
}

print("Testing embed generation with thumbnails enabled...")
print(f"Config: {handler.config}")
print(f"Variables: {variables}")

# Build the embed
embed = handler._build_rich_embed("b-a-o-tl", variables)
print(f"\nEmbed structure: {embed}")

# Check if thumbnail would be added
use_map_thumbnails = handler.config.get("use_map_thumbnails", "false") == "true"
print(f"\nuse_map_thumbnails check: {use_map_thumbnails}")
print(f"Has lat: {bool(variables.get('lat'))}")
print(f"Has lon: {bool(variables.get('lon'))}")

if use_map_thumbnails and variables.get("lat") and variables.get("lon"):
    thumbnail_url = handler._generate_map_thumbnail_url(
        variables["lat"], variables["lon"]
    )
    print(f"\nGenerated thumbnail URL:")
    print(thumbnail_url)

    # Add to embed
    embed["thumbnail"] = {"url": thumbnail_url}
    print(f"\nFinal embed with thumbnail:")
    print(f"  Title: {embed['title']}")
    print(f"  Thumbnail URL: {embed['thumbnail']['url'][:60]}...")
else:
    print("\nThumbnail NOT added - conditions not met")
    print(f"  use_map_thumbnails: {use_map_thumbnails}")
    print(f"  has lat: {bool(variables.get('lat'))}")
    print(f"  has lon: {bool(variables.get('lon'))}")
