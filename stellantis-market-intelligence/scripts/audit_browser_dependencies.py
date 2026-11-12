"""Audit exactly pinned CDN script dependencies using the OSV advisory service."""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            source = dict(attrs).get("src")
            if source:
                self.sources.append(source)


def collect_dependencies(directory: Path) -> list[dict]:
    dependencies = {}
    for path in directory.glob("*.html"):
        parser = ScriptSources()
        parser.feed(path.read_text(encoding="utf-8"))
        for source in parser.sources:
            parsed = urlparse(source)
            if parsed.hostname != "cdn.jsdelivr.net":
                if parsed.scheme in {"http", "https"}:
                    raise ValueError(f"Unsupported CDN must be audited explicitly: {path.name}")
                continue
            match = re.match(r"^/npm/((?:@[^/]+/)?[^/@]+)@(\d+\.\d+\.\d+)/", parsed.path)
            if match is None:
                raise ValueError(f"Script dependency must have an exact version: {path.name}")
            name, version = match.groups()
            dependencies[(name, version)] = {"package": {"name": name, "ecosystem": "npm"}, "version": version}
    return list(dependencies.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/reports/browser-audit.json"))
    args = parser.parse_args()
    dependencies = collect_dependencies(Path("dashboard/templates"))
    response = requests.post("https://api.osv.dev/v1/querybatch", json={"queries": dependencies}, timeout=30)
    response.raise_for_status()
    results = response.json()["results"]
    if len(results) != len(dependencies):
        raise RuntimeError("Incomplete advisory response")
    findings = [{**dependency, "vulns": result.get("vulns", [])} for dependency, result in zip(dependencies, results)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    affected = sum(bool(finding["vulns"]) for finding in findings)
    print(f"Audited {len(dependencies)} browser dependencies; {affected} affected packages")
    raise SystemExit(1 if affected else 0)


if __name__ == "__main__":
    main()