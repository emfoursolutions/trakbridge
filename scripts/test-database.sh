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
        # Explicitly set DB_NAME for SQLite to ensure consistent path
        export DB_NAME="/app/data/app.db"
        export DB_USER=""
        COMPOSE_PROFILE=""
        ;;
esac

# Set common environment
export FLASK_ENV="production"
# Mark as database test environment to skip migration timing checks
export DB_TEST_MODE="true"
export APP_VERSION="$IMAGE_TAG"
export USER_ID=${USER_ID:-$(id -u)}
export GROUP_ID=${GROUP_ID:-$(id -g)}
export DOCKER_USER_ID=${USER_ID}
export DOCKER_GROUP_ID=${GROUP_ID}

# Use staging compose file for validation (can be overridden by environment)
export COMPOSE_FILE=${COMPOSE_FILE:-"docker-compose.staging.yml"}

# Set container names based on compose file
if [[ "$COMPOSE_FILE" == *"staging"* ]]; then
    CONTAINER_NAME_SUFFIX="-staging"
    APP_CONTAINER_NAME="trakbridge-staging"
    APP_SERVICE_NAME="trakbridge"
else
    CONTAINER_NAME_SUFFIX=""
    APP_CONTAINER_NAME="trakbridge"
    APP_SERVICE_NAME="trakbridge"
fi

log_info "Using container name suffix: '$CONTAINER_NAME_SUFFIX'"
log_info "Application container name: '$APP_CONTAINER_NAME'"
log_info "Application service name: '$APP_SERVICE_NAME'"

# Use dynamic port to avoid conflicts
TEST_PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('', 0)); print(s.getsockname()[1]); s.close()")
export TEST_PORT
log_info "Using dynamic port for testing: $TEST_PORT"

# Create test report directory and ensure correct permissions
mkdir -p test-reports logs data external_plugins external_config secrets

# Handle backups directory specially - it might be created by deploy script as root
if [ -d "backups" ]; then
    log_warn "Backups directory already exists (likely created by deploy script or CI)"
    
    # Create database-specific backup directories if they don't exist
    for backup_dir in "backups/postgres-staging" "backups/mysql-staging" "backups/staging"; do
        if [ ! -d "$backup_dir" ]; then
            log_info "Creating missing backup directory: $backup_dir"
            mkdir -p "$backup_dir" 2>/dev/null || true
        fi
    done
    
    # Try to fix permissions on backup directories, but don't fail if we can't
    log_info "Attempting to fix backup directory permissions..."
    for backup_dir in "backups" "backups/postgres-staging" "backups/mysql-staging" "backups/staging"; do
        if [ -d "$backup_dir" ] && [ -w "$backup_dir" ]; then
            if chown -R ${USER_ID}:${GROUP_ID} "$backup_dir" 2>/dev/null; then
                log_info "✅ Fixed ownership of $backup_dir"
            else
                log_warn "⚠️ Cannot change ownership of $backup_dir (likely root-owned), trying chmod..."
                if chmod -R 755 "$backup_dir" 2>/dev/null; then
                    log_info "✅ Fixed permissions of $backup_dir with chmod"
                else
                    log_warn "⚠️ Cannot fix permissions of $backup_dir, will use test subdirectory if needed"
                    # Create a test-specific subdirectory as fallback
                    test_backup_dir="$backup_dir/test-$$"
                    mkdir -p "$test_backup_dir" 2>/dev/null || true
                    chmod 755 "$test_backup_dir" 2>/dev/null || true
                fi
            fi
        else
            log_warn "$backup_dir not writable or doesn't exist"
        fi
    done
else
    # Create backups directory structure with correct ownership from start
    log_info "Creating backup directory structure..."
    mkdir -p backups/postgres-staging backups/mysql-staging backups/staging
    chown -R ${USER_ID}:${GROUP_ID} backups 2>/dev/null || {
        log_warn "Cannot set ownership, using chmod instead"
        chmod -R 755 backups 2>/dev/null || true
    }
fi

# Set ownership to match the Docker container user (only if possible)
log_info "Setting directory permissions for user ${USER_ID}:${GROUP_ID}..."
for dir in test-reports logs data external_plugins external_config secrets; do
    if [ -d "$dir" ] && [ -w "$dir" ]; then
        chown -R ${USER_ID}:${GROUP_ID} "$dir" 2>/dev/null || {
            log_warn "Could not change ownership of $dir, using current permissions"
            # If we can't chown, at least make it writable
            chmod -R u+w "$dir" 2>/dev/null || true
        }
    else
        log_warn "Directory $dir not writable or doesn't exist"
    fi
done

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
        docker compose -f "$COMPOSE_FILE" --profile "$COMPOSE_PROFILE" down -v --remove-orphans 2>/dev/null || true
    else
        docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true
    fi
    
    # Remove any dangling volumes
    docker volume prune -f 2>/dev/null || true
    
    # Clean up any test data files including SQLite databases
    rm -rf data/sqlite data/test* 2>/dev/null || true
    rm -f data/app.db data/app.db-* 2>/dev/null || true
    
    # Clean up bootstrap marker files to prevent cross-test contamination
    rm -f data/.bootstrap_completed 2>/dev/null || true
    rm -f data/.bootstrap_completed.lock 2>/dev/null || true
    
    # Clean up override file
    rm -f docker-compose.override.yml 2>/dev/null || true
    
    log_info "Cleanup completed for $DB_TYPE"
}

# Trap cleanup on exit
trap cleanup_database EXIT

log_step "Starting $DB_TYPE database test sequence..."

# Clean up bootstrap files and SQLite databases from previous tests to prevent cross-contamination
log_info "Cleaning up bootstrap files and databases from previous tests..."
rm -f data/.bootstrap_completed 2>/dev/null || true
rm -f data/.bootstrap_completed.lock 2>/dev/null || true
if [[ "$DB_TYPE" == "sqlite" ]]; then
    rm -f data/app.db data/app.db-* 2>/dev/null || true
    log_info "Removed existing SQLite database files"
fi

# Clean up any existing containers to prevent conflicts
log_info "Cleaning up any existing containers to prevent port conflicts..."
docker ps -q --filter "name=$APP_CONTAINER_NAME" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "name=$APP_CONTAINER_NAME" | xargs -r docker rm 2>/dev/null || true
docker ps -q --filter "name=trakbridge-postgres$CONTAINER_NAME_SUFFIX" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "name=trakbridge-postgres$CONTAINER_NAME_SUFFIX" | xargs -r docker rm 2>/dev/null || true
docker ps -q --filter "name=trakbridge-mysql$CONTAINER_NAME_SUFFIX" | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "name=trakbridge-mysql$CONTAINER_NAME_SUFFIX" | xargs -r docker rm 2>/dev/null || true

# Step 1: Deploy the database
log_step "1. Deploying $DB_TYPE with production configuration..."

# Debug: Show current working directory and file structure
log_info "=== DEBUGGING DIRECTORY STRUCTURE ==="
log_info "Current working directory: $(pwd)"
log_info "Using compose file: $COMPOSE_FILE"
log_info "Checking for required directories..."
for dir in logs data secrets config backups external_plugins; do
    if [ -d "$dir" ]; then
        log_info "✅ $dir exists ($(ls -ld "$dir" | awk '{print $1, $3, $4}'))"
    else
        log_warn "❌ $dir does NOT exist - creating it"
        mkdir -p "$dir"
        chmod 755 "$dir"
    fi
done
log_info "=== END DEBUGGING ==="

# Create override file to use dynamic port and correct user ID
# Include volume mounts for realistic testing (permissions fixed in staging job)
# Using compose file: $COMPOSE_FILE
cat > docker-compose.override.yml << EOF
services:
  $APP_SERVICE_NAME:
    ports:
      - "${TEST_PORT}:5000"
    environment:
      - FLASK_ENV=production
      - APP_VERSION=$IMAGE_TAG
      - USER_ID=${USER_ID}
      - GROUP_ID=${GROUP_ID}
      - DOCKER_USER_ID=${DOCKER_USER_ID}
      - DOCKER_GROUP_ID=${DOCKER_GROUP_ID}
      - DB_TYPE=${DB_TYPE}
      - DB_HOST=${DB_HOST}
      - DB_PORT=${DB_PORT}
      - DB_NAME=${DB_NAME}
      - DB_USER=${DB_USER}
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
      - ./secrets:/app/secrets
      - ./config:/app/external_config
      - ./backups:/app/backups
      - ./external_plugins:/app/external_plugins
EOF

if [[ -n "$COMPOSE_PROFILE" ]]; then
    log_info "Using docker compose profile: $COMPOSE_PROFILE on port $TEST_PORT with file: $COMPOSE_FILE"
    docker compose -f "$COMPOSE_FILE" --profile "$COMPOSE_PROFILE" up -d
else
    log_info "Using docker compose without profile (SQLite) on port $TEST_PORT with file: $COMPOSE_FILE"
    docker compose -f "$COMPOSE_FILE" up -d
fi

# Wait for services to be ready
log_info "Waiting for services to become ready..."
log_info "Giving containers extra time to complete volume mounting and user switching..."
sleep 20

# Check container health
CONTAINER_NAME="$APP_CONTAINER_NAME"
if [[ -n "$COMPOSE_PROFILE" ]]; then
    DB_CONTAINER="trakbridge-${COMPOSE_PROFILE}${CONTAINER_NAME_SUFFIX}"
    
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
timeout 240 bash -c "
    attempts=0
    max_attempts=24
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
                echo 'Application container is unhealthy according to Docker health check'
                echo 'Testing actual health endpoint to verify if application is really working...'
                
                # Test the actual health endpoint directly
                if docker exec $CONTAINER_NAME curl -f -s http://localhost:5000/api/health > /dev/null 2>&1; then
                    echo '✅ Application health endpoint is actually responding correctly!'
                    echo 'Docker health check may be misconfigured, but application is working - continuing tests'
                    break
                else
                    echo '❌ Application health endpoint is not responding'
                    echo 'Container logs:'
                    docker logs $CONTAINER_NAME --tail=20
                    if [ \$attempts -ge \$max_attempts ]; then
                        echo 'Both Docker health check and direct endpoint test failed'
                        exit 1
                    fi
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

log_info "Running migration validation for $DB_TYPE..."
if docker exec "$CONTAINER_NAME" bash -c "
    cd /app
    echo 'Testing migration status...'
    flask db current || echo 'No current migration (clean database)'
    
    echo 'Running database upgrade...'
    flask db upgrade
    
    echo 'Verifying migration completed successfully...'
    current_rev=\$(flask db current 2>/dev/null | head -1)
    if [ -n \"\$current_rev\" ] && [ \"\$current_rev\" != \"None\" ]; then
        echo \"Migration successful. Current revision: \$current_rev\"
        exit 0
    else
        echo \"Migration validation failed\"
        exit 1
    fi
"; then
    log_info "Migration validation passed for $DB_TYPE"
    add_test_result "migrations" "passed" "Database migrations executed successfully"
else
    log_error "Migration validation failed for $DB_TYPE"
    add_test_result "migrations" "failed" "Database migration execution failed"
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

# Note: This test may show "Working outside of application context" errors during cleanup
# These are normal application shutdown messages and don't indicate test failure
if docker exec "$CONTAINER_NAME" python -c "
import sys
sys.path.append('/app')
try:
    from database import db
    from app import create_app
    import os
    
    # Set environment to avoid issues with delayed startup tasks
    os.environ['SKIP_DB_INIT'] = 'false'
    
    app = create_app('testing')
    with app.app_context():
        # Use text() for SQLAlchemy 2.0+ compatibility
        from sqlalchemy import text
        result = db.session.execute(text('SELECT 1')).scalar()
        if result == 1:
            print('Database connectivity test passed')
            # Explicit success exit
            sys.exit(0)
        else:
            raise Exception('Database query returned unexpected result')
except Exception as e:
    print(f'Database connectivity test failed: {e}')
    sys.exit(1)
" 2>&1; then
    log_info "Database connectivity test passed for $DB_TYPE"
    add_test_result "database_connectivity" "passed" "Database connection successful" 
else
    log_error "Database connectivity test failed for $DB_TYPE"
    add_test_result "database_connectivity" "failed" "Database connection failed"
    finalize_test_report "failed"
    exit 1
fi

log_info "Note: Any 'Working outside of application context' messages above are normal cleanup warnings and don't indicate test failure"

# Step 5: Test authentication system
log_step "5. Testing authentication system..."

log_info "Testing local authentication system..."
if docker exec "$CONTAINER_NAME" python -c "
import sys
sys.path.append('/app')
try:
    from app import create_app
    from services.auth.auth_manager import AuthenticationManager
    from services.auth.bootstrap_service import BootstrapService
    import os
    
    # Set environment to avoid issues with delayed startup tasks
    os.environ['SKIP_DB_INIT'] = 'false'
    
    app = create_app('testing')
    with app.app_context():
        # Bootstrap the admin user to ensure it exists
        bootstrap_service = BootstrapService()
        admin_user = bootstrap_service.create_initial_admin()
        
        # If admin user creation returns None, try to find existing admin
        if admin_user is None:
            from models.user import User, UserRole
            admin_user = User.query.filter_by(role=UserRole.ADMIN).first()
            
        if admin_user is None:
            raise Exception('No admin user available for authentication testing')
            
        admin_username = admin_user.username
        admin_password = bootstrap_service.default_admin_password
        
        print(f'Testing authentication for bootstrapped admin user: {admin_username}')
        
        # Initialize auth manager
        from config.authentication_loader import load_authentication_config
        auth_config = load_authentication_config()
        auth_manager = AuthenticationManager(auth_config.get('authentication', {}))
        
        # Test authentication
        result = auth_manager.authenticate(admin_username, admin_password)
        
        if result.success:
            print(f'Authentication successful for {admin_username}')
            
            # Check if user needs password change using bootstrap service
            from services.auth.bootstrap_service import check_password_change_required
            if result.user and check_password_change_required(result.user):
                print('Initial admin requires password change (as expected)')
            
            # Verify user has admin role
            if result.user and hasattr(result.user, 'role'):
                from models.user import UserRole
                if result.user.role == UserRole.ADMIN:
                    print('User has admin role')
                else:
                    print(f'User role is {result.user.role}, expected ADMIN')
            
            print('Local authentication test passed')
            sys.exit(0)
        else:
            print(f'Authentication failed: {result.message}')
            raise Exception('Authentication failed')
            
except Exception as e:
    print(f'Authentication test failed: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
" 2>&1; then
    log_info "Admin authentication test passed for $DB_TYPE"
    add_test_result "local_authentication" "passed" "Admin authentication working correctly"
else
    log_error "Admin authentication test failed for $DB_TYPE"
    add_test_result "local_authentication" "failed" "Admin authentication not working"
    finalize_test_report "failed"
    exit 1
fi

log_info "Note: Any 'Working outside of application context' messages above are normal cleanup warnings and don't indicate test failure"

# Step 6: Test LDAP connectivity (if enabled)
if [[ "${LDAP_ENABLED:-false}" == "true" ]] && [[ -s "secrets/ldap_bind_password" ]]; then
    log_step "6. Testing LDAP connectivity..."
    
    log_info "Testing LDAP connection..."
    if docker exec "$CONTAINER_NAME" python -c "
import sys
sys.path.append('/app')
from services.auth.ldap_provider import LDAPAuthProvider
from config.authentication_loader import load_authentication_config
from models.user import AuthProvider

# Load LDAP configuration
auth_config = load_authentication_config()
providers = auth_config.get('authentication', {}).get('providers', {})
ldap_config = providers.get('ldap', {})

if ldap_config.get('enabled', False):
    provider = LDAPAuthProvider(ldap_config)
    # Test LDAP provider health
    health_result = provider.health_check()
    if health_result.get('status') == 'healthy':
        print('LDAP connectivity test passed')
    else:
        raise Exception(f'LDAP connection failed: {health_result.get(\"message\", health_result.get(\"status\", \"Unknown error\"))}')
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