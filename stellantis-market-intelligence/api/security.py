"""Authentication and request safeguards for local and hosted deployments."""

from __future__ import annotations

import hmac
import os
from datetime import timedelta

from flask import abort, jsonify, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash


def configure_security(app) -> None:
    if os.getenv("TRUST_PROXY", "false").lower() == "true":
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0)
    password_hash = os.getenv("AUTH_PASSWORD_HASH", "")
    production = os.getenv("FLASK_ENV") == "production"
    if production and (not password_hash or len(os.getenv("SECRET_KEY", "")) < 32):
        raise RuntimeError("Production requires AUTH_PASSWORD_HASH and a persistent SECRET_KEY of at least 32 characters")
    app.config.update(
        AUTH_ENABLED=bool(password_hash),
        WTF_CSRF_CHECK_DEFAULT=False,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    csrf = CSRFProtect(app)
    limiter = Limiter(
        get_remote_address, app=app, default_limits=["240 per minute"],
        storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        headers_enabled=True,
    )
    app.extensions["request_limiter"] = limiter

    @app.before_request
    def authorize_request():
        if request.endpoint in {"health.health", "dashboard.static", "static"}:
            return None
        if request.endpoint == "login":
            if request.method == "POST":
                csrf.protect()
            return None
        expected = os.getenv("DASHBOARD_API_TOKEN", "")
        supplied = request.headers.get("Authorization", "")
        bearer = bool(expected) and hmac.compare_digest(supplied, f"Bearer {expected}")
        if app.config["AUTH_ENABLED"] and not (session.get("authenticated") or bearer):
            if request.path.startswith("/api/") or request.path == "/metrics":
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login"))
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not bearer:
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                abort(403, description="Cross-origin mutation is not permitted")
            if app.config["AUTH_ENABLED"]:
                csrf.protect()
        return None

    @app.route("/login", methods=["GET", "POST"])
    @limiter.limit("5 per minute", methods=["POST"])
    def login():
        if not app.config["AUTH_ENABLED"]:
            return redirect(url_for("dashboard.executive_overview"))
        error = None
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            valid_password = check_password_hash(password_hash, password)
            if hmac.compare_digest(username, os.getenv("AUTH_USERNAME", "admin")) and valid_password:
                session.clear()
                session["authenticated"] = True
                session.permanent = True
                return redirect(url_for("dashboard.executive_overview"))
            error = "Invalid credentials"
        return render_template("login.html", error=error), 401 if error else 200

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    for endpoint in ("chat.chat", "investigate.investigate", "search.search"):
        view = app.view_functions.get(endpoint)
        if view is not None:
            app.view_functions[endpoint] = limiter.limit("10 per minute")(view)

    @app.after_request
    def security_headers(response):
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'"
        )
        if app.config["AUTH_ENABLED"]:
            response.headers["Cache-Control"] = "no-store"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.context_processor
    def security_context():
        return {"auth_enabled": app.config["AUTH_ENABLED"], "authenticated": session.get("authenticated", False)}