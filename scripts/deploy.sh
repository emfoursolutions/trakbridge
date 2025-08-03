#!/bin/bash

# =============================================================================
# TrakBridge Deployment Script
# =============================================================================
#
# Automated deployment script for TrakBridge across different environments.
# This script handles environment setup, Docker deployments, health checks,
# and rollback capabilities.
#
# Author: Emfour Solutions
# Version: 1.0.0
# =============================================================================

set -euo pipefail

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="/tmp/trakbridge-deploy-$(date +%Y%m%d-%H%M%S).log"

# Default values
ENVIRONMENT="development"
ACTION="deploy"
COMPOSE_FILE=""
PROFILES=""
HEALTH_CHECK_TIMEOUT=300
ROLLBACK_ON_FAILURE=true
VERBOSE=false
APP_PORT=""
BRANCH_NAME=""
USE_PREBUILT=false

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Utility Functions
# =============================================================================

log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case "$level" in
        "INFO")
            echo -e "${GREEN}[INFO]${NC} $message" | tee -a "$LOG_FILE"
            ;;
        "WARN")
            echo -e "${YELLOW}[WARN]${NC} $message" | tee -a "$LOG_FILE"
            ;;
        "ERROR")
            echo -e "${RED}[ERROR]${NC} $message" | tee -a "$LOG_FILE"
            ;;
        "DEBUG")
            if [[ "$VERBOSE" == "true" ]]; then
                echo -e "${BLUE}[DEBUG]${NC} $message" | tee -a "$LOG_FILE"
            fi
            ;;
    esac
    
    echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
}

show_usage() {
    cat << EOF
TrakBridge Deployment Script

Usage: $0 [OPTIONS]

Options:
    -e, --environment ENV    Target environment (development|staging|production|feature)
    -a, --action ACTION      Action to perform (deploy|stop|restart|status|rollback)
    -p, --profiles PROFILES  Docker Compose profiles to enable (comma-separated)
    -t, --timeout SECONDS    Health check timeout (default: 300)
    -f, --compose-file FILE  Custom docker-compose file
        --port PORT          Override application port (for feature branches)
        --branch BRANCH      Feature branch name (for feature environment)
        --use-prebuilt       Use pre-built images instead of building locally
    -v, --verbose            Enable verbose logging
    -h, --help              Show this help message

Examples:
    $0 --environment development --action deploy
    $0 --environment staging --profiles postgres,nginx --action deploy
    $0 --environment production --action status
    $0 --environment feature --port 5010 --branch feature-auth --action deploy
    $0 --action rollback

Environments:
    development     - Development environment with debug features
    staging         - Production-like environment for testing
    production      - Production deployment (Docker Hub images only)
    feature         - Feature branch review environment with dynamic ports

Actions:
    deploy          - Deploy or update the application
    stop            - Stop all services
    restart         - Restart all services
    status          - Show deployment status
    rollback        - Rollback to previous deployment

EOF
}

check_prerequisites() {
    log "INFO" "Checking prerequisites..."
    
    # Check if Docker is installed and running
    if ! command -v docker &> /dev/null; then
        log "ERROR" "Docker is not installed or not in PATH"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        log "ERROR" "Docker daemon is not running"
        exit 1
    fi
    
    # Check if Docker Compose is available
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log "ERROR" "Docker Compose is not installed"
        exit 1
    fi
    
    # Check if we're in the right directory
    if [[ ! -f "$PROJECT_ROOT/docker-compose.yml" ]]; then
        log "ERROR" "Not in TrakBridge project directory"
        exit 1
    fi
    
    log "INFO" "Prerequisites check passed"
}

setup_environment() {
    local env="$1"
    
    log "INFO" "Setting up environment: $env"
    
    case "$env" in
        "development")
            COMPOSE_FILE="docker-compose-dev.yml"
            PROFILES="${PROFILES:-postgres}"
            ;;
        "staging")
            COMPOSE_FILE="docker-compose.staging.yml"
            PROFILES="${PROFILES:-postgres,nginx}"
            ;;
        "feature")
            COMPOSE_FILE="docker-compose-dev.yml"
            PROFILES="${PROFILES:-postgres}"
            
            # Feature branch deployments require branch name and port
            if [[ -z "$BRANCH_NAME" ]]; then
                log "ERROR" "Feature environment requires --branch parameter"
                exit 1
            fi
            
            if [[ -z "$APP_PORT" ]]; then
                log "ERROR" "Feature environment requires --port parameter"
                exit 1
            fi
            
            # Set unique compose project name for feature branch
            export COMPOSE_PROJECT_NAME="trakbridge-$BRANCH_NAME"
            export APP_PORT="$APP_PORT"
            
            log "INFO" "Feature branch: $BRANCH_NAME"
            log "INFO" "Application port: $APP_PORT"
            log "INFO" "Compose project: $COMPOSE_PROJECT_NAME"
            ;;
        "production")
            log "ERROR" "Production deployment should use Docker Hub images, not local builds"
            log "INFO" "For production, pull images from: emfoursolutions/trakbridge:latest"
            exit 1
            ;;
        *)
            log "ERROR" "Unknown environment: $env"
            exit 1
            ;;
    esac
    
    # Set compose command
    if command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        COMPOSE_CMD="docker compose"
    fi
    
    log "DEBUG" "Using compose file: $COMPOSE_FILE"
    log "DEBUG" "Using profiles: $PROFILES"
}

create_secrets() {
    local env="$1"
    local secrets_dir
    
    # Handle feature branch environments
    if [[ "$env" == "feature" ]]; then
        # For feature branches, use a shared secrets directory or create minimal secrets
        secrets_dir="$PROJECT_ROOT/secrets/feature"
        log "INFO" "Creating secrets for feature environment: $secrets_dir"
    else
        secrets_dir="$PROJECT_ROOT/secrets/$env"
        log "INFO" "Creating secrets for environment: $env"
    fi
    
    mkdir -p "$secrets_dir"
    
    # Generate secrets if they don't exist
    if [[ ! -f "$secrets_dir/db_password" ]]; then
        log "INFO" "Generating database password"
        openssl rand -base64 32 > "$secrets_dir/db_password"
        chmod 600 "$secrets_dir/db_password"
    fi
    
    if [[ ! -f "$secrets_dir/secret_key" ]]; then
        log "INFO" "Generating Flask secret key"
        openssl rand -hex 32 > "$secrets_dir/secret_key"
        chmod 600 "$secrets_dir/secret_key"
    fi
    
    if [[ ! -f "$secrets_dir/tb_master_key" ]]; then
        log "INFO" "Generating TrakBridge master key"
        openssl rand -hex 32 > "$secrets_dir/tb_master_key"
        chmod 600 "$secrets_dir/tb_master_key"
    fi
    
    # Create optional secrets with defaults if they don't exist
    if [[ ! -f "$secrets_dir/ldap_bind_password" ]]; then
        log "INFO" "Creating default LDAP bind password"
        echo "default-ldap-password" > "$secrets_dir/ldap_bind_password"
        chmod 600 "$secrets_dir/ldap_bind_password"
    fi
    
    if [[ ! -f "$secrets_dir/oidc_client_secret" ]]; then
        log "INFO" "Creating default OIDC client secret"
        echo "default-oidc-secret" > "$secrets_dir/oidc_client_secret"
        chmod 600 "$secrets_dir/oidc_client_secret"
    fi
    
    # Set environment variables for Docker Compose
    export DB_PASSWORD_FILE="$secrets_dir/db_password"
    export SECRET_KEY_FILE="$secrets_dir/secret_key"
    export TB_MASTER_KEY_FILE="$secrets_dir/tb_master_key"
    export LDAP_BIND_PASSWORD_FILE="$secrets_dir/ldap_bind_password"
    export OIDC_CLIENT_SECRET_FILE="$secrets_dir/oidc_client_secret"
    
    log "INFO" "Secrets created successfully"
}

prepare_directories() {
    local env="$1"
    
    log "INFO" "Preparing directories for environment: $env"
    
    # Create necessary directories
    mkdir -p "$PROJECT_ROOT/logs/$env"
    mkdir -p "$PROJECT_ROOT/data/$env"
    mkdir -p "$PROJECT_ROOT/config/$env"
    mkdir -p "$PROJECT_ROOT/backups/$env"
    
    # Set permissions
    chmod 755 "$PROJECT_ROOT/logs/$env"
    chmod 755 "$PROJECT_ROOT/data/$env"
    chmod 755 "$PROJECT_ROOT/config/$env"
    chmod 755 "$PROJECT_ROOT/backups/$env"
    
    log "INFO" "Directories prepared successfully"
}

build_image() {
    local env="$1"
    
    log "INFO" "Building Docker image for environment: $env"
    
    local build_target="production"
    local build_env="production"
    
    if [[ "$env" == "development" ]]; then
        build_env="development"
    fi
    
    docker build \
        --target "$build_target" \
        --build-arg BUILD_ENV="$build_env" \
        --tag "trakbridge:$env-latest" \
        "$PROJECT_ROOT"
    
    log "INFO" "Docker image built successfully"
}

deploy_services() {
    local env="$1"
    
    log "INFO" "Deploying services for environment: $env"
    
    cd "$PROJECT_ROOT"
    
    # Set environment variables for docker-compose
    export APP_VERSION="$env-latest"
    export COMPOSE_FILE="$COMPOSE_FILE"
    
    # Set image tag for pre-built images
    if [[ "$USE_PREBUILT" == "true" ]]; then
        # For feature branches, use the branch tag
        if [[ "$env" == "feature" && -n "$BRANCH_NAME" ]]; then
            export IMAGE_TAG="$BRANCH_NAME"
            log "INFO" "Using pre-built image tag: $IMAGE_TAG"
        else
            export IMAGE_TAG="$env"
            log "INFO" "Using pre-built image tag: $IMAGE_TAG"
        fi
    else
        export IMAGE_TAG="$env-latest"
    fi
    
    # Build profiles argument
    local profiles_arg=""
    if [[ -n "$PROFILES" ]]; then
        IFS=',' read -ra PROFILE_ARRAY <<< "$PROFILES"
        for profile in "${PROFILE_ARRAY[@]}"; do
            profiles_arg="$profiles_arg --profile $profile"
        done
    fi
    
    # Deploy services
    log "INFO" "Starting services with profiles: $PROFILES"
    $COMPOSE_CMD -f "$COMPOSE_FILE" $profiles_arg up -d
    
    log "INFO" "Services deployed successfully"
}

wait_for_health() {
    local timeout="$1"
    local port="${APP_PORT:-5000}"
    local url="http://localhost:${port}/api/health"
    
    if [[ "$ENVIRONMENT" == "staging" ]] && [[ "$PROFILES" == *"nginx"* ]]; then
        url="http://localhost/api/health"
    fi
    
    log "INFO" "Waiting for application to be healthy..."
    log "DEBUG" "Health check URL: $url"
    
    local elapsed=0
    local interval=5
    
    while [[ $elapsed -lt $timeout ]]; do
        if curl -f -s "$url" > /dev/null 2>&1; then
            log "INFO" "Application is healthy!"
            return 0
        fi
        
        sleep $interval
        elapsed=$((elapsed + interval))
        
        if [[ $((elapsed % 30)) -eq 0 ]]; then
            log "DEBUG" "Still waiting for health check... ($elapsed/${timeout}s)"
        fi
    done
    
    log "ERROR" "Health check timed out after ${timeout}s"
    return 1
}

run_post_deployment_tests() {
    local env="$1"
    
    log "INFO" "Running post-deployment tests for environment: $env"
    
    local port="${APP_PORT:-5000}"
    local base_url="http://localhost:${port}"
    if [[ "$env" == "staging" ]] && [[ "$PROFILES" == *"nginx"* ]]; then
        base_url="http://localhost"
    fi
    
    # Test basic endpoints
    log "DEBUG" "Testing basic health endpoint"
    if ! curl -f -s "$base_url/api/health" > /dev/null; then
        log "ERROR" "Basic health check failed"
        return 1
    fi
    
    log "DEBUG" "Testing detailed health endpoint"
    if ! curl -f -s "$base_url/api/health/detailed" > /dev/null; then
        log "WARN" "Detailed health check failed (this might be expected)"
    fi
    
    # Test application response time
    log "DEBUG" "Testing application response time"
    local response_time=$(curl -o /dev/null -s -w '%{time_total}' "$base_url/")
    log "INFO" "Application response time: ${response_time}s"
    
    log "INFO" "Post-deployment tests completed successfully"
}

show_deployment_status() {
    log "INFO" "Current deployment status:"
    
    cd "$PROJECT_ROOT"
    
    if [[ -f "$COMPOSE_FILE" ]]; then
        $COMPOSE_CMD -f "$COMPOSE_FILE" ps
        echo ""
        log "INFO" "Service logs (last 10 lines):"
        $COMPOSE_CMD -f "$COMPOSE_FILE" logs --tail=10
    else
        log "WARN" "No active deployment found"
    fi
}

stop_services() {
    log "INFO" "Stopping services..."
    
    cd "$PROJECT_ROOT"
    
    if [[ -f "$COMPOSE_FILE" ]]; then
        $COMPOSE_CMD -f "$COMPOSE_FILE" down
        log "INFO" "Services stopped successfully"
    else
        log "WARN" "No services to stop"
    fi
}

restart_services() {
    log "INFO" "Restarting services..."
    
    stop_services
    sleep 5
    deploy_services "$ENVIRONMENT"
    
    if wait_for_health "$HEALTH_CHECK_TIMEOUT"; then
        run_post_deployment_tests "$ENVIRONMENT"
        log "INFO" "Services restarted successfully"
    else
        log "ERROR" "Service restart failed health check"
        return 1
    fi
}

backup_current_deployment() {
    local env="$1"
    local backup_dir="$PROJECT_ROOT/backups/$env/deployments"
    local timestamp=$(date +%Y%m%d-%H%M%S)
    
    log "INFO" "Creating deployment backup..."
    
    mkdir -p "$backup_dir"
    
    # Backup current compose file
    if [[ -f "$PROJECT_ROOT/$COMPOSE_FILE" ]]; then
        cp "$PROJECT_ROOT/$COMPOSE_FILE" "$backup_dir/docker-compose-$timestamp.yml"
    fi
    
    # Backup current environment state
    cd "$PROJECT_ROOT"
    $COMPOSE_CMD -f "$COMPOSE_FILE" config > "$backup_dir/compose-config-$timestamp.yml" 2>/dev/null || true
    
    log "INFO" "Deployment backup created: $backup_dir"
}

rollback_deployment() {
    log "INFO" "Rolling back deployment..."
    
    local env="$ENVIRONMENT"
    local backup_dir="$PROJECT_ROOT/backups/$env/deployments"
    
    if [[ ! -d "$backup_dir" ]]; then
        log "ERROR" "No backup directory found for rollback"
        return 1
    fi
    
    # Find the most recent backup
    local latest_backup=$(find "$backup_dir" -name "docker-compose-*.yml" | sort -r | head -n1)
    
    if [[ -z "$latest_backup" ]]; then
        log "ERROR" "No backup files found for rollback"
        return 1
    fi
    
    log "INFO" "Rolling back to: $(basename "$latest_backup")"
    
    # Stop current services
    stop_services
    
    # Restore backup
    cp "$latest_backup" "$PROJECT_ROOT/$COMPOSE_FILE"
    
    # Restart with backup configuration
    deploy_services "$env"
    
    if wait_for_health "$HEALTH_CHECK_TIMEOUT"; then
        log "INFO" "Rollback completed successfully"
    else
        log "ERROR" "Rollback failed health check"
        return 1
    fi
}

# =============================================================================
# Main Deployment Function
# =============================================================================

main() {
    log "INFO" "Starting TrakBridge deployment script"
    log "INFO" "Log file: $LOG_FILE"
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -e|--environment)
                ENVIRONMENT="$2"
                shift 2
                ;;
            -a|--action)
                ACTION="$2"
                shift 2
                ;;
            -p|--profiles)
                PROFILES="$2"
                shift 2
                ;;
            -t|--timeout)
                HEALTH_CHECK_TIMEOUT="$2"
                shift 2
                ;;
            -f|--compose-file)
                COMPOSE_FILE="$2"
                shift 2
                ;;
            --port)
                APP_PORT="$2"
                shift 2
                ;;
            --branch)
                BRANCH_NAME="$2"
                shift 2
                ;;
            --use-prebuilt)
                USE_PREBUILT=true
                shift
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            *)
                log "ERROR" "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # Execute action
    case "$ACTION" in
        "deploy")
            check_prerequisites
            setup_environment "$ENVIRONMENT"
            create_secrets "$ENVIRONMENT"
            prepare_directories "$ENVIRONMENT"
            backup_current_deployment "$ENVIRONMENT" || true
            
            # Only build if not using pre-built images
            if [[ "$USE_PREBUILT" != "true" ]]; then
                build_image "$ENVIRONMENT"
            else
                log "INFO" "Skipping image build, using pre-built images"
            fi
            
            deploy_services "$ENVIRONMENT"
            
            if wait_for_health "$HEALTH_CHECK_TIMEOUT"; then
                run_post_deployment_tests "$ENVIRONMENT"
                log "INFO" "Deployment completed successfully! 🎉"
                
                # Show access information
                local port="${APP_PORT:-5000}"
                local url="http://localhost:${port}"
                if [[ "$ENVIRONMENT" == "staging" ]] && [[ "$PROFILES" == *"nginx"* ]]; then
                    url="http://localhost"
                fi
                
                log "INFO" "Application URL: $url"
                log "INFO" "Default login: admin / TrakBridge-Setup-2025!"
            else
                log "ERROR" "Deployment failed health check"
                if [[ "$ROLLBACK_ON_FAILURE" == "true" ]]; then
                    log "INFO" "Attempting automatic rollback..."
                    rollback_deployment || log "ERROR" "Rollback also failed"
                fi
                exit 1
            fi
            ;;
        "stop")
            setup_environment "$ENVIRONMENT"
            stop_services
            ;;
        "restart")
            setup_environment "$ENVIRONMENT"
            restart_services
            ;;
        "status")
            setup_environment "$ENVIRONMENT"
            show_deployment_status
            ;;
        "rollback")
            setup_environment "$ENVIRONMENT"
            rollback_deployment
            ;;
        *)
            log "ERROR" "Unknown action: $ACTION"
            show_usage
            exit 1
            ;;
    esac
    
    log "INFO" "Script completed successfully"
}

# =============================================================================
# Error Handling
# =============================================================================

trap 'log "ERROR" "Script interrupted"; exit 1' INT TERM
trap 'log "ERROR" "Script failed on line $LINENO"; exit 1' ERR

# =============================================================================
# Script Entry Point
# =============================================================================

main "$@"