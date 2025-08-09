# TrakBridge Authentication System

## Overview

TrakBridge implements a comprehensive, multi-provider authentication system designed for enterprise environments. The system supports three authentication methods with a hierarchical fallback strategy:

1. **OIDC (OpenID Connect)** - Primary authentication for modern enterprise SSO
2. **LDAP/LDAPS** - Active Directory integration for traditional enterprise environments  
3. **Local Database** - Failsafe authentication stored locally

## Architecture

### Core Components

#### 1. Authentication Manager (`services/auth/auth_manager.py`)
Central orchestrator that coordinates between different authentication providers and manages user sessions.

```python
from services.auth import AuthenticationManager

auth_manager = AuthenticationManager()
user = auth_manager.authenticate('username', 'password', 'local')
```

#### 2. Authentication Providers
- **LocalAuthProvider** - Database-backed authentication with bcrypt password hashing
- **LDAPAuthProvider** - LDAP/Active Directory integration with secure connection support
- **OIDCAuthProvider** - OpenID Connect for modern SSO integration

#### 3. Database Models
- **User** - User account information with role-based permissions
- **UserSession** - Session management with automatic expiration

#### 4. Authentication Decorators
Route protection decorators for Flask applications:
- `@require_auth` - Basic authentication requirement
- `@require_role(role)` - Role-based access control
- `@require_permission(resource, action)` - Fine-grained permission checking
- `@admin_required` - Administrative access only
- `@operator_required` - Operator level or higher

## User Roles and Permissions

### Role Hierarchy
1. **User** - Basic read access to assigned resources
2. **Operator** - Can manage streams and TAK servers
3. **Admin** - Full system administration capabilities

### Permission Model
Permissions are resource-based with actions:
- **Resources**: `streams`, `tak_servers`, `admin`, `api`, `profile`
- **Actions**: `read`, `write`, `delete`, `admin`

### Permission Matrix
| Role | Streams | TAK Servers | Admin | API | Profile |
|------|---------|-------------|-------|-----|---------|
| User | read | read | - | read | read/write |
| Operator | read/write | read/write | - | read | read/write |
| Admin | all | all | all | all | all |

## Configuration

### Docker Compose Configuration (Recommended)

For Docker deployments, authentication is configured directly in the docker-compose.yml file using environment variables. This approach keeps all configuration in one location and eliminates the need for external configuration files.

#### Authentication Environment Variables

Edit the `x-environment` section in your docker-compose.yml file to configure authentication:

```yaml
# docker-compose.yml
x-environment: &common-environment
  # Session Configuration
  SESSION_LIFETIME_HOURS: "8"
  SESSION_CLEANUP_INTERVAL: "60"
  SESSION_SECURE_COOKIES: "true"
  
  # Local Authentication (always enabled as fallback)
  LOCAL_AUTH_ENABLED: "true"
  PASSWORD_MIN_LENGTH: "12"
  PASSWORD_REQUIRE_UPPERCASE: "true"
  PASSWORD_REQUIRE_LOWERCASE: "true"
  PASSWORD_REQUIRE_NUMBERS: "true"
  PASSWORD_REQUIRE_SPECIAL: "true"
  PASSWORD_MAX_AGE_DAYS: "90"
  
  # LDAP Authentication (set LDAP_ENABLED to "true" to enable)
  LDAP_ENABLED: "false"
  LDAP_SERVER: "ldap://your-ad-server.company.com"
  LDAP_PORT: "389"
  LDAP_USE_SSL: "false"
  LDAP_USE_TLS: "true"
  LDAP_VALIDATE_CERT: "true"
  LDAP_BIND_DN: "CN=trakbridge,OU=Service Accounts,DC=company,DC=com"
  LDAP_USER_SEARCH_BASE: "OU=Users,DC=company,DC=com"
  LDAP_USER_SEARCH_FILTER: "(sAMAccountName={username})"
  LDAP_GROUP_SEARCH_BASE: "OU=Groups,DC=company,DC=com"
  LDAP_GROUP_SEARCH_FILTER: "(member={user_dn})"
  LDAP_ADMIN_GROUP: "CN=TrakBridge-Admins,OU=Groups,DC=company,DC=com"
  LDAP_OPERATOR_GROUP: "CN=TrakBridge-Operators,OU=Groups,DC=company,DC=com"
  LDAP_USER_GROUP: "CN=TrakBridge-Users,OU=Groups,DC=company,DC=com"
  LDAP_DEFAULT_ROLE: "user"
  
  # OIDC/SSO Authentication (set OIDC_ENABLED to "true" to enable)
  OIDC_ENABLED: "false"
  OIDC_ISSUER: "https://your-identity-provider.com"
  OIDC_CLIENT_ID: "trakbridge-client"
  OIDC_REDIRECT_URI: "https://trakbridge.company.com/auth/oidc/callback"
  OIDC_VERIFY_SIGNATURE: "true"
  OIDC_VERIFY_AUDIENCE: "true"
  OIDC_VERIFY_ISSUER: "true"
  OIDC_ADMIN_GROUP: "trakbridge-admins"
  OIDC_OPERATOR_GROUP: "trakbridge-operators"
  OIDC_USER_GROUP: "trakbridge-users"
  OIDC_DEFAULT_ROLE: "user"
```

#### Docker Secrets for Sensitive Data

Sensitive credentials are managed through Docker secrets rather than environment variables:

```bash
# Create secrets directory
mkdir -p secrets

# LDAP bind password (if using LDAP)
echo "your-ldap-service-account-password" > secrets/ldap_bind_password

# OIDC client secret (if using OIDC)
echo "your-oidc-client-secret" > secrets/oidc_client_secret

# Set secure permissions
chmod 600 secrets/*
```

### External Configuration Files (Plugin Development Only)

External configuration files in the `./config` directory are primarily used for external plugin development and advanced customizations. For standard Docker deployments, use the environment variable approach above.

### Authentication Provider Priority

TrakBridge attempts authentication in this order:
1. **OIDC** (if enabled) - Modern enterprise SSO
2. **LDAP** (if enabled) - Active Directory integration
3. **Local** (always enabled) - Database fallback

The first successful authentication method is used. Local authentication always serves as a fallback to ensure system access.

### Security Features

#### Docker Secrets Protection
Sensitive credentials are stored in Docker secrets files rather than environment variables:
- **LDAP passwords**: Stored in `secrets/ldap_bind_password`
- **OIDC secrets**: Stored in `secrets/oidc_client_secret`
- **Encryption keys**: Stored in `secrets/tb_master_key`

#### Environment Variable Security
- Configuration values are set directly in docker-compose.yml
- No external .env files required
- Sensitive data isolated in secrets files with proper permissions
- All authentication events logged for audit trails

## Setup Instructions

### 1. Basic Local Authentication Setup

1. **Local authentication is enabled by default** in docker-compose.yml:
```yaml
# Already configured in docker-compose.yml
LOCAL_AUTH_ENABLED: "true"
PASSWORD_MIN_LENGTH: "12"
PASSWORD_REQUIRE_UPPERCASE: "true"
# ... other password policy settings
```

2. **Initial admin user is created automatically**:
   - Default credentials: `admin` / `TrakBridge-Setup-2025!`
   - Password change required on first login
   - Bootstrap service handles this automatically

3. **Customize password policy** by editing the environment variables in docker-compose.yml:
   - `PASSWORD_MIN_LENGTH`: Minimum password length
   - `PASSWORD_REQUIRE_UPPERCASE`: Require uppercase letters
   - `PASSWORD_REQUIRE_LOWERCASE`: Require lowercase letters  
   - `PASSWORD_REQUIRE_NUMBERS`: Require numbers
   - `PASSWORD_REQUIRE_SPECIAL`: Require special characters
   - `PASSWORD_MAX_AGE_DAYS`: Password expiration in days

### 2. LDAP/Active Directory Setup

1. **Configure LDAP settings** in docker-compose.yml environment section:
```yaml
# Edit these values in docker-compose.yml
LDAP_ENABLED: "true"
LDAP_SERVER: "ldap://your-ad-server.company.com"
LDAP_PORT: "389"
LDAP_USE_TLS: "true"
LDAP_VALIDATE_CERT: "true"
LDAP_BIND_DN: "CN=trakbridge,OU=Service Accounts,DC=company,DC=com"
LDAP_USER_SEARCH_BASE: "OU=Users,DC=company,DC=com"
LDAP_USER_SEARCH_FILTER: "(sAMAccountName={username})"
LDAP_GROUP_SEARCH_BASE: "OU=Groups,DC=company,DC=com"
LDAP_GROUP_SEARCH_FILTER: "(member={user_dn})"
```

2. **Set LDAP password** using Docker secrets:
```bash
# Create LDAP password secret
mkdir -p secrets
echo "your-ldap-service-account-password" > secrets/ldap_bind_password
chmod 600 secrets/ldap_bind_password
```

3. **Configure group to role mappings** in docker-compose.yml:
```yaml
LDAP_ADMIN_GROUP: "CN=TrakBridge-Admins,OU=Groups,DC=company,DC=com"
LDAP_OPERATOR_GROUP: "CN=TrakBridge-Operators,OU=Groups,DC=company,DC=com"
LDAP_USER_GROUP: "CN=TrakBridge-Users,OU=Groups,DC=company,DC=com"
LDAP_DEFAULT_ROLE: "user"
```

4. **Restart application** to apply LDAP configuration:
```bash
docker-compose restart
```

5. **Test LDAP connection**: Verify through application logs or attempt login with LDAP credentials

### 3. OIDC/SSO Setup

1. **Register TrakBridge** with your identity provider (Azure AD, Okta, etc.)
   - Set redirect URI to: `https://your-domain.com/auth/oidc/callback`
   - Note the client ID and client secret

2. **Configure OIDC settings** in docker-compose.yml environment section:
```yaml
# Edit these values in docker-compose.yml
OIDC_ENABLED: "true"
OIDC_ISSUER: "https://login.microsoftonline.com/your-tenant-id/v2.0"
OIDC_CLIENT_ID: "your-application-client-id"
OIDC_REDIRECT_URI: "https://trakbridge.company.com/auth/oidc/callback"
OIDC_VERIFY_SIGNATURE: "true"
OIDC_VERIFY_AUDIENCE: "true"
OIDC_VERIFY_ISSUER: "true"
```

3. **Set OIDC client secret** using Docker secrets:
```bash
# Create OIDC client secret
mkdir -p secrets
echo "your-oidc-client-secret" > secrets/oidc_client_secret
chmod 600 secrets/oidc_client_secret
```

4. **Configure role mappings** for group-based access:
```yaml
OIDC_ADMIN_GROUP: "trakbridge-admins"
OIDC_OPERATOR_GROUP: "trakbridge-operators"
OIDC_USER_GROUP: "trakbridge-users"
OIDC_DEFAULT_ROLE: "user"
```

5. **Restart application** to apply OIDC configuration:
```bash
docker-compose restart
```

6. **Test OIDC flow** by clicking "Sign in with SSO" on the login page

## User Management

### Creating Users

#### Initial Admin User (Automatic)
TrakBridge automatically creates an initial admin user on first startup:
- **Username**: `admin`
- **Password**: `TrakBridge-Setup-2025!`
- **Forced password change**: Required on first login
- **Bootstrap protection**: Only created if no admin users exist

#### Via Web Interface (Recommended)
1. **Login as admin** using the default credentials
2. **Navigate to User Management**: Admin → User Management
3. **Click Create User**
4. **Fill in user details** and assign appropriate role
5. **Set initial password** for local users

**Security Note**: All user management is intentionally restricted to the web interface for enhanced security and audit logging.

### Password Management

#### Local Users
- Users can change passwords via **Profile > Change Password**
- Admins can reset passwords via **User Management**
- Password policies are enforced based on configuration

#### LDAP/OIDC Users
- Password changes must be done through the external system
- TrakBridge will sync user information on next login

## Security Features

### Session Management
- **Secure sessions** with configurable lifetime
- **Automatic cleanup** of expired sessions
- **Session invalidation** on logout or user disable

### Password Security
- **bcrypt hashing** for local passwords
- **Configurable password policies**
- **Password strength validation** with real-time feedback

### Connection Security
- **TLS encryption** for LDAP connections
- **HTTPS enforcement** for OIDC redirects
- **Secure cookie flags** in production

### Audit Logging
All authentication events are logged:
- Login attempts (successful and failed)
- User creation/modification
- Role changes
- Session management events

## Troubleshooting

### Common Issues

#### Configuration Issues
```bash
# Check environment variable configuration in docker-compose.yml
cat docker-compose.yml | grep -A 50 "x-environment"

# Check secrets files exist and have correct permissions
ls -la secrets/

# Check configuration loading in app logs
docker-compose logs | grep -i "authentication.*loaded"

# Restart container to reload configuration
docker-compose restart
```

#### LDAP Connection Failures
```bash
# Check logs for detailed error information
tail -f logs/app.log | grep -i ldap

# Test LDAP connectivity by attempting login through web interface
# Review authentication logs for specific error details
```

#### OIDC Configuration Issues
```bash
# Check issuer discovery
curl https://your-issuer/.well-known/openid_configuration

# Test OIDC flow by attempting login through web interface
# Review authentication logs for configuration errors
tail -f logs/app.log | grep -i oidc
```

#### Permission Denied Errors
1. Check user role assignment in **User Management**
2. Verify role mappings in auth configuration
3. Check decorator usage on protected routes

### Debug Mode
Enable debug logging for authentication:
```yaml
logging:
  level: DEBUG
  loggers:
    services.auth: DEBUG
```

### Health Checks
Monitor authentication system health:
```bash
# Check authentication system status
curl http://localhost:8080/api/health/detailed | jq '.checks.authentication'

# Monitor authentication logs
tail -f logs/app.log | grep -i auth
```

## Migration Guide

### From No Authentication
1. Deploy authentication system with local provider enabled
2. Create initial admin user
3. Configure additional providers as needed
4. Gradually migrate users to new system

### Adding LDAP to Existing Local Setup
1. Configure LDAP in auth.yaml
2. Test LDAP connectivity
3. Enable LDAP provider
4. Users can now login with either local or LDAP credentials

### Adding OIDC to Existing Setup
1. Register application with identity provider
2. Configure OIDC in auth.yaml
3. Test OIDC flow
4. Enable OIDC provider as primary authentication method

## API Authentication

### Session-Based API Access
API endpoints support session-based authentication for web applications:
```javascript
// Login first
fetch('/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'user', password: 'pass' })
});

// Then access API with session cookie
fetch('/api/streams/status');
```

### Future: API Key Authentication
API key authentication is planned for machine-to-machine access:
```bash
curl -H "X-API-Key: your-api-key" http://localhost:8080/api/streams/status
```

## Best Practices

### Security
1. **Use HTTPS** in production environments
2. **Set strong SECRET_KEY** for Flask sessions
3. **Enable TLS** for LDAP connections
4. **Regularly rotate** service account passwords
5. **Monitor logs** for suspicious authentication activity

### Configuration
1. **Use persistent configuration** for Docker deployments
2. **Use environment variables** for secrets
3. **Validate configuration** after changes with CLI tools
4. **Backup configuration** before making changes
5. **Start with local authentication** for initial setup
6. **Test each provider** thoroughly before enabling
7. **Document role mappings** for your organization
8. **Implement backup admin access** for emergencies

### Operational
1. **Monitor session counts** and cleanup frequency
2. **Review user roles** regularly
3. **Test authentication** after configuration changes
4. **Backup authentication configuration** before changes
5. **Plan for provider outages** with fallback options

## Support

For authentication system support:
1. Check application logs in `logs/app.log`
2. Use CLI tools for diagnostics
3. Review configuration against this documentation
4. Test individual components in isolation
5. Refer to provider-specific documentation for external systems