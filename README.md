# TrakBridge

A web application for bridging tracking devices and services to TAK (Team Awareness Kit) servers. Provides real-time data streaming from various GPS sources to TAK servers for situational awareness.

## Features

- **Multi-Source Integration**: Support for GPS trackers, OSINT platforms, and emergency management systems
- **Plugin Categorization**: Organized plugin system with OSINT, Tracker, and EMS categories
- **Authentication System**: Multi-provider authentication (Local, LDAP, OIDC) with role-based access control
- **TAK Server Management**: Configure multiple TAK server connections with certificate support
- **Real-Time Streaming**: Continuous data forwarding with health monitoring and circuit breaker protection
- **Web Interface**: Secure dashboard for stream management and monitoring with categorized plugin selection
- **Role-Based Access**: Viewer, User, Operator, and Admin roles with appropriate UI controls
- **Plugin Architecture**: Extensible system for adding new data sources with external plugin support
- **Enterprise Ready**: Multi-database support, SSL/TLS, backup & recovery, audit logging
- **Security Hardened**: Comprehensive security implementations including field-level encryption
- **Performance Optimized**: uvloop integration, connection pooling, intelligent caching (2-3x performance boost)
- **Single Worker Architecture**: Simplified deployment with single Hypercorn worker for improved efficiency and debugging
- **Real-Time Monitoring**: Integrated dashboard with queue metrics, stream health, and performance graphs
- **Circuit Breaker Protection**: Automatic failure recovery with intelligent retry mechanisms
- **Hot Configuration Reload**: Zero-downtime configuration changes with validation caching
- **Resource Management**: Memory optimization, leak prevention, and capacity monitoring

<img width="1900" height="690" alt="image" src="https://github.com/user-attachments/assets/d09d3e17-de62-4524-a0d6-d1990c827ac7" />


## Quick Start

### Docker (Recommended)

```bash
# Download setup files
wget https://raw.githubusercontent.com/emfoursolutions/trakbridge/main/docker-compose.yml
wget https://raw.githubusercontent.com/emfoursolutions/trakbridge/refs/heads/main/scripts/setup.sh

# Setup and run
chmod +x setup.sh
./setup.sh --enable-nginx --nginx-ssl yourdomain.com
docker-compose --profile postgres --profile nginx up -d
```

Access the web interface at `https://yourdomain.com`

**First-time login**:
- Username: `admin`
- Password: `TrakBridge-Setup-2025!`
- You'll be forced to change the password on first logins

### Environment Configuration
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

### Python Development

```bash
git clone <repository-url>
cd trakbridge
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install .
hypercorn app.py  # Single worker deployment for optimal performance
```

## Basic Usage

1. **Login**: Use default admin credentials (change password on first login)
2. **Create Users**: Set up user accounts with appropriate roles (Admin → User Management)
3. **Configure TAK Server**: Add your TAK server details and certificates
4. **Create Stream**: Select from categorized data sources (OSINT, Tracker, EMS) and configure credentials
5. **Start Streaming**: Monitor real-time data flow to your TAK server

## Documentation

- [Documentation Hub](docs/index.md) - Complete documentation index
- [Installation Guide](docs/INSTALLATION.md) - First-time setup and deployment
- [User Guide](docs/USER_GUIDE.md) - End-user procedures and workflows
- [Administrator Guide](docs/ADMINISTRATOR_GUIDE.md) - System administration
- [Authentication Guide](docs/AUTHENTICATION.md) - Multi-provider authentication setup
- [Security Documentation](docs/SECURITY.md) - Comprehensive security guide
- [Plugin Development](docs/PLUGIN_DEVELOPMENT.md) - Creating custom plugins
- [API Reference](docs/API_REFERENCE.md) - Complete API documentation
- [Upgrade Guide](docs/UPGRADE_GUIDE.md) - Version upgrade procedures
- [Performance Guide](docs/PERFORMANCE_CONFIGURATION.md) - Performance Tuning Guide
- [Monitoring Guide](docs/MONITORING.md) - Real-time monitoring and dashboards

## Supported Providers

### OSINT Platforms
- **Deepstate** - OSINT platform for battlefield intelligence and situational awareness

### GPS Trackers  
- **Garmin InReach** - Satellite communicators and GPS tracking devices
- **SPOT Tracker** - GPS tracking devices and emergency communicators
- **Traccar** - Open-source GPS tracking platform and server

### External Plugin Support
- Docker volume mount support for custom plugins
- Plugin categorization system for organized management
- API endpoints for category-based plugin discovery

## Health Check & Monitoring

```bash
# Basic health check
curl -f https://yourdomain.com/api/health

# Real-time monitoring dashboard
curl https://yourdomain.com/api/monitoring/dashboard
```

The v1.0.0 release includes comprehensive monitoring capabilities:
- **Queue Metrics**: Real-time queue sizes, throughput, latency, and error rates
- **Stream Health**: Plugin API response times and TAK connection status
- **Performance Tracking**: Historical performance data with regression detection
- **Resource Monitoring**: Memory usage tracking and leak detection
- **Circuit Breaker Status**: External dependency health and failure recovery

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Support

- [Report Issues](../../issues)
- [Discussions](../../discussions)
- [Documentation](../../wiki)
- [Troubleshooting Guide](../../wiki/Troubleshooting)

---

**TrakBridge v1.0.0** - Production-ready GPS tracking data bridge for TAK servers with enterprise performance, monitoring, and reliability features.