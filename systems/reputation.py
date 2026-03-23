"""Reputation & Social Hierarchy System.

Each Praxan has a community ``reputation`` score (0-100, default 50) within
their faction.  Reputation rises and falls based on observable actions:
building, crafting masterworks, healing, teaching, combat victories, ritual
leadership — and drops from insults, mental breaks, fleeing combat, etc.

Reputation determines a Praxan's **social tier** which drives:

- **Leadership elections**: high-rep Praxans are weighted in leader selection
- **Moodlets**: Luminaries feel proud; Outcasts feel shunned
- **Social interactions**: high-rep Praxans are approached more often
- **Ritual roles**: highest-rep faction member leads rituals
- **Episodic memory**: tier transitions create lasting memories
- **EventBus**: tier changes publish CATEGORY_PERSONAL events

Definitions live in ``defs/core/reputation.json`` (ReputationEventDef and
ReputationTierDef) and are loaded via ``DefDatabase``.

Integration:
    - ``ReputationManager.update()`` called on rare-tick cadence
    - ``ReputationManager.record_event(praxan_id, event_id)`` called by
      other systems when noteworthy actions occur
    - Snapshot: ``serialize()`` / ``restore()`` for save/load
"""

from __future__ import annotations

import time
from typing import Any, Optional

from events.bus import CATEGORY_PERSONAL, GameEvent

# ---------------------------------------------------------------------------
# Def caches (lazily loaded from DefDatabase)
# ---------------------------------------------------------------------------

_event_def_cache: dict[str, dict[str, Any]] = {}
_tier_def_cache: list[dict[str, Any]] = []


def _load_defs() -> None:
    """Populate caches from DefDatabase."""
    global _event_def_cache, _tier_def_cache
    if _event_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        event_defs = DefDatabase.get_all("ReputationEventDef")
        if event_defs:
            for def_id, def_data in event_defs.items():
                _event_def_cache[def_id] = def_data
        tier_defs = DefDatabase.get_all("ReputationTierDef")
        if tier_defs:
            # Sort tiers descending by min_reputation so highest tier matches first
            _tier_def_cache = sorted(
                tier_defs.values(),
                key=lambda t: t.get("min_reputation", 0),
                reverse=True,
            )
    except Exception:
        pass


def get_event_def(event_id: str) -> Optional[dict[str, Any]]:
    """Return a ReputationEventDef by id, or None."""
    _load_defs()
    return _event_def_cache.get(event_id)


def get_all_event_defs() -> dict[str, dict[str, Any]]:
    """Return all known ReputationEventDefs."""
    _load_defs()
    return dict(_event_def_cache)


def get_tier_for_reputation(reputation: float) -> dict[str, Any]:
    """Return the ReputationTierDef matching *reputation*."""
    _load_defs()
    for tier in _tier_def_cache:
        if reputation >= tier.get("min_reputation", 0):
            return tier
    # Fallback: outcast
    if _tier_def_cache:
        return _tier_def_cache[-1]
    return {"id": "established", "label": "Established", "min_reputation": 40}


def clear_cache() -> None:
    """Clear cached defs (for testing)."""
    global _event_def_cache, _tier_def_cache
    _event_def_cache = {}
    _tier_def_cache = []


# ---------------------------------------------------------------------------
# ReputationManager
# ---------------------------------------------------------------------------

# How often (seconds) the manager re-evaluates tier moodlets
_TIER_EVAL_INTERVAL = 30.0

# Natural drift rate per evaluation toward 50 (regression to the mean)
_DRIFT_RATE = 0.3

# How much reputation a leader gains per rare-tick evaluation
_LEADER_TENURE_DELTA = 1.0


class ReputationManager:
    """Manages per-Praxan reputation scores and social hierarchy tiers.

    Typical lifecycle::

        mgr = ReputationManager()
        mgr.attach_event_bus(event_bus)  # auto-react to game events
        # Other systems call record_event when things happen:
        mgr.record_event(praxan_id, "built_structure")
        mgr.record_event(praxan_id, "insult_given")
        # On rare tick:
        mgr.update(praxans, faction_manager, event_bus, current_time)
    """

    def __init__(self) -> None:
        # {praxan_id: float}  reputation scores (0-100, default 50)
        self._scores: dict[int, float] = {}
        # {praxan_id: str}  current tier id (for detecting transitions)
        self._tiers: dict[int, str] = {}
        # {praxan_id: [(event_id, timestamp), ...]}  recent event log
        self._event_log: dict[int, list[tuple[str, float]]] = {}
        # Last time we evaluated tiers
        self._last_eval_time: float = 0.0
        # EventBus reference for auto-subscription
        self._event_bus: Any = None

    # ---- EventBus auto-subscription ---------------------------------------

    def attach_event_bus(self, event_bus: Any) -> None:
        """Subscribe to EventBus categories to auto-record reputation events."""
        self._event_bus = event_bus
        if event_bus is None:
            return
        try:
            from events.bus import (
                CATEGORY_PERSONAL, CATEGORY_BUILDING, CATEGORY_DEATH,
                CATEGORY_DISASTER, CATEGORY_MILESTONE,
            )
            event_bus.subscribe(CATEGORY_PERSONAL, self._on_personal_event)
            event_bus.subscribe(CATEGORY_DEATH, self._on_death_event)
            event_bus.subscribe(CATEGORY_DISASTER, self._on_disaster_event)
        except Exception:
            pass

    def _on_personal_event(self, event: Any) -> None:
        """React to CATEGORY_PERSONAL events (social interactions, disease)."""
        metadata = getattr(event, "metadata", {}) or {}
        praxan_id = getattr(event, "praxan_id", None)

        # Disease recovery
        if metadata.get("type") == "disease_recovered" and praxan_id is not None:
            self.record_event(praxan_id, "recovered_from_disease")
            return

        # Social interaction events
        interaction_id = metadata.get("interaction")
        initiator_id = metadata.get("initiator")
        target_id = metadata.get("target")

        if interaction_id and initiator_id is not None:
            if interaction_id == "insult":
                self.record_event(initiator_id, "insult_given")
            elif interaction_id == "argument":
                self.record_event(initiator_id, "argument_started")
            elif interaction_id == "teach" and initiator_id is not None:
                self.record_event(initiator_id, "taught_skill")
            elif interaction_id == "comfort" and initiator_id is not None:
                self.record_event(initiator_id, "comforted_grieving")
            elif interaction_id == "share_meal" and initiator_id is not None:
                self.record_event(initiator_id, "shared_food")

    def _on_death_event(self, event: Any) -> None:
        """Clean up reputation data when a praxan dies."""
        praxan_id = getattr(event, "praxan_id", None)
        if praxan_id is not None:
            self.remove_praxan(praxan_id)

    def _on_disaster_event(self, event: Any) -> None:
        """Surviving a disaster grants reputation to affected praxans."""
        metadata = getattr(event, "metadata", {}) or {}
        survivors = metadata.get("survivors", [])
        for pid in survivors:
            if isinstance(pid, int):
                self.record_event(pid, "survived_disaster")

    # ---- public API -------------------------------------------------------

    def get_reputation(self, praxan_id: int) -> float:
        """Return *praxan_id*'s reputation (default 50)."""
        return self._scores.get(praxan_id, 50.0)

    def get_tier(self, praxan_id: int) -> str:
        """Return *praxan_id*'s current tier id."""
        return self._tiers.get(praxan_id, "established")

    def get_tier_label(self, praxan_id: int) -> str:
        """Return a human-readable tier label."""
        rep = self.get_reputation(praxan_id)
        tier = get_tier_for_reputation(rep)
        return tier.get("label", "Established")

    def record_event(
        self,
        praxan_id: int,
        event_id: str,
        multiplier: float = 1.0,
    ) -> float:
        """Apply a reputation event to *praxan_id*.

        Returns the actual delta applied (after clamping).
        The *multiplier* allows scaling (e.g. masterwork quality bonus).
        """
        edef = get_event_def(event_id)
        if edef is None:
            return 0.0

        base_delta = edef.get("delta", 0)
        delta = base_delta * multiplier

        old_score = self._scores.get(praxan_id, 50.0)
        new_score = max(0.0, min(100.0, old_score + delta))
        self._scores[praxan_id] = new_score

        # Log the event
        now = time.time()
        log = self._event_log.setdefault(praxan_id, [])
        log.append((event_id, now))
        # Keep bounded (last 30 events per praxan)
        if len(log) > 30:
            del log[:-30]

        return new_score - old_score

    def set_reputation(self, praxan_id: int, value: float) -> None:
        """Directly set reputation (for snapshot restore)."""
        self._scores[praxan_id] = max(0.0, min(100.0, float(value)))

    def remove_praxan(self, praxan_id: int) -> None:
        """Clean up when a praxan dies."""
        self._scores.pop(praxan_id, None)
        self._tiers.pop(praxan_id, None)
        self._event_log.pop(praxan_id, None)

    # ---- rare-tick update --------------------------------------------------

    def update(
        self,
        praxans: list,
        faction_manager: Any = None,
        event_bus: Any = None,
        current_time: float | None = None,
    ) -> None:
        """Evaluate tiers, apply moodlets, drift toward mean.

        Called on rare-tick cadence (~every 4 seconds).
        """
        now = current_time or time.time()

        # Only run full tier evaluation periodically
        do_tier_eval = (now - self._last_eval_time) >= _TIER_EVAL_INTERVAL
        if do_tier_eval:
            self._last_eval_time = now

        # Grant leadership tenure bonus
        if faction_manager is not None and do_tier_eval:
            self._apply_leadership_tenure(faction_manager)

        for praxan in praxans:
            pid = praxan.id
            if not getattr(praxan, "alive", True):
                continue

            # Initialize if new
            if pid not in self._scores:
                self._scores[pid] = 50.0

            # Drain queued reputation events from entity code
            pending = getattr(praxan, "_pending_reputation_events", None)
            if pending:
                for event_id in pending:
                    self.record_event(pid, event_id)
                pending.clear()

            # Natural drift toward 50 (regression to mean) on tier eval
            if do_tier_eval:
                score = self._scores[pid]
                if score > 50.0:
                    self._scores[pid] = max(50.0, score - _DRIFT_RATE)
                elif score < 50.0:
                    self._scores[pid] = min(50.0, score + _DRIFT_RATE)

            # Tier evaluation and moodlet application
            if do_tier_eval:
                self._evaluate_tier(praxan, event_bus, now)

    def _apply_leadership_tenure(self, faction_manager: Any) -> None:
        """Grant small reputation bonus to current faction leaders."""
        factions = getattr(faction_manager, "factions", {})
        # factions is a dict {faction_id: Faction} — iterate values, not keys
        faction_iter = factions.values() if isinstance(factions, dict) else factions
        for faction in faction_iter:
            leader_id = getattr(faction, "leader_id", None)
            if leader_id is not None:
                self.record_event(leader_id, "leadership_tenure")

    def _evaluate_tier(
        self,
        praxan: Any,
        event_bus: Any,
        current_time: float,
    ) -> None:
        """Check for tier transitions and apply/refresh tier moodlets."""
        pid = praxan.id
        score = self._scores.get(pid, 50.0)
        new_tier_def = get_tier_for_reputation(score)
        new_tier_id = new_tier_def.get("id", "established")
        old_tier_id = self._tiers.get(pid, "established")

        # Detect tier transition
        if new_tier_id != old_tier_id:
            self._tiers[pid] = new_tier_id
            self._on_tier_change(praxan, old_tier_id, new_tier_id, new_tier_def, event_bus, current_time)

        # Refresh tier moodlet (so it stays active while in the tier)
        moodlet_name = new_tier_def.get("moodlet")
        mood_offset = new_tier_def.get("mood_offset", 0)
        mood_duration = new_tier_def.get("mood_duration", 600)
        if moodlet_name and mood_offset != 0 and hasattr(praxan, "add_moodlet"):
            praxan.add_moodlet(moodlet_name, mood_offset, mood_duration, current_time)

    def _on_tier_change(
        self,
        praxan: Any,
        old_tier_id: str,
        new_tier_id: str,
        new_tier_def: dict[str, Any],
        event_bus: Any,
        current_time: float,
    ) -> None:
        """Handle a tier transition: memory, event, moodlet pulse."""
        name = getattr(praxan, "name", f"Praxan {praxan.id}")
        label = new_tier_def.get("label", new_tier_id)

        # Episodic memory
        if hasattr(praxan, "episodic_memory") and praxan.episodic_memory is not None:
            if new_tier_id == "luminary":
                praxan.episodic_memory.record(
                    "became_luminary",
                    f"{name} became a Luminary — revered by the community",
                    metadata={"tier": new_tier_id, "reputation": self._scores.get(praxan.id, 50.0)},
                )
            elif new_tier_id == "outcast":
                praxan.episodic_memory.record(
                    "became_outcast",
                    f"{name} became an Outcast — shunned by the community",
                    metadata={"tier": new_tier_id, "reputation": self._scores.get(praxan.id, 50.0)},
                )
            else:
                praxan.episodic_memory.record(
                    "reputation_milestone",
                    f"{name} is now {label} in the community",
                    metadata={"tier": new_tier_id, "reputation": self._scores.get(praxan.id, 50.0)},
                )

        # Transition moodlet pulse (short-lived)
        is_rise = _tier_rank(new_tier_id) > _tier_rank(old_tier_id)
        if hasattr(praxan, "add_moodlet"):
            if is_rise:
                praxan.add_moodlet("GainedReputation", 3, 180, current_time)
            else:
                praxan.add_moodlet("LostReputation", -3, 180, current_time)

        # EventBus
        if event_bus is not None:
            try:
                direction = "rose to" if is_rise else "fell to"
                event_bus.publish(GameEvent(
                    category=CATEGORY_PERSONAL,
                    summary=f"{name} {direction} {label}",
                    detail=f"Reputation: {self._scores.get(praxan.id, 50.0):.0f}/100",
                    praxan_id=praxan.id,
                    faction_id=getattr(praxan, "faction_id", None),
                    metadata={"old_tier": old_tier_id, "new_tier": new_tier_id, "reputation": self._scores.get(praxan.id, 50.0)},
                ))
            except Exception:
                pass

    # ---- leader election integration --------------------------------------

    def leadership_score_bonus(self, praxan_id: int) -> float:
        """Return a score bonus for leader election based on reputation.

        Range: -5.0 (outcast) to +15.0 (luminary).
        Designed to be added to the existing skill-based score in
        ``Faction.update_leader()``.
        """
        rep = self.get_reputation(praxan_id)
        # Linear mapping: 0 rep → -5, 50 rep → 0, 100 rep → +15
        if rep >= 50:
            return (rep - 50) * 0.3  # 0 to +15
        else:
            return (rep - 50) * 0.1  # -5 to 0

    # ---- social interaction integration -----------------------------------

    def social_weight_modifier(self, praxan_id: int) -> float:
        """Return a multiplier for how likely this praxan is to be
        chosen as a social interaction target.

        Range: 0.5 (outcast) to 1.5 (luminary).
        """
        rep = self.get_reputation(praxan_id)
        return 0.5 + (rep / 100.0)

    # ---- query helpers ----------------------------------------------------

    def get_faction_hierarchy(self, faction_member_ids: list[int]) -> list[tuple[int, float, str]]:
        """Return faction members sorted by reputation (descending).

        Returns list of (praxan_id, reputation, tier_id).
        """
        entries = []
        for pid in faction_member_ids:
            rep = self.get_reputation(pid)
            tier = get_tier_for_reputation(rep).get("id", "established")
            entries.append((pid, rep, tier))
        entries.sort(key=lambda e: e[1], reverse=True)
        return entries

    def get_luminaries(self, praxan_ids: list[int] | None = None) -> list[int]:
        """Return IDs of all praxans at Luminary tier."""
        source = praxan_ids if praxan_ids is not None else list(self._scores.keys())
        return [pid for pid in source if self.get_reputation(pid) >= 80]

    def get_outcasts(self, praxan_ids: list[int] | None = None) -> list[int]:
        """Return IDs of all praxans at Outcast tier."""
        source = praxan_ids if praxan_ids is not None else list(self._scores.keys())
        return [pid for pid in source if self.get_reputation(pid) < 20]

    # ---- serialization ----------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        """Serialize for snapshot."""
        return {
            "scores": {str(k): round(v, 2) for k, v in self._scores.items()},
            "tiers": {str(k): v for k, v in self._tiers.items()},
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Restore from snapshot data."""
        self._scores.clear()
        self._tiers.clear()
        self._event_log.clear()

        scores = data.get("scores", {})
        for pid_str, score in scores.items():
            try:
                pid = int(pid_str)
                self._scores[pid] = max(0.0, min(100.0, float(score)))
            except (TypeError, ValueError):
                continue

        tiers = data.get("tiers", {})
        for pid_str, tier_id in tiers.items():
            try:
                pid = int(pid_str)
                self._tiers[pid] = str(tier_id)
            except (TypeError, ValueError):
                continue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIER_RANKS = {
    "outcast": 0,
    "marginal": 1,
    "established": 2,
    "respected": 3,
    "luminary": 4,
}


def _tier_rank(tier_id: str) -> int:
    """Numeric rank for ordering tier transitions."""
    return _TIER_RANKS.get(tier_id, 2)
