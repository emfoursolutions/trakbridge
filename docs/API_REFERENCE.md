# TrakBridge API Reference

> **The authoritative endpoint reference is the OpenAPI 3.1 spec, not this document.**
>
> - Interactive UI: **`/api/docs`** (Swagger UI, browse and try requests)
> - Machine-readable spec: **`/api/openapi.json`** (feed to Postman, Insomnia, or a code generator)
>
> This document explains *concepts*: how auth works, what conventions apply
> across all endpoints, and how to integrate against TrakBridge end-to-end.
> Per-endpoint request/response shapes, path parameters, and status codes
> live in the spec so they never drift from the running code.

## Overview

TrakBridge exposes a JSON HTTP API for:

- **Ingestion** — external devices push tracker data via `/api/inbound/*`
- **Introspection** — health, status, version, monitoring dashboard
- **Configuration read** — streams, plugins, callsign mappings, coordinate utilities

Admin, auth, and HTML endpoints are intentionally **not** in the public
OpenAPI spec. They exist and work, but they are internal to the browser
UI and are not a supported integration surface.

## Base URL

All API endpoints are prefixed with `/api`:

- Development: `http://localhost:8080/api`
- Production: `https://your-deployment/api`

## Authentication

TrakBridge supports three authentication mechanisms. Which one applies to a
given endpoint is declared in the OpenAPI spec's `security` block per
operation — check `/api/docs` to see what's accepted where.

### 1. Session cookie + CSRF token (browser UI)

Log in via the web UI (or the `/auth/login` form) to establish a session
cookie. For any state-changing request (`POST`, `PUT`, `PATCH`, `DELETE`),
the CSRF token from the `<meta name="csrf-token">` tag on every rendered
page must also be sent in the `X-CSRFToken` header.

This is the *internal* auth path — designed for the browser UI, not
external integrators. If you're scripting against TrakBridge you almost
certainly want one of the other two mechanisms.

### 2. Bearer token (inbound webhooks)

Used exclusively by `POST /api/inbound/{stream_id}/data`. The token is
per-stream, generated when the inbound stream is configured, and validated
by the stream's plugin (`plugin.validate_inbound_request`).

```bash
curl -X POST https://your-deployment/api/inbound/5/data \
  -H "Authorization: Bearer YOUR_STREAM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"id": "drone-1", "name": "Alpha", "lat": 38.897, "lon": -77.036}'
```

Failed auth returns the same `404 Not Found` response as a missing stream
— this is intentional (anti-enumeration) so external callers cannot probe
for valid stream ids.

Generate a new inbound key via `POST /api/inbound/generate-api-key`
(requires `streams:write` permission — accessed through the browser UI).

### 3. API key (`X-API-Key`) — planned

The `X-API-Key` header scheme is **declared** in the OpenAPI spec but
**not yet implemented server-side**. The `@api_key_or_auth_required`
decorator currently falls through to session auth when an `X-API-Key`
header is present. Do not depend on this scheme yet; it will be finished
in a follow-up release.

## Base conventions

### Response envelopes

Most endpoints return the payload directly. Two exceptions are worth
knowing about:

- **Coordinate converters** (`/api/convert-*`) wrap every response in
  `{"success": <bool>, ...}` with `"error"` on failure.
- **Discovery and enumeration endpoints** (`/api/streams/discover-trackers`,
  `/api/streams/{id}/callsign-mappings`, `/api/team-member-options`) also
  wrap in `{"success": true, ...}`.

Everything else returns the resource directly on success, and an error
object on failure.

### Error object

```json
{
  "error": "Short error identifier",
  "message": "Human-readable detail",
  "status": 401
}
```

Not every failing endpoint sets `message` or `status`. Rely on the HTTP
status code first; treat the body as a hint.

### HTTP status codes

TrakBridge uses standard status codes:

| Code | Meaning |
| --- | --- |
| `200` | Success |
| `202` | Accepted for asynchronous processing (inbound data) |
| `400` | Invalid request body or parameters |
| `401` | Authentication required or invalid |
| `403` | Authenticated but insufficient permissions |
| `404` | Not found — or, for `/api/inbound/*/data`, an anti-enumeration response for wrong stream / bad auth / IP blocked |
| `413` | Payload too large |
| `415` | Content-Type not accepted by the stream's plugin |
| `429` | Rate limit exceeded |
| `500` | Internal error |
| `503` | Service unavailable — startup incomplete or a critical health check failed |

## Rate limiting

Rate limits are enforced by Flask-Limiter with the following defaults:

| Scope | Limit |
| --- | --- |
| Global default | 120 requests / minute |
| `/api/*` (main API) | 30 requests / minute |
| `/api/inbound/*` | 60 requests / minute |
| `/auth/*` | 10 requests / minute |

For `POST /api/inbound/{stream_id}/data` specifically, an additional
per-stream rate limit is enforced inside the handler (default
60/minute, configurable per stream). This layer applies *on top of* the
blueprint-level limit above.

Rate limits are enforced by IP address by default. When TrakBridge sits
behind a reverse proxy you must set `PROXY_TRUSTED=true` and
`TRUSTED_PROXY_COUNT` correctly, otherwise every request will look like
it came from the proxy and share a single quota.

## Endpoint groups

The OpenAPI spec is tagged by group. Browse `/api/docs` and expand a tag
for the full operation list.

| Tag | Purpose | Examples |
| --- | --- | --- |
| `Health` | Container/orchestrator probes and component health | `/health`, `/health/ready`, `/health/database` |
| `Status` | Aggregate system status counts | `/status` |
| `Version` | Currently running TrakBridge version | `/version` |
| `Streams` | Stream metadata, stats, config, callsign mappings, tracker discovery | `/streams/stats`, `/streams/{id}/config` |
| `Plugins` | Plugin metadata, categories, available identifier fields | `/plugins/metadata`, `/plugins/categorized` |
| `Inbound` | External push ingestion + preview mode inspection | `/inbound/{id}/data`, `/inbound/{id}/preview` |
| `Coordinates` | Lat/lon ↔ MGRS conversion utilities | `/convert-latlon-to-mgrs` |
| `Monitoring` | Combined dashboard snapshot | `/monitoring/dashboard` |
| `TeamMembers` | Enumeration of role and color options for UI dropdowns | `/team-member-options` |

## Integration examples

### Push tracker data into an inbound stream

The most common external integration — a device or middleware pushes
locations, TrakBridge converts to CoT and dispatches to configured
TAK servers.

```bash
curl -X POST https://your-deployment/api/inbound/5/data \
  -H "Authorization: Bearer $INBOUND_STREAM_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "locations": [
      {"id": "unit-1", "name": "Alpha", "lat": 38.897, "lon": -77.036},
      {"id": "unit-2", "name": "Bravo", "lat": 38.898, "lon": -77.037}
    ]
  }'
```

Expected response (`202 Accepted`):

```json
{
  "status": "accepted",
  "locations_received": 2,
  "events_created": 2,
  "servers": {"TAK1": {"success": true, "events_enqueued": 2}}
}
```

If the stream is in **preview mode**, the response is `202` with
`"status": "preview"` and the parsed locations echoed back — nothing is
dispatched to TAK. Use preview mode when validating a new integration
before flipping the stream to live.

### Discover available plugins to build a UI

Both endpoints return category → plugin data suitable for populating
a dropdown grouped by category.

```python
import requests

resp = requests.get(
    "https://your-deployment/api/plugins/categorized",
    cookies={"session": SESSION_COOKIE},
    headers={"X-CSRFToken": CSRF_TOKEN},
)
for category, plugins in resp.json().items():
    print(f"[{category}]")
    for p in plugins:
        print(f"  {p['key']}: {p['display_name']}")
```

### Health-check integration for Kubernetes / load balancers

```yaml
# Kubernetes probes
readinessProbe:
  httpGet:
    path: /api/health/ready
    port: 8080
  periodSeconds: 5
livenessProbe:
  httpGet:
    path: /api/health/live
    port: 8080
  periodSeconds: 30
```

`/api/health/ready` returns `503` while the app is starting up or when a
critical dependency (database, encryption) is unhealthy — remove from
the LB pool. `/api/health/live` returns `200` as long as the process
event loop is responsive.

## Inbound streams — payload shape

The inbound API is the surface most affected by plugin choice. The wire
format for `POST /api/inbound/{stream_id}/data` depends on the stream's
plugin:

| Plugin | Content-Type | Payload |
| --- | --- | --- |
| `generic_inbound` (JSON) | `application/json` | `{"locations": [{"id", "name", "lat", "lon"}, ...]}` |
| `generic_xml_inbound` | `application/xml` | Plugin-defined XML schema |
| `inbound_http` | `application/x-www-form-urlencoded` or JSON | Fields configured per stream |

Location field names (`id` vs `uid`, `name` vs `callsign`, etc.) are
configurable per stream in the callsign-mapping UI. The safe bet: check
`GET /api/streams/{id}/callsign-mappings` to see what identifier field
the stream expects, then use that key in your payload.

See the [Inbound Streams Guide](INBOUND_STREAMS_GUIDE.md) for
architecture details, per-plugin payload examples, and guidance on
building custom inbound plugins.

### Inbound limits

Enforced by the `POST /api/inbound/{stream_id}/data` handler regardless
of plugin:

| Limit | Value |
| --- | --- |
| Payload size | 1 MB |
| Locations per request | 100 |
| Latitude | ±90° |
| Longitude | ±180° |
| Per-stream rate limit (default) | 60 requests/minute, configurable |

## Reverse proxy notes

TrakBridge respects `X-Forwarded-For` and `X-Forwarded-Proto` only when
`PROXY_TRUSTED=true` is set in the environment, and only for the number
of proxy hops declared in `TRUSTED_PROXY_COUNT`. Without those, the
`request.remote_addr` used for rate limiting and IP allowlists will be
the proxy's address, not the real client — every rate limit will share
one quota and every allowlist will match or fail as one.

## What's not in the spec

The OpenAPI spec covers the public JSON API — 31 operations across
health, streams, plugins, inbound, coordinates, monitoring, and
team-member groups. Deliberately excluded:

- Admin endpoints under `/admin/*` — browser UI only
- Plugin manager under `/admin/plugins/*` — browser UI only
- Auth flows under `/auth/*` (`/login`, `/logout`, `/oidc/callback`)
- Every HTML page (`/streams`, `/tak-servers`, etc.)
- `/admin/api/cot_types/export-data`

These endpoints exist and are used by the browser UI, but they are not
designed for external integration and are not part of the supported API
surface.

---

**Reference:** `/api/docs` (Swagger UI) · `/api/openapi.json` (raw spec)
**Prose docs:** this file, `docs/AUTHENTICATION.md`, `docs/INBOUND_STREAMS_GUIDE.md`
