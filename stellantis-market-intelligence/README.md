# Stellantis Market Impact Intelligence

Market and corporate research prototype centered on Stellantis (STLA). Market data is stored
from periodic ingestion; dashboard values are not real-time quotes.

> This is a market/corporate intelligence research tool. It is **NOT** an investment
> recommendation system. It does not provide buy/sell signals or price predictions.

## Features

### Core Analytics
- **Event Detection**: Automatically detects significant STLA market movements
- **Market Context**: Compares STLA movements against market and sector benchmarks
- **Correlation Analysis**: Statistical relationships between STLA and other companies
- **Event Studies**: Analyzes company reactions around STLA events
- **Abnormal Returns**: Calculates market-adjusted and sector-adjusted returns

### Relationship Intelligence
- **Corporate Graph**: NetworkX-based knowledge graph of business relationships
- **Supply Chain Analysis**: First, second, and third-order exposure tracking
- **Evidence-Based**: Every relationship backed by documented sources
- **Exposure Scoring**: Quantifies ecosystem exposure to STLA events

### AI & RAG
- **Document Search**: TF-IDF retrieval over locally indexed document chunks
- **AI Synthesis**: Optional Groq-hosted analysis with source attribution
- **Event Similarity**: Find historical events similar to current ones
- **Investigation Agent**: Automated analysis workflow for new events

### Professional Dashboards
- **Executive Overview**: High-level event summary and ecosystem status
- **Event Explorer**: Browse and analyze all detected events
- **Impact Analysis**: Detailed view of affected companies
- **Ecosystem Graph**: Interactive visualization of relationships
- **Business Reports**: Comprehensive event reports (JSON/text)

### Flask API
- **RESTful API**: Flask backend with JSON responses
- **Health Checks**: Basic and detailed system status endpoints
- **Metrics**: Prometheus-compatible monitoring
- **Error Handling**: Graceful degradation with structured errors
- **Security**: Optional authenticated sessions, CSRF, bearer access, rate limits, and dependency audits; not independently security-audited

## Tech Stack

- **Data**: Pandas/Polars, PyArrow, DuckDB, Parquet
- **Market Data**: yfinance (free/public)
- **Analytics**: NumPy, SciPy, Statsmodels, Scikit-learn
- **Graph**: NetworkX
- **Vector Search**: FAISS
- **Text features**: scikit-learn TF-IDF (not neural embeddings)
- **LLM**: Optional Groq-hosted API (cloud)
- **Backend**: Flask with Gunicorn/Waitress
- **Frontend**: Server-rendered HTML with vanilla JS/CSS
- **Monitoring**: Prometheus metrics

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Groq API key (optional, for AI features)

### Installation

1. Clone the repository
2. Install dependencies:
```bash
uv sync
```

3. Create `.env` file (copy from `.env.example`):
```bash
cp .env.example .env
```

4. Initialize database:
```bash
uv run python -m storage.load_companies
```

### Data Pipeline

Run all commands from the `stellantis-market-intelligence` directory. For an
initial or offline CLI refresh, stop the web server first: DuckDB does not allow
an independent writer process while the server holds the warehouse open.
Once running, use **System Status > Refresh Data** instead. It executes the same
pipeline safely inside the server process, with overlap prevention and job history.

```bash
uv run python -m ingestion.pipeline --full --days 365
```

This loads the configured companies and documented relationships, ingests daily
prices for every company **and both benchmarks**, fetches the enabled RSS/Atom feeds,
computes daily features and correlations, detects events, runs event studies,
enriches catalysts, generates historical fingerprints, and rebuilds search.
It does not require an LLM API key.

For subsequent daily refreshes, the default downloads overlap the latest stored
prices by seven calendar days and upsert without duplicating rows:

```bash
uv run python -m ingestion.pipeline
uv run python -m ingestion.pipeline --check-only
```

`--full` re-downloads the entire requested window, including historical price
revisions. Use it periodically or when increasing the lookback. Downloads use
completed days only; the current trading day is excluded.

The refresh returns exit code **0 only when all stages and readiness checks pass**.
Failures retain existing data, are recorded per stage, and return a nonzero exit
code. The atomic report is `data/reports/pipeline-latest.json`. A lock beside the
warehouse prevents overlapping pipeline runs. After an interrupted run, remove a
leftover `.pipeline.lock` only after verifying no refresh process is running.

Readiness requires at least 60 daily rows per configured ticker, prices no older
than seven calendar days, matching feature coverage, valid OHLCV rows, usable
company correlations, recent Stellantis news/filings, a relationship graph, and a
search corpus. `/api/health/ready` returns **503** for missing/stale data and **200**
when ready; `/api/health` remains a process-liveness check. Detailed data issues
and coverage are available at `/api/health/detailed`.

External providers can fail or change access terms. Only enabled, configured
sources are fetched; no synthetic prices, fabricated relationships, or invented
catalysts are used to conceal gaps. Market holidays, unconfirmed catalysts, and
future event-study windows can legitimately have no observation. Optional AI
answers additionally require a working Groq key and available model.

### Operations and Evidence

- **System Status** shows maintenance history, feed outcomes, and per-ticker quality.
	Enable the in-process scheduler with `ENABLE_SCHEDULER=true`; the default daily
	refresh is 06:00 UTC (`REFRESH_UTC_HOUR` / `REFRESH_UTC_MINUTE`). The app must remain running.
- Refreshes automatically create checksummed warehouse/index backups. **Create Backup**
	makes an additional snapshot. Failed/degraded jobs append `data/reports/alerts.jsonl`;
	`ALERT_WEBHOOK_URL` optionally delivers an HTTPS notification.
- Reference-session gaps are comparisons against another stored listing/benchmark,
	not exchange-calendar-certified missing sessions. Future study windows and entities
	without tracked listings are distinguished from missing observations.
- Event detail includes linked publications, actual benchmark/peer returns, and
	event-window coverage. Publication proximity is an association, not proof of cause.
- Relationships retain source URLs, evidence dates, review dates, and review states.
	Historical partnership announcements do not establish all current commercial scope.
- Chat and investigation synthesis reject missing/out-of-range numeric source references.
	This verifies reference bounds, not whether every generated sentence follows from its citation.
	Search generations are published atomically so a failed rebuild preserves the prior index.

See [DEPLOYMENT.md](DEPLOYMENT.md) for authentication, HTTPS, backup/restore drills,
single-process hosting, alerts, and operational limits.

### Development

Run development server:
```bash
uv run flask --app api.main:create_app run --debug
```

Access at: http://localhost:5000

### Production

First run `uv run python -m scripts.configure_security` directly in your local
terminal to configure the login password hash and session secret. Production
startup refuses missing credentials. Use HTTPS through a trusted reverse proxy;
never expose the development server. Passwords and API keys must not be sent in chat.

#### Linux/Mac
```bash
chmod +x start_production.sh
./start_production.sh
```

#### Windows (PowerShell)
```powershell
.\start_production.ps1
```

Or manually with Gunicorn:
```bash
uv run gunicorn --config gunicorn.conf.py wsgi:application
```

Or manually with Waitress (Windows-friendly):
```bash
uv run --env-file .env waitress-serve --host=127.0.0.1 --port=8000 --threads=8 wsgi:application
```

## API Endpoints

### Health & Monitoring
- `GET /api/health` - Basic health check
- `GET /api/health/detailed` - Detailed component status
- `GET /metrics` - Prometheus metrics

### Companies
- `GET /api/companies` - List all companies
- `GET /api/companies/{ticker}` - Get company details

### Events
- `GET /api/events` - List all STLA events
- `GET /api/events/{event_id}` - Get event details
- `GET /api/events/{event_id}/impact` - Get affected companies
- `GET /api/events/{event_id}/timeline` - Publications, peer prices, and study-window coverage

### Maintenance
- `GET /api/maintenance` - Current job, schedule, history, feed outcomes
- `POST /api/maintenance/refresh` - Queue the complete refresh (202, or 409 if busy)
- `POST /api/maintenance/backup` - Queue a verified backup (202, or 409 if busy)

### Relationships
- `GET /api/relationships` - List all relationships
- `GET /api/relationships/{company}` - Get company relationships
- `GET /api/network` - Get full network graph

### Reports
- `GET /api/reports/event/{event_id}` - Generate event report
- `GET /api/reports/event/{event_id}?format=text` - Text format report

### Market Data
- `GET /api/prices/{ticker}` - Get price data

### AI & Search
- `POST /api/investigate` - Run AI investigation
- `POST /api/search` - TF-IDF document retrieval

## Configuration

### Environment Variables

```bash
# Database
DUCKDB_PATH=data/warehouse/market.duckdb

# Logging
LOG_LEVEL=INFO

# Groq API (for AI features)
GROQ_API_KEY=your_key_here
GROQ_MODEL=openai/gpt-oss-20b

# Production server
PORT=8000
GUNICORN_WORKERS=1
# Configure SECRET_KEY and AUTH_PASSWORD_HASH with scripts.configure_security
ENABLE_SCHEDULER=true

# Flask environment
FLASK_ENV=production
```

### Company Universe

Edit `config/companies.yaml` to add/remove companies from the universe.

### Relationship Evidence

Edit `config/relationships.yaml` to document business relationships with evidence.

### Event Rules

Edit `config/event_rules.yaml` to configure event detection thresholds.

## Testing

Run all tests:
```bash
uv run pytest
```

Run specific test file:
```bash
uv run pytest tests/unit/test_companies.py -v
```

With coverage:
```bash
uv run pytest --cov=. --cov-report=html
```

## Project Structure

```
stellantis-market-intelligence/
├── ai/                    # AI, RAG, and embeddings
├── analytics/             # Return, correlation, event studies
├── api/                   # Flask API routes and services
├── config/                # YAML configuration files
├── dashboard/             # Server-rendered HTML dashboards
├── data/                  # Data storage (raw, processed, warehouse)
├── events/                # Event detection and classification
├── ingestion/             # Market data and news ingestion
├── relationships/         # Corporate graph and supply chain
├── reports/               # Business report generation
├── storage/               # DuckDB and data persistence
├── tests/                 # Unit and integration tests
├── logs/                  # Application logs
├── wsgi.py                # Production WSGI entry point
├── gunicorn.conf.py       # Gunicorn configuration
└── start_production.*     # Production startup scripts
```

## Implementation Status

This is a working prototype, not a production-certified system. Several phases have code but
limited real data or incomplete end-to-end validation. See [PROJECT_AUDIT.md](PROJECT_AUDIT.md)
for the phase-by-phase status, known data gaps, and current remediation notes. The chosen
implementation uses Flask, Groq-hosted synthesis, and TF-IDF; these are documented deviations
from the original FastAPI/local-LLM plan.

## Monitoring

### Logs

Logs are written to the `logs/` directory:
- `app.log` - Application logs (rotating, 10MB max)
- `error.log` - Error logs only (daily rotation)
- `access.log` - HTTP access logs (rotating, 10MB max)

### Metrics

Prometheus metrics available at `/metrics`:
- `http_requests_total` - Total HTTP requests by method, endpoint, status
- `http_request_duration_seconds` - Request duration histogram

## Security

Current safeguards include request-size limits, HttpOnly/SameSite session cookies, baseline
security headers, and structured server errors. The application has not received a security
audit or deployment certification; see [PRODUCTION_READY.md](PRODUCTION_READY.md) for the current
readiness assessment.

## Performance

Implemented runtime features:
- Response compression (gzip)
- Simple caching (5-minute default)
- Configurable WSGI server entry points

## Troubleshooting

### Database Connection Issues
```bash
# Verify database exists
uv run python -c "from storage.duckdb import get_connection; print(get_connection())"

# Reinitialize if needed
uv run python -m storage.load_companies
```

### Missing Dependencies
```bash
# Resync dependencies
uv sync --frozen
```

### Port Already in Use
```bash
# Change port
export PORT=8080
./start_production.sh
```

### Logs Not Appearing
```bash
# Ensure logs directory exists and is writable
mkdir -p logs
chmod 755 logs
```

## License

Proprietary - Market Intelligence Research Tool

## Disclaimer

This application is a market intelligence and corporate research tool only. It is **NOT**:
- An investment recommendation system
- A buy/sell signal generator
- A price prediction system
- Financial advice

All analysis is for research and informational purposes only.
