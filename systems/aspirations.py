"""Personal Aspirations & Life Goals System.

Each adult Praxan receives a personality-driven **aspiration** — a long-term
life goal that creates narrative drama and connects to skills, reputation,
relationships, and faction governance.

Aspirations are:

- **Personality-weighted**: diligent Praxans aspire to master crafting; sociable
  ones want friendships; curious ones seek exploration.
- **Progress-tracked**: the manager evaluates progress every rare-tick and
  applies moodlets at milestone thresholds (25%, 50%, 75%).
- **Rewarded on completion**: big mood boost, reputation gain, episodic memory.
- **Failed on death or elder transition**: minor mood penalty if unfinished.
- **One at a time**: a Praxan receives a new aspiration after completing or
  failing the current one, with a 30-second cooldown.

Definitions live in ``defs/core/aspirations.json`` (AspirationDef) and are
loaded via ``DefDatabase``.

Integration:
    - ``AspirationManager.update()`` called on rare-tick cadence
    - Entity field: ``praxan.aspiration`` dict with id/progress/assigned_time
    - Snapshot: ``serialize()`` / ``restore()``
    - EventBus: publishes CATEGORY_PERSONAL on completion/failure
    - Reputation: queues ``aspiration_achieved`` / ``aspiration_abandoned``
    - Episodic memory: records assignment, progress milestones, completion, failure
"""

from __future__ import annotations

import random
import time
from typing import Any, Optional

from events.bus import CATEGORY_PERSONAL, CATEGORY_DEATH, GameEvent

# ---------------------------------------------------------------------------
# Def cache (lazily loaded from DefDatabase)
# ---------------------------------------------------------------------------

_aspiration_def_cache: dict[str, dict[str, Any]] = {}


def _load_defs() -> None:
    """Populate cache from DefDatabase."""
    global _aspiration_def_cache
    if _aspiration_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        defs = DefDatabase.get_all("AspirationDef")
        if defs:
            for def_id, def_data in defs.items():
                _aspiration_def_cache[def_id] = def_data
    except Exception:
        pass


def get_aspiration_def(aspiration_id: str) -> Optional[dict[str, Any]]:
    """Return an AspirationDef by id, or None."""
    _load_defs()
    return _aspiration_def_cache.get(aspiration_id)


def get_all_aspiration_defs() -> dict[str, dict[str, Any]]:
    """Return all known AspirationDefs."""
    _load_defs()
    return dict(_aspiration_def_cache)


def clear_cache() -> None:
    """Clear cached defs (for testing)."""
    global _aspiration_def_cache
    _aspiration_def_cache = {}


# ---------------------------------------------------------------------------
# Progress checking functions
# ---------------------------------------------------------------------------

def _check_skill_level(praxan: Any, check: dict) -> tuple[float, float]:
    """Check skill_level aspiration: returns (current_level, threshold)."""
    skill = check.get("skill", "crafting")
    threshold = float(check.get("threshold", 4))
    skill_data = getattr(praxan, "skills", {}).get(skill, {})
    current = float(skill_data.get("level", 1)) if isinstance(skill_data, dict) else 1.0
    return (current, threshold)


def _check_friend_count(praxan: Any, check: dict) -> tuple[float, float]:
    """Check friend_count aspiration: returns (current_friends, threshold)."""
    threshold = float(check.get("threshold", 3))
    relationships = getattr(praxan, "relationships", {})
    # REL_FRIEND = "friend" (from praxans_game constants)
    friend_count = sum(1 for rel in relationships.values() if rel == "friend")
    return (float(friend_count), threshold)


def _check_is_faction_leader(praxan: Any, check: dict, faction_manager: Any = None) -> tuple[float, float]:
    """Check if praxan is current faction leader: (1.0 if leader, 1.0 threshold)."""
    if faction_manager is None:
        return (0.0, 1.0)
    faction_id = getattr(praxan, "faction_id", None)
    if faction_id is None:
        return (0.0, 1.0)
    try:
        faction = faction_manager.factions.get(faction_id)
        if faction is not None:
            leader_id = getattr(faction, "leader_id", None)
            if leader_id == praxan.id:
                return (1.0, 1.0)
    except Exception:
        pass
    return (0.0, 1.0)


def _check_known_resources(praxan: Any, check: dict) -> tuple[float, float]:
    """Check known_resources aspiration: (current_count, threshold)."""
    threshold = float(check.get("threshold", 10))
    known = getattr(praxan, "known_resources", [])
    return (float(len(known)), threshold)


def _check_living_children(praxan: Any, check: dict, all_praxans: list = None) -> tuple[float, float]:
    """Check living_children aspiration: (alive_children, threshold)."""
    threshold = float(check.get("threshold", 2))
    if all_praxans is None:
        return (0.0, threshold)
    relationships = getattr(praxan, "relationships", {})
    children_ids = [pid for pid, rel in relationships.items() if rel == "child"]
    alive_children = 0
    for child_id in children_ids:
        for p in all_praxans:
            if p.id == child_id and getattr(p, "alive", False):
                alive_children += 1
                break
    return (float(alive_children), threshold)


def _check_reputation_tier(praxan: Any, check: dict, reputation_manager: Any = None) -> tuple[float, float]:
    """Check reputation_tier aspiration: (current_rep, tier_threshold)."""
    tier_name = check.get("tier", "Luminary")
    # Map tier names to min reputation
    tier_thresholds = {"Luminary": 80.0, "Respected": 60.0, "Established": 40.0, "Marginal": 20.0, "Outcast": 0.0}
    threshold = tier_thresholds.get(tier_name, 80.0)
    if reputation_manager is None:
        return (50.0, threshold)
    current_rep = reputation_manager.get_reputation(praxan.id)
    return (current_rep, threshold)


def _check_multi_skill(praxan: Any, check: dict) -> tuple[float, float]:
    """Check multi_skill aspiration: (skills_at_threshold, count_needed)."""
    threshold_level = int(check.get("threshold_level", 3))
    threshold_count = float(check.get("threshold_count", 3))
    skills = getattr(praxan, "skills", {})
    count = 0
    for skill_data in skills.values():
        if isinstance(skill_data, dict) and skill_data.get("level", 1) >= threshold_level:
            count += 1
    return (float(count), threshold_count)


def _check_total_inventory(praxan: Any, check: dict) -> tuple[float, float]:
    """Check total_inventory aspiration: (total_resources, threshold)."""
    threshold = float(check.get("threshold", 200))
    inventory = getattr(praxan, "inventory", {})
    total = sum(v for v in inventory.values() if isinstance(v, (int, float)))
    return (float(total), threshold)


def check_progress(praxan: Any, aspiration_def: dict, **context) -> tuple[float, float]:
    """Evaluate progress for a given aspiration definition.

    Returns (current_value, target_value).  Completion when current >= target.
    """
    check = aspiration_def.get("check", {})
    check_type = check.get("type", "")

    if check_type == "skill_level":
        return _check_skill_level(praxan, check)
    elif check_type == "friend_count":
        return _check_friend_count(praxan, check)
    elif check_type == "is_faction_leader":
        return _check_is_faction_leader(praxan, check, context.get("faction_manager"))
    elif check_type == "known_resources":
        return _check_known_resources(praxan, check)
    elif check_type == "living_children":
        return _check_living_children(praxan, check, context.get("all_praxans"))
    elif check_type == "reputation_tier":
        return _check_reputation_tier(praxan, check, context.get("reputation_manager"))
    elif check_type == "multi_skill":
        return _check_multi_skill(praxan, check)
    elif check_type == "total_inventory":
        return _check_total_inventory(praxan, check)
    return (0.0, 1.0)


# ---------------------------------------------------------------------------
# Personality-weighted aspiration selection
# ---------------------------------------------------------------------------

def _score_aspiration_for_praxan(praxan: Any, asp_def: dict) -> float:
    """Score how well an aspiration matches a Praxan's personality.

    Higher score = more likely to be chosen.
    """
    personality = getattr(praxan, "personality", {})
    weights = asp_def.get("personality_weights", {})
    traits = list(getattr(praxan, "traits", []))

    # Base score from personality match
    score = 0.0
    for pkey, weight in weights.items():
        pval = personality.get(pkey, 0.5)
        score += pval * weight

    # Trait affinity bonus
    affinities = asp_def.get("trait_affinities", [])
    for aff in affinities:
        if aff in traits:
            score += 0.2

    # Life stage eligibility
    life_stage = getattr(praxan, "life_stage", "adult")
    allowed_stages = asp_def.get("life_stages", ["adult"])
    if life_stage not in allowed_stages:
        return -999.0  # Ineligible

    # Small random jitter to prevent identical assignments
    score += random.uniform(0.0, 0.15)

    return score


# ---------------------------------------------------------------------------
# AspirationManager
# ---------------------------------------------------------------------------

# How often (seconds) the manager evaluates aspirations
_EVAL_INTERVAL = 15.0

# Cooldown after completing/failing before a new aspiration is assigned
_REASSIGNMENT_COOLDOWN = 30.0

# Progress milestone thresholds (fraction of target) that trigger moodlets
_PROGRESS_MILESTONES = [0.25, 0.50, 0.75]


class AspirationManager:
    """Manages personal aspirations for all Praxans.

    Typical lifecycle::

        mgr = AspirationManager()
        mgr.attach_event_bus(event_bus)
        # On rare tick:
        mgr.update(praxans, faction_manager, reputation_manager, event_bus, current_time)
    """

    def __init__(self) -> None:
        # {praxan_id: aspiration_state_dict}
        # aspiration_state_dict: {id, assigned_time, progress, milestones_hit, completed, failed}
        self._aspirations: dict[int, dict[str, Any]] = {}
        # {praxan_id: timestamp} when last aspiration ended (for cooldown)
        self._cooldowns: dict[int, float] = {}
        self._last_eval_time: float = 0.0
        self._event_bus: Any = None

    # ---- EventBus integration ---------------------------------------------

    def attach_event_bus(self, event_bus: Any) -> None:
        """Subscribe to death events for aspiration failure on death."""
        self._event_bus = event_bus
        if event_bus is None:
            return
        try:
            event_bus.subscribe(CATEGORY_DEATH, self._on_death_event)
        except Exception:
            pass

    def _on_death_event(self, event: Any) -> None:
        """Handle praxan death — fail their aspiration."""
        praxan_id = getattr(event, "praxan_id", None)
        if praxan_id is not None and praxan_id in self._aspirations:
            asp_state = self._aspirations[praxan_id]
            if not asp_state.get("completed") and not asp_state.get("failed"):
                asp_state["failed"] = True
            # Clean up
            del self._aspirations[praxan_id]
            self._cooldowns.pop(praxan_id, None)

    # ---- Core update loop -------------------------------------------------

    def update(
        self,
        praxans: list,
        faction_manager: Any = None,
        reputation_manager: Any = None,
        event_bus: Any = None,
        current_time: float | None = None,
    ) -> None:
        """Evaluate aspirations for all praxans.  Called on rare-tick."""
        if current_time is None:
            current_time = time.time()

        if current_time - self._last_eval_time < _EVAL_INTERVAL:
            return
        self._last_eval_time = current_time

        eb = event_bus or self._event_bus

        for praxan in praxans:
            if not getattr(praxan, "alive", True):
                continue
            pid = praxan.id

            asp_state = self._aspirations.get(pid)

            if asp_state is not None:
                # Evaluate progress
                self._evaluate_progress(praxan, asp_state, faction_manager,
                                        reputation_manager, praxans, eb, current_time)
            else:
                # Try to assign a new aspiration
                self._try_assign(praxan, faction_manager, reputation_manager,
                                 praxans, eb, current_time)

    def _try_assign(
        self,
        praxan: Any,
        faction_manager: Any,
        reputation_manager: Any,
        all_praxans: list,
        event_bus: Any,
        current_time: float,
    ) -> None:
        """Attempt to assign a new aspiration to a praxan."""
        # Only adults and eligible life stages
        life_stage = getattr(praxan, "life_stage", "adult")
        if life_stage == "infant":
            return

        # Respect cooldown
        cooldown_end = self._cooldowns.get(praxan.id, 0.0)
        if current_time < cooldown_end:
            return

        # Score all aspirations for this praxan
        all_defs = get_all_aspiration_defs()
        if not all_defs:
            return

        # Filter already-completed aspirations (avoid repeats within same life)
        completed_ids = set(getattr(praxan, "_completed_aspirations", []))

        candidates: list[tuple[float, str, dict]] = []
        for asp_id, asp_def in all_defs.items():
            if asp_id in completed_ids:
                continue
            score = _score_aspiration_for_praxan(praxan, asp_def)
            if score <= -900:  # Ineligible
                continue
            candidates.append((score, asp_id, asp_def))

        if not candidates:
            return

        # Weighted random selection (softmax-like: top candidates are more likely)
        candidates.sort(key=lambda c: c[0], reverse=True)
        # Take top 5 and weight by score
        top = candidates[:5]
        min_score = min(c[0] for c in top)
        weights = [max(0.01, c[0] - min_score + 0.1) for c in top]
        chosen_idx = random.choices(range(len(top)), weights=weights, k=1)[0]
        _, asp_id, asp_def = top[chosen_idx]

        # Check that the aspiration isn't already complete (don't assign trivially)
        current, target = check_progress(
            praxan, asp_def,
            faction_manager=faction_manager,
            reputation_manager=reputation_manager,
            all_praxans=all_praxans,
        )
        if target > 0 and current >= target:
            # Already fulfilled — skip this one, try next
            for idx in range(len(top)):
                if idx == chosen_idx:
                    continue
                _, alt_id, alt_def = top[idx]
                if alt_id in completed_ids:
                    continue
                alt_cur, alt_tar = check_progress(
                    praxan, alt_def,
                    faction_manager=faction_manager,
                    reputation_manager=reputation_manager,
                    all_praxans=all_praxans,
                )
                if alt_tar > 0 and alt_cur < alt_tar:
                    asp_id, asp_def = alt_id, alt_def
                    current, target = alt_cur, alt_tar
                    break
            else:
                return  # All top candidates already complete

        # Assign
        progress = current / target if target > 0 else 0.0
        asp_state = {
            "id": asp_id,
            "assigned_time": current_time,
            "progress": round(min(progress, 0.99), 3),
            "milestones_hit": [],
            "completed": False,
            "failed": False,
        }
        self._aspirations[praxan.id] = asp_state

        # Set entity-level field for inspect drawer / snapshot
        praxan.aspiration = {
            "id": asp_id,
            "label": asp_def.get("label", asp_id),
            "progress": asp_state["progress"],
            "assigned_time": current_time,
        }

        # Moodlet: new aspiration feels hopeful
        try:
            praxan.add_moodlet("AspirationAssigned", 2, 120, current_time)
        except Exception:
            pass

        # Episodic memory
        try:
            narrative = asp_def.get("narrative", "{name} set a life goal").replace(
                "{name}", getattr(praxan, "name", f"Praxan {praxan.id}")
            )
            praxan.episodic_memory.record("aspiration_assigned", narrative, timestamp=current_time)
        except Exception:
            pass

        # EventBus
        if event_bus is not None:
            try:
                event_bus.publish(GameEvent(
                    category=CATEGORY_PERSONAL,
                    summary=f"{getattr(praxan, 'name', f'Praxan {praxan.id}')} set aspiration: {asp_def.get('label', asp_id)}",
                    detail=asp_def.get("description", ""),
                    praxan_id=praxan.id,
                    faction_id=getattr(praxan, "faction_id", None),
                    location=(praxan.x, praxan.y) if hasattr(praxan, "x") else None,
                    metadata={"type": "aspiration_assigned", "aspiration_id": asp_id},
                ))
            except Exception:
                pass

    def _evaluate_progress(
        self,
        praxan: Any,
        asp_state: dict,
        faction_manager: Any,
        reputation_manager: Any,
        all_praxans: list,
        event_bus: Any,
        current_time: float,
    ) -> None:
        """Evaluate progress on an active aspiration."""
        asp_id = asp_state["id"]
        asp_def = get_aspiration_def(asp_id)
        if asp_def is None:
            return

        # Check for elder transition — graceful expiry (no penalty)
        life_stage = getattr(praxan, "life_stage", "adult")
        allowed_stages = asp_def.get("life_stages", ["adult"])
        if life_stage not in allowed_stages and life_stage == "elder":
            # Elder graceful expiry — no mood penalty, just cleanup
            self._complete_aspiration(praxan, asp_state, asp_def, event_bus,
                                     current_time, success=False, graceful=True)
            return

        # Compute progress
        current_val, target_val = check_progress(
            praxan, asp_def,
            faction_manager=faction_manager,
            reputation_manager=reputation_manager,
            all_praxans=all_praxans,
        )
        progress = current_val / target_val if target_val > 0 else 0.0
        progress = min(progress, 1.0)
        asp_state["progress"] = round(progress, 3)

        # Update entity-level field
        praxan.aspiration = {
            "id": asp_id,
            "label": asp_def.get("label", asp_id),
            "progress": asp_state["progress"],
            "assigned_time": asp_state["assigned_time"],
        }

        # Check milestones
        milestones_hit = asp_state.get("milestones_hit", [])
        for milestone in _PROGRESS_MILESTONES:
            if progress >= milestone and milestone not in milestones_hit:
                milestones_hit.append(milestone)
                asp_state["milestones_hit"] = milestones_hit
                # Progress moodlet
                try:
                    praxan.add_moodlet("AspirationProgress", 3, 180, current_time)
                except Exception:
                    pass
                # Episodic memory
                try:
                    pct = int(milestone * 100)
                    name = getattr(praxan, "name", f"Praxan {praxan.id}")
                    label = asp_def.get("label", asp_id)
                    praxan.episodic_memory.record(
                        "aspiration_progress",
                        f"{name} is {pct}% toward {label}",
                        timestamp=current_time,
                    )
                except Exception:
                    pass

        # Check completion
        if progress >= 1.0:
            self._complete_aspiration(praxan, asp_state, asp_def, event_bus,
                                     current_time, success=True)

    def _complete_aspiration(
        self,
        praxan: Any,
        asp_state: dict,
        asp_def: dict,
        event_bus: Any,
        current_time: float,
        success: bool = True,
        graceful: bool = False,
    ) -> None:
        """Handle aspiration completion or failure."""
        asp_id = asp_state["id"]
        pid = praxan.id
        name = getattr(praxan, "name", f"Praxan {pid}")
        label = asp_def.get("label", asp_id)

        if success:
            asp_state["completed"] = True

            # Track completed aspirations on the entity to avoid repeats
            if not hasattr(praxan, "_completed_aspirations"):
                praxan._completed_aspirations = []
            praxan._completed_aspirations.append(asp_id)

            # Reward moodlet
            reward = asp_def.get("reward", {})
            mood_id = reward.get("mood", "AspirationAchieved")
            try:
                praxan.add_moodlet(mood_id, 15, 600, current_time)
            except Exception:
                pass

            # Reputation boost
            if not hasattr(praxan, "_pending_reputation_events"):
                praxan._pending_reputation_events = []
            praxan._pending_reputation_events.append("aspiration_achieved")

            # Episodic memory
            try:
                praxan.episodic_memory.record(
                    "aspiration_achieved",
                    f"{name} achieved their aspiration: {label}",
                    timestamp=current_time,
                )
            except Exception:
                pass

            # EventBus
            if event_bus is not None:
                try:
                    event_bus.publish(GameEvent(
                        category=CATEGORY_PERSONAL,
                        summary=f"{name} achieved aspiration: {label}!",
                        detail=asp_def.get("description", ""),
                        praxan_id=pid,
                        faction_id=getattr(praxan, "faction_id", None),
                        location=(praxan.x, praxan.y) if hasattr(praxan, "x") else None,
                        metadata={"type": "aspiration_achieved", "aspiration_id": asp_id},
                    ))
                except Exception:
                    pass

        else:
            asp_state["failed"] = True
            if not graceful:
                # Failure moodlet (only if not graceful elder transition)
                try:
                    praxan.add_moodlet("AspirationFailed", -8, 300, current_time)
                except Exception:
                    pass
                # Reputation penalty
                if not hasattr(praxan, "_pending_reputation_events"):
                    praxan._pending_reputation_events = []
                praxan._pending_reputation_events.append("aspiration_abandoned")

            # Episodic memory
            try:
                if graceful:
                    praxan.episodic_memory.record(
                        "aspiration_failed",
                        f"{name}'s aspiration ({label}) faded with age",
                        timestamp=current_time,
                    )
                else:
                    praxan.episodic_memory.record(
                        "aspiration_failed",
                        f"{name} failed to achieve: {label}",
                        timestamp=current_time,
                    )
            except Exception:
                pass

            # EventBus
            if event_bus is not None:
                try:
                    event_bus.publish(GameEvent(
                        category=CATEGORY_PERSONAL,
                        summary=f"{name} {'outgrew' if graceful else 'failed'} aspiration: {label}",
                        praxan_id=pid,
                        faction_id=getattr(praxan, "faction_id", None),
                        metadata={"type": "aspiration_failed", "aspiration_id": asp_id, "graceful": graceful},
                    ))
                except Exception:
                    pass

        # Clear entity aspiration field
        praxan.aspiration = None

        # Remove from tracking and set cooldown
        self._aspirations.pop(pid, None)
        self._cooldowns[pid] = current_time + _REASSIGNMENT_COOLDOWN

    # ---- Public API -------------------------------------------------------

    def get_aspiration(self, praxan_id: int) -> Optional[dict[str, Any]]:
        """Return current aspiration state for a praxan, or None."""
        return self._aspirations.get(praxan_id)

    def get_aspiration_def_for(self, praxan_id: int) -> Optional[dict[str, Any]]:
        """Return the AspirationDef for a praxan's current aspiration, or None."""
        asp_state = self._aspirations.get(praxan_id)
        if asp_state is None:
            return None
        return get_aspiration_def(asp_state["id"])

    def get_progress(self, praxan_id: int) -> float:
        """Return progress (0.0-1.0) for praxan's current aspiration."""
        asp_state = self._aspirations.get(praxan_id)
        if asp_state is None:
            return 0.0
        return asp_state.get("progress", 0.0)

    def has_aspiration(self, praxan_id: int) -> bool:
        """Return True if praxan has an active aspiration."""
        return praxan_id in self._aspirations

    def force_assign(self, praxan: Any, aspiration_id: str, current_time: float | None = None) -> bool:
        """Force-assign a specific aspiration (for testing / dev mode)."""
        asp_def = get_aspiration_def(aspiration_id)
        if asp_def is None:
            return False
        if current_time is None:
            current_time = time.time()
        asp_state = {
            "id": aspiration_id,
            "assigned_time": current_time,
            "progress": 0.0,
            "milestones_hit": [],
            "completed": False,
            "failed": False,
        }
        self._aspirations[praxan.id] = asp_state
        praxan.aspiration = {
            "id": aspiration_id,
            "label": asp_def.get("label", aspiration_id),
            "progress": 0.0,
            "assigned_time": current_time,
        }
        return True

    def fail_aspiration(self, praxan: Any, current_time: float | None = None, event_bus: Any = None) -> bool:
        """Manually fail a praxan's current aspiration."""
        if current_time is None:
            current_time = time.time()
        asp_state = self._aspirations.get(praxan.id)
        if asp_state is None:
            return False
        asp_def = get_aspiration_def(asp_state["id"]) or {}
        self._complete_aspiration(praxan, asp_state, asp_def, event_bus, current_time, success=False)
        return True

    # ---- Serialization ----------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        """Serialize for snapshot."""
        return {
            "aspirations": {
                str(pid): {
                    "id": asp.get("id"),
                    "assigned_time": asp.get("assigned_time", 0.0),
                    "progress": asp.get("progress", 0.0),
                    "milestones_hit": list(asp.get("milestones_hit", [])),
                    "completed": asp.get("completed", False),
                    "failed": asp.get("failed", False),
                }
                for pid, asp in self._aspirations.items()
            },
            "cooldowns": {
                str(pid): cd for pid, cd in self._cooldowns.items()
            },
        }

    def restore(self, data: dict[str, Any], now: float | None = None) -> None:
        """Restore from snapshot data."""
        if now is None:
            now = time.time()
        self._aspirations.clear()
        self._cooldowns.clear()

        aspirations = data.get("aspirations", {})
        for pid_str, asp_data in aspirations.items():
            try:
                pid = int(pid_str)
                self._aspirations[pid] = {
                    "id": str(asp_data.get("id", "")),
                    "assigned_time": float(asp_data.get("assigned_time", now)),
                    "progress": max(0.0, min(1.0, float(asp_data.get("progress", 0.0)))),
                    "milestones_hit": list(asp_data.get("milestones_hit", [])),
                    "completed": bool(asp_data.get("completed", False)),
                    "failed": bool(asp_data.get("failed", False)),
                }
            except (TypeError, ValueError):
                continue

        cooldowns = data.get("cooldowns", {})
        for pid_str, cd_time in cooldowns.items():
            try:
                pid = int(pid_str)
                # Convert relative cooldown to absolute using now
                self._cooldowns[pid] = max(now, float(cd_time))
            except (TypeError, ValueError):
                continue

    def restore_praxan_aspirations(self, praxans: list) -> None:
        """After restore, sync entity-level aspiration fields from manager state."""
        for praxan in praxans:
            pid = praxan.id
            asp_state = self._aspirations.get(pid)
            if asp_state is not None:
                asp_def = get_aspiration_def(asp_state["id"])
                label = asp_def.get("label", asp_state["id"]) if asp_def else asp_state["id"]
                praxan.aspiration = {
                    "id": asp_state["id"],
                    "label": label,
                    "progress": asp_state.get("progress", 0.0),
                    "assigned_time": asp_state.get("assigned_time", 0.0),
                }
            else:
                praxan.aspiration = None
