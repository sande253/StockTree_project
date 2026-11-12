"""Flask application factory (Phase 24 API + Phase 23 dashboard, one process/app).

The JSON API lives under /api/*. The dashboard (server-rendered HTML) lives at the
root. Both share the same service layer (api/services/*) - the dashboard calls those
service functions directly rather than making an HTTP round-trip to its own API.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, g
from flask_compress import Compress
from flask_caching import Cache
from werkzeug.exceptions import HTTPException
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

logger = logging.getLogger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter(
    'http_requests_total', 
    'Total HTTP requests', 
    ['method', 'endpoint', 'status']
)
REQUEST_DURATION = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint']
)


def create_app() -> Flask:
    app = Flask(__name__)
    
    # Production configuration
    app.config.update(
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16MB max request size
        SECRET_KEY=os.getenv('SECRET_KEY', os.urandom(32).hex()),
        SESSION_COOKIE_SECURE=os.getenv('FLASK_ENV') == 'production',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )
    
    # Enable compression
    Compress(app)
    
    # Enable caching
    cache = Cache(app, config={
        'CACHE_TYPE': 'SimpleCache',
        'CACHE_DEFAULT_TIMEOUT': 300
    })
    
    # Setup logging
    Path('logs').mkdir(exist_ok=True)
    from config.logging import setup_logging
    setup_logging(app)

    from api.routes.companies import companies_bp
    from api.routes.chat import chat_bp
    from api.routes.events import events_bp
    from api.routes.health import health_bp
    from api.routes.historical import historical_bp
    from api.routes.investigate import investigate_bp
    from api.routes.network import network_bp
    from api.routes.prices import prices_bp
    from api.routes.relationships import relationships_bp
    from api.routes.search import search_bp
    from api.routes.reports import reports_bp
    from dashboard.routes import dashboard_bp

    for blueprint in (
        health_bp, companies_bp, chat_bp, prices_bp, events_bp, relationships_bp,
        network_bp, historical_bp, investigate_bp, search_bp, reports_bp,
    ):
        app.register_blueprint(blueprint, url_prefix="/api")

    app.register_blueprint(dashboard_bp)

    from api.security import configure_security

    configure_security(app)
    app.extensions["dashboard_cache"] = cache

    from api.maintenance import configure_maintenance

    configure_maintenance(app)
    
    # Request timing and logging middleware
    @app.before_request
    def before_request():
        g.start_time = time.time()
        g.request_id = os.urandom(8).hex()
    
    @app.after_request
    def after_request(response):
        if hasattr(g, 'start_time'):
            duration = time.time() - g.start_time
            
            # Record metrics
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=request.endpoint or 'unknown',
                status=response.status_code
            ).inc()
            
            REQUEST_DURATION.labels(
                method=request.method,
                endpoint=request.endpoint or 'unknown'
            ).observe(duration)
            
            # Add headers
            response.headers['X-Request-ID'] = g.request_id
            response.headers['X-Response-Time'] = f"{duration:.3f}s"
            
            # Access logging
            access_logger = logging.getLogger('access')
            access_logger.info(
                f'{request.remote_addr} - "{request.method} {request.path}" '
                f'{response.status_code} {duration:.3f}s'
            )
        
        # Security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        return response
    
    # Prometheus metrics endpoint
    @app.route('/metrics')
    def metrics():
        return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith('/api/'):
            return jsonify({"error": "Resource not found"}), 404
        return "Page not found", 404
    
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({"error": "Bad request", "message": str(error)}), 400
    
    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}")
        return jsonify({"error": "Internal server error"}), 500
    
    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        # Let Flask's normal HTTP errors (404, 400, etc. from abort()/routing) pass through
        # unchanged - only truly unexpected exceptions should be converted to a generic 500.
        if isinstance(exc, HTTPException):
            return exc
        # Phase 28: never leak a raw stack trace / crash the app - log it and return a
        # structured error instead.
        logger.exception("Unhandled error in request")
        return jsonify({"error": "An unexpected error occurred. Data unavailable."}), 500
    
    app.logger.info("Stellantis Market Intelligence application initialized")
    return app
