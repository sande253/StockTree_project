"""Coordinate atomic JSON publication with readers in the single app process."""

import json
import threading
from pathlib import Path
from uuid import uuid4

_LOCK = threading.RLock()


def write_json(path: Path, payload: dict) -> None:
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        temporary.replace(path)


def read_json(path: Path) -> dict:
    with _LOCK:
        return json.loads(path.read_text(encoding="utf-8"))