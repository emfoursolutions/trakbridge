# TrakBridge Upgrade Guide

## Overview

This guide covers upgrading TrakBridge between versions, including major version upgrades and security enhancements. TrakBridge follows semantic versioning with careful attention to backward compatibility.

**IMPORTANT**: Always backup your data before upgrading. Some upgrades may introduce breaking changes or new security requirements.

## Version Compatibility Matrix

| Upgrade From | Upgrade To | Compatibility | Notes |
|--------------|------------|---------------|-------|
| v1.0.0-beta.4 | Current | Major upgrade | Requires authentication setup |
| Development | Any release | Variable | Check migration requirements |

## Current Version Features

### Authentication System
- **Multi-Provider Support**: Local database, LDAP/Active Directory, OIDC/SSO
- **Role-Based Access Control**: Viewer, User, Operator, Admin roles
- **Automatic Bootstrap**: Initial admin user created on first startup
- **Web-Only Management**: All user administration through secure web interface

### Plugin Categorization
- **OSINT Category**: Open source intelligence platforms (Deepstate)
- **Tracker Category**: GPS and satellite tracking devices (Garmin, SPOT, Traccar)
- **EMS Category**: Emergency management systems (future expansion)
- **Category API**: RESTful endpoints for category-based plugin discovery

### Security Hardening
- **Field-Level Encryption**: Sensitive configuration data encrypted at rest
- **JSON Validation**: Comprehensive input validation and DoS protection
- **Container Security**: Non-root execution and secure defaults
- **Session Management**: Secure session handling with automatic cleanup

### UI Enhancements
- **Categorized Plugin Selection**: Organized data source selection by category
- **Role-Based UI**: Buttons and features shown based on user permissions
- **External Plugin Support**: Docker volume mounting for custom plugins

## General Upgrade Process

### Standard Upgrade Steps

For most version upgrades, follow these standard steps:

#### 1. Preparation
```bash
# Check current version
curl https://yourdomain.com/api/version

# Stop the application
docker compose --profiles postgres --profiles nginx down
```

#### 2. Backup (Critical)
```bash
# Create backup with timestamp
DATE=$(date +%Y%m%d-%H%M%S)
mkdir -p backups/upgrade-$DATE
cp -r data config secrets docker-compose.yml backups/upgrade-$DATE/ 2>/dev/null
tar -czf backups/trakbridge-$DATE.tar.gz backups/upgrade-$DATE/
```

#### 3. Update Application
```bash
# Docker: Pull latest image
docker compose pull

# Development: Pull latest code
git pull origin main && pip install .
```

#### 4. Database Migration
```bash
# Docker: Automatic on startup
docker compose --profiles postgres --profiles nginx up -d

# Development: Manual migration
python -m flask db upgrade
```

#### 5. Verification
```bash
# Check health and version
curl https://yourdomain.com/api/health
curl https://yourdomain.com/api/version

# Verify functionality through web interface
```

### Rolling Back
If issues occur during upgrade:
```bash
# Stop application
docker compose --profiles postgres --profiles nginx down

# Restore from backup
cp -r backups/upgrade-*/data backups/upgrade-*/config .

# Restart previous version
docker compose --profiles postgres --profiles nginx up -d
```

## Major Version Upgrades

### v1.0.0-beta.4 to Current (Authentication System)

This section covers the major upgrade from pre-authentication versions to the current authenticated system.

### Pre-Upgrade Checklist

### Backup Your Data
**CRITICAL**: Always backup before upgrading!

#### Docker Installation Backup
```bash
# Stop the application
docker compose --profiles postgres --profiles nginx down

# Create comprehensive backup
mkdir -p backups/pre-auth-upgrade-$(date +%Y%m%d)
cd backups/pre-auth-upgrade-$(date +%Y%m%d)

# Backup all data
cp -r ../../data ./data-backup
cp -r ../../config ./config-backup  
cp ../../docker-compose.yml ./
cp -r ../../secrets ./ 2>/dev/null || echo "No secrets directory found"

# Backup database specifically
# Identify the Database Container
docker ps

# If using PostgreSQL
docker run --rm \
  --network container:<container_name> \
  -v "$(pwd)":/backups \
  --secret source=db_password,target=/run/secrets/db_password \
  postgres:15 \
  pg_dump -U trakbridge -d trakbridge_db > /backups/postgres_backup_$(date +%F).sql

# If using MySQL
docker run --rm \
  --network container:<container_name> \
  -v "$(pwd)":/backups \
  --secret source=db_password,target=/run/secrets/db_password \
  -e MYSQL_PWD=$(cat ./secrets/db_password) \
  mysql:8.0 \
  mysqldump -u trakbridge trakbridge_db > /backups/mysql_backup_$(date +%F).sql

# Create backup archive
cd ..
tar -czf pre-auth-upgrade-$(date +%Y%m%d).tar.gz pre-auth-upgrade-$(date +%Y%m%d)/
```
### Document Current Settings
1. **Note your current streams**: Take screenshots or notes of configured streams
2. **Note your TAK servers**: Document server configurations and certificates
3. **Record custom configurations**: Any custom settings or modifications

### Plan Authentication Strategy
Decide which authentication method you'll use:
- **Local Only**: Simplest upgrade path (recommended for most users)
- **LDAP Integration**: If you have Active Directory
- **OIDC/SSO**: If you have enterprise identity provider

## Upgrade Process

## Step 1: Update Application Code

### Docker Upgrade
```bash
# Stop current application
docker compose --profiles postgres --profiles nginx down

# Pull latest image
docker compose pull

# Or update docker-compose.yml to use latest tag
sed -i 's/trakbridge:.*/trakbridge:latest/' docker-compose.yml
```

### Development Upgrade
```bash
# Stash any local changes
git stash

# Pull latest code
git pull origin main

# Update dependencies
pip install .
```

## Step 2: Database Migration

The new version includes database schema changes for the authentication system.

### Automatic Migration (Recommended)
```bash
# Docker - migrations run automatically on startup. Use the appropriate startup command
docker compose --profile postgres --profile nginx up -d

docker compose --profile mysql --profile nginx up -d

docker compose --profile postgres up -d

docker compose --profile mysql up -d

# Development - run migrations manually
python -m flask db upgrade
```

### Manual Migration Verification
```bash
# Check migration status
python -m flask db current

# Should show the latest migration with authentication tables
```

**New Tables Created:**
- `users` - User accounts and authentication data
- `user_sessions` - Active user sessions
- Authentication-related indexes and constraints

## Step 3: Initial Admin Setup

### First Startup - Automatic Admin Creation
The application automatically creates an initial admin user on first startup:

1. **Start the application**:
```bash
# Docker
docker compose --profiles postgres --profiles nginx up -d

# Development
python app.py
```

2. **Check logs for admin creation**:
```bash
# Docker
docker compose logs | grep -i "INITIAL ADMIN"

# You should see:
# INITIAL ADMIN USER CREATED
# CHANGE PASSWORD ON FIRST LOGIN
```

3. **Access the application**:
   - URL: http://localhost:8080 (or your configured URL)
   - Username: `admin`
   - Password: `TrakBridge-Setup-2025!`

4. **Change the default password**:
   - You'll be **forced to change the password** on first login
   - Choose a strong password for security

## Step 4: Configure Authentication (Optional)

### Option A: Keep Local Authentication
No additional configuration needed. You can create users through the web interface:
1. Login as admin
2. Go to **Settings** → **User Management**
3. Click **Create User**
4. Add users and assign roles

### Option B: Configure LDAP Integration
1. **Configure LDAP Settings in docker-compose.yml** (Docker users):
```yaml
  # LDAP Settings (set LDAP_ENABLED to "true" and configure for your environment)
  LDAP_ENABLED: "false"
  LDAP_SERVER: "ldap://your-ad-server.company.com"  # Update for your LDAP server
  LDAP_PORT: "389"
  LDAP_USE_SSL: "false"
  LDAP_USE_TLS: "true"
  LDAP_VALIDATE_CERT: "true"
  LDAP_BIND_DN: "CN=trakbridge,OU=Service Accounts,DC=company,DC=com"  # Update for your domain
  LDAP_USER_SEARCH_BASE: "OU=Users,DC=company,DC=com"  # Update for your domain
  LDAP_USER_SEARCH_FILTER: "(sAMAccountName={username})"
  LDAP_GROUP_SEARCH_BASE: "OU=Groups,DC=company,DC=com"  # Update for your domain
  LDAP_GROUP_SEARCH_FILTER: "(member={user_dn})"
  LDAP_ADMIN_GROUP: "CN=TrakBridge-Admins,OU=Groups,DC=company,DC=com"  # Update group names
  LDAP_OPERATOR_GROUP: "CN=TrakBridge-Operators,OU=Groups,DC=company,DC=com"
  LDAP_USER_GROUP: "CN=TrakBridge-Users,OU=Groups,DC=company,DC=com"
  LDAP_DEFAULT_ROLE: "user"
  LDAP_CONNECTION_TIMEOUT: "10"
  LDAP_RESPONSE_TIMEOUT: "30"```
```

2. **Set LDAP password**:
```bash
# Add to secrets file (Docker) or export (Development)
echo "your-service-account-password" > secrets/ldap_bind_password

# Secure the file
chmod 600 secrets/ldap_bind_password
```

3. **Restart application**:
```bash
docker compose --profiles postgres --profiles nginx down
docker compose --profiles postgres --profiles nginx up -d
```

### Option C: Configure OIDC/SSO
1. **Register TrakBridge** with your identity provider
2. **Configure OIDC settings**:
```yaml
  # OIDC/SSO Settings (set OIDC_ENABLED to "true" and configure for your identity provider)
  OIDC_ENABLED: "false"
  OIDC_ISSUER: "https://your-identity-provider.com"  # Update for your OIDC provider
  OIDC_CLIENT_ID: "trakbridge-client"  # Update with your client ID
  OIDC_REDIRECT_URI: "https://trakbridge.company.com/auth/oidc/callback"  # Update for your domain
  OIDC_VERIFY_SIGNATURE: "true"
  OIDC_VERIFY_AUDIENCE: "true"
  OIDC_VERIFY_ISSUER: "true"
  OIDC_ADMIN_GROUP: "trakbridge-admins"  # Update role mappings for your provider
  OIDC_OPERATOR_GROUP: "trakbridge-operators"
  OIDC_USER_GROUP: "trakbridge-users"
  OIDC_DEFAULT_ROLE: "user"
```

3. **Set OIDC credentials**:
```bash
echo "your-oidc-client-secret" > secrets/oidc_client_secret
chmod 600 secrets/oidc_client_secret
```

## Step 5: Verify Upgrade Success

### Test Authentication
1. **Access application** at your URL
2. **Login successfully** with admin credentials
3. **Verify forced password change** worked
4. **Check user management interface** is accessible

### Verify Data Integrity
1. **Check streams**: Navigate to Streams page
   - All your previous streams should be visible
   - Stream configurations should be intact
   - Test stream connections

2. **Check TAK servers**: Navigate to TAK Servers page
   - All server configurations should be present
   - Test server connections
   - Verify certificates are still valid

3. **Check system health**:
```bash
curl http://localhost:8080/api/health
```

### Test Role-Based Access
1. **Create a test user**:
   - Go to User Management → Create User
   - Create a user with "Viewer" role
   - Test that they can't see create/edit buttons

2. **Test different roles**:
   - **Viewer**: Should see read-only interface
   - **User**: Basic access with profile management
   - **Operator**: Can manage streams and TAK servers
   - **Admin**: Full access to everything

## Step 6: Production Hardening

### Security Configuration
1. **Set strong encryption key**:
```bash
# Generate secure 32-character key
openssl rand -base64 32 | cut -c1-32

# Add to secrets file
echo "your-generated-key" > secrets/tb_master_key
```

2. **Configure HTTPS** (production only):
```bash
# Use the setup script for automated SSL
./setup.sh --enable-nginx --nginx-ssl yourdomain.com
```

3. **Review firewall settings**:
   - Ensure only necessary ports are open
   - Consider restricting admin access by IP

### Backup Schedule
Set up automated backups now that authentication is configured:
```bash
# Create backup script
cat > backup-trakbridge.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="backups/automated-$DATE"
mkdir -p "$BACKUP_DIR"

# Backup data and config
cp -r data "$BACKUP_DIR/"
cp -r config "$BACKUP_DIR/"
cp docker-compose.yml "$BACKUP_DIR/" 2>/dev/null
cp -r secrets "$BACKUP_DIR/" 2>/dev/null

# Create archive
tar -czf "backups/trakbridge-$DATE.tar.gz" "$BACKUP_DIR"
rm -rf "$BACKUP_DIR"

# Keep only last 7 days
find backups/ -name "trakbridge-*.tar.gz" -mtime +7 -delete
EOF

chmod +x backup-trakbridge.sh

# Add to crontab for daily backups
echo "0 2 * * * $(pwd)/backup-trakbridge.sh" | crontab -
```

## Troubleshooting Common Upgrade Issues

### Issue: Cannot Access Application (403/401 Errors)
**Solution**: The application now requires authentication
1. Access the login page at your URL
2. Use admin credentials: `admin` / `TrakBridge-Setup-2025!`
3. Change password when prompted

### Issue: Default Admin User Not Created
**Symptom**: No login possible, no admin user exists

**Solution**:
1. **Check logs** for bootstrap errors:
```bash
docker-compose logs | grep -i bootstrap
```

2. **Manual admin creation** (if needed):
```bash
# Stop application
docker-compose down

# Remove bootstrap flag to retry
rm data/.bootstrap_completed

# Restart application
docker-compose up -d

# Check logs for admin creation
docker-compose logs | grep -i "INITIAL ADMIN"
```

### Issue: Streams/TAK Servers Missing
**Symptom**: Previous configurations not visible

**Solution**:
1. **Check database migration**:
```bash
python -m flask db current
```

2. **Restore from backup** if needed:
```bash
# Stop application
docker-compose down

# Restore database
cp backups/pre-auth-upgrade-*/trakbridge-pre-upgrade.db data/trakbridge.db

# Restart and retry migration
docker-compose up -d
```

### Issue: LDAP/OIDC Authentication Not Working
**Solution**:
1. **Test configuration**:
```bash
# LDAP test
python -m flask auth test-ldap --username testuser

# OIDC test  
python -m flask auth test-oidc
```

2. **Check provider logs**:
```bash
tail -f logs/app.log | grep -i "ldap\|oidc"
```

3. **Verify credentials** are set correctly in environment

### Issue: Role-Based UI Not Working
**Symptom**: Users see buttons they shouldn't have access to

**Solution**: 
1. **Check user roles** in User Management
2. **Verify current_user context** is available
3. **Clear browser cache** and refresh

## Rollback Procedure (If Needed)

If the upgrade fails and you need to rollback:

### Emergency Rollback Steps
1. **Stop current application**:
```bash
docker-compose down
```

2. **Restore backup**:
```bash
# Restore previous version files
cd backups/pre-auth-upgrade-*/
cp trakbridge-pre-upgrade.db ../../data/trakbridge.db
cp docker-compose.yml ../../
cp -r secrets ../../ 2>/dev/null || true
```

3. **Revert to previous image**:
```bash
# Change docker-compose.yml to use previous version
sed -i 's/trakbridge:latest/trakbridge:v1.0.0-beta.4/' ../../docker-compose.yml
```

4. **Start previous version**:
```bash
cd ../../
docker-compose up -d
```

**Note**: You'll lose authentication features but regain access to your data.

## Post-Upgrade Best Practices

### 1. User Training
- **Admin users**: Train on new user management interface
- **End users**: Inform about login requirements and password policies
- **Operators**: Update procedures to include authentication

### 2. Documentation Updates
- Update any deployment scripts to include authentication
- Document your chosen authentication provider configuration
- Update monitoring scripts to check authentication health

### 3. Monitoring and Alerting
- Monitor authentication logs for suspicious activity
- Set up alerts for failed login attempts
- Monitor user session counts and cleanup

### 4. Regular Maintenance
- Review user accounts monthly
- Update passwords according to policy
- Keep authentication provider configurations current

## Support and Help

If you encounter issues during the upgrade:

1. **Check logs first**: `docker-compose logs` or `logs/app.log`
2. **Review this guide**: Ensure all steps were followed
3. **Test step by step**: Isolate the problem area
4. **Use validation tools**: CLI scripts in `scripts/` directory
5. **Seek help**: 
   - GitHub Issues: [Report Problems](../../issues)
   - Discussions: [Community Support](../../discussions)
   - Email: support@emfoursolutions.com.au

## Summary

After successful upgrade, you'll have:
- Secure authentication system with role-based access
- All existing streams and TAK servers preserved
- Enhanced UI with role-appropriate controls
- Comprehensive audit logging
- Web-based user management
- Future-proof architecture for additional features

The upgrade provides significant security and usability improvements while maintaining full compatibility with your existing GPS tracking configurations.

---

**Upgrade completed successfully?** Welcome to the enhanced TrakBridge experience with comprehensive security and plugin categorization features.