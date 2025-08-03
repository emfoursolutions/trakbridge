# TrakBridge - GPS Tracking Data Bridge

[![Docker Image Version](https://img.shields.io/docker/v/emfoursolutions/trakbridge?sort=semver)](https://hub.docker.com/r/emfoursolutions/trakbridge)
[![Docker Image Size](https://img.shields.io/docker/image-size/emfoursolutions/trakbridge/latest)](https://hub.docker.com/r/emfoursolutions/trakbridge)
[![Docker Pulls](https://img.shields.io/docker/pulls/emfoursolutions/trakbridge)](https://hub.docker.com/r/emfoursolutions/trakbridge)

TrakBridge is a GPS tracking data bridge that forwards location data from various GPS providers to TAK (Team Awareness Kit) servers. It provides a unified interface for integrating multiple GPS tracking systems with military and tactical communication networks.

## 🚀 Quick Start

### Basic Deployment

```bash
# Pull the latest image
docker pull emfoursolutions/trakbridge:latest

# Run with SQLite (for testing)
docker run -d \
  --name trakbridge \
  -p 5000:5000 \
  -e FLASK_ENV=production \
  -e DB_TYPE=sqlite \
  -v trakbridge_data:/app/data \
  emfoursolutions/trakbridge:latest
```

### Production Deployment with PostgreSQL

```bash
# Create a network
docker network create trakbridge-network

# Start PostgreSQL
docker run -d \
  --name trakbridge-postgres \
  --network trakbridge-network \
  -e POSTGRES_DB=trakbridge \
  -e POSTGRES_USER=trakbridge \
  -e POSTGRES_PASSWORD=your-secure-password \
  -v postgres_data:/var/lib/postgresql/data \
  postgres:15-alpine

# Start TrakBridge
docker run -d \
  --name trakbridge \
  --network trakbridge-network \
  -p 5000:5000 \
  -e FLASK_ENV=production \
  -e DB_TYPE=postgresql \
  -e DB_HOST=trakbridge-postgres \
  -e DB_NAME=trakbridge \
  -e DB_USER=trakbridge \
  -e DB_PASSWORD=your-secure-password \
  -e SECRET_KEY=your-secret-key \
  -e TB_MASTER_KEY=your-master-key \
  -v trakbridge_data:/app/data \
  -v trakbridge_logs:/app/logs \
  emfoursolutions/trakbridge:latest
```

### Docker Compose Deployment

```yaml
version: '3.8'

services:
  trakbridge:
    image: emfoursolutions/trakbridge:latest
    container_name: trakbridge
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      FLASK_ENV: production
      DB_TYPE: postgresql
      DB_HOST: postgres
      DB_NAME: trakbridge
      DB_USER: trakbridge
      DB_PASSWORD_FILE: /run/secrets/db_password
      SECRET_KEY_FILE: /run/secrets/secret_key
      TB_MASTER_KEY_FILE: /run/secrets/tb_master_key
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
    secrets:
      - db_password
      - secret_key
      - tb_master_key
    depends_on:
      - postgres

  postgres:
    image: postgres:15-alpine
    container_name: trakbridge-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: trakbridge
      POSTGRES_USER: trakbridge
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    secrets:
      - db_password

volumes:
  postgres_data:

secrets:
  db_password:
    file: ./secrets/db_password
  secret_key:
    file: ./secrets/secret_key
  tb_master_key:
    file: ./secrets/tb_master_key
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_ENV` | Flask environment (development/production) | `production` |
| `DB_TYPE` | Database type (sqlite/postgresql/mysql) | `sqlite` |
| `DB_HOST` | Database host | `localhost` |
| `DB_PORT` | Database port | `5432` |
| `DB_NAME` | Database name | `trakbridge` |
| `DB_USER` | Database user | `trakbridge` |
| `DB_PASSWORD` | Database password | - |
| `SECRET_KEY` | Flask secret key | - |
| `TB_MASTER_KEY` | TrakBridge encryption key | - |
| `LOG_LEVEL` | Logging level | `INFO` |
| `MAX_WORKER_THREADS` | Maximum worker threads | `4` |

### Volumes

| Volume | Description |
|--------|-------------|
| `/app/data` | Application data and SQLite database |
| `/app/logs` | Application logs |
| `/app/config` | Configuration files |
| `/app/external_plugins` | External plugin directory |

### Exposed Ports

| Port | Description |
|------|-------------|
| `5000` | Main web interface and API |

## 🔌 Supported GPS Providers

- **Garmin InReach**: Satellite communication devices
- **SPOT Tracker**: Satellite GPS messengers
- **Traccar**: Open-source GPS tracking platform
- **Deepstate**: Military and tactical GPS systems
- **Custom Plugins**: Extensible plugin architecture

## 🔒 Security Features

- **Enterprise Security**: Comprehensive security hardening
- **Authentication**: Multi-provider authentication system
- **Encryption**: Field-level encryption for sensitive data
- **Input Validation**: Comprehensive JSON validation with DoS protection
- **Container Security**: Non-root user execution by default
- **Security Headers**: Complete security header implementation

## 🏗️ Architecture

TrakBridge follows a plugin-based architecture:

- **Flask Web Framework**: RESTful API and web interface
- **Plugin System**: Extensible GPS provider integration
- **Stream Processing**: Multi-threaded data processing
- **TAK Integration**: Native Cursor on Target (CoT) support
- **Database Layer**: SQLAlchemy ORM with migration support

## 📋 Health Checks

The container includes comprehensive health checks:

```bash
# Basic health check
curl http://localhost:5000/api/health

# Detailed health status
curl http://localhost:5000/api/health/detailed
```

## 🏷️ Available Tags

| Tag | Description |
|-----|-------------|
| `latest` | Latest stable release |
| `stable` | Alias for latest stable |
| `v1.x` | Specific version releases |
| `develop` | Development builds (not for production) |

## 📖 Documentation

- [Installation Guide](https://github.com/emfoursolutions/trakbridge/blob/main/docs/INSTALLATION.md)
- [Plugin Development](https://github.com/emfoursolutions/trakbridge/blob/main/docs/DOCKER_PLUGINS.md)
- [Security Guide](https://github.com/emfoursolutions/trakbridge/blob/main/docs/DOCKER_SECURITY.md)
- [Authentication Setup](https://github.com/emfoursolutions/trakbridge/blob/main/docs/AUTHENTICATION.md)

## 🆘 Support

- **GitHub Issues**: [Report bugs and request features](https://github.com/emfoursolutions/trakbridge/issues)
- **GitHub Discussions**: [Community support and questions](https://github.com/emfoursolutions/trakbridge/discussions)
- **Documentation**: [Comprehensive guides and API docs](https://github.com/emfoursolutions/trakbridge/tree/main/docs)

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](https://github.com/emfoursolutions/trakbridge/blob/main/LICENSE) file for details.

## 🏢 Vendor

**Emfour Solutions** - Tactical Communications and GPS Integration Specialists

---

*TrakBridge bridges the gap between civilian GPS tracking systems and military tactical networks, providing seamless integration for enhanced situational awareness.*