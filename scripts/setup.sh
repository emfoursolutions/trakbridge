#!/bin/bash
# =============================================================================
# setup.sh - TrakBridge Setup Script
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
ENVIRONMENT="production"
FORCE_RECREATE=false
ENABLE_NGINX=false
NGINX_SSL=false
NGINX_DOMAIN="localhost"

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
        --enable-nginx)
            ENABLE_NGINX=true
            shift
            ;;
        --nginx-ssl)
            NGINX_SSL=true
            NGINX_DOMAIN="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  -f, --force          Force recreate secrets and config files"
            echo "  --enable-nginx       Enable nginx setup and download configuration"
            echo "  --nginx-ssl DOMAIN   Enable SSL for nginx with specified domain"
            echo "  -h, --help           Show this help"
            echo ""
            echo "Examples:"
            echo "  $0 --enable-nginx                    # Setup with nginx"
            echo "  $0 --nginx-ssl example.com           # Setup with SSL for example.com"
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
mkdir -p secrets plugins logs data config docker/init-scripts

# Create nginx directory if enabled
if [[ "$ENABLE_NGINX" == true ]] || [[ "$NGINX_SSL" == true ]]; then
    mkdir -p docker/nginx
fi

# Set UID and GID Environment Variables
setup_uidgid() {
    log_step "Setting Docker User ID and Group ID Environment Variables based on current user"
    export DOCKER_USER_ID=$(id -u)
    export DOCKER_GROUP_ID=$(id -g)
    log_info "Set DOCKER_USER_ID=$DOCKER_USER_ID and DOCKER_GROUP_ID=$DOCKER_GROUP_ID"
}

# Setup secrets
setup_secrets() {
    log_step "Setting up secrets..."

    # Production secrets (secure)
    if [[ ! -f "secrets/db_password" ]] || [[ "$FORCE_RECREATE" == true ]]; then
        openssl rand -base64 32 > secrets/db_password
        log_info "Generated secure database password"
    fi

    if [[ ! -f "secrets/secret_key" ]] || [[ "$FORCE_RECREATE" == true ]]; then
        python3 -c "import secrets; print(secrets.token_urlsafe(64))" > secrets/secret_key
        log_info "Generated secure secret key"
    fi

    if [[ ! -f "secrets/tb_master_key" ]] || [[ "$FORCE_RECREATE" == true ]]; then
        python3 -c "import secrets; print(secrets.token_urlsafe(64))" > secrets/tb_master_key
        log_info "Generated secure master key"
    fi

    # Set appropriate permissions
    chmod 600 secrets/*
    log_info "Set secure permissions on secret files"
}

# Setup Docker initialization scripts
setup_docker_scripts() {
    log_step "Setting up Docker initialization scripts..."

    # Create separate directories for each database
    mkdir -p docker/init-scripts/postgres docker/init-scripts/mysql

    # PostgreSQL init script
    cat > docker/init-scripts/postgres/01-init-postgres.sql << 'EOF'
-- PostgreSQL initialization script
-- This script runs when the PostgreSQL container starts for the first time

-- Create additional databases if needed
-- CREATE DATABASE trakbridge;

-- Create extensions if needed
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- CREATE EXTENSION IF NOT EXISTS "hstore";

-- Set up proper permissions
GRANT ALL PRIVILEGES ON DATABASE trakbridge TO postgres;
EOF

    # MySQL init script
    cat > docker/init-scripts/mysql/01-init-mysql.sql << 'EOF'
-- MySQL initialization script
-- This script runs when the MySQL container starts for the first time

-- Create additional databases if needed
-- CREATE DATABASE trakbridge CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Grant permissions
GRANT ALL PRIVILEGES ON trakbridge.* TO 'mysql'@'%';
FLUSH PRIVILEGES;
EOF

    log_info "Created database initialization scripts in separate directories"
}

# Setup nginx
setup_nginx() {
    if [[ "$ENABLE_NGINX" == true ]] || [[ "$NGINX_SSL" == true ]]; then
        log_step "Setting up nginx..."
        
        # Download nginx configuration
        if command -v curl &> /dev/null; then
            log_info "Downloading nginx configuration..."
            curl -s -o docker/nginx/nginx.conf https://raw.githubusercontent.com/emfoursolutions/trakbridge/refs/heads/main/init/nginx/nginx.conf
            log_info "nginx configuration downloaded to docker/nginx/nginx.conf"
        elif command -v wget &> /dev/null; then
            log_info "Downloading nginx configuration..."
            wget -q -O docker/nginx/nginx.conf https://raw.githubusercontent.com/emfoursolutions/trakbridge/refs/heads/main/init/nginx/nginx.conf
            log_info "nginx configuration downloaded to docker/nginx/nginx.conf"
        else
            log_error "Neither curl nor wget is available. Please install one of them to download nginx configuration."
            exit 1
        fi
    fi
}

# Setup SSL certificates
setup_ssl() {
    if [[ "$NGINX_SSL" == true ]]; then
        log_step "Setting up SSL certificates..."
        
        # Create SSL setup script inline
        cat > /tmp/setup-ssl.sh << 'EOF'
#!/bin/bash
# SSL Certificate Setup for TrakBridge

set -euo pipefail

SSL_DIR="./docker/nginx/ssl"
DOMAIN="${1:-localhost}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }

# Create SSL directory
mkdir -p "$SSL_DIR"

# Check if certificates already exist
if [[ -f "$SSL_DIR/trakbridge.crt" && -f "$SSL_DIR/trakbridge.key" ]]; then
    warn "SSL certificates already exist. Use --force to overwrite."
    if [[ "${2:-}" != "--force" ]]; then
        exit 0
    fi
fi

info "Setting up SSL certificates for domain: $DOMAIN"

# Generate self-signed certificate for development/testing
if [[ "$DOMAIN" == "localhost" || "$DOMAIN" == "127.0.0.1" ]]; then
    info "Generating self-signed certificate for development..."
    
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$SSL_DIR/trakbridge.key" \
        -out "$SSL_DIR/trakbridge.crt" \
        -subj "/C=US/ST=State/L=City/O=Organization/CN=$DOMAIN" \
        -config <(
            echo '[req]'
            echo 'distinguished_name = req_distinguished_name'
            echo 'req_extensions = v3_req'
            echo 'prompt = no'
            echo '[req_distinguished_name]'
            echo 'C = US'
            echo 'ST = State'
            echo 'L = City'
            echo 'O = Organization'
            echo 'CN = '$DOMAIN
            echo '[v3_req]'
            echo 'keyUsage = keyEncipherment, dataEncipherment'
            echo 'extendedKeyUsage = serverAuth'
            echo 'subjectAltName = @alt_names'
            echo '[alt_names]'
            echo 'DNS.1 = localhost'
            echo 'DNS.2 = 127.0.0.1'
            echo 'IP.1 = 127.0.0.1'
        )
    
    warn "Self-signed certificate generated. Browsers will show security warnings."
    info "For production, replace with certificates from a trusted CA."
    
else
    info "For production domain '$DOMAIN', you should:"
    echo "1. Obtain certificates from Let's Encrypt or a trusted CA"
    echo "2. Place your certificate as: $SSL_DIR/trakbridge.crt"
    echo "3. Place your private key as: $SSL_DIR/trakbridge.key"
    echo ""
    echo "Let's Encrypt example:"
    echo "  certbot certonly --standalone -d $DOMAIN"
    echo "  cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem $SSL_DIR/trakbridge.crt"
    echo "  cp /etc/letsencrypt/live/$DOMAIN/privkey.pem $SSL_DIR/trakbridge.key"
    
    # Generate temporary self-signed cert for initial setup
    info "Generating temporary self-signed certificate..."
    openssl req -x509 -nodes -days 30 -newkey rsa:2048 \
        -keyout "$SSL_DIR/trakbridge.key" \
        -out "$SSL_DIR/trakbridge.crt" \
        -subj "/C=US/ST=State/L=City/O=Organization/CN=$DOMAIN"
    
    warn "Temporary certificate created. Replace with proper certificate before production!"
fi

# Set proper permissions
chmod 600 "$SSL_DIR/trakbridge.key"
chmod 644 "$SSL_DIR/trakbridge.crt"

info "✅ SSL certificates ready in: $SSL_DIR"
info "Certificate: $SSL_DIR/trakbridge.crt"
info "Private Key: $SSL_DIR/trakbridge.key"
EOF

        # Make the SSL script executable and run it
        chmod +x /tmp/setup-ssl.sh
        /tmp/setup-ssl.sh "$NGINX_DOMAIN" "${FORCE_RECREATE:+--force}"
        
        # Clean up temporary script
        rm /tmp/setup-ssl.sh
    fi
}

# Main setup
main() {
    setup_secrets
    setup_docker_scripts
    setup_nginx
    setup_ssl
    setup_uidgid

    log_info "Setup completed successfully!"
    echo ""
    log_info "Next steps:"
    log_info "1. Review the generated configuration files"
    if [[ "$ENABLE_NGINX" == true ]] || [[ "$NGINX_SSL" == true ]]; then
        log_info "2. Start the services: docker-compose --profile [postgres | mysql | sqlite] up -d"
        log_info "3. nginx configuration available at: docker/nginx/nginx.conf"
        log_info "4. If you intend to run the docker container as a different user set the DOCKER_USER_ID and DOCKER_GROUP_ID Environment Variables to that users UID and GID"
        if [[ "$NGINX_SSL" == true ]]; then
            log_info "4. SSL certificates generated for domain: $NGINX_DOMAIN"
        fi
    else
        log_info "2. Start the services: docker-compose --profile [postgres | mysql | sqlite] up -d"
        log_info "3. If you intend to run the docker container as a different user set the DOCKER_USER_ID and DOCKER_GROUP_ID Environment Variables to that users UID and GID"
    fi
    log_info "$(( [[ "$ENABLE_NGINX" == true ]] || [[ "$NGINX_SSL" == true ]] ) && echo "5" || echo "3"). Check logs: docker-compose logs -f"

    echo ""
    log_warn "IMPORTANT: Review and update the generated secrets in the secrets/ directory!"
    log_warn "The current secrets are randomly generated and should be backed up securely."
    
    if [[ "$NGINX_SSL" == true ]]; then
        echo ""
        log_warn "SSL NOTES:"
        if [[ "$NGINX_DOMAIN" == "localhost" || "$NGINX_DOMAIN" == "127.0.0.1" ]]; then
            log_warn "- Self-signed certificate generated for development"
            log_warn "- Browsers will show security warnings"
        else
            log_warn "- Temporary certificate generated for '$NGINX_DOMAIN'"
            log_warn "- Replace with proper certificate before production!"
        fi
    fi
}

# Run main function
main