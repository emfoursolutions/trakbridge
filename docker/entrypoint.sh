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
    log_info "Running database migrations..."

    if command -v flask >/dev/null 2>&1; then
        if flask db current >/dev/null 2>&1; then
            log_info "Running Flask-Migrate migrations"
            flask db upgrade
        else
            log_warn "Flask-Migrate not configured, skipping migrations"
        fi
    else
        log_warn "Flask CLI not available, skipping migrations"
    fi
}

# Function to create necessary directories
create_directories() {
    log_info "Creating necessary directories..."

    mkdir -p /app/logs
    mkdir -p /app/data
    mkdir -p /app/tmp

    # Ensure proper permissions
    chmod 755 /app/logs /app/data /app/tmp
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
import os
sys.path.insert(0, '/app')
os.chdir('/app')
try:
    from app import app
    print('Application loaded successfully')
    print(f'App name: {app.name}')
    print(f'App config keys: {list(app.config.keys())[:5]}...')
except ImportError as e:
    print(f'Import error: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
except Exception as e:
    print(f'Other error: {e}')
    import traceback
    traceback.print_exc()
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
print('Current working directory:', sys.getcwd())
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
        if [[ -z "$SECRET_KEY" ]] && [[ ! -f "/run/secrets/secret_key" ]]; then
            log_error "SECRET_KEY is required in production environment"
            return 1
        fi

        if [[ "$DB_TYPE" != "sqlite" ]] && [[ ! -f "/run/secrets/db_password" ]] && [[ -z "$DB_PASSWORD" ]]; then
            log_error "Database password is required for $DB_TYPE in production"
            return 1
        fi

        if [[ -z "$TB_MASTER_KEY" ]] && [[ ! -f "/run/secrets/tb_master_key" ]]; then
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

    # Ensure log directory exists
    mkdir -p /app/logs

    # Create log files if they don't exist
    touch /app/logs/app.log
    touch /app/logs/error.log
    touch /app/logs/hypercorn-access.log
    touch /app/logs/hypercorn-error.log

    # Set appropriate permissions
    chmod 644 /app/logs/*.log
}

# Function to handle shutdown signals
cleanup() {
    log_info "Received shutdown signal, cleaning up..."

    # Kill any background processes
    jobs -p | xargs -r kill

    log_info "Cleanup completed"
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Function to determine the appropriate server command
get_server_command() {
    case "$FLASK_ENV" in
        "development")
            log_info "Using Flask development server"
            echo "python -m flask run --host=0.0.0.0 --port=5000 --debug"
            ;;
        "production"|"staging")
            # Check if hypercorn.toml exists
            if [[ -f "/app/hypercorn.toml" ]]; then
                log_info "Using Hypercorn production server with config file"
                echo "cd /app && hypercorn --config /app/hypercorn.toml app:app"
            else
                log_info "Using Hypercorn production server with inline configuration"
                # Inline hypercorn configuration as fallback
                local workers=${HYPERCORN_WORKERS:-4}
                local worker_class=${HYPERCORN_WORKER_CLASS:-asyncio}
                local bind=${HYPERCORN_BIND:-0.0.0.0:5000}
                local keep_alive=${HYPERCORN_KEEP_ALIVE:-5}
                local max_requests=${HYPERCORN_MAX_REQUESTS:-1000}
                local max_requests_jitter=${HYPERCORN_MAX_REQUESTS_JITTER:-100}
                local log_level=${HYPERCORN_LOG_LEVEL:-info}

                echo "cd /app && hypercorn --bind $bind --workers $workers --worker-class $worker_class --keep-alive $keep_alive --max-requests $max_requests --max-requests-jitter $max_requests_jitter --log-level $log_level --access-logfile /app/logs/hypercorn-access.log --error-logfile /app/logs/hypercorn-error.log app:app"
            fi
            ;;
        *)
            # Default to production settings with Hypercorn
            log_info "Unknown environment '$FLASK_ENV', defaulting to Hypercorn"
            if [[ -f "/app/hypercorn.toml" ]]; then
                echo "cd /app && hypercorn --config /app/hypercorn.toml app:app"
            else
                echo "cd /app && hypercorn --bind 0.0.0.0:5000 --workers 4 --worker-class asyncio app:app"
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

    # Create necessary directories
    create_directories

    # Setup logging
    setup_logging

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

    # Execute the provided command or determine the appropriate server
    if [[ $# -eq 0 ]]; then
        # No command provided, use the appropriate server for the environment
        server_cmd=$(get_server_command)
        log_info "Starting server: $server_cmd"
        eval $server_cmd
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
        create_directories
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