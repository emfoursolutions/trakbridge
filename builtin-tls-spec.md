# Built-in TLS Implementation Specification

**Document Version**: 1.0  
**Date**: 2025-09-02  
**Status**: Future Enhancement - Not Scheduled  
**Estimated Effort**: 4-6 hours development + testing

## Overview

This specification outlines the implementation of optional built-in TLS/HTTPS functionality for TrakBridge, providing an alternative to the current reverse proxy (nginx) approach for simpler deployments.

## Current Architecture

TrakBridge currently relies on nginx or another reverse proxy for:
- TLS termination and HTTPS enforcement
- Security header configuration
- Static file serving optimization
- Load balancing capabilities

## Proposed Feature: Optional Built-in TLS

### Use Cases
- **Development environments** - Easier HTTPS testing without nginx setup
- **Simple deployments** - Single-instance deployments without reverse proxy
- **Edge deployments** - Minimal infrastructure requirements
- **Testing scenarios** - Self-contained HTTPS for integration tests

### Design Principles
- **Optional functionality** - Disabled by default, enabled via configuration
- **Production ready** - Proper certificate validation and security headers
- **Backwards compatible** - No impact on existing nginx-based deployments
- **Configuration driven** - All TLS settings via environment variables

## Implementation Plan

### 1. Configuration Changes

#### File: `config/base.py`
```python
# TLS Configuration
ENABLE_BUILTIN_TLS = os.getenv('TRAKBRIDGE_ENABLE_TLS', 'false').lower() == 'true'
TLS_CERT_PATH = os.getenv('TRAKBRIDGE_TLS_CERT', '/app/certs/server.crt')
TLS_KEY_PATH = os.getenv('TRAKBRIDGE_TLS_KEY', '/app/certs/server.key')
TLS_PORT = int(os.getenv('TRAKBRIDGE_TLS_PORT', '443'))
TLS_REDIRECT_HTTP = os.getenv('TRAKBRIDGE_TLS_REDIRECT_HTTP', 'true').lower() == 'true'
```

#### Environment Variables
- `TRAKBRIDGE_ENABLE_TLS=true` - Enable built-in TLS
- `TRAKBRIDGE_TLS_CERT=/path/to/cert.pem` - Certificate file path
- `TRAKBRIDGE_TLS_KEY=/path/to/key.pem` - Private key file path
- `TRAKBRIDGE_TLS_PORT=443` - HTTPS port (default 443)
- `TRAKBRIDGE_TLS_REDIRECT_HTTP=true` - Redirect HTTP to HTTPS

### 2. Application Changes

#### File: `app.py`
```python
def create_app(config_class=None):
    # ... existing code ...
    
    # Add TLS security headers when built-in TLS is enabled
    if app.config.get('ENABLE_BUILTIN_TLS'):
        @app.after_request
        def add_tls_security_headers(response):
            # HSTS - HTTP Strict Transport Security
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
            # Prevent MIME type sniffing
            response.headers['X-Content-Type-Options'] = 'nosniff'
            # Clickjacking protection
            response.headers['X-Frame-Options'] = 'DENY'
            # XSS protection
            response.headers['X-XSS-Protection'] = '1; mode=block'
            # Referrer policy
            response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
            return response
        
        # HTTP to HTTPS redirect
        if app.config.get('TLS_REDIRECT_HTTP'):
            @app.before_request
            def force_https():
                if not request.is_secure and request.headers.get('X-Forwarded-Proto') != 'https':
                    return redirect(request.url.replace('http://', 'https://', 1), code=301)
    
    return app

def validate_tls_config(app):
    """Validate TLS configuration and certificate files"""
    if not app.config.get('ENABLE_BUILTIN_TLS'):
        return True
    
    import os
    import ssl
    
    cert_path = app.config['TLS_CERT_PATH']
    key_path = app.config['TLS_KEY_PATH']
    
    # Check certificate files exist
    if not os.path.exists(cert_path):
        logger.error(f"TLS certificate file not found: {cert_path}")
        return False
    
    if not os.path.exists(key_path):
        logger.error(f"TLS private key file not found: {key_path}")
        return False
    
    # Validate certificate and key match
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        logger.info("TLS certificate validation successful")
        return True
    except Exception as e:
        logger.error(f"TLS certificate validation failed: {e}")
        return False
```

### 3. Server Startup Changes

#### Development Server (`app.py`)
```python
def run_development_server(app):
    """Run development server with optional TLS"""
    if app.config.get('ENABLE_BUILTIN_TLS'):
        if not validate_tls_config(app):
            logger.error("TLS configuration invalid, falling back to HTTP")
            app.run(host='0.0.0.0', port=5000, debug=True)
            return
        
        import ssl
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(
            app.config['TLS_CERT_PATH'], 
            app.config['TLS_KEY_PATH']
        )
        
        logger.info(f"Starting development server with TLS on port {app.config['TLS_PORT']}")
        app.run(
            host='0.0.0.0',
            port=app.config['TLS_PORT'],
            ssl_context=context,
            debug=False  # Never debug with TLS in production
        )
    else:
        app.run(host='0.0.0.0', port=5000, debug=True)
```

#### Production Server (`docker/entrypoint.sh`)
```bash
# Add TLS support to Hypercorn startup
start_server() {
    cd /app
    
    if [ "$TRAKBRIDGE_ENABLE_TLS" = "true" ]; then
        # Validate certificate files exist
        if [ ! -f "$TRAKBRIDGE_TLS_CERT" ]; then
            echo "ERROR: TLS certificate file not found: $TRAKBRIDGE_TLS_CERT"
            exit 1
        fi
        
        if [ ! -f "$TRAKBRIDGE_TLS_KEY" ]; then
            echo "ERROR: TLS private key file not found: $TRAKBRIDGE_TLS_KEY"
            exit 1
        fi
        
        echo "Starting Hypercorn with built-in TLS on port $TRAKBRIDGE_TLS_PORT"
        exec hypercorn --bind "0.0.0.0:$TRAKBRIDGE_TLS_PORT" \
                       --certfile "$TRAKBRIDGE_TLS_CERT" \
                       --keyfile "$TRAKBRIDGE_TLS_KEY" \
                       --workers "$workers" \
                       app:app
    else
        echo "Starting Hypercorn with HTTP on port $bind"
        exec hypercorn --bind "$bind" --workers "$workers" app:app
    fi
}
```

### 4. Container Changes

#### File: `Dockerfile`
```dockerfile
# Expose HTTPS port for built-in TLS
EXPOSE 5000 443

# Create certificates directory with proper permissions
RUN mkdir -p /app/certs && \
    chown -R appuser:appuser /app/certs && \
    chmod 700 /app/certs

# Set secure permissions for certificate directory
VOLUME ["/app/certs"]
```

#### File: `docker-compose.yml`
```yaml
services:
  trakbridge:
    # ... existing configuration ...
    ports:
      - "5000:5000"    # HTTP (existing)
      - "443:443"      # HTTPS (new)
    volumes:
      - ./certs:/app/certs:ro  # Mount certificate directory
    environment:
      # TLS Configuration
      - TRAKBRIDGE_ENABLE_TLS=${ENABLE_TLS:-false}
      - TRAKBRIDGE_TLS_CERT=/app/certs/server.crt
      - TRAKBRIDGE_TLS_KEY=/app/certs/server.key
      - TRAKBRIDGE_TLS_PORT=443
```

### 5. Certificate Management

#### Self-Signed Certificate Generation Script
```bash
#!/bin/bash
# scripts/generate-self-signed-cert.sh

CERT_DIR="/app/certs"
CERT_FILE="$CERT_DIR/server.crt"
KEY_FILE="$CERT_DIR/server.key"
DOMAIN="${1:-localhost}"

mkdir -p "$CERT_DIR"

openssl req -x509 -newkey rsa:4096 -keyout "$KEY_FILE" -out "$CERT_FILE" \
    -days 365 -nodes -subj "/CN=$DOMAIN" \
    -addext "subjectAltName=DNS:$DOMAIN,DNS:localhost,IP:127.0.0.1"

chmod 600 "$KEY_FILE"
chmod 644 "$CERT_FILE"

echo "Self-signed certificate generated:"
echo "  Certificate: $CERT_FILE"
echo "  Private Key: $KEY_FILE"
echo "  Domain: $DOMAIN"
```

### 6. Documentation Updates

#### Files to Update:
- `docs/INSTALLATION.md` - Add TLS configuration section
- `docs/DOCKER_DEPLOYMENT.md` - Add built-in TLS deployment example
- `docs/SECURITY.md` - Update security architecture section
- `README.md` - Add TLS configuration to quick start

#### Documentation Sections:
```markdown
## Built-in TLS Configuration (Optional)

TrakBridge can optionally provide built-in HTTPS/TLS instead of relying on a reverse proxy:

### Enable Built-in TLS
```bash
export TRAKBRIDGE_ENABLE_TLS=true
export TRAKBRIDGE_TLS_CERT=/path/to/certificate.crt
export TRAKBRIDGE_TLS_KEY=/path/to/private.key
```

### Generate Self-Signed Certificate
```bash
./scripts/generate-self-signed-cert.sh your-domain.com
```

### Docker Deployment with Built-in TLS
```yaml
# docker-compose.yml
services:
  trakbridge:
    environment:
      - TRAKBRIDGE_ENABLE_TLS=true
    volumes:
      - ./certs:/app/certs:ro
    ports:
      - "443:443"
```
```

## Testing Plan

### 1. Unit Tests
- Certificate validation functions
- Configuration loading with TLS options
- Security header application

### 2. Integration Tests
- HTTPS server startup and shutdown
- Certificate file validation
- HTTP to HTTPS redirect functionality
- Security headers presence

### 3. Manual Testing
- Self-signed certificate generation
- Docker deployment with built-in TLS
- Browser HTTPS access validation
- Certificate renewal process

## Security Considerations

### Certificate Management
- Certificates should be mounted as read-only volumes
- Private keys must have restricted permissions (600)
- Certificate expiration monitoring recommended
- Support for certificate chains (intermediate certificates)

### Security Headers
- Comprehensive HTTPS security headers applied automatically
- HSTS (HTTP Strict Transport Security) with long max-age
- Content type sniffing prevention
- Clickjacking protection

### Performance Impact
- TLS termination in Python is less efficient than nginx
- Suitable for low-to-medium traffic scenarios
- Consider nginx for high-performance requirements

## Migration Path

### From Nginx to Built-in TLS
1. Generate or obtain TLS certificates
2. Configure TLS environment variables
3. Update port mappings (443 instead of 80)
4. Remove nginx service from deployment
5. Test HTTPS functionality

### From Built-in TLS to Nginx
1. Deploy nginx with TLS configuration
2. Set `TRAKBRIDGE_ENABLE_TLS=false`
3. Update port mappings back to HTTP
4. Remove certificate volumes

## Future Enhancements

- **Automatic certificate renewal** via Let's Encrypt integration
- **Certificate monitoring** with expiration alerts
- **SNI support** for multiple domains
- **Advanced TLS configuration** (cipher suites, protocols)
- **Performance optimization** for TLS operations

## Implementation Priority

**Priority**: Low - Nice to have  
**Dependencies**: None  
**Breaking Changes**: None  
**Backwards Compatibility**: Full

This feature can be implemented independently without affecting existing deployments or the current refactoring work.