"""Mentorship & Apprenticeship System.

Experienced Praxans (skill level 3+) take on apprentices, creating persistent
master-apprentice bonds that accelerate skill transfer.  Apprentices gain
boosted XP when near their mentor, and both parties receive moodlets, bond
growth, reputation gains, and episodic memories.

Key mechanics:

- **Matching**: on eval tick, eligible mentor-apprentice pairs are formed based
  on skill levels, personality affinity, faction membership, and capacity.
- **Proximity learning**: when an apprentice is within ``proximity_radius`` of
  their mentor, skill XP gain is multiplied by the def's ``xp_multiplier``.
- **Training sessions**: periodic XP grants (``session_xp`` every
  ``session_interval`` seconds) when in proximity, with bond growth.
- **Graduation**: when the apprentice reaches ``graduation_level`` in the
  mentored skill, both receive mood boosts, reputation gains, and memories.
- **Breakage**: mentorship ends on death, faction change, or elder transition
  of the apprentice.  Grief moodlets apply if the cause is death.
- **Limits**: each mentor can have at most ``max_apprentices_per_mentor``
  active apprenticeships per skill.

Definitions live in ``defs/core/mentorship.json`` (MentorshipDef) and are
loaded via ``DefDatabase``.

Integration:
    - ``MentorshipManager.update()`` called on rare-tick cadence
    - Entity fields: ``praxan.mentorship`` dict (or None)
    - Snapshot: ``serialize()`` / ``restore()``
    - EventBus: publishes CATEGORY_PERSONAL on formation/graduation/breakage
    - Reputation: queues ``graduated_apprentice`` / ``mentorship_session``
    - Episodic memory: records formation, graduation, breakage
    - Traditions: ``scholars_path`` reinforced by mentorship events
"""

from __future__ import annotations

import logging
import math
import random
import time
from typing import Any, Optional

from events.bus import CATEGORY_DEATH, CATEGORY_PERSONAL, GameEvent

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Def cache (lazily loaded from DefDatabase)
# ---------------------------------------------------------------------------

_mentorship_def_cache: dict[str, dict[str, Any]] = {}


def _load_defs() -> None:
    """Populate cache from DefDatabase."""
    global _mentorship_def_cache
    if _mentorship_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        defs = DefDatabase.get_all("MentorshipDef")
        if defs:
            for def_id, def_data in defs.items():
                _mentorship_def_cache[def_id] = def_data
    except Exception:
        pass


def get_mentorship_def(mentorship_id: str) -> Optional[dict[str, Any]]:
    """Return a MentorshipDef by id, or None."""
    _load_defs()
    return _mentorship_def_cache.get(mentorship_id)


def get_all_mentorship_defs() -> dict[str, dict[str, Any]]:
    """Return all known MentorshipDefs."""
    _load_defs()
    return dict(_mentorship_def_cache)


def get_def_for_skill(skill: str) -> Optional[dict[str, Any]]:
    """Return the MentorshipDef for a given skill, or None."""
    _load_defs()
    for mdef in _mentorship_def_cache.values():
        if mdef.get("skill") == skill:
            return mdef
    return None


def clear_cache() -> None:
    """Clear cached defs (for testing)."""
    global _mentorship_def_cache
    _mentorship_def_cache = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _distance(a: Any, b: Any) -> float:
    """Euclidean distance between two entities with x/y attributes."""
    ax = getattr(a, "x", 0.0)
    ay = getattr(a, "y", 0.0)
    bx = getattr(b, "x", 0.0)
    by = getattr(b, "y", 0.0)
    return math.hypot(bx - ax, by - ay)


def _score_pair(mentor: Any, apprentice: Any, mdef: dict) -> float:
    """Score how good a mentor-apprentice match is (higher = better)."""
    personality = getattr(mentor, "personality", {})
    weights = mdef.get("personality_weights", {})
    traits = list(getattr(mentor, "traits", []))

    score = 0.0
    for pkey, weight in weights.items():
        score += personality.get(pkey, 0.5) * weight

    # Trait affinity bonus
    for aff in mdef.get("trait_affinities", []):
        if aff in traits:
            score += 0.3

    # Existing bond bonus — prefer teaching friends/kin
    bond = getattr(mentor, "bonds", {}).get(apprentice.id, 0)
    score += min(bond / 100.0, 0.3)

    # Same faction bonus
    if getattr(mentor, "faction_id", None) == getattr(apprentice, "faction_id", None):
        score += 0.4

    # Small jitter
    score += random.uniform(0.0, 0.1)
    return score


# ---------------------------------------------------------------------------
# MentorshipManager
# ---------------------------------------------------------------------------

# How often (seconds) the manager evaluates mentorships
_EVAL_INTERVAL = 30.0

# Cooldown after a mentorship ends before the apprentice can get a new one
_APPRENTICE_COOLDOWN = 45.0

# Maximum active mentorships across the entire colony
_MAX_GLOBAL_MENTORSHIPS = 20


class MentorshipManager:
    """Manages mentor-apprentice relationships across all Praxans.

    Typical lifecycle::

        mgr = MentorshipManager()
        mgr.attach_event_bus(event_bus)
        # On rare tick:
        mgr.update(praxans, faction_manager, reputation_manager,
                    event_bus, current_time)
    """

    def __init__(self) -> None:
        # Active mentorships: {apprentice_id: mentorship_state}
        # mentorship_state: {
        #   mentor_id, apprentice_id, def_id, skill,
        #   started_at, last_session_time, sessions_count, graduated
        # }
        self._active: dict[int, dict[str, Any]] = {}
        # Cooldowns: {apprentice_id: timestamp when cooldown expires}
        self._cooldowns: dict[int, float] = {}
        self._last_eval_time: float = 0.0
        self._event_bus: Any = None

    # ---- EventBus integration ---------------------------------------------

    def attach_event_bus(self, event_bus: Any) -> None:
        """Subscribe to death events for mentorship cleanup."""
        self._event_bus = event_bus
        if event_bus is None:
            return
        try:
            event_bus.subscribe(CATEGORY_DEATH, self._on_death_event)
        except Exception:
            pass

    def _on_death_event(self, event: Any) -> None:
        """Clean up mentorships when a praxan dies."""
        praxan_id = getattr(event, "praxan_id", None)
        if praxan_id is None:
            return
        self._break_mentorship_for(praxan_id, reason="death")

    # ---- Public API -------------------------------------------------------

    def get_mentorship(self, praxan_id: int) -> Optional[dict[str, Any]]:
        """Return the active mentorship for a praxan (as apprentice), or None."""
        return self._active.get(praxan_id)

    def get_mentor_apprentices(self, mentor_id: int) -> list[dict[str, Any]]:
        """Return all active mentorships where *mentor_id* is the mentor."""
        return [m for m in self._active.values() if m.get("mentor_id") == mentor_id]

    def is_mentor(self, praxan_id: int) -> bool:
        """Return True if *praxan_id* is currently mentoring anyone."""
        return any(m.get("mentor_id") == praxan_id for m in self._active.values())

    def is_apprentice(self, praxan_id: int) -> bool:
        """Return True if *praxan_id* is currently an apprentice."""
        return praxan_id in self._active

    def get_xp_multiplier(self, praxan_id: int, skill: str) -> float:
        """Return the XP multiplier for an apprentice in a given skill.

        Returns 1.0 if the praxan is not an apprentice in that skill or
        the multiplier field is not found.
        """
        m = self._active.get(praxan_id)
        if m is None or m.get("skill") != skill:
            return 1.0
        mdef = get_mentorship_def(m.get("def_id", ""))
        if mdef is None:
            return 1.0
        return float(mdef.get("xp_multiplier", 1.0))

    def active_count(self) -> int:
        """Return the number of active mentorships."""
        return len(self._active)

    # ---- Rare-tick update -------------------------------------------------

    def update(
        self,
        praxans: list,
        faction_manager: Any = None,
        reputation_manager: Any = None,
        event_bus: Any = None,
        current_time: float | None = None,
        advisor: Any = None,
        narrative_panel: Any = None,
    ) -> None:
        """Evaluate mentorships: run sessions, check graduations, form new pairs.

        Called on rare-tick cadence (~every 4 seconds).
        """
        now = current_time or time.time()
        bus = event_bus or self._event_bus

        # Build lookup for alive praxans
        alive = {p.id: p for p in praxans if getattr(p, "alive", True)}

        # 1. Run training sessions and check graduations for active mentorships
        ended_ids: list[int] = []
        for app_id, mstate in list(self._active.items()):
            mentor = alive.get(mstate["mentor_id"])
            apprentice = alive.get(app_id)
            if mentor is None or apprentice is None:
                ended_ids.append(app_id)
                continue
            self._run_session(mentor, apprentice, mstate, now, reputation_manager, bus)
            if self._check_graduation(mentor, apprentice, mstate, now, reputation_manager, bus, advisor, narrative_panel):
                ended_ids.append(app_id)

        for app_id in ended_ids:
            if app_id in self._active:
                # If not already graduated, it's a breakage (death/missing)
                mstate = self._active[app_id]
                if not mstate.get("graduated"):
                    self._break_mentorship_for(app_id, reason="missing")
                else:
                    del self._active[app_id]

        # 2. Periodically form new mentorships
        do_eval = (now - self._last_eval_time) >= _EVAL_INTERVAL
        if do_eval:
            self._last_eval_time = now
            self._form_new_mentorships(alive, now, bus, advisor, narrative_panel)

    def _run_session(
        self,
        mentor: Any,
        apprentice: Any,
        mstate: dict,
        now: float,
        reputation_manager: Any,
        event_bus: Any,
    ) -> None:
        """Grant session XP and bond if mentor & apprentice are in proximity."""
        mdef = get_mentorship_def(mstate.get("def_id", ""))
        if mdef is None:
            return

        interval = float(mdef.get("session_interval", 10.0))
        last_session = mstate.get("last_session_time", 0.0)
        if (now - last_session) < interval:
            return

        proximity = float(mdef.get("proximity_radius", 100))
        if _distance(mentor, apprentice) > proximity:
            return

        # Grant session XP to apprentice
        skill = mstate["skill"]
        session_xp = float(mdef.get("session_xp", 15))
        if hasattr(apprentice, "gain_skill_xp"):
            apprentice.gain_skill_xp(skill, session_xp)

        # Bond growth
        bond_delta = int(mdef.get("bond_per_session", 2))
        mentor_bonds = getattr(mentor, "bonds", {})
        mentor_bonds[apprentice.id] = min(100, mentor_bonds.get(apprentice.id, 0) + bond_delta)
        app_bonds = getattr(apprentice, "bonds", {})
        app_bonds[mentor.id] = min(100, app_bonds.get(mentor.id, 0) + bond_delta)

        # Moodlets
        mentor_mood = float(mdef.get("mentor_mood_offset", 3))
        apprentice_mood = float(mdef.get("apprentice_mood_offset", 4))
        if hasattr(mentor, "add_moodlet"):
            mentor.add_moodlet("TeachingApprentice", mentor_mood, 120, now)
        if hasattr(apprentice, "add_moodlet"):
            apprentice.add_moodlet("LearningFromMentor", apprentice_mood, 120, now)

        # Reputation for mentor
        if reputation_manager is not None:
            reputation_manager.record_event(mentor.id, "mentorship_session")

        mstate["last_session_time"] = now
        mstate["sessions_count"] = mstate.get("sessions_count", 0) + 1

    def _check_graduation(
        self,
        mentor: Any,
        apprentice: Any,
        mstate: dict,
        now: float,
        reputation_manager: Any,
        event_bus: Any,
        advisor: Any = None,
        narrative_panel: Any = None,
    ) -> bool:
        """Check if apprentice has reached graduation level. Returns True if graduated."""
        mdef = get_mentorship_def(mstate.get("def_id", ""))
        if mdef is None:
            return False

        skill = mstate["skill"]
        grad_level = int(mdef.get("graduation_level", 3))
        skill_data = getattr(apprentice, "skills", {}).get(skill, {})
        current_level = skill_data.get("level", 1) if isinstance(skill_data, dict) else 1

        if current_level < grad_level:
            return False

        # Graduate!
        mstate["graduated"] = True
        grad_mood = float(mdef.get("graduation_mood_offset", 10))

        # Moodlets
        if hasattr(apprentice, "add_moodlet"):
            apprentice.add_moodlet("ApprenticeGraduated", grad_mood, 180, now)
        if hasattr(mentor, "add_moodlet"):
            mentor.add_moodlet("MentorProud", grad_mood * 0.8, 180, now)

        # Reputation
        if reputation_manager is not None:
            reputation_manager.record_event(mentor.id, "graduated_apprentice")

        # Episodic memory
        if hasattr(apprentice, "episodic_memory") and apprentice.episodic_memory is not None:
            apprentice.episodic_memory.record(
                "mentorship_graduated",
                f"Graduated as {mdef.get('label', skill)} under {getattr(mentor, 'name', 'mentor')}",
                now,
                getattr(apprentice, "personality", {}),
            )
        if hasattr(mentor, "episodic_memory") and mentor.episodic_memory is not None:
            mentor.episodic_memory.record(
                "mentored_graduate",
                f"Trained {getattr(apprentice, 'name', 'apprentice')} as {mdef.get('label', skill)}",
                now,
                getattr(mentor, "personality", {}),
            )

        # Update relationship type
        if hasattr(mentor, "relationships"):
            mentor.relationships[apprentice.id] = "former_mentor"
        if hasattr(apprentice, "relationships"):
            apprentice.relationships[mentor.id] = "former_apprentice"

        # EventBus
        if event_bus is not None:
            try:
                event_bus.publish(GameEvent(
                    category=CATEGORY_PERSONAL,
                    summary=f"{getattr(apprentice, 'name', 'Apprentice')} graduated from {mdef.get('label', skill)} mentorship",
                    detail=f"Mentor: {getattr(mentor, 'name', 'Unknown')} | Skill: {skill} | Sessions: {mstate.get('sessions_count', 0)}",
                    location=(apprentice.x, apprentice.y),
                    praxan_id=apprentice.id,
                    faction_id=getattr(apprentice, "faction_id", None),
                    metadata={
                        "type": "mentorship_graduated",
                        "mentor_id": mentor.id,
                        "apprentice_id": apprentice.id,
                        "skill": skill,
                        "def_id": mstate.get("def_id"),
                    },
                ))
            except Exception:
                pass

        # Narrative panel
        if narrative_panel is not None:
            try:
                narrative_panel.add_message(
                    f"{getattr(apprentice, 'name', 'Apprentice')} graduated as {mdef.get('label', skill)}!",
                    "Achievement",
                )
            except Exception:
                pass

        # Observer timeline
        if advisor is not None:
            timeline = getattr(advisor, "observer_timeline", None)
            if isinstance(timeline, list):
                timeline.append({
                    "time": now,
                    "event": "mentorship_graduated",
                    "detail": f"{getattr(apprentice, 'name', '?')} graduated under {getattr(mentor, 'name', '?')} ({skill})",
                })

        _logger.info(
            "Mentorship graduated: %s (skill=%s, mentor=%s, apprentice=%s, sessions=%d)",
            mdef.get("id"), skill, mentor.id, apprentice.id, mstate.get("sessions_count", 0),
        )
        return True

    def _form_new_mentorships(
        self,
        alive: dict[int, Any],
        now: float,
        event_bus: Any,
        advisor: Any = None,
        narrative_panel: Any = None,
    ) -> None:
        """Try to form new mentor-apprentice pairs."""
        if len(self._active) >= _MAX_GLOBAL_MENTORSHIPS:
            return

        _load_defs()
        if not _mentorship_def_cache:
            return

        # Identify current mentors/apprentices to avoid double-assignment
        current_apprentice_ids = set(self._active.keys())
        current_mentor_ids: set[int] = set()
        current_mentor_counts: dict[int, int] = {}
        for m in self._active.values():
            mid = m["mentor_id"]
            current_mentor_ids.add(mid)
            current_mentor_counts[mid] = current_mentor_counts.get(mid, 0) + 1

        for def_id, mdef in _mentorship_def_cache.items():
            skill = mdef.get("skill", "")
            mentor_min = int(mdef.get("mentor_min_level", 3))
            apprentice_max = int(mdef.get("apprentice_max_level", 2))
            max_per_mentor = int(mdef.get("max_apprentices_per_mentor", 2))
            allowed_stages = mdef.get("life_stages", ["adult", "elder"])

            # Find eligible mentors (exclude current apprentices to avoid dual-role)
            mentors = []
            for p in alive.values():
                if p.id in current_apprentice_ids:
                    continue
                if getattr(p, "life_stage", "adult") not in allowed_stages:
                    continue
                skill_data = getattr(p, "skills", {}).get(skill, {})
                level = skill_data.get("level", 1) if isinstance(skill_data, dict) else 1
                if level >= mentor_min:
                    # Check capacity
                    current = current_mentor_counts.get(p.id, 0)
                    if current < max_per_mentor:
                        mentors.append(p)

            # Find eligible apprentices (exclude current mentors/apprentices)
            apprentices = []
            for p in alive.values():
                if p.id in current_apprentice_ids or p.id in current_mentor_ids:
                    continue
                # Check cooldown
                if self._cooldowns.get(p.id, 0.0) > now:
                    continue
                stage = getattr(p, "life_stage", "adult")
                if stage not in ("youth", "adult"):
                    continue
                skill_data = getattr(p, "skills", {}).get(skill, {})
                level = skill_data.get("level", 1) if isinstance(skill_data, dict) else 1
                if level <= apprentice_max:
                    apprentices.append(p)

            if not mentors or not apprentices:
                continue

            # Score all viable pairs and pick the best
            candidates: list[tuple[float, Any, Any]] = []
            for mentor in mentors:
                for apprentice in apprentices:
                    # Must be same faction
                    if getattr(mentor, "faction_id", None) != getattr(apprentice, "faction_id", None):
                        continue
                    score = _score_pair(mentor, apprentice, mdef)
                    candidates.append((score, mentor, apprentice))

            if not candidates:
                continue

            # Sort by score descending, form top pair(s)
            candidates.sort(key=lambda c: c[0], reverse=True)
            formed = 0
            max_to_form = max(1, len(mentors))  # At most one per mentor this cycle

            for score, mentor, apprentice in candidates:
                if formed >= max_to_form:
                    break
                if len(self._active) >= _MAX_GLOBAL_MENTORSHIPS:
                    break
                if apprentice.id in current_apprentice_ids:
                    continue
                if mentor.id in current_apprentice_ids:
                    continue
                # Re-check mentor capacity
                mc = current_mentor_counts.get(mentor.id, 0)
                if mc >= max_per_mentor:
                    continue

                self._form_mentorship(mentor, apprentice, def_id, mdef, now, event_bus, advisor, narrative_panel)
                current_apprentice_ids.add(apprentice.id)
                current_mentor_ids.add(mentor.id)
                current_mentor_counts[mentor.id] = mc + 1
                formed += 1

    def _form_mentorship(
        self,
        mentor: Any,
        apprentice: Any,
        def_id: str,
        mdef: dict,
        now: float,
        event_bus: Any,
        advisor: Any = None,
        narrative_panel: Any = None,
    ) -> None:
        """Create a new mentorship between mentor and apprentice."""
        skill = mdef.get("skill", "")
        mstate = {
            "mentor_id": mentor.id,
            "apprentice_id": apprentice.id,
            "def_id": def_id,
            "skill": skill,
            "started_at": now,
            "last_session_time": now,
            "sessions_count": 0,
            "graduated": False,
        }
        self._active[apprentice.id] = mstate

        # Set relationship
        if hasattr(mentor, "relationships"):
            mentor.relationships[apprentice.id] = "mentor"
        if hasattr(apprentice, "relationships"):
            apprentice.relationships[mentor.id] = "apprentice"

        # Sync to praxan entity field
        if hasattr(apprentice, "mentorship"):
            apprentice.mentorship = {
                "mentor_id": mentor.id,
                "skill": skill,
                "def_id": def_id,
            }

        # Moodlets
        if hasattr(mentor, "add_moodlet"):
            mentor.add_moodlet("MentorshipFormed", 4, 90, now)
        if hasattr(apprentice, "add_moodlet"):
            apprentice.add_moodlet("MentorshipFormed", 4, 90, now)

        # Episodic memory
        if hasattr(apprentice, "episodic_memory") and apprentice.episodic_memory is not None:
            apprentice.episodic_memory.record(
                "mentorship_began",
                f"Began learning {skill} from {getattr(mentor, 'name', 'mentor')}",
                now,
                getattr(apprentice, "personality", {}),
            )
        if hasattr(mentor, "episodic_memory") and mentor.episodic_memory is not None:
            mentor.episodic_memory.record(
                "mentorship_began",
                f"Began teaching {skill} to {getattr(apprentice, 'name', 'apprentice')}",
                now,
                getattr(mentor, "personality", {}),
            )

        # EventBus
        if event_bus is not None:
            try:
                event_bus.publish(GameEvent(
                    category=CATEGORY_PERSONAL,
                    summary=f"{getattr(mentor, 'name', 'Mentor')} begins teaching {skill} to {getattr(apprentice, 'name', 'Apprentice')}",
                    detail=f"Mentorship: {mdef.get('label', def_id)}",
                    location=(mentor.x, mentor.y),
                    praxan_id=apprentice.id,
                    faction_id=getattr(apprentice, "faction_id", None),
                    metadata={
                        "type": "mentorship_formed",
                        "mentor_id": mentor.id,
                        "apprentice_id": apprentice.id,
                        "skill": skill,
                        "def_id": def_id,
                    },
                ))
            except Exception:
                pass

        # Narrative panel
        if narrative_panel is not None:
            try:
                narrative_panel.add_message(
                    f"{getattr(mentor, 'name', 'Mentor')} takes {getattr(apprentice, 'name', 'Apprentice')} as {mdef.get('label', skill)}",
                    "Social",
                )
            except Exception:
                pass

        # Observer timeline
        if advisor is not None:
            timeline = getattr(advisor, "observer_timeline", None)
            if isinstance(timeline, list):
                timeline.append({
                    "time": now,
                    "event": "mentorship_formed",
                    "detail": f"{getattr(mentor, 'name', '?')} → {getattr(apprentice, 'name', '?')} ({skill})",
                })

        _logger.info(
            "Mentorship formed: %s (skill=%s, mentor=%s, apprentice=%s)",
            def_id, skill, mentor.id, apprentice.id,
        )

    def _break_mentorship_for(self, praxan_id: int, reason: str = "unknown") -> None:
        """End all mentorships involving *praxan_id* (as mentor or apprentice)."""
        now = time.time()

        # As apprentice
        if praxan_id in self._active:
            mstate = self._active.pop(praxan_id)
            self._cooldowns[praxan_id] = now + _APPRENTICE_COOLDOWN
            _logger.info(
                "Mentorship broken (apprentice=%s, mentor=%s, reason=%s)",
                praxan_id, mstate.get("mentor_id"), reason,
            )

        # As mentor — break all apprenticeships under this mentor
        to_remove = [
            app_id for app_id, m in self._active.items()
            if m.get("mentor_id") == praxan_id
        ]
        for app_id in to_remove:
            mstate = self._active.pop(app_id)
            self._cooldowns[app_id] = now + _APPRENTICE_COOLDOWN
            _logger.info(
                "Mentorship broken (mentor=%s died/left, apprentice=%s, reason=%s)",
                praxan_id, app_id, reason,
            )

    def break_mentorship(self, apprentice_id: int, reason: str = "manual") -> None:
        """Public API to break a specific mentorship by apprentice ID."""
        if apprentice_id in self._active:
            self._break_mentorship_for(apprentice_id, reason=reason)

    # ---- Proximity XP boost query -----------------------------------------

    def is_near_mentor(self, praxan_id: int, praxans_by_id: dict[int, Any]) -> bool:
        """Return True if apprentice is within proximity of their mentor."""
        m = self._active.get(praxan_id)
        if m is None:
            return False
        mentor = praxans_by_id.get(m["mentor_id"])
        apprentice = praxans_by_id.get(praxan_id)
        if mentor is None or apprentice is None:
            return False
        mdef = get_mentorship_def(m.get("def_id", ""))
        radius = float(mdef.get("proximity_radius", 100)) if mdef else 100.0
        return _distance(mentor, apprentice) <= radius

    # ---- Serialization ----------------------------------------------------

    def serialize(self, current_time: float | None = None) -> dict[str, Any]:
        """Serialize state for snapshot."""
        now = current_time or time.time()
        return {
            "active": {
                str(app_id): {
                    "mentor_id": m["mentor_id"],
                    "apprentice_id": m["apprentice_id"],
                    "def_id": m["def_id"],
                    "skill": m["skill"],
                    "elapsed": round(now - m.get("started_at", now), 3),
                    "since_last_session": round(now - m.get("last_session_time", now), 3),
                    "sessions_count": m.get("sessions_count", 0),
                    "graduated": m.get("graduated", False),
                }
                for app_id, m in self._active.items()
            },
            "cooldowns": {
                str(pid): round(max(0.0, ts - now), 3)
                for pid, ts in self._cooldowns.items()
                if ts > now
            },
            "last_eval_elapsed": round(now - self._last_eval_time, 3),
        }

    def restore(self, data: dict[str, Any], current_time: float | None = None) -> None:
        """Restore state from snapshot."""
        now = current_time or time.time()
        self._active.clear()
        self._cooldowns.clear()

        for app_id_str, mdata in data.get("active", {}).items():
            try:
                app_id = int(app_id_str)
            except (TypeError, ValueError):
                continue
            elapsed = float(mdata.get("elapsed", 0.0))
            since_session = float(mdata.get("since_last_session", 0.0))
            self._active[app_id] = {
                "mentor_id": int(mdata["mentor_id"]),
                "apprentice_id": app_id,
                "def_id": str(mdata.get("def_id", "")),
                "skill": str(mdata.get("skill", "")),
                "started_at": now - elapsed,
                "last_session_time": now - since_session,
                "sessions_count": int(mdata.get("sessions_count", 0)),
                "graduated": bool(mdata.get("graduated", False)),
            }

        for pid_str, remaining in data.get("cooldowns", {}).items():
            try:
                pid = int(pid_str)
                self._cooldowns[pid] = now + max(0.0, float(remaining))
            except (TypeError, ValueError):
                continue

        last_eval_elapsed = float(data.get("last_eval_elapsed", _EVAL_INTERVAL))
        self._last_eval_time = now - last_eval_elapsed

    def restore_praxan_mentorships(self, praxans: list) -> None:
        """Sync mentorship state back to praxan entity fields after restore."""
        praxan_map = {p.id: p for p in praxans}
        for app_id, mstate in self._active.items():
            apprentice = praxan_map.get(app_id)
            if apprentice is not None and hasattr(apprentice, "mentorship"):
                apprentice.mentorship = {
                    "mentor_id": mstate["mentor_id"],
                    "skill": mstate["skill"],
                    "def_id": mstate["def_id"],
                }
            # Set relationship types
            mentor = praxan_map.get(mstate["mentor_id"])
            if mentor is not None and hasattr(mentor, "relationships"):
                mentor.relationships[app_id] = "mentor"
            if apprentice is not None and hasattr(apprentice, "relationships"):
                apprentice.relationships[mstate["mentor_id"]] = "apprentice"

    # ---- Queries ----------------------------------------------------------

    def get_all_active(self) -> dict[int, dict[str, Any]]:
        """Return all active mentorships."""
        return dict(self._active)

    def get_stats(self) -> dict[str, Any]:
        """Return summary stats for HUD/analytics."""
        skills: dict[str, int] = {}
        for m in self._active.values():
            sk = m.get("skill", "unknown")
            skills[sk] = skills.get(sk, 0) + 1
        return {
            "active_count": len(self._active),
            "by_skill": skills,
        }
