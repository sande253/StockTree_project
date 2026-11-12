"""Entity model for the corporate relationship graph (Phase 11).

Entities are the nodes of the graph: Stellantis itself, its brands, suppliers,
competitors, partners, technologies, products, manufacturing facilities, and
geographic regions.
"""

from __future__ import annotations

from dataclasses import dataclass

from storage.schemas import VALID_ENTITY_TYPES

STELLANTIS_ENTITY_ID = "STLA"


@dataclass(frozen=True)
class Entity:
    """A single node in the corporate relationship graph."""

    entity_id: str
    name: str
    entity_type: str

    def __post_init__(self) -> None:
        if not self.entity_id or not self.entity_id.strip():
            raise ValueError("Entity.entity_id must be a non-empty string")
        if not self.name or not self.name.strip():
            raise ValueError("Entity.name must be a non-empty string")
        if self.entity_type not in VALID_ENTITY_TYPES:
            raise ValueError(f"Entity.entity_type {self.entity_type!r} is not one of {sorted(VALID_ENTITY_TYPES)}")
