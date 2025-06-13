#!/bin/bash
# =============================================================================
# build.sh - Environment Setup Script
# =============================================================================

set -e

# Colors
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

# Default values
ENVIRONMENT="development"
FORCE_RECREATE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -f|--force)
            FORCE_RECREATE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  -e, --env ENV    Environment (development|production|staging) [default: development]"
            echo "  -f, --force      Force recreate secrets and config files"
            echo "  -h, --help       Show this help"
            echo ""
            echo "Examples:"
            echo "  $0                        # Setup development environment"
            echo "  $0 -e production         # Setup production environment"
            echo "  $0 -e development -f     # Force recreate development setup"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

log_info "Setting up TrakBridge for environment: $ENVIRONMENT"

# Create directory structure
log_step "Creating directory structure..."
mkdir -p secrets logs data config/settings docker/init-scripts docker/nginx

# Setup secrets
setup_secrets() {
    log_step "Setting up secrets..."

    if [[ "$ENVIRONMENT" == "development" ]]; then
        # Development secrets (not secure)
        if [[ ! -f "secrets/db_password.txt" ]] || [[ "$FORCE_RECREATE" == true ]]; then
            echo "dev-password-123" > secrets/db_password.txt
            log_info "Created development database password"
        fi

        if [[ ! -f "secrets/secret_key.txt" ]] || [[ "$FORCE_RECREATE" == true ]]; then
            echo "dev-secret-key-change-in-production-$(date +%s)" > secrets/secret_key.txt
            log_info "Created development secret key"
        fi

        if [[ ! -f "secrets/master_key.txt" ]] || [[ "$FORCE_RECREATE" == true ]]; then
            echo "dev-secret-key-change-in-production-$(date +%s)" > secrets/master_key.txt
            log_info "Created development master key"
        fi
    else
        # Production secrets (secure)
        if [[ ! -f "secrets/db_password.txt" ]] || [[ "$FORCE_RECREATE" == true ]]; then
            openssl rand -base64 32 > secrets/db_password.txt
            log_info "Generated secure database password"
        fi

        if [[ ! -f "secrets/secret_key.txt" ]] || [[ "$FORCE_RECREATE" == true ]]; then
            python3 -c "import secrets; print(secrets.token_urlsafe(64))" > secrets/secret_key.txt
            log_info "Generated secure secret key"
        fi

        if [[ ! -f "secrets/master_key.txt" ]] || [[ "$FORCE_RECREATE" == true ]]; then
            python3 -c "import secrets; print(secrets.token_urlsafe(64))" > secrets/master_key.txt
            log_info "Generated secure master key"
        fi
    fi

    # Set appropriate permissions
    chmod 600 secrets/*.txt
    log_info "Set secure permissions on secret files"
}

# Setup environment file
setup_environment() {
    log_step "Setting up environment configuration..."

    ENV_FILE=".env"
    if [[ "$ENVIRONMENT" != "development" ]]; then
        ENV_FILE=".env.${ENVIRONMENT}"
    fi

    if [[ ! -f "$ENV_FILE" ]] || [[ "$FORCE_RECREATE" == true ]]; then
        case "$ENVIRONMENT" in
            "development")
                cat > "$ENV_FILE" << 'EOF'
# Development Environment
FLASK_ENV=development
FLASK_APP=app.py
DEBUG=true
LOG_LEVEL=DEBUG

# Database
DB_TYPE=sqlite
DB_NAME=dev_app.db

# Docker Compose
BUILD_TARGET=development
APP_PORT=5000
POSTGRES_PORT=5432
MYSQL_PORT=3306

# Performance
MAX_WORKER_THREADS=4
MAX_CONCURRENT_STREAMS=50
DEFAULT_POLL_INTERVAL=60

# Secret files
DB_PASSWORD_FILE=./secrets/db_password.txt
SECRET_KEY_FILE=./secrets/secret_key.txt
TB_MASTER_KEY=./secrets/master_key.txt
EOF
                ;;
            "production")
                cat > "$ENV_FILE" << 'EOF'
# Production Environment
FLASK_ENV=production
FLASK_APP=app.py
DEBUG=false
LOG_LEVEL=INFO

# Database
DB_TYPE=postgresql
DB_HOST=postgres
DB_PORT=5432
DB_NAME=takbridge_db
DB_USER=postgres

# Docker Compose
BUILD_TARGET=production
APP_PORT=5000

# Performance
MAX_WORKER_THREADS=8
MAX_CONCURRENT_STREAMS=200
DEFAULT_POLL_INTERVAL=120
HTTP_TIMEOUT=30

# Feature flags
ENABLE_SQL_ECHO=false
SQLALCHEMY_RECORD_QUERIES=false

# Secret files
DB_PASSWORD_FILE=./secrets/db_password.txt
SECRET_KEY_FILE=./secrets/secret_key.txt
TB_MASTER_KEY=./secrets/master_key.txt
EOF
                ;;
            "staging")
                cat > "$ENV_FILE" << 'EOF'
# Staging Environment
FLASK_ENV=staging
FLASK_APP=app.py
DEBUG=false
LOG_LEVEL=INFO

# Database
DB_TYPE=postgresql
DB_HOST=postgres
DB_PORT=5432
DB_NAME=takbridge_db_staging
DB_USER=postgres

# Docker Compose
BUILD_TARGET=production
APP_PORT=5000

# Performance
MAX_WORKER_THREADS=6
MAX_CONCURRENT_STREAMS=100
DEFAULT_POLL_INTERVAL=120

# Secret files
DB_PASSWORD_FILE=./secrets/db_password.txt
SECRET_KEY_FILE=./secrets/secret_key.txt
TB_MASTER_KEY=./secrets/master_key.txt
EOF
                ;;
        esac
        log_info "Created $ENV_FILE"
    else
        log_info "$ENV_FILE already exists"
    fi
}

# Setup configuration validation
setup_config_validation() {
    log_step "Setting up configuration validation..."

    cat > validate_config.py << 'EOF'
#!/usr/bin/env python3
"""Configuration validation script."""

import sys
import os
sys.path.insert(0, '.')

try:
    from config.base import BaseConfig

    # Get environment from command line or default
    environment = sys.argv[1] if len(sys.argv) > 1 else 'development'

    print(f"Validating configuration for environment: {environment}")

    # Create config instance
    config = BaseConfig(environment=environment)

    # Validate configuration
    issues = config.validate_config()

    if issues:
        print("Configuration issues found:")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)
    else:
        print("Configuration validation passed!")

        # Print configuration summary
        print("\nConfiguration Summary:")
        config_dict = config.to_dict()
        for section, values in config_dict.items():
            print(f"  {section}:")
            if isinstance(values, dict):
                for key, value in values.items():
                    print(f"    {key}: {value}")
            else:
                print(f"    {values}")

        sys.exit(0)

except Exception as e:
    print(f"Configuration validation failed: {e}")
    sys.exit(1)
EOF

    chmod +x validate_config.py
    log_info "Created configuration validation script"
}

# Setup Docker initialization scripts
setup_docker_scripts() {
    log_step "Setting up Docker initialization scripts..."

    # PostgreSQL init script
    cat > docker/init-scripts/01-init-postgres.sql << 'EOF'
-- PostgreSQL initialization script
-- This script runs when the PostgreSQL container starts for the first time

-- Create additional databases if needed
-- CREATE DATABASE trakbridge_db_test;

-- Create extensions if needed
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- CREATE EXTENSION IF NOT EXISTS "hstore";

-- Set up proper permissions
GRANT ALL PRIVILEGES ON DATABASE trakbridge_db TO postgres;
EOF

    # MySQL init script
    cat > docker/init-scripts/01-init-mysql.sql << 'EOF'
-- MySQL initialization script
-- This script runs when the MySQL container starts for the first time

-- Set proper character set and collation
ALTER DATABASE trakbridge_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create additional databases if needed
-- CREATE DATABASE trakbridge_db_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Grant permissions
GRANT ALL PRIVILEGES ON trakbridge_db.* TO 'mysql'@'%';
FLUSH PRIVILEGES;
EOF

    log_info "Created database initialization scripts"
}

# Main setup
main() {
    setup_secrets
    setup_environment
    setup_config_validation
    setup_docker_scripts

    # Validate configuration
    log_step "Validating configuration..."
    if command -v python3 >/dev/null 2>&1; then
        if python3 validate_config.py "$ENVIRONMENT"; then
            log_info "Configuration validation passed!"
        else
            log_warn "Configuration validation failed - please check your setup"
        fi
    else
        log_warn "Python3 not found - skipping configuration validation"
    fi

    log_info "Setup completed successfully!"
    echo ""
    log_info "Next steps:"
    log_info "1. Review the generated configuration files"
    log_info "2. Build the Docker image: ./build.sh -e $ENVIRONMENT"
    log_info "3. Start the services: docker-compose --env-file .env${ENVIRONMENT:+.$ENVIRONMENT} up -d"
    log_info "4. Check logs: docker-compose logs -f"

    if [[ "$ENVIRONMENT" == "production" ]]; then
        echo ""
        log_warn "IMPORTANT: Review and update the generated secrets in the secrets/ directory!"
        log_warn "The current secrets are randomly generated and should be backed up securely."
    fi
}

# Run main function
main