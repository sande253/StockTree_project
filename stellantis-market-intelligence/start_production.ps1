# Production startup script for Stellantis Market Intelligence (Windows/PowerShell)

Write-Host "=== Stellantis Market Intelligence - Production Startup ===" -ForegroundColor Cyan

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:FLASK_ENV = 'production'
if (-not (Test-Path .env)) {
    throw 'Run uv run python -m scripts.configure_security before production startup.'
}

# Create necessary directories
$directories = @(
    "logs",
    "data/raw",
    "data/processed", 
    "data/features",
    "data/reports",
    "data/warehouse",
    "data/vector_store"
)

foreach ($dir in $directories) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}
Write-Host "Directories created" -ForegroundColor Green

# Check if virtual environment exists
if (-not (Test-Path ".venv")) {
    Write-Host "Installing dependencies with uv..." -ForegroundColor Yellow
    uv sync
}

# Check database
Write-Host "Checking database..." -ForegroundColor Yellow
uv run --frozen --env-file .env python -c "from storage.duckdb import get_connection; get_connection().close()"
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }

# Start application with waitress (better for Windows)
Write-Host ""
Write-Host "Starting application with Waitress..." -ForegroundColor Cyan
$port = if ($env:PORT) { $env:PORT } else { "8000" }
Write-Host "Port: $port" -ForegroundColor White
Write-Host "Log Level: $(if ($env:LOG_LEVEL) { $env:LOG_LEVEL } else { 'info' })" -ForegroundColor White
Write-Host ""

uv run --frozen --env-file .env waitress-serve --host=127.0.0.1 --port=$port --threads=8 wsgi:application
if ($LASTEXITCODE -ne 0) { throw 'Application startup failed.' }
