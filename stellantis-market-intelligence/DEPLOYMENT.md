# Deployment and Recovery

Run commands from this application's directory. Python 3.11+, uv, network access,
and sufficient storage for the warehouse, retained index generations, and backups
are required. Use one application process: the embedded DuckDB warehouse and
in-process scheduler are not a shared multi-worker service.

## Initial Setup

```bash
uv sync --frozen
cp .env.example .env
uv run python -m scripts.configure_security
uv run --env-file .env python -m ingestion.pipeline --full --days 365
```

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`. Run credential
setup directly in your own terminal: it prompts without echoing the password,
stores a Werkzeug password hash, and creates a persistent session secret.
Never share `.env`, passwords, session secrets, or API tokens in chat or source control.
Restrict `.env` and data directories to the service account (Windows ACLs or Unix
file permissions). Preserve a secure copy of the session secret across restarts.

Optional Groq synthesis uses `GROQ_API_KEY` and `GROQ_MODEL=openai/gpt-oss-20b`.
Data ingestion and deterministic analytics do not require an LLM key.

## Hosting

Windows:

```powershell
.\start_production.ps1
```

Linux:

```bash
./start_production.sh
```

Both scripts require `.env` and set production mode. Windows uses a single
Waitress process with eight threads. Linux uses the checked-in Gunicorn config:
one `gthread` worker, eight threads, no preload, and no request-count recycling.
`GUNICORN_WORKERS` must be 1. Do not fork multiple workers or enable reloaders
with the scheduler. Do not restart the process while a maintenance job is running.
For systemd, use the app directory as `WorkingDirectory`, the startup script as
`ExecStart`, and a shutdown grace period of at least 300 seconds.

Docker Compose requires `SECRET_KEY` and `AUTH_PASSWORD_HASH` in the local `.env`:

```bash
docker compose up --build -d
```

The published port is bound to `127.0.0.1:8000`. Keep the persistent data/config
volumes and file permissions consistent with the container's service user.

## HTTPS and Authentication

Production refuses startup without a password hash and an explicit secret of at
least 32 characters. Sessions expire after eight hours. Production cookies are
Secure, HttpOnly, and SameSite; direct HTTP cannot be used for production login.

Put an HTTPS reverse proxy in front of the loopback-bound application. Preserve
the original Host and overwrite forwarded headers, for example in Nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_read_timeout 120s;
}
```

Set `TRUST_PROXY=true` **only** behind exactly one trusted proxy with direct app
access blocked. The app trusts one forwarded scheme/client hop, never forwarded
host. Configure the proxy's TLS certificate, HTTP-to-HTTPS redirect, allowed hosts,
and network firewall separately. Do not trust client-supplied forwarding headers.

API clients may use an optional `DASHBOARD_API_TOKEN` bearer credential. Browser
mutations require the page CSRF token. Rate limits default to 240/minute overall,
5 login POSTs/minute, 10 AI/search requests/minute, and 4 maintenance POSTs/minute.
The default limiter is process-local memory and resets on restart; configure
`RATELIMIT_STORAGE_URI` for persistence if needed. This is a shared-password
research deployment, not enterprise identity, role-based access, or multi-tenancy.
The CSP retains inline allowances required by existing templates; it is not a
strict nonce-based policy. Independent security review is still recommended.

## Refreshes, Scheduling, and Alerts

Use **System Status > Refresh Data** while the app runs. It queues the canonical
pipeline in the same process, creates a pre-refresh backup, rejects overlapping
maintenance jobs, clears dashboard caches, and retains job and source outcomes.

Set `ENABLE_SCHEDULER=true` for a daily refresh; defaults are `REFRESH_UTC_HOUR=6`
and `REFRESH_UTC_MINUTE=0`. UTC has no daylight-saving shift. The app must remain
running; this is not an external always-on scheduling service. The status page
shows the next run. Do not also schedule independent warehouse-writing scripts.

The CLI pipeline is for offline use with the server stopped:

```bash
uv run --env-file .env python -m ingestion.pipeline
uv run --env-file .env python -m ingestion.pipeline --check-only
```

Latest and immutable reports live under `data/reports/`. Failed/degraded jobs
append `alerts.jsonl`; optionally set `ALERT_WEBHOOK_URL` to an HTTPS receiver.
Webhook delivery and external alert handling need deployment-specific testing.
`NEWS_USER_AGENT` should identify the real operator/contact, particularly for SEC
fair-access requirements. Feeds can be empty, throttled, unavailable, or delayed;
the dashboard reports those outcomes rather than manufacturing observations.

`GET /api/health` is public process liveness. Authenticated
`GET /api/health/ready` returns 503 when data quality is not ready. Reference-session
gaps compare observed listings, not authoritative exchange calendars. A recent
event can legitimately lack future study windows; unlisted brands have no tracked
stock metrics. Partnership announcements retain historical scope and review dates.

## Backups and Recovery

Use **System Status > Create Backup** while the app runs. Backups export DuckDB
tables as portable Parquet/SQL and copy the vector store with a SHA-256 manifest.
They are placed under `data/backups/`. A refresh also creates a backup before
changing an existing warehouse. Keep encrypted off-machine copies and define
retention/restore objectives separately; local copies do not survive disk loss.

Offline equivalents, with the server stopped:

```bash
uv run --env-file .env python -m storage.backup
uv run --env-file .env python -m storage.backup --restore data/backups/<backup> --target data/warehouse/recovered.duckdb
```

Restore verifies checksums and imports into a **new** database; it refuses to
overwrite a target. Use only trusted backups: checksums prove integrity, not
authenticity, and DuckDB import executes SQL. Configuration and `.env` are not
part of this data backup and require separate secure recovery.

The restore CLI restores the database, not the active vector directory. To recover
search safely, stop the server, point `DUCKDB_PATH` at the recovered database in
`.env`, and rebuild:

```bash
uv run --env-file .env python -m scripts.build_vector_index
```

Alternatively restore the complete matching `vector_store` snapshot from a trusted
backup while stopped. Do not mix individual generation files. Search uses the
atomic `CURRENT` pointer and matching immutable chunks; a failed rebuild retains
the preceding usable generation. Old generations are retained, so monitor disk
usage and prune only known inactive generations while the app is stopped.

Practice restoration to a separate file, compare table counts and representative
records against the backup, rebuild search, then check readiness before switching
the service. Never delete a DuckDB WAL to resolve a lock: stop the owning service
and let DuckDB recover it. Remove a stale `.pipeline.lock` only after confirming
that no refresh process remains.

## Validation and Dependency Audits

```bash
uv run pytest -q
uv run pip-audit --local --format json --output data/reports/python-audit.json
uv run python -m scripts.audit_browser_dependencies
```

The root `.github/workflows/quality.yml` runs tests, compilation, Python and browser
advisory scans on pushes, pull requests, manual runs, and a weekly schedule, and
uploads audit artifacts. It needs a GitHub repository to execute. The browser scan
requires exact jsDelivr npm versions and checks OSV; Python uses pip-audit. Current
security floors include Brotli 1.2.1, Certifi 2026.10.19, Flask-WTF 1.2.2, and
DOMPurify 3.4.17. A clean advisory scan is not proof of no vulnerabilities.

Horizontal scaling, multi-user roles, exchange-certified calendars, webhook uptime,
off-machine backup automation, and provider access/licensing are not supplied by
this embedded single-process deployment. Do not share one writable warehouse
between independent replicas.