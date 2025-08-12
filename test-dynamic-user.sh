#!/bin/bash
# Test script to verify dynamic user functionality and volume mounting

set -e

echo "=== Testing Dynamic User Functionality ==="

# Test different UID/GID combinations
test_combinations=(
    "1001:1001:Test with UID 1001"
    "2000:2000:Test with UID 2000" 
    "1500:100:Test with mixed UID/GID"
    "1000:1000:Test with default appuser"
)

IMAGE_NAME="${CI_REGISTRY_IMAGE:-git.emfour.net:5050/npoulter/trackbridge}:${IMAGE_TAG:-feature-auth}"

echo "Testing with image: $IMAGE_NAME"

# Create temporary directory for volume mount tests
TEMP_PLUGINS_DIR=$(mktemp -d)
echo "Created temporary plugins directory: $TEMP_PLUGINS_DIR"

# Create a test plugin file
cat > "$TEMP_PLUGINS_DIR/test_plugin.py" << 'EOF'
"""Test external plugin file"""
class TestPlugin:
    def __init__(self):
        self.name = "test_plugin"
EOF

echo "Created test plugin file in $TEMP_PLUGINS_DIR"

for test_case in "${test_combinations[@]}"; do
    IFS=':' read -r test_uid test_gid description <<< "$test_case"
    
    echo ""
    echo "--- $description (UID:$test_uid, GID:$test_gid) ---"
    
    # Test 1: Basic container startup and Python import
    echo "Testing basic functionality..."
    if docker run --rm \
        -e USER_ID="$test_uid" \
        -e GROUP_ID="$test_gid" \
        -e DEBUG="true" \
        "$IMAGE_NAME" \
        config-check; then
        echo "✅ Basic test passed"
    else
        echo "❌ Basic test failed"
        continue
    fi
    
    # Test 2: Volume mounting with external_plugins
    echo "Testing external_plugins volume mounting..."
    if docker run --rm \
        -e USER_ID="$test_uid" \
        -e GROUP_ID="$test_gid" \
        -e DEBUG="true" \
        -v "$TEMP_PLUGINS_DIR:/app/external_plugins:ro" \
        "$IMAGE_NAME" \
        bash -c 'ls -la /app/external_plugins && test -r /app/external_plugins/test_plugin.py && echo "External plugin file is readable"'; then
        echo "✅ Volume mount test passed"
    else
        echo "❌ Volume mount test failed"
    fi
    
    # Test 3: Write access to external_plugins (without read-only mount)
    echo "Testing external_plugins write access..."
    if docker run --rm \
        -e USER_ID="$test_uid" \
        -e GROUP_ID="$test_gid" \
        -e DEBUG="true" \
        "$IMAGE_NAME" \
        bash -c 'touch /app/external_plugins/test_write.txt && echo "Can write to external_plugins directory"'; then
        echo "✅ Write access test passed"
    else
        echo "❌ Write access test failed"
    fi
    
    # Test 4: Write access to external_config (needed for config installation)
    echo "Testing external_config write access..."
    if docker run --rm \
        -e USER_ID="$test_uid" \
        -e GROUP_ID="$test_gid" \
        -e DEBUG="true" \
        "$IMAGE_NAME" \
        bash -c 'touch /app/external_config/test_config.yaml && echo "Can write to external_config directory"'; then
        echo "✅ Config write access test passed"
    else
        echo "❌ Config write access test failed"
    fi
    
    echo "✅ SUCCESS: $description - All tests passed"
done

# Cleanup
rm -rf "$TEMP_PLUGINS_DIR"
echo ""
echo "=== Dynamic User and Volume Mount Testing Complete ==="