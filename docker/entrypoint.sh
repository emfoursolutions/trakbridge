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

# Function to handle user switching and security
handle_user_switching() {
    log_info "Handling user switching and security..."
    
    # Get target UID/GID from environment or current user
    local TARGET_UID=${USER_ID:-$(id -u)}
    local TARGET_GID=${GROUP_ID:-$(id -g)}
    local CURRENT_UID=$(id -u)
    
    log_debug "USER_ID environment variable: ${USER_ID:-not set}"
    log_debug "GROUP_ID environment variable: ${GROUP_ID:-not set}"
    log_debug "TARGET_UID (resolved): $TARGET_UID"
    log_debug "TARGET_GID (resolved): $TARGET_GID"
    log_debug "CURRENT_UID: $CURRENT_UID"
    log_debug "Current user: $(whoami)"
    
    # Security check: prevent running as root unless explicitly needed
    if [[ $CURRENT_UID -eq 0 ]]; then
        # We are running as root - handle user switching securely
        if [[ $TARGET_UID -eq 0 ]] && [[ "${ALLOW_ROOT:-false}" != "true" ]]; then
            log_error "Running as root is not allowed for security reasons."
            log_error "Set ALLOW_ROOT=true environment variable to override this protection."
            log_error "For production deployments, consider using USER_ID and GROUP_ID instead."
            exit 1
        fi
        
        # Create or modify user if dynamic UID/GID is requested
        if [[ $TARGET_UID -ne 1000 ]] || [[ $TARGET_GID -ne 1000 ]]; then
            log_info "Creating dynamic user with UID:$TARGET_UID GID:$TARGET_GID for host compatibility"
            
            # Create group if it doesn't exist
            if ! getent group $TARGET_GID > /dev/null 2>&1; then
                groupadd -g $TARGET_GID appuser-dynamic
            fi
            
            # Create user if it doesn't exist  
            if ! getent passwd $TARGET_UID > /dev/null 2>&1; then
                useradd -r -u $TARGET_UID -g $TARGET_GID -d /app -s /bin/bash appuser-dynamic
                # Add dynamic user to appuser group for inherited permissions
                usermod -a -G appuser appuser-dynamic 2>/dev/null || log_debug "Could not add dynamic user to appuser group"
            else
                # If user exists, ensure it's added to appuser group
                local existing_user=$(getent passwd $TARGET_UID | cut -d: -f1)
                usermod -a -G appuser "$existing_user" 2>/dev/null || log_debug "Could not add existing user to appuser group"
            fi
            
            # Fix ownership of app directories for dynamic user
            # Only chown directories that are writable (not read-only mounted)
            log_debug "Fixing ownership for writable directories..."
            
            # Always fix these writable directories (including external directories for volume mounts)
            chown -R $TARGET_UID:$TARGET_GID /app/logs /app/data /app/tmp /app/external_plugins /app/external_config
            
            # Check each application code directory for writability before chown
            local app_dirs=("/app/utils" "/app/plugins" "/app/services" "/app/models" "/app/routes" "/app/config")
            for dir in "${app_dirs[@]}"; do
                if [[ -d "$dir" ]]; then
                    if [[ -w "$dir" ]]; then
                        log_debug "Changing ownership of writable directory: $dir"
                        if chown -R $TARGET_UID:$TARGET_GID "$dir" 2>/dev/null; then
                            log_debug "Successfully changed ownership of $dir"
                        else
                            log_debug "Failed to chown $dir, trying fallback permission strategy"
                            # Fallback: ensure group-readable permissions
                            chmod -R g+r "$dir" 2>/dev/null || log_debug "Could not set group read permissions on $dir"
                            find "$dir" -type d -exec chmod g+rx {} \; 2>/dev/null || log_debug "Could not set directory execute permissions"
                        fi
                    else
                        log_debug "Skipping read-only directory: $dir"
                        # For read-only directories, verify they're readable by group
                        if [[ ! -r "$dir" ]]; then
                            log_warn "Read-only directory $dir is not readable by current user"
                            # Try to make readable via group permissions if possible
                            chmod g+r "$dir" 2>/dev/null || log_debug "Could not improve read permissions on $dir"
                        fi
                    fi
                else
                    log_debug "Directory not found: $dir"
                fi
            done
            
            # Ensure core application files are readable by the dynamic user via group membership
            log_debug "Ensuring core application files are accessible to dynamic user"
            local core_files=("/app/app.py" "/app/database.py" "/app/_version.py" "/app/pyproject.toml")
            for file in "${core_files[@]}"; do
                if [[ -f "$file" ]]; then
                    # Verify file is group-readable
                    if [[ ! -r "$file" ]]; then
                        log_debug "Making $file group-readable"
                        chmod g+r "$file" 2>/dev/null || log_debug "Could not make $file group-readable"
                    fi
                fi
            done
            
            # Fix ownership and permissions of secrets if they exist
            if [ -d "/app/secrets" ]; then
                chown -R $TARGET_UID:$TARGET_GID /app/secrets
                chmod -R 640 /app/secrets/* 2>/dev/null || true
            fi
        else
            log_info "Using default appuser (1000:1000)"
        fi
        
        # Switch to target user using gosu and continue execution
        log_info "Switching to user $TARGET_UID:$TARGET_GID and continuing startup"
        exec gosu $TARGET_UID:$TARGET_GID "$0" "$@"
    else
        # Already running as non-root user, proceed normally
        log_info "Running as non-root user $(id -u):$(id -g)"
    fi
}

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
    log_info "Ensuring application directories exist and are accessible..."

    # Create directories if they don't exist
    mkdir -p /app/logs /app/data /app/tmp /app/external_plugins /app/external_config

    # Simple validation that critical directories are accessible
    local dirs_to_check=(
        "/app/logs:Logs:write"
        "/app/data:Data:write" 
        "/app/tmp:Tmp:write"
        "/app/external_plugins:ExternalPlugins:write"
        "/app/external_config:ExternalConfig:write"
        "/app/utils:Utils:read"
        "/app/plugins:Plugins:read"
        "/app/services:Services:read"
        "/app/models:Models:read"
        "/app/routes:Routes:read"
        "/app/config:Config:read"
    )

    for dir_info in "${dirs_to_check[@]}"; do
        IFS=':' read -r dir_path dir_name access_type <<< "$dir_info"
        
        if [[ ! -d "$dir_path" ]]; then
            log_warn "$dir_name directory not found: $dir_path"
            continue
        fi

        case "$access_type" in
            "write")
                if [[ -w "$dir_path" ]]; then
                    log_debug "$dir_name directory is writable"
                else
                    log_error "$dir_name directory is not writable: $dir_path"
                    log_error "Check Docker volume mount permissions and USER_ID/GROUP_ID settings"
                fi
                ;;
            "read")
                if [[ -r "$dir_path" ]]; then
                    log_debug "$dir_name directory is readable"
                else
                    log_error "$dir_name directory is not readable: $dir_path"
                    log_error "Python modules cannot be imported from $dir_path"
                    return 1
                fi
                ;;
        esac
    done
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
                if pg_isready -h "$host" -p "$port" -U "${DB_USER:-postgres}" -d "${DB_NAME:-trakbridge}" >/dev/null 2>&1; then
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
        if flask db current >/dev/null 2>&1; then
            log_info "Flask-Migrate is configured"
            
            current_rev=$(flask db current 2>/dev/null || echo "")
            
            if [[ -z "$current_rev" ]] || [[ "$current_rev" == *"None"* ]]; then
                log_info "No current migration revision found"
                
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
                
                if flask db heads >/dev/null 2>&1; then
                    head_rev=$(flask db heads 2>/dev/null | head -n1 | awk '{print $1}')
                    if [[ -n "$head_rev" ]] && [[ "$current_rev" != "$head_rev" ]]; then
                        log_info "Pending migrations found, running upgrade..."
                        flask db upgrade || log_warn "Migration failed, will retry in application"
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

    # Test import with more detailed error reporting and permission validation
    log_info "Testing Flask application import and Python module accessibility..."
    if python -c "
import sys
import os
sys.path.insert(0, '/app')

# Test critical Python modules first
critical_modules = ['utils', 'services', 'models', 'routes', 'plugins', 'config']
failed_modules = []

for module_name in critical_modules:
    module_path = f'/app/{module_name}'
    if os.path.exists(module_path):
        if not os.access(module_path, os.R_OK):
            failed_modules.append(f'{module_name} (not readable)')
        elif not os.access(module_path, os.X_OK):
            failed_modules.append(f'{module_name} (not executable)')
    else:
        failed_modules.append(f'{module_name} (not found)')

if failed_modules:
    print(f'Module access issues: {failed_modules}')
    # Don't exit here, continue with app import test

try:
    # Test that we can import the module without initializing
    import importlib.util
    spec = importlib.util.spec_from_file_location('app', '/app/app.py')
    if spec is None:
        raise ImportError('Could not create module spec for app.py')
    app_module = importlib.util.module_from_spec(spec)
    print('Application module can be loaded')
    
    # Test key module imports that typically fail with permission issues
    try:
        import utils.json_validator
        print('utils.json_validator import successful')
    except ImportError as e:
        print(f'utils.json_validator import failed: {e}')
        
except Exception as e:
    print(f'Import error: {e}')
    # Show current user context
    import pwd
    import grp
    uid = os.getuid()
    gid = os.getgid() 
    groups = os.getgroups()
    print(f'Current UID: {uid}, GID: {gid}, Groups: {groups}')
    try:
        print(f'User: {pwd.getpwuid(uid).pw_name}')
    except:
        print('Could not resolve username')
    sys.exit(1)
" 2>&1; then
        log_info "Flask application and module import successful"
    else
        log_error "Failed to import Flask application or modules"
        log_error "Attempting to diagnose permission issues..."

        # Additional debugging with user context
        python -c "
import sys
import os
print('=== Python Environment ===')
print('Python version:', sys.version)
print('Python path:', sys.path)
print('=== User Context ===')
print(f'UID: {os.getuid()}, GID: {os.getgid()}, Groups: {os.getgroups()}')
print('=== Environment Variables ===')
for key in ['FLASK_APP', 'FLASK_ENV', 'PYTHONPATH']:
    print(f'  {key}: {os.environ.get(key, \"Not set\")}')
print('=== File Permissions ===')
import stat
for path in ['/app/app.py', '/app/utils', '/app/utils/json_validator.py']:
    if os.path.exists(path):
        st = os.stat(path)
        print(f'{path}: mode={oct(st.st_mode)}, owner={st.st_uid}:{st.st_gid}, readable={os.access(path, os.R_OK)}')
    else:
        print(f'{path}: does not exist')
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

    # Set appropriate permissions if possible
    chmod 644 /app/logs/*.log 2>/dev/null || log_debug "Could not set log file permissions"
}

# Function to install default configuration files to external mount
install_config_files() {
    local external_config_dir="${TRAKBRIDGE_CONFIG_DIR:-/app/external_config}"
    local bundled_config_dir="/app/config/settings"
    local auto_install="${TRAKBRIDGE_CONFIG_AUTO_INSTALL:-true}"
    local update_mode="${TRAKBRIDGE_CONFIG_UPDATE_MODE:-preserve}"
    
    log_info "Checking configuration installation..."
    log_debug "External config dir: $external_config_dir"
    log_debug "Bundled config dir: $bundled_config_dir"
    log_debug "Auto install: $auto_install"
    log_debug "Update mode: $update_mode"
    
    # Skip if auto-install is disabled
    if [[ "$auto_install" != "true" ]]; then
        log_info "Configuration auto-install disabled"
        return 0
    fi
    
    # Skip if external config directory doesn't exist (no volume mount)
    if [[ ! -d "$external_config_dir" ]]; then
        log_debug "External config directory not found - no volume mounted"
        return 0
    fi
    
    # Skip if bundled config doesn't exist
    if [[ ! -d "$bundled_config_dir" ]]; then
        log_warn "Bundled configuration directory not found: $bundled_config_dir"
        return 0
    fi
    
    # Ensure external config directory is writable
    if [[ ! -w "$external_config_dir" ]]; then
        log_error "External config directory is not writable: $external_config_dir"
        return 1
    fi
    
    local files_installed=0
    local files_updated=0
    local files_skipped=0
    
    # Process each configuration file
    for config_file in "$bundled_config_dir"/*.yaml; do
        if [[ ! -f "$config_file" ]]; then
            continue
        fi
        
        local filename=$(basename "$config_file")
        local external_file="$external_config_dir/$filename"
        
        if [[ -f "$external_file" ]]; then
            # File exists in external config
            case "$update_mode" in
                "preserve")
                    log_debug "Preserving existing config: $filename"
                    files_skipped=$((files_skipped + 1))
                    ;;
                "overwrite")
                    log_info "Overwriting config file: $filename"
                    cp "$config_file" "$external_file"
                    files_updated=$((files_updated + 1))
                    ;;
                "merge")
                    # For now, preserve existing (merge could be implemented later)
                    log_debug "Preserving existing config (merge mode): $filename"
                    files_skipped=$((files_skipped + 1))
                    ;;
                *)
                    log_warn "Unknown update mode: $update_mode, preserving existing file"
                    files_skipped=$((files_skipped + 1))
                    ;;
            esac
        else
            # File doesn't exist, install it
            log_info "Installing config file: $filename"
            cp "$config_file" "$external_file"
            files_installed=$((files_installed + 1))
        fi
    done
    
    # Set appropriate permissions on installed files
    if [[ $files_installed -gt 0 ]] || [[ $files_updated -gt 0 ]]; then
        chmod 644 "$external_config_dir"/*.yaml 2>/dev/null || log_debug "Could not set config file permissions"
    fi
    
    # Log summary
    if [[ $files_installed -gt 0 ]] || [[ $files_updated -gt 0 ]] || [[ $files_skipped -gt 0 ]]; then
        log_info "Configuration installation complete:"
        log_info "  Installed: $files_installed files"
        log_info "  Updated: $files_updated files"
        log_info "  Preserved: $files_skipped files"
    else
        log_debug "No configuration files processed"
    fi
    
    return 0
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
            # Sanitize and validate environment variables
            local workers=${HYPERCORN_WORKERS:-4}
            local worker_class=${HYPERCORN_WORKER_CLASS:-asyncio}
            local bind=${HYPERCORN_BIND:-0.0.0.0:5000}
            local keep_alive=${HYPERCORN_KEEP_ALIVE:-5}
            local max_requests=${HYPERCORN_MAX_REQUESTS:-1000}
            local max_requests_jitter=${HYPERCORN_MAX_REQUESTS_JITTER:-100}
            local log_level=${HYPERCORN_LOG_LEVEL:-warning}
            local timeout=${HYPERCORN_TIMEOUT:-60}
            local graceful_timeout=${HYPERCORN_GRACEFUL_TIMEOUT:-30}
            local preload_app=${HYPERCORN_PRELOAD_APP:-true}
            local max_concurrent_connections=${HYPERCORN_MAX_CONCURRENT_CONNECTIONS:-1000}
            local enable_http2=${HYPERCORN_ENABLE_HTTP2:-true}
            local enable_websockets=${HYPERCORN_ENABLE_WEBSOCKETS:-true}

            log_info "Using Hypercorn production server with inline configuration"

            # SQLite concurrency check: Force single worker for SQLite to avoid file locking issues
            if [[ "${DB_TYPE:-}" == "sqlite" ]] || [[ -z "${DB_TYPE:-}" && -z "${DATABASE_URL:-}" ]]; then
                if [[ "$workers" -gt 1 ]]; then
                    log_warn "SQLite detected: Forcing single worker (workers=1) to avoid database file locking issues"
                    log_warn "For better performance with multiple workers, consider using PostgreSQL or MySQL"
                    workers=1
                fi
            fi

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
                --timeout "$timeout" \
                --graceful_timeout "$graceful_timeout" \
                --preload_app "$preload_app" \
                --max_concurrent_connections "$max_concurrent_connections" \
                --enable_http2 "$enable_http2" \
                --enable_websockets "$enable_websockets" \
                --access-logfile /app/logs/hypercorn-access.log \
                --error-logfile /app/logs/hypercorn-error.log \
                app:app
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

    # Handle user switching first (this may cause re-exec)
    handle_user_switching

    # Ensure we're in the correct directory
    cd /app

    # Ensure proper permissions (simplified since user switching handles ownership)
    ensure_permissions

    # Handle secrets permissions
    if ! handle_secrets; then
        log_error "Failed to handle secrets permissions"
        exit 1
    fi

    # Setup logging
    setup_logging

    # Install configuration files to external mount if needed
    if ! install_config_files; then
        log_error "Configuration installation failed"
        exit 1
    fi

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