# TrakBridge Installation Guide

## Overview

TrakBridge is a comprehensive GPS tracking data bridge that forwards location data from various providers to TAK (Team Awareness Kit) servers. This guide covers first-time installation for both Docker and development environments.

**Key Features:**
- **Multi-Provider Authentication**: OIDC, LDAP, and local database authentication
- **Role-Based Access Control**: Viewer, User, Operator, and Admin roles
- **Automatic Initial Admin**: Bootstrap service creates initial admin on first startup
- **Plugin Architecture**: Extensible system for GPS providers
- **Enterprise Ready**: SSL/TLS, backup & recovery, multi-database support

## Prerequisites

### System Requirements
- **CPU**: 2+ cores recommended
- **RAM**: 2GB minimum, 4GB recommended
- **Storage**: 10GB minimum, 50GB recommended for logs and data
- **Network**: Internet access for GPS provider APIs and TAK server connections

### Software Requirements

#### Docker Installation (Recommended)
- Docker Engine 20.10+
- Docker Compose v2.0+
- Port 8080 available (or custom port)

#### Development Installation
- Python 3.10+
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

# Advanced setup with PostgreSQL and Nginx
wget https://raw.githubusercontent.com/emfoursolutions/trakbridge/main/docker-compose-production.yml
wget https://raw.githubusercontent.com/emfoursolutions/trakbridge/main/init/setup.sh
chmod +x setup.sh
```

3. **Basic deployment**:
```bash
# Start with SQLite (development/testing)
docker-compose up -d

# Access at http://localhost:8080
```

4. **Production deployment** with PostgreSQL and Nginx:
```bash
# Setup with SSL certificate
./setup.sh --enable-nginx --nginx-ssl yourdomain.com

# Start production stack
docker-compose --profile postgres --profile nginx up -d

# Access at https://yourdomain.com
```

### Docker Configuration

#### Environment Variables
Create `.env` file for configuration:
```bash
# Application settings
FLASK_ENV=production
SECRET_KEY=your-super-secret-key-change-this-in-production

# Database (for PostgreSQL setup)
POSTGRES_DB=trakbridge
POSTGRES_USER=trakbridge
POSTGRES_PASSWORD=secure-database-password

# Encryption key for sensitive data
TRAKBRIDGE_ENCRYPTION_KEY=your-32-character-encryption-key

# Authentication (optional - see authentication setup)
LDAP_BIND_PASSWORD=your-ldap-password
OIDC_CLIENT_SECRET=your-oidc-client-secret
```

#### Volume Mounts
The Docker setup uses these persistent volumes:
```yaml
volumes:
  - ./config:/app/external_config      # Configuration files
  - ./data:/app/data                   # Database and application data
  - ./logs:/app/logs                   # Log files
  - ./certs:/app/certs                 # TAK server certificates
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
pip install -r requirements.txt

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

# Access at http://localhost:8080
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
   - Development: http://localhost:8080

3. **Login and change password**:
   - Use the default credentials above
   - You'll be **forced to change the password** on first login
   - Set a strong password for your admin account

### Security Setup Checklist

#### ✅ Required Security Steps
1. **Change default admin password** (forced on first login)
2. **Set strong SECRET_KEY** in production
3. **Generate secure TRAKBRIDGE_ENCRYPTION_KEY** (32 characters)
4. **Configure HTTPS** for production deployments
5. **Review firewall settings** and exposed ports

#### ✅ Configuration Files Security
Docker installations automatically create configuration files in `./config/`:
- `authentication.yaml` - Authentication provider settings
- `app.yaml` - Application configuration
- `database.yaml` - Database connection settings

**Important**: These files may contain sensitive configuration. Secure them appropriately:
```bash
chmod 600 ./config/*.yaml
```

### Authentication Configuration

#### Option A: Local Authentication Only (Default)
No additional configuration required. Users are managed through the web interface.

#### Option B: LDAP/Active Directory Integration
1. **Edit authentication configuration**:
```bash
# Docker installation
nano ./config/authentication.yaml

# Development installation  
nano config/settings/authentication.yaml
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
```

3. **Set LDAP credentials**:
```bash
export LDAP_BIND_PASSWORD="your-service-account-password"
```

#### Option C: OIDC/SSO Integration
1. **Register application** with your identity provider (Azure AD, Okta, etc.)

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
export OIDC_CLIENT_SECRET="your-oidc-client-secret"
```

## Database Configuration

### SQLite (Default)
No additional configuration needed. Database file stored in:
- Docker: `./data/trakbridge.db`
- Development: `instance/trakbridge.db`

### PostgreSQL (Production)
1. **Docker setup** automatically configures PostgreSQL
2. **Manual PostgreSQL setup**:
```yaml
# config/settings/database.yaml
database:
  url: "postgresql://username:password@localhost:5432/trakbridge"
  pool_size: 10
  pool_recycle: 3600
```

### Database Migrations
The application automatically runs database migrations on startup. For manual management:
```bash
# Check migration status
python -m flask db current

# Apply pending migrations
python -m flask db upgrade

# Create new migration (development)
python -m flask db migrate -m "Description of changes"
```

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

### 2. Configure GPS Providers
1. **Navigate to Streams** → Create Stream
2. **Select GPS provider**: Garmin InReach, SPOT, Traccar, etc.
3. **Configure credentials** and polling settings
4. **Test connection** before saving

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

2. **Verify credentials** in `.env` file

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

1. **Check application logs**: `docker-compose logs` or `logs/app.log`
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