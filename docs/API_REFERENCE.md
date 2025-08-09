# TrakBridge API Reference

## Overview

TrakBridge provides a comprehensive RESTful API for system monitoring, stream management, and plugin discovery. All API endpoints support JSON responses and follow standard HTTP status codes.

## Authentication

API endpoints require authentication through one of these methods:

### Session-Based Authentication
Log in through the web interface to establish a session:
```bash
# Login creates a session cookie
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}' \
  -c cookies.txt

# Use session cookie for API calls  
curl -H "Cookie: session=..." http://localhost:8080/api/health \
  -b cookies.txt
```

### API Key Authentication
Generate API keys through the web interface (Admin → API Keys):
```bash
# Use API key in header
curl -H "X-API-Key: your-api-key" http://localhost:8080/api/health
```

## Base URL

All API endpoints are prefixed with `/api`:
- Development: `http://localhost:8080/api`
- Production: `https://your-domain.com/api`

## System Health API

### Basic Health Check
**GET** `/health`

Basic health status for load balancers and monitoring systems.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-08-08T12:00:00Z",
  "version": "1.2.0",
  "service": "trakbridge"
}
```

**Status Values:**
- `healthy` - System operating normally
- `starting` - Application starting up
- `unhealthy` - System has critical issues

### Detailed Health Check
**GET** `/health/detailed`

Comprehensive health check with component-level status.

**Authentication Required:** Optional (shows more details when authenticated)

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-08-08T12:00:00Z",
  "response_time_ms": 45.2,
  "version": "1.2.0",
  "service": "trakbridge",
  "checks": {
    "database": {
      "status": "healthy",
      "connection_time_ms": 12.3,
      "migrations_current": true
    },
    "encryption": {
      "status": "healthy",
      "service_initialized": true
    },
    "stream_manager": {
      "status": "healthy",
      "event_loop_running": true,
      "worker_count": 3
    },
    "system": {
      "status": "healthy",
      "cpu_percent": 15.2,
      "memory": {
        "total_gb": 8.0,
        "available_gb": 5.2,
        "percent": 35.0
      }
    }
  }
}
```

### Kubernetes Probes
**GET** `/health/ready` - Readiness probe (checks critical dependencies)
**GET** `/health/live` - Liveness probe (basic application health)

## Plugin Categories API

The plugin categorization system provides organized access to data source plugins through category-based endpoints.

### Get Available Categories
**GET** `/plugins/categories`

Returns all available plugin categories with metadata and plugin counts.

**Authentication:** Requires `api:read` permission

**Response:**
```json
{
  "OSINT": {
    "key": "OSINT",
    "display_name": "OSINT",
    "description": "Open Source Intelligence platforms and tools",
    "icon": "fas fa-search",
    "plugin_count": 1
  },
  "Tracker": {
    "key": "Tracker", 
    "display_name": "Tracker",
    "description": "GPS and satellite tracking devices and platforms",
    "icon": "fas fa-satellite-dish",
    "plugin_count": 3
  },
  "EMS": {
    "key": "EMS",
    "display_name": "EMS", 
    "description": "Emergency Management Systems and services",
    "icon": "fas fa-ambulance",
    "plugin_count": 0
  }
}
```

### Get Plugins by Category
**GET** `/plugins/by-category/{category}`

Returns all plugins in a specific category.

**Authentication:** Requires `api:read` permission

**Path Parameters:**
- `category` (string) - Category key (OSINT, Tracker, EMS)

**Example:** `/plugins/by-category/Tracker`

**Response:**
```json
{
  "category": "Tracker",
  "plugins": [
    {
      "key": "garmin",
      "display_name": "Garmin InReach",
      "description": "Connect to Garmin InReach satellite communicators",
      "icon": "fas fa-satellite-dish",
      "category": "Tracker"
    },
    {
      "key": "spot",
      "display_name": "SPOT Tracker", 
      "description": "Connect to SPOT GPS tracking devices",
      "icon": "fas fa-map-marker-alt",
      "category": "Tracker"
    },
    {
      "key": "traccar",
      "display_name": "Traccar Server",
      "description": "Connect to Traccar GPS tracking server",
      "icon": "fas fa-server",
      "category": "Tracker"
    }
  ]
}
```

### Get All Categorized Plugins
**GET** `/plugins/categorized`

Returns all plugins grouped by category.

**Authentication:** Requires `api:read` permission

**Response:**
```json
{
  "OSINT": [
    {
      "key": "deepstate",
      "display_name": "Deepstate OSINT Platform",
      "description": "Connect to DeepstateMAP OSINT platform",
      "icon": "fas fa-map-marked-alt",
      "category": "OSINT"
    }
  ],
  "Tracker": [
    {
      "key": "garmin",
      "display_name": "Garmin InReach", 
      "description": "Connect to Garmin InReach satellite communicators",
      "icon": "fas fa-satellite-dish",
      "category": "Tracker"
    }
  ],
  "EMS": []
}
```

### Get Category Statistics
**GET** `/plugins/category-statistics`

Returns statistical information about plugin categories.

**Authentication:** Requires `api:read` permission

**Response:**
```json
{
  "total_categories": 3,
  "total_plugins": 4,
  "categories": {
    "OSINT": {
      "plugin_count": 1,
      "display_name": "OSINT",
      "description": "Open Source Intelligence platforms and tools"
    },
    "Tracker": {
      "plugin_count": 3,
      "display_name": "Tracker", 
      "description": "GPS and satellite tracking devices and platforms"
    },
    "EMS": {
      "plugin_count": 0,
      "display_name": "EMS",
      "description": "Emergency Management Systems and services"
    }
  },
  "category_distribution": {
    "OSINT": 25.0,
    "Tracker": 75.0,
    "EMS": 0.0
  }
}
```

## Plugin Management API

### Get All Plugin Metadata
**GET** `/plugins/metadata`

Returns configuration metadata for all available plugins.

**Authentication:** Requires `api:read` permission

**Response:**
```json
{
  "garmin": {
    "display_name": "Garmin InReach",
    "description": "Connect to Garmin InReach satellite communicators",
    "icon": "fas fa-satellite-dish",
    "category": "tracker",
    "config_fields": [
      {
        "name": "username",
        "label": "InReach Username",
        "type": "text",
        "required": true,
        "help": "Your Garmin InReach username"
      },
      {
        "name": "password", 
        "label": "InReach Password",
        "type": "password",
        "required": true,
        "sensitive": true,
        "help": "Your Garmin InReach password"
      }
    ]
  }
}
```

### Get Single Plugin Configuration
**GET** `/streams/plugins/{plugin_name}/config`

Returns configuration metadata for a specific plugin.

**Authentication:** Requires `api:read` permission

**Path Parameters:**
- `plugin_name` (string) - Plugin key (e.g., "garmin", "spot", "deepstate")

**Response:** Same format as single plugin in metadata response above.

## Stream Management API

### Get Stream Statistics
**GET** `/streams/stats`

Returns aggregate statistics for all streams.

**Authentication:** Requires API key or session authentication

**Response:**
```json
{
  "total_streams": 5,
  "active_streams": 3,
  "inactive_streams": 2,
  "streams_by_plugin": {
    "garmin": 2,
    "spot": 1,
    "deepstate": 2
  },
  "streams_by_category": {
    "Tracker": 3,
    "OSINT": 2
  },
  "total_events_sent": 15432,
  "events_last_24h": 1205
}
```

### Get Stream Status
**GET** `/streams/status` 

Returns detailed status for all streams.

**Authentication:** Requires API key or session authentication

**Response:**
```json
{
  "streams": [
    {
      "id": 1,
      "name": "Garmin Team Alpha",
      "plugin_name": "garmin", 
      "plugin_category": "Tracker",
      "is_active": true,
      "status": "running",
      "last_update": "2025-08-08T11:58:30Z",
      "events_sent": 245,
      "last_error": null,
      "tak_server": "TAK-Primary"
    }
  ]
}
```

### Get Stream Configuration
**GET** `/streams/{stream_id}/config`

Returns stream configuration for editing (sensitive fields masked).

**Authentication:** Requires `streams:read` permission

**Path Parameters:**
- `stream_id` (integer) - Stream ID

**Response:**
```json
{
  "username": "myuser",
  "password": "********", 
  "refresh_interval": 300,
  "api_url": "https://explore.garmin.com/feed/share/myuser"
}
```

### Export Stream Configuration
**GET** `/streams/{stream_id}/export-config`

Exports complete stream configuration for backup (sensitive fields masked).

**Authentication:** Requires `streams:read` permission

**Response:** Complete stream configuration with metadata.

## System Status API

### Application Status
**GET** `/status`

Returns basic application status and counts.

**Authentication:** Optional (shows more details when authenticated)

**Response:**
```json
{
  "total_streams": 5,
  "active_streams": 3,
  "tak_servers": 2,
  "running_workers": 3
}
```

### Version Information  
**GET** `/version`

Returns application version information.

**Authentication:** None required

**Response:**
```json
{
  "version": "1.2.0"
}
```

### Security Status
**GET** `/streams/security-status`

Returns security status for all streams (admin only).

**Authentication:** Requires `admin:read` permission

**Response:**
```json
{
  "encrypted_fields": 15,
  "unencrypted_sensitive_fields": 0,
  "streams_with_weak_passwords": 0,
  "ssl_certificates_expiring": [],
  "security_score": 95
}
```

## Error Handling

All API endpoints use standard HTTP status codes and return consistent error responses:

### Success Responses
- `200 OK` - Request successful
- `201 Created` - Resource created successfully

### Error Responses
- `400 Bad Request` - Invalid request format or parameters
- `401 Unauthorized` - Authentication required
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

**Error Response Format:**
```json
{
  "error": "Brief error description",
  "message": "Detailed error message",
  "timestamp": "2025-08-08T12:00:00Z"
}
```

### Authentication Errors
```json
{
  "error": "Authentication required",
  "message": "This endpoint requires authentication. Please provide a valid API key or session.",
  "timestamp": "2025-08-08T12:00:00Z"
}
```

### Permission Errors  
```json
{
  "error": "Insufficient permissions",
  "message": "This operation requires 'admin:read' permission.",
  "timestamp": "2025-08-08T12:00:00Z"
}
```

## Rate Limiting

API endpoints are rate limited to prevent abuse:
- **Authenticated users**: 1000 requests per hour
- **Unauthenticated endpoints**: 100 requests per hour

Rate limit headers are included in responses:
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1691496000
```

## Usage Examples

### Get System Health with curl
```bash
# Basic health check
curl http://localhost:8080/api/health

# Detailed health check with authentication
curl -H "X-API-Key: your-api-key" \
  http://localhost:8080/api/health/detailed
```

### List Plugins by Category with Python
```python
import requests

# Get all tracker plugins
response = requests.get(
    'http://localhost:8080/api/plugins/by-category/Tracker',
    headers={'X-API-Key': 'your-api-key'}
)

trackers = response.json()
for plugin in trackers['plugins']:
    print(f"{plugin['display_name']}: {plugin['description']}")
```

### Monitor Stream Status with JavaScript
```javascript
async function getStreamStatus() {
  const response = await fetch('/api/streams/status', {
    headers: {
      'X-API-Key': 'your-api-key'
    }
  });
  
  const data = await response.json();
  return data.streams;
}
```

## Integration Notes

### Monitoring Systems
Use `/api/health` for load balancer health checks and basic monitoring. Use `/api/health/detailed` for comprehensive monitoring with authenticated access.

### Category-Based UI
The plugin category API enables dynamic UI generation where users first select a category (OSINT, Tracker, EMS) then choose from available plugins in that category.

### External Plugin Support
External plugins loaded via Docker volumes are automatically included in category responses when properly configured in `plugins.yaml`.

---

**API Version:** 1.2.0  
**Last Updated:** 2025-08-08  
**Base URL:** `/api`