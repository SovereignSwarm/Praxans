"""Ecology & Regional Fertility System for Praxans.

Divides the world into a grid of ecological regions, each with a fertility
score (0-100) that responds to harvesting pressure, weather, season, and
biome type.  Low fertility reduces resource spawn chance in that region,
creating genuine scarcity and strategic pressure.

Integration points:
    - Record harvest:  ecology.record_harvest(x, y, resource_type)
    - Spawn modifier:  ecology.get_fertility_multiplier(x, y)  -> 0.0-1.0
    - Tick:            ecology.update(delta_time, season, weather_system)
    - EventBus:        publishes CATEGORY_DISASTER on degradation, milestone on recovery
    - Snapshot:        ecology.serialize() / EcologyManager.deserialize(data, ...)
"""

from __future__ import annotations

import math
import time
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CELL_SIZE = 512          # px per ecological region (matches chunk size)
DEFAULT_FERTILITY = 80.0         # Starting fertility for all cells
MAX_FERTILITY = 100.0
MIN_FERTILITY = 0.0

# Harvesting impact per resource type
HARVEST_IMPACT = {
    "food": 1.2,     # food harvesting has moderate impact
    "wood": 2.5,     # tree-felling is damaging
    "stone": 1.8,    # mining scars the land
}

# Regeneration rate per second (base, before modifiers)
BASE_REGEN_RATE = 0.08           # fertility points per second

# Season regeneration multipliers
SEASON_REGEN = {
    "spring": 1.6,
    "summer": 1.0,
    "autumn": 0.7,
    "winter": 0.3,
}

# Weather regeneration multipliers
WEATHER_REGEN = {
    "clear":   1.0,
    "rain":    1.8,    # rain accelerates regrowth
    "storm":   0.6,    # storms damage ecology
    "drought": 0.2,    # drought stunts regeneration
    "aurora":  1.1,
}

# Weather direct damage (applied once per weather event)
WEATHER_DAMAGE = {
    "storm":   1.5,    # storms directly reduce fertility
    "drought": 2.0,    # drought scorches the land
}

# Fertility thresholds for status labels
THRESHOLD_BARREN   = 15.0
THRESHOLD_DEGRADED = 35.0
THRESHOLD_STRESSED = 55.0
THRESHOLD_HEALTHY  = 75.0
# Above HEALTHY = "Lush"

# Biome base fertility caps (some biomes are naturally less fertile)
BIOME_FERTILITY_CAP = {
    "forest":    100.0,
    "plains":    95.0,
    "swamp":     90.0,
    "taiga":     80.0,
    "mountains": 60.0,
    "tundra":    50.0,
    "desert":    40.0,
    "snow":      45.0,
}

# Biome regeneration rate multipliers
BIOME_REGEN_MULT = {
    "forest":    1.4,
    "plains":    1.1,
    "swamp":     1.2,
    "taiga":     0.8,
    "mountains": 0.5,
    "tundra":    0.4,
    "desert":    0.3,
    "snow":      0.3,
}

# How many harvests before degradation event fires
DEGRADATION_HARVEST_THRESHOLD = 20


# ---------------------------------------------------------------------------
# Ecology Cell
# ---------------------------------------------------------------------------

class EcoCell:
    """A single ecological region on the grid."""

    __slots__ = (
        "fertility", "harvest_pressure", "total_harvests",
        "biome", "status", "_last_event_fertility",
    )

    def __init__(self, fertility: float = DEFAULT_FERTILITY, biome: str = "plains"):
        self.fertility: float = fertility
        self.harvest_pressure: float = 0.0   # accumulated pressure since last regen tick
        self.total_harvests: int = 0
        self.biome: str = biome
        self.status: str = _fertility_status(fertility)
        self._last_event_fertility: float = fertility  # track for event hysteresis

    def to_dict(self) -> dict[str, Any]:
        return {
            "fertility": round(self.fertility, 2),
            "harvest_pressure": round(self.harvest_pressure, 2),
            "total_harvests": self.total_harvests,
            "biome": self.biome,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "EcoCell":
        cell = EcoCell(
            fertility=float(data.get("fertility", DEFAULT_FERTILITY)),
            biome=str(data.get("biome", "plains")),
        )
        cell.harvest_pressure = float(data.get("harvest_pressure", 0.0))
        cell.total_harvests = int(data.get("total_harvests", 0))
        cell.status = _fertility_status(cell.fertility)
        cell._last_event_fertility = cell.fertility
        return cell


def _fertility_status(fertility: float) -> str:
    if fertility <= THRESHOLD_BARREN:
        return "Barren"
    elif fertility <= THRESHOLD_DEGRADED:
        return "Degraded"
    elif fertility <= THRESHOLD_STRESSED:
        return "Stressed"
    elif fertility <= THRESHOLD_HEALTHY:
        return "Healthy"
    else:
        return "Lush"


# ---------------------------------------------------------------------------
# Ecology Manager
# ---------------------------------------------------------------------------

class EcologyManager:
    """Grid-based ecology tracking for the entire world.

    Responsibilities:
        - Track per-cell fertility that decreases with harvesting
        - Regenerate fertility based on weather, season, biome
        - Provide spawn multipliers for the resource respawn loop
        - Publish events when regions degrade or recover
    """

    def __init__(
        self,
        world_width: int,
        world_height: int,
        cell_size: int = DEFAULT_CELL_SIZE,
        world_map: Any = None,
    ):
        self.cell_size = cell_size
        self.cols = max(1, math.ceil(world_width / cell_size))
        self.rows = max(1, math.ceil(world_height / cell_size))
        self.world_width = world_width
        self.world_height = world_height

        # Build grid, seeding biome from world_map if available
        self.grid: list[list[EcoCell]] = []
        for col in range(self.cols):
            column: list[EcoCell] = []
            for row in range(self.rows):
                cx = col * cell_size + cell_size // 2
                cy = row * cell_size + cell_size // 2
                biome = "plains"
                if world_map is not None:
                    try:
                        biome = world_map.get_biome_at(cx, cy)
                    except Exception:
                        pass
                cap = BIOME_FERTILITY_CAP.get(biome, 80.0)
                initial = min(DEFAULT_FERTILITY, cap)
                column.append(EcoCell(fertility=initial, biome=biome))
            self.grid.append(column)

        self.last_update_time: float = 0.0
        self.update_interval: float = 4.0   # seconds between regen ticks
        self._pending_events: list[dict[str, Any]] = []

        # Aggregate stats
        self.total_harvests: int = 0
        self.degradation_events: int = 0
        self.recovery_events: int = 0

    # ---- coordinate helpers ------------------------------------------------

    def _cell_coords(self, x: float, y: float) -> tuple[int, int]:
        col = max(0, min(self.cols - 1, int(x / self.cell_size)))
        row = max(0, min(self.rows - 1, int(y / self.cell_size)))
        return col, row

    def _get_cell(self, x: float, y: float) -> EcoCell:
        col, row = self._cell_coords(x, y)
        return self.grid[col][row]

    # ---- public API --------------------------------------------------------

    def record_harvest(self, x: float, y: float, resource_type: str) -> None:
        """Called when a praxan finishes gathering a resource."""
        cell = self._get_cell(x, y)
        impact = HARVEST_IMPACT.get(resource_type, 1.0)
        cell.harvest_pressure += impact
        cell.total_harvests += 1
        self.total_harvests += 1

        # Apply immediate fertility reduction
        cell.fertility = max(MIN_FERTILITY, cell.fertility - impact * 0.5)
        cell.status = _fertility_status(cell.fertility)

    def get_fertility_multiplier(self, x: float, y: float) -> float:
        """Return a 0.0-1.0 multiplier for resource spawn probability at (x, y).

        1.0 = fully fertile, 0.0 = barren (no spawns).
        Uses a gentle curve so fertility has to drop quite low before
        spawn rates are seriously affected.
        """
        cell = self._get_cell(x, y)
        # Quadratic curve: mild effect until fertility < 50, severe below 25
        ratio = cell.fertility / MAX_FERTILITY
        return max(0.0, min(1.0, ratio * ratio + 0.15 * ratio))

    def get_region_info(self, x: float, y: float) -> dict[str, Any]:
        """Return human-readable info about the ecological region at (x, y)."""
        cell = self._get_cell(x, y)
        return {
            "fertility": round(cell.fertility, 1),
            "status": cell.status,
            "biome": cell.biome,
            "total_harvests": cell.total_harvests,
            "spawn_multiplier": round(self.get_fertility_multiplier(x, y), 2),
        }

    def get_world_fertility_summary(self) -> dict[str, Any]:
        """Aggregate ecology stats for HUD / LLM state views."""
        total_cells = self.cols * self.rows
        total_fertility = 0.0
        status_counts: dict[str, int] = {}
        for col in self.grid:
            for cell in col:
                total_fertility += cell.fertility
                status_counts[cell.status] = status_counts.get(cell.status, 0) + 1
        avg_fertility = total_fertility / total_cells if total_cells else 0.0
        return {
            "avg_fertility": round(avg_fertility, 1),
            "total_harvests": self.total_harvests,
            "degradation_events": self.degradation_events,
            "recovery_events": self.recovery_events,
            "region_counts": dict(status_counts),
            "grid_size": f"{self.cols}x{self.rows}",
        }

    # ---- update / tick -----------------------------------------------------

    def update(
        self,
        current_time: float,
        season: Any = None,
        weather_system: Any = None,
        event_bus: Any = None,
    ) -> None:
        """Regeneration tick — call on rare-tick schedule (~4s)."""
        if current_time - self.last_update_time < self.update_interval:
            return
        dt = current_time - self.last_update_time if self.last_update_time else self.update_interval
        self.last_update_time = current_time

        # Resolve modifiers
        season_name = getattr(season, "current", "summer") if season else "summer"
        weather_name = getattr(weather_system, "current_weather", "clear") if weather_system else "clear"
        season_mult = SEASON_REGEN.get(season_name, 1.0)
        weather_mult = WEATHER_REGEN.get(weather_name, 1.0)
        weather_dmg = WEATHER_DAMAGE.get(weather_name, 0.0)

        for col_idx, column in enumerate(self.grid):
            for row_idx, cell in enumerate(column):
                biome_mult = BIOME_REGEN_MULT.get(cell.biome, 1.0)
                cap = BIOME_FERTILITY_CAP.get(cell.biome, MAX_FERTILITY)

                # Apply weather damage (distributed over the tick interval)
                if weather_dmg > 0:
                    cell.fertility = max(
                        MIN_FERTILITY,
                        cell.fertility - weather_dmg * 0.1 * dt,
                    )

                # Regeneration: base * biome * season * weather * dt
                regen = BASE_REGEN_RATE * biome_mult * season_mult * weather_mult * dt

                # Harvest pressure decays over time, slowing regen
                if cell.harvest_pressure > 0:
                    pressure_penalty = min(0.8, cell.harvest_pressure * 0.04)
                    regen *= (1.0 - pressure_penalty)
                    # Decay pressure
                    cell.harvest_pressure = max(
                        0.0,
                        cell.harvest_pressure - 0.3 * dt,
                    )

                cell.fertility = min(cap, cell.fertility + regen)
                new_status = _fertility_status(cell.fertility)

                # Check for degradation / recovery events (with hysteresis)
                old_status = cell.status
                if new_status != old_status:
                    cell.status = new_status
                    self._check_status_event(
                        col_idx, row_idx, cell, old_status, new_status, event_bus,
                    )

    def apply_weather_event(
        self,
        weather_type: str,
        event_bus: Any = None,
    ) -> None:
        """Called once when a new weather event starts (optional, for burst damage)."""
        dmg = WEATHER_DAMAGE.get(weather_type, 0.0)
        if dmg <= 0:
            return
        for column in self.grid:
            for cell in column:
                cell.fertility = max(
                    MIN_FERTILITY,
                    cell.fertility - dmg * 0.3,
                )
                cell.status = _fertility_status(cell.fertility)

    # ---- events ------------------------------------------------------------

    def _check_status_event(
        self,
        col: int,
        row: int,
        cell: EcoCell,
        old_status: str,
        new_status: str,
        event_bus: Any,
    ) -> None:
        """Publish EventBus events on significant fertility transitions."""
        status_order = ["Barren", "Degraded", "Stressed", "Healthy", "Lush"]
        old_idx = status_order.index(old_status) if old_status in status_order else 2
        new_idx = status_order.index(new_status) if new_status in status_order else 2

        cx = col * self.cell_size + self.cell_size // 2
        cy = row * self.cell_size + self.cell_size // 2

        if new_idx < old_idx and new_idx <= 1:
            # Degradation event
            self.degradation_events += 1
            if event_bus is not None:
                try:
                    from events.bus import GameEvent, CATEGORY_DISASTER
                    event_bus.publish(GameEvent(
                        category=CATEGORY_DISASTER,
                        summary=f"Region ({col},{row}) has become {new_status.lower()} — fertility at {cell.fertility:.0f}%",
                        detail=f"Biome: {cell.biome}, total harvests: {cell.total_harvests}",
                        location=(float(cx), float(cy)),
                        metadata={"ecology": True, "fertility": cell.fertility, "status": new_status},
                    ))
                except ImportError:
                    pass

        elif new_idx > old_idx and old_idx <= 1 and new_idx >= 2:
            # Recovery event
            self.recovery_events += 1
            if event_bus is not None:
                try:
                    from events.bus import GameEvent, CATEGORY_MILESTONE
                    event_bus.publish(GameEvent(
                        category=CATEGORY_MILESTONE,
                        summary=f"Region ({col},{row}) has recovered to {new_status.lower()} — fertility at {cell.fertility:.0f}%",
                        detail=f"Biome: {cell.biome}",
                        location=(float(cx), float(cy)),
                        metadata={"ecology": True, "fertility": cell.fertility, "status": new_status},
                    ))
                except ImportError:
                    pass

    # ---- serialization -----------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        """Serialize ecology state for snapshots."""
        cells = []
        for col_idx, column in enumerate(self.grid):
            for row_idx, cell in enumerate(column):
                # Only serialize cells that deviate from default to save space
                if (
                    abs(cell.fertility - DEFAULT_FERTILITY) > 1.0
                    or cell.harvest_pressure > 0.5
                    or cell.total_harvests > 0
                ):
                    cells.append({
                        "col": col_idx,
                        "row": row_idx,
                        **cell.to_dict(),
                    })
        return {
            "cell_size": self.cell_size,
            "cols": self.cols,
            "rows": self.rows,
            "total_harvests": self.total_harvests,
            "degradation_events": self.degradation_events,
            "recovery_events": self.recovery_events,
            "cells": cells,
        }

    @classmethod
    def deserialize(
        cls,
        data: dict[str, Any],
        world_width: int,
        world_height: int,
        world_map: Any = None,
    ) -> "EcologyManager":
        """Restore an EcologyManager from snapshot data."""
        cell_size = int(data.get("cell_size", DEFAULT_CELL_SIZE))
        mgr = cls(world_width, world_height, cell_size=cell_size, world_map=world_map)
        mgr.total_harvests = int(data.get("total_harvests", 0))
        mgr.degradation_events = int(data.get("degradation_events", 0))
        mgr.recovery_events = int(data.get("recovery_events", 0))

        for cell_data in data.get("cells", []):
            col = int(cell_data.get("col", 0))
            row = int(cell_data.get("row", 0))
            if 0 <= col < mgr.cols and 0 <= row < mgr.rows:
                mgr.grid[col][row] = EcoCell.from_dict(cell_data)

        return mgr
