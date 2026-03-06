"""Spatial systems façade — re-exports from the monolith.

This module establishes the target namespace for spatial system code.
New code should import from here rather than thronglets_game directly.

Classes available:
- FogOfWar: Manages tile-based visibility driven by thronglet proximity
- TerritoryManager: Voronoi-based territory claiming
- CityPlanner: LLM-integrated zone generation and building placement
"""

from __future__ import annotations

# Re-export spatial system classes from the monolith
from thronglets_game import (  # noqa: F401
    FogOfWar,
    TerritoryManager,
    CityPlanner,
)
