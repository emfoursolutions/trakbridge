# TrakBridge Upgrade Guide

## Overview

This guide covers upgrading TrakBridge between versions, including major version upgrades and security enhancements. TrakBridge follows semantic versioning with careful attention to backward compatibility.

**IMPORTANT**: Always backup your data before upgrading. Some upgrades may introduce breaking changes or new security requirements.

## Version Compatibility Matrix

| Upgrade From   | Upgrade To  | Compatibility | Notes                                                                      |
|----------------|-------------|---------------|----------------------------------------------------------------------------|
| v2.0.x         | v2.1.0      | Compatible    | Behavioural change: CSRF on by default (see below); no schema migration    |
| v1.3.x         | v2.1.0      | Compatible    | Plugin manager + tier gating + CSRF change (see 2.0.0 and 2.1.0 sections)  |
| v1.2.x         | v1.3.0      | Compatible    | DB migrations auto-apply; webhook_handler removed                          |
| v1.1.x         | v1.3.0      | Compatible    | Authentication required; DB migrations auto-apply                          |
| v1.0.x         | v1.3.0      | Compatible    | DB migrations auto-apply                                                   |
| v1.0.0-beta.4  | v1.3.0      | Major upgrade | Requires authentication setup (see below)                                  |
| Development    | Any release | Variable      | Check migration requirements                                               |

## v2.0.x to v2.1.0 Upgrade Notes

Straight upgrade from 2.0.1. No schema migration, no configuration change required. All Phase 1 security defaults take effect immediately for new sessions and requests.

### CSRF now on by default

`WTF_CSRF_CHECK_DEFAULT` has been flipped from False to True. Every **session-authenticated** state-changing request (POST/PUT/PATCH/DELETE) now requires a valid CSRF token, either as `csrf_token` in the form body or `X-CSRFToken` in the request header.

**No changes needed for:**

- The built-in admin UI — every form template already emits `{{ csrf_token() }}`; a global `fetch()` interceptor in `base.html` injects the token from a `<meta name="csrf-token">` tag on every same-origin fetch.
- Bearer-token / API-key authenticated endpoints — the inbound webhook endpoints (`POST /api/inbound/<stream_id>/data`, `DELETE /api/inbound/<stream_id>/preview`, `POST /api/inbound/<stream_id>/preview/remap`) and the two coordinate-conversion utility endpoints (`POST /api/convert-latlon-to-mgrs`, `POST /api/convert-mgrs-to-latlon`) are explicitly CSRF-exempt.

**Action required if you have external scripts or integrations** that POST to a session-authenticated TrakBridge endpoint using only a saved session cookie: they will now receive `400 Bad Request`. Migrate to bearer/API-key authentication or include the CSRF token via `X-CSRFToken` header.

### Session cookie attributes changed

`SESSION_COOKIE_HTTPONLY=True` and `SESSION_COOKIE_SAMESITE="Lax"` are now set explicitly in every environment. `SESSION_COOKIE_SECURE=True` in production (env-var override available via `SESSION_COOKIE_SECURE=true|false`). Existing user sessions keep their pre-2.1 cookies until expiry or logout — no forced re-login. Downstream cookie inspectors will see the new attributes on new logins.

### Health / monitoring endpoints now require authentication

Eight previously `@optional_auth` endpoints now return `401` to unauthenticated callers:

- `GET /api/health/detailed`
- `GET /api/health/database`
- `GET /api/health/configuration`
- `GET /api/health/circuit-breakers`
- `GET /api/health/recovery`
- `GET /api/monitoring/dashboard`
- `POST /api/convert-latlon-to-mgrs`
- `POST /api/convert-mgrs-to-latlon`

**`GET /api/status` remains unauthenticated** for container health-check probes. Any external monitoring probe hitting one of the moved endpoints will need to authenticate; if the probe was scraping stream/worker counts, expect a 401 until it presents a session cookie.

### Master key rotation advisory

If your deployment previously ran at `LOG_LEVEL=DEBUG` and generated its master key at runtime (as opposed to loading one from `TB_MASTER_KEY` or `secrets/tb_master_key`), the generated key value was written to the DEBUG log. Rotate the master key via the admin key-rotation UI (Admin → Key Rotation) or `services/key_rotation_service.py`.

### Signed-plugin gate for premium tiers

Plugins whose `plugin.yaml` declares `tier: pro` or `tier: enterprise` must now carry a valid Emfour Ed25519 signature. Unsigned premium plugins are refused at install time.

**No impact on:**

- Community plugins (unsigned or signed) — still install with existing behaviour.
- Plugins already installed (this check runs on new installs; existing installed plugins keep their `is_verified` state).

### Multi-arch container images

GHCR and Docker Hub release publishing now preserves the multi-arch manifest end-to-end. If you were running on Apple Silicon or arm64 servers and seeing amd64 emulation warnings since 2.0.0, pulling the 2.1.0 image will resolve them.

## v1.3.x to v2.0.x Upgrade Notes

Two major additions in 2.0.0: the plugin SDK and the admin plugin manager. Both are backward compatible for existing installs.

### Database migrations

One new migration applies automatically on startup:

- `add_plugin_management_tables` — adds `installed_plugins` (packaged plugin tracking) and `plugin_audit_log` (install/enable/disable/uninstall history) tables.

Existing streams and configuration are unaffected.

### External plugin whitelist gating

Plugins in `external_plugins/` now require an explicit `external_plugins.<plugin_id>` entry in `plugins.yaml` to load. This is auto-populated on startup for pre-existing external plugins, so no manual whitelist edit is required for the upgrade.

**Action required only if:** you deploy new external plugins by dropping files into `external_plugins/` without using the admin plugin manager UI. Add a corresponding `external_plugins.<plugin_id>` line to `plugins.yaml` for the new plugin, or use the plugin manager UI which handles the whitelist automatically.

### Plugin tier gating

`plugin.yaml` gains an optional `tier` field (`community`, `pro`, `enterprise`) enforced at install AND load time. A premium plugin cannot be loaded on a Community deployment even if manually copied into `external_plugins/`.

### Plugin base classes moved to `trakbridge-plugin-sdk`

`plugins/base_plugin.py` is now a re-export shim to `trakbridge-plugin-sdk` on PyPI. Existing in-tree plugins continue to work unchanged. To write a new custom plugin, `pip install trakbridge-plugin-sdk` and subclass a base class — see [Plugin Development Guide](PLUGIN_DEVELOPMENT.md).

### Licence service

A new offline Ed25519 licence service (`services/license_service.py`) maps deployments to Community, Pro, or Enterprise tiers. Community is the default with no licence required — existing deployments continue running as Community with no change. To activate Pro or Enterprise, install a signed licence file via Admin → About → Install Licence.

### v2.0.1 hotfixes

Straight upgrade from 2.0.0. Fixes silent data loss on multi-server streams (RX-side dispatch bug), removes Hypercorn worker recycling that was tearing down stream state every ~30 minutes, and drives full CoT service shutdown on SIGTERM so buffering plugins flush cleanly. No configuration change; `HYPERCORN_MAX_REQUESTS` environment variable is no longer honoured (safe to leave in existing compose files, silently ignored).

## v1.2.x to v1.3.0 Upgrade Notes

### Database Migrations

Two new migrations apply automatically on startup:

- `add_inbound_stream_fields` — adds `stream_mode`, `inbound_api_key`, `inbound_rate_limit`, `inbound_ip_allowlist`, `inbound_preview_mode` columns to the `streams` table
- `add_ca_cert_to_streams` — adds `ca_cert` column to the `streams` table

Both are safe to apply to existing databases. Existing rows receive `NULL` defaults for the new columns — existing streams continue operating unchanged.

**Verify migrations applied cleanly** by checking startup logs:
```bash
docker compose logs trakbridge | grep -i migration
```

### webhook_handler Plugin Removed

The legacy `webhook_handler` plugin has been removed. If you have streams using it:

1. Note your existing message type filters, webhook URL, and any geofence settings
2. Create a new stream using the `outbound_http` plugin
3. Re-enter your endpoint URL, message rules, and geofence in the new plugin UI
4. Disable and delete the old `webhook_handler` stream

The `outbound_http` plugin provides all the same functionality with a cleaner configuration UI.

### New Outbound Plugins

Three new outbound plugins are available for forwarding CoT to external systems:

- **`outbound_http`** — POST/PUT to any HTTP/HTTPS endpoint (JSON, XML, or template)
- **`outbound_mqtt`** — publish to an MQTT broker topic (plain or TLS)
- **`outbound_websocket`** — stream to a WebSocket server

See [Output Plugins Guide](OUTPUT_PLUGINS_GUIDE.md) for configuration details.

### New Inbound Stream Support

Inbound streams allow external devices to push location data to TrakBridge via HTTP POST, or TrakBridge to actively connect to MQTT/WebSocket sources. These are entirely new stream types — no existing configuration is affected.

To create an inbound stream: **Streams → Create Stream → Stream Type: Inbound**.

See [Inbound Streams Guide](INBOUND_STREAMS_GUIDE.md) for details.

### UDP Multicast CoT Bridge

A new `udp_multicast_listener` inbound plugin bridges LAN multicast (e.g. ATAK Mesh SA) to TAK servers across VPN/WAN links. Requires Docker macvlan or host networking — see [INBOUND_STREAMS_GUIDE.md](INBOUND_STREAMS_GUIDE.md) for Docker networking guidance.

### Development Container Change

If you run the dev container (`FLASK_ENV=development`), the entrypoint now starts Hypercorn instead of `flask run --debug`. This eliminates the duplicate TAK connection caused by Werkzeug's reloader spawning a child process. No configuration change needed — it happens automatically.

### TAK Worker Stability Fixes

Several TAK connection bugs that caused 60-second circuit-breaker lockouts after stream saves have been fixed. No operator action required — these fixes are transparent.

## Current Version Features (v1.3.0)

### Inbound Streams
- **HTTP Push**: External devices POST location data to `/api/inbound/<stream_id>/data`
- **Active-Connect**: TrakBridge connects out to MQTT brokers or WebSocket servers
- **UDP Multicast Bridge**: Join a multicast group and forward ATAK Mesh SA to TAK servers
- **Preview Mode**: Capture payloads for field-mapping verification before going live
- **Security**: Per-stream API keys, IP allowlisting, rate limiting, anti-enumeration

### Outbound Plugins
- **OutboundHTTP**: POST/PUT CoT to HTTP/HTTPS endpoints
- **OutboundMQTT**: Publish CoT to MQTT broker topics
- **OutboundWebSocket**: Stream CoT to WebSocket servers
- **Shared pipeline**: Message rules, geofence, deduplication, rate limiting across all three

### Authentication System
- **Multi-Provider Support**: Local database, LDAP/Active Directory, OIDC/SSO
- **Role-Based Access Control**: Viewer, User, Operator, Admin roles
- **Automatic Bootstrap**: Initial admin user created on first startup
- **Web-Only Management**: All user administration through secure web interface

### Plugin Categorisation
- **OSINT Category**: Open source intelligence platforms (Deepstate, LiveUAMap)
- **Tracker Category**: GPS and satellite tracking devices (Garmin, SPOT, Traccar)
- **EMS Category**: Emergency management systems (future expansion)
- **Output Category**: Outbound CoT forwarders (HTTP, MQTT, WebSocket)
- **Inbound Category**: Push-based and active-connect inbound plugins
- **Category API**: RESTful endpoints for category-based plugin discovery

### Security Hardening
- **Field-Level Encryption**: Sensitive configuration data encrypted at rest
- **CSRF Protection**: All HTML forms protected via Flask-WTF
- **HTTP Security Headers**: HSTS, CSP, frame-ancestors via flask-talisman
- **JSON Validation**: Comprehensive input validation and DoS protection
- **Container Security**: Non-root execution and secure defaults
- **Session Management**: Secure session handling with automatic cleanup

### UI Enhancements
- **Categorised Plugin Selection**: Organised data source selection by category
- **Role-Based UI**: Buttons and features shown based on user permissions
- **External Plugin Support**: Docker volume mounting for custom plugins
- **Geofence Map**: Interactive Leaflet map visualisation for output plugin geofence bounds

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
   - Email: support@trakbridge.io

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