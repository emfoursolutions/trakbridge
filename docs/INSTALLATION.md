# TrakBridge Installation Guide

## Overview

TrakBridge is a comprehensive data stream bridge that forwards location data from various providers to TAK (Team Awareness Kit) servers. This guide covers first-time installation for both Docker and development environments.

**Key Features:**
- **Multi-Provider Authentication**: OIDC, LDAP, and local database authentication
- **Role-Based Access Control**: Viewer, User, Operator, and Admin roles
- **Plugin Categorization**: Dynamic Categories for organized data source management
- **Automatic Initial Admin**: Bootstrap service creates initial admin on first startup
- **Plugin Architecture**: Extensible system with external plugin support via Docker volumes
- **Security Hardened**: Field-level encryption, JSON validation, and comprehensive security controls
- **Enterprise Ready**: SSL/TLS, backup & recovery, multi-database support

### Software Requirements

#### Docker Installation (Recommended)
- Docker Engine 20.10+
- Docker Compose v2.0+
- Port 8080 available (or custom port)

#### Development Installation
- Python 3.12+
- pip package manager
- Git for source code
- SQLite (included with Python) or PostgreSQL/MySQL

## Installation Methods

## Option 1: Docker Installation (Recommended)

### Quick Start with Docker

1. **Create installation directory**:
```bash
mkdir trakbridge && cd trakbridge
```

2. **Download setup files**:
```bash
# Basic setup
wget https://raw.githubusercontent.com/emfoursolutions/trakbridge/main/docker-compose.yml
wget https://raw.githubusercontent.com/emfoursolutions/trakbridge/refs/heads/main/scripts/setup.sh
chmod +x setup.sh
```

3. **Basic deployment**:
```bash
# Start with SQLite (development/testing)
./setup.sh
docker compose up -d

# Access at http://yourdomain.com:5000
```

4. **Production deployment** with PostgreSQL and Nginx:
```bash
# Setup with SSL certificate
./setup.sh --enable-nginx --nginx-ssl yourdomain.com

# Start production stack
docker compose --profile postgres --profile nginx up -d

# Access at https://yourdomain.com
```

### Docker Configuration

#### Environment Configuration
All configuration is managed directly in the docker-compose.yml file. Edit the `x-environment` section to customize your deployment:

```yaml
# Edit these values in docker-compose.yml
x-environment: &common-environment
  # Application Settings
  FLASK_ENV: "production"
  USER_ID: "1000"  # Change if needed for filesystem permissions
  GROUP_ID: "1000"  # Change if needed for filesystem permissions
  
  # Database Configuration (choose one)
  DB_TYPE: "postgresql"  # postgresql, mysql, or sqlite
  DB_HOST: "postgres"
  DB_NAME: "trakbridge"
  DB_USER: "trakbridge"
  
  # LDAP Authentication (set LDAP_ENABLED to "true" to enable)
  LDAP_ENABLED: "false"
  LDAP_SERVER: "ldap://your-ad-server.company.com"  # Update for your LDAP server
  LDAP_BIND_DN: "CN=trakbridge,OU=Service Accounts,DC=company,DC=com"  # Update for your domain
  
  # OIDC/SSO Authentication (set OIDC_ENABLED to "true" to enable)
  OIDC_ENABLED: "false"
  OIDC_ISSUER: "https://your-identity-provider.com"  # Update for your OIDC provider
  OIDC_CLIENT_ID: "trakbridge-client"  # Update with your client ID
  OIDC_REDIRECT_URI: "https://trakbridge.company.com/auth/oidc/callback"  # Update for your domain
```

#### Docker Secrets Setup
Sensitive credentials are managed through Docker secrets. These are created by the setup.sh script.
If LDAP or OIDC authentication backends are being used the password / OIDC client secret must be inserted into their respective secret file.

```bash
# LDAP password (if using LDAP authentication)
echo "your-ldap-bind-password" > secrets/ldap_bind_password

# OIDC client secret (if using OIDC authentication)
echo "your-oidc-client-secret" > secrets/oidc_client_secret
```

#### Volume Mounts
The Docker setup uses these persistent volumes:
```yaml
volumes:
  - ./config:/app/external_config      # Configuration files
  - ./data:/app/data                   # Database and application data
  - ./logs:/app/logs                   # Log files
  - ./certs:/app/certs                 # TAK server certificates
  - ./plugins:/app/external_plugins  # External custom plugins (optional)
```

#### External Plugin Support
To use external plugins, copy them into the ./plugins directory:
```bash
cp my_custom_tracker.py ./plugins
```

Configure plugin modules in `config/plugins.yaml`:
```yaml
allowed_plugin_modules:
  - external_plugins.my_custom_tracker
```

See [Docker Plugin Documentation](DOCKER_PLUGINS.md) for complete setup instructions.

### Reverse Proxy Setup

TrakBridge includes built-in support for reverse proxies (Apache, Nginx, etc.) with automatic handling of proxy headers.

#### Apache Configuration

**Basic reverse proxy setup:**

```apache
<VirtualHost *:80>
    ServerName your-domain.com
    
    # Redirect HTTP to HTTPS (recommended)
    Redirect permanent / https://your-domain.com/
</VirtualHost>

<VirtualHost *:443>
    ServerName your-domain.com
    
    # SSL Configuration
    SSLEngine on
    SSLCertificateFile /path/to/your/certificate.crt
    SSLCertificateKeyFile /path/to/your/private.key
    
    # Reverse Proxy Configuration
    ProxyPreserveHost On
    ProxyRequests Off
    
    # Essential proxy headers for TrakBridge
    ProxyPassReverse / http://localhost:8080/
    ProxyPass / http://localhost:8080/
    
    # Set required headers for proper redirect handling
    ProxyPassReverse / http://localhost:8080/
    ProxyPassReverseInterpolateEnv On
    
    # WebSocket support (if needed)
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteCond %{HTTP:Connection} upgrade [NC]
    RewriteRule ^/?(.*) "ws://localhost:8080/$1" [P,L]
    
    # Security headers
    Header always set X-Frame-Options DENY
    Header always set X-Content-Type-Options nosniff
    Header always set Referrer-Policy strict-origin-when-cross-origin
</VirtualHost>
```

**Required Apache modules:**
```bash
sudo a2enmod proxy
sudo a2enmod proxy_http
sudo a2enmod ssl
sudo a2enmod headers
sudo a2enmod rewrite
```

#### Nginx Configuration (Alternative)

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    # SSL Configuration
    ssl_certificate /path/to/your/certificate.crt;
    ssl_certificate_key /path/to/your/private.key;
    
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

#### Docker with Reverse Proxy

If running TrakBridge in Docker behind a reverse proxy, ensure the container port is accessible:

```yaml
services:
  trakbridge:
    image: emfoursolutions/trakbridge:latest
    ports:
      - "127.0.0.1:8080:8080"  # Only bind to localhost for security
    environment:
      - FLASK_ENV=production
```

#### Troubleshooting Reverse Proxy Issues

**Common Issues:**
- **Redirects to wrong port**: Fixed automatically by ProxyFix middleware
- **HTTPS redirects to HTTP**: Ensure `X-Forwarded-Proto` header is set
- **Authentication redirects fail**: Verify `X-Forwarded-Host` is configured
- **WebSocket connections fail**: Enable WebSocket proxy support

**Testing your reverse proxy setup:**
```bash
# Test that proxy headers are working
curl -H "X-Forwarded-Proto: https" -H "X-Forwarded-Host: your-domain.com" http://localhost:8080/

# Check application logs for any redirect issues
docker logs your-trakbridge-container
```

## Option 2: Development Installation

### Local Python Setup

1. **Clone repository**:
```bash
git clone https://github.com/emfoursolutions/trakbridge.git
cd trakbridge
```

2. **Create virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**:
```bash
pip install .

# For development with testing tools
pip install -e ".[dev]"
```

4. **Initialize database**:
```bash
python -m flask db upgrade
```

5. **Start application**:
```bash
# Development server
python app.py

# Access at http://localhost:5000
```

### Development Configuration

1. **Copy configuration templates**:
```bash
cp config/settings/authentication.yaml.example config/settings/authentication.yaml
cp config/settings/app.yaml.example config/settings/app.yaml
```

2. **Set environment variables**:
```bash
export FLASK_ENV=development
export SECRET_KEY=dev-secret-key
export TRAKBRIDGE_ENCRYPTION_KEY=dev-32-character-encryption-key-123
```

## Initial Setup and Configuration

### First-Time Login

TrakBridge automatically creates an initial admin user on first startup:

1. **Default credentials** (automatically created):
   - **Username**: `admin`
   - **Password**: `TrakBridge-Setup-2025!`

2. **Access the application**:
   - Docker: http://localhost:8080 or https://yourdomain.com
   - Development: http://localhost:5000

3. **Login and change password**:
   - Use the default credentials above
   - You'll be **forced to change the password** on first login
   - Set a strong password for your admin account

## Post-Installation Tasks

### 1. User Management Setup
1. **Login as admin** using default credentials
2. **Change admin password** (forced on first login)
3. **Create additional users** (Admin → User Management → Create User)
4. **Assign appropriate roles**:
   - **Viewer**: Read-only access
   - **User**: Basic access with profile management
   - **Operator**: Can manage streams and TAK servers
   - **Admin**: Full system administration

### 2. Configure Data Sources
1. **Navigate to Streams** → Create Stream
2. **Select category**: OSINT, Tracker, or EMS from the dropdown
3. **Choose provider**: Select from categorized options (Deepstate, Garmin InReach, SPOT, Traccar, etc.)
4. **Configure credentials** and settings specific to the selected provider
5. **Test connection** before saving to verify functionality

### 3. Configure TAK Servers
1. **Navigate to TAK Servers** → New Server
2. **Add server details**: hostname, port, protocol
3. **Upload certificates** if using SSL/TLS
4. **Test connection** to verify connectivity

### 4. Monitor System Health
1. **Dashboard**: Real-time status overview
2. **Health endpoint**: `http://your-server:8080/api/health`
3. **Logs**: Available in Docker logs or `logs/` directory

## Backup and Recovery

### Configuration Backup
```bash
# Docker installation
tar -czf trakbridge-config-$(date +%Y%m%d).tar.gz ./config ./data

# Development installation
tar -czf trakbridge-config-$(date +%Y%m%d).tar.gz config/ instance/
```

### Database Backup
```bash
# SQLite
cp ./data/trakbridge.db ./backups/trakbridge-$(date +%Y%m%d).db

# PostgreSQL (Docker)
docker-compose exec postgres pg_dump -U trakbridge trakbridge > backup-$(date +%Y%m%d).sql
```

### Recovery
1. **Stop application**
2. **Restore configuration and data files**
3. **Restart application**
4. **Verify operation** through health endpoint

## Troubleshooting

### Common Installation Issues

#### Port Already in Use
```bash
# Check what's using port 8080
sudo lsof -i :8080

# Change port in docker-compose.yml
services:
  trakbridge:
    ports:
      - "8081:8080"  # Use port 8081 instead
```

#### Permission Denied (Docker)
```bash
# Fix file permissions
sudo chown -R $(id -u):$(id -g) ./config ./data ./logs

# Or run with correct user
docker-compose run --user $(id -u):$(id -g) trakbridge
```

#### Database Connection Issues
1. **Check database logs**:
```bash
docker-compose logs postgres
```

2. **Verify credentials** in docker-compose.yml and secrets files

3. **Test connection manually**:
```bash
docker-compose exec postgres psql -U trakbridge -d trakbridge
```

#### Authentication Problems
1. **Check configuration files**:
```bash
# Validate configuration
python scripts/manage_config.py validate --environment production
```

2. **Test providers individually**:
```bash
# Development installation
python -m flask auth test-ldap --username testuser
python -m flask auth test-oidc
```

3. **Review logs** for detailed error information:
```bash
tail -f logs/app.log | grep -i auth
```

### Getting Help

1. **Check application logs**: `docker-compose logs` or `logs/trakbridge-version.log`
2. **Health check endpoint**: `curl http://localhost:8080/api/health`
3. **Configuration validation**: Use CLI tools in `scripts/`
4. **GitHub Issues**: Report bugs and get support
5. **Documentation**: Comprehensive guides in `docs/` directory

## Next Steps

After successful installation:

1. **Read the User Guide**: Learn about creating streams and managing TAK servers
2. **Configure Authentication**: Set up LDAP or OIDC if needed
3. **Set up Monitoring**: Configure log aggregation and health monitoring
4. **Plan Backups**: Implement regular backup procedures
5. **Review Security**: Follow security best practices for production

## Support and Community

- **Documentation**: [GitHub Wiki](../../wiki)
- **Issues**: [Report Problems](../../issues)  
- **Discussions**: [Community Forum](../../discussions)
- **Email Support**: support@emfoursolutions.com.au

---

**Security Notice**: Always change default passwords, use HTTPS in production, and keep the system updated with latest security patches.