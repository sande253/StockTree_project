#!/bin/bash
# Production startup script for Stellantis Market Intelligence

set -e
cd "$(dirname "$0")"
export FLASK_ENV=production

echo "=== Stellantis Market Intelligence - Production Startup ==="

# Load environment variables
test -f .env || { echo "Run uv run python -m scripts.configure_security first"; exit 1; }

# Create necessary directories
mkdir -p logs data/raw data/processed data/features data/reports data/warehouse data/vector_store
echo "✓ Directories created"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Installing dependencies with uv..."
    uv sync
fi

# Run database migrations/setup if needed
echo "Checking database..."
uv run --frozen --env-file .env python -c "from storage.duckdb import get_connection; get_connection().close()"

# Start application with gunicorn
echo ""
echo "Starting application with Gunicorn..."
echo "Workers: 1 (DuckDB single-process mode)"
echo "Port: ${PORT:-8000}"
echo "Log Level: ${LOG_LEVEL:-info}"
echo ""

exec uv run --frozen --env-file .env gunicorn --config gunicorn.conf.py wsgi:application
