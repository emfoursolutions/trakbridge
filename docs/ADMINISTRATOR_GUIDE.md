# TrakBridge Administrator Guide

## Overview

This guide covers comprehensive system administration for TrakBridge, including user management, system monitoring, security administration, and operational maintenance. This guide assumes you have Admin role access and technical knowledge of the deployment environment.

## System Administration

### User Management

#### User Account Operations

##### Creating Users
1. **Navigate to Admin → User Management**
2. **Click "Create User"**
3. **Enter user details**:
   - Username (unique, alphanumeric)
   - Email address (for notifications)
   - Full name (display name)
   - Initial password (user will change on first login)
4. **Assign role**: Viewer, User, Operator, or Admin
5. **Set authentication provider**: Local, LDAP, or OIDC
6. **Save user account**

##### User Role Assignments
**Viewer Role**:
- Read-only access to streams and dashboard
- Cannot create, edit, or delete resources
- Suitable for monitoring personnel and observers

**User Role**:
- Can create and manage their own streams
- Profile management and password changes
- Suitable for individual operators and field personnel

**Operator Role**:
- Full stream and TAK server management
- Cannot manage users or system settings
- Suitable for operations supervisors and technical operators

**Admin Role**:
- Complete system administration access
- User management and system configuration
- Suitable for system administrators and technical leads

##### Managing Existing Users
**Edit User Accounts**:
- Update contact information and display names
- Change role assignments as needed
- Reset passwords for account recovery
- Enable/disable accounts without deletion

**User Account Lifecycle**:
- **Active**: Normal operational access
- **Disabled**: Account exists but cannot login (temporary suspension)
- **Locked**: Account temporarily locked due to security policy
- **Archived**: Account preserved for audit but marked inactive

#### Authentication Provider Management

##### Local Authentication
Default authentication method with local database storage.

**Configuration**:
```yaml
authentication:
  default_provider: local
  password_policy:
    min_length: 12
    require_mixed_case: true
    require_numbers: true
    require_symbols: true
    max_age_days: 90
  session_timeout_minutes: 480
  max_failed_attempts: 5
  lockout_duration_minutes: 30
```

**Administrative Tasks**:
- Password policy enforcement
- Account lockout management
- Session monitoring and cleanup
- Password reset procedures

##### LDAP/Active Directory Integration
Enterprise directory integration for centralized authentication.

**Configuration Management**:
```yaml
authentication:
  providers:
    ldap:
      enabled: true
      server: "ldap://your-domain-controller.company.com"
      port: 389
      use_tls: true
      bind_dn: "CN=trakbridge,OU=Service Accounts,DC=company,DC=com"
      user_search_base: "OU=Users,DC=company,DC=com"
      user_search_filter: "(sAMAccountName={username})"
      group_search_base: "OU=Groups,DC=company,DC=com"
      role_mapping:
        "CN=TrakBridge-Admins,OU=Groups,DC=company,DC=com": "admin"
        "CN=TrakBridge-Operators,OU=Groups,DC=company,DC=com": "operator"
        "CN=TrakBridge-Users,OU=Groups,DC=company,DC=com": "user"
```

**Administrative Tasks**:
- LDAP connection monitoring
- Group membership synchronization
- Service account credential rotation
- Directory integration troubleshooting

##### OIDC/SSO Integration
Single sign-on integration with enterprise identity providers.

**Configuration Management**:
```yaml
authentication:
  providers:
    oidc:
      enabled: true
      issuer: "https://login.microsoftonline.com/tenant-id/v2.0"
      client_id: "application-client-id"
      redirect_uri: "https://trakbridge.company.com/auth/oidc/callback"
      scopes: ["openid", "profile", "email"]
      role_claim: "roles"
      role_mapping:
        "trakbridge-admins": "admin"
        "trakbridge-operators": "operator"
        "trakbridge-users": "user"
```

**Administrative Tasks**:
- Application registration management
- Certificate and token validation
- Role claim mapping updates
- SSO provider integration testing

### System Monitoring

#### Health Monitoring

##### System Health Checks
Regular monitoring of system components:

```bash
# Basic health check
curl http://localhost:8080/api/health

# Detailed component health
curl -H "X-API-Key: admin-key" http://localhost:8080/api/health/detailed

# Kubernetes readiness/liveness probes
curl http://localhost:8080/api/health/ready
curl http://localhost:8080/api/health/live
```

**Key Health Indicators**:
- Database connectivity and migration status
- Encryption service functionality
- Stream manager and worker threads
- System resources (CPU, memory, disk)
- Plugin health and availability

##### Performance Monitoring
**Resource Utilization**:
- CPU usage patterns and peak loads
- Memory consumption and garbage collection
- Disk I/O and storage capacity
- Network connectivity and throughput

**Application Metrics**:
- Stream processing rates and latency
- Authentication success/failure rates
- API request volumes and response times
- Error rates and exception patterns

#### Log Management

##### Log Analysis and Monitoring
**Critical Log Categories**:
- **Authentication Events**: Login successes/failures, role changes
- **Stream Operations**: Stream starts/stops, data flow, errors
- **Security Events**: Permission denials, suspicious activity
- **System Errors**: Application exceptions, database errors
- **Configuration Changes**: Settings updates, user modifications

**Log Monitoring Tools**:
```bash
# Real-time authentication monitoring
tail -f logs/trakbridge.log | grep -i "auth\|login"

# Stream error monitoring
tail -f logs/trakbridge.log | grep -E "ERROR|CRITICAL" | grep -i "stream"

# Security event monitoring
tail -f logs/trakbridge.log | grep -i "security\|permission\|unauthorized"
```

### TAK Server Management

#### TAK Server Configuration

##### Adding TAK Servers
1. **Navigate to Admin → TAK Servers**
2. **Click "Add TAK Server"**
3. **Configure connection details**:
   - Server name (descriptive identifier)
   - Hostname/IP address
   - Port (typically 8089 for SSL, 8088 for non-SSL)
   - Protocol (TCP/SSL preferred for security)
4. **Upload certificates** if using SSL/TLS
5. **Test connection** before saving
6. **Save configuration**

##### Connection Monitoring
**TAK Server Health Checks**:
- Connection status and latency
- Certificate validity and expiration
- Data transmission rates and success
- Error rates and connection failures

### Plugin System Administration

#### Built-in Plugin Management

##### Plugin Status Monitoring
```bash
# Check all plugin health
curl -H "X-API-Key: admin-key" http://localhost:8080/api/health/plugins

# Get plugin categories and counts
curl -H "X-API-Key: admin-key" http://localhost:8080/api/plugins/category-statistics
```

**Plugin Health Indicators**:
- Plugin initialization status
- Configuration validation results
- API connectivity and authentication
- Data processing performance

##### Plugin Configuration Updates
Monitor and manage plugin-specific configurations:

**Garmin InReach Plugin**:
- API endpoint accessibility
- Authentication credential validation
- Share page availability and format
- Rate limiting and quota usage

**SPOT Tracker Plugin**:
- Feed ID validity and accessibility
- Shared page configuration status
- Data format and parsing accuracy
- API response time and reliability

**Deepstate OSINT Plugin**:
- Public API availability
- Data source reliability and currency
- Content filtering and processing
- Geographic data accuracy

#### External Plugin Management

##### External Plugin Configuration
Configure external plugin loading in `config/settings/plugins.yaml`:

```yaml
plugins:
  external_paths:
    - /app/external_plugins
    - /opt/trakbridge/plugins
    - ~/.trakbridge/plugins
  
  allowed_plugin_modules:
    - external_plugins.custom_tracker
    - external_plugins.enterprise_gps
    - external_plugins.special_osint
  
  security:
    validate_signatures: true
    require_manifest: true
    sandbox_execution: true
```

##### External Plugin Deployment
**Docker Volume Mounting**:
```yaml
# docker-compose.yml
volumes:
  - ./custom-plugins:/app/external_plugins:ro
  - ./plugin-configs:/app/external_config/plugins:ro
```

**Plugin Validation and Security**:
- Signature verification for plugin authenticity
- Manifest validation for plugin metadata
- Sandboxed execution environment
- Resource usage monitoring and limits

### Database Administration

#### Database Configuration

##### SQLite Administration (Development/Testing)
**Database Maintenance**:
```bash
# Database backup
cp data/trakbridge.db backups/trakbridge-$(date +%Y%m%d).db

# Database integrity check
sqlite3 data/trakbridge.db "PRAGMA integrity_check;"

# Database optimization
sqlite3 data/trakbridge.db "VACUUM; ANALYZE;"
```

##### PostgreSQL Administration (Production)
**Database Maintenance**:
```bash
# Database backup
pg_dump -h postgres -U trakbridge trakbridge > backup-$(date +%Y%m%d).sql

# Database statistics update
docker-compose exec postgres psql -U trakbridge -d trakbridge -c "ANALYZE;"

# Connection monitoring
docker-compose exec postgres psql -U trakbridge -d trakbridge -c "SELECT * FROM pg_stat_activity;"
```

### Security Administration

#### Security Monitoring

##### Authentication Security
**Failed Login Monitoring**:
```bash
# Monitor failed authentication attempts
grep "Authentication failed" logs/trakbridge.log | tail -20

# Account lockout monitoring
grep "Account locked" logs/trakbridge.log | tail -10

# Suspicious activity patterns
grep -E "Multiple failed.*|Brute force.*|Unusual access" logs/trakbridge.log
```

### Troubleshooting Guide

#### Common Administrative Issues

##### Authentication Problems
**LDAP Connection Failures**:
- Verify LDAP server connectivity and credentials
- Check service account permissions and password expiration
- Validate LDAP queries and group membership
- Monitor network connectivity and firewall rules

**OIDC Integration Issues**:
- Verify application registration and client credentials
- Check certificate validation and trust relationships
- Validate redirect URIs and callback endpoints
- Monitor token exchange and validation processes

##### Performance Issues
**High Resource Usage**:
- Identify resource-intensive streams and processes
- Adjust refresh intervals and processing parameters
- Scale resources or optimize configurations
- Implement load balancing if necessary

**Database Performance Problems**:
- Analyze query performance and execution plans
- Update database statistics and optimize indexes
- Monitor connection pool usage and configuration
- Consider database tuning and hardware upgrades

##### Integration Problems
**TAK Server Connectivity**:
- Verify network connectivity and firewall rules
- Check certificate validity and mutual TLS configuration
- Monitor TAK server logs for connection errors
- Validate data format and protocol compatibility

**Plugin Failures**:
- Check external API accessibility and authentication
- Verify plugin configuration and credentials
- Monitor plugin-specific logs and error messages
- Test plugin functionality in isolation

---

**Administrator Guide Version**: 1.2.0  
**Last Updated**: 2025-08-08  
**Applies To**: TrakBridge v1.0.0 and later