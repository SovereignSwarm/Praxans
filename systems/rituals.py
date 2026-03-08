"""Rituals & Gatherings System.

Factions periodically hold rituals at shrines — data-driven ceremonies that
bring members together, reinforce doctrine, boost morale and bonds, and
create episodic memories.  Rituals fire based on periodic timers or reactive
conditions (recent death, season change, food abundance, crisis survival).

Ritual definitions live in ``defs/core/rituals.json`` and are loaded via
``DefDatabase``.

Integration points:
    - ``RitualManager.update()`` called from main loop on rare-tick cadence
    - Uses existing shrine buildings as gathering points
    - Applies moodlets via ``praxan.add_moodlet()``
    - Records episodic memories via ``praxan.episodic_memory.record()``
    - Publishes ``CATEGORY_CULTURAL_SHIFT`` events to EventBus
    - Modifies faction cohesion and doctrine reinforcement
    - Snapshot: ``serialize()`` / ``restore()`` for save/load
"""

from __future__ import annotations

import math
import random
import time
from typing import Any, Optional

from events.bus import CATEGORY_CULTURAL_SHIFT, CATEGORY_DISASTER, GameEvent

# ---------------------------------------------------------------------------
# RitualDef cache (loaded from DefDatabase lazily)
# ---------------------------------------------------------------------------

_ritual_def_cache: dict[str, dict[str, Any]] = {}


def _load_ritual_defs() -> None:
    """Populate cache from DefDatabase."""
    if _ritual_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        defs = DefDatabase.get_all("RitualDef")
        for def_id, def_data in defs.items():
            _ritual_def_cache[def_id] = def_data
    except Exception:
        pass


def get_ritual_def(ritual_id: str) -> Optional[dict[str, Any]]:
    """Return a RitualDef by id, or None."""
    _load_ritual_defs()
    return _ritual_def_cache.get(ritual_id)


def get_all_ritual_defs() -> dict[str, dict[str, Any]]:
    """Return all known RitualDefs."""
    _load_ritual_defs()
    return dict(_ritual_def_cache)


def clear_cache() -> None:
    """Clear the ritual def cache (for tests)."""
    _ritual_def_cache.clear()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RITUAL_EVAL_INTERVAL = 30.0  # seconds between evaluation sweeps
SETTLEMENT_AURA_RADIUS = 120  # must match praxans_game constant
RITUAL_GATHER_RADIUS = 150  # praxans within this range of shrine participate


# ---------------------------------------------------------------------------
# Per-faction ritual state
# ---------------------------------------------------------------------------

class FactionRitualState:
    """Tracks ritual cooldowns and history for one faction."""

    __slots__ = (
        "faction_id", "last_ritual_times", "last_eval_time",
        "active_ritual", "ritual_history", "pending_conditions",
    )

    def __init__(self, faction_id: int):
        self.faction_id = faction_id
        self.last_ritual_times: dict[str, float] = {}  # {ritual_id: last_time}
        self.last_eval_time: float = 0.0
        self.active_ritual: Optional[dict[str, Any]] = None  # currently executing
        self.ritual_history: list[dict[str, Any]] = []  # bounded log
        self.pending_conditions: dict[str, float] = {}  # condition -> timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "faction_id": self.faction_id,
            "last_ritual_times": dict(self.last_ritual_times),
            "last_eval_time": self.last_eval_time,
            "ritual_history": list(self.ritual_history[-8:]),
            "pending_conditions": dict(self.pending_conditions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FactionRitualState":
        state = cls(data.get("faction_id", 0))
        state.last_ritual_times = dict(data.get("last_ritual_times", {}))
        state.last_eval_time = data.get("last_eval_time", 0.0)
        state.ritual_history = list(data.get("ritual_history", []))
        state.pending_conditions = dict(data.get("pending_conditions", {}))
        return state


# ---------------------------------------------------------------------------
# RitualManager
# ---------------------------------------------------------------------------

class RitualManager:
    """Manages faction rituals — evaluation, execution, and effects."""

    def __init__(self):
        self.faction_states: dict[int, FactionRitualState] = {}
        self.last_eval_time: float = -RITUAL_EVAL_INTERVAL  # ensures first call runs
        self.total_rituals_held: int = 0
        # Condition flags set by external systems
        self._recent_deaths: dict[int, float] = {}  # {faction_id: timestamp}
        self._recent_births: dict[int, float] = {}
        self._season_changed: float = 0.0
        self._last_season: str = ""
        self._survived_crisis: dict[int, float] = {}  # {faction_id: timestamp}

    def attach_event_bus(self, event_bus) -> None:
        """Subscribe to EventBus events for automatic condition detection."""
        if event_bus is None:
            return
        event_bus.subscribe(CATEGORY_DISASTER, self._on_disaster_event)

    def _on_disaster_event(self, event: GameEvent) -> None:
        """When a disaster fires, mark all factions as crisis survivors after a delay."""
        # All factions present at disaster time are potential "survivors"
        # The survived_crisis condition checks recency so it triggers rituals later
        for fid in list(self.faction_states.keys()):
            self._survived_crisis[fid] = event.timestamp + 30.0  # delay so they survive first

    # ---- external condition signals ----------------------------------------

    def signal_death(self, faction_id: int, current_time: float) -> None:
        """Called when a faction member dies."""
        self._recent_deaths[faction_id] = current_time

    def signal_birth(self, faction_id: int, current_time: float) -> None:
        """Called when a faction member is born."""
        self._recent_births[faction_id] = current_time

    def signal_season_change(self, season: str, current_time: float) -> None:
        """Called when the season transitions."""
        if season != self._last_season:
            self._last_season = season
            self._season_changed = current_time

    def signal_crisis_survived(self, faction_id: int, current_time: float) -> None:
        """Called when a faction survives a disaster or epidemic."""
        self._survived_crisis[faction_id] = current_time

    # ---- main update -------------------------------------------------------

    def update(
        self,
        faction_manager,
        praxans: list,
        buildings: list,
        current_time: float,
        event_bus=None,
        advisor=None,
        narrative_panel=None,
        particle_system=None,
        season: str = "summer",
    ) -> None:
        """Evaluate and execute rituals for all factions."""
        if current_time - self.last_eval_time < RITUAL_EVAL_INTERVAL:
            return
        self.last_eval_time = current_time

        if faction_manager is None:
            return

        _load_ritual_defs()

        for faction_id, faction in faction_manager.factions.items():
            # Ensure we have state for this faction
            if faction_id not in self.faction_states:
                self.faction_states[faction_id] = FactionRitualState(faction_id)

            state = self.faction_states[faction_id]
            members = faction.get_members(praxans)
            if len(members) < 2:
                continue

            # Find best available ritual
            ritual_def = self._select_ritual(
                faction, state, members, buildings, current_time, season
            )
            if ritual_def is None:
                continue

            # Execute the ritual
            self._execute_ritual(
                ritual_def, faction, state, members, buildings,
                current_time, event_bus, advisor, narrative_panel,
                particle_system, season,
            )

        # Clean up states for dissolved factions
        active_ids = set(faction_manager.factions.keys())
        for fid in list(self.faction_states.keys()):
            if fid not in active_ids:
                del self.faction_states[fid]

    # ---- ritual selection ---------------------------------------------------

    def _select_ritual(
        self,
        faction,
        state: FactionRitualState,
        members: list,
        buildings: list,
        current_time: float,
        season: str,
    ) -> Optional[dict[str, Any]]:
        """Pick the highest-priority available ritual for this faction."""
        candidates = []

        for ritual_id, ritual_def in _ritual_def_cache.items():
            # Check cooldown (None = never fired, always eligible)
            cooldown = ritual_def.get("cooldown_seconds", ritual_def.get("interval_seconds", 120))
            last_time = state.last_ritual_times.get(ritual_id)
            if last_time is not None and current_time - last_time < cooldown:
                continue

            # Check min participants
            min_p = ritual_def.get("min_participants", 2)
            if len(members) < min_p:
                continue

            # Check required building
            req_building = ritual_def.get("required_building")
            if req_building:
                has_building = any(
                    getattr(b, "building_type", "") == req_building
                    for b in buildings
                )
                if not has_building:
                    continue

            # Check trigger conditions
            trigger = ritual_def.get("trigger", "periodic")
            if trigger == "periodic":
                interval = ritual_def.get("interval_seconds", 120)
                if last_time is not None and current_time - last_time < interval:
                    continue
            elif trigger == "condition":
                condition = ritual_def.get("condition", "")
                if not self._check_condition(
                    condition, faction, state, members, current_time, season, ritual_def
                ):
                    continue

            # Score: drama weight + condition urgency
            score = ritual_def.get("drama_weight", 3)
            candidates.append((score, ritual_id, ritual_def))

        if not candidates:
            return None

        # Weighted random selection favoring higher drama
        candidates.sort(key=lambda c: c[0], reverse=True)
        # Top candidate with some randomness
        if len(candidates) == 1:
            return candidates[0][2]
        weights = [c[0] for c in candidates]
        total = sum(weights)
        r = random.random() * total
        cumulative = 0.0
        for score, rid, rdef in candidates:
            cumulative += score
            if r <= cumulative:
                return rdef
        return candidates[0][2]

    def _check_condition(
        self,
        condition: str,
        faction,
        state: FactionRitualState,
        members: list,
        current_time: float,
        season: str,
        ritual_def: dict[str, Any],
    ) -> bool:
        """Check whether a conditional ritual's trigger is satisfied."""
        if condition == "food_security_high":
            threshold = ritual_def.get("condition_threshold", 75.0)
            return getattr(faction, "food_security", 0.0) >= threshold

        elif condition == "recent_death":
            death_time = self._recent_deaths.get(faction.id, 0.0)
            return death_time > 0.0 and current_time - death_time < 60.0

        elif condition == "recent_birth":
            birth_time = self._recent_births.get(faction.id, 0.0)
            return birth_time > 0.0 and current_time - birth_time < 60.0

        elif condition == "season_changed":
            return (
                self._season_changed > 0.0
                and current_time - self._season_changed < 45.0
            )

        elif condition == "survived_crisis":
            crisis_time = self._survived_crisis.get(faction.id, 0.0)
            return crisis_time > 0.0 and current_time - crisis_time < 90.0

        return False

    # ---- ritual execution ---------------------------------------------------

    def _execute_ritual(
        self,
        ritual_def: dict[str, Any],
        faction,
        state: FactionRitualState,
        members: list,
        buildings: list,
        current_time: float,
        event_bus,
        advisor,
        narrative_panel,
        particle_system,
        season: str,
    ) -> None:
        """Execute a ritual: find gathering point, gather participants, apply effects."""
        ritual_id = ritual_def.get("id", "unknown")

        # Find the gathering point (nearest shrine to faction centroid, or centroid)
        gathering_point = self._find_gathering_point(
            ritual_def, faction, members, buildings
        )
        if gathering_point is None:
            return

        # Gather participants (members within radius of gathering point)
        participants = [
            m for m in members
            if _distance(m.x, m.y, gathering_point[0], gathering_point[1])
            <= RITUAL_GATHER_RADIUS
        ]

        min_p = ritual_def.get("min_participants", 2)
        if len(participants) < min_p:
            # Include all members if there aren't enough near the shrine
            # (small factions where everyone should participate)
            if len(members) >= min_p:
                participants = list(members)
            else:
                return

        # Apply effects to participants
        effects = ritual_def.get("effects", {})
        moodlet_id = ritual_def.get("moodlet")
        memory_event = ritual_def.get("memory_event")

        for praxan in participants:
            self._apply_ritual_effects(
                praxan, effects, moodlet_id, memory_event,
                ritual_def, current_time, participants,
            )

        # Faction-level effects
        cohesion_boost = effects.get("cohesion_boost", 0.0)
        if cohesion_boost and hasattr(faction, "cohesion"):
            faction.cohesion = min(100.0, faction.cohesion + cohesion_boost)

        doctrine_reinforcement = effects.get("doctrine_reinforcement", 0.0)
        if doctrine_reinforcement and hasattr(faction, "stability"):
            faction.stability = min(100.0, faction.stability + doctrine_reinforcement * 20)

        # Record in state
        state.last_ritual_times[ritual_id] = current_time
        history_entry = {
            "ritual_id": ritual_id,
            "ritual_name": ritual_def.get("name", ritual_id),
            "time": current_time,
            "participants": len(participants),
            "location": list(gathering_point),
        }
        state.ritual_history.append(history_entry)
        if len(state.ritual_history) > 8:
            del state.ritual_history[:-8]

        self.total_rituals_held += 1

        # Narrative output
        narrative_text = ritual_def.get("narrative_template", "").format(
            faction_id=faction.id,
            participants=len(participants),
            doctrine=getattr(faction, "primary_doctrine", "growth"),
            season=season,
        )
        if narrative_panel and narrative_text:
            narrative_panel.add_message(narrative_text, "Achievement")

        # Particles at gathering point
        if particle_system and gathering_point:
            effect_type = "confetti" if ritual_def.get("category") == "celebration" else "sparkle"
            try:
                particle_system.create_particles(
                    gathering_point[0], gathering_point[1],
                    effect_type, 16,
                )
            except Exception:
                pass

        # EventBus
        if event_bus:
            event_bus.publish(GameEvent(
                category=CATEGORY_CULTURAL_SHIFT,
                summary=f"{ritual_def.get('name', ritual_id)} at Faction {faction.id}",
                detail=narrative_text,
                location=gathering_point,
                faction_id=faction.id,
                metadata={
                    "ritual_id": ritual_id,
                    "participants": len(participants),
                    "category": ritual_def.get("category", "spiritual"),
                },
            ))

        # Advisor stats
        if advisor is not None:
            advisor.session_stats["rituals_held"] = (
                advisor.session_stats.get("rituals_held", 0) + 1
            )
            # Record to observer timeline (direct list append avoids praxans_game import)
            timeline = getattr(advisor, "observer_timeline", None)
            if timeline is not None:
                timeline.append({
                    "time": current_time,
                    "category": "cultural_shift",
                    "summary": f"{ritual_def.get('name', ritual_id)} held by Faction {faction.id}",
                    "detail": f"{len(participants)} participants.",
                })

    def _find_gathering_point(
        self,
        ritual_def: dict[str, Any],
        faction,
        members: list,
        buildings: list,
    ) -> Optional[tuple[float, float]]:
        """Find the best gathering point for a ritual."""
        req_building = ritual_def.get("required_building")

        if req_building:
            # Find nearest required building to faction centroid
            centroid = faction.get_centroid(members)
            if centroid is None and members:
                centroid = (members[0].x, members[0].y)
            elif centroid is None:
                return None

            best_building = None
            best_dist = float("inf")
            for b in buildings:
                if getattr(b, "building_type", "") != req_building:
                    continue
                d = _distance(centroid[0], centroid[1], b.x, b.y)
                if d < best_dist:
                    best_dist = d
                    best_building = b

            if best_building:
                return (best_building.x, best_building.y)
            return None  # Required building not found

        # No required building — use faction centroid
        centroid = faction.get_centroid(members)
        if centroid:
            return centroid
        if members:
            return (members[0].x, members[0].y)
        return None

    def _apply_ritual_effects(
        self,
        praxan,
        effects: dict[str, Any],
        moodlet_id: Optional[str],
        memory_event: Optional[str],
        ritual_def: dict[str, Any],
        current_time: float,
        participants: list,
    ) -> None:
        """Apply ritual effects to a single participant praxan."""
        # Morale
        morale_boost = effects.get("morale_boost", 0)
        if morale_boost:
            praxan.morale = min(100.0, getattr(praxan, "morale", 65.0) + morale_boost)

        # Happiness
        happiness_boost = effects.get("happiness_boost", 0)
        if happiness_boost:
            praxan.happiness = min(100.0, praxan.happiness + happiness_boost)

        # Inspiration
        inspiration_boost = effects.get("inspiration_boost", 0)
        if inspiration_boost:
            praxan.inspiration = min(100.0, getattr(praxan, "inspiration", 0.0) + inspiration_boost)

        # Social need
        social_need = effects.get("social_need", 0)
        if social_need and hasattr(praxan, "needs"):
            praxan.needs["social"] = min(100.0, praxan.needs.get("social", 50.0) + social_need)

        # Hunger restore
        hunger_restore = effects.get("hunger_restore", 0)
        if hunger_restore and hasattr(praxan, "needs"):
            praxan.needs["hunger"] = min(100.0, praxan.needs.get("hunger", 50.0) + hunger_restore)

        # Resilience
        resilience_boost = effects.get("resilience_boost", 0.0)
        if resilience_boost:
            praxan.resilience = min(
                2.0, getattr(praxan, "resilience", 1.0) + resilience_boost
            )

        # Bond changes with other participants
        bond_change = effects.get("bond_change", 0)
        if bond_change:
            for other in participants:
                if other.id != praxan.id:
                    current_bond = praxan.bonds.get(other.id, 50.0)
                    praxan.bonds[other.id] = min(100.0, current_bond + bond_change)

        # Grief relief (reduce grief moodlets)
        grief_relief = effects.get("grief_relief", 0.0)
        if grief_relief and hasattr(praxan, "moodlets"):
            for moodlet in praxan.moodlets:
                if moodlet.get("value", 0) < 0 and "grief" in moodlet.get("name", "").lower():
                    moodlet["value"] = int(moodlet["value"] * (1.0 - grief_relief))

        # Moodlet
        if moodlet_id and hasattr(praxan, "add_moodlet"):
            # Look up mood_offset from MoodDef
            mood_offset = effects.get("morale_boost", 5)
            duration = 300.0
            try:
                from systems.def_database import DefDatabase
                mood_defs = DefDatabase.get_all("MoodDef")
                for mid, mdef in mood_defs.items():
                    if mid == moodlet_id:
                        mood_offset = mdef.get("mood_offset", mood_offset)
                        duration = mdef.get("duration", duration)
                        break
            except Exception:
                pass
            praxan.add_moodlet(moodlet_id, mood_offset, duration, current_time)

        # Episodic memory
        if memory_event and hasattr(praxan, "episodic_memory"):
            ritual_name = ritual_def.get("name", "a ritual")
            participant_ids = [p.id for p in participants if p.id != praxan.id][:3]
            praxan.episodic_memory.record(
                memory_event,
                f"Attended {ritual_name} with {len(participants) - 1} others",
                related_ids=participant_ids,
                timestamp=current_time,
                metadata={"ritual_id": ritual_def.get("id", "unknown")},
            )

    # ---- serialization -----------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        """Serialize ritual manager state for snapshots."""
        return {
            "total_rituals_held": self.total_rituals_held,
            "last_eval_time": self.last_eval_time,
            "faction_states": {
                str(fid): state.to_dict()
                for fid, state in self.faction_states.items()
            },
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Restore ritual manager state from snapshot data."""
        if not data:
            return
        self.total_rituals_held = data.get("total_rituals_held", 0)
        self.last_eval_time = data.get("last_eval_time", 0.0)
        for fid_str, state_data in data.get("faction_states", {}).items():
            try:
                fid = int(fid_str)
                self.faction_states[fid] = FactionRitualState.from_dict(state_data)
            except (ValueError, TypeError):
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
