"""Portable warehouse backups with checksums and non-destructive restore."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import duckdb

from storage.duckdb import get_connection


def _checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def backup_warehouse(
    db_path: Path | str | None = None,
    backup_dir: Path | str = "data/backups",
    index_dir: Path | str | None = "data/vector_store",
) -> dict:
    destination = Path(backup_dir) / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    destination.mkdir(parents=True, exist_ok=False)
    conn = get_connection(db_path)
    try:
        export_path = str((destination / "warehouse").resolve()).replace("'", "''")
        conn.execute(f"EXPORT DATABASE '{export_path}' (FORMAT PARQUET)")
        if index_dir is not None and Path(index_dir).is_dir():
            shutil.copytree(index_dir, destination / "vector_store")
        manifest = {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": {
                path.relative_to(destination).as_posix(): _checksum(path)
                for path in sorted(destination.rglob("*")) if path.is_file()
            },
        }
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {"path": str(destination), "files": len(manifest["files"])}
    except Exception:
        shutil.rmtree(destination)
        raise
    finally:
        conn.close()


def verify_backup(backup_path: Path | str) -> dict:
    root = Path(backup_path).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or not manifest.get("files"):
        raise ValueError("Invalid backup manifest")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if actual != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("Backup contains missing or unexpected files")
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or _checksum(path) != expected:
            raise ValueError(f"Backup verification failed: {relative}")
    return manifest


def restore_warehouse(backup_path: Path | str, target: Path | str) -> dict:
    verify_backup(backup_path)
    target = Path(target)
    if target.exists():
        raise FileExistsError("Restore target already exists; restore to a new warehouse and verify it first")
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(target))
    try:
        source = str((Path(backup_path) / "warehouse").resolve()).replace("'", "''")
        conn.execute(f"IMPORT DATABASE '{source}'")
        tables = conn.execute("SHOW TABLES").fetchall()
        return {"warehouse": str(target), "tables": len(tables)}
    except Exception:
        conn.close()
        target.unlink(missing_ok=True)
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    if args.restore:
        if args.target is None:
            parser.error("--restore requires a new --target path")
        result = restore_warehouse(args.restore, args.target)
    else:
        result = backup_warehouse()
        verify_backup(result["path"])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()