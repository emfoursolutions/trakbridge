#!/bin/bash
# =============================================================================
# init-secrets.sh - One-time secret bootstrap script
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Configurable variables
# -----------------------------------------------------------------------------
ENVIRONMENT="${1:-development}"  # default to development
FORCE=false

SECRETS_DIR="./secrets"
mkdir -p "$SECRETS_DIR"

# -----------------------------------------------------------------------------
# Colors
# -----------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }

# -----------------------------------------------------------------------------
# Argument parsing
# -----------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -e|--env)
      ENVIRONMENT="$2"
      shift 2
      ;;
    -f|--force)
      FORCE=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [-e ENV] [-f]"
      echo "  -e, --env     Set environment (development|production|staging)"
      echo "  -f, --force   Overwrite existing secrets"
      echo "  -h, --help    Show this help message"
      exit 0
      ;;
    *)
      err "Unknown argument: $1"
      exit 1
      ;;
  esac
done

info "Bootstrapping secrets for: $ENVIRONMENT"

# -----------------------------------------------------------------------------
# Secret generation logic
# -----------------------------------------------------------------------------
create_secret_if_missing() {
  local name="$1"
  local generator="$2"
  local path="$SECRETS_DIR/$name"

  if [[ "$FORCE" == true || ! -f "$path" ]]; then
    eval "$generator" > "$path"
    chmod 600 "$path"
    info "Generated $path"
  else
    info "Secret exists: $path"
  fi
}

# -----------------------------------------------------------------------------
# Generate environment-appropriate secrets
# -----------------------------------------------------------------------------
if [[ "$ENVIRONMENT" == "development" ]]; then
  create_secret_if_missing "db_password" "echo 'dev-password-123'"
  create_secret_if_missing "secret_key" "echo 'dev-secret-key-$(date +%s)'"
  create_secret_if_missing "tb_master_key" "echo 'dev-master-key-$(date +%s)'"
else
  create_secret_if_missing "db_password" "openssl rand -base64 32"
  create_secret_if_missing "secret_key" "python3 -c 'import secrets; print(secrets.token_urlsafe(64))'"
  create_secret_if_missing "tb_master_key" "python3 -c 'import secrets; print(secrets.token_urlsafe(64))'"
fi

info "✅ All secrets created or already exist in: $SECRETS_DIR"
