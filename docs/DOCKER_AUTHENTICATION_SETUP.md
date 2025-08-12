# Docker Authentication Setup Guide

This guide explains how to configure authentication for TrakBridge when running with Docker Compose.

## Overview

TrakBridge supports three authentication methods:
1. **Local Authentication** - Database-stored user credentials
2. **LDAP/Active Directory** - Enterprise directory integration
3. **OIDC/SSO** - Single Sign-On with OpenID Connect providers

All docker-compose configurations now include comprehensive authentication environment variables with sensible defaults.

## Environment Variables

### LDAP Authentication

```bash
# Enable/disable LDAP authentication
LDAP_ENABLED=true

# LDAP server configuration
LDAP_SERVER=ldap://your-ad-server.company.com
LDAP_PORT=389
LDAP_USE_SSL=false
LDAP_USE_TLS=true
LDAP_VALIDATE_CERT=true

# Service account for LDAP binding
LDAP_BIND_DN="CN=trakbridge,OU=Service Accounts,DC=company,DC=com"

# User search configuration
LDAP_USER_SEARCH_BASE="OU=Users,DC=company,DC=com"
LDAP_USER_SEARCH_FILTER="(sAMAccountName={username})"

# Group search configuration
LDAP_GROUP_SEARCH_BASE="OU=Groups,DC=company,DC=com"
LDAP_GROUP_SEARCH_FILTER="(member={user_dn})"

# Role mapping
LDAP_ADMIN_GROUP="CN=TrakBridge-Admins,OU=Groups,DC=company,DC=com"
LDAP_OPERATOR_GROUP="CN=TrakBridge-Operators,OU=Groups,DC=company,DC=com"
LDAP_USER_GROUP="CN=TrakBridge-Users,OU=Groups,DC=company,DC=com"
LDAP_DEFAULT_ROLE=user

# Connection timeouts
LDAP_CONNECTION_TIMEOUT=10
LDAP_RESPONSE_TIMEOUT=30
```

### OIDC/SSO Authentication

```bash
# Enable/disable OIDC authentication
OIDC_ENABLED=false

# OIDC provider configuration
OIDC_ISSUER=https://your-identity-provider.com
OIDC_CLIENT_ID=trakbridge-client
OIDC_REDIRECT_URI=https://trakbridge.company.com/auth/oidc/callback

# JWT validation settings
OIDC_VERIFY_SIGNATURE=true
OIDC_VERIFY_AUDIENCE=true
OIDC_VERIFY_ISSUER=true

# Role mapping from OIDC groups
OIDC_ADMIN_GROUP=trakbridge-admins
OIDC_OPERATOR_GROUP=trakbridge-operators
OIDC_USER_GROUP=trakbridge-users
OIDC_DEFAULT_ROLE=user
```

### Local Authentication

```bash
# Enable/disable local authentication
LOCAL_AUTH_ENABLED=true

# Password policy settings
PASSWORD_MIN_LENGTH=12
PASSWORD_REQUIRE_UPPERCASE=true
PASSWORD_REQUIRE_LOWERCASE=true
PASSWORD_REQUIRE_NUMBERS=true
PASSWORD_REQUIRE_SPECIAL=true
PASSWORD_MAX_AGE_DAYS=90
```

### Session Configuration

```bash
# Session management
SESSION_LIFETIME_HOURS=8
SESSION_CLEANUP_INTERVAL=60
SESSION_SECURE_COOKIES=true
SESSION_COOKIE_DOMAIN=""
SESSION_COOKIE_PATH="/"
```

## Secrets Management

Authentication secrets are managed through Docker secrets:

### Required Secret Files

1. **LDAP Bind Password**: `./secrets/ldap_bind_password`
2. **OIDC Client Secret**: `./secrets/oidc_client_secret`

### Creating Secret Files

```bash
# Create secrets directory
mkdir -p secrets

# LDAP bind password
echo "your-ldap-service-account-password" > secrets/ldap_bind_password

# OIDC client secret
echo "your-oidc-client-secret" > secrets/oidc_client_secret

# Set secure permissions
chmod 600 secrets/*
```

For staging environment:
```bash
mkdir -p secrets/staging
echo "staging-ldap-password" > secrets/staging/ldap_bind_password
echo "staging-oidc-secret" > secrets/staging/oidc_client_secret
chmod 600 secrets/staging/*
```

## Environment-Specific Configurations

### Development Environment

The development configuration (`docker-compose-dev.yml`) includes:
- Relaxed password policies (minimum 4 characters)
- Disabled SSL/TLS validation for testing
- HTTP redirect URIs for local development
- Disabled secure cookies for HTTP testing

```bash
# Development-specific overrides
PASSWORD_MIN_LENGTH=4
PASSWORD_REQUIRE_UPPERCASE=false
PASSWORD_REQUIRE_LOWERCASE=false
PASSWORD_REQUIRE_NUMBERS=false
PASSWORD_REQUIRE_SPECIAL=false
LDAP_USE_TLS=false
LDAP_VALIDATE_CERT=false
SESSION_SECURE_COOKIES=false
OIDC_REDIRECT_URI=http://localhost:5000/auth/oidc/callback
```

### Staging Environment

The staging configuration (`docker-compose.staging.yml`) includes:
- Production-like security settings
- Enhanced password policies
- SSL/TLS enabled and validated
- Staging-specific redirect URIs

```bash
# Staging-specific settings
PASSWORD_MIN_LENGTH=10
LDAP_USE_TLS=true
LDAP_VALIDATE_CERT=true
SESSION_SECURE_COOKIES=true
SESSION_COOKIE_DOMAIN=staging.trakbridge.local
OIDC_REDIRECT_URI=https://staging.trakbridge.local/auth/oidc/callback
```

### Production Environment

The production configuration (`docker-compose.yml`) includes:
- Maximum security settings
- Strong password policies (12+ characters)
- Full SSL/TLS validation
- Production redirect URIs

```bash
# Production security settings
PASSWORD_MIN_LENGTH=12
PASSWORD_REQUIRE_SPECIAL=true
PASSWORD_MAX_AGE_DAYS=90
LDAP_USE_TLS=true
LDAP_VALIDATE_CERT=true
SESSION_SECURE_COOKIES=true
```

## Usage Examples

### Development with LDAP

```bash
# Update docker-compose.yml with development settings
# Edit the x-environment section:
#   LDAP_ENABLED: "true"
#   LDAP_SERVER: "ldap://dev-dc.company.com"
#   LDAP_BIND_DN: "CN=dev-trakbridge,OU=Service Accounts,DC=dev,DC=company,DC=com"
#   LDAP_USER_SEARCH_BASE: "OU=Users,DC=dev,DC=company,DC=com"
#   LDAP_USE_TLS: "false"  # Relaxed for development
#   LDAP_VALIDATE_CERT: "false"  # Relaxed for development

# Create LDAP secret
mkdir -p secrets
echo "dev-service-password" > secrets/ldap_bind_password
chmod 600 secrets/ldap_bind_password

# Start development environment
docker-compose -f docker-compose-dev.yml --profile postgres up -d
```

### Production with Full Authentication

```bash
# Set production environment variables
export LDAP_ENABLED=true
export LDAP_SERVER=ldaps://dc01.company.com
export LDAP_PORT=636
export LDAP_USE_SSL=true
export OIDC_ENABLED=true
export OIDC_ISSUER=https://sso.company.com

# Create production secrets
echo "production-ldap-password" > secrets/ldap_bind_password
echo "production-oidc-secret" > secrets/oidc_client_secret
chmod 600 secrets/*

# Deploy production stack
docker-compose --profile postgres --profile nginx up -d
```

### Staging Environment

```bash
# Create staging secrets
mkdir -p secrets/staging
echo "staging-ldap-password" > secrets/staging/ldap_bind_password
echo "staging-oidc-secret" > secrets/staging/oidc_client_secret

# Set staging variables
export LDAP_ENABLED=true
export LDAP_SERVER=ldap://staging-dc.company.com
export OIDC_ENABLED=true
export STAGING_URL=https://staging.trakbridge.company.com

# Deploy staging environment
docker-compose -f docker-compose.staging.yml --profile postgres --profile nginx up -d
```

## Security Considerations

### Production Deployment

1. **Use strong passwords**: Configure appropriate password policies
2. **Enable SSL/TLS**: Always use encrypted LDAP connections in production
3. **Validate certificates**: Enable certificate validation for security
4. **Secure cookies**: Use secure cookies with HTTPS
5. **Limit permissions**: Use least-privilege service accounts
6. **Regular rotation**: Rotate secrets regularly

### Network Security

1. **Firewall rules**: Restrict LDAP/OIDC network access
2. **VPN/Private networks**: Use private networks for directory access
3. **Certificate management**: Properly manage SSL certificates
4. **Monitoring**: Monitor authentication attempts and failures

## Troubleshooting

### LDAP Issues

```bash
# Test LDAP connectivity
docker exec -it trakbridge-container ldapsearch -H $LDAP_SERVER -D "$LDAP_BIND_DN" -W -b "$LDAP_USER_SEARCH_BASE" "(sAMAccountName=testuser)"

# Check LDAP configuration
docker exec -it trakbridge-container python -c "
from config.authentication_loader import load_authentication_config
config = load_authentication_config('production')
print('LDAP Config:', config['authentication']['providers']['ldap'])
"
```

### Secret Issues

```bash
# Verify secret files exist and have correct permissions
ls -la secrets/
cat secrets/ldap_bind_password  # Should show password content

# Check Docker secret mounts
docker exec -it trakbridge-container ls -la /run/secrets/
```

### Configuration Validation

```bash
# Validate authentication configuration
docker exec -it trakbridge-container python -c "
from services.auth.auth_manager import AuthenticationManager
from config.authentication_loader import load_authentication_config
config = load_authentication_config()
auth_manager = AuthenticationManager(config['authentication'])
print('Authentication providers:', list(auth_manager.providers.keys()))
"
```

## References

- [LDAP Docker Secrets Guide](./LDAP_DOCKER_SECRETS.md)
- [Authentication Configuration](../config/settings/authentication.yaml)
- [Production Deployment Guide](./INSTALLATION.md)