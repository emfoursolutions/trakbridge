# TrakBridge

A comprehensive web application for bridging tracking devices and services to TAK (Team Awareness Kit) servers. Provides real-time data streaming from various GPS sources to TAK servers for situational awareness.

## Features

- **Multi-Source Integration**: Support for GPS trackers, OSINT platforms, and emergency management systems
- **Plugin Categorization**: Organized plugin system with OSINT, Tracker, and EMS categories
- **Authentication System**: Multi-provider authentication (Local, LDAP, OIDC) with role-based access control
- **TAK Server Management**: Configure multiple TAK server connections with certificate support
- **Real-Time Streaming**: Continuous data forwarding with health monitoring
- **Web Interface**: Secure dashboard for stream management and monitoring with categorized plugin selection
- **Role-Based Access**: Viewer, User, Operator, and Admin roles with appropriate UI controls
- **Plugin Architecture**: Extensible system for adding new data sources with external plugin support
- **Enterprise Ready**: Multi-database support, SSL/TLS, backup & recovery, audit logging
- **Security Hardened**: Comprehensive security implementations including field-level encryption

<img width="1900" height="690" alt="image" src="https://github.com/user-attachments/assets/d09d3e17-de62-4524-a0d6-d1990c827ac7" />


## Quick Start

### Docker (Recommended)

```bash
# Download setup files
wget https://raw.githubusercontent.com/emfoursolutions/trakbridge/main/docker-compose.yml
wget https://raw.githubusercontent.com/emfoursolutions/trakbridge/main/init/setup.sh

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

### Python Development

```bash
git clone <repository-url>
cd trakbridge
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install .
hypercorn app.py
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

## Health Check

```bash
curl -f https://yourdomain.com/api/health
```

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

**TrakBridge** - Professional GPS tracking data bridge for TAK servers.