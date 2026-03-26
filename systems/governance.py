"""Governance & Edicts System — autonomous faction policy decisions.

Faction leaders periodically evaluate conditions (warfare, disease, food,
cohesion) and issue edicts that modify faction behaviour for a limited
duration.  Only one edict can be active per faction at a time.  Edicts
produce moodlets, episodic memory, EventBus events, and feed into other
systems via the ``get_active_effect`` helper.

Defs live in ``defs/core/edicts.json`` (defType ``EdictDef``).
"""

from __future__ import annotations

import random
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Def cache
# ---------------------------------------------------------------------------

_edict_def_cache: dict[str, dict] = {}


def _load_defs() -> None:
    from systems.def_database import DefDatabase

    _edict_def_cache.clear()
    raw = DefDatabase.get_all("EdictDef")
    if isinstance(raw, dict):
        _edict_def_cache.update(raw)
    elif isinstance(raw, list):
        for d in raw:
            if isinstance(d, dict) and "id" in d:
                _edict_def_cache[d["id"]] = d


def get_edict_def(edict_id: str) -> Optional[dict]:
    if not _edict_def_cache:
        _load_defs()
    return _edict_def_cache.get(edict_id)


def get_all_edict_defs() -> dict[str, dict]:
    if not _edict_def_cache:
        _load_defs()
    return dict(_edict_def_cache)


def clear_cache() -> None:
    _edict_def_cache.clear()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVAL_INTERVAL: float = 30.0       # seconds between evaluations
EDICT_APPLY_INTERVAL: float = 15.0  # seconds between moodlet re-application

# EventBus categories used
try:
    from events.bus import (
        CATEGORY_DOCTRINE,
        CATEGORY_WARFARE,
        CATEGORY_DISASTER,
        GameEvent,
    )
except ImportError:
    CATEGORY_DOCTRINE = "doctrine"
    CATEGORY_WARFARE = "warfare"
    CATEGORY_DISASTER = "disaster"
    GameEvent = None  # type: ignore[misc, assignment]


# ---------------------------------------------------------------------------
# ActiveEdict — runtime state for a single active edict
# ---------------------------------------------------------------------------

class ActiveEdict:
    """Tracks a single active edict within a faction."""

    __slots__ = (
        "edict_id", "faction_id", "issued_at", "duration",
        "leader_id_at_issue", "last_moodlet_time",
    )

    def __init__(
        self,
        edict_id: str,
        faction_id: int,
        issued_at: float,
        duration: float,
        leader_id_at_issue: Optional[int] = None,
    ) -> None:
        self.edict_id = edict_id
        self.faction_id = faction_id
        self.issued_at = issued_at
        self.duration = duration
        self.leader_id_at_issue = leader_id_at_issue
        self.last_moodlet_time: float = 0.0

    @property
    def expires_at(self) -> float:
        return self.issued_at + self.duration

    def is_expired(self, current_time: float) -> bool:
        return current_time >= self.expires_at

    def remaining(self, current_time: float) -> float:
        return max(0.0, self.expires_at - current_time)

    # -- serialization --

    def serialize(self, now: float) -> dict[str, Any]:
        return {
            "edict_id": self.edict_id,
            "faction_id": self.faction_id,
            "remaining_seconds": self.remaining(now),
            "duration": self.duration,
            "leader_id_at_issue": self.leader_id_at_issue,
        }

    @classmethod
    def restore(cls, data: dict[str, Any], now: float) -> "ActiveEdict":
        remaining = max(5.0, float(data.get("remaining_seconds", 30)))
        duration = float(data.get("duration", 180))
        issued_at = now - (duration - remaining)
        ae = cls(
            edict_id=data["edict_id"],
            faction_id=data["faction_id"],
            issued_at=issued_at,
            duration=duration,
            leader_id_at_issue=data.get("leader_id_at_issue"),
        )
        return ae


# ---------------------------------------------------------------------------
# GovernanceManager
# ---------------------------------------------------------------------------

class GovernanceManager:
    """Manages edict issuance and expiry per faction.

    Public API:
        update(...)          — called on rare-tick from main loop
        get_active_edict(fid) — returns ActiveEdict or None
        get_active_effect(fid, key, default)
                             — read a specific effect value for a faction
        serialize / restore  — snapshot persistence
        attach_event_bus     — subscribe to warfare / disaster
    """

    def __init__(self) -> None:
        # faction_id → ActiveEdict (one at a time)
        self._active: dict[int, ActiveEdict] = {}
        # faction_id → {edict_id: last_issued_time}
        self._cooldowns: dict[int, dict[str, float]] = {}
        # faction_id → list of past edict ids (history)
        self._history: dict[int, list[str]] = {}

        self._last_eval_time: float = 0.0
        self._event_bus = None

        # Pending signals from EventBus
        self._warfare_active_factions: set[int] = set()

    # ---- EventBus ----------------------------------------------------------

    def attach_event_bus(self, event_bus) -> None:
        self._event_bus = event_bus
        if event_bus:
            event_bus.subscribe(CATEGORY_WARFARE, self._on_warfare)

    def _on_warfare(self, event) -> None:
        metadata = getattr(event, "metadata", {}) or {}
        for key in ("attacker_faction_id", "attacker_faction",
                     "defender_faction_id", "defender_faction"):
            fid = metadata.get(key)
            if fid is not None:
                self._warfare_active_factions.add(fid)

    # ---- Queries -----------------------------------------------------------

    def get_active_edict(self, faction_id: int) -> Optional[ActiveEdict]:
        return self._active.get(faction_id)

    def get_active_effect(self, faction_id: int, key: str, default: Any = None) -> Any:
        """Return the value of a specific effect from the active edict, or *default*."""
        ae = self._active.get(faction_id)
        if ae is None:
            return default
        edict_def = get_edict_def(ae.edict_id)
        if not edict_def:
            return default
        return edict_def.get("effects", {}).get(key, default)

    def get_edict_history(self, faction_id: int) -> list[str]:
        return list(self._history.get(faction_id, []))

    def has_active_edict(self, faction_id: int) -> bool:
        return faction_id in self._active

    # ---- Main update -------------------------------------------------------

    def update(
        self,
        faction_manager=None,
        praxans: Optional[list] = None,
        diplomacy_manager=None,
        disease_manager=None,
        warfare_manager=None,
        current_time: float = 0.0,
        advisor=None,
        narrative_panel=None,
    ) -> None:
        if current_time - self._last_eval_time < EVAL_INTERVAL:
            return
        self._last_eval_time = current_time

        praxans = praxans or []
        praxan_map = {p.id: p for p in praxans if getattr(p, "alive", True)}

        # 1. Expire finished edicts
        self._expire_edicts(current_time, praxan_map)

        # 2. Apply ongoing edict effects (moodlets)
        self._apply_ongoing_effects(current_time, praxan_map, faction_manager)

        # 3. Issue new edicts for factions without one
        if faction_manager:
            for faction in (faction_manager.factions.values()
                            if isinstance(faction_manager.factions, dict)
                            else faction_manager.factions):
                fid = faction.id
                if fid in self._active:
                    continue  # already has an edict
                if len(getattr(faction, "member_ids", [])) < 3:
                    continue  # too small

                edict_id = self._select_edict(
                    faction, praxan_map, diplomacy_manager,
                    disease_manager, warfare_manager, current_time,
                )
                if edict_id:
                    self._issue_edict(
                        edict_id, faction, praxan_map, current_time,
                        advisor, narrative_panel,
                    )

        # Decay warfare signals
        self._warfare_active_factions.clear()

    # ---- Edict lifecycle ---------------------------------------------------

    def _issue_edict(
        self,
        edict_id: str,
        faction,
        praxan_map: dict,
        current_time: float,
        advisor=None,
        narrative_panel=None,
    ) -> None:
        edict_def = get_edict_def(edict_id)
        if not edict_def:
            return

        fid = faction.id
        duration = float(edict_def.get("duration", 180))
        ae = ActiveEdict(
            edict_id=edict_id,
            faction_id=fid,
            issued_at=current_time,
            duration=duration,
            leader_id_at_issue=getattr(faction, "leader_id", None),
        )
        self._active[fid] = ae

        # Record cooldown
        self._cooldowns.setdefault(fid, {})[edict_id] = current_time

        # Record history
        self._history.setdefault(fid, []).append(edict_id)

        # Apply initial moodlets + memory
        self._apply_moodlets(ae, edict_def, praxan_map, faction, current_time)

        # Episodic memory for notable edicts
        memory_event = None
        if edict_id == "festival_decree":
            memory_event = "edict_festival"
        elif edict_id == "martial_law":
            memory_event = "edict_martial_law"
        else:
            memory_event = "edict_issued"

        edict_name = edict_def.get("name", edict_id)
        for mid in getattr(faction, "member_ids", []):
            p = praxan_map.get(mid)
            if p and hasattr(p, "episodic_memory") and p.episodic_memory:
                p.episodic_memory.record(
                    memory_event,
                    f"Faction issued edict: {edict_name}",
                )

        # EventBus
        if self._event_bus and GameEvent is not None:
            self._event_bus.publish(GameEvent(
                category=CATEGORY_DOCTRINE,
                summary=f"Edict: {edict_name}",
                detail=edict_def.get("description", ""),
                faction_id=fid,
                timestamp=current_time,
                metadata={
                    "edict_id": edict_id,
                    "faction_id": fid,
                    "duration": duration,
                },
            ))

        # Narrative panel
        if narrative_panel:
            faction_name = getattr(faction, "name", f"Faction {fid}")
            narrative_panel.add_message(
                f"{faction_name} issued edict: {edict_name}",
                "Governance",
            )

        # Observer timeline
        if advisor and hasattr(advisor, "observer_timeline"):
            faction_name = getattr(faction, "name", f"Faction {fid}")
            advisor.observer_timeline.append({
                "time": current_time,
                "type": "governance",
                "message": f"{faction_name} issued '{edict_name}' edict",
            })

    def _expire_edicts(self, current_time: float, praxan_map: dict) -> None:
        expired_fids = [
            fid for fid, ae in self._active.items()
            if ae.is_expired(current_time)
        ]
        for fid in expired_fids:
            del self._active[fid]

    def _apply_ongoing_effects(
        self, current_time: float, praxan_map: dict, faction_manager=None,
    ) -> None:
        """Re-apply moodlets periodically for active edicts."""
        if not faction_manager:
            return

        factions_map = {}
        factions_list = (faction_manager.factions.values()
                         if isinstance(faction_manager.factions, dict)
                         else faction_manager.factions)
        for f in factions_list:
            factions_map[f.id] = f

        for fid, ae in self._active.items():
            if current_time - ae.last_moodlet_time < EDICT_APPLY_INTERVAL:
                continue

            edict_def = get_edict_def(ae.edict_id)
            faction = factions_map.get(fid)
            if not edict_def or not faction:
                continue

            self._apply_moodlets(ae, edict_def, praxan_map, faction, current_time)

            # Apply cohesion drift
            cohesion_tick = edict_def.get("effects", {}).get("cohesion_per_tick")
            if cohesion_tick is not None and hasattr(faction, "cohesion"):
                faction.cohesion = max(0.0, min(100.0, faction.cohesion + float(cohesion_tick)))

    def _apply_moodlets(
        self,
        ae: ActiveEdict,
        edict_def: dict,
        praxan_map: dict,
        faction,
        current_time: float,
    ) -> None:
        moodlet_id = edict_def.get("moodlet_id")
        moodlet_offset = edict_def.get("moodlet_offset", 0)
        moodlet_duration = edict_def.get("moodlet_duration", 120)
        if not moodlet_id:
            return

        ae.last_moodlet_time = current_time

        for mid in getattr(faction, "member_ids", []):
            p = praxan_map.get(mid)
            if p and hasattr(p, "add_moodlet"):
                p.add_moodlet(moodlet_id, moodlet_offset, moodlet_duration, current_time)

    # ---- Edict selection (AI decision) -------------------------------------

    def _select_edict(
        self,
        faction,
        praxan_map: dict,
        diplomacy_manager,
        disease_manager,
        warfare_manager,
        current_time: float,
    ) -> Optional[str]:
        """Score each edict for the faction and pick the best valid candidate."""
        all_defs = get_all_edict_defs()
        if not all_defs:
            return None

        fid = faction.id
        leader_id = getattr(faction, "leader_id", None)
        leader = praxan_map.get(leader_id) if leader_id is not None else None

        candidates: list[tuple[str, float]] = []

        for edict_id, edict_def in all_defs.items():
            # Cooldown check — skip if issued too recently
            faction_cds = self._cooldowns.get(fid, {})
            if edict_id in faction_cds:
                cd = faction_cds[edict_id]
                cooldown = float(edict_def.get("cooldown", 300))
                if current_time - cd < cooldown:
                    continue

            # Precondition check
            if not self._check_preconditions(
                edict_def, faction, praxan_map, diplomacy_manager,
                disease_manager, warfare_manager, current_time,
            ):
                continue

            # Score = base + doctrine_affinity + leader personality
            score = float(edict_def.get("priority_score_base", 3))

            # Doctrine affinity bonus
            doctrine = getattr(faction, "primary_doctrine", "growth")
            if edict_def.get("doctrine_affinity") == doctrine:
                score += 4.0

            # Leader personality bonus
            if leader:
                pw = edict_def.get("personality_weights", {})
                for trait, weight in pw.items():
                    trait_val = getattr(leader, trait, None)
                    if trait_val is None:
                        trait_val = getattr(leader, "genetics", {}).get(trait, 0.5)
                    if isinstance(trait_val, (int, float)):
                        score += float(weight) * float(trait_val) * 5.0

            # Slight randomness
            score += random.uniform(0, 2.0)

            if score > 0:
                candidates.append((edict_id, score))

        if not candidates:
            return None

        # Weighted random from top 3 candidates
        candidates.sort(key=lambda x: x[1], reverse=True)
        top = candidates[:3]
        total_weight = sum(s for _, s in top)
        if total_weight <= 0:
            return top[0][0]

        roll = random.uniform(0, total_weight)
        cumulative = 0.0
        for eid, s in top:
            cumulative += s
            if roll <= cumulative:
                return eid
        return top[0][0]

    def _check_preconditions(
        self,
        edict_def: dict,
        faction,
        praxan_map: dict,
        diplomacy_manager,
        disease_manager,
        warfare_manager,
        current_time: float,
    ) -> bool:
        """Return True if the edict's preconditions are met."""
        preconds = edict_def.get("preconditions", {})
        if not preconds:
            return True

        fid = faction.id

        # min_warfare_threat: requires active raids or hostile diplomacy
        if preconds.get("min_warfare_threat"):
            has_threat = fid in self._warfare_active_factions
            if not has_threat and warfare_manager:
                active = getattr(warfare_manager, "active_raids", [])
                has_threat = any(
                    getattr(r, "attacker_faction_id", None) == fid or
                    getattr(r, "defender_faction_id", None) == fid
                    for r in active
                )
            if not has_threat and diplomacy_manager:
                # Check if any faction is hostile
                has_threat = self._has_hostile_neighbour(fid, diplomacy_manager)
            if not has_threat:
                return False

        # max_food_security
        max_food = preconds.get("max_food_security")
        if max_food is not None:
            food_sec = getattr(faction, "food_security", 50.0) / 100.0
            if food_sec > float(max_food):
                return False

        # min_cohesion / max_cohesion
        min_coh = preconds.get("min_cohesion")
        if min_coh is not None:
            if getattr(faction, "cohesion", 50.0) < float(min_coh):
                return False

        max_coh = preconds.get("max_cohesion")
        if max_coh is not None:
            if getattr(faction, "cohesion", 50.0) > float(max_coh):
                return False

        # min_disease_count
        min_disease = preconds.get("min_disease_count")
        if min_disease is not None:
            sick_count = 0
            for mid in getattr(faction, "member_ids", []):
                p = praxan_map.get(mid)
                if p and getattr(p, "diseased", False):
                    sick_count += 1
            if sick_count < int(min_disease):
                return False

        return True

    @staticmethod
    def _has_hostile_neighbour(faction_id: int, diplomacy_manager) -> bool:
        """Check if any faction is hostile (standing < -40) toward *faction_id*."""
        if not hasattr(diplomacy_manager, "get_standing"):
            return False
        # Try to iterate all faction pairs
        standings = getattr(diplomacy_manager, "_standings", {})
        for pair, standing in standings.items():
            if faction_id in pair and standing < -40:
                return True
        return False

    # ---- Serialization -----------------------------------------------------

    def serialize(self, current_time: float) -> dict[str, Any]:
        return {
            "version": 1,
            "active_edicts": [
                ae.serialize(current_time) for ae in self._active.values()
            ],
            "cooldowns": {
                str(fid): {eid: current_time - t for eid, t in cds.items()}
                for fid, cds in self._cooldowns.items()
            },
            "history": {str(fid): eids for fid, eids in self._history.items()},
            "last_eval_elapsed": current_time - self._last_eval_time,
        }

    def restore(self, data: dict[str, Any], current_time: float) -> None:
        if not data:
            return

        self._active.clear()
        self._cooldowns.clear()
        self._history.clear()

        for ae_data in data.get("active_edicts", []):
            ae = ActiveEdict.restore(ae_data, current_time)
            self._active[ae.faction_id] = ae

        for fid_str, cds in data.get("cooldowns", {}).items():
            fid = int(fid_str)
            self._cooldowns[fid] = {
                eid: current_time - float(elapsed)
                for eid, elapsed in cds.items()
            }

        for fid_str, eids in data.get("history", {}).items():
            self._history[int(fid_str)] = list(eids)

        elapsed = float(data.get("last_eval_elapsed", EVAL_INTERVAL + 1))
        self._last_eval_time = current_time - elapsed
