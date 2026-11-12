"""Configure local deployment secrets without printing or transmitting passwords."""

from __future__ import annotations

import getpass
import os
import secrets
from pathlib import Path

from dotenv import dotenv_values, set_key
from werkzeug.security import generate_password_hash


def main() -> None:
    username = input("Dashboard username [admin]: ").strip() or "admin"
    password = getpass.getpass("Dashboard password (minimum 14 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 14 or password != confirmation:
        raise SystemExit("Passwords must match and contain at least 14 characters; nothing was changed.")
    path = Path(".env")
    existing = dotenv_values(path) if path.exists() else {}
    path.touch(exist_ok=True)
    os.chmod(path, 0o600)
    for key, value in {
        "AUTH_USERNAME": username,
        "AUTH_PASSWORD_HASH": generate_password_hash(password),
        "SECRET_KEY": existing["SECRET_KEY"] if len(existing.get("SECRET_KEY") or "") >= 32 else secrets.token_hex(32),
        "ENABLE_SCHEDULER": existing.get("ENABLE_SCHEDULER") or "true",
    }.items():
        set_key(str(path), key, value)
    print("Authentication configured. Production sessions require HTTPS. Restrict .env access to the service account.")


if __name__ == "__main__":
    main()