# TrakBridge Upgrade Guide: v1.0.0-beta.4 to Current Version

## Overview

This guide covers upgrading TrakBridge from v1.0.0-beta.4 (which did not have an authentication system) to the current version with comprehensive multi-provider authentication and role-based access control.

**⚠️ IMPORTANT**: This is a **major upgrade** that introduces breaking changes. The application now requires authentication for all access. Plan for downtime and follow this guide carefully.

## What's New in This Version

### 🔐 Authentication System
- **Multi-Provider Support**: Local database, LDAP/Active Directory, OIDC/SSO
- **Role-Based Access Control**: Viewer, User, Operator, Admin roles
- **Automatic Bootstrap**: Initial admin user created on first startup
- **Web-Only Management**: All user administration through secure web interface

### 🛡️ Security Enhancements
- **Encrypted Credentials**: Field-level encryption for sensitive data
- **Session Management**: Secure session handling with automatic cleanup
- **Audit Logging**: Comprehensive logging of all authentication events
- **CLI Security**: Restricted CLI access for enhanced security

### 🎛️ UI Improvements
- **Role-Based UI**: Buttons and features shown based on user permissions
- **User Management**: Complete user administration interface
- **Profile Management**: User profile and password change functionality

## Pre-Upgrade Checklist

### ✅ Backup Your Data
**CRITICAL**: Always backup before upgrading!

#### Docker Installation Backup
```bash
# Stop the application
docker-compose down

# Create comprehensive backup
mkdir -p backups/pre-auth-upgrade-$(date +%Y%m%d)
cd backups/pre-auth-upgrade-$(date +%Y%m%d)

# Backup all data
cp -r ../../data ./data-backup
cp -r ../../config ./config-backup  
cp ../../docker-compose.yml ./
cp ../../.env ./ 2>/dev/null || echo "No .env file found"

# Backup database specifically
cp ../../data/trakbridge.db ./trakbridge-pre-upgrade.db

# Create backup archive
cd ..
tar -czf pre-auth-upgrade-$(date +%Y%m%d).tar.gz pre-auth-upgrade-$(date +%Y%m%d)/
```

#### Development Installation Backup
```bash
# Create backup directory
mkdir -p backups/pre-auth-upgrade-$(date +%Y%m%d)

# Backup database and config
cp instance/trakbridge.db backups/pre-auth-upgrade-$(date +%Y%m%d)/
cp -r config/ backups/pre-auth-upgrade-$(date +%Y%m%d)/config-backup/

# Backup any custom modifications
git stash push -m "Pre-authentication upgrade stash"
```

### ✅ Document Current Settings
1. **Note your current streams**: Take screenshots or notes of configured streams
2. **Note your TAK servers**: Document server configurations and certificates
3. **Record custom configurations**: Any custom settings or modifications

### ✅ Plan Authentication Strategy
Decide which authentication method you'll use:
- **Local Only**: Simplest upgrade path (recommended for most users)
- **LDAP Integration**: If you have Active Directory
- **OIDC/SSO**: If you have enterprise identity provider

## Upgrade Process

## Step 1: Update Application Code

### Docker Upgrade
```bash
# Stop current application
docker-compose down

# Pull latest image
docker-compose pull

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
# Docker - migrations run automatically on startup
docker-compose --profile postgres --profile nginx up -d

docker-compose --profile mysql --profile nginx up -d

docker-compose --profile postgres up -d

docker-compose --profile mysql up -d

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
docker-compose up -d

# Development
python app.py
```

2. **Check logs for admin creation**:
```bash
# Docker
docker-compose logs | grep -i "INITIAL ADMIN"

# You should see:
# INITIAL ADMIN USER CREATED
# ⚠️  CHANGE PASSWORD ON FIRST LOGIN  ⚠️
```

3. **Access the application**:
   - URL: http://localhost:8080 (or your configured URL)
   - Username: `admin`
   - Password: `TrakBridge-Setup-2025!`

4. **Change the default password**:
   - You'll be **forced to change the password** on first login
   - Choose a strong password for security

## Step 4: Configure Authentication (Optional)

### Option A: Keep Local Authentication (Recommended)
No additional configuration needed. You can create users through the web interface:
1. Login as admin
2. Go to **Settings** → **User Management**
3. Click **Create User**
4. Add users and assign roles

### Option B: Configure LDAP Integration
1. **Create authentication configuration** (Docker users):
```bash
# Edit the auto-created config file
nano ./config/authentication.yaml
```

2. **Configure LDAP settings**:
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
      role_mapping:
        "CN=TrakBridge-Admins,OU=Groups,DC=company,DC=com": "admin"
        "CN=TrakBridge-Operators,OU=Groups,DC=company,DC=com": "operator"
        "CN=TrakBridge-Users,OU=Groups,DC=company,DC=com": "user"
```

3. **Set LDAP password**:
```bash
# Add to .env file (Docker) or export (Development)
echo "LDAP_BIND_PASSWORD=your-service-account-password" >> .env
```

4. **Restart application**:
```bash
docker-compose restart
```

### Option C: Configure OIDC/SSO
1. **Register TrakBridge** with your identity provider
2. **Configure OIDC settings**:
```yaml
authentication:
  providers:
    oidc:
      enabled: true
      issuer: "https://login.microsoftonline.com/your-tenant-id/v2.0"
      client_id: "your-application-id"
      redirect_uri: "https://trakbridge.company.com/auth/oidc/callback"
      role_mapping:
        "trakbridge-admins": "admin"
        "trakbridge-operators": "operator"
```

3. **Set OIDC credentials**:
```bash
echo "OIDC_CLIENT_SECRET=your-oidc-client-secret" >> .env
```

## Step 5: Verify Upgrade Success

### ✅ Test Authentication
1. **Access application** at your URL
2. **Login successfully** with admin credentials
3. **Verify forced password change** worked
4. **Check user management interface** is accessible

### ✅ Verify Data Integrity
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

### ✅ Test Role-Based Access
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

# Add to .env file
echo "TRAKBRIDGE_ENCRYPTION_KEY=your-generated-key" >> .env
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
cp docker-compose.yml .env "$BACKUP_DIR/" 2>/dev/null

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
cp .env ../../  2>/dev/null || true
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
- ✅ Secure authentication system with role-based access
- ✅ All existing streams and TAK servers preserved
- ✅ Enhanced UI with role-appropriate controls
- ✅ Comprehensive audit logging
- ✅ Web-based user management
- ✅ Future-proof architecture for additional features

The upgrade provides significant security and usability improvements while maintaining full compatibility with your existing GPS tracking configurations.

---

**Upgrade completed successfully?** 🎉 Welcome to the new authenticated TrakBridge experience!