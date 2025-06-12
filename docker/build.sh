#!/bin/bash
# =============================================================================
# Build Script
# =============================================================================

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
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

# Default values
ENVIRONMENT="production"
VERSION="latest"
NO_CACHE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -v|--version)
            VERSION="$2"
            shift 2
            ;;
        --no-cache)
            NO_CACHE="--no-cache"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  -e, --env ENV        Environment (development|production) [default: production]"
            echo "  -v, --version VER    Version tag [default: latest]"
            echo "      --no-cache       Build without cache"
            echo "  -h, --help           Show this help"
            echo ""
            echo "Examples:"
            echo "  $0                           # Build production version"
            echo "  $0 -e development           # Build development version"
            echo "  $0 -v v1.0.0                # Build with specific version"
            echo "  $0 -e production --no-cache # Build production without cache"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Determine build target
if [[ "$ENVIRONMENT" == "development" ]]; then
    BUILD_TARGET="development"
else
    BUILD_TARGET="production"
fi

log_info "Building GPS TAK Application"
log_info "Environment: $ENVIRONMENT"
log_info "Build Target: $BUILD_TARGET"
log_info "Version: $VERSION"

# Build the image
log_info "Building Docker image..."
docker build \
    $NO_CACHE \
    --target $BUILD_TARGET \
    --build-arg BUILD_ENV=$ENVIRONMENT \
    -t trakbridge:$VERSION \
    -t trakbridge:latest \
    .

log_info "Build completed successfully!"
log_info "Image tags created:"
log_info "  - trakbridge:$VERSION"
log_info "  - trakbridge:latest"

echo ""
log_info "Next steps:"
log_info "1. Edit docker-compose.yml to configure your database"
log_info "2. Run: docker-compose up -d"
log_info "3. Check logs: docker-compose logs -f"