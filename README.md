# TrakBridge

A comprehensive web application for bridging tracking devices and services to TAK (Team Awareness Kit) servers. Provides real-time data streaming from various GPS sources to TAK servers for situational awareness.

## Features

- **Multi-Source Integration**: Support for Garmin InReach, SPOT Trackers, Traccar, and more
- **TAK Server Management**: Configure multiple TAK server connections with certificate support
- **Real-Time Streaming**: Continuous data forwarding with health monitoring
- **Web Interface**: Dashboard for stream management and monitoring
- **Plugin Architecture**: Extensible system for adding new data sources
- **Enterprise Ready**: Multi-database support, SSL/TLS, backup & recovery

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

### Python Development

```bash
git clone <repository-url>
cd trakbridge
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Basic Usage

1. **Configure TAK Server**: Add your TAK server details and certificates
2. **Create Stream**: Select a GPS provider and configure credentials
3. **Start Streaming**: Monitor real-time data flow to your TAK server

## Documentation

- [Installation Guide](../../wiki/Installation)
- [Configuration Guide](../../wiki/Configuration-Guide)
- [Plugin Development](../../wiki/Plugin-Development)
- [API Reference](../../wiki/API-Reference)
- [Troubleshooting](../../wiki/Troubleshooting)

## Supported Providers

- **Garmin InReach** - Satellite communicators
- **SPOT Tracker** - GPS tracking devices
- **Traccar** - Open-source GPS tracking platform

*Coming Soon: Deepstate, LiveUAMap*

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

⭐ **Star this repo** if you find it useful!