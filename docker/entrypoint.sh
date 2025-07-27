#!/bin/bash
# =============================================================================
# Docker Entrypoint Script for TrakBridge with Hypercorn Support
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_debug() {
    if [[ "${DEBUG:-false}" == "true" ]]; then
        echo -e "${BLUE}[DEBUG]${NC} $1" >&2
    fi
}

# Default environment variables
export FLASK_ENV=${FLASK_ENV:-production}
export FLASK_APP=${FLASK_APP:-app.py}
export DB_TYPE=${DB_TYPE:-sqlite}
export LOG_LEVEL=${LOG_LEVEL:-INFO}

# Ensure we're in the correct directory
cd /app

log_info "Starting TrakBridge from $(pwd)"
log_info "Environment: $FLASK_ENV"
log_info "Database Type: $DB_TYPE"
log_info "Log Level: $LOG_LEVEL"
log_info "Running as UID: $(id -u), GID: $(id -g)"
log_info "User: $(whoami), Home: $HOME"

# Function to handle secrets permissions
handle_secrets() {
    log_info "Handling secrets permissions..."

    local secrets_dir="/app/secrets"
    local current_uid=$(id -u)
    local current_gid=$(id -g)

    if [[ -d "$secrets_dir" ]]; then
        log_info "Secrets directory found, checking permissions..."

        # Check if we can access the secrets directory
        if [[ ! -r "$secrets_dir" ]]; then
            log_error "Cannot read secrets directory: $secrets_dir"
            return 1
        fi

        # Process each secret file
        for secret_file in "$secrets_dir"/*; do
            if [[ -f "$secret_file" ]]; then
                local filename=$(basename "$secret_file")
                log_debug "Processing secret file: $filename"

                # Check if we can read the file
                if [[ ! -r "$secret_file" ]]; then
                    log_warn "Cannot read secret file: $secret_file"

                    # Try to fix permissions (this will work if we're root or if the file is group-writable)
                    if chmod 640 "$secret_file" 2>/dev/null; then
                        log_info "Fixed permissions for $filename"
                    else
                        log_error "Cannot fix permissions for $filename"
                        log_error "Please ensure the secret file is readable by UID $current_uid or GID $current_gid"
                        return 1
                    fi
                fi

                # Test that we can actually read the file content
                if ! cat "$secret_file" >/dev/null 2>&1; then
                    log_error "Cannot read content of secret file: $secret_file"
                    return 1
                fi

                log_debug "Secret file $filename is readable"
            fi
        done

        log_info "All secret files are accessible"
    else
        log_debug "No secrets directory found at $secrets_dir"
    fi

    return 0
}

# Function to ensure directory permissions
ensure_permissions() {
    log_info "Ensuring proper permissions for application directories..."

    # Create directories if they don't exist
    mkdir -p /app/logs /app/data /app/tmp

    # Get current user info
    local current_uid=$(id -u)
    local current_gid=$(id -g)

    log_debug "Checking permissions as UID:$current_uid GID:$current_gid"

    # Function to check and fix directory permissions
    check_and_fix_dir() {
        local dir="$1"
        local dir_name="$2"

        if [[ -w "$dir" ]]; then
            log_debug "$dir_name directory is writable"
        else
            log_warn "$dir_name directory is not writable"
            
            # In the new security model, permissions should be handled by docker-entrypoint.sh
            # We can only fix what we have permission to fix
            if chmod 755 "$dir" 2>/dev/null; then
                log_info "Fixed $dir_name directory permissions"
            else
                log_warn "Cannot fix $dir_name directory permissions"
                log_warn "This should have been handled by the Docker entrypoint script"
                log_warn "If using dynamic UID/GID, ensure USER_ID and GROUP_ID are set correctly"
            fi
        fi

        # Ensure we can create files in the directory
        local test_file="$dir/.write_test_$(date +%s)"
        if touch "$test_file" 2>/dev/null; then
            rm -f "$test_file" 2>/dev/null
            log_debug "$dir_name directory write test passed"
        else
            log_error "$dir_name directory write test failed"
            log_error "Application may not function correctly without write access to $dir"
            log_error "Check Docker volume mount permissions and USER_ID/GROUP_ID settings"
        fi
    }

    # Check each directory
    check_and_fix_dir "/app/logs" "Logs"
    check_and_fix_dir "/app/data" "Data"
    check_and_fix_dir "/app/tmp" "Tmp"
}

# Function to wait for database
wait_for_database() {
    local db_type="$1"
    local host="$2"
    local port="$3"
    local max_attempts=30
    local attempt=1

    if [[ "$db_type" == "sqlite" ]]; then
        log_info "Using SQLite database - no wait required"
        return 0
    fi

    log_info "Waiting for $db_type database at $host:$port..."

    while [[ $attempt -le $max_attempts ]]; do
        case "$db_type" in
            "postgresql")
                if pg_isready -h "$host" -p "$port" -U "${DB_USER:-postgres}" -d "${DB_NAME:-trakbridge_db}" >/dev/null 2>&1; then
                    log_info "PostgreSQL is ready!"
                    return 0
                fi
                ;;
            "mysql")
                if mysqladmin ping -h "$host" -P "$port" --silent >/dev/null 2>&1; then
                    log_info "MySQL is ready!"
                    return 0
                fi
                ;;
        esac

        log_debug "Database not ready, attempt $attempt/$max_attempts"
        sleep 2
        ((attempt++))
    done

    log_error "Database failed to become ready after $max_attempts attempts"
    return 1
}

# Function to run database migrations
run_migrations() {
    log_info "Checking database initialization..."

    if command -v flask >/dev/null 2>&1; then
        # Check if Flask-Migrate is configured
        if flask db current >/dev/null 2>&1; then
            log_info "Flask-Migrate is configured"

            # Get current revision
            current_rev=$(flask db current 2>/dev/null || echo "")

            if [[ -z "$current_rev" ]] || [[ "$current_rev" == *"None"* ]]; then
                log_info "No current migration revision found"

                # Check if database file exists (for SQLite)
                if [[ "$DB_TYPE" == "sqlite" ]]; then
                    db_path="${SQLALCHEMY_DATABASE_URI#sqlite:///}"
                    if [[ -f "$db_path" ]]; then
                        log_info "Database file exists, stamping with current revision"
                        flask db stamp head || log_warn "Could not stamp database"
                    else
                        log_info "New database - will be handled by application"
                    fi
                else
                    log_info "Database initialization will be handled by application"
                fi
            else
                log_info "Current migration revision: $current_rev"
                
                # Check if there are pending migrations before running upgrade
                if flask db heads >/dev/null 2>&1; then
                    head_rev=$(flask db heads 2>/dev/null | head -n1 | awk '{print $1}')
                    if [[ -n "$head_rev" ]] && [[ "$current_rev" != "$head_rev" ]]; then
                        log_info "Pending migrations found (head: $head_rev), running upgrade..."
                        flask db upgrade || {
                            log_warn "Migration failed, will retry in application"
                        }
                    else
                        log_info "Database is up to date, no migrations needed"
                    fi
                else
                    log_info "Could not check migration heads, skipping migrations"
                fi
            fi
        else
            log_info "Flask-Migrate not configured - database initialization handled by application"
        fi
    else
        log_warn "Flask CLI not available - database initialization handled by application"
    fi
}

# Function to validate configuration
validate_config() {
    log_info "Validating configuration..."

    # Ensure we're in the app directory
    cd /app

    # Debug: Show current directory and Python path
    log_debug "Current directory: $(pwd)"
    log_debug "Python path: $PYTHONPATH"
    log_debug "Contents of /app: $(ls -la /app)"

    # Check if app.py exists
    if [[ ! -f "/app/app.py" ]]; then
        log_error "app.py not found in /app directory"
        return 1
    fi

    # Set PYTHONPATH to include current directory
    export PYTHONPATH="/app:${PYTHONPATH:-}"

    # Test import with more detailed error reporting
    log_info "Testing Flask application import..."
    if python -c "
import sys
sys.path.insert(0, '/app')
try:
    # Test that we can import the module without initializing
    import importlib.util
    spec = importlib.util.spec_from_file_location('app', '/app/app.py')
    app_module = importlib.util.module_from_spec(spec)
    print('Application module can be loaded')
except Exception as e:
    print(f'Import error: {e}')
    sys.exit(1)
" 2>&1; then
        log_info "Flask application import successful"
    else
        log_error "Failed to import Flask application"
        log_error "Attempting to diagnose the issue..."

        # Additional debugging
        python -c "
import sys
print('Python version:', sys.version)
print('Python path:', sys.path)
import os
print('Environment variables:')
for key in ['FLASK_APP', 'FLASK_ENV', 'PYTHONPATH']:
    print(f'  {key}: {os.environ.get(key, \"Not set\")}')
"
        return 1
    fi

    # Validate database connection for non-SQLite databases
    if [[ "$DB_TYPE" != "sqlite" ]]; then
        if [[ -z "$DB_HOST" ]]; then
            log_error "DB_HOST is required for $DB_TYPE database"
            return 1
        fi

        if [[ -z "$DB_USER" ]]; then
            log_error "DB_USER is required for $DB_TYPE database"
            return 1
        fi
    fi

    # Check for required secrets in production
    if [[ "$FLASK_ENV" == "production" ]]; then
        if [[ -z "$SECRET_KEY" ]] && [[ ! -f "/app/secrets/secret_key" ]]; then
            log_error "SECRET_KEY is required in production environment"
            return 1
        fi

        if [[ "$DB_TYPE" != "sqlite" ]] && [[ ! -f "/app/secrets/db_password" ]] && [[ -z "$DB_PASSWORD" ]]; then
            log_error "Database password is required for $DB_TYPE in production"
            return 1
        fi

        if [[ -z "$TB_MASTER_KEY" ]] && [[ ! -f "/app/secrets/tb_master_key" ]]; then
            log_error "Master Key is required in production"
            return 1
        fi
    fi

    log_info "Configuration validation passed"
    return 0
}

# Function to setup logging
setup_logging() {
    log_info "Setting up logging..."

    # Ensure log directory exists and is writable
    mkdir -p /app/logs

    # Create log files if they don't exist
    #touch /app/logs/app.log 2>/dev/null || log_warn "Cannot create app.log"
    #touch /app/logs/error.log 2>/dev/null || log_warn "Cannot create error.log"
    touch /app/logs/hypercorn-access.log 2>/dev/null || log_warn "Cannot create hypercorn-access.log"
    touch /app/logs/hypercorn-error.log 2>/dev/null || log_warn "Cannot create hypercorn-error.log"

    # Set appropriate permissions if possible
    chmod 644 /app/logs/*.log 2>/dev/null || log_debug "Could not set log file permissions"
}

# Function to handle shutdown signals
cleanup() {
    log_info "Received shutdown signal, cleaning up..."

    # Kill any background processes
    jobs -p | xargs -r kill

    log_info "Cleanup completed"
    exit 0
}

# Setup External Plugins
setup_plugins(){
    log_info "Setting up External Plugins..."

    # Ensure plugins directory exists and is writable
    mkdir -p /app/external_plugins
    mkdir -p /app/external_config

    # Create required files
    touch /app/external_plugins/__init__.py 2>/dev/null || log_warn "Cannot create module init in external_plugins"
    touch /app/external_config/__init__.py 2>/dev/null || log_warn "Cannot create module init in external_config"

    # Set appropriate permissions if possible
    chmod 644 /app/external_plugins/*.py 2>/dev/null || log_debug "Could not set plugins file permissions"
    chmod 644 /app/external_config/*.yaml 2>/dev/null || log_debug "Could not set pluing config file permissions"
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Function to start the appropriate server (replaces eval-based approach)
start_server() {
    # Ensure we're in the correct directory
    cd /app
    
    case "$FLASK_ENV" in
        "development")
            log_info "Using Flask development server"
            exec python -m flask run --host=0.0.0.0 --port=5000 --debug
            ;;
        "production"|"staging")
            # Check if hypercorn.toml exists
            if [[ -f "/app/hypercorn.toml" ]]; then
                log_info "Using Hypercorn production server with config file"
                exec hypercorn --config /app/hypercorn.toml app:app
            else
                log_info "Using Hypercorn production server with inline configuration"
                # Sanitize and validate environment variables
                local workers=${HYPERCORN_WORKERS:-4}
                local worker_class=${HYPERCORN_WORKER_CLASS:-asyncio}
                local bind=${HYPERCORN_BIND:-0.0.0.0:5000}
                local keep_alive=${HYPERCORN_KEEP_ALIVE:-5}
                local max_requests=${HYPERCORN_MAX_REQUESTS:-1000}
                local max_requests_jitter=${HYPERCORN_MAX_REQUESTS_JITTER:-100}
                local log_level=${HYPERCORN_LOG_LEVEL:-info}

                # Validate numeric values to prevent injection
                if ! [[ "$workers" =~ ^[0-9]+$ ]] || [[ "$workers" -lt 1 ]] || [[ "$workers" -gt 16 ]]; then
                    log_warn "Invalid HYPERCORN_WORKERS value '$workers', using default: 4"
                    workers=4
                fi
                
                if ! [[ "$keep_alive" =~ ^[0-9]+$ ]] || [[ "$keep_alive" -lt 1 ]] || [[ "$keep_alive" -gt 300 ]]; then
                    log_warn "Invalid HYPERCORN_KEEP_ALIVE value '$keep_alive', using default: 5"
                    keep_alive=5
                fi
                
                if ! [[ "$max_requests" =~ ^[0-9]+$ ]] || [[ "$max_requests" -lt 100 ]] || [[ "$max_requests" -gt 10000 ]]; then
                    log_warn "Invalid HYPERCORN_MAX_REQUESTS value '$max_requests', using default: 1000"
                    max_requests=1000
                fi
                
                # Validate worker class
                case "$worker_class" in
                    "asyncio"|"trio"|"uvloop") ;;
                    *) 
                        log_warn "Invalid HYPERCORN_WORKER_CLASS value '$worker_class', using default: asyncio"
                        worker_class="asyncio"
                        ;;
                esac
                
                # Validate log level
                case "$log_level" in
                    "critical"|"error"|"warning"|"info"|"debug") ;;
                    *)
                        log_warn "Invalid HYPERCORN_LOG_LEVEL value '$log_level', using default: info"
                        log_level="info"
                        ;;
                esac
                
                # Validate bind address (basic validation)
                if ! [[ "$bind" =~ ^[0-9a-zA-Z\.:_-]+$ ]]; then
                    log_warn "Invalid HYPERCORN_BIND value '$bind', using default: 0.0.0.0:5000"
                    bind="0.0.0.0:5000"
                fi

                log_info "Starting Hypercorn with: workers=$workers, bind=$bind, worker-class=$worker_class"
                exec hypercorn \
                    --bind "$bind" \
                    --workers "$workers" \
                    --worker-class "$worker_class" \
                    --keep-alive "$keep_alive" \
                    --max-requests "$max_requests" \
                    --max-requests-jitter "$max_requests_jitter" \
                    --log-level "$log_level" \
                    --access-logfile /app/logs/hypercorn-access.log \
                    --error-logfile /app/logs/hypercorn-error.log \
                    app:app
            fi
            ;;
        *)
            # Default to production settings with Hypercorn
            log_info "Unknown environment '$FLASK_ENV', defaulting to Hypercorn"
            if [[ -f "/app/hypercorn.toml" ]]; then
                exec hypercorn --config /app/hypercorn.toml app:app
            else
                exec hypercorn --bind 0.0.0.0:5000 --workers 4 --worker-class asyncio app:app
            fi
            ;;
    esac
}

# Function to check if Hypercorn is available
check_hypercorn() {
    if ! command -v hypercorn >/dev/null 2>&1; then
        log_error "Hypercorn is not installed but required for production environment"
        log_error "Installing Hypercorn..."
        pip install hypercorn || {
            log_error "Failed to install Hypercorn"
            return 1
        }
    fi
    log_info "Hypercorn is available"
    return 0
}

# Main execution
main() {
    log_info "=== TrakBridge Startup ==="

    # Ensure we're in the correct directory
    cd /app

    # Ensure proper permissions
    ensure_permissions

    # Handle secrets permissions
    if ! handle_secrets; then
        log_error "Failed to handle secrets permissions"
        exit 1
    fi

    # Setup logging
    setup_logging

    # Setup External Plugins
    setup_plugins

    # Validate configuration
    if ! validate_config; then
        log_error "Configuration validation failed"
        exit 1
    fi

    # Check for Hypercorn in production/staging environments
    if [[ "$FLASK_ENV" == "production" ]] || [[ "$FLASK_ENV" == "staging" ]]; then
        if ! check_hypercorn; then
            log_error "Hypercorn check failed"
            exit 1
        fi
    fi

    # Wait for database if needed
    if [[ "$DB_TYPE" != "sqlite" ]]; then
        if ! wait_for_database "$DB_TYPE" "${DB_HOST:-localhost}" "${DB_PORT:-5432}"; then
            log_error "Database connection failed"
            exit 1
        fi
    fi

    # Run migrations
    if [[ "${RUN_MIGRATIONS:-true}" == "true" ]]; then
        run_migrations
    fi

    log_info "=== Starting Application ==="

    # Execute the provided command or start the appropriate server
    if [[ $# -eq 0 ]]; then
        # No command provided, start the appropriate server for the environment
        start_server
    else
        # Command provided, execute it
        exec "$@"
    fi
}

# Handle special commands
case "${1:-}" in
    "bash"|"sh")
        log_info "Starting interactive shell"
        exec "$@"
        ;;
    "python")
        log_info "Starting Python with args: ${*:2}"
        cd /app
        exec "$@"
        ;;
    "flask")
        log_info "Starting Flask command: ${*:2}"
        cd /app
        exec "$@"
        ;;
    "hypercorn")
        log_info "Starting Hypercorn with args: ${*:2}"
        main # Run setup first
        cd /app
        exec "$@"
        ;;
    "test")
        log_info "Running tests"
        export FLASK_ENV=testing
        cd /app
        exec python -m pytest "${@:2}"
        ;;
    "migrate")
        log_info "Running database migrations only"
        cd /app
        ensure_permissions
        handle_secrets
        setup_logging
        validate_config
        if [[ "$DB_TYPE" != "sqlite" ]]; then
            wait_for_database "$DB_TYPE" "${DB_HOST:-localhost}" "${DB_PORT:-5432}"
        fi
        run_migrations
        exit 0
        ;;
    "config-check")
        log_info "Checking configuration"
        cd /app
        validate_config
        python -c "
import sys
sys.path.insert(0, '/app')
from app import app
print('Flask app loaded successfully')
print(f'Environment: {app.config.get(\"FLASK_ENV\", \"unknown\")}')
print(f'Debug mode: {app.config.get(\"DEBUG\", False)}')
db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', 'not set')
print(f'Database URI: {db_uri[:50] if len(db_uri) > 50 else db_uri}...')
"
        exit 0
        ;;
    "")
        # No command provided - run main startup sequence
        main
        ;;
    *)
        # Custom command provided - run main startup then execute command
        main "$@"
        ;;
esac