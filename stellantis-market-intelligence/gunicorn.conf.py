"""Gunicorn production configuration for Stellantis Market Intelligence."""
import os

# Server socket
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
backlog = 2048

# Worker processes
workers = int(os.getenv('GUNICORN_WORKERS', '1'))
if workers != 1:
    raise RuntimeError('DuckDB and the in-process scheduler require exactly one Gunicorn worker')
worker_class = 'gthread'
threads = int(os.getenv('GUNICORN_THREADS', '8'))
worker_connections = 1000
max_requests = 0
max_requests_jitter = 0
timeout = 120
keepalive = 5

# Logging
accesslog = '-'
errorlog = '-'
loglevel = os.getenv('LOG_LEVEL', 'info').lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'stellantis-market-intelligence'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (if needed)
keyfile = os.getenv('SSL_KEYFILE', None)
certfile = os.getenv('SSL_CERTFILE', None)

# Preload app for better memory usage
preload_app = False
graceful_timeout = 300

def on_starting(server):
    """Called just before the master process is initialized."""
    print(f"Starting Stellantis Market Intelligence on {bind}")

def on_reload(server):
    """Called when workers are reloaded."""
    print("Reloading workers...")

def worker_int(worker):
    """Called when a worker receives SIGINT or SIGQUIT."""
    print(f"Worker {worker.pid} received interrupt signal")

def worker_abort(worker):
    """Called when a worker receives SIGABRT."""
    print(f"Worker {worker.pid} aborted")
