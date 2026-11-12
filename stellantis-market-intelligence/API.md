# API Documentation

RESTful API for Stellantis Market Intelligence platform.

Base URL: `http://localhost:8000/api`

## Authentication

Production requires `AUTH_PASSWORD_HASH` and an explicit session `SECRET_KEY` of
at least 32 characters. Configure them locally with `python -m scripts.configure_security`.
`GET /login` and `POST /login` establish an authenticated session; `POST /logout`
clears it. API requests without authentication return 401; page requests redirect
to login. `/api/health` is public liveness.

Authenticated browser mutations require the CSRF token from the page's meta tag
in `X-CSRFToken`. Alternatively, configure `DASHBOARD_API_TOKEN` and supply
`Authorization: Bearer <token>`; this bypasses session CSRF, not rate limits.
Never expose bearer tokens in browser code or URLs. Cross-origin mutations are
rejected unless bearer-authenticated. Development can run without credentials
on localhost; this is not a production configuration.

Defaults are 240 requests/minute, login POSTs 5/minute, expensive AI/search routes
10/minute, maintenance POSTs 4/minute. Limit violations return 429. Use HTTPS and
restrict network access; see [DEPLOYMENT.md](DEPLOYMENT.md).

## Response Format

API success bodies are endpoint-specific (objects or arrays), not a uniform envelope.
Errors generally include an `error` field. The following envelope is illustrative only:

```json
{
  "status": "success|error",
  "data": {...},
  "error": "error message if applicable"
}
```

## Health & Monitoring

### GET /api/health

Basic health check.

**Response:**
```json
{
  "status": "ok",
  "timestamp": 1791179144.88
}
```

### GET /api/health/detailed

Detailed system health with component status.

**Response:**
```json
{
  "status": "healthy|degraded|unhealthy",
  "timestamp": 1791179144.88,
  "components": {
    "database": {
      "status": "healthy",
      "type": "DuckDB"
    },
    "storage": {
      "status": "healthy",
      "missing_directories": null
    },
    "logging": {
      "status": "healthy",
      "writable": true
    },
    "vector_store": {
      "status": "healthy",
      "index_exists": true
    }
  }
}
```

## Maintenance

### GET /api/maintenance

Returns `current` job/scheduler state, the latest ten `history` entries, latest
pipeline `sources` outcomes, and a `pipeline` run summary. Source failures are
preserved, not replaced with fabricated news.

### POST /api/maintenance/{kind}

`kind` is `refresh` or `backup`. Refresh accepts optional JSON `{"full": true}`.
Returns 202 with queued job metadata, 409 if another maintenance job is running,
or 400 for an unsupported operation. Poll `GET /api/maintenance` for completion.
With authentication disabled, only localhost can submit jobs. Session CSRF or
bearer authentication applies when authentication is configured.

### GET /api/health/ready

Returns 200 when stored-data checks pass, 503 for stale, missing, or insufficient
data. This is separate from public process liveness. Detailed health includes
per-ticker freshness, feature coverage, and reference-session gaps; these are not
an exchange-calendar guarantee.

## Companies

### GET /api/companies

List all companies in the universe.

**Response:**
```json
[
  {
    "ticker": "STLA",
    "name": "Stellantis N.V.",
    "sector": "Automotive",
    "industry": "Auto Manufacturers",
    "country": "Netherlands"
  },
  ...
]
```

### GET /api/companies/{ticker}

Get detailed information for a specific company.

**Parameters:**
- `ticker` (path): Company ticker symbol

**Response:**
```json
{
  "ticker": "STLA",
  "name": "Stellantis N.V.",
  "sector": "Automotive",
  "industry": "Auto Manufacturers",
  "country": "Netherlands",
  "relationships": [...],
  "statistics": {...}
}
```

## Market Data

### GET /api/prices/{ticker}

Get historical price data.

**Parameters:**
- `ticker` (path): Company ticker symbol
- `start_date` (query): Start date (YYYY-MM-DD)
- `end_date` (query): End date (YYYY-MM-DD)
- `interval` (query): Data interval (1d, 1h, etc.)

**Example:** `/api/prices/STLA?start_date=2026-09-01&end_date=2026-10-01`

**Response:**
```json
{
  "ticker": "STLA",
  "data": [
    {
      "date": "2026-09-01",
      "open": 25.50,
      "high": 26.00,
      "low": 25.20,
      "close": 25.80,
      "adj_close": 25.80,
      "volume": 15000000
    },
    ...
  ]
}
```

## Events

### GET /api/events/{event_id}/timeline

Returns stored event context, linked publications with source/timestamp provenance,
actual daily ticker/benchmark/peer prices and adjusted returns within 15 calendar
days, and configured-company study-window coverage. Coverage distinguishes
`complete`, `incomplete`, and `not_yet_observable`. Publication proximity does not
prove causation. Unknown events return 404.

### GET /api/events

List all detected STLA events.

**Query Parameters:**
- `ticker` (optional): Filter by ticker (default: STLA)
- `start_date` (optional): Filter from date
- `end_date` (optional): Filter to date
- `severity` (optional): Filter by severity (High, Medium, Low)
- `event_type` (optional): Filter by event type

**Response:**
```json
[
  {
    "event_id": "STLA-2026-09-29",
    "event_date": "2026-09-29",
    "ticker": "STLA",
    "return": -0.082,
    "z_score": -3.45,
    "volume_z_score": 2.87,
    "volatility": 0.025,
    "severity": "High",
    "direction": "negative",
    "event_type": "Production",
    "classification": "Production shutdown announcement"
  },
  ...
]
```

### GET /api/events/{event_id}

Get detailed information for a specific event.

**Parameters:**
- `event_id` (path): Event identifier

**Response:**
```json
{
  "event_id": "STLA-2026-09-29",
  "event_date": "2026-09-29",
  "ticker": "STLA",
  "return": -0.082,
  "market_return": -0.004,
  "sector_return": -0.016,
  "abnormal_return": -0.078,
  "z_score": -3.45,
  "severity": "High",
  "event_type": "Production",
  "classification": "Production shutdown announcement",
  "description": "...",
  "related_news": [...]
}
```

### GET /api/events/{event_id}/impact

Get potentially affected companies for an event.

**Response:**
```json
{
  "event_id": "STLA-2026-09-29",
  "impact": [
    {
      "ticker": "SUPPLIER_A",
      "name": "Supplier A Inc.",
      "relationship_type": "Direct Supplier",
      "relationship_strength": "High",
      "historical_correlation": 0.68,
      "historical_event_sensitivity": "High",
      "current_event_reaction": -0.042,
      "ecosystem_exposure_score": 85,
      "evidence_url": "https://..."
    },
    ...
  ]
}
```

## Relationships

### GET /api/relationships

List all documented business relationships.

**Query Parameters:**
- `company` (optional): Filter by company name/ticker
- `relationship_type` (optional): Filter by type

**Response:**
```json
[
  {
    "source": "STLA",
    "target": "SUPPLIER_A",
    "relationship_type": "Direct Supplier",
    "relationship_strength": "High",
    "confidence": 0.95,
    "evidence_url": "https://...",
    "date_discovered": "2026-01-15"
  },
  ...
]
```

### GET /api/relationships/{company}

Get all relationships for a specific company.

**Parameters:**
- `company` (path): Company ticker or name

**Response:**
```json
{
  "company": "STLA",
  "relationships": [
    {
      "related_company": "SUPPLIER_A",
      "relationship_type": "Direct Supplier",
      "strength": "High",
      "evidence": "..."
    },
    ...
  ]
}
```

## Network

### GET /api/network

Get full corporate network graph.

**Query Parameters:**
- `max_depth` (optional): Maximum relationship depth (default: 2)
- `relationship_types` (optional): Comma-separated types to include

**Response:**
```json
{
  "nodes": [
    {
      "id": "STLA",
      "name": "Stellantis N.V.",
      "entity_type": "Company",
      "ticker": "STLA"
    },
    ...
  ],
  "edges": [
    {
      "source": "STLA",
      "target": "SUPPLIER_A",
      "relationship_type": "Direct Supplier",
      "confidence": 0.95
    },
    ...
  ]
}
```

## Historical Analysis

### GET /api/historical-events

Search historical events similar to current/specified event.

**Query Parameters:**
- `event_id` (optional): Find events similar to this one
- `event_type` (optional): Filter by event type
- `limit` (optional): Number of results (default: 10)

**Response:**
```json
[
  {
    "event_id": "STLA-2025-06-12",
    "event_date": "2025-06-12",
    "similarity_score": 0.91,
    "return": -0.061,
    "event_type": "Production",
    "description": "..."
  },
  ...
]
```

## Reports

### GET /api/reports/event/{event_id}

Generate comprehensive business report for an event.

**Parameters:**
- `event_id` (path): Event identifier
- `format` (query): Response format ('json' or 'text', default: json)

**Example:** `/api/reports/event/STLA-2026-09-29?format=text`

**Response (JSON):**
```json
{
  "report_id": "STLA-REPORT-STLA-2026-09-29",
  "generated_at": "2026-10-05T11:30:00",
  "event_summary": {
    "event_id": "STLA-2026-09-29",
    "date": "2026-09-29",
    "type": "Production",
    "severity": "High",
    "stla_movement": -0.082
  },
  "market_context": {
    "stla_return": -0.082,
    "market_return": -0.004,
    "sector_return": -0.016,
    "abnormal_return": -0.078,
    "interpretation": "..."
  },
  "affected_companies": [...],
  "business_connections": [...],
  "historical_precedent": [...],
  "key_findings": [...],
  "uncertainties": [...]
}
```

## AI & Search

### POST /api/investigate

Run AI-powered investigation workflow.

**Request Body:**
```json
{
  "event_id": "STLA-2026-09-29",
  "depth": "comprehensive|standard|quick"
}
```

**Response:**
```json
{
  "investigation_id": "INV-123",
  "event_summary": "...",
  "market_context": "...",
  "likely_catalyst": "...",
  "affected_companies": [...],
  "supply_chain_exposure": [...],
  "similar_historical_events": [...],
  "evidence": [...],
  "uncertainties": [...]
}
```

### POST /api/search

Semantic search across documents and relationships.

**Request Body:**
```json
{
  "query": "battery suppliers to Stellantis",
  "limit": 10,
  "filters": {
    "document_type": "relationship",
    "date_range": ["2025-01-01", "2026-10-01"]
  }
}
```

**Response:**
```json
{
  "query": "battery suppliers to Stellantis",
  "results": [
    {
      "id": "doc_123",
      "text": "...",
      "score": 0.89,
      "metadata": {
        "type": "relationship",
        "company": "STLA",
        "date": "2026-03-15"
      }
    },
    ...
  ]
}
```

## Metrics

### GET /metrics

Prometheus-compatible metrics endpoint.

**Response:** (text/plain)
```
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{method="GET",endpoint="health",status="200"} 145
http_requests_total{method="GET",endpoint="events",status="200"} 89

# HELP http_request_duration_seconds HTTP request duration
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{method="GET",endpoint="events",le="0.1"} 78
...
```

## Error Responses

### 400 Bad Request
```json
{
  "error": "Bad request",
  "message": "Invalid date format. Expected YYYY-MM-DD"
}
```

### 404 Not Found
```json
{
  "error": "Resource not found"
}
```

### 500 Internal Server Error
```json
{
  "error": "An unexpected error occurred. Data unavailable."
}
```

## Rate Limiting

**Recommended limits:**
- Standard endpoints: 100 requests/minute
- Heavy operations (investigate, reports): 10 requests/minute
- Health checks: No limit

Implement at reverse proxy level (Nginx/Apache).

## CORS

For cross-origin requests, configure CORS headers:

```python
@app.after_request
def after_request(response):
    response.headers['Access-Control-Allow-Origin'] = 'https://your-frontend.com'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response
```

## Versioning

Current version: v1 (implicit)

Future versions will use URL prefix: `/api/v2/...`

## Support

For API issues or questions:
- Check `/api/health/detailed` for system status
- Review logs in `logs/` directory
- Verify request format matches documentation
- Ensure all required services are running
