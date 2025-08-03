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

### Configuration Management

TrakBridge uses a **multi-source configuration system** that supports both bundled defaults and persistent external configuration:

#### Configuration Sources (Priority Order)
1. **External Configuration** (`./config` or `TRAKBRIDGE_CONFIG_DIR`) - Highest priority
2. **Bundled Configuration** (`config/settings/`) - Fallback defaults

#### Docker Configuration Management

For Docker deployments, TrakBridge automatically installs default configuration files to external volumes:

```yaml
# docker-compose.yml
services:
  trakbridge:
    environment:
      TRAKBRIDGE_CONFIG_DIR: "/app/external_config"
      TRAKBRIDGE_CONFIG_AUTO_INSTALL: "true"
      TRAKBRIDGE_CONFIG_UPDATE_MODE: "preserve"
    volumes:
      - ./config:/app/external_config  # Persistent config mount
```

**Update Modes**:
- `preserve` (default) - Keep existing external configs, install missing ones
- `overwrite` - Replace external configs with container defaults
- `merge` - Smart merge (planned future feature)

#### Configuration CLI Management

Use the configuration management CLI for advanced operations:

```bash
# List all configuration files and their sources
python scripts/manage_config.py list

# Install default configurations to external directory
python scripts/manage_config.py install

# Install specific configuration file
python scripts/manage_config.py install --file authentication.yaml

# Install with overwrite mode
python scripts/manage_config.py install --update-mode overwrite

# Validate configuration for production environment
python scripts/manage_config.py validate --environment production

# Backup current configuration
python scripts/manage_config.py backup

# Restore from backup
python scripts/manage_config.py restore --backup-dir ./config-backup-20250127_143022
```

### Authentication Configuration (`authentication.yaml`)

**Important**: The authentication system uses `config/settings/authentication.yaml` (bundled) or `./config/authentication.yaml` (external) which is automatically loaded on startup. External configs take priority over bundled defaults.

```yaml
authentication:
  # Session configuration
  session:
    lifetime_hours: 8
    cleanup_interval_minutes: 60
    secure_cookies: true
    
  # Provider priority (first successful authentication wins)
  provider_priority:
    - oidc
    - ldap
    - local
    
  # Provider configurations
  providers:
    local:
      enabled: true
      password_policy:
        min_length: 8
        require_uppercase: true
        require_lowercase: true
        require_numbers: true
        require_special: false
        
    ldap:
      enabled: false
      server: "ldap://your-ad-server.company.com"
      port: 389
      use_ssl: false
      use_tls: true
      bind_dn: "CN=trakbridge,OU=Service Accounts,DC=company,DC=com"
      bind_password: "service_account_password"
      user_search_base: "OU=Users,DC=company,DC=com"
      user_search_filter: "(sAMAccountName={username})"
      group_search_base: "OU=Groups,DC=company,DC=com"
      group_search_filter: "(member={user_dn})"
      attributes:
        username: "sAMAccountName"
        email: "mail"
        first_name: "givenName"
        last_name: "sn"
        display_name: "displayName"
      role_mapping:
        "CN=TrakBridge-Admins,OU=Groups,DC=company,DC=com": "admin"
        "CN=TrakBridge-Operators,OU=Groups,DC=company,DC=com": "operator"
        "CN=TrakBridge-Users,OU=Groups,DC=company,DC=com": "user"
        
    oidc:
      enabled: false
      issuer: "https://your-identity-provider.com"
      client_id: "trakbridge-client"
      client_secret: "your-client-secret"
      scopes: ["openid", "email", "profile"]
      redirect_uri: "https://trakbridge.company.com/auth/oidc/callback"
      role_claim: "groups"
      role_mapping:
        "trakbridge-admins": "admin"
        "trakbridge-operators": "operator"
        "trakbridge-users": "user"
```

### Secure Configuration Management

**Important**: TrakBridge now uses a **secure dual-configuration system** to protect sensitive authentication credentials while supporting both local development and CI/CD deployment.

#### Configuration Pattern Overview

TrakBridge uses different configuration approaches based on the environment:

- **Local Development**: Uses `authentication.yaml` with real credentials (gitignored)
- **CI/CD Production**: Uses `authentication.yaml.template` with environment variable substitution

#### Configuration Files

1. **`authentication.yaml.template`** *(Committed to repository)*
   - Contains `${VARIABLE_NAME:-default_value}` placeholders
   - Safe to commit - contains no real secrets
   - Used in CI/CD environments with environment variables

2. **`authentication.yaml`** *(Local development only)*
   - Contains actual credentials for local development
   - Automatically gitignored - never committed
   - Takes priority over template when present

3. **`authentication.yaml.example`** *(Reference documentation)*
   - Comprehensive example showing all configuration options
   - Use as reference for understanding structure

#### Local Development Setup

1. **Copy the template for local development**:
   ```bash
   cp config/settings/authentication.yaml.template config/settings/authentication.yaml
   ```

2. **Edit with your local credentials**:
   ```bash
   # Replace placeholder values with real development credentials
   nano config/settings/authentication.yaml
   ```

3. **Never commit the local file** - it's automatically gitignored.

#### CI/CD Environment Variables

For CI/CD deployment, set these **masked** variables in GitLab Project Settings → CI/CD → Variables:

```bash
# Core session settings
SESSION_LIFETIME_HOURS=8
SESSION_SECURE_COOKIES=true
SESSION_COOKIE_DOMAIN=yourdomain.com

# LDAP/Active Directory
LDAP_ENABLED=true
LDAP_SERVER=ldap://your-ldap-server.com
LDAP_BIND_DN=cn=service,ou=accounts,dc=company,dc=com
LDAP_BIND_PASSWORD=your_secure_password  # Mark as Protected + Masked
LDAP_USER_SEARCH_BASE=ou=users,dc=company,dc=com

# OpenID Connect (OIDC)
OIDC_ENABLED=true
OIDC_ISSUER=https://your-identity-provider.com
OIDC_CLIENT_ID=trakbridge-client
OIDC_CLIENT_SECRET=your_oidc_secret  # Mark as Protected + Masked
OIDC_REDIRECT_URI=https://trakbridge.company.com/auth/callback

# Local authentication
LOCAL_AUTH_ENABLED=true
PASSWORD_MIN_LENGTH=12
PASSWORD_REQUIRE_SPECIAL=true

# Database encryption key
TRAKBRIDGE_ENCRYPTION_KEY="your-32-character-encryption-key"

# Session security
SECRET_KEY="your-flask-secret-key"
```

#### Environment Variable Substitution

The template uses `${VARIABLE_NAME:-default_value}` syntax:

```yaml
# Template format in authentication.yaml.template
ldap:
  server: "${LDAP_SERVER:-ldap.company.com}"
  bind_password: "${LDAP_BIND_PASSWORD:-REPLACE_WITH_PASSWORD}"
  enabled: ${LDAP_ENABLED:-false}
```

The secure loader automatically:
- Substitutes environment variables
- Converts string booleans (`"true"` → `true`)
- Provides fallback defaults
- Validates the final configuration
- Masks sensitive values in logs

#### Environment-Specific Variables

Use GitLab's **environment scoping** for different deployments:

**Development Environment:**
- Scope: `development`
- Relaxed password policies
- HTTP cookies allowed

**Production Environment:**
- Scope: `production` 
- Strong password policies
- HTTPS-only cookies
- **Protected variables** (only available on protected branches)

#### Security Features

- ✅ **Never commits secrets** - Real credentials only in local files
- ✅ **Masked in logs** - Sensitive values replaced with `***MASKED***`
- ✅ **Environment isolation** - Different secrets per environment  
- ✅ **Validation** - Configuration validated before use
- ✅ **Protected variables** - Production secrets only on protected branches
- ✅ **Fallback safety** - Defaults to secure local-only authentication

#### Troubleshooting Secure Configuration

**"No authentication providers enabled"**
- Check that at least one provider has `enabled: true`
- Verify environment variables are set correctly in CI/CD

**"Authentication config validation failed"**
- Check application logs for specific validation errors
- Ensure required fields are provided for enabled providers

**"Using fallback authentication configuration"**
- Configuration loading failed - check file permissions
- Missing environment variables in CI/CD

**Configuration not loading in CI/CD**
- Verify GitLab CI/CD variables are set and not expired
- Check variable masking isn't interfering with values
- Ensure variables are scoped to the correct environment

## Setup Instructions

### 0. Configuration Setup (Docker Deployments)

For Docker deployments with persistent configuration:

1. **Create local config directory**:
```bash
mkdir -p ./config
```

2. **Start container** to auto-install default configs:
```bash
docker-compose up
# or
docker run -v $(pwd)/config:/app/external_config trakbridge:latest
```

3. **Verify config installation**:
```bash
ls -la ./config/
# Should show: app.yaml, authentication.yaml, database.yaml, etc.
```

4. **Customize configuration** by editing files in `./config/`:
```bash
# Edit authentication settings
nano ./config/authentication.yaml

# Validate your changes
python scripts/manage_config.py validate --environment production
```

### 1. Basic Local Authentication Setup

1. **Enable local authentication** in `authentication.yaml`:
   - **Docker**: Edit `./config/authentication.yaml`  
   - **Local**: Edit `config/settings/authentication.yaml`
```yaml
authentication:
  providers:
    local:
      enabled: true
```

2. **Initial admin user is created automatically**:
   - Default credentials: `admin` / `TrakBridge-Setup-2025!`
   - Password change required on first login
   - Bootstrap service handles this automatically

3. **Configure password policy** as needed in the auth configuration.

### 2. LDAP/Active Directory Setup

1. **Configure LDAP connection** in `authentication.yaml`:
   - **Docker**: Edit `./config/authentication.yaml`
   - **Local**: Edit `config/settings/authentication.yaml`
```yaml
authentication:
  providers:
    ldap:
      enabled: true
      server: "ldap://your-ad-server.company.com"
      port: 389
      use_tls: true
      bind_dn: "CN=trakbridge,OU=Service Accounts,DC=company,DC=com"
      user_search_base: "OU=Users,DC=company,DC=com"
      user_search_filter: "(sAMAccountName={username})"
```

2. **Set LDAP password** via environment variable:
```bash
export LDAP_BIND_PASSWORD="service_account_password"
```

3. **Configure group mappings** for automatic role assignment:
```yaml
role_mapping:
  "CN=TrakBridge-Admins,OU=Groups,DC=company,DC=com": "admin"
  "CN=TrakBridge-Operators,OU=Groups,DC=company,DC=com": "operator"
```

4. **Test LDAP connection**: Verify through application logs after attempting login

### 3. OIDC/SSO Setup

1. **Register TrakBridge** with your identity provider (Azure AD, Okta, etc.)

2. **Configure OIDC** in `authentication.yaml`:
   - **Docker**: Edit `./config/authentication.yaml`
   - **Local**: Edit `config/settings/authentication.yaml`
```yaml
authentication:
  providers:
    oidc:
      enabled: true
      issuer: "https://login.microsoftonline.com/your-tenant-id/v2.0"
      client_id: "your-application-id"
      redirect_uri: "https://trakbridge.company.com/auth/oidc/callback"
```

3. **Set client secret** via environment variable:
```bash
export OIDC_CLIENT_SECRET="your-oidc-client-secret"
```

4. **Configure role claims** based on your identity provider's group claims.

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

#### Configuration File Issues
```bash
# Check which config files are being used
python scripts/manage_config.py list

# Validate current configuration
python scripts/manage_config.py validate --environment production

# Check configuration loading in app logs
grep -i "configuration.*loaded" logs/app.log

# Backup and reinstall default configs
python scripts/manage_config.py backup
python scripts/manage_config.py install --update-mode overwrite
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