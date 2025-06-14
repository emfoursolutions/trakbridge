# TrakBridge

A comprehensive web application for bridging tracking devices and services to TAK (Team Awareness Kit) servers. This application provides a centralized platform for managing multiple data streams and forwarding them to TAK servers for real-time situational awareness.

## Features

### Core Functionality
- **Multi-Source Stream Integration**: Support for various Stream providers through a plugin architecture
- **TAK Server Management**: Configure and manage multiple TAK server connections
- **Real-Time Data Streaming**: Continuous GPS data forwarding to TAK servers
- **Certificate Management**: Full support for P12/PKCS12 client certificates for secure TAK connections
- **Stream Management**: Start, stop, restart, and monitor individual GPS streams
- **Connection Testing**: Built-in tools to test GPS sources and TAK server connectivity

### Web Interface
- **Dashboard**: Overview of all streams and their status
- **Stream Configuration**: Easy-to-use forms for configuring GPS data sources
- **Real-Time Monitoring**: Live status updates and error reporting
- **Bulk Operations**: Start/stop multiple streams simultaneously
- **Health Checks**: Automated monitoring and diagnostics

### Technical Features
- **Plugin Architecture**: Extensible system for adding new GPS providers
- **Async Processing**: High-performance asynchronous data processing
- **Database Persistence**: SQLite database for configuration storage
- **Thread-Safe Operations**: Concurrent stream processing
- **Comprehensive Logging**: Detailed logging for troubleshooting
- **Error Recovery**: Automatic retry mechanisms and error handling

## Installation

### Prerequisites
- Python 3.10 or higher
- pip (Python package installer)
- Virtual environment (recommended)

### Setup Instructions

1. **Clone the Repository**
   ```bash
   git clone <repository-url>
   cd gps-tak-bridge
   ```

2. **Create Virtual Environment**
   ```bash
   python -m venv venv
   
   # On Windows
   venv\Scripts\activate
   
   # On macOS/Linux
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration**
   Create a `.env` file in the root directory:
   ```env
   FLASK_ENV=development
   SECRET_KEY=your-secret-key-here
   TB_MASTER_KEY=your-secret-key-here
   DATABASE_URL=sqlite:///gps_tak_bridge.db
   LOG_LEVEL=INFO
   ```

5. **Initialize Database**
   ```bash
   flask db init
   flask db migrate -m "Initial migration"
   flask db upgrade
   ```

6. **Run the Application**
   ```bash
   python app.py
   ```

   The application will be available at `http://localhost:8080`

## Configuration

### TAK Server Configuration

1. Navigate to **TAK Servers** in the web interface
2. Click **Create TAK Server**
3. Fill in the required information:
   - **Name**: Descriptive name for the server
   - **Host**: TAK server hostname or IP address
   - **Port**: TAK server port (typically 8089 for TLS)
   - **Protocol**: Connection protocol (TCP/TLS/UDP)
   - **Certificate**: Upload P12 certificate file (if required)
   - **SSL Verification**: Enable/disable SSL certificate verification

### Stream Configuration

1. Navigate to **Streams** in the web interface
2. Click **Create Stream**
3. Configure the stream:
   - **Name**: Descriptive name for the stream
   - **TAK Server**: Select target TAK server
   - **Plugin Type**: Choose GPS data source type
   - **Plugin Configuration**: Configure GPS source parameters
   - **CoT Type**: Set Cursor-on-Target message type
   - **Update Interval**: Set polling frequency

## Plugin Architecture

The application uses a plugin system to support different GPS data sources:

### Available Plugins
- **Garmin InReach**: [Garmin InReach ](https://www.garmin.com/en-US/c/outdoor-recreation/satellite-communicators/)
- **SPOT Tracker**: [SPOT Trackers](https://www.findmespot.com/en-us)
- **Traccar**: [Traccar based devices](https://www.traccar.org/)
- **Custom Plugins**: Extensible for new data sources

### Adding New Plugins

1. Create a new plugin class inheriting from the base plugin
2. Implement required methods:
   - `get_metadata()`: Plugin configuration schema
   - `test_connection()`: Connection testing
   - `start_stream()`: Stream initialization
   - `stop_stream()`: Stream cleanup
3. Register the plugin in the plugin manager

## API Endpoints

### Stream Management
- `GET /streams/api/status` - Get all stream statuses
- `GET /streams/api/stats` - Get stream statistics
- `POST /streams/<id>/start` - Start a stream
- `POST /streams/<id>/stop` - Stop a stream
- `POST /streams/<id>/restart` - Restart a stream
- `POST /streams/<id>/test` - Test stream connection

### TAK Server Management
- `GET /tak-servers/` - List TAK servers
- `POST /tak-servers/create` - Create TAK server
- `POST /tak-servers/<id>/test` - Test TAK server connection
- `POST /tak-servers/validate-certificate` - Validate P12 certificate

### Health Monitoring
- `GET /api/health` - Application health check
- `GET /api/health/detailed` - Detailed health information

## Logging and Monitoring

### Log Files
- `logs/app.log` - Main application log
- `logs/streams.log` - Stream-specific logs
- `logs/errors.log` - Error logs

### Monitoring Features
- Real-time stream status updates
- Connection health monitoring
- Error tracking and reporting
- Performance metrics
- Certificate expiration warnings

## Security Considerations

### Certificate Management
- P12 certificates are encrypted at rest
- Certificate passwords are hashed
- SSL/TLS verification configurable per server
- Certificate validation before storage

### Network Security
- Support for client certificate authentication
- Configurable SSL/TLS settings
- Connection timeout protection
- Rate limiting capabilities

### Data Protection
- Database encryption support
- Secure configuration storage
- Audit logging
- Session management

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Check database file permissions
   - Verify DATABASE_URL configuration
   - Run database migrations

2. **TAK Server Connection Failures**
   - Verify server address and port
   - Check certificate configuration
   - Test network connectivity
   - Review SSL settings

3. **GPS Stream Errors**
   - Validate plugin configuration
   - Check GPS source availability
   - Review authentication credentials
   - Monitor rate limits

4. **Performance Issues**
   - Adjust MAX_WORKER_THREADS
   - Optimize polling intervals
   - Monitor resource usage
   - Check database performance

### Debug Mode
Enable debug mode for detailed error information:
```env
FLASK_ENV=development
LOG_LEVEL=DEBUG
```

### Health Checks
Use the built-in health check endpoint:
```bash
curl http://localhost:8080/api/health
```

## Development

### Project Structure
```
gps-tak-bridge/
├── app.py                 # Main application entry point
├── config/               # Configuration management
├── models/               # Database models
├── routes/               # Flask routes/controllers
├── services/             # Business logic services
├── plugins/              # GPS provider plugins
├── templates/            # HTML templates
├── static/               # CSS, JS, images
├── migrations/           # Database migrations
└── tests/                # Test files
```

### Running Tests
```bash
python -m pytest tests/
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues, questions, or contributions:
- Create an issue in the GitHub repository
- Check the troubleshooting section
- Review the application logs
- Test connectivity using built-in tools

## Changelog

### Version 0.1.0
- Initial release
- Multi-source GPS integration
- TAK server management
- Web-based configuration interface
- Plugin architecture
- Real-time monitoring
- Certificate management