"""Personality Evolution System.

Praxan personality traits (curiosity, sociability, diligence) shift gradually
based on life experiences.  Instead of being fixed at birth, personality becomes
a living record of the Praxan's journey.

Triggers come from two sources:
  1. **Entity queue** — ``praxan._pending_personality_shifts`` list, populated by
     entity-level code (social interactions, skill level-ups, building, mental
     breaks, etc.) and drained by the manager on rare-tick.
  2. **EventBus subscription** — CATEGORY_DEATH for grief shifts,
     CATEGORY_CULTURAL_SHIFT for ritual participation.

Shift magnitudes are defined in ``defs/core/personality_shifts.json`` as
``PersonalityShiftDef`` entries.  Life-stage scaling applies (youth = 1.5×,
adult = 1.0×, elder = 0.3×).  A small natural drift toward 0.5 prevents
runaway extremes.  When a trait crosses a major threshold (0.25, 0.50, 0.75)
the manager records an episodic memory and applies a brief moodlet.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("PersonalityEvolution")

# ---------------------------------------------------------------------------
# Module-level def cache
# ---------------------------------------------------------------------------

_shift_def_cache: dict[str, dict] = {}


def _load_defs() -> None:
    """Lazily load PersonalityShiftDef entries from DefDatabase."""
    global _shift_def_cache
    if _shift_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        raw = DefDatabase.get_all("PersonalityShiftDef")
        if isinstance(raw, dict):
            _shift_def_cache = dict(raw)
        elif isinstance(raw, list):
            _shift_def_cache = {d["id"]: d for d in raw if isinstance(d, dict) and "id" in d}
    except Exception as exc:
        logger.warning("Failed to load PersonalityShiftDef: %s", exc)


def clear_cache() -> None:
    """Clear cached defs (for testing)."""
    global _shift_def_cache
    _shift_def_cache = {}


def get_shift_def(shift_id: str) -> dict | None:
    """Return a single PersonalityShiftDef by id, or None."""
    _load_defs()
    return _shift_def_cache.get(shift_id)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EVAL_INTERVAL = 15.0  # Seconds between drift/threshold evaluation
_DRIFT_RATE = 0.002  # Per-eval drift toward 0.5
_THRESHOLDS = (0.25, 0.50, 0.75)  # Milestone thresholds for memory/moodlet
_TRAITS = ("curiosity", "sociability", "diligence")

# Life-stage scaling factors for personality shift magnitude
_STAGE_SCALE: dict[str, float] = {
    "infant": 0.0,   # Infants don't evolve personality
    "youth": 1.5,    # Youth are impressionable
    "adult": 1.0,    # Normal
    "elder": 0.3,    # Elders are set in their ways
}

# Moodlet defs applied on threshold crossings
_THRESHOLD_MOODLETS = {
    "up": {"id": "PersonalityGrowth", "offset": 3, "duration": 120},
    "down": {"id": "PersonalityDecline", "offset": -3, "duration": 120},
}

# Episodic memory event IDs per trait + direction
_MEMORY_EVENTS = {
    ("curiosity", "up"): "personality_curiosity_grew",
    ("curiosity", "down"): "personality_curiosity_faded",
    ("sociability", "up"): "personality_sociability_grew",
    ("sociability", "down"): "personality_sociability_faded",
    ("diligence", "up"): "personality_diligence_grew",
    ("diligence", "down"): "personality_diligence_faded",
}

# Human-readable labels for memory descriptions
_TRAIT_LABELS = {
    "curiosity": "curiosity",
    "sociability": "sociability",
    "diligence": "diligence",
}


# ---------------------------------------------------------------------------
# Interaction → shift mapping  (built from defs at load time)
# ---------------------------------------------------------------------------

_interaction_shift_map: dict[str, list[dict]] = {}


def _build_interaction_map() -> None:
    """Build a lookup from interaction id → list of shift defs."""
    global _interaction_shift_map
    _load_defs()
    _interaction_shift_map.clear()
    for sdef in _shift_def_cache.values():
        trigger = sdef.get("trigger", "")
        if trigger.startswith("interaction:"):
            interaction_id = trigger.split(":", 1)[1]
            _interaction_shift_map.setdefault(interaction_id, []).append(sdef)


def get_interaction_shifts(interaction_id: str) -> list[dict]:
    """Return PersonalityShiftDefs triggered by a social interaction."""
    if not _interaction_shift_map:
        _build_interaction_map()
    return _interaction_shift_map.get(interaction_id, [])


# ---------------------------------------------------------------------------
# Entity-trigger → shift mapping
# ---------------------------------------------------------------------------

_entity_shift_map: dict[str, list[dict]] = {}


def _build_entity_map() -> None:
    """Build a lookup from entity trigger id → list of shift defs."""
    global _entity_shift_map
    _load_defs()
    _entity_shift_map.clear()
    for sdef in _shift_def_cache.values():
        trigger = sdef.get("trigger", "")
        if trigger.startswith("entity:"):
            entity_trigger = trigger.split(":", 1)[1]
            _entity_shift_map.setdefault(entity_trigger, []).append(sdef)


def get_entity_shifts(trigger_id: str) -> list[dict]:
    """Return PersonalityShiftDefs triggered by an entity-level event."""
    if not _entity_shift_map:
        _build_entity_map()
    return _entity_shift_map.get(trigger_id, [])


# ---------------------------------------------------------------------------
# Queue helper — called from social_interactions.py
# ---------------------------------------------------------------------------

def queue_interaction_shifts(
    initiator: Any,
    target: Any,
    interaction_id: str,
) -> None:
    """Queue personality shifts on initiator/target from a social interaction.

    Called by ``execute_interaction`` in social_interactions.py.
    """
    shifts = get_interaction_shifts(interaction_id)
    for sdef in shifts:
        who = sdef.get("target", "both")
        trigger_id = sdef.get("trigger", "")
        shift_item = trigger_id  # e.g. "interaction:deep_conversation"
        if who in ("initiator", "both"):
            pending = getattr(initiator, "_pending_personality_shifts", None)
            if pending is not None:
                pending.append(shift_item)
        if who in ("target", "both"):
            pending = getattr(target, "_pending_personality_shifts", None)
            if pending is not None:
                pending.append(shift_item)


# ---------------------------------------------------------------------------
# PersonalityEvolutionManager
# ---------------------------------------------------------------------------

class PersonalityEvolutionManager:
    """Manages gradual personality evolution for all Praxans."""

    def __init__(self) -> None:
        self._last_eval_time: float = 0.0
        self._event_bus: Any = None
        # Track previous threshold zone per praxan per trait for crossing detection
        # {praxan_id: {trait: zone_index}}  where zone = int(value * 4) clamped 0..3
        self._prev_zones: dict[int, dict[str, int]] = {}

    def attach_event_bus(self, bus: Any) -> None:
        """Subscribe to relevant EventBus categories."""
        self._event_bus = bus
        if bus is None:
            return
        try:
            from events.bus import CATEGORY_DEATH, CATEGORY_CULTURAL_SHIFT
            bus.subscribe(CATEGORY_DEATH, self._on_death)
            bus.subscribe(CATEGORY_CULTURAL_SHIFT, self._on_cultural_shift)
        except Exception as exc:
            logger.warning("EventBus subscription failed: %s", exc)

    # ---- EventBus handlers ------------------------------------------------

    def _on_death(self, event: Any) -> None:
        """Handle death events — apply grief personality shifts to relatives."""
        # GameEvent stores praxan_id as a top-level field; also check metadata
        dead_id = getattr(event, "praxan_id", None)
        if dead_id is None:
            meta = getattr(event, "metadata", {}) or {}
            dead_id = meta.get("praxan_id") or meta.get("id")
        if dead_id is None:
            return
        # Grief shifts are applied via _pending_personality_shifts by the
        # manager's update() method, which checks relationships.
        # Store the dead_id for processing in the next update cycle.
        if not hasattr(self, "_pending_deaths"):
            self._pending_deaths: list[int] = []
        self._pending_deaths.append(dead_id)

    def _on_cultural_shift(self, event: Any) -> None:
        """Handle ritual events — queue sociability shifts on participants."""
        metadata = getattr(event, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            return
        ritual_id = metadata.get("ritual_id")
        if not ritual_id:
            return
        # Store event for processing — participant IDs will be resolved in update()
        if not hasattr(self, "_pending_ritual_faction"):
            self._pending_ritual_faction: list[int] = []
        faction_id = getattr(event, "faction_id", None)
        if faction_id is not None:
            self._pending_ritual_faction.append(faction_id)

    # ---- Main update ------------------------------------------------------

    def update(
        self,
        praxans: list,
        current_time: float | None = None,
    ) -> None:
        """Drain pending personality shifts and apply periodic drift.

        Called on rare-tick cadence (~every 4 seconds).
        """
        now = current_time or time.time()
        _load_defs()
        if not _shift_def_cache:
            return

        alive = {p.id: p for p in praxans if getattr(p, "alive", True)}

        # 1. Process entity-queued shifts on every call
        for praxan in alive.values():
            self._drain_entity_queue(praxan, now)

        # 2. Process death-grief shifts
        self._process_deaths(alive, now)

        # 3. Process ritual participation shifts
        self._process_rituals(alive, now)

        # 4. Periodic drift + threshold detection
        do_eval = (now - self._last_eval_time) >= _EVAL_INTERVAL
        if do_eval:
            self._last_eval_time = now
            for praxan in alive.values():
                self._apply_drift(praxan)
                self._check_thresholds(praxan, now)

    # ---- Internal methods -------------------------------------------------

    def _drain_entity_queue(self, praxan: Any, now: float) -> None:
        """Drain _pending_personality_shifts from a praxan."""
        pending = getattr(praxan, "_pending_personality_shifts", None)
        if not pending:
            return

        stage = getattr(praxan, "life_stage", "adult")
        scale = _STAGE_SCALE.get(stage, 1.0)
        if scale <= 0:
            pending.clear()
            return

        personality = getattr(praxan, "personality", None)
        if not personality:
            pending.clear()
            return

        for trigger in pending:
            # Find matching shift defs
            shift_defs = self._resolve_trigger(trigger)
            for sdef in shift_defs:
                trait = sdef.get("trait", "")
                if trait not in personality:
                    continue
                base_shift = float(sdef.get("shift", 0))
                personality[trait] = _clamp(personality[trait] + base_shift * scale)

        pending.clear()

    def _resolve_trigger(self, trigger: str) -> list[dict]:
        """Resolve a trigger string to its shift defs."""
        _load_defs()
        # Try direct match (e.g. "interaction:deep_conversation")
        if trigger.startswith("interaction:"):
            iid = trigger.split(":", 1)[1]
            return get_interaction_shifts(iid)
        elif trigger.startswith("entity:"):
            eid = trigger.split(":", 1)[1]
            return get_entity_shifts(eid)
        else:
            # Treat as entity trigger ID directly
            return get_entity_shifts(trigger)

    def _process_deaths(self, alive: dict[int, Any], now: float) -> None:
        """Apply grief-related personality shifts for recent deaths."""
        deaths = getattr(self, "_pending_deaths", [])
        if not deaths:
            return

        _load_defs()
        partner_defs = [d for d in _shift_def_cache.values()
                        if d.get("trigger") == "event:partner_death"]
        child_defs = [d for d in _shift_def_cache.values()
                      if d.get("trigger") == "event:child_death"]

        for dead_id in deaths:
            for praxan in alive.values():
                rels = getattr(praxan, "relationships", {})
                stage = getattr(praxan, "life_stage", "adult")
                scale = _STAGE_SCALE.get(stage, 1.0)
                personality = getattr(praxan, "personality", None)
                if not personality or scale <= 0:
                    continue

                rel_type = rels.get(dead_id)
                if rel_type == "partner":
                    for sdef in partner_defs:
                        trait = sdef.get("trait", "")
                        if trait in personality:
                            personality[trait] = _clamp(
                                personality[trait] + float(sdef.get("shift", 0)) * scale
                            )
                elif rel_type == "child":
                    for sdef in child_defs:
                        trait = sdef.get("trait", "")
                        if trait in personality:
                            personality[trait] = _clamp(
                                personality[trait] + float(sdef.get("shift", 0)) * scale
                            )

        deaths.clear()

    def _process_rituals(self, alive: dict[int, Any], now: float) -> None:
        """Apply ritual participation personality shifts."""
        ritual_factions = getattr(self, "_pending_ritual_faction", [])
        if not ritual_factions:
            return

        _load_defs()
        ritual_defs = [d for d in _shift_def_cache.values()
                       if d.get("trigger") == "event:ritual_participation"]

        for faction_id in ritual_factions:
            for praxan in alive.values():
                if getattr(praxan, "faction_id", None) != faction_id:
                    continue
                stage = getattr(praxan, "life_stage", "adult")
                scale = _STAGE_SCALE.get(stage, 1.0)
                personality = getattr(praxan, "personality", None)
                if not personality or scale <= 0:
                    continue
                for sdef in ritual_defs:
                    trait = sdef.get("trait", "")
                    if trait in personality:
                        personality[trait] = _clamp(
                            personality[trait] + float(sdef.get("shift", 0)) * scale
                        )

        ritual_factions.clear()

    def _apply_drift(self, praxan: Any) -> None:
        """Apply natural drift toward 0.5 (equilibrium)."""
        personality = getattr(praxan, "personality", None)
        if not personality:
            return
        stage = getattr(praxan, "life_stage", "adult")
        scale = _STAGE_SCALE.get(stage, 1.0)
        if scale <= 0:
            return

        for trait in _TRAITS:
            if trait not in personality:
                continue
            val = personality[trait]
            if abs(val - 0.5) < _DRIFT_RATE:
                continue  # Close enough — skip
            direction = 1.0 if val < 0.5 else -1.0
            personality[trait] = _clamp(val + direction * _DRIFT_RATE * scale)

    def _check_thresholds(self, praxan: Any, now: float) -> None:
        """Detect threshold crossings and record memories/moodlets."""
        personality = getattr(praxan, "personality", None)
        if not personality:
            return

        pid = praxan.id
        if pid not in self._prev_zones:
            # First time — just record current zones, no crossing
            self._prev_zones[pid] = {
                t: _zone(personality.get(t, 0.5)) for t in _TRAITS
            }
            return

        prev = self._prev_zones[pid]
        for trait in _TRAITS:
            val = personality.get(trait, 0.5)
            new_zone = _zone(val)
            old_zone = prev.get(trait, 2)  # Default to middle zone

            if new_zone != old_zone:
                # Crossed a threshold
                direction = "up" if new_zone > old_zone else "down"
                self._record_threshold_crossing(praxan, trait, direction, val, now)

            prev[trait] = new_zone

    def _record_threshold_crossing(
        self,
        praxan: Any,
        trait: str,
        direction: str,
        value: float,
        now: float,
    ) -> None:
        """Record an episodic memory and apply a moodlet for a threshold crossing."""
        name = getattr(praxan, "name", f"Praxan {praxan.id}")
        label = _TRAIT_LABELS.get(trait, trait)

        # Episodic memory
        memory_key = _MEMORY_EVENTS.get((trait, direction))
        if memory_key and hasattr(praxan, "episodic_memory") and praxan.episodic_memory is not None:
            if direction == "up":
                desc = f"{name}'s {label} grew stronger ({value:.2f})"
            else:
                desc = f"{name}'s {label} faded ({value:.2f})"
            praxan.episodic_memory.record(memory_key, desc, now)

        # Moodlet
        moodlet_info = _THRESHOLD_MOODLETS.get(direction)
        if moodlet_info and hasattr(praxan, "add_moodlet"):
            praxan.add_moodlet(
                moodlet_info["id"],
                moodlet_info["offset"],
                moodlet_info["duration"],
                now,
            )

    # ---- Cleanup ----------------------------------------------------------

    def cleanup_praxan(self, praxan_id: int) -> None:
        """Remove tracking for a dead praxan."""
        self._prev_zones.pop(praxan_id, None)

    # ---- Serialization ----------------------------------------------------

    def serialize(self) -> dict:
        """Serialize manager state for snapshot."""
        return {
            "prev_zones": {str(k): v for k, v in self._prev_zones.items()},
        }

    def restore(self, data: dict, current_time: float | None = None) -> None:
        """Restore manager state from snapshot."""
        now = current_time or time.time()
        self._last_eval_time = now

        prev_raw = data.get("prev_zones", {})
        self._prev_zones = {}
        for k, v in prev_raw.items():
            try:
                pid = int(k)
                if isinstance(v, dict):
                    self._prev_zones[pid] = v
            except (ValueError, TypeError):
                continue

        # Clear any pending event queues
        self._pending_deaths = []
        self._pending_ritual_faction = []


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _zone(value: float) -> int:
    """Map a 0-1 personality value to a zone index (0-3).

    Zone boundaries at 0.25, 0.50, 0.75:
      zone 0: [0.00, 0.25)
      zone 1: [0.25, 0.50)
      zone 2: [0.50, 0.75)
      zone 3: [0.75, 1.00]
    """
    if value < 0.25:
        return 0
    elif value < 0.50:
        return 1
    elif value < 0.75:
        return 2
    else:
        return 3
