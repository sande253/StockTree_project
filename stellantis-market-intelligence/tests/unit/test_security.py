"""Authentication, CSRF, origin, and production-startup regressions."""

import re

import pytest
from werkzeug.security import generate_password_hash

from api.main import create_app


@pytest.fixture
def secure_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("AUTH_PASSWORD_HASH", generate_password_hash("test-only-password"))
    monkeypatch.setenv("DASHBOARD_API_TOKEN", "test-only-bearer-token")
    app = create_app()
    app.config["TESTING"] = True
    app.add_url_rule("/api/security-probe", view_func=lambda: {"ok": True}, methods=["POST"])
    return app


def test_production_requires_explicit_credentials(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("AUTH_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Production requires"):
        create_app()


def test_login_logout_and_csrf(secure_app):
    client = secure_app.test_client()
    assert client.get("/").status_code == 302
    assert client.get("/api/companies").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.post("/login", data={"username": "admin", "password": "test-only-password"}).status_code == 400
    page = client.get("/login")
    token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    response = client.post("/login", data={"username": "admin", "password": "test-only-password", "csrf_token": token})
    assert response.status_code == 302
    assert client.get("/api/companies").status_code == 200
    assert client.post("/api/security-probe").status_code == 400
    page = client.get("/login")
    token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    assert client.post("/api/security-probe", headers={"X-CSRFToken": token}).status_code == 200
    assert client.post("/logout", data={"csrf_token": token}).status_code == 302
    assert client.get("/api/companies").status_code == 401


def test_bearer_auth_and_cross_origin_rejection(secure_app):
    client = secure_app.test_client()
    assert client.post("/api/security-probe", headers={"Authorization": "Bearer test-only-bearer-token"}).status_code == 200
    assert client.post("/api/security-probe", headers={"Authorization": "Bearer incorrect"}).status_code == 401
    with client.session_transaction() as state:
        state["authenticated"] = True
    assert client.post("/api/security-probe", headers={"Origin": "https://untrusted.invalid"}).status_code == 403
    assert client.get("/login").headers["Cache-Control"] == "no-store"


def test_login_rate_limit(secure_app):
    client = secure_app.test_client()
    page = client.get("/login")
    token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    statuses = [client.post("/login", data={"username": "admin", "password": "wrong", "csrf_token": token}).status_code for attempt in range(6)]
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429


def test_trusted_https_proxy_preserves_csrf_origin(secure_app, monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "true")
    app = create_app()
    app.config["TESTING"] = True
    app.add_url_rule("/api/security-probe", view_func=lambda: {"ok": True}, methods=["POST"])
    client = app.test_client()
    headers = {
        "X-Forwarded-Proto": "https", "Origin": "https://example.test",
        "Referer": "https://example.test/login",
    }
    page = client.get("/login", base_url="http://example.test", headers=headers)
    token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    response = client.post("/login", base_url="http://example.test", headers=headers, data={
        "username": "admin", "password": "test-only-password", "csrf_token": token,
    })
    assert response.status_code == 302
    page = client.get("/login", base_url="http://example.test", headers=headers)
    token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    assert client.post("/api/security-probe", base_url="http://example.test", headers={**headers, "X-CSRFToken": token}).status_code == 200