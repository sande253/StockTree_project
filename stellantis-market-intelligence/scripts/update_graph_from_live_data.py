"""Seed the relationship graph from its evidence-backed configuration."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from relationships.graph import load_and_store_relationships

count = load_and_store_relationships()
print(f"Loaded {count} evidence-backed relationships from config/relationships.yaml")
print("Market correlations remain statistical data and are not written to the relationship graph.")
