# TrakBridge

A web application for bridging tracking devices and services to TAK (Team Awareness Kit) servers. Provides real-time data streaming from various GPS sources to TAK servers for situational awareness.

## Features

- **Team Member COT Support** (NEW in v1.1.0): Display GPS trackers as ATAK team members with role and color customization
- **Custom CoT Attributes** (NEW in v1.1.0): Plugin-extensible system for adding military symbols, custom icons, and arbitrary XML to CoT messages
- **Enhanced Tracker Data** (NEW in v1.1.0): Speed/course extraction from Garmin InReach and Traccar, dynamic battery state mapping for SPOT trackers
- **Multi-Source Integration**: Support for GPS trackers, OSINT platforms, and emergency management systems
- **Inbound Streams**: Receive CoT into TrakBridge via HTTP push (JSON/XML) or active-connect transports (MQTT, WebSocket, UDP multicast)
- **UDP Multicast → TAK Bridge**: Forward LAN multicast Mesh SA (CoT XML and TAK Protocol v1 protobuf, auto-detected) to TAK servers across VPN/WAN where multicast does not route
- **CoT Forwarding Plugins**: Forward CoT from connected TAK servers to external systems via HTTP, MQTT, WebSocket, or UDP multicast
- **Notification Plugins**: Post CoT alerts to messaging platforms — Discord, Slack, IRC
- **Plugin Categorisation**: Organised plugin system with OSINT, Tracker, EMS, CoT Forwarding, Notifications, Inbound, and Bidirectional categories
- **Callsign Mapping**: Custom callsign assignment with per-tracker COT type overrides and team member configuration
- **Authentication System**: Multi-provider authentication (Local, LDAP, OIDC) with role-based access control
- **TAK Server Management**: Configure multiple TAK server connections with certificate support
- **Real-Time Streaming**: Continuous data forwarding with health monitoring and circuit breaker protection
- **Web Interface**: Secure dashboard for stream management and monitoring with categorised plugin selection
- **Role-Based Access**: Viewer, User, Operator, and Admin roles with appropriate UI controls
- **Plugin Architecture**: Extensible system for adding new data sources with external plugin support
- **Enterprise Ready**: Multi-database support, SSL/TLS, backup & recovery, audit logging
- **Security Hardened**: Comprehensive security implementations including field-level encryption
- **Performance Optimised**: uvloop integration, connection pooling, intelligent caching (2-3x performance boost)
- **Single Worker Architecture**: Simplified deployment with single Hypercorn worker for improved efficiency and debugging
- **Real-Time Monitoring**: Integrated dashboard with queue metrics, stream health, and performance graphs
- **Circuit Breaker Protection**: Automatic failure recovery with intelligent retry mechanisms
- **Hot Configuration Reload**: Zero-downtime configuration changes with validation caching
- **Resource Management**: Memory optimisation, leak prevention, and capacity monitoring

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

#### Docker networking note for the UDP Multicast CoT Bridge

The **UDP Multicast CoT Bridge** inbound plugin joins a multicast group on the LAN. By default a container's only NIC is the Docker bridge (typically `172.x.x.x`), and the IGMP join lands there rather than on the host's physical LAN NIC — so no ATAK traffic arrives. Two ways to fix it depending on your setup:

**Option A — `macvlan` network (recommended when behind a reverse proxy like Traefik).** Add a second network on the host's LAN NIC; the container keeps its existing bridge IP for HTTP and gets a real LAN IP for multicast.

```yaml
networks:
  lan_multicast:
    driver: macvlan
    driver_opts:
      parent: eth0           # host's LAN NIC
    ipam:
      config:
        - subnet: 192.168.1.0/24
          gateway: 192.168.1.1
          ip_range: 192.168.1.240/29

services:
  trakbridge:
    networks:
      web: {}                # existing reverse-proxy network
      lan_multicast:
        ipv4_address: 192.168.1.242
```

Then set `bind_interface = 192.168.1.242` in the multicast stream config. Caveat: on Linux the Docker *host* cannot reach the macvlan IP directly on the same NIC — other devices on the LAN can. Not an issue when traffic flows through the reverse proxy on the bridge network.

**Option B — `network_mode: host` (simplest when there's no reverse proxy in front of TrakBridge).**

```yaml
services:
  trakbridge:
    network_mode: host
    # delete `ports:` and `networks:` — host mode bypasses them
```

The container shares the host's network namespace and joins multicast on the host NICs directly. Don't use this if Traefik / nginx is fronting TrakBridge on a Docker network — host mode will bypass it. Also not available on Docker Desktop for Mac/Windows (host networking is not supported there).

In both cases, set `bind_interface` to the explicit LAN IP rather than `0.0.0.0` so the IGMP join is deterministic on multi-homed hosts. See [Inbound Streams Guide](docs/INBOUND_STREAMS_GUIDE.md#built-in-plugin-udp-multicast-cot-bridge) for full troubleshooting.

### Environment Configuration
All configuration is managed directly in the docker-compose.yml file. Edit the `x-environment` section to customise your deployment:

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

  # Security Configuration (NEW in v1.2.0)
  PROXY_TRUSTED: "false"  # Set to "true" if behind reverse proxy (nginx, load balancer)
  TRUSTED_PROXY_COUNT: "0"  # Number of proxies in chain (e.g., "1" for nginx)
  FORCE_HTTPS: "true"  # Force HTTPS redirect (disable with "false" for internal deployments only)

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
4. **Create Stream**: Select from categorised data sources (OSINT, Tracker, EMS) and configure credentials
5. **Start Streaming**: Monitor real-time data flow to your TAK server

## Documentation

- [Documentation Hub](docs/index.md) - Complete documentation index
- [Installation Guide](docs/INSTALLATION.md) - First-time setup and deployment
- [User Guide](docs/USER_GUIDE.md) - End-user procedures and workflows
- [Administrator Guide](docs/ADMINISTRATOR_GUIDE.md) - System administration
- [Authentication Guide](docs/AUTHENTICATION.md) - Multi-provider authentication setup
- [Security Documentation](docs/SECURITY.md) - Comprehensive security guide
- [Plugin Development](docs/PLUGIN_DEVELOPMENT.md) - Creating custom plugins
- [Inbound Streams Guide](docs/INBOUND_STREAMS_GUIDE.md) - Push-based and active-connect inbound plugins, UDP multicast bridge
- [Output Plugins Guide](docs/OUTPUT_PLUGINS_GUIDE.md) - CoT forwarding and notification plugins, custom plugin development
- [API Reference](docs/API_REFERENCE.md) - Complete API documentation
- [Upgrade Guide](docs/UPGRADE_GUIDE.md) - Version upgrade procedures
- [Performance Guide](docs/PERFORMANCE_CONFIGURATION.md) - Performance Tuning Guide
- [Monitoring Guide](docs/MONITORING.md) - Real-time monitoring and dashboards

## Supported Providers and Plugins

### OSINT Platforms
- **Deepstate** - OSINT platform for battlefield intelligence and situational awareness
- **LiveMapUA** - OSINT platform for independent global news and information

### GPS Trackers
- **Garmin InReach** - Satellite communicators and GPS tracking devices
- **SPOT Tracker** - GPS tracking devices and emergency communicators
- **Traccar** - Open-source GPS tracking platform and server

### Inbound Plugins (receive data into TrakBridge)

- **JSON Receiver** - HTTP push with configurable dot-notation field mapping
- **XML Receiver** - HTTP push with XPath-based field extraction
- **HTTP Location Endpoint** - Lightweight HTTP push for ad-hoc devices
- **MQTT / WebSocket Client** - Active-connect MQTT broker or WebSocket source
- **UDP Multicast CoT Bridge** - Joins a multicast group and forwards CoT XML or TAK Protocol v1 (Mesh SA protobuf) to TAK servers; bridges LAN multicast over VPN/WAN

### CoT Forwarding Plugins (forward CoT from TAK to external systems)

- **OutboundHTTP** - POST/PUT JSON, XML, or template payloads to an endpoint
- **OutboundMQTT** - Publish CoT to an MQTT broker topic with TLS support
- **OutboundWebSocket** - Push CoT to a WebSocket server with automatic reconnect
- **UDP Multicast Publisher** - Publish CoT to a UDP multicast group on the LAN

### Notification Plugins (post CoT alerts to messaging platforms)

- **Discord** - Rich embeds or plain text via incoming webhook
- **Slack** - Block Kit formatted messages via incoming webhook
- **IRC** - Plain text or templated messages to an IRC channel

### External Plugin Support
- Docker volume mount support for custom plugins
- Plugin categorisation system for organised management
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

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Support

- [Report Issues](../../issues)
- [Discussions](../../discussions)
- [Documentation](../../wiki)
- [Troubleshooting Guide](../../wiki/Troubleshooting)

---

**TrakBridge v1.3.0** - Production-ready GPS tracking data bridge for TAK servers with inbound streams, CoT forwarding, notifications, UDP multicast bridging, enterprise performance, monitoring, and reliability features.
