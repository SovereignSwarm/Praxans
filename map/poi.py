"""
Points of Interest (POI) — Strategic geography layer for the world map.

Generates faction settlements, ancient ruins, resource deposits, and trade posts
across the world map. POIs provide targets for caravanning and strategic decisions.
"""
from __future__ import annotations

import random
import math
import logging
from typing import Optional

logger = logging.getLogger("POI")


# POI Categories
POI_SETTLEMENT = "settlement"
POI_RUIN = "ruin"
POI_DEPOSIT = "resource_deposit"
POI_TRADE_POST = "trade_post"
POI_SHRINE = "ancient_shrine"
POI_CAVE = "cave"


class PointOfInterest:
    """A world-map level Point of Interest."""

    def __init__(self, poi_id: str, name: str, category: str,
                 world_x: float, world_y: float, biome: str = "plains"):
        self.poi_id = poi_id
        self.name = name
        self.category = category
        self.world_x = world_x
        self.world_y = world_y
        self.biome = biome
        self.discovered = False
        self.visited = False
        self.faction: Optional[str] = None

        # Category-specific data
        self.resources: dict[str, int] = {}       # For deposits/trade posts
        self.danger_level: int = 0                 # 0-5 threat scale
        self.description: str = ""
        self.loot_table: list[dict] = []          # Items available on visit

    def distance_to(self, x: float, y: float) -> float:
        return math.sqrt((self.world_x - x)**2 + (self.world_y - y)**2)

    def to_dict(self) -> dict:
        return {
            "poi_id": self.poi_id,
            "name": self.name,
            "category": self.category,
            "world_x": self.world_x,
            "world_y": self.world_y,
            "biome": self.biome,
            "discovered": self.discovered,
            "visited": self.visited,
            "faction": self.faction,
            "resources": self.resources,
            "danger_level": self.danger_level,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PointOfInterest":
        poi = cls(
            poi_id=data.get("poi_id", "unknown"),
            name=data.get("name", "Unknown Location"),
            category=data.get("category", POI_RUIN),
            world_x=data.get("world_x", 0.0),
            world_y=data.get("world_y", 0.0),
            biome=data.get("biome", "plains"),
        )
        poi.discovered = data.get("discovered", False)
        poi.visited = data.get("visited", False)
        poi.faction = data.get("faction")
        poi.resources = data.get("resources", {})
        poi.danger_level = data.get("danger_level", 0)
        return poi


# ---- Name Generation ----

_SETTLEMENT_NAMES = [
    "Haven", "Windbreak", "Thornfield", "Dusthollow", "Frostpeak",
    "Ember Ridge", "Salt Marsh", "Iron Gate", "Greenwall", "Ashford",
    "Stone Hearth", "Tall Pine", "Red Hill", "Silver Creek", "Dark Water",
]

_RUIN_NAMES = [
    "The Old Works", "Shattered Pillar", "Forsaken Hall", "Bone Garden",
    "Echo Chamber", "Collapsed Archive", "Silent Tower", "Rusted Gate",
]

_DEPOSIT_NAMES = [
    "Rich Vein", "Crystal Formation", "Deep Quarry", "Mineral Seam",
    "Ore Shelf", "Gem Pocket", "Stone Bed", "Clay Basin",
]

_SHRINE_NAMES = [
    "Star Altar", "Moon Basin", "Sunken Sanctum", "Whispering Stone",
    "Ancient Monolith", "Primal Circle", "Elder's Rest",
]


class POIGenerator:
    """Generates Points of Interest for the world map."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self._name_counters = {}

    def generate(self, world_width: float, world_height: float,
                 biome_fn=None, count: int = 12) -> list[PointOfInterest]:
        """
        Generate POIs distributed across the world.
        
        Args:
            world_width: Width of the world in pixels
            world_height: Height of the world in pixels
            biome_fn: Optional callable(x, y) -> biome_name
            count: Number of POIs to generate
        """
        pois = []
        margin = 200
        min_distance = 400  # Minimum distance between POIs

        # Define category distribution
        categories = [
            (POI_SETTLEMENT, 0.25),
            (POI_RUIN, 0.20),
            (POI_DEPOSIT, 0.20),
            (POI_TRADE_POST, 0.15),
            (POI_SHRINE, 0.10),
            (POI_CAVE, 0.10),
        ]

        for i in range(count):
            # Pick category using weighted distribution
            roll = self.rng.random()
            cumulative = 0.0
            category = POI_RUIN
            for cat, weight in categories:
                cumulative += weight
                if roll <= cumulative:
                    category = cat
                    break

            # Find a position that's not too close to existing POIs
            attempts = 0
            while attempts < 50:
                x = self.rng.uniform(margin, world_width - margin)
                y = self.rng.uniform(margin, world_height - margin)

                too_close = any(
                    poi.distance_to(x, y) < min_distance for poi in pois
                )
                if not too_close:
                    break
                attempts += 1

            biome = biome_fn(x, y) if biome_fn else "plains"
            poi = self._create_poi(f"poi_{i}", category, x, y, biome)
            pois.append(poi)

        logger.info(f"Generated {len(pois)} Points of Interest")
        return pois

    def _create_poi(self, poi_id: str, category: str,
                    x: float, y: float, biome: str) -> PointOfInterest:
        """Create a POI with category-appropriate attributes."""

        if category == POI_SETTLEMENT:
            name = self.rng.choice(_SETTLEMENT_NAMES)
            poi = PointOfInterest(poi_id, name, category, x, y, biome)
            poi.faction = self.rng.choice(["neutral", "friendly", "hostile"])
            poi.danger_level = {"neutral": 1, "friendly": 0, "hostile": 3}[poi.faction]
            poi.description = f"A {poi.faction} settlement in the {biome}."
            poi.resources = {"food": self.rng.randint(5, 20), "wood": self.rng.randint(3, 15)}

        elif category == POI_RUIN:
            name = self.rng.choice(_RUIN_NAMES)
            poi = PointOfInterest(poi_id, name, category, x, y, biome)
            poi.danger_level = self.rng.randint(2, 4)
            poi.description = "Ancient ruins that may contain valuable artifacts."
            poi.loot_table = [
                {"type": "stone", "amount": self.rng.randint(10, 30)},
                {"type": "wood", "amount": self.rng.randint(5, 15)},
            ]

        elif category == POI_DEPOSIT:
            name = self.rng.choice(_DEPOSIT_NAMES)
            poi = PointOfInterest(poi_id, name, category, x, y, biome)
            poi.danger_level = 0
            res_type = self.rng.choice(["stone", "wood", "food"])
            poi.resources = {res_type: self.rng.randint(20, 50)}
            poi.description = f"A rich {res_type} deposit."

        elif category == POI_TRADE_POST:
            name = "Trader's Rest"
            poi = PointOfInterest(poi_id, name, category, x, y, biome)
            poi.faction = "neutral"
            poi.danger_level = 0
            poi.resources = {
                "food": self.rng.randint(10, 30),
                "wood": self.rng.randint(5, 20),
                "stone": self.rng.randint(5, 20),
            }
            poi.description = "A traveling merchant's outpost."

        elif category == POI_SHRINE:
            name = self.rng.choice(_SHRINE_NAMES)
            poi = PointOfInterest(poi_id, name, category, x, y, biome)
            poi.danger_level = self.rng.randint(1, 3)
            poi.description = "A mystical shrine with unknown powers."

        elif category == POI_CAVE:
            name = "Hidden Cave"
            poi = PointOfInterest(poi_id, name, category, x, y, biome)
            poi.danger_level = self.rng.randint(2, 5)
            poi.description = "A dark cave that may hold treasures or dangers."
            poi.loot_table = [
                {"type": "stone", "amount": self.rng.randint(15, 40)},
            ]

        else:
            poi = PointOfInterest(poi_id, "Unknown", category, x, y, biome)

        return poi
