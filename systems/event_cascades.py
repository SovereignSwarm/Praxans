"""Event Cascade System — cross-system reactive chain reactions.

Subscribes to EventBus events and automatically triggers follow-up effects
across systems, creating emergent behavior chains.  For example, a disaster
can trigger a disease outbreak, mass deaths can trigger collective trauma and
mourning rituals, and warfare outcomes can spiral into deeper hostility.

Cascade definitions live in ``defs/core/cascades.json`` and are loaded via
``DefDatabase``.

Integration points:
    - ``EventCascadeManager.attach_event_bus()`` wires subscriptions
    - Calls into: DiseaseManager, RitualManager, DiplomacyManager, FactionManager
    - Applies moodlets, cohesion changes, migration pressure, memory events
    - Snapshot: ``serialize()`` / ``restore()`` for save/load
    - EventBus: publishes CATEGORY_PERSONAL for cascade-generated effects
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

from events.bus import (
    CATEGORY_BIRTH,
    CATEGORY_DEATH,
    CATEGORY_DISASTER,
    CATEGORY_PERSONAL,
    CATEGORY_WARFARE,
    GameEvent,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CascadeDef cache (loaded from DefDatabase lazily)
# ---------------------------------------------------------------------------

_cascade_def_cache: dict[str, dict[str, Any]] = {}


def _load_cascade_defs() -> None:
    """Populate cache from DefDatabase."""
    if _cascade_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        defs = DefDatabase.get_all("CascadeDef")
        for def_id, def_data in defs.items():
            _cascade_def_cache[def_id] = def_data
    except Exception:
        pass


def get_cascade_def(cascade_id: str) -> Optional[dict[str, Any]]:
    """Return a CascadeDef by id, or None."""
    _load_cascade_defs()
    return _cascade_def_cache.get(cascade_id)


def get_all_cascade_defs() -> dict[str, dict[str, Any]]:
    """Return all known CascadeDefs."""
    _load_cascade_defs()
    return dict(_cascade_def_cache)


def clear_cache() -> None:
    """Clear the cascade def cache (for tests)."""
    _cascade_def_cache.clear()


# ---------------------------------------------------------------------------
# EventCascadeManager
# ---------------------------------------------------------------------------

class EventCascadeManager:
    """Manages cross-system event cascades.

    Subscribes to EventBus categories and evaluates cascade rules
    when relevant events fire.  Tracks state such as recent death
    counts and cooldown timers to decide which cascades trigger.
    """

    def __init__(self) -> None:
        # Recent death tracking for mass_death_trauma cascade
        self._recent_deaths: list[dict[str, Any]] = []  # [{time, faction_id, praxan_id, cause}, ...]
        self._max_recent_deaths = 30  # bounded

        # Cooldowns per cascade_id
        self._cooldowns: dict[str, float] = {}  # cascade_id -> last_fired_time

        # Stats
        self.total_cascades_fired: int = 0
        self.cascade_history: list[dict[str, Any]] = []  # bounded log
        self._max_history = 20

        # Pending effects queue — drained by apply_pending_effects() in main loop
        self._pending_effects: list[dict[str, Any]] = []
        self._max_pending = 50

        # System references (set via set_systems)
        self._disease_manager = None
        self._ritual_manager = None
        self._diplomacy_manager = None
        self._faction_manager = None
        self._event_bus = None

    def set_systems(
        self,
        disease_manager=None,
        ritual_manager=None,
        diplomacy_manager=None,
        faction_manager=None,
    ) -> None:
        """Provide references to other game systems for cascade effects."""
        self._disease_manager = disease_manager
        self._ritual_manager = ritual_manager
        self._diplomacy_manager = diplomacy_manager
        self._faction_manager = faction_manager

    def attach_event_bus(self, event_bus) -> None:
        """Subscribe to EventBus categories that trigger cascades."""
        if event_bus is None:
            return
        self._event_bus = event_bus
        event_bus.subscribe(CATEGORY_DEATH, self._on_death)
        event_bus.subscribe(CATEGORY_DISASTER, self._on_disaster)
        event_bus.subscribe(CATEGORY_WARFARE, self._on_warfare)
        event_bus.subscribe(CATEGORY_BIRTH, self._on_birth)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_death(self, event: GameEvent) -> None:
        """Handle death events — track for mass_death_trauma, trigger combat mourning."""
        now = event.timestamp
        meta = event.metadata or {}
        cause = meta.get("cause", "unknown")

        # Record in recent deaths
        self._recent_deaths.append({
            "time": now,
            "faction_id": event.faction_id,
            "praxan_id": event.praxan_id,
            "cause": cause,
        })
        # Trim old entries
        cutoff = now - 120.0
        self._recent_deaths = [
            d for d in self._recent_deaths if d["time"] > cutoff
        ][-self._max_recent_deaths:]

        _load_cascade_defs()

        # Check mass_death_trauma
        trauma_def = _cascade_def_cache.get("mass_death_trauma")
        if trauma_def:
            self._evaluate_mass_death_trauma(trauma_def, now)

        # Check combat_death_mourning
        mourning_def = _cascade_def_cache.get("combat_death_mourning")
        if mourning_def and cause == "combat":
            self._evaluate_combat_death_mourning(mourning_def, event, now)

    def _on_disaster(self, event: GameEvent) -> None:
        """Handle disaster events — resource stress, epidemic anxiety, survivor resilience."""
        now = event.timestamp
        meta = event.metadata or {}
        event_type = meta.get("type", "disaster")

        _load_cascade_defs()

        if event_type == "epidemic":
            # Epidemic anxiety cascade
            anxiety_def = _cascade_def_cache.get("epidemic_anxiety")
            if anxiety_def:
                self._evaluate_epidemic_anxiety(anxiety_def, event, now)
        else:
            # Post-disaster resource stress
            stress_def = _cascade_def_cache.get("disaster_resource_stress")
            if stress_def:
                self._evaluate_disaster_resource_stress(stress_def, event, now)

            # Survivor resilience
            resilience_def = _cascade_def_cache.get("crisis_resilience")
            if resilience_def:
                self._evaluate_crisis_resilience(resilience_def, event, now)

            # Ecology-driven famine warning (disaster type from ecology system)
            if event_type == "ecology_degradation":
                famine_def = _cascade_def_cache.get("ecology_famine_warning")
                if famine_def:
                    self._evaluate_famine_warning(famine_def, event, now)

    def _on_warfare(self, event: GameEvent) -> None:
        """Handle warfare events — diplomacy spiral."""
        now = event.timestamp
        _load_cascade_defs()

        escalation_def = _cascade_def_cache.get("warfare_escalation")
        if escalation_def:
            self._evaluate_warfare_escalation(escalation_def, event, now)

    def _on_birth(self, event: GameEvent) -> None:
        """Handle birth events — communal joy."""
        now = event.timestamp
        _load_cascade_defs()

        joy_def = _cascade_def_cache.get("birth_celebration")
        if joy_def:
            self._evaluate_birth_celebration(joy_def, event, now)

    # ------------------------------------------------------------------
    # Cascade evaluators
    # ------------------------------------------------------------------

    def _check_cooldown(self, cascade_id: str, cooldown_seconds: float, now: float) -> bool:
        """Return True if the cascade is off cooldown and can fire."""
        last = self._cooldowns.get(cascade_id, 0.0)
        return now - last >= cooldown_seconds

    def _fire_cascade(self, cascade_id: str, now: float, detail: str = "") -> None:
        """Mark a cascade as fired: update cooldown, stats, history."""
        self._cooldowns[cascade_id] = now
        self.total_cascades_fired += 1
        cdef = _cascade_def_cache.get(cascade_id, {})
        record = {
            "cascade_id": cascade_id,
            "label": cdef.get("label", cascade_id),
            "time": now,
            "detail": detail,
        }
        self.cascade_history.append(record)
        if len(self.cascade_history) > self._max_history:
            self.cascade_history = self.cascade_history[-self._max_history:]

    def _queue_effect(self, effect: dict[str, Any]) -> None:
        """Queue a pending effect for the main loop to apply to praxans."""
        self._pending_effects.append(effect)
        if len(self._pending_effects) > self._max_pending:
            self._pending_effects = self._pending_effects[-self._max_pending:]

    def apply_pending_effects(self, praxans: list, now: float) -> int:
        """Drain pending cascade effects and apply to alive praxans.

        Called from the main loop on rare-tick cadence.
        Returns the number of effects applied.
        """
        if not self._pending_effects:
            return 0

        effects = list(self._pending_effects)
        self._pending_effects.clear()
        applied = 0

        for effect in effects:
            scope = effect.get("scope", "all")  # "all", "faction", "survivors"
            faction_id = effect.get("faction_id")
            survivor_ids = effect.get("survivor_ids")

            moodlet_id = effect.get("moodlet_id")
            mood_offset = effect.get("mood_offset")
            duration = effect.get("duration")
            memory_event = effect.get("memory_event")
            memory_text = effect.get("memory_text")
            resilience_boost = effect.get("resilience_boost")
            morale_penalty = effect.get("morale_penalty")
            bond_boost = effect.get("bond_boost")
            cascade_type = effect.get("cascade_type", "")

            for praxan in praxans:
                if not getattr(praxan, "alive", True):
                    continue

                # Scope filtering
                if scope == "faction" and faction_id is not None:
                    if getattr(praxan, "faction_id", None) != faction_id:
                        continue
                elif scope == "survivors" and survivor_ids is not None:
                    if praxan.id not in survivor_ids:
                        continue

                # Apply moodlet
                if moodlet_id and mood_offset is not None and duration:
                    add_moodlet = getattr(praxan, "add_moodlet", None)
                    if add_moodlet:
                        add_moodlet(moodlet_id, mood_offset, duration, now)

                # Apply episodic memory
                if memory_event and memory_text:
                    mem = getattr(praxan, "episodic_memory", None)
                    if mem and hasattr(mem, "record"):
                        mem.record(
                            memory_event, memory_text,
                            timestamp=now,
                            metadata={"cascade_type": cascade_type},
                        )

                # Apply resilience boost
                if resilience_boost:
                    praxan.resilience = min(
                        2.0, getattr(praxan, "resilience", 1.0) + resilience_boost
                    )

                # Apply morale penalty
                if morale_penalty:
                    praxan.morale = max(
                        0.0, getattr(praxan, "morale", 65.0) - morale_penalty
                    )

                # Apply bond boost with other faction members
                if bond_boost and faction_id is not None:
                    if getattr(praxan, "faction_id", None) == faction_id:
                        for other in praxans:
                            if other.id != praxan.id and getattr(other, "alive", True):
                                if getattr(other, "faction_id", None) == faction_id:
                                    bonds = getattr(praxan, "bonds", {})
                                    bonds[other.id] = min(100.0, bonds.get(other.id, 50.0) + bond_boost)

                applied += 1

        return applied

    def _evaluate_mass_death_trauma(
        self, cdef: dict[str, Any], now: float,
    ) -> None:
        """If enough deaths within the window, apply collective trauma to all alive praxans."""
        params = cdef.get("parameters", {})
        threshold = params.get("death_threshold", 3)
        window = params.get("window_seconds", 60.0)
        cooldown = cdef.get("cooldown_seconds", 120.0)
        probability = cdef.get("probability", 1.0)

        if not self._check_cooldown("mass_death_trauma", cooldown, now):
            return

        # Count recent deaths within window
        recent = [d for d in self._recent_deaths if now - d["time"] <= window]
        if len(recent) < threshold:
            return

        if random.random() > probability:
            return

        self._fire_cascade("mass_death_trauma", now,
                           f"{len(recent)} deaths in {window}s")

        # Determine affected factions
        affected_factions = set(d.get("faction_id") for d in recent if d.get("faction_id") is not None)

        # Apply collective trauma moodlet + memory to alive praxans
        moodlet_id = params.get("moodlet_id", "CollectiveTrauma")
        mood_offset = params.get("mood_offset", -12)
        duration = params.get("duration", 360)
        memory_event = params.get("memory_event", "collective_trauma")
        memory_text = params.get("memory_text", "A wave of death shook the colony")

        if self._faction_manager:
            for faction_id in affected_factions:
                faction = self._faction_manager.factions.get(faction_id)
                if not faction:
                    continue
                # Cohesion penalty
                cohesion_penalty = params.get("cohesion_penalty", 5.0)
                if hasattr(faction, "cohesion"):
                    faction.cohesion = max(0.0, faction.cohesion - cohesion_penalty)

                # Signal mourning ritual
                if params.get("signal_mourning") and self._ritual_manager:
                    self._ritual_manager.signal_death(faction_id, now)

        # Queue moodlet/memory effect for affected factions
        for fid in affected_factions:
            self._queue_effect({
                "scope": "faction",
                "faction_id": fid,
                "cascade_type": "mass_death_trauma",
                "moodlet_id": moodlet_id,
                "mood_offset": mood_offset,
                "duration": duration,
                "memory_event": memory_event,
                "memory_text": memory_text,
            })

        # Publish cascade event for narrative/historian
        if self._event_bus:
            self._event_bus.publish(GameEvent(
                category=CATEGORY_PERSONAL,
                summary=f"Collective trauma: {len(recent)} deaths in rapid succession",
                metadata={
                    "type": "cascade_mass_death_trauma",
                    "death_count": len(recent),
                    "affected_factions": list(affected_factions),
                },
            ))

    def _evaluate_combat_death_mourning(
        self, cdef: dict[str, Any], event: GameEvent, now: float,
    ) -> None:
        """When a praxan dies in combat, signal mourning and apply grief moodlet to faction."""
        params = cdef.get("parameters", {})
        cooldown = cdef.get("cooldown_seconds", 30.0)
        probability = cdef.get("probability", 1.0)

        if not self._check_cooldown("combat_death_mourning", cooldown, now):
            return
        if random.random() > probability:
            return

        faction_id = event.faction_id
        if faction_id is None:
            return

        self._fire_cascade("combat_death_mourning", now,
                           f"Combat death in faction {faction_id}")

        # Signal mourning ritual
        if params.get("signal_mourning") and self._ritual_manager:
            self._ritual_manager.signal_death(faction_id, now)

        # Queue faction-scoped moodlet/memory
        moodlet_id = params.get("moodlet_id", "FallenInBattle")
        mood_offset = params.get("mood_offset", -8)
        duration = params.get("duration", 300)
        memory_event = params.get("memory_event", "comrade_fallen_battle")
        memory_text = params.get("memory_text", "A comrade fell in battle")

        self._queue_effect({
            "scope": "faction",
            "faction_id": faction_id,
            "cascade_type": "combat_death_mourning",
            "moodlet_id": moodlet_id,
            "mood_offset": mood_offset,
            "duration": duration,
            "memory_event": memory_event,
            "memory_text": memory_text,
        })

        if self._event_bus:
            self._event_bus.publish(GameEvent(
                category=CATEGORY_PERSONAL,
                summary=f"Faction {faction_id} mourns a fallen warrior",
                faction_id=faction_id,
                metadata={"type": "cascade_combat_death_mourning"},
            ))

    def _evaluate_epidemic_anxiety(
        self, cdef: dict[str, Any], event: GameEvent, now: float,
    ) -> None:
        """When an epidemic is declared, apply anxiety to all factions."""
        params = cdef.get("parameters", {})
        cooldown = cdef.get("cooldown_seconds", 90.0)
        probability = cdef.get("probability", 1.0)

        if not self._check_cooldown("epidemic_anxiety", cooldown, now):
            return
        if random.random() > probability:
            return

        self._fire_cascade("epidemic_anxiety", now,
                           f"Epidemic: {event.summary}")

        moodlet_id = params.get("moodlet_id", "EpidemicFear")
        mood_offset = params.get("mood_offset", -10)
        duration = params.get("duration", 240)
        cohesion_penalty = params.get("cohesion_penalty", 8.0)
        morale_penalty = params.get("morale_penalty", 10.0)
        memory_event = params.get("memory_event", "epidemic_fear")
        memory_text = params.get("memory_text", "A plague spread through the colony")

        # Apply faction cohesion drop
        if self._faction_manager:
            for faction_id, faction in self._faction_manager.factions.items():
                if hasattr(faction, "cohesion"):
                    faction.cohesion = max(0.0, faction.cohesion - cohesion_penalty)

        # Queue moodlet/memory for all praxans
        self._queue_effect({
            "scope": "all",
            "cascade_type": "epidemic_anxiety",
            "moodlet_id": moodlet_id,
            "mood_offset": mood_offset,
            "duration": duration,
            "morale_penalty": morale_penalty,
            "memory_event": memory_event,
            "memory_text": memory_text,
        })

        if self._event_bus:
            self._event_bus.publish(GameEvent(
                category=CATEGORY_PERSONAL,
                summary="Epidemic anxiety grips the colony",
                metadata={"type": "cascade_epidemic_anxiety"},
            ))

    def _evaluate_disaster_resource_stress(
        self, cdef: dict[str, Any], event: GameEvent, now: float,
    ) -> None:
        """After disaster damages buildings, spike resource stress on affected factions."""
        params = cdef.get("parameters", {})
        cooldown = cdef.get("cooldown_seconds", 60.0)
        probability = cdef.get("probability", 0.8)

        if not self._check_cooldown("disaster_resource_stress", cooldown, now):
            return
        if random.random() > probability:
            return

        meta = event.metadata or {}
        affected_buildings = meta.get("affected_buildings", 0)
        min_buildings = params.get("min_affected_buildings", 1)
        if affected_buildings < min_buildings:
            return

        self._fire_cascade("disaster_resource_stress", now,
                           f"Disaster damaged {affected_buildings} buildings")

        stress_increase = params.get("stress_increase", 25.0)

        # Apply resource stress to all factions
        if self._faction_manager:
            for faction_id, faction in self._faction_manager.factions.items():
                if hasattr(faction, "resource_stress"):
                    faction.resource_stress = min(
                        100.0, faction.resource_stress + stress_increase
                    )

        # Queue moodlet/memory for all praxans
        moodlet_id = params.get("moodlet_id", "PostDisasterScarcity")
        mood_offset = params.get("mood_offset", -6)
        duration = params.get("duration", 180)
        memory_event = params.get("memory_event", "resource_scarcity")
        memory_text = params.get("memory_text", "Resources grew scarce after a disaster")

        self._queue_effect({
            "scope": "all",
            "cascade_type": "disaster_resource_stress",
            "moodlet_id": moodlet_id,
            "mood_offset": mood_offset,
            "duration": duration,
            "memory_event": memory_event,
            "memory_text": memory_text,
        })

        if self._event_bus:
            self._event_bus.publish(GameEvent(
                category=CATEGORY_PERSONAL,
                summary=f"Post-disaster scarcity: {affected_buildings} buildings damaged",
                metadata={"type": "cascade_disaster_resource_stress"},
            ))

    def _evaluate_crisis_resilience(
        self, cdef: dict[str, Any], event: GameEvent, now: float,
    ) -> None:
        """Survivors of severe disasters gain resilience."""
        params = cdef.get("parameters", {})
        cooldown = cdef.get("cooldown_seconds", 90.0)
        probability = cdef.get("probability", 0.6)

        if not self._check_cooldown("crisis_resilience", cooldown, now):
            return

        meta = event.metadata or {}
        severity = meta.get("severity", 0.0)
        min_severity = params.get("min_severity", 0.5)
        if severity < min_severity:
            return

        if random.random() > probability:
            return

        self._fire_cascade("crisis_resilience", now,
                           f"Survivors hardened by disaster (severity {severity:.0%})")

        # Signal crisis survived for rituals
        survivors = meta.get("survivors", [])
        if self._ritual_manager and self._faction_manager:
            for fid in self._faction_manager.factions:
                self._ritual_manager.signal_crisis_survived(fid, now)

        # Queue resilience + moodlet for disaster survivors only
        moodlet_id = params.get("moodlet_id", "HardenedByCrisis")
        mood_offset = params.get("mood_offset", 4)
        duration = params.get("duration", 600)
        resilience_boost = params.get("resilience_boost", 0.15)
        memory_event = params.get("memory_event", "survived_crisis")
        memory_text = params.get("memory_text", "Survived a devastating crisis and grew stronger")

        self._queue_effect({
            "scope": "survivors" if survivors else "all",
            "survivor_ids": survivors if survivors else None,
            "cascade_type": "crisis_resilience",
            "moodlet_id": moodlet_id,
            "mood_offset": mood_offset,
            "duration": duration,
            "resilience_boost": resilience_boost,
            "memory_event": memory_event,
            "memory_text": memory_text,
        })

        if self._event_bus:
            self._event_bus.publish(GameEvent(
                category=CATEGORY_PERSONAL,
                summary="Survivors hardened by crisis",
                metadata={"type": "cascade_crisis_resilience"},
            ))

    def _evaluate_famine_warning(
        self, cdef: dict[str, Any], event: GameEvent, now: float,
    ) -> None:
        """Ecology fertility crash triggers famine anxiety and migration pressure."""
        params = cdef.get("parameters", {})
        cooldown = cdef.get("cooldown_seconds", 120.0)
        probability = cdef.get("probability", 0.7)

        if not self._check_cooldown("ecology_famine_warning", cooldown, now):
            return
        if random.random() > probability:
            return

        self._fire_cascade("ecology_famine_warning", now,
                           f"Ecology degradation famine warning")

        migration_boost = params.get("migration_pressure_boost", 15.0)

        # Increase migration pressure on all factions
        if self._faction_manager:
            for faction_id, faction in self._faction_manager.factions.items():
                if hasattr(faction, "migration_pressure"):
                    faction.migration_pressure = min(
                        100.0, getattr(faction, "migration_pressure", 0.0) + migration_boost
                    )

        moodlet_id = params.get("moodlet_id", "FamineWarning")
        mood_offset = params.get("mood_offset", -8)
        duration = params.get("duration", 300)
        memory_event = params.get("memory_event", "famine_warning")
        memory_text = params.get("memory_text", "The land grew barren and food became scarce")

        self._queue_effect({
            "scope": "all",
            "cascade_type": "famine_warning",
            "moodlet_id": moodlet_id,
            "mood_offset": mood_offset,
            "duration": duration,
            "memory_event": memory_event,
            "memory_text": memory_text,
        })

        if self._event_bus:
            self._event_bus.publish(GameEvent(
                category=CATEGORY_PERSONAL,
                summary="Famine warning: the land grows barren",
                metadata={"type": "cascade_famine_warning"},
            ))

    def _evaluate_warfare_escalation(
        self, cdef: dict[str, Any], event: GameEvent, now: float,
    ) -> None:
        """After a raid, shift diplomacy further to create a spiral of violence."""
        params = cdef.get("parameters", {})
        cooldown = cdef.get("cooldown_seconds", 60.0)
        probability = cdef.get("probability", 0.7)

        if not self._check_cooldown("warfare_escalation", cooldown, now):
            return
        if random.random() > probability:
            return

        meta = event.metadata or {}
        attacker_fid = meta.get("attacker_faction_id")
        defender_fid = meta.get("defender_faction_id")
        outcome = meta.get("outcome", "")

        if attacker_fid is None or defender_fid is None:
            return

        self._fire_cascade("warfare_escalation", now,
                           f"Warfare escalation: faction {attacker_fid} vs {defender_fid}")

        # Apply diplomacy standing shifts
        standing_loser = params.get("standing_shift_loser", -5)
        standing_winner = params.get("standing_shift_winner", -3)

        if self._diplomacy_manager:
            # Both sides lose standing with each other (war is costly)
            try:
                self._diplomacy_manager.modify_standing(
                    attacker_fid, defender_fid, standing_winner
                )
                self._diplomacy_manager.modify_standing(
                    defender_fid, attacker_fid, standing_loser
                )
            except Exception:
                pass

        # Queue moodlets for both factions
        moodlet_loser = params.get("moodlet_loser", "DesireForRevenge")
        mood_offset_loser = params.get("mood_offset_loser", -6)
        moodlet_winner = params.get("moodlet_winner", "WarWeariness")
        mood_offset_winner = params.get("mood_offset_winner", -3)
        duration = params.get("duration", 300)
        memory_event = params.get("memory_event", "warfare_escalation")
        memory_text = params.get("memory_text", "The cycle of violence between factions deepened")

        # Defender (loser) gets revenge desire
        self._queue_effect({
            "scope": "faction",
            "faction_id": defender_fid,
            "cascade_type": "warfare_escalation",
            "moodlet_id": moodlet_loser,
            "mood_offset": mood_offset_loser,
            "duration": duration,
            "memory_event": memory_event,
            "memory_text": memory_text,
        })
        # Attacker (winner) gets war weariness
        self._queue_effect({
            "scope": "faction",
            "faction_id": attacker_fid,
            "cascade_type": "warfare_escalation",
            "moodlet_id": moodlet_winner,
            "mood_offset": mood_offset_winner,
            "duration": duration,
            "memory_event": memory_event,
            "memory_text": memory_text,
        })

        if self._event_bus:
            self._event_bus.publish(GameEvent(
                category=CATEGORY_PERSONAL,
                summary=f"Cycle of violence deepens between factions {attacker_fid} and {defender_fid}",
                metadata={"type": "cascade_warfare_escalation"},
            ))

    def _evaluate_birth_celebration(
        self, cdef: dict[str, Any], event: GameEvent, now: float,
    ) -> None:
        """Birth triggers communal joy in the faction."""
        params = cdef.get("parameters", {})
        cooldown = cdef.get("cooldown_seconds", 45.0)
        probability = cdef.get("probability", 0.8)

        if not self._check_cooldown("birth_celebration", cooldown, now):
            return
        if random.random() > probability:
            return

        faction_id = event.faction_id
        self._fire_cascade("birth_celebration", now,
                           f"New birth in faction {faction_id}")

        # Signal birth for naming day ritual
        if params.get("signal_birth") and self._ritual_manager and faction_id is not None:
            self._ritual_manager.signal_birth(faction_id, now)

        moodlet_id = params.get("moodlet_id", "NewLifeJoy")
        mood_offset = params.get("mood_offset", 4)
        duration = params.get("duration", 180)
        bond_boost = params.get("bond_boost", 2.0)
        memory_event = params.get("memory_event", "new_birth_joy")
        memory_text = params.get("memory_text", "A new life brought joy to the community")

        self._queue_effect({
            "scope": "faction",
            "faction_id": faction_id,
            "cascade_type": "birth_celebration",
            "moodlet_id": moodlet_id,
            "mood_offset": mood_offset,
            "duration": duration,
            "bond_boost": bond_boost,
            "memory_event": memory_event,
            "memory_text": memory_text,
        })

        if self._event_bus:
            self._event_bus.publish(GameEvent(
                category=CATEGORY_PERSONAL,
                summary=f"New life brings joy to faction {faction_id}",
                faction_id=faction_id,
                metadata={"type": "cascade_birth_celebration"},
            ))

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        """Serialize cascade manager state for snapshots."""
        now = time.time()
        return {
            "total_cascades_fired": self.total_cascades_fired,
            "cascade_history": list(self.cascade_history[-self._max_history:]),
            "cooldowns": {
                cid: round(max(0.0, now - t), 2)
                for cid, t in self._cooldowns.items()
            },
            "recent_deaths": [
                {
                    "elapsed": round(max(0.0, now - d["time"]), 2),
                    "faction_id": d.get("faction_id"),
                    "praxan_id": d.get("praxan_id"),
                    "cause": d.get("cause", "unknown"),
                }
                for d in self._recent_deaths
                if now - d["time"] < 120.0
            ],
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Restore cascade manager state from snapshot data."""
        if not data or not isinstance(data, dict):
            return

        now = time.time()
        self.total_cascades_fired = data.get("total_cascades_fired", 0)
        self.cascade_history = list(data.get("cascade_history", []))

        # Restore cooldowns
        cooldowns = data.get("cooldowns", {})
        if isinstance(cooldowns, dict):
            for cid, elapsed in cooldowns.items():
                try:
                    self._cooldowns[str(cid)] = now - float(elapsed)
                except (TypeError, ValueError):
                    pass

        # Restore recent deaths
        recent = data.get("recent_deaths", [])
        if isinstance(recent, list):
            self._recent_deaths = []
            for entry in recent:
                if not isinstance(entry, dict):
                    continue
                try:
                    elapsed = float(entry.get("elapsed", 0.0))
                    self._recent_deaths.append({
                        "time": now - elapsed,
                        "faction_id": entry.get("faction_id"),
                        "praxan_id": entry.get("praxan_id"),
                        "cause": entry.get("cause", "unknown"),
                    })
                except (TypeError, ValueError):
                    pass

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def recent_cascades(self, count: int = 5) -> list[dict[str, Any]]:
        """Return the N most recent cascade records."""
        return self.cascade_history[-count:]

    @property
    def recent_death_count(self) -> int:
        """Number of deaths tracked in the rolling window."""
        return len(self._recent_deaths)
