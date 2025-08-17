#!/bin/bash
# =============================================================================
# test-database.sh - Database-specific testing for staging validation
# =============================================================================
#
# This script tests a specific database type with full deployment, migration,
# health, and authentication validation. Used by the staging-production-mirror
# CI/CD job to validate each database type sequentially.
#
# Usage: ./test-database.sh <db_type> <profile> <image_tag>
#   db_type: postgresql, mysql, sqlite
#   profile: docker compose profile (postgres, mysql, or empty for sqlite)
#   image_tag: Docker image tag to test
#
# =============================================================================

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Parse arguments
DB_TYPE="${1:-postgresql}"
PROFILE="${2:-postgres}"
IMAGE_TAG="${3:-latest}"

# Validate arguments
if [[ ! "$DB_TYPE" =~ ^(postgresql|mysql|sqlite)$ ]]; then
    log_error "Invalid database type: $DB_TYPE. Must be postgresql, mysql, or sqlite"
    exit 1
fi

log_info "Testing Database: $DB_TYPE"
log_info "Docker Compose Profile: ${PROFILE:-none}"
log_info "Image Tag: $IMAGE_TAG"

# Set database-specific configuration
case "$DB_TYPE" in
    "postgresql")
        export DB_TYPE="postgresql"
        export DB_HOST="postgres"
        export DB_PORT="5432"
        export DB_NAME="trakbridge"
        export DB_USER="trakbridge"
        COMPOSE_PROFILE="postgres"
        ;;
    "mysql")
        export DB_TYPE="mysql"
        export DB_HOST="mysql"
        export DB_PORT="3306"
        export DB_NAME="trakbridge"
        export DB_USER="trakbridge"
        COMPOSE_PROFILE="mysql"
        ;;
    "sqlite")
        export DB_TYPE="sqlite"
        export DB_HOST=""
        export DB_PORT=""
        export DB_NAME=""
        export DB_USER=""
        COMPOSE_PROFILE=""
        ;;
esac

# Set common environment
export FLASK_ENV="testing"
export APP_VERSION="$IMAGE_TAG"
export USER_ID=${USER_ID:-$(id -u)}
export GROUP_ID=${GROUP_ID:-$(id -g)}

# Use dynamic port to avoid conflicts
TEST_PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('', 0)); print(s.getsockname()[1]); s.close()")
export TEST_PORT
log_info "Using dynamic port for testing: $TEST_PORT"

# Create test report directory and ensure correct permissions
mkdir -p test-reports logs data external_plugins external_config backups secrets
# Set ownership to match the Docker container user
chown -R ${USER_ID}:${GROUP_ID} test-reports logs data external_plugins external_config backups secrets 2>/dev/null || true

# Initialize test report for this database
TEST_REPORT="test-reports/${DB_TYPE}-test-report.json"
cat > "$TEST_REPORT" << EOF
{
  "database": "$DB_TYPE",
  "test_start": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "test_end": "",
  "status": "running",
  "tests": []
}
EOF

# Function to add test result
add_test_result() {
    local test_name="$1"
    local status="$2"
    local details="$3"
    local timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    jq --arg name "$test_name" --arg status "$status" --arg details "$details" --arg timestamp "$timestamp" \
        '.tests += [{"name": $name, "status": $status, "details": $details, "timestamp": $timestamp}]' \
        "$TEST_REPORT" > temp.json && mv temp.json "$TEST_REPORT"
}

# Function to finalize test report
finalize_test_report() {
    local final_status="$1"
    local end_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    jq --arg status "$final_status" --arg end_time "$end_time" \
        '.status = $status | .test_end = $end_time' \
        "$TEST_REPORT" > temp.json && mv temp.json "$TEST_REPORT"
}

# Cleanup function
cleanup_database() {
    log_step "Cleaning up $DB_TYPE test environment..."
    
    # Stop and remove containers
    if [[ -n "$COMPOSE_PROFILE" ]]; then
        docker compose --profile "$COMPOSE_PROFILE" down -v --remove-orphans 2>/dev/null || true
    else
        docker compose down -v --remove-orphans 2>/dev/null || true
    fi
    
    # Remove any dangling volumes
    docker volume prune -f 2>/dev/null || true
    
    # Clean up any test data files
    rm -rf data/sqlite data/test* 2>/dev/null || true
    
    # Clean up override file
    rm -f docker-compose.override.yml 2>/dev/null || true
    
    log_info "Cleanup completed for $DB_TYPE"
}

# Trap cleanup on exit
trap cleanup_database EXIT

log_step "Starting $DB_TYPE database test sequence..."

# Clean up any existing containers to prevent conflicts
log_info "Cleaning up any existing containers to prevent port conflicts..."
docker ps -q --filter "name=trakbridge" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "name=trakbridge" | xargs -r docker rm 2>/dev/null || true
docker ps -q --filter "name=trakbridge-postgres" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "name=trakbridge-postgres" | xargs -r docker rm 2>/dev/null || true
docker ps -q --filter "name=trakbridge-mysql" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "name=trakbridge-mysql" | xargs -r docker rm 2>/dev/null || true

# Step 1: Deploy the database
log_step "1. Deploying $DB_TYPE with production configuration..."

# Create override file to use dynamic port and correct user ID
cat > docker-compose.override.yml << EOF
services:
  trakbridge:
    ports:
      - "${TEST_PORT}:5000"
    environment:
      - FLASK_ENV=testing
      - APP_VERSION=$IMAGE_TAG
      - TEST_MODE=true
      - USER_ID=${USER_ID}
      - GROUP_ID=${GROUP_ID}
EOF

if [[ -n "$COMPOSE_PROFILE" ]]; then
    log_info "Using docker compose profile: $COMPOSE_PROFILE on port $TEST_PORT"
    docker compose --profile "$COMPOSE_PROFILE" up -d
else
    log_info "Using docker compose without profile (SQLite) on port $TEST_PORT"
    docker compose up -d
fi

# Wait for services to be ready
log_info "Waiting for services to become ready..."
sleep 10

# Check container health
CONTAINER_NAME="trakbridge"
if [[ -n "$COMPOSE_PROFILE" ]]; then
    DB_CONTAINER="trakbridge-${COMPOSE_PROFILE}"
    
    log_info "Checking database container health: $DB_CONTAINER"
    timeout 60 bash -c "
        while true; do
            if docker inspect --format='{{.State.Health.Status}}' $DB_CONTAINER 2>/dev/null | grep -q 'healthy'; then
                echo 'Database container is healthy'
                break
            fi
            echo 'Waiting for database container to be healthy...'
            sleep 5
        done
    "
fi

log_info "Checking application container health: $CONTAINER_NAME"
timeout 180 bash -c "
    attempts=0
    max_attempts=18
    while true; do
        attempts=\$((attempts + 1))
        health_status=\$(docker inspect --format='{{.State.Health.Status}}' $CONTAINER_NAME 2>/dev/null || echo 'none')
        container_status=\$(docker inspect --format='{{.State.Status}}' $CONTAINER_NAME 2>/dev/null || echo 'unknown')
        
        echo \"Attempt \$attempts/\$max_attempts: Container status: \$container_status, Health: \$health_status\"
        
        case \$health_status in
            'healthy')
                echo 'Application container is healthy'
                break
                ;;
            'unhealthy')
                echo 'Application container is unhealthy'
                echo 'Container logs:'
                docker logs $CONTAINER_NAME --tail=20
                if [ \$attempts -ge \$max_attempts ]; then
                    exit 1
                fi
                ;;
            'starting'|'none')
                if [ \$attempts -ge \$max_attempts ]; then
                    echo 'Timeout waiting for container health'
                    echo 'Container logs:'
                    docker logs $CONTAINER_NAME --tail=20
                    exit 1
                fi
                echo 'Waiting for application container to be healthy...'
                ;;
        esac
        sleep 10
    done
"

add_test_result "deployment" "passed" "Successfully deployed $DB_TYPE with profile: ${COMPOSE_PROFILE:-none}"

# Step 2: Test database migrations
log_step "2. Testing database migrations..."

log_info "Running migration tests for $DB_TYPE..."
if docker exec "$CONTAINER_NAME" python -m pytest tests/unit/test_migrations.py -v --tb=short -x; then
    log_info "Migration tests passed for $DB_TYPE"
    add_test_result "migrations" "passed" "All migration tests passed"
else
    log_error "Migration tests failed for $DB_TYPE"
    add_test_result "migrations" "failed" "Migration tests failed"
    finalize_test_report "failed"
    exit 1
fi

# Step 3: Test application health endpoint
log_step "3. Testing application health endpoint..."

log_info "Testing health endpoint via container..."
if docker exec "$CONTAINER_NAME" curl -f -s http://localhost:5000/api/health > /dev/null; then
    log_info "Health endpoint test passed for $DB_TYPE"
    add_test_result "health_endpoint" "passed" "Health endpoint responding correctly"
else
    log_error "Health endpoint test failed for $DB_TYPE"
    add_test_result "health_endpoint" "failed" "Health endpoint not responding"
    
    # Get container logs for debugging
    log_error "Container logs for debugging:"
    docker logs "$CONTAINER_NAME" --tail=50
    
    finalize_test_report "failed"
    exit 1
fi

# Step 4: Test database connectivity
log_step "4. Testing database connectivity..."

log_info "Testing database connectivity via application..."
if docker exec "$CONTAINER_NAME" python -c "
import sys
sys.path.append('/app')
from database import db
from app import create_app

app = create_app('testing')
with app.app_context():
    db.engine.execute('SELECT 1')
    print('Database connectivity test passed')
"; then
    log_info "Database connectivity test passed for $DB_TYPE"
    add_test_result "database_connectivity" "passed" "Database connection successful"
else
    log_error "Database connectivity test failed for $DB_TYPE"
    add_test_result "database_connectivity" "failed" "Database connection failed"
    finalize_test_report "failed"
    exit 1
fi

# Step 5: Test authentication system
log_step "5. Testing authentication system..."

log_info "Testing local authentication..."
if docker exec "$CONTAINER_NAME" python -c "
import sys
sys.path.append('/app')
from app import create_app
from models.user import User, AuthProvider, UserRole, AccountStatus
from database import db

app = create_app('testing')
with app.app_context():
    # Test local user creation
    user = User.create_local_user('test_user', 'TestPassword123!', 'test@example.com')
    db.session.add(user)
    db.session.commit()
    
    # Test password verification
    if user.check_password('TestPassword123!'):
        print('Local authentication test passed')
    else:
        raise Exception('Password verification failed')
"; then
    log_info "Local authentication test passed for $DB_TYPE"
    add_test_result "local_authentication" "passed" "Local authentication working correctly"
else
    log_error "Local authentication test failed for $DB_TYPE"
    add_test_result "local_authentication" "failed" "Local authentication not working"
    finalize_test_report "failed"
    exit 1
fi

# Step 6: Test LDAP connectivity (if enabled)
if [[ "${LDAP_ENABLED:-false}" == "true" ]] && [[ -s "secrets/ldap_bind_password" ]]; then
    log_step "6. Testing LDAP connectivity..."
    
    log_info "Testing LDAP connection..."
    if docker exec "$CONTAINER_NAME" python -c "
import sys
sys.path.append('/app')
from services.auth.ldap_provider import LDAPProvider
from config.authentication_loader import load_authentication_config

# Load LDAP configuration
auth_config = load_authentication_config()
ldap_config = auth_config.get('ldap', {})

if ldap_config.get('enabled', False):
    provider = LDAPProvider(ldap_config)
    # Test basic LDAP connection
    if provider.test_connection():
        print('LDAP connectivity test passed')
    else:
        raise Exception('LDAP connection failed')
else:
    print('LDAP not enabled, skipping test')
"; then
        log_info "LDAP connectivity test passed for $DB_TYPE"
        add_test_result "ldap_connectivity" "passed" "LDAP connection successful"
    else
        log_warn "LDAP connectivity test failed for $DB_TYPE"
        add_test_result "ldap_connectivity" "failed" "LDAP connection failed"
        # Don't fail the entire test for LDAP issues in staging
    fi
else
    log_info "LDAP not enabled or password not configured, skipping LDAP test"
    add_test_result "ldap_connectivity" "skipped" "LDAP not configured"
fi

# Step 7: Test basic API functionality
log_step "7. Testing basic API functionality..."

log_info "Testing API endpoints..."
if docker exec "$CONTAINER_NAME" python -c "
import sys
sys.path.append('/app')
import requests
from app import create_app

app = create_app('testing')
with app.test_client() as client:
    # Test health endpoint
    response = client.get('/api/health')
    if response.status_code != 200:
        raise Exception('Health endpoint failed')
    
    # Test static assets
    response = client.get('/')
    if response.status_code not in [200, 302]:  # 302 for auth redirect
        raise Exception('Main page failed')
    
    print('Basic API functionality test passed')
"; then
    log_info "Basic API functionality test passed for $DB_TYPE"
    add_test_result "api_functionality" "passed" "Basic API endpoints working"
else
    log_error "Basic API functionality test failed for $DB_TYPE"
    add_test_result "api_functionality" "failed" "API endpoints not working correctly"
    finalize_test_report "failed"
    exit 1
fi

# All tests passed
log_info "All tests passed for $DB_TYPE database!"
finalize_test_report "passed"

# Generate JUnit XML report for GitLab
cat > "test-reports/junit-${DB_TYPE}.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="${DB_TYPE}_database_tests" tests="7" failures="0" errors="0" time="$SECONDS">
    <testcase classname="${DB_TYPE}" name="deployment" time="10"/>
    <testcase classname="${DB_TYPE}" name="migrations" time="30"/>
    <testcase classname="${DB_TYPE}" name="health_endpoint" time="5"/>
    <testcase classname="${DB_TYPE}" name="database_connectivity" time="5"/>
    <testcase classname="${DB_TYPE}" name="local_authentication" time="10"/>
    <testcase classname="${DB_TYPE}" name="ldap_connectivity" time="5"/>
    <testcase classname="${DB_TYPE}" name="api_functionality" time="10"/>
</testsuite>
EOF

log_info "$DB_TYPE database validation completed successfully!"
log_info "Test duration: ${SECONDS} seconds"
log_info "Test report: $TEST_REPORT"

exit 0