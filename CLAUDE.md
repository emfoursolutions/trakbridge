# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the Application
```bash
# Development server
python app.py

# Production server with Hypercorn (default config)
hypercorn app:app

# Production server with custom config
hypercorn -c hypercorn.toml app:app
```

### Testing and Quality
```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Code formatting
black .

# Linting
flake8 .

# Import sorting
isort .

# Type checking
mypy .

# Security scanning
bandit -r .

# Safety check for dependencies
safety check
```

### Database Management
```bash
# Initialize database
flask db init

# Create migration
flask db migrate -m "Description"

# Apply migrations
flask db upgrade

# Downgrade
flask db downgrade
```

### Docker Operations
```bash
# Development with file watching
docker-compose -f docker-compose-dev.yml up

# Production deployment
docker-compose up -d

# With PostgreSQL and Nginx
docker-compose --profile postgres --profile nginx up -d
```

## Architecture Overview

TrakBridge is a GPS tracking data bridge that forwards location data from various providers to TAK (Team Awareness Kit) servers. The application follows a plugin-based architecture with these core components:

### Core Architecture
- **Flask Application Factory** (`app.py`): Main application entry point with factory pattern
- **Stream Manager** (`services/stream_manager.py`): Central orchestrator for all data streams using singleton pattern
- **Plugin System** (`plugins/`): Extensible architecture for different GPS providers
- **Database Layer** (`models/`, `database.py`): SQLAlchemy ORM with Alembic migrations
- **Configuration Management** (`config/`): YAML-based configuration with secrets management

### Plugin Architecture
All GPS providers inherit from `BaseGPSPlugin` (`plugins/base_plugin.py`) and implement:
- `fetch_data()`: Retrieve GPS data from provider
- `transform_data()`: Convert to CoT (Cursor on Target) format
- Configuration field definitions for UI generation

Current plugins:
- Garmin InReach (`garmin_plugin.py`)
- SPOT Tracker (`spot_plugin.py`) 
- Traccar (`traccar_plugin.py`)
- Deepstate (`deepstate_plugin.py`)

### Stream Processing Flow
1. Stream Manager starts worker threads for each active stream
2. Plugin fetches data from GPS provider APIs
3. Data transformed to CoT XML format
4. CoT events sent to configured TAK servers
5. Health monitoring and automatic restart on failures

### Key Services
- **COT Service** (`services/cot_service.py`): Persistent TAK server connections
- **Stream Worker** (`services/stream_worker.py`): Individual stream execution
- **Database Manager** (`services/database_manager.py`): Database operations and health
- **Encryption Service** (`services/encryption_service.py`): Field-level encryption for credentials
- **Session Manager** (`services/session_manager.py`): HTTP session pooling

### Database Models
- **Stream**: GPS data stream configuration
- **TAKServer**: TAK server connection details with certificate support
- Uses SQLAlchemy with Flask-Migrate for schema management

### Configuration System
- YAML-based configuration in `config/settings/`
- Environment-specific settings (development, production, staging)
- Secrets management with encryption for sensitive data
- Validation layer in `config/validators.py`

## Development Notes

### Code Style
- Uses comprehensive docstrings with file descriptions starting with "file:"
- Type hints throughout the codebase
- Logging configuration in `services/logging_service.py`
- Error handling with custom exception classes

### Testing
- Test dependencies defined in `pyproject.toml` under `[project.optional-dependencies.dev]`
- No existing test directory found - tests should be created following pytest conventions

### Deployment
- Docker-first deployment with multi-stage builds
- Hypercorn ASGI server for production
- Database migrations handled via Alembic
- Health check endpoint at `/api/health`

### Key Dependencies
- Flask with SQLAlchemy for web framework and ORM
- Hypercorn for ASGI server deployment
- PyTAK for TAK server integration
- Cryptography for field-level encryption
- Alembic for database migrations

## External Plugin Support

TrakBridge supports loading external plugins from Docker volume mounts without modifying core code:

### Docker Volume Mount
```bash
# Mount external plugins directory
docker run -v $(pwd)/my-plugins:/app/external_plugins:ro trakbridge:latest
```

### Plugin Configuration
Add external plugins to `config/settings/plugins.yaml`:
```yaml
allowed_plugin_modules:
  - external_plugins.my_custom_tracker
  - external_plugins.enterprise_gps
```

### Available External Plugin Paths
- `/app/external_plugins` (primary - for Docker volumes)
- `/opt/trakbridge/plugins` (system-wide)
- `~/.trakbridge/plugins` (user-specific)
- `./external_plugins` (local directory)

### Plugin Management
```bash
# List allowed plugin modules
python scripts/manage_plugins.py list

# Add plugin module (temporary)
python scripts/manage_plugins.py add external_plugins.new_plugin

# Reload configuration
python scripts/manage_plugins.py reload
```

### Configuration Management
```bash
# List configuration files and sources
python scripts/manage_config.py list

# Install default configurations
python scripts/manage_config.py install

# Validate configuration
python scripts/manage_config.py validate --environment production

# Backup configuration
python scripts/manage_config.py backup

# Restore from backup
python scripts/manage_config.py restore --backup-dir ./config-backup-timestamp
```

See `docs/DOCKER_PLUGINS.md` for complete Docker plugin setup guide and `example_external_plugins/` for sample plugins.

## Security Implementation

TrakBridge has undergone comprehensive security hardening to meet enterprise security standards and eliminate identified vulnerabilities.

### Security Fixes Implemented (2025-07-26)

#### 1. JSON Validation Security (`utils/json_validator.py`)
**Issue:** Unvalidated JSON parsing could cause DoS attacks through memory exhaustion or stack overflow
**Solution:** Comprehensive JSON validation with security controls
- **Size limits:** 64KB for plugin configs, 256KB for database configs, 1MB default
- **Depth limits:** Maximum 32 levels of nesting to prevent stack overflow
- **Structure limits:** Max 1000 keys per object, 10000 array elements
- **Schema validation:** Plugin-specific validation with type checking
- **Files updated:** `plugins/plugin_manager.py:312`, `models/stream.py:71,93`

#### 2. XSS Vulnerability Fixes (Templates)
**Issue:** Cross-site scripting vulnerabilities in HTML templates
**Solution:** Replaced embedded JSON with secure API endpoints
- **Templates updated:** `create_stream.html`, `edit_stream.html`, `cot_types.html`
- **API endpoints added:** `/api/plugins/metadata`, `/api/streams/{id}/config`, `/api/cot_types/export-data`
- **Security benefit:** Complete separation of data and presentation layers

#### 3. CDN Security Migration (Static Assets)
**Issue:** External CDN dependencies posed security and privacy risks
**Solution:** All external resources moved to local static files
- **Assets localized:** Bootstrap 5.1.3, Font Awesome 6.0.0, Google Fonts (Inter, JetBrains Mono), jQuery 3.6.0
- **Total size:** ~2.7MB of assets now served locally
- **Security benefit:** Eliminated external tracking, prevented CDN compromise attacks

#### 4. Docker Container Security (High Priority)
**Issue:** Container running as root user violated principle of least privilege
**Solution:** Enhanced Docker security with non-root execution by default
- **Default user:** Container runs as `appuser` (1000:1000) by default
- **Dynamic UID/GID:** Maintains host filesystem compatibility via USER_ID/GROUP_ID environment variables
- **Root protection:** Explicit `ALLOW_ROOT=true` required for root access
- **Secure switching:** Uses `gosu` for secure user transitions when needed

#### 5. Shell Command Injection Prevention (Entrypoint Script)
**Issue:** Use of `eval` in entrypoint script posed command injection risk
**Solution:** Replaced `eval` with secure direct execution and input validation
- **Removed eval:** Eliminated `eval $server_cmd` vulnerable pattern
- **Direct execution:** Uses `exec` with validated parameters instead of string evaluation
- **Input validation:** Environment variables sanitized with range and format validation
- **Allowlist validation:** Worker class and log level restricted to known safe values
- **File updated:** `docker/entrypoint.sh:463` and related functions

### Security Architecture Enhancements

#### JSON Validation (`utils/json_validator.py`)
```python
# Secure JSON parsing with comprehensive protection
def safe_json_loads(json_string: str, max_size: int = DEFAULT_MAX_SIZE, context: str = "unknown") -> Any
class SecureJSONValidator  # Size, depth, structure, and schema validation
class JSONValidationError  # Detailed error context and security information
```

#### Docker Security Model
```dockerfile
# Create default non-root user
RUN groupadd -g 1000 appuser && useradd -r -u 1000 -g appuser -d /app -s /bin/bash appuser
# Switch to non-root user by default
USER appuser
```

```bash
# Dynamic UID/GID support maintained
docker run -e USER_ID=$(id -u) -e GROUP_ID=$(id -g) trakbridge:latest
```

#### Secure Entrypoint Script (`docker/entrypoint.sh`)
```bash
# Secure server startup (replaces eval-based approach)
start_server() {
    cd /app
    case "$FLASK_ENV" in
        "production"|"staging")
            # Input validation prevents injection
            if ! [[ "$workers" =~ ^[0-9]+$ ]] || [[ "$workers" -lt 1 ]] || [[ "$workers" -gt 16 ]]; then
                workers=4  # Safe default
            fi
            # Direct execution instead of eval
            exec hypercorn --bind "$bind" --workers "$workers" app:app
            ;;
    esac
}
```

### Security Testing and Validation

#### Comprehensive Security Scans
- **Semgrep analysis:** Identified and resolved 13 security findings
- **Static analysis:** No critical SQL injection, XSS, or command injection vulnerabilities
- **Dynamic testing:** All security controls validated with test cases

#### Security Compliance Achieved
- ✅ **CIS Docker Benchmark:** Container runs as non-root user
- ✅ **NIST Cybersecurity Framework:** Principle of least privilege implemented
- ✅ **Input validation:** Comprehensive JSON validation prevents DoS attacks
- ✅ **XSS prevention:** Secure API-based data loading implemented

### Security Documentation
- **`docs/JSON_VALIDATION_SECURITY.md`** - Comprehensive JSON validation implementation
- **`docs/DOCKER_SECURITY.md`** - Docker security architecture and deployment guide
- **Backward compatibility:** All security fixes maintain existing functionality

### Remaining Security Recommendations (Low Priority)
1. **Nginx H2C configuration review** - Restrict upgrade headers if WebSocket not needed
2. **Enhanced security headers** - Add comprehensive security headers to nginx config
3. **Dependency scanning** - Integrate automated vulnerability scanning in CI/CD

### Security Development Guidelines
- **Secure by default:** All new features implement security controls from the start
- **Defense in depth:** Multiple layers of security protection
- **Principle of least privilege:** Minimal permissions required for operation
- **Comprehensive logging:** All security events logged for monitoring and analysis