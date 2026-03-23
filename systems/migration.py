"""Individual Migration & Faction Defection System.

Praxans evaluate their satisfaction with their current faction and, under
certain conditions, defect to a more appealing one.  Unlike the existing
spatial migration (which moves the whole faction), this system handles
**individual** faction-switching driven by personal push/pull factors.

Key mechanics:

- **Push factors**: unhappiness, low cohesion, outcast reputation, warfare,
  disease, family separation, doctrine mismatch — these accumulate a
  *discontent* score.
- **Pull factors**: high cohesion in target, friendly diplomacy, family or
  friends present, matching doctrine — these accumulate an *attraction* score
  for each candidate faction.
- **Defection**: when discontent exceeds threshold *and* a target faction's
  attraction exceeds its threshold, the praxan switches faction.
- **Consequences**: reputation shifts, moodlets, cohesion changes, diplomacy
  penalties, episodic memories, EventBus events.

5 MigrationDef types in ``defs/core/migration.json``:
  discontent_defection, war_refugee, plague_flight, family_reunion,
  ideological_exile.

Integration:
    - ``MigrationManager.update()`` called on rare-tick cadence
    - Subscribes to EventBus for warfare/death/disaster signals
    - Snapshot: ``serialize()`` / ``restore()``
    - Publishes CATEGORY_MIGRATION events
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from events.bus import (
    CATEGORY_DEATH,
    CATEGORY_DISASTER,
    CATEGORY_MIGRATION,
    CATEGORY_WARFARE,
    GameEvent,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Def cache
# ---------------------------------------------------------------------------

_migration_def_cache: dict[str, dict[str, Any]] = {}


def _load_defs() -> None:
    global _migration_def_cache
    if _migration_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        defs = DefDatabase.get_all("MigrationDef")
        if defs:
            for def_id, def_data in defs.items():
                _migration_def_cache[def_id] = def_data
    except Exception:
        pass


def get_migration_def(migration_id: str) -> Optional[dict[str, Any]]:
    _load_defs()
    return _migration_def_cache.get(migration_id)


def get_all_migration_defs() -> dict[str, dict[str, Any]]:
    _load_defs()
    return dict(_migration_def_cache)


def clear_cache() -> None:
    _migration_def_cache.clear()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVAL_INTERVAL = 30.0  # seconds between evaluations
PER_FACTION_COOLDOWN = 120.0  # min seconds between defections from same faction
MAX_DEFECTIONS_PER_EVAL = 2  # prevent mass exodus in a single tick
MIN_FACTION_SIZE = 3  # factions below this size don't lose members
LEADER_IMMUNE = True  # faction leaders never defect


# ---------------------------------------------------------------------------
# MigrationManager
# ---------------------------------------------------------------------------

class MigrationManager:
    """Evaluates individual praxan satisfaction and handles faction defection."""

    def __init__(self) -> None:
        self._last_eval: float = 0.0
        # faction_id -> last time someone defected FROM this faction
        self._faction_cooldowns: dict[int, float] = {}

        # Recent warfare/death/epidemic signals per faction
        self._recent_warfare: dict[int, list[float]] = {}  # faction_id -> [timestamps]
        self._recent_deaths: dict[int, list[float]] = {}
        self._active_epidemics: set[int] = set()  # faction_ids with active epidemics

        # Stats
        self.total_defections: int = 0
        self.defection_history: list[dict[str, Any]] = []
        self._max_history = 30

        # System refs
        self._event_bus = None
        self._diplomacy_manager = None

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_systems(self, diplomacy_manager=None) -> None:
        self._diplomacy_manager = diplomacy_manager

    def attach_event_bus(self, event_bus) -> None:
        if event_bus is None:
            return
        self._event_bus = event_bus
        event_bus.subscribe(CATEGORY_WARFARE, self._on_warfare)
        event_bus.subscribe(CATEGORY_DEATH, self._on_death)
        event_bus.subscribe(CATEGORY_DISASTER, self._on_disaster)

    def _on_warfare(self, event: GameEvent) -> None:
        meta = event.metadata or {}
        for key in ("attacker_faction_id", "defender_faction_id"):
            fid = meta.get(key)
            if fid is not None:
                self._recent_warfare.setdefault(fid, []).append(event.timestamp)

    def _on_death(self, event: GameEvent) -> None:
        if event.faction_id is not None:
            self._recent_deaths.setdefault(event.faction_id, []).append(event.timestamp)

    def _on_disaster(self, event: GameEvent) -> None:
        meta = event.metadata or {}
        if meta.get("type") == "epidemic":
            if event.faction_id is not None:
                self._active_epidemics.add(event.faction_id)
        elif meta.get("type") == "epidemic_ended":
            self._active_epidemics.discard(event.faction_id)

    # ------------------------------------------------------------------
    # Main update
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
        reputation_manager=None,
        disease_manager=None,
    ) -> None:
        """Evaluate migration candidates and execute defections.

        Called on rare-tick cadence from the main game loop.
        """
        if current_time is None:
            current_time = time.time()

        if current_time - self._last_eval < EVAL_INTERVAL:
            return
        self._last_eval = current_time

        _load_defs()
        if not _migration_def_cache:
            return

        if diplomacy_manager is not None:
            self._diplomacy_manager = diplomacy_manager

        if faction_manager is None or praxans is None:
            return

        factions = getattr(faction_manager, "factions", {})
        if len(factions) < 2:
            return  # need at least 2 factions for migration

        # Prune old signals (keep last 5 minutes)
        cutoff = current_time - 300.0
        for fid in list(self._recent_warfare):
            self._recent_warfare[fid] = [t for t in self._recent_warfare[fid] if t > cutoff]
            if not self._recent_warfare[fid]:
                del self._recent_warfare[fid]
        for fid in list(self._recent_deaths):
            self._recent_deaths[fid] = [t for t in self._recent_deaths[fid] if t > cutoff]
            if not self._recent_deaths[fid]:
                del self._recent_deaths[fid]

        # Check active epidemics from disease_manager if provided
        if disease_manager is not None:
            try:
                active = set()
                for fid in factions:
                    faction = factions[fid]
                    members = faction.get_members(praxans) if hasattr(faction, 'get_members') else []
                    for member in members:
                        diseases = getattr(disease_manager, 'get_active_diseases', lambda pid: [])(member.id)
                        if diseases:
                            active.add(fid)
                            break
                self._active_epidemics = active
            except Exception:
                pass

        # Build praxan lookup
        praxan_map = {p.id: p for p in praxans}

        # Evaluate candidates
        defections_this_eval = 0
        for fid, faction in list(factions.items()):
            if defections_this_eval >= MAX_DEFECTIONS_PER_EVAL:
                break

            if len(faction.member_ids) <= MIN_FACTION_SIZE:
                continue

            # Per-faction cooldown
            last_defection = self._faction_cooldowns.get(fid, 0.0)
            if current_time - last_defection < PER_FACTION_COOLDOWN:
                continue

            # Evaluate each member
            for pid in list(faction.member_ids):
                if defections_this_eval >= MAX_DEFECTIONS_PER_EVAL:
                    break

                praxan = praxan_map.get(pid)
                if praxan is None:
                    continue
                if not getattr(praxan, "alive", True):
                    continue
                if getattr(praxan, "life_stage", "adult") in ("infant", "youth"):
                    continue
                if LEADER_IMMUNE and pid == faction.leader_id:
                    continue
                if getattr(praxan, "health", 100.0) < 20.0:
                    continue  # too weak to migrate

                # Evaluate push/pull for each migration type
                best_result = self._evaluate_migration(
                    praxan, faction, fid, factions, praxan_map,
                    current_time, reputation_manager,
                )

                if best_result is not None:
                    mdef, target_fid, target_faction = best_result
                    self._execute_defection(
                        praxan, faction, fid,
                        target_faction, target_fid,
                        mdef, current_time, praxans,
                        narrative_panel, advisor, reputation_manager,
                    )
                    defections_this_eval += 1
                    self._faction_cooldowns[fid] = current_time
                    break  # one defection per source faction per eval

    # ------------------------------------------------------------------
    # Push / Pull evaluation
    # ------------------------------------------------------------------

    def _evaluate_migration(
        self,
        praxan,
        source_faction,
        source_fid: int,
        factions: dict,
        praxan_map: dict,
        now: float,
        reputation_manager=None,
    ) -> Optional[tuple]:
        """Evaluate all migration types; return (mdef, target_fid, target_faction) or None."""

        best_score = 0.0
        best_result = None

        for mdef_id, mdef in _migration_def_cache.items():
            discontent = self._calc_discontent(
                praxan, source_faction, source_fid, mdef, now,
                praxan_map, reputation_manager,
            )

            disc_threshold = mdef.get("discontent_threshold", 5.0)
            if discontent < disc_threshold:
                continue

            # Find best target faction
            attr_threshold = mdef.get("attraction_threshold", 4.0)
            for tfid, tfaction in factions.items():
                if tfid == source_fid:
                    continue

                attraction = self._calc_attraction(
                    praxan, tfaction, tfid, source_fid, mdef,
                    praxan_map,
                )

                if attraction < attr_threshold:
                    continue

                combined = discontent + attraction
                if combined > best_score:
                    best_score = combined
                    best_result = (mdef, tfid, tfaction)

        return best_result

    def _calc_discontent(
        self,
        praxan,
        faction,
        faction_id: int,
        mdef: dict[str, Any],
        now: float,
        praxan_map: dict,
        reputation_manager=None,
    ) -> float:
        """Calculate push-factor discontent score."""
        score = 0.0
        push = mdef.get("push_factors", {})

        # Low happiness
        if "low_happiness" in push:
            threshold = push["low_happiness"].get("threshold", 40)
            weight = push["low_happiness"].get("weight", 1.0)
            happiness = getattr(praxan, "happiness", 70.0)
            if happiness < threshold:
                score += weight * (1.0 - happiness / threshold)

        # Low cohesion
        if "low_cohesion" in push:
            threshold = push["low_cohesion"].get("threshold", 30)
            weight = push["low_cohesion"].get("weight", 1.0)
            cohesion = getattr(faction, "cohesion", 50.0)
            if cohesion < threshold:
                score += weight * (1.0 - cohesion / threshold)

        # Outcast reputation
        if "outcast_reputation" in push and reputation_manager is not None:
            threshold = push["outcast_reputation"].get("threshold", 25)
            weight = push["outcast_reputation"].get("weight", 1.0)
            try:
                rep = reputation_manager.get_reputation(praxan.id)
                if rep < threshold:
                    score += weight * (1.0 - rep / threshold)
            except Exception:
                pass

        # No friends in faction
        if "no_friends" in push:
            weight = push["no_friends"].get("weight", 1.0)
            relationships = getattr(praxan, "relationships", {})
            friends_in_faction = sum(
                1 for rid, rtype in relationships.items()
                if rtype == "friend" and rid in set(faction.member_ids)
            )
            if friends_in_faction == 0:
                score += weight

        # Many rivals in faction
        if "many_rivals" in push:
            threshold = push["many_rivals"].get("threshold", 2)
            weight = push["many_rivals"].get("weight", 1.0)
            relationships = getattr(praxan, "relationships", {})
            rivals_in_faction = sum(
                1 for rid, rtype in relationships.items()
                if rtype == "rival" and rid in set(faction.member_ids)
            )
            if rivals_in_faction >= threshold:
                score += weight * (rivals_in_faction / threshold)

        # Recent warfare loss
        if "recent_warfare_loss" in push:
            weight = push["recent_warfare_loss"].get("weight", 2.0)
            warfare_count = len(self._recent_warfare.get(faction_id, []))
            if warfare_count > 0:
                score += weight * min(2.0, warfare_count / 2.0)

        # Low health
        if "low_health" in push:
            threshold = push["low_health"].get("threshold", 50)
            weight = push["low_health"].get("weight", 1.0)
            health = getattr(praxan, "health", 100.0)
            if health < threshold:
                score += weight * (1.0 - health / threshold)

        # Comrades fallen (recent deaths in faction)
        if "comrades_fallen" in push:
            weight = push["comrades_fallen"].get("weight", 2.0)
            death_count = len(self._recent_deaths.get(faction_id, []))
            if death_count > 0:
                score += weight * min(2.0, death_count / 2.0)

        # Active epidemic
        if "active_epidemic" in push:
            weight = push["active_epidemic"].get("weight", 3.0)
            if faction_id in self._active_epidemics:
                score += weight

        # Faction deaths recent
        if "faction_deaths_recent" in push:
            threshold = push["faction_deaths_recent"].get("threshold", 2)
            weight = push["faction_deaths_recent"].get("weight", 2.0)
            death_count = len(self._recent_deaths.get(faction_id, []))
            if death_count >= threshold:
                score += weight

        # Family in other faction
        if "family_in_other_faction" in push:
            weight = push["family_in_other_faction"].get("weight", 3.0)
            relationships = getattr(praxan, "relationships", {})
            family_elsewhere = any(
                rtype in ("partner", "parent", "child")
                and rid in praxan_map
                and getattr(praxan_map[rid], "faction_id", None) != faction_id
                for rid, rtype in relationships.items()
            )
            if family_elsewhere:
                score += weight

        # Doctrine mismatch
        if "doctrine_mismatch" in push:
            weight = push["doctrine_mismatch"].get("weight", 2.0)
            mismatch = self._doctrine_mismatch_score(praxan, faction)
            score += weight * mismatch

        return score

    def _calc_attraction(
        self,
        praxan,
        target_faction,
        target_fid: int,
        source_fid: int,
        mdef: dict[str, Any],
        praxan_map: dict,
    ) -> float:
        """Calculate pull-factor attraction score for a target faction."""
        score = 0.0
        pull = mdef.get("pull_factors", {})

        # High cohesion
        if "high_cohesion" in pull:
            threshold = pull["high_cohesion"].get("threshold", 55)
            weight = pull["high_cohesion"].get("weight", 1.0)
            cohesion = getattr(target_faction, "cohesion", 50.0)
            if cohesion >= threshold:
                score += weight * (cohesion / 100.0)

        # Friendly standing
        if "friendly_standing" in pull and self._diplomacy_manager is not None:
            threshold = pull["friendly_standing"].get("threshold", 0)
            weight = pull["friendly_standing"].get("weight", 1.5)
            try:
                standing = self._diplomacy_manager.get_standing(source_fid, target_fid)
                if standing >= threshold:
                    score += weight * min(1.5, (standing - threshold) / 40.0)
            except Exception:
                pass

        # Family present in target
        if "family_present" in pull:
            weight = pull["family_present"].get("weight", 3.0)
            relationships = getattr(praxan, "relationships", {})
            target_members = set(target_faction.member_ids)
            family_there = sum(
                1 for rid, rtype in relationships.items()
                if rtype in ("partner", "parent", "child") and rid in target_members
            )
            if family_there > 0:
                score += weight * min(2.0, family_there)

        # Friends present in target
        if "friends_present" in pull:
            weight = pull["friends_present"].get("weight", 2.0)
            relationships = getattr(praxan, "relationships", {})
            target_members = set(target_faction.member_ids)
            friends_there = sum(
                1 for rid, rtype in relationships.items()
                if rtype == "friend" and rid in target_members
            )
            if friends_there > 0:
                score += weight * min(2.0, friends_there)

        # Doctrine match
        if "doctrine_match" in pull:
            weight = pull["doctrine_match"].get("weight", 1.5)
            match = 1.0 - self._doctrine_mismatch_score(praxan, target_faction)
            score += weight * match

        # No active warfare
        if "no_active_warfare" in pull:
            weight = pull["no_active_warfare"].get("weight", 2.0)
            if len(self._recent_warfare.get(target_fid, [])) == 0:
                score += weight

        # No epidemic
        if "no_epidemic" in pull:
            weight = pull["no_epidemic"].get("weight", 3.0)
            if target_fid not in self._active_epidemics:
                score += weight

        return score

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _doctrine_mismatch_score(praxan, faction) -> float:
        """0.0 = perfect match, 1.0 = total mismatch.

        Compare praxan personality traits with faction doctrine focus.
        """
        doctrine = getattr(faction, "primary_doctrine", "growth")
        # Map doctrine to personality traits that align
        affinity_map = {
            "growth": ("sociability",),
            "security": ("bravery", "diligence"),
            "industry": ("diligence",),
            "exploration": ("curiosity",),
            "harmony": ("sociability", "curiosity"),
        }
        desired_traits = affinity_map.get(doctrine, ())
        if not desired_traits:
            return 0.0

        personality = getattr(praxan, "personality", {})
        if not personality:
            return 0.5

        # Average alignment of matching personality traits (0-1 each)
        total = 0.0
        for trait in desired_traits:
            total += personality.get(trait, 0.5)
        avg = total / len(desired_traits)

        # High personality value = good match, return mismatch
        return max(0.0, min(1.0, 1.0 - avg))

    # ------------------------------------------------------------------
    # Execute defection
    # ------------------------------------------------------------------

    def _execute_defection(
        self,
        praxan,
        source_faction,
        source_fid: int,
        target_faction,
        target_fid: int,
        mdef: dict[str, Any],
        now: float,
        praxans: list,
        narrative_panel=None,
        advisor=None,
        reputation_manager=None,
    ) -> None:
        """Move a praxan from source to target faction and apply consequences."""
        pid = praxan.id
        mdef_id = mdef.get("id", "unknown")
        mdef_name = mdef.get("name", mdef_id)

        # 1. Faction membership transfer
        source_faction.remove_member(pid)
        target_faction.add_member(pid)
        praxan.faction_id = target_fid

        # 2. Moodlets
        try:
            # Defector: anxiety/relief moodlet
            defector_mood = mdef.get("moodlet_defector", "DefectorAnxiety")
            praxan.add_moodlet(defector_mood, -5, 180, now)

            # Source faction: loss moodlet
            source_mood = mdef.get("moodlet_source_faction", "MemberDefected")
            for mid in source_faction.member_ids:
                member = next((p for p in praxans if p.id == mid), None)
                if member is not None:
                    member.add_moodlet(source_mood, -4, 120, now)

            # Target faction: welcome moodlet
            target_mood = mdef.get("moodlet_target_faction", "NewcomerArrival")
            for mid in target_faction.member_ids:
                if mid == pid:
                    continue
                member = next((p for p in praxans if p.id == mid), None)
                if member is not None:
                    member.add_moodlet(target_mood, 3, 120, now)
        except Exception:
            pass

        # 3. Reputation
        if reputation_manager is not None:
            try:
                rep_loss = mdef.get("reputation_loss_defector", -3)
                if rep_loss:
                    if not hasattr(praxan, '_pending_reputation_events'):
                        praxan._pending_reputation_events = []
                    praxan._pending_reputation_events.append("defected_faction")
            except Exception:
                pass

        # 4. Cohesion impacts
        try:
            cohesion_loss = mdef.get("cohesion_loss_source", -2.0)
            source_faction.cohesion = max(0.0, source_faction.cohesion + cohesion_loss)

            cohesion_gain = mdef.get("cohesion_gain_target", 1.0)
            target_faction.cohesion = min(100.0, target_faction.cohesion + cohesion_gain)
        except Exception:
            pass

        # 5. Diplomacy penalty
        if self._diplomacy_manager is not None:
            try:
                penalty = mdef.get("diplomacy_penalty", -3)
                if penalty:
                    self._diplomacy_manager.adjust_standing(source_fid, target_fid, penalty)
            except Exception:
                pass

        # 6. Episodic memory
        try:
            memory = getattr(praxan, "memory", None)
            if memory is not None:
                memory_text = mdef.get("memory_text_defector", "I left my people")
                memory.record(
                    category="migration",
                    summary=memory_text,
                    timestamp=now,
                    metadata={"from_faction": source_fid, "to_faction": target_fid},
                )
        except Exception:
            pass

        # 7. EventBus
        if self._event_bus is not None:
            try:
                praxan_name = getattr(praxan, "name", f"Praxan {pid}")
                self._event_bus.publish(GameEvent(
                    category=CATEGORY_MIGRATION,
                    summary=f"{praxan_name} defected ({mdef_name})",
                    faction_id=target_fid,
                    praxan_id=pid,
                    timestamp=now,
                    metadata={
                        "type": "individual_defection",
                        "migration_type": mdef_id,
                        "source_faction_id": source_fid,
                        "target_faction_id": target_fid,
                        "praxan_name": praxan_name,
                    },
                ))
            except Exception:
                pass

        # 8. Narrative panel
        if narrative_panel is not None:
            try:
                praxan_name = getattr(praxan, "name", f"Praxan {pid}")
                narrative_panel.add_message(
                    f"{praxan_name} defected: {mdef_name}",
                    "Migration",
                )
            except Exception:
                pass

        # 9. Observer timeline
        if advisor is not None:
            try:
                tl = getattr(advisor, "observer_timeline", None)
                if tl is not None:
                    praxan_name = getattr(praxan, "name", f"Praxan {pid}")
                    tl.append({
                        "time": now,
                        "category": "migration",
                        "summary": f"{praxan_name} defected from faction {source_fid} "
                                   f"to faction {target_fid} ({mdef_name})",
                    })
                    if len(tl) > 50:
                        del tl[:-50]
            except Exception:
                pass

        # 10. Stats & history
        self.total_defections += 1
        record = {
            "type": mdef_id,
            "praxan_id": pid,
            "source_faction_id": source_fid,
            "target_faction_id": target_fid,
            "time": now,
        }
        self.defection_history.append(record)
        if len(self.defection_history) > self._max_history:
            self.defection_history = self.defection_history[-self._max_history:]

        _logger.info(
            "Praxan %d defected from faction %d to %d (%s)",
            pid, source_fid, target_fid, mdef_id,
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_recent_defections(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent defection history entries."""
        return list(self.defection_history[-limit:])

    def get_faction_defection_count(self, faction_id: int) -> int:
        """Count defections from a specific faction."""
        return sum(
            1 for r in self.defection_history
            if r.get("source_faction_id") == faction_id
        )

    def get_faction_immigration_count(self, faction_id: int) -> int:
        """Count immigrations into a specific faction."""
        return sum(
            1 for r in self.defection_history
            if r.get("target_faction_id") == faction_id
        )

    # ------------------------------------------------------------------
    # Snapshot serialization
    # ------------------------------------------------------------------

    def serialize(self, current_time: float | None = None) -> dict[str, Any]:
        if current_time is None:
            current_time = time.time()
        return {
            "last_eval_elapsed": round(max(0.0, current_time - self._last_eval), 2),
            "faction_cooldowns": {
                str(fid): round(max(0.0, current_time - t), 2)
                for fid, t in self._faction_cooldowns.items()
            },
            "total_defections": self.total_defections,
            "history": list(self.defection_history[-self._max_history:]),
            "active_epidemics": list(self._active_epidemics),
        }

    def restore(self, data: dict[str, Any], current_time: float | None = None) -> None:
        if current_time is None:
            current_time = time.time()

        self._last_eval = current_time - float(data.get("last_eval_elapsed", 0.0))
        self._faction_cooldowns.clear()
        for fid_str, elapsed in data.get("faction_cooldowns", {}).items():
            try:
                self._faction_cooldowns[int(fid_str)] = current_time - float(elapsed)
            except (ValueError, TypeError):
                pass

        self.total_defections = int(data.get("total_defections", 0))
        self.defection_history = list(data.get("history", []))[-self._max_history:]
        self._active_epidemics = set(data.get("active_epidemics", []))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def remove_faction(self, faction_id: int) -> None:
        """Clean up when a faction is disbanded."""
        self._faction_cooldowns.pop(faction_id, None)
        self._recent_warfare.pop(faction_id, None)
        self._recent_deaths.pop(faction_id, None)
        self._active_epidemics.discard(faction_id)
