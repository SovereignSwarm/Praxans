"""Natural Disasters & Environmental Events System.

Adds area-of-effect environmental catastrophes (earthquakes, floods, wildfires,
blizzards, toxic blooms, meteor strikes, dust storms) that damage buildings,
injure praxans, destroy resources, and trigger follow-up disease outbreaks.

Disaster definitions live in ``defs/core/disasters.json`` and are loaded via
``DefDatabase``.

Integration points:
    - ``DisasterManager.update()`` called from main loop (long-tick cadence ~33s)
    - Storyteller integration: registers disasters as high-cost bad incidents
    - EventBus: publishes CATEGORY_DISASTER events for cascades/title cards
    - Ecology: farm destruction, resource scatter
    - Disease: follow-up outbreaks after certain disasters
    - Snapshot: ``serialize()`` / ``restore()`` for save/load
"""

from __future__ import annotations

import math
import random
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# DisasterDef cache (loaded from DefDatabase lazily)
# ---------------------------------------------------------------------------

_disaster_def_cache: dict[str, dict[str, Any]] = {}


def _load_disaster_defs() -> None:
    """Populate cache from DefDatabase."""
    if _disaster_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        defs = DefDatabase.get_all("DisasterDef")  # returns {id: data_dict}
        for def_id, def_data in defs.items():
            _disaster_def_cache[def_id] = def_data
    except Exception:
        pass


def get_disaster_def(disaster_id: str) -> Optional[dict[str, Any]]:
    """Return a DisasterDef by id, or None."""
    _load_disaster_defs()
    return _disaster_def_cache.get(disaster_id)


def get_all_disaster_ids() -> list[str]:
    """Return all known disaster IDs."""
    _load_disaster_defs()
    return list(_disaster_def_cache.keys())


def clear_cache() -> None:
    """Clear the disaster def cache (for tests)."""
    _disaster_def_cache.clear()


# ---------------------------------------------------------------------------
# Active disaster instance
# ---------------------------------------------------------------------------

class ActiveDisaster:
    """A disaster currently in progress."""

    __slots__ = (
        "disaster_id", "center_x", "center_y", "severity",
        "started_at", "duration", "applied",
    )

    def __init__(
        self,
        disaster_id: str,
        center_x: float,
        center_y: float,
        severity: float,
        started_at: float,
        duration: float,
    ) -> None:
        self.disaster_id = disaster_id
        self.center_x = center_x
        self.center_y = center_y
        self.severity = severity
        self.started_at = started_at
        self.duration = duration
        self.applied = False  # effects applied on first tick

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.started_at + self.duration

    def to_dict(self) -> dict[str, Any]:
        return {
            "disaster_id": self.disaster_id,
            "center_x": round(self.center_x, 2),
            "center_y": round(self.center_y, 2),
            "severity": round(self.severity, 3),
            "elapsed": round(max(0.0, time.time() - self.started_at), 2),
            "duration": round(self.duration, 2),
            "applied": self.applied,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActiveDisaster":
        inst = cls(
            disaster_id=data["disaster_id"],
            center_x=data.get("center_x", 0.0),
            center_y=data.get("center_y", 0.0),
            severity=data.get("severity", 0.5),
            started_at=time.time() - data.get("elapsed", 0.0),
            duration=data.get("duration", 15.0),
        )
        inst.applied = data.get("applied", False)
        return inst


# ---------------------------------------------------------------------------
# DisasterManager
# ---------------------------------------------------------------------------

# Timing constants
EVAL_INTERVAL = 30.0        # Seconds between disaster evaluations
MIN_COOLDOWN_GLOBAL = 90.0  # Minimum time between any two disasters
BASE_CHANCE_PER_EVAL = 0.12 # Base probability of a disaster firing per eval


class DisasterManager:
    """Manages disaster evaluation, selection, execution, and state.

    Called from the main loop at long-tick cadence (~33s).
    """

    def __init__(self) -> None:
        self.active_disasters: list[ActiveDisaster] = []
        self.history: list[dict[str, Any]] = []  # recent disasters for UI/narrative
        self._last_eval_time: float = 0.0
        self._last_disaster_time: float = 0.0
        self._cooldowns: dict[str, float] = {}  # disaster_id -> last fired time
        self._max_history = 20

    # ---- main tick ---------------------------------------------------------

    def update(
        self,
        current_time: float,
        praxans: list,
        buildings: list,
        world_map: object | None = None,
        season_name: str = "summer",
        weather_name: str = "clear",
        event_bus: object | None = None,
        narrative_panel: object | None = None,
        storyteller_phase: str = "build_up",
        colony_wealth: float = 0.0,
    ) -> Optional[dict[str, Any]]:
        """Evaluate and possibly fire a disaster. Returns disaster info dict if fired."""
        # Clean up expired active disasters
        self.active_disasters = [d for d in self.active_disasters if not d.is_expired]

        # Apply effects for newly started disasters
        for ad in self.active_disasters:
            if not ad.applied:
                ad.applied = True
                self._apply_effects(
                    ad, praxans, buildings, world_map,
                    event_bus, narrative_panel,
                )

        # Evaluate for new disaster
        if current_time - self._last_eval_time < EVAL_INTERVAL:
            return None
        self._last_eval_time = current_time

        # Global cooldown
        if current_time - self._last_disaster_time < MIN_COOLDOWN_GLOBAL:
            return None

        # Phase-adjusted chance
        chance = BASE_CHANCE_PER_EVAL
        if storyteller_phase == "climax":
            chance *= 2.0
        elif storyteller_phase == "recovery":
            chance *= 0.2

        # Wealth scaling — more wealthy colonies attract more disasters
        if colony_wealth > 5000:
            chance *= 1.0 + min(1.0, (colony_wealth - 5000) / 20000)

        if random.random() > chance:
            return None

        # Select a disaster
        disaster_id = self._select_disaster(
            current_time, praxans, buildings,
            world_map, season_name, weather_name,
        )
        if disaster_id is None:
            return None

        # Fire it
        result = self._fire_disaster(
            disaster_id, current_time, praxans, buildings,
            world_map, event_bus, narrative_panel,
        )
        return result

    # ---- selection ---------------------------------------------------------

    def _select_disaster(
        self,
        current_time: float,
        praxans: list,
        buildings: list,
        world_map: object | None,
        season_name: str,
        weather_name: str,
    ) -> Optional[str]:
        """Weighted selection of a disaster considering conditions."""
        _load_disaster_defs()
        if not _disaster_def_cache:
            return None

        candidates: list[tuple[str, float]] = []

        for did, ddef in _disaster_def_cache.items():
            # Check per-disaster cooldown
            last_fired = self._cooldowns.get(did, 0.0)
            cooldown = ddef.get("cooldown", 120.0)
            if current_time - last_fired < cooldown:
                continue

            # Check population/building minimums
            conditions = ddef.get("conditions", {})
            if len(praxans) < conditions.get("min_population", 1):
                continue
            if len(buildings) < conditions.get("min_buildings", 0):
                continue

            # Base weight
            weight = ddef.get("base_weight", 1.0)

            # Season weight
            season_weights = conditions.get("season_weights", {})
            weight *= season_weights.get(season_name, 1.0)

            # Weather boost
            weather_boost = conditions.get("weather_boost", {})
            weight *= weather_boost.get(weather_name, 1.0)

            # Biome weight — average across settlement area
            biome_weights = conditions.get("biome_weights", {})
            if world_map and biome_weights and buildings:
                biome_sum = 0.0
                for b in buildings[:10]:  # Sample up to 10 buildings
                    biome = world_map.get_biome_at(b.x, b.y)
                    biome_sum += biome_weights.get(biome, 1.0)
                weight *= biome_sum / min(len(buildings), 10)

            # Rare tag penalty
            tags = ddef.get("tags", [])
            if "rare" in tags:
                weight *= 0.15

            if weight > 0.01:
                candidates.append((did, weight))

        if not candidates:
            return None

        # Weighted random selection
        ids, weights = zip(*candidates)
        return random.choices(ids, weights=weights, k=1)[0]

    # ---- execution ---------------------------------------------------------

    def _fire_disaster(
        self,
        disaster_id: str,
        current_time: float,
        praxans: list,
        buildings: list,
        world_map: object | None,
        event_bus: object | None,
        narrative_panel: object | None,
    ) -> dict[str, Any]:
        """Create and fire a disaster event."""
        ddef = get_disaster_def(disaster_id)
        if ddef is None:
            return {}

        # Determine center — near the settlement center
        if buildings:
            avg_x = sum(b.x for b in buildings) / len(buildings)
            avg_y = sum(b.y for b in buildings) / len(buildings)
            # Add some randomness
            center_x = avg_x + random.uniform(-150, 150)
            center_y = avg_y + random.uniform(-150, 150)
        elif praxans:
            avg_x = sum(p.x for p in praxans) / len(praxans)
            avg_y = sum(p.y for p in praxans) / len(praxans)
            center_x = avg_x + random.uniform(-100, 100)
            center_y = avg_y + random.uniform(-100, 100)
        else:
            return {}

        # Severity roll (0.3-1.0 range, influenced by def)
        severity = random.uniform(0.3, 1.0)

        duration = ddef.get("duration", 15.0)

        # Create active disaster
        ad = ActiveDisaster(
            disaster_id=disaster_id,
            center_x=center_x,
            center_y=center_y,
            severity=severity,
            started_at=current_time,
            duration=duration,
        )
        self.active_disasters.append(ad)

        # Update tracking
        self._last_disaster_time = current_time
        self._cooldowns[disaster_id] = current_time

        # Record history
        record = {
            "disaster_id": disaster_id,
            "label": ddef.get("label", disaster_id),
            "severity": round(severity, 2),
            "time": round(current_time, 2),
            "center": (round(center_x, 1), round(center_y, 1)),
        }
        self.history.append(record)
        if len(self.history) > self._max_history:
            self.history = self.history[-self._max_history:]

        return record

    # ---- effect application ------------------------------------------------

    def _apply_effects(
        self,
        ad: ActiveDisaster,
        praxans: list,
        buildings: list,
        world_map: object | None,
        event_bus: object | None,
        narrative_panel: object | None,
    ) -> None:
        """Apply the disaster's effects to the game world."""
        ddef = get_disaster_def(ad.disaster_id)
        if ddef is None:
            return

        effects = ddef.get("effects", {})
        radius = ddef.get("radius", 300)
        severity = ad.severity
        label = ddef.get("label", ad.disaster_id)

        affected_praxans = 0
        affected_buildings = 0

        # --- Building damage ---
        building_damage_pct = effects.get("building_damage_pct", 0.0) * severity
        farm_destruction_pct = effects.get("farm_destruction_pct", 0.0) * severity
        wood_destruction_pct = effects.get("wood_destruction_pct", 0.0) * severity
        resource_scatter_pct = effects.get("resource_scatter_pct", 0.0) * severity

        for b in buildings:
            dist = math.sqrt((b.x - ad.center_x) ** 2 + (b.y - ad.center_y) ** 2)
            if dist > radius:
                continue

            affected_buildings += 1
            falloff = max(0.0, 1.0 - (dist / radius))

            # Scatter stored resources
            if resource_scatter_pct > 0:
                stored = getattr(b, "stored_resources", {})
                for rtype in list(stored.keys()):
                    loss = int(stored[rtype] * resource_scatter_pct * falloff)
                    if loss > 0:
                        stored[rtype] = max(0, stored[rtype] - loss)

            # Farm-specific crop destruction
            if getattr(b, "building_type", "") == "farm" and farm_destruction_pct > 0:
                stored = getattr(b, "stored_resources", {})
                food_loss = int(stored.get("food", 0) * farm_destruction_pct * falloff)
                if food_loss > 0:
                    stored["food"] = max(0, stored.get("food", 0) - food_loss)

            # Wood destruction (fires)
            if wood_destruction_pct > 0:
                stored = getattr(b, "stored_resources", {})
                wood_loss = int(stored.get("wood", 0) * wood_destruction_pct * falloff)
                if wood_loss > 0:
                    stored["wood"] = max(0, stored.get("wood", 0) - wood_loss)

        # --- Praxan damage ---
        health_damage = effects.get("health_damage", 0) * severity
        mood_offset = effects.get("mood_offset", 0) * severity

        for p in praxans:
            if not getattr(p, "alive", True):
                continue

            dist = math.sqrt((p.x - ad.center_x) ** 2 + (p.y - ad.center_y) ** 2)
            if dist > radius:
                continue

            affected_praxans += 1
            falloff = max(0.0, 1.0 - (dist / radius))

            # Health damage
            if health_damage > 0:
                dmg = health_damage * falloff
                p.health = max(1.0, p.health - dmg)

            # Mood impact via moodlet
            if mood_offset != 0:
                moodlets = getattr(p, "moodlets", None)
                if moodlets is not None:
                    moodlet_id = f"disaster_{ad.disaster_id}"
                    # Check if moodlet already applied
                    if not any(m.get("id") == moodlet_id for m in moodlets):
                        moodlets.append({
                            "id": moodlet_id,
                            "label": f"Survived {label}",
                            "offset": int(mood_offset),
                            "duration": ddef.get("duration", 15.0) + 30.0,
                            "applied_at": time.time(),
                        })

            # Speed penalty (blizzards, dust storms)
            speed_penalty = effects.get("speed_penalty", 0.0)
            if speed_penalty > 0:
                # Apply as temporary modifier via attribute
                current_speed = getattr(p, "speed", 1.0)
                p._disaster_speed_penalty = speed_penalty * falloff * severity

        # --- Resource bonus (meteor) ---
        resource_bonus = effects.get("resource_bonus", {})
        if resource_bonus and buildings:
            # Deposit bonus resources at nearest storage building
            storage_buildings = [b for b in buildings
                                 if getattr(b, "building_type", "") in ("storage", "workshop")]
            if not storage_buildings:
                storage_buildings = buildings[:1]
            if storage_buildings:
                target = min(storage_buildings,
                             key=lambda b: math.sqrt((b.x - ad.center_x) ** 2 + (b.y - ad.center_y) ** 2))
                stored = getattr(target, "stored_resources", {})
                for rtype, amount in resource_bonus.items():
                    bonus = int(amount * severity)
                    stored[rtype] = stored.get(rtype, 0) + bonus

        # --- Follow-up disease outbreak ---
        follow_up = ddef.get("follow_up", {})
        disease_chance = follow_up.get("chance", 0.0) * severity
        disease_id = follow_up.get("disease_id")
        if disease_id and random.random() < disease_chance and affected_praxans > 0:
            self._trigger_follow_up_disease(
                disease_id, praxans, ad.center_x, ad.center_y, radius,
                event_bus, narrative_panel, label,
            )

        # --- Publish EventBus event ---
        if event_bus is not None:
            try:
                from events.bus import GameEvent, CATEGORY_DISASTER
                event_bus.publish(GameEvent(
                    category=CATEGORY_DISASTER,
                    summary=f"{label} struck! {affected_praxans} praxans affected, {affected_buildings} buildings damaged. (Severity: {severity:.0%})",
                    detail=f"Center: ({ad.center_x:.0f}, {ad.center_y:.0f}), Radius: {radius}",
                    location=(ad.center_x, ad.center_y),
                    metadata={
                        "disaster_id": ad.disaster_id,
                        "severity": round(severity, 2),
                        "affected_praxans": affected_praxans,
                        "affected_buildings": affected_buildings,
                    },
                ))
            except Exception:
                pass

        # --- Narrative panel ---
        if narrative_panel is not None and hasattr(narrative_panel, "add_message"):
            severity_word = "devastating" if severity > 0.7 else "moderate" if severity > 0.4 else "minor"
            narrative_panel.add_message(
                f"A {severity_word} {label} has struck! "
                f"{affected_praxans} praxans caught in the disaster, "
                f"{affected_buildings} structures damaged.",
                "Catastrophe",
            )

        # --- Episodic memory for affected praxans ---
        for p in praxans:
            if not getattr(p, "alive", True):
                continue
            dist = math.sqrt((p.x - ad.center_x) ** 2 + (p.y - ad.center_y) ** 2)
            if dist > radius:
                continue
            memory = getattr(p, "memory", None)
            if memory is not None and hasattr(memory, "add_event"):
                memory.add_event(
                    event_type="disaster",
                    description=f"Survived a {label}",
                    emotional_weight=min(1.0, severity * 0.8),
                )

    # ---- follow-up disease -------------------------------------------------

    def _trigger_follow_up_disease(
        self,
        disease_id: str,
        praxans: list,
        center_x: float,
        center_y: float,
        radius: float,
        event_bus: object | None,
        narrative_panel: object | None,
        disaster_label: str,
    ) -> None:
        """Infect nearby praxans with a follow-up disease after a disaster."""
        try:
            from systems.disease import DiseaseManager as DM, get_disease_def
            dm = DM()
            ddef = get_disease_def(disease_id)
            disease_label = ddef.get("label", disease_id) if ddef else disease_id

            infected = 0
            for p in praxans:
                if not getattr(p, "alive", True):
                    continue
                dist = math.sqrt((p.x - center_x) ** 2 + (p.y - center_y) ** 2)
                if dist > radius:
                    continue
                # 30% chance per praxan in radius
                if random.random() < 0.30:
                    if dm.infect(p, disease_id, event_bus=event_bus, narrative_panel=narrative_panel):
                        infected += 1

            if infected > 0 and narrative_panel and hasattr(narrative_panel, "add_message"):
                narrative_panel.add_message(
                    f"In the aftermath of the {disaster_label}, "
                    f"{infected} praxans contracted {disease_label}.",
                    "Crisis",
                )
        except Exception:
            pass  # Disease system unavailable

    # ---- serialization -----------------------------------------------------

    def serialize(self, current_time: float | None = None) -> dict[str, Any]:
        """Serialize disaster manager state for snapshots."""
        now = current_time or time.time()
        return {
            "active_disasters": [d.to_dict() for d in self.active_disasters],
            "history": list(self.history[-self._max_history:]),
            "last_disaster_elapsed": round(max(0.0, now - self._last_disaster_time), 2),
            "cooldowns": {
                did: round(max(0.0, now - t), 2)
                for did, t in self._cooldowns.items()
            },
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Restore disaster manager state from a snapshot."""
        if not data:
            return

        now = time.time()

        # Restore active disasters
        self.active_disasters = []
        for ad_data in data.get("active_disasters", []):
            try:
                self.active_disasters.append(ActiveDisaster.from_dict(ad_data))
            except Exception:
                pass

        # Restore history
        self.history = list(data.get("history", []))

        # Restore timing
        elapsed = data.get("last_disaster_elapsed", 0.0)
        self._last_disaster_time = now - elapsed

        # Restore cooldowns
        for did, elapsed_cd in data.get("cooldowns", {}).items():
            self._cooldowns[did] = now - elapsed_cd

    # ---- query helpers -----------------------------------------------------

    @property
    def has_active_disaster(self) -> bool:
        return len(self.active_disasters) > 0

    def get_active_labels(self) -> list[str]:
        """Return labels of currently active disasters."""
        labels = []
        for ad in self.active_disasters:
            ddef = get_disaster_def(ad.disaster_id)
            labels.append(ddef.get("label", ad.disaster_id) if ddef else ad.disaster_id)
        return labels

    def recent_history(self, count: int = 5) -> list[dict[str, Any]]:
        """Return the N most recent disaster records."""
        return self.history[-count:]
