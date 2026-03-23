"""Cultural Heritage & Traditions System.

Factions organically develop **traditions** based on significant events in
their history.  A tradition forms when a faction accumulates enough qualifying
events within a time window (e.g., 3 wars in 5 minutes → Warrior Spirit).
Once formed, traditions provide passive bonuses, shape behaviour, and create
unique cultural identities.

Key mechanics:

- **Formation**: qualifying EventBus events accumulate per-faction; when a
  threshold is crossed the tradition forms at its initial strength.
- **Reinforcement**: new matching events strengthen the tradition (capped at
  100).
- **Decay**: traditions lose strength over time when unreinforced — and are
  removed when they fall below 5.
- **Max traditions**: each faction can hold at most 5 active traditions.  When
  a new one would push past the limit the weakest is dropped.
- **Conflict**: certain traditions conflict (e.g. Warrior Spirit vs
  Peacekeeper's Way).  Shared conflicting traditions between factions increase
  diplomatic tension.
- **Cultural exchange**: allied / friendly factions can spread traditions to
  each other.
- **Effects**: applied as modifiers to praxan behaviour (skill XP rates, mood
  bonuses, combat bonuses, gathering efficiency, etc.).

Definitions live in ``defs/core/traditions.json`` (TraditionDef) and are
loaded via ``DefDatabase``.

Integration:
    - ``TraditionManager.update()`` called on rare-tick cadence
    - ``TraditionManager.record_event()`` called by other systems when
      tradition-relevant events occur
    - ``attach_event_bus()`` auto-subscribes to relevant EventBus categories
    - Snapshot: ``serialize()`` / ``restore()``
    - EventBus: publishes CATEGORY_CULTURAL_SHIFT on formation/loss
    - Diplomacy: conflicting/shared traditions modify standing drift
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

from events.bus import (
    CATEGORY_BIRTH,
    CATEGORY_BUILDING,
    CATEGORY_CULTURAL_SHIFT,
    CATEGORY_DEATH,
    CATEGORY_DIPLOMACY,
    CATEGORY_DISASTER,
    CATEGORY_MILESTONE,
    CATEGORY_PERSONAL,
    CATEGORY_TRADE,
    CATEGORY_WARFARE,
    GameEvent,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Def cache (lazily loaded from DefDatabase)
# ---------------------------------------------------------------------------

_tradition_def_cache: dict[str, dict[str, Any]] = {}


def _load_defs() -> None:
    """Populate cache from DefDatabase."""
    global _tradition_def_cache
    if _tradition_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        defs = DefDatabase.get_all("TraditionDef")
        if defs:
            for def_id, def_data in defs.items():
                _tradition_def_cache[def_id] = def_data
    except Exception:
        pass


def get_tradition_def(tradition_id: str) -> Optional[dict[str, Any]]:
    """Return a TraditionDef by id, or None."""
    _load_defs()
    return _tradition_def_cache.get(tradition_id)


def get_all_tradition_defs() -> dict[str, dict[str, Any]]:
    """Return all known TraditionDefs."""
    _load_defs()
    return dict(_tradition_def_cache)


def clear_cache() -> None:
    """Clear the tradition def cache (for tests)."""
    _tradition_def_cache.clear()


# ---------------------------------------------------------------------------
# FactionTradition — runtime instance of a tradition held by a faction
# ---------------------------------------------------------------------------

class FactionTradition:
    """A living tradition held by a specific faction."""

    __slots__ = (
        "tradition_id", "strength", "formed_at", "last_reinforced",
        "last_decay_time",
    )

    def __init__(
        self,
        tradition_id: str,
        strength: float,
        formed_at: float,
        last_reinforced: float | None = None,
        last_decay_time: float | None = None,
    ) -> None:
        self.tradition_id = tradition_id
        self.strength = strength
        self.formed_at = formed_at
        self.last_reinforced = last_reinforced or formed_at
        self.last_decay_time = last_decay_time or formed_at

    def to_dict(self, current_time: float) -> dict[str, Any]:
        """Serialize using elapsed-duration pattern."""
        return {
            "tradition_id": self.tradition_id,
            "strength": round(self.strength, 2),
            "age_seconds": round(max(0.0, current_time - self.formed_at), 2),
            "since_reinforced_seconds": round(
                max(0.0, current_time - self.last_reinforced), 2
            ),
            "since_decay_seconds": round(
                max(0.0, current_time - self.last_decay_time), 2
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], current_time: float) -> "FactionTradition":
        """Restore from snapshot dict."""
        age = float(data.get("age_seconds", 0.0))
        since_reinforced = float(data.get("since_reinforced_seconds", 0.0))
        since_decay = float(data.get("since_decay_seconds", 0.0))
        return cls(
            tradition_id=data["tradition_id"],
            strength=float(data.get("strength", 30.0)),
            formed_at=current_time - age,
            last_reinforced=current_time - since_reinforced,
            last_decay_time=current_time - since_decay,
        )


# ---------------------------------------------------------------------------
# TraditionManager
# ---------------------------------------------------------------------------

# Mapping from EventBus event signals to tradition trigger / reinforcement keys
_EVENT_SIGNAL_MAP: dict[str, list[str]] = {
    # Death events
    "death": ["death"],
    "combat_death": ["combat_death"],
    "mass_death_trauma": ["mass_death_trauma"],
    # Warfare events
    "warfare": ["warfare"],
    "raid_completed": ["warfare"],
    # Disaster events
    "disaster": ["disaster"],
    "epidemic": ["epidemic_survived"],
    "epidemic_ended": ["epidemic_survived"],
    "crisis_survived": ["survived_crisis", "crisis_resilience"],
    # Building events
    "building_completed": ["building_completed", "built_structure"],
    # Milestone events
    "tech_unlocked": ["tech_unlocked"],
    # Trade / diplomacy
    "trade_completed": ["trade_completed"],
    "treaty_signed": ["treaty_signed"],
    "cultural_exchange": ["cultural_exchange"],
    # Personal
    "crafted_masterwork": ["crafted_masterwork", "craft_completed"],
    "healed_other": ["healed_other", "disease_recovery"],
    "teaching": ["teaching"],
    # Ritual-based
    "ritual_harvest_thanksgiving": ["harvest_thanksgiving"],
    "ritual_mourning_ceremony": ["mourning_ceremony"],
    "ritual_victory_celebration": ["survived_crisis"],
    # Birth
    "birth": [],
    # Food surplus (from settlement state)
    "food_surplus": ["food_surplus"],
    # Exploration
    "resource_discovered": ["resource_discovered"],
    "exploration_milestone": ["exploration_milestone"],
}

MAX_TRADITIONS_PER_FACTION = 5
UPDATE_INTERVAL = 30.0  # seconds between full evaluations
CULTURAL_EXCHANGE_INTERVAL = 120.0  # seconds between spread attempts
MIN_STRENGTH_ALIVE = 5.0  # traditions below this are removed
EXCHANGE_STANDING_THRESHOLD = 20  # Friendly+ required for cultural exchange
EXCHANGE_CHANCE = 0.15  # probability of spreading per eligible pair per eval


class TraditionManager:
    """Manages per-faction cultural traditions.

    Call ``record_event(faction_id, event_key)`` whenever a tradition-relevant
    event occurs.  The manager accumulates events and evaluates formation /
    reinforcement / decay on its own cadence.
    """

    def __init__(self) -> None:
        # faction_id -> list[FactionTradition]
        self._traditions: dict[int, list[FactionTradition]] = {}

        # faction_id -> {event_key: [timestamps]}  (rolling window)
        self._event_log: dict[int, dict[str, list[float]]] = {}

        self._last_update: float = 0.0
        self._last_exchange: float = 0.0

        # Stats
        self.total_traditions_formed: int = 0
        self.total_traditions_lost: int = 0
        self.tradition_history: list[dict[str, Any]] = []
        self._max_history = 30

        # System references
        self._event_bus = None
        self._diplomacy_manager = None

    # ------------------------------------------------------------------
    # System wiring
    # ------------------------------------------------------------------

    def set_systems(self, diplomacy_manager=None) -> None:
        """Provide references to other game systems."""
        self._diplomacy_manager = diplomacy_manager

    def attach_event_bus(self, event_bus) -> None:
        """Subscribe to EventBus categories that feed tradition events."""
        if event_bus is None:
            return
        self._event_bus = event_bus
        event_bus.subscribe(CATEGORY_DEATH, self._on_death)
        event_bus.subscribe(CATEGORY_WARFARE, self._on_warfare)
        event_bus.subscribe(CATEGORY_DISASTER, self._on_disaster)
        event_bus.subscribe(CATEGORY_BUILDING, self._on_building)
        event_bus.subscribe(CATEGORY_MILESTONE, self._on_milestone)
        event_bus.subscribe(CATEGORY_TRADE, self._on_trade)
        event_bus.subscribe(CATEGORY_DIPLOMACY, self._on_diplomacy)
        event_bus.subscribe(CATEGORY_PERSONAL, self._on_personal)
        event_bus.subscribe(CATEGORY_CULTURAL_SHIFT, self._on_cultural)

    # ------------------------------------------------------------------
    # Event handlers (feed _event_log)
    # ------------------------------------------------------------------

    def _log_event(self, faction_id: int | None, event_key: str, now: float) -> None:
        """Record a tradition-relevant event for a faction."""
        if faction_id is None:
            return
        signals = _EVENT_SIGNAL_MAP.get(event_key, [event_key])
        faction_log = self._event_log.setdefault(faction_id, {})
        for sig in signals:
            faction_log.setdefault(sig, []).append(now)

    def record_event(self, faction_id: int, event_key: str, now: float | None = None) -> None:
        """Public API: record a tradition-relevant event for a faction."""
        if now is None:
            now = time.time()
        self._log_event(faction_id, event_key, now)
        # Immediate reinforcement check for existing traditions
        self._try_reinforce(faction_id, event_key, now)

    def _on_death(self, event: GameEvent) -> None:
        meta = event.metadata or {}
        cause = meta.get("cause", "unknown")
        self._log_event(event.faction_id, "death", event.timestamp)
        if cause == "combat":
            self._log_event(event.faction_id, "combat_death", event.timestamp)

    def _on_warfare(self, event: GameEvent) -> None:
        meta = event.metadata or {}
        # Record warfare event for all involved factions
        attacker_id = meta.get("attacker_faction_id")
        defender_id = meta.get("defender_faction_id")
        for fid in (attacker_id, defender_id):
            if fid is not None:
                self._log_event(fid, "warfare", event.timestamp)

    def _on_disaster(self, event: GameEvent) -> None:
        meta = event.metadata or {}
        dtype = meta.get("type", "disaster")
        if dtype == "epidemic":
            self._log_event(event.faction_id, "epidemic", event.timestamp)
        else:
            self._log_event(event.faction_id, "disaster", event.timestamp)

    def _on_building(self, event: GameEvent) -> None:
        self._log_event(event.faction_id, "building_completed", event.timestamp)

    def _on_milestone(self, event: GameEvent) -> None:
        meta = event.metadata or {}
        if meta.get("type") == "tech_unlocked":
            self._log_event(event.faction_id, "tech_unlocked", event.timestamp)

    def _on_trade(self, event: GameEvent) -> None:
        meta = event.metadata or {}
        self._log_event(event.faction_id, "trade_completed", event.timestamp)
        other_id = meta.get("other_faction_id")
        if other_id is not None:
            self._log_event(other_id, "trade_completed", event.timestamp)

    def _on_diplomacy(self, event: GameEvent) -> None:
        meta = event.metadata or {}
        dtype = meta.get("type", "")
        if "treaty" in dtype:
            self._log_event(event.faction_id, "treaty_signed", event.timestamp)
            other_id = meta.get("other_faction_id")
            if other_id is not None:
                self._log_event(other_id, "treaty_signed", event.timestamp)
        elif dtype == "cultural_exchange":
            self._log_event(event.faction_id, "cultural_exchange", event.timestamp)

    def _on_personal(self, event: GameEvent) -> None:
        meta = event.metadata or {}
        ptype = meta.get("type", "")
        if ptype == "crafted_masterwork":
            self._log_event(event.faction_id, "crafted_masterwork", event.timestamp)
        elif ptype in ("healed_other", "disease_recovery"):
            self._log_event(event.faction_id, "healed_other", event.timestamp)
        elif ptype == "teaching":
            self._log_event(event.faction_id, "teaching", event.timestamp)

    def _on_cultural(self, event: GameEvent) -> None:
        meta = event.metadata or {}
        ritual_id = meta.get("ritual_id", "")
        if ritual_id == "harvest_thanksgiving":
            self._log_event(event.faction_id, "ritual_harvest_thanksgiving", event.timestamp)
        elif ritual_id == "mourning_ceremony":
            self._log_event(event.faction_id, "ritual_mourning_ceremony", event.timestamp)
        elif ritual_id == "victory_celebration":
            self._log_event(event.faction_id, "ritual_victory_celebration", event.timestamp)

    # ------------------------------------------------------------------
    # Reinforcement (immediate, on matching event)
    # ------------------------------------------------------------------

    def _try_reinforce(self, faction_id: int, event_key: str, now: float) -> None:
        """Reinforce any existing traditions that match this event."""
        _load_defs()
        traditions = self._traditions.get(faction_id, [])
        signals = _EVENT_SIGNAL_MAP.get(event_key, [event_key])
        for trad in traditions:
            tdef = _tradition_def_cache.get(trad.tradition_id)
            if tdef is None:
                continue
            reinforce_events = tdef.get("reinforcement_events", [])
            if any(s in reinforce_events for s in signals):
                amount = tdef.get("reinforcement_amount", 5)
                max_str = tdef.get("max_strength", 100)
                trad.strength = min(max_str, trad.strength + amount)
                trad.last_reinforced = now

    # ------------------------------------------------------------------
    # Main update loop
    # ------------------------------------------------------------------

    def update(
        self,
        faction_manager=None,
        diplomacy_manager=None,
        praxans=None,
        current_time: float | None = None,
        event_bus=None,
        advisor=None,
        narrative_panel=None,
    ) -> None:
        """Evaluate tradition formation, decay, and cultural exchange.

        Called on rare-tick cadence from the main game loop.
        """
        if current_time is None:
            current_time = time.time()

        if current_time - self._last_update < UPDATE_INTERVAL:
            return
        self._last_update = current_time

        _load_defs()
        if not _tradition_def_cache:
            return

        if diplomacy_manager is not None:
            self._diplomacy_manager = diplomacy_manager

        factions = {}
        if faction_manager is not None:
            factions = getattr(faction_manager, "factions", {})

        # Prune event logs (remove entries older than max window)
        max_window = max(
            (d.get("trigger_window_seconds", 600) for d in _tradition_def_cache.values()),
            default=600,
        )
        cutoff = current_time - max_window
        for fid in list(self._event_log):
            flog = self._event_log[fid]
            for key in list(flog):
                flog[key] = [t for t in flog[key] if t > cutoff]
                if not flog[key]:
                    del flog[key]
            if not flog:
                del self._event_log[fid]

        # Evaluate each faction
        for fid in list(factions):
            self._evaluate_formation(fid, current_time, narrative_panel, advisor)
            self._apply_decay(fid, current_time, narrative_panel, advisor)

        # Cultural exchange between factions
        if current_time - self._last_exchange >= CULTURAL_EXCHANGE_INTERVAL:
            self._last_exchange = current_time
            self._evaluate_cultural_exchange(
                factions, current_time, narrative_panel, advisor
            )

        # Apply diplomacy modifiers from tradition conflicts/alignment
        if self._diplomacy_manager is not None:
            self._apply_diplomacy_effects(factions)

    # ------------------------------------------------------------------
    # Formation
    # ------------------------------------------------------------------

    def _evaluate_formation(
        self,
        faction_id: int,
        now: float,
        narrative_panel=None,
        advisor=None,
    ) -> None:
        """Check if any new tradition should form for this faction."""
        faction_log = self._event_log.get(faction_id, {})
        current_ids = {t.tradition_id for t in self._traditions.get(faction_id, [])}

        for tid, tdef in _tradition_def_cache.items():
            if tid in current_ids:
                continue  # already have it

            trigger_events = tdef.get("trigger_events", [])
            threshold = tdef.get("trigger_threshold", 3)
            window = tdef.get("trigger_window_seconds", 600)

            # Count matching events in window
            cutoff = now - window
            count = 0
            for evt_key in trigger_events:
                timestamps = faction_log.get(evt_key, [])
                count += sum(1 for t in timestamps if t > cutoff)

            if count >= threshold:
                self._form_tradition(faction_id, tid, tdef, now, narrative_panel, advisor)

    def _form_tradition(
        self,
        faction_id: int,
        tradition_id: str,
        tdef: dict[str, Any],
        now: float,
        narrative_panel=None,
        advisor=None,
    ) -> None:
        """Create a new tradition for a faction."""
        traditions = self._traditions.setdefault(faction_id, [])

        # Enforce max traditions — drop weakest if at limit
        if len(traditions) >= MAX_TRADITIONS_PER_FACTION:
            weakest = min(traditions, key=lambda t: t.strength)
            self._remove_tradition(
                faction_id, weakest, now, narrative_panel, advisor,
                reason="replaced"
            )

        initial = tdef.get("initial_strength", 30)
        ft = FactionTradition(tradition_id, initial, now)
        traditions.append(ft)
        self.total_traditions_formed += 1

        # History
        record = {
            "type": "formed",
            "faction_id": faction_id,
            "tradition_id": tradition_id,
            "name": tdef.get("name", tradition_id),
            "time": now,
        }
        self.tradition_history.append(record)
        if len(self.tradition_history) > self._max_history:
            self.tradition_history = self.tradition_history[-self._max_history:]

        # EventBus
        if self._event_bus is not None:
            try:
                self._event_bus.publish(GameEvent(
                    category=CATEGORY_CULTURAL_SHIFT,
                    summary=f"Tradition formed: {tdef.get('name', tradition_id)}",
                    faction_id=faction_id,
                    timestamp=now,
                    metadata={
                        "type": "tradition_formed",
                        "tradition_id": tradition_id,
                        "tradition_name": tdef.get("name", tradition_id),
                        "strength": initial,
                    },
                ))
            except Exception:
                pass

        # Narrative
        if narrative_panel is not None:
            name = tdef.get("name", tradition_id)
            try:
                narrative_panel.add_message(
                    f"A new tradition emerges: {name}!",
                    "Achievement",
                )
            except Exception:
                pass

        # Observer timeline
        if advisor is not None:
            try:
                tl = getattr(advisor, "observer_timeline", None)
                if tl is not None:
                    tl.append({
                        "time": now,
                        "category": "cultural_shift",
                        "summary": f"Tradition formed: {tdef.get('name', tradition_id)}",
                    })
                    if len(tl) > 50:
                        del tl[:-50]
            except Exception:
                pass

        _logger.info(
            "Tradition '%s' formed for faction %d (strength %.0f)",
            tradition_id, faction_id, initial,
        )

    # ------------------------------------------------------------------
    # Decay
    # ------------------------------------------------------------------

    def _apply_decay(
        self,
        faction_id: int,
        now: float,
        narrative_panel=None,
        advisor=None,
    ) -> None:
        """Decay traditions that haven't been reinforced recently."""
        _load_defs()
        traditions = self._traditions.get(faction_id, [])
        to_remove: list[FactionTradition] = []

        for trad in traditions:
            tdef = _tradition_def_cache.get(trad.tradition_id)
            if tdef is None:
                to_remove.append(trad)
                continue

            decay_interval = tdef.get("decay_interval_seconds", 60)
            elapsed_since_decay = now - trad.last_decay_time

            if elapsed_since_decay >= decay_interval:
                intervals = int(elapsed_since_decay / decay_interval)
                decay_rate = tdef.get("decay_rate", 0.3)
                trad.strength -= decay_rate * intervals
                trad.last_decay_time = now

                if trad.strength < MIN_STRENGTH_ALIVE:
                    to_remove.append(trad)

        for trad in to_remove:
            self._remove_tradition(
                faction_id, trad, now, narrative_panel, advisor,
                reason="decayed"
            )

    def _remove_tradition(
        self,
        faction_id: int,
        trad: FactionTradition,
        now: float,
        narrative_panel=None,
        advisor=None,
        reason: str = "decayed",
    ) -> None:
        """Remove a tradition from a faction."""
        traditions = self._traditions.get(faction_id, [])
        if trad in traditions:
            traditions.remove(trad)
        self.total_traditions_lost += 1

        tdef = _tradition_def_cache.get(trad.tradition_id, {})
        name = tdef.get("name", trad.tradition_id)

        record = {
            "type": "lost",
            "faction_id": faction_id,
            "tradition_id": trad.tradition_id,
            "name": name,
            "reason": reason,
            "time": now,
        }
        self.tradition_history.append(record)
        if len(self.tradition_history) > self._max_history:
            self.tradition_history = self.tradition_history[-self._max_history:]

        if self._event_bus is not None:
            try:
                self._event_bus.publish(GameEvent(
                    category=CATEGORY_CULTURAL_SHIFT,
                    summary=f"Tradition lost: {name} ({reason})",
                    faction_id=faction_id,
                    timestamp=now,
                    metadata={
                        "type": "tradition_lost",
                        "tradition_id": trad.tradition_id,
                        "tradition_name": name,
                        "reason": reason,
                    },
                ))
            except Exception:
                pass

        if narrative_panel is not None and reason != "replaced":
            try:
                narrative_panel.add_message(
                    f"Tradition fading: {name} is no longer upheld.",
                    "Cultural",
                )
            except Exception:
                pass

        _logger.info(
            "Tradition '%s' lost by faction %d (reason: %s)",
            trad.tradition_id, faction_id, reason,
        )

    # ------------------------------------------------------------------
    # Cultural exchange between factions
    # ------------------------------------------------------------------

    def _evaluate_cultural_exchange(
        self,
        factions: dict,
        now: float,
        narrative_panel=None,
        advisor=None,
    ) -> None:
        """Friendly/allied factions may spread traditions to each other."""
        _load_defs()
        if self._diplomacy_manager is None:
            return

        faction_ids = list(factions.keys())
        for i, fid_a in enumerate(faction_ids):
            for fid_b in faction_ids[i + 1:]:
                standing = self._diplomacy_manager.get_standing(fid_a, fid_b)
                if standing < EXCHANGE_STANDING_THRESHOLD:
                    continue
                if random.random() > EXCHANGE_CHANCE:
                    continue

                # Pick a random tradition from one to spread to the other
                trads_a = self._traditions.get(fid_a, [])
                trads_b = self._traditions.get(fid_b, [])
                ids_a = {t.tradition_id for t in trads_a}
                ids_b = {t.tradition_id for t in trads_b}

                # Traditions A has that B doesn't
                spreadable_to_b = [t for t in trads_a if t.tradition_id not in ids_b and t.strength >= 40]
                spreadable_to_a = [t for t in trads_b if t.tradition_id not in ids_a and t.strength >= 40]

                candidates = []
                if spreadable_to_b:
                    src = random.choice(spreadable_to_b)
                    candidates.append((fid_b, src))
                if spreadable_to_a:
                    src = random.choice(spreadable_to_a)
                    candidates.append((fid_a, src))

                if not candidates:
                    continue

                target_fid, source_trad = random.choice(candidates)
                tdef = _tradition_def_cache.get(source_trad.tradition_id)
                if tdef is None:
                    continue

                # Spread at reduced initial strength
                spread_strength = max(15, source_trad.strength * 0.4)
                self._form_tradition(
                    target_fid, source_trad.tradition_id, tdef, now,
                    narrative_panel, advisor,
                )
                # Set to reduced strength
                target_trads = self._traditions.get(target_fid, [])
                for t in target_trads:
                    if t.tradition_id == source_trad.tradition_id and t.formed_at == now:
                        t.strength = spread_strength
                        break

    # ------------------------------------------------------------------
    # Diplomacy effects (tradition conflicts/alignment)
    # ------------------------------------------------------------------

    def _apply_diplomacy_effects(self, factions: dict) -> None:
        """Adjust diplomacy standings based on shared or conflicting traditions."""
        _load_defs()
        if self._diplomacy_manager is None:
            return

        faction_ids = list(factions.keys())
        for i, fid_a in enumerate(faction_ids):
            trads_a = {t.tradition_id for t in self._traditions.get(fid_a, [])}
            for fid_b in faction_ids[i + 1:]:
                trads_b = {t.tradition_id for t in self._traditions.get(fid_b, [])}

                # Shared traditions improve standing slightly
                shared = trads_a & trads_b
                if shared:
                    bonus = len(shared) * 0.3  # small per-eval drift
                    try:
                        self._diplomacy_manager.adjust_standing(fid_a, fid_b, bonus)
                    except Exception:
                        pass

                # Conflicting traditions increase tension
                for tid in trads_a:
                    tdef = _tradition_def_cache.get(tid)
                    if tdef is None:
                        continue
                    conflicts = tdef.get("conflicts_with", [])
                    for cid in conflicts:
                        if cid in trads_b:
                            tension = tdef.get("conflict_tension", 5) * 0.1
                            try:
                                self._diplomacy_manager.adjust_standing(
                                    fid_a, fid_b, -tension
                                )
                            except Exception:
                                pass

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_faction_traditions(self, faction_id: int) -> list[dict[str, Any]]:
        """Return tradition info dicts for a faction (for UI / LLM)."""
        _load_defs()
        result = []
        for trad in self._traditions.get(faction_id, []):
            tdef = _tradition_def_cache.get(trad.tradition_id, {})
            result.append({
                "id": trad.tradition_id,
                "name": tdef.get("name", trad.tradition_id),
                "category": tdef.get("category", "unknown"),
                "strength": round(trad.strength, 1),
                "effects": tdef.get("effects", {}),
                "narrative": tdef.get("narrative_template", ""),
            })
        return result

    def get_tradition_effects(self, faction_id: int) -> dict[str, Any]:
        """Return aggregated tradition effects for a faction.

        Returns a dict of all active effect keys with their summed values,
        ready to be applied as modifiers by the main game loop.
        """
        _load_defs()
        aggregated: dict[str, Any] = {}
        for trad in self._traditions.get(faction_id, []):
            tdef = _tradition_def_cache.get(trad.tradition_id)
            if tdef is None:
                continue
            effects = tdef.get("effects", {})
            strength_mult = trad.strength / 100.0  # scale by tradition strength
            for key, value in effects.items():
                if key == "skill_xp_bonus" and isinstance(value, dict):
                    existing = aggregated.setdefault("skill_xp_bonus", {})
                    for skill, bonus in value.items():
                        existing[skill] = existing.get(skill, 0.0) + bonus * strength_mult
                elif isinstance(value, (int, float)):
                    aggregated[key] = aggregated.get(key, 0.0) + value * strength_mult
        return aggregated

    def get_tradition_moodlets(self, faction_id: int) -> list[dict[str, Any]]:
        """Return moodlets that should be applied to faction members."""
        _load_defs()
        moodlets = []
        for trad in self._traditions.get(faction_id, []):
            tdef = _tradition_def_cache.get(trad.tradition_id)
            if tdef is None:
                continue
            moodlet_id = tdef.get("moodlet")
            effects = tdef.get("effects", {})
            mood_offset = effects.get("mood_offset", 0)
            if moodlet_id and mood_offset:
                strength_mult = trad.strength / 100.0
                moodlets.append({
                    "id": moodlet_id,
                    "mood_offset": round(mood_offset * strength_mult, 1),
                    "duration": 120,  # reapplied each eval cycle
                })
        return moodlets

    def has_tradition(self, faction_id: int, tradition_id: str) -> bool:
        """Check if a faction has a specific tradition."""
        return any(
            t.tradition_id == tradition_id
            for t in self._traditions.get(faction_id, [])
        )

    def get_tradition_strength(self, faction_id: int, tradition_id: str) -> float:
        """Return the strength of a specific tradition, or 0 if not held."""
        for t in self._traditions.get(faction_id, []):
            if t.tradition_id == tradition_id:
                return t.strength
        return 0.0

    def get_all_faction_ids_with_traditions(self) -> list[int]:
        """Return faction IDs that have at least one tradition."""
        return [fid for fid, trads in self._traditions.items() if trads]

    # ------------------------------------------------------------------
    # Snapshot serialization
    # ------------------------------------------------------------------

    def serialize(self, current_time: float | None = None) -> dict[str, Any]:
        """Serialize to JSON-safe dict for snapshots."""
        if current_time is None:
            current_time = time.time()
        return {
            "traditions": {
                str(fid): [t.to_dict(current_time) for t in trads]
                for fid, trads in self._traditions.items()
                if trads
            },
            "last_update_elapsed": round(max(0.0, current_time - self._last_update), 2),
            "last_exchange_elapsed": round(max(0.0, current_time - self._last_exchange), 2),
            "total_formed": self.total_traditions_formed,
            "total_lost": self.total_traditions_lost,
            "history": list(self.tradition_history[-self._max_history:]),
        }

    def restore(self, data: dict[str, Any], current_time: float | None = None) -> None:
        """Restore from snapshot data."""
        if current_time is None:
            current_time = time.time()

        self._traditions.clear()
        self._event_log.clear()

        traditions_data = data.get("traditions", {})
        for fid_str, trad_list in traditions_data.items():
            try:
                fid = int(fid_str)
            except (ValueError, TypeError):
                continue
            self._traditions[fid] = [
                FactionTradition.from_dict(td, current_time)
                for td in trad_list
                if isinstance(td, dict) and "tradition_id" in td
            ]

        last_update_elapsed = float(data.get("last_update_elapsed", 0.0))
        self._last_update = current_time - last_update_elapsed
        last_exchange_elapsed = float(data.get("last_exchange_elapsed", 0.0))
        self._last_exchange = current_time - last_exchange_elapsed

        self.total_traditions_formed = int(data.get("total_formed", 0))
        self.total_traditions_lost = int(data.get("total_lost", 0))
        self.tradition_history = list(data.get("history", []))[-self._max_history:]

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def remove_faction(self, faction_id: int) -> None:
        """Clean up when a faction is disbanded."""
        self._traditions.pop(faction_id, None)
        self._event_log.pop(faction_id, None)
