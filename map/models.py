from __future__ import annotations

from dataclasses import asdict, dataclass, field


WORLD_GENERATION_VERSION = 2


@dataclass(frozen=True)
class WorldSeed:
    value: int


@dataclass(frozen=True)
class WorldProfile:
    chunk_cols: int = 16
    chunk_rows: int = 12
    region_cols: int = 8
    region_rows: int = 6
    chunk_size: int = 512
    tile_size: int = 32
    climate_bias: str = "temperate"
    ruggedness: float = 0.55
    water_abundance: float = 0.5
    hazard_density: float = 0.45
    polity_count: int = 5
    polity_cap: int = 8
    resource_richness: float = 1.0
    mutation_pressure: float = 1.0
    temperature_bias: float = 0.0
    moisture_bias: float = 0.0
    zoom_bands: tuple[float, ...] = (0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)

    @property
    def world_width(self) -> int:
        return self.chunk_cols * self.chunk_size

    @property
    def world_height(self) -> int:
        return self.chunk_rows * self.chunk_size

    @property
    def region_width(self) -> int:
        return max(1, self.world_width // max(1, self.region_cols))

    @property
    def region_height(self) -> int:
        return max(1, self.world_height // max(1, self.region_rows))

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["zoom_bands"] = list(self.zoom_bands)
        return payload


@dataclass(frozen=True)
class WorldRegion:
    region_id: str
    col: int
    row: int
    world_rect: tuple[int, int, int, int]
    biome: str
    elevation: float
    moisture: float
    temperature: float
    fertility: float
    defensibility: float
    water_score: float
    frontier_score: float
    route_score: float
    coastal: bool = False
    river: bool = False
    landmark_ids: tuple[str, ...] = field(default_factory=tuple)
    settlement_ids: tuple[str, ...] = field(default_factory=tuple)
    claimed_by: int | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "region_id": self.region_id,
            "col": self.col,
            "row": self.row,
            "world_rect": list(self.world_rect),
            "biome": self.biome,
            "elevation": round(self.elevation, 4),
            "moisture": round(self.moisture, 4),
            "temperature": round(self.temperature, 4),
            "fertility": round(self.fertility, 4),
            "defensibility": round(self.defensibility, 4),
            "water_score": round(self.water_score, 4),
            "frontier_score": round(self.frontier_score, 4),
            "route_score": round(self.route_score, 4),
            "coastal": self.coastal,
            "river": self.river,
            "landmark_ids": list(self.landmark_ids),
            "settlement_ids": list(self.settlement_ids),
            "claimed_by": self.claimed_by,
        }


@dataclass(frozen=True)
class ChunkState:
    chunk_x: int
    chunk_y: int
    world_x: int
    world_y: int
    tiles: dict[tuple[int, int], str]
    elevations: dict[tuple[int, int], float] = field(default_factory=dict)
    moistures: dict[tuple[int, int], float] = field(default_factory=dict)
    biome_mix: dict[str, float] = field(default_factory=dict)
    elevation_avg: float = 0.0
    moisture_avg: float = 0.0
    temperature_avg: float = 0.0
    region_id: str = ""
    water_tiles: tuple[tuple[int, int], ...] = field(default_factory=tuple)
    river_tiles: tuple[tuple[int, int], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Landmark:
    landmark_id: str
    region_id: str
    name: str
    category: str
    x: float
    y: float
    importance: float

    def to_payload(self) -> dict[str, object]:
        return {
            "landmark_id": self.landmark_id,
            "region_id": self.region_id,
            "name": self.name,
            "category": self.category,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "importance": round(self.importance, 4),
        }


@dataclass(frozen=True)
class Route:
    route_id: str
    route_type: str
    start_region_id: str
    end_region_id: str
    points: tuple[tuple[float, float], ...]
    risk: float

    def to_payload(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "route_type": self.route_type,
            "start_region_id": self.start_region_id,
            "end_region_id": self.end_region_id,
            "points": [{"x": round(x, 2), "y": round(y, 2)} for x, y in self.points],
            "risk": round(self.risk, 4),
        }


@dataclass(frozen=True)
class SettlementState:
    settlement_id: str
    region_id: str
    x: float
    y: float
    settlement_type: str
    population: int
    prosperity: float
    water_access: float
    route_access: float
    polity_id: int | None

    def to_payload(self) -> dict[str, object]:
        return {
            "settlement_id": self.settlement_id,
            "region_id": self.region_id,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "settlement_type": self.settlement_type,
            "population": self.population,
            "prosperity": round(self.prosperity, 4),
            "water_access": round(self.water_access, 4),
            "route_access": round(self.route_access, 4),
            "polity_id": self.polity_id,
        }


@dataclass(frozen=True)
class PolityMapState:
    polity_id: int
    name: str
    home_region_id: str
    doctrine_bias: str
    frontier_pressure: float
    settlement_ids: tuple[str, ...]
    claimed_region_ids: tuple[str, ...]
    trade_route_ids: tuple[str, ...]
    capital_settlement_id: str | None
    accent_color: tuple[int, int, int]

    def to_payload(self) -> dict[str, object]:
        return {
            "polity_id": self.polity_id,
            "name": self.name,
            "home_region_id": self.home_region_id,
            "doctrine_bias": self.doctrine_bias,
            "frontier_pressure": round(self.frontier_pressure, 4),
            "settlement_ids": list(self.settlement_ids),
            "claimed_region_ids": list(self.claimed_region_ids),
            "trade_route_ids": list(self.trade_route_ids),
            "capital_settlement_id": self.capital_settlement_id,
            "accent_color": list(self.accent_color),
        }
