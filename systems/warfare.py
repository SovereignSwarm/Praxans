"""Warfare & Raiding System — Inter-faction armed conflict.

When diplomatic relations fall to Hostile (standing < -60), factions may
launch raids against each other.  The WarfareManager evaluates raid
opportunities on a long-tick cadence, selects combatants, resolves
round-by-round combat, and applies consequences: loot, building damage,
moodlets, reputation, episodic memory, diplomacy shifts, and EventBus
events.

Raid types (defined in ``defs/core/warfare.json``):
    - **Pillage Raid**: steal food/wood/stone
    - **Border Skirmish**: short armed clash, no loot, reputation stakes
    - **Sabotage Mission**: covert team damages buildings
    - **Conquest Assault**: full-scale attack, heavy loot, can absorb defeated

Combat resolution:
    Each round, every combatant rolls an attack based on weapon damage,
    combat skill, personality (bravery factor from genetics), and equipment.
    Defenders get a fortification bonus if near buildings.  Damage is applied
    via ``praxan.take_damage()``.  A side loses when all combatants are
    downed or flee (morale check each round).

Integration:
    - ``WarfareManager.update()`` called on long-tick cadence (~every 33s)
    - Reads diplomacy standings to find hostile pairs
    - Publishes CATEGORY_WARFARE events to EventBus
    - Records reputation events (defended_colony, fled_battle, raid_kill, etc.)
    - Applies moodlets to combatants and witnesses
    - Records episodic memories for participants
    - Shifts diplomacy standing post-raid
    - Serialized in run snapshots for save/load
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("Warfare")

# ---------------------------------------------------------------------------
# Def cache (lazily loaded from DefDatabase)
# ---------------------------------------------------------------------------

_raid_def_cache: dict[str, dict[str, Any]] = {}


def _load_defs() -> None:
    global _raid_def_cache
    if _raid_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        raid_defs = DefDatabase.get_all("RaidDef")
        if raid_defs:
            for def_id, def_data in raid_defs.items():
                _raid_def_cache[def_id] = def_data
    except Exception:
        pass


def get_raid_def(raid_id: str) -> Optional[dict[str, Any]]:
    _load_defs()
    return _raid_def_cache.get(raid_id)


def get_all_raid_defs() -> dict[str, dict[str, Any]]:
    _load_defs()
    return dict(_raid_def_cache)


def clear_cache() -> None:
    global _raid_def_cache
    _raid_def_cache = {}


# ---------------------------------------------------------------------------
# Combat Helpers
# ---------------------------------------------------------------------------

def _combat_power(praxan: Any) -> float:
    """Compute a combatant's fighting power from skills, equipment, health."""
    # Base: combat-adjacent skill levels
    skill_bonus = 0.0
    skills = getattr(praxan, "skills", {})
    for sk in ("crafting", "building", "gathering"):
        sd = skills.get(sk)
        if sd and isinstance(sd, dict):
            skill_bonus += float(sd.get("level", 1)) * 0.5

    # Weapon bonus
    weapon = (getattr(praxan, "equipment", {}) or {}).get("weapon")
    weapon_dmg = 5.0  # unarmed base
    if weapon and isinstance(weapon, dict):
        weapon_dmg = float(weapon.get("damage", 5))

    # Health factor (0..1)
    health_pct = max(0.0, min(1.0, float(getattr(praxan, "health", 100.0)) / 100.0))

    # Bravery from genetics (0..1 scale, default 0.5)
    genetics = getattr(praxan, "genetics", {}) or {}
    bravery = float(genetics.get("aggression", genetics.get("bravery", 0.5)))

    # Capacity modifiers (moving/manipulation affect fighting)
    capacities = getattr(praxan, "capacities", {}) or {}
    move_cap = float(capacities.get("moving", 1.0))
    manip_cap = float(capacities.get("manipulation", 1.0))

    power = (weapon_dmg + skill_bonus) * health_pct * (0.5 + 0.5 * bravery) * move_cap * manip_cap
    return max(0.1, power)


def _morale_check(praxan: Any, casualties_ratio: float) -> bool:
    """Return True if praxan holds morale (stays in fight).

    casualties_ratio: fraction of own side that is downed (0..1).
    """
    genetics = getattr(praxan, "genetics", {}) or {}
    bravery = float(genetics.get("aggression", genetics.get("bravery", 0.5)))
    happiness = float(getattr(praxan, "happiness", 50.0)) / 100.0

    # Higher bravery + happiness = more likely to hold
    threshold = 0.3 + (bravery * 0.3) + (happiness * 0.2)
    # Casualties push toward fleeing
    flee_pressure = casualties_ratio * 0.8

    return random.random() < (threshold - flee_pressure)


def _fortification_bonus(praxan: Any, buildings: list) -> float:
    """Defenders near buildings get a damage reduction bonus."""
    px, py = float(getattr(praxan, "x", 0)), float(getattr(praxan, "y", 0))
    for b in buildings:
        bx, by = float(getattr(b, "x", 0)), float(getattr(b, "y", 0))
        dist = math.sqrt((px - bx) ** 2 + (py - by) ** 2)
        if dist < 80:
            return 0.7  # 30% damage reduction
    return 1.0


# ---------------------------------------------------------------------------
# ActiveRaid — represents an ongoing raid
# ---------------------------------------------------------------------------

@dataclass
class ActiveRaid:
    """A raid currently in progress."""
    raid_id: str  # unique per instance
    raid_def_id: str
    attacker_faction_id: int
    defender_faction_id: int
    attacker_ids: list[int] = field(default_factory=list)
    defender_ids: list[int] = field(default_factory=list)
    started_at: float = 0.0
    ends_at: float = 0.0
    current_round: int = 0
    max_rounds: int = 4
    resolved: bool = False
    outcome: str = ""  # "attacker_victory", "defender_victory", "draw"
    casualties_attacker: list[int] = field(default_factory=list)
    casualties_defender: list[int] = field(default_factory=list)
    fled_attacker: list[int] = field(default_factory=list)
    fled_defender: list[int] = field(default_factory=list)
    loot_taken: dict[str, int] = field(default_factory=dict)
    buildings_damaged: int = 0
    combat_log: list[str] = field(default_factory=list)

    def serialize(self, current_time: float) -> dict[str, Any]:
        return {
            "raid_id": self.raid_id,
            "raid_def_id": self.raid_def_id,
            "attacker_faction_id": self.attacker_faction_id,
            "defender_faction_id": self.defender_faction_id,
            "attacker_ids": list(self.attacker_ids),
            "defender_ids": list(self.defender_ids),
            "remaining_seconds": max(0.0, self.ends_at - current_time),
            "current_round": self.current_round,
            "max_rounds": self.max_rounds,
            "resolved": self.resolved,
            "outcome": self.outcome,
            "casualties_attacker": list(self.casualties_attacker),
            "casualties_defender": list(self.casualties_defender),
            "fled_attacker": list(self.fled_attacker),
            "fled_defender": list(self.fled_defender),
            "loot_taken": dict(self.loot_taken),
            "buildings_damaged": self.buildings_damaged,
        }


# ---------------------------------------------------------------------------
# WarfareManager
# ---------------------------------------------------------------------------

_RAID_COUNTER = 0

class WarfareManager:
    """Evaluates and resolves inter-faction armed conflicts.

    Lifecycle::

        mgr = WarfareManager()
        mgr.attach_event_bus(event_bus)
        # On long tick:
        mgr.update(praxans, buildings, faction_manager, diplomacy_manager,
                    reputation_manager, current_time)
    """

    EVAL_INTERVAL = 30.0        # seconds between raid opportunity checks
    RAID_COOLDOWN = 90.0        # min seconds between raids for same pair
    RAID_CHANCE_BASE = 0.15     # base probability per hostile pair per eval
    POST_RAID_STANDING_SHIFT = -8.0   # standing penalty after a raid

    def __init__(self) -> None:
        self.active_raids: list[ActiveRaid] = []
        self.raid_history: list[dict[str, Any]] = []  # capped at 20
        self._last_eval_time: float = 0.0
        self._pair_cooldowns: dict[tuple[int, int], float] = {}  # (fid_a, fid_b) -> last raid end time
        self._event_bus: Any = None

    def attach_event_bus(self, event_bus: Any) -> None:
        self._event_bus = event_bus

    # ---- Main update ---------------------------------------------------------

    def update(
        self,
        praxans: list,
        buildings: list,
        faction_manager: Any = None,
        diplomacy_manager: Any = None,
        reputation_manager: Any = None,
        current_time: float | None = None,
        advisor: Any = None,
    ) -> None:
        """Run warfare evaluation and combat resolution."""
        now = current_time or time.time()

        # 1. Resolve ongoing raids
        for raid in self.active_raids:
            if not raid.resolved:
                self._resolve_raid_tick(raid, praxans, buildings, faction_manager,
                                        diplomacy_manager, reputation_manager, now, advisor)

        # Clean up resolved raids
        newly_resolved = [r for r in self.active_raids if r.resolved]
        for raid in newly_resolved:
            self._archive_raid(raid, now)
        self.active_raids = [r for r in self.active_raids if not r.resolved]

        # 2. Check for new raid opportunities
        if now - self._last_eval_time < self.EVAL_INTERVAL:
            return
        self._last_eval_time = now

        if faction_manager is None or diplomacy_manager is None:
            return

        factions = getattr(faction_manager, "factions", {})
        if not isinstance(factions, dict):
            return
        faction_ids = list(factions.keys())
        if len(faction_ids) < 2:
            return

        # Find hostile pairs
        for i, fid_a in enumerate(faction_ids):
            for fid_b in faction_ids[i + 1:]:
                rel = diplomacy_manager.get_relation(fid_a, fid_b)
                if rel.standing > -40:
                    continue  # not hostile enough

                # Check cooldown
                pair_key = (min(fid_a, fid_b), max(fid_a, fid_b))
                last_raid = self._pair_cooldowns.get(pair_key, 0.0)
                if now - last_raid < self.RAID_COOLDOWN:
                    continue

                # Skip if already raiding
                if any(r.attacker_faction_id in (fid_a, fid_b) and
                       r.defender_faction_id in (fid_a, fid_b) and
                       not r.resolved for r in self.active_raids):
                    continue

                # NAP treaty blocks raids
                if rel.has_treaty("non_aggression_pact") or rel.has_treaty("alliance"):
                    continue

                # Roll for raid
                standing_factor = max(0.0, (-rel.standing - 40) / 60.0)  # 0 at -40, 1 at -100
                chance = self.RAID_CHANCE_BASE * (0.5 + standing_factor)
                if random.random() < chance:
                    self._initiate_raid(fid_a, fid_b, rel.standing, factions,
                                        praxans, now)

    # ---- Raid initiation -----------------------------------------------------

    def _initiate_raid(
        self,
        fid_a: int,
        fid_b: int,
        standing: float,
        factions: dict,
        praxans: list,
        current_time: float,
    ) -> Optional[ActiveRaid]:
        """Pick a raid type and form attack/defense parties."""
        _load_defs()
        if not _raid_def_cache:
            return None

        faction_a = factions.get(fid_a)
        faction_b = factions.get(fid_b)
        if faction_a is None or faction_b is None:
            return None

        # Determine attacker (faction with higher aggression doctrine, or random)
        a_aggression = self._faction_aggression(faction_a)
        b_aggression = self._faction_aggression(faction_b)
        if a_aggression > b_aggression:
            attacker_faction, defender_faction = faction_a, faction_b
            att_id, def_id = fid_a, fid_b
        elif b_aggression > a_aggression:
            attacker_faction, defender_faction = faction_b, faction_a
            att_id, def_id = fid_b, fid_a
        else:
            if random.random() < 0.5:
                attacker_faction, defender_faction = faction_a, faction_b
                att_id, def_id = fid_a, fid_b
            else:
                attacker_faction, defender_faction = faction_b, faction_a
                att_id, def_id = fid_b, fid_a

        # Select raid type based on standing and doctrine
        raid_def = self._select_raid_type(standing, attacker_faction, praxans)
        if raid_def is None:
            return None

        # Select combatants
        attacker_ids = self._select_combatants(
            attacker_faction, praxans,
            raid_def.get("min_attackers", 1),
            raid_def.get("max_attacker_ratio", 0.5),
        )
        if not attacker_ids:
            return None

        defender_ids = self._select_defenders(defender_faction, praxans)
        if not defender_ids:
            return None

        # Create the raid
        global _RAID_COUNTER
        _RAID_COUNTER += 1
        raid = ActiveRaid(
            raid_id=f"raid_{_RAID_COUNTER}",
            raid_def_id=raid_def["id"],
            attacker_faction_id=att_id,
            defender_faction_id=def_id,
            attacker_ids=attacker_ids,
            defender_ids=defender_ids,
            started_at=current_time,
            ends_at=current_time + raid_def.get("duration_seconds", 25),
            current_round=0,
            max_rounds=raid_def.get("combat_rounds", 4),
        )
        self.active_raids.append(raid)

        # Publish raid start event
        self._publish_event(
            current_time,
            f"{raid_def.get('label', 'Raid')}: F{att_id} attacks F{def_id}",
            f"{raid_def.get('description', '')} Attackers: {len(attacker_ids)}, Defenders: {len(defender_ids)}.",
            faction_id=att_id,
            metadata={
                "raid_id": raid.raid_id,
                "raid_type": raid_def["id"],
                "attacker_faction": att_id,
                "defender_faction": def_id,
                "attacker_count": len(attacker_ids),
                "defender_count": len(defender_ids),
                "phase": "started",
            },
        )

        logger.info("Raid started: %s — F%d (%d) attacks F%d (%d)",
                     raid_def["id"], att_id, len(attacker_ids), def_id, len(defender_ids))
        return raid

    def _faction_aggression(self, faction: Any) -> float:
        """How aggressive a faction's doctrine is."""
        doctrine = getattr(faction, "primary_doctrine", "growth")
        aggression_map = {
            "security": 1.5, "industry": 0.8, "exploration": 1.0,
            "growth": 0.4, "harmony": 0.1,
        }
        return aggression_map.get(doctrine, 0.5)

    def _select_raid_type(
        self,
        standing: float,
        attacker_faction: Any,
        praxans: list,
    ) -> Optional[dict[str, Any]]:
        """Pick a raid def weighted by doctrine and standing."""
        _load_defs()
        doctrine = getattr(attacker_faction, "primary_doctrine", "growth")
        member_count = len(getattr(attacker_faction, "member_ids", []))

        candidates = []
        weights = []
        for rd in _raid_def_cache.values():
            threshold = rd.get("standing_threshold", -60)
            if standing > threshold:
                continue  # relations not bad enough for this raid type
            min_att = rd.get("min_attackers", 1)
            if member_count < min_att:
                continue  # not enough members
            w = rd.get("doctrine_weight", {}).get(doctrine, 0.5)
            candidates.append(rd)
            weights.append(max(0.01, w))

        if not candidates:
            return None
        return random.choices(candidates, weights=weights, k=1)[0]

    def _select_combatants(
        self,
        faction: Any,
        praxans: list,
        min_count: int,
        max_ratio: float,
    ) -> list[int]:
        """Select faction members for the raiding party."""
        member_ids = set(getattr(faction, "member_ids", []))
        eligible = [
            p for p in praxans
            if p.id in member_ids
            and getattr(p, "alive", True)
            and getattr(p, "life_stage", "adult") in ("adult", "elder")
            and not getattr(p, "downed", False)
            and float(getattr(p, "health", 100.0)) > 30.0
        ]
        if len(eligible) < min_count:
            return []

        max_count = max(min_count, int(len(eligible) * max_ratio))
        count = random.randint(min_count, max_count)
        count = min(count, len(eligible))

        # Sort by combat power and pick top + some random
        eligible.sort(key=lambda p: _combat_power(p), reverse=True)
        # Take top half deterministically, rest random
        half = max(1, count // 2)
        selected = eligible[:half]
        remaining = eligible[half:]
        if remaining and count > half:
            selected += random.sample(remaining, min(count - half, len(remaining)))

        return [p.id for p in selected]

    def _select_defenders(self, faction: Any, praxans: list) -> list[int]:
        """All able-bodied adult members defend."""
        member_ids = set(getattr(faction, "member_ids", []))
        return [
            p.id for p in praxans
            if p.id in member_ids
            and getattr(p, "alive", True)
            and getattr(p, "life_stage", "adult") in ("adult", "elder")
            and not getattr(p, "downed", False)
            and float(getattr(p, "health", 100.0)) > 20.0
        ]

    # ---- Combat resolution ---------------------------------------------------

    def _resolve_raid_tick(
        self,
        raid: ActiveRaid,
        praxans: list,
        buildings: list,
        faction_manager: Any,
        diplomacy_manager: Any,
        reputation_manager: Any,
        current_time: float,
        advisor: Any = None,
    ) -> None:
        """Advance one combat round of an active raid."""
        raid_def = get_raid_def(raid.raid_def_id) or {}

        # Time-based round advancement
        total_duration = raid_def.get("duration_seconds", 25)
        if total_duration <= 0:
            total_duration = 25
        round_duration = total_duration / max(1, raid.max_rounds)
        expected_round = min(
            raid.max_rounds,
            int((current_time - raid.started_at) / round_duration) + 1,
        )

        if expected_round <= raid.current_round:
            # Not time for next round yet; check if raid timed out
            if current_time >= raid.ends_at:
                self._finalize_raid(raid, praxans, buildings, faction_manager,
                                    diplomacy_manager, reputation_manager, current_time, advisor)
            return

        # Build combatant lists (alive, not fled)
        praxan_map = {p.id: p for p in praxans}
        attackers = [
            praxan_map[pid] for pid in raid.attacker_ids
            if pid in praxan_map
            and getattr(praxan_map[pid], "alive", True)
            and not getattr(praxan_map[pid], "downed", False)
            and pid not in raid.fled_attacker
        ]
        defenders = [
            praxan_map[pid] for pid in raid.defender_ids
            if pid in praxan_map
            and getattr(praxan_map[pid], "alive", True)
            and not getattr(praxan_map[pid], "downed", False)
            and pid not in raid.fled_defender
        ]

        if not attackers or not defenders:
            self._finalize_raid(raid, praxans, buildings, faction_manager,
                                diplomacy_manager, reputation_manager, current_time, advisor)
            return

        # --- Run one combat round ---
        raid.current_round = expected_round

        # Attackers hit defenders
        for attacker in attackers:
            if not defenders:
                break
            target = random.choice(defenders)
            damage = _combat_power(attacker) * random.uniform(0.5, 1.5)
            # Defenders near buildings get fortification
            damage *= _fortification_bonus(target, buildings)
            target.take_damage(damage, "raid", current_time)
            if not getattr(target, "alive", True) or getattr(target, "downed", False):
                if target.id not in raid.casualties_defender:
                    raid.casualties_defender.append(target.id)
                    raid.combat_log.append(f"R{raid.current_round}: {getattr(attacker, 'name', attacker.id)} downed {getattr(target, 'name', target.id)}")
                defenders = [d for d in defenders if getattr(d, "alive", True) and not getattr(d, "downed", False)]

        # Defenders hit attackers
        for defender in defenders:
            if not attackers:
                break
            target = random.choice(attackers)
            damage = _combat_power(defender) * random.uniform(0.4, 1.3)
            target.take_damage(damage, "raid", current_time)
            if not getattr(target, "alive", True) or getattr(target, "downed", False):
                if target.id not in raid.casualties_attacker:
                    raid.casualties_attacker.append(target.id)
                    raid.combat_log.append(f"R{raid.current_round}: {getattr(defender, 'name', defender.id)} downed {getattr(target, 'name', target.id)}")
                attackers = [a for a in attackers if getattr(a, "alive", True) and not getattr(a, "downed", False)]

        # Morale checks
        att_casualties_ratio = len(raid.casualties_attacker) / max(1, len(raid.attacker_ids))
        def_casualties_ratio = len(raid.casualties_defender) / max(1, len(raid.defender_ids))

        for attacker in list(attackers):
            if not _morale_check(attacker, att_casualties_ratio):
                raid.fled_attacker.append(attacker.id)
                raid.combat_log.append(f"R{raid.current_round}: {getattr(attacker, 'name', attacker.id)} fled!")
                attackers.remove(attacker)

        for defender in list(defenders):
            if not _morale_check(defender, def_casualties_ratio):
                raid.fled_defender.append(defender.id)
                raid.combat_log.append(f"R{raid.current_round}: {getattr(defender, 'name', defender.id)} broke and ran!")
                defenders.remove(defender)

        # Check if one side is eliminated
        if not attackers or not defenders or raid.current_round >= raid.max_rounds:
            self._finalize_raid(raid, praxans, buildings, faction_manager,
                                diplomacy_manager, reputation_manager, current_time, advisor)

    def _finalize_raid(
        self,
        raid: ActiveRaid,
        praxans: list,
        buildings: list,
        faction_manager: Any,
        diplomacy_manager: Any,
        reputation_manager: Any,
        current_time: float,
        advisor: Any = None,
    ) -> None:
        """Determine outcome and apply all consequences."""
        if raid.resolved:
            return
        raid.resolved = True

        raid_def = get_raid_def(raid.raid_def_id) or {}
        praxan_map = {p.id: p for p in praxans}

        # Determine outcome
        att_standing = len([
            pid for pid in raid.attacker_ids
            if pid not in raid.casualties_attacker and pid not in raid.fled_attacker
        ])
        def_standing = len([
            pid for pid in raid.defender_ids
            if pid not in raid.casualties_defender and pid not in raid.fled_defender
        ])

        if att_standing > def_standing:
            raid.outcome = "attacker_victory"
        elif def_standing > att_standing:
            raid.outcome = "defender_victory"
        else:
            # Tie-breaker: fewer casualties wins
            if len(raid.casualties_attacker) < len(raid.casualties_defender):
                raid.outcome = "attacker_victory"
            elif len(raid.casualties_defender) < len(raid.casualties_attacker):
                raid.outcome = "defender_victory"
            else:
                raid.outcome = "draw"

        # --- Apply consequences ---

        # 1. Loot (attacker victory only)
        if raid.outcome == "attacker_victory":
            loot_types = raid_def.get("loot_types", [])
            loot_ratio = raid_def.get("loot_ratio", 0.0)
            if loot_types and loot_ratio > 0:
                raid.loot_taken = self._apply_loot(
                    raid, praxan_map, buildings, loot_types, loot_ratio,
                    raid.defender_faction_id, faction_manager,
                )

            # Building damage
            bld_dmg_chance = raid_def.get("building_damage_chance", 0.0)
            if bld_dmg_chance > 0:
                raid.buildings_damaged = self._apply_building_damage(
                    buildings, raid.defender_faction_id, faction_manager, bld_dmg_chance,
                )

        # Sabotage: building damage regardless of outcome (but less if defenders won)
        if raid_def.get("raid_type") == "sabotage":
            bld_chance = raid_def.get("building_damage_chance", 0.3)
            if raid.outcome == "defender_victory":
                bld_chance *= 0.3
            raid.buildings_damaged += self._apply_building_damage(
                buildings, raid.defender_faction_id, faction_manager, bld_chance,
            )

        # 2. Moodlets
        self._apply_moodlets(raid, raid_def, praxan_map, current_time)

        # 3. Reputation events
        self._apply_reputation(raid, reputation_manager, praxan_map, current_time)

        # 4. Episodic memories
        self._apply_memories(raid, raid_def, praxan_map, current_time)

        # 5. Diplomacy shift
        if diplomacy_manager is not None:
            pair_key = (min(raid.attacker_faction_id, raid.defender_faction_id),
                        max(raid.attacker_faction_id, raid.defender_faction_id))
            rel = diplomacy_manager.get_relation(pair_key[0], pair_key[1])
            rel.shift_standing(self.POST_RAID_STANDING_SHIFT, current_time)
            rel.record_incident(
                "raid_" + raid.raid_def_id,
                f"Raid: {raid_def.get('label', 'Unknown')}",
                self.POST_RAID_STANDING_SHIFT,
                current_time,
            )
            self._pair_cooldowns[pair_key] = current_time

        # 6. Publish outcome event
        outcome_label = {
            "attacker_victory": "Attackers won",
            "defender_victory": "Defenders held",
            "draw": "Inconclusive",
        }.get(raid.outcome, "Unknown")

        casualties_total = len(raid.casualties_attacker) + len(raid.casualties_defender)
        self._publish_event(
            current_time,
            f"{raid_def.get('label', 'Raid')} resolved: {outcome_label}",
            (f"F{raid.attacker_faction_id} vs F{raid.defender_faction_id}. "
             f"Casualties: {casualties_total}. Loot: {sum(raid.loot_taken.values())} items. "
             f"Buildings damaged: {raid.buildings_damaged}."),
            faction_id=raid.attacker_faction_id,
            metadata={
                "raid_id": raid.raid_id,
                "raid_type": raid.raid_def_id,
                "outcome": raid.outcome,
                "attacker_faction": raid.attacker_faction_id,
                "defender_faction": raid.defender_faction_id,
                "casualties_attacker": len(raid.casualties_attacker),
                "casualties_defender": len(raid.casualties_defender),
                "loot": dict(raid.loot_taken),
                "buildings_damaged": raid.buildings_damaged,
                "phase": "resolved",
            },
        )

        # 7. Observer timeline
        if advisor is not None:
            try:
                timeline = getattr(advisor, "observer_timeline", None)
                if timeline is not None:
                    timeline.append({
                        "time": current_time,
                        "category": "warfare",
                        "summary": f"{raid_def.get('label', 'Raid')}: F{raid.attacker_faction_id} vs F{raid.defender_faction_id} — {outcome_label}",
                        "details": f"Casualties: {casualties_total}. Loot: {sum(raid.loot_taken.values())}. Buildings damaged: {raid.buildings_damaged}.",
                    })
                    if len(timeline) > 32:
                        del timeline[:-32]
            except Exception:
                pass

        logger.info("Raid resolved: %s — %s. Casualties: att=%d, def=%d",
                     raid.raid_id, raid.outcome,
                     len(raid.casualties_attacker), len(raid.casualties_defender))

    # ---- Consequence helpers -------------------------------------------------

    def _apply_loot(
        self,
        raid: ActiveRaid,
        praxan_map: dict[int, Any],
        buildings: list,
        loot_types: list[str],
        loot_ratio: float,
        defender_faction_id: int,
        faction_manager: Any,
    ) -> dict[str, int]:
        """Transfer resources from defender buildings to attacker inventories."""
        loot = {}
        defender_member_ids = set()
        if faction_manager is not None:
            factions = getattr(faction_manager, "factions", {})
            def_faction = factions.get(defender_faction_id)
            if def_faction:
                defender_member_ids = set(getattr(def_faction, "member_ids", []))

        # Loot from buildings belonging to defender faction members
        for b in buildings:
            owner_id = getattr(b, "owner_id", None)
            if owner_id is not None and owner_id not in defender_member_ids:
                continue
            stored = getattr(b, "stored_resources", None)
            if not isinstance(stored, dict):
                continue
            for res_type in loot_types:
                amount = stored.get(res_type, 0)
                if amount > 0:
                    take = max(1, int(amount * loot_ratio))
                    stored[res_type] = max(0, stored[res_type] - take)
                    loot[res_type] = loot.get(res_type, 0) + take

        # Distribute loot to surviving attackers
        surviving = [
            praxan_map[pid] for pid in raid.attacker_ids
            if pid in praxan_map
            and getattr(praxan_map[pid], "alive", True)
            and pid not in raid.casualties_attacker
        ]
        if surviving and loot:
            for res_type, total in loot.items():
                per_person = max(1, total // len(surviving))
                for attacker in surviving:
                    inv = getattr(attacker, "inventory", {})
                    inv[res_type] = inv.get(res_type, 0) + per_person

        return loot

    def _apply_building_damage(
        self,
        buildings: list,
        defender_faction_id: int,
        faction_manager: Any,
        damage_chance: float,
    ) -> int:
        """Damage random defender buildings."""
        defender_member_ids = set()
        if faction_manager is not None:
            factions = getattr(faction_manager, "factions", {})
            def_faction = factions.get(defender_faction_id)
            if def_faction:
                defender_member_ids = set(getattr(def_faction, "member_ids", []))

        damaged = 0
        for b in buildings:
            owner_id = getattr(b, "owner_id", None)
            if owner_id is not None and owner_id not in defender_member_ids:
                continue
            if random.random() < damage_chance:
                hp = getattr(b, "health", 100)
                dmg = random.uniform(15, 40)
                b.health = max(0, hp - dmg)
                damaged += 1
        return damaged

    def _apply_moodlets(
        self,
        raid: ActiveRaid,
        raid_def: dict,
        praxan_map: dict[int, Any],
        current_time: float,
    ) -> None:
        """Apply victory/defeat/witness moodlets."""
        winner_moodlet = None
        loser_moodlet = None

        if raid.outcome == "attacker_victory":
            winner_moodlet = raid_def.get("attacker_moodlet", "RaidVictory")
            loser_moodlet = raid_def.get("defeat_moodlet", "RaidDefeated")
            winner_ids = raid.attacker_ids
            loser_ids = raid.defender_ids
        elif raid.outcome == "defender_victory":
            winner_moodlet = raid_def.get("defender_moodlet", "RaidSurvived")
            loser_moodlet = raid_def.get("defeat_moodlet", "RaidDefeated")
            winner_ids = raid.defender_ids
            loser_ids = raid.attacker_ids
        else:
            winner_ids = []
            loser_ids = []
            # Draw: mild negative for everyone
            all_ids = raid.attacker_ids + raid.defender_ids
            for pid in all_ids:
                p = praxan_map.get(pid)
                if p and hasattr(p, "add_moodlet"):
                    p.add_moodlet("LostSkirmish", -3, 180, current_time)
            return

        # Winners
        for pid in winner_ids:
            p = praxan_map.get(pid)
            if p and hasattr(p, "add_moodlet") and winner_moodlet:
                p.add_moodlet(winner_moodlet, 5, 300, current_time)

        # Losers
        for pid in loser_ids:
            p = praxan_map.get(pid)
            if p and hasattr(p, "add_moodlet") and loser_moodlet:
                p.add_moodlet(loser_moodlet, -8, 300, current_time)

        # Comrade casualties: witnesses get mood penalty
        all_casualties = raid.casualties_attacker + raid.casualties_defender
        for cid in all_casualties:
            casualty = praxan_map.get(cid)
            if casualty is None:
                continue
            fid = getattr(casualty, "faction_id", None)
            # Fellow faction members see a comrade fall
            for pid in (raid.attacker_ids + raid.defender_ids):
                if pid == cid:
                    continue
                witness = praxan_map.get(pid)
                if witness is None:
                    continue
                if getattr(witness, "faction_id", None) == fid:
                    if hasattr(witness, "add_moodlet"):
                        if getattr(casualty, "alive", True):
                            witness.add_moodlet("ComradeWounded", -5, 180, current_time)
                        else:
                            witness.add_moodlet("ComradeFallen", -10, 300, current_time)

        # Battle hardened: surviving veterans
        for pid in (raid.attacker_ids + raid.defender_ids):
            if pid in all_casualties:
                continue
            p = praxan_map.get(pid)
            if p and hasattr(p, "add_moodlet"):
                p.add_moodlet("BattleHardened", 3, 600, current_time)

    def _apply_reputation(
        self,
        raid: ActiveRaid,
        reputation_manager: Any,
        praxan_map: dict[int, Any],
        current_time: float,
    ) -> None:
        """Record reputation events for combat participants."""
        if reputation_manager is None:
            return

        # Defenders who stood get "defended_colony"
        if raid.outcome == "defender_victory":
            for pid in raid.defender_ids:
                if pid not in raid.casualties_defender and pid not in raid.fled_defender:
                    reputation_manager.record_event(pid, "defended_colony")
            # Leader bonus
            factions = {}
            try:
                # Access faction manager through reputation manager's references
                # Use the entity's faction_id to find the leader
                for pid in raid.defender_ids:
                    p = praxan_map.get(pid)
                    if p:
                        leader_fid = getattr(p, "faction_id", None)
                        if leader_fid == raid.defender_faction_id:
                            # Check if this praxan is the leader
                            break
            except Exception:
                pass

        # Attackers who won get "raided_enemy"
        if raid.outcome == "attacker_victory":
            for pid in raid.attacker_ids:
                if pid not in raid.casualties_attacker and pid not in raid.fled_attacker:
                    reputation_manager.record_event(pid, "raided_enemy")

        # Combat victories (downing an opponent)
        for pid in raid.attacker_ids:
            if pid not in raid.casualties_attacker:
                reputation_manager.record_event(pid, "combat_victory")

        for pid in raid.defender_ids:
            if pid not in raid.casualties_defender:
                # Defenders who stood and weren't downed
                if pid not in raid.fled_defender:
                    reputation_manager.record_event(pid, "combat_victory")

        # Fled = reputation penalty
        for pid in raid.fled_attacker + raid.fled_defender:
            reputation_manager.record_event(pid, "fled_battle")

        # Wounded in battle
        for pid in raid.casualties_attacker + raid.casualties_defender:
            p = praxan_map.get(pid)
            if p and getattr(p, "alive", True):
                reputation_manager.record_event(pid, "wounded_in_battle")

    def _apply_memories(
        self,
        raid: ActiveRaid,
        raid_def: dict,
        praxan_map: dict[int, Any],
        current_time: float,
    ) -> None:
        """Record episodic memories for participants."""
        label = raid_def.get("label", "a raid")

        for pid in raid.attacker_ids:
            p = praxan_map.get(pid)
            if p and hasattr(p, "episodic_memory") and p.episodic_memory is not None:
                p.episodic_memory.record(
                    "raid_participated",
                    f"{getattr(p, 'name', p.id)} fought in {label} against F{raid.defender_faction_id}",
                    timestamp=current_time,
                    metadata={"outcome": raid.outcome, "side": "attacker"},
                )

        for pid in raid.defender_ids:
            p = praxan_map.get(pid)
            if p and hasattr(p, "episodic_memory") and p.episodic_memory is not None:
                p.episodic_memory.record(
                    "raid_defended",
                    f"{getattr(p, 'name', p.id)} defended against {label} from F{raid.attacker_faction_id}",
                    timestamp=current_time,
                    metadata={"outcome": raid.outcome, "side": "defender"},
                )

        # Comrade fallen memories
        all_casualties = raid.casualties_attacker + raid.casualties_defender
        for cid in all_casualties:
            casualty = praxan_map.get(cid)
            if casualty is None:
                continue
            cname = getattr(casualty, "name", str(cid))
            fid = getattr(casualty, "faction_id", None)
            for pid in (raid.attacker_ids + raid.defender_ids):
                if pid == cid:
                    continue
                p = praxan_map.get(pid)
                if p and getattr(p, "faction_id", None) == fid:
                    if hasattr(p, "episodic_memory") and p.episodic_memory is not None:
                        if not getattr(casualty, "alive", True):
                            p.episodic_memory.record(
                                "comrade_fell_in_battle",
                                f"{getattr(p, 'name', p.id)} witnessed {cname} fall in battle",
                                timestamp=current_time,
                            )

    # ---- Event publishing ----------------------------------------------------

    def _publish_event(
        self,
        current_time: float,
        summary: str,
        detail: str,
        faction_id: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        if self._event_bus is None:
            return
        try:
            from events.bus import GameEvent, CATEGORY_WARFARE
            self._event_bus.publish(GameEvent(
                category=CATEGORY_WARFARE,
                summary=summary,
                detail=detail,
                faction_id=faction_id,
                timestamp=current_time,
                metadata=metadata or {},
            ))
        except Exception:
            pass

    # ---- Archive & cleanup ---------------------------------------------------

    def _archive_raid(self, raid: ActiveRaid, current_time: float) -> None:
        """Move resolved raid to history."""
        self.raid_history.append({
            "raid_id": raid.raid_id,
            "raid_def_id": raid.raid_def_id,
            "attacker_faction_id": raid.attacker_faction_id,
            "defender_faction_id": raid.defender_faction_id,
            "outcome": raid.outcome,
            "casualties_attacker": len(raid.casualties_attacker),
            "casualties_defender": len(raid.casualties_defender),
            "loot_taken": dict(raid.loot_taken),
            "buildings_damaged": raid.buildings_damaged,
            "ended_at": current_time,
        })
        if len(self.raid_history) > 20:
            del self.raid_history[:-20]

    # ---- Query methods -------------------------------------------------------

    def get_active_raids(self) -> list[dict[str, Any]]:
        """Return summaries of ongoing raids for UI."""
        return [
            {
                "raid_id": r.raid_id,
                "type": r.raid_def_id,
                "attacker": r.attacker_faction_id,
                "defender": r.defender_faction_id,
                "round": r.current_round,
                "max_rounds": r.max_rounds,
                "outcome": r.outcome,
            }
            for r in self.active_raids
        ]

    def get_recent_raids(self, count: int = 5) -> list[dict[str, Any]]:
        return self.raid_history[-count:]

    def is_faction_at_war(self, faction_id: int) -> bool:
        """Whether a faction is currently involved in a raid."""
        return any(
            (r.attacker_faction_id == faction_id or r.defender_faction_id == faction_id)
            and not r.resolved
            for r in self.active_raids
        )

    def get_faction_war_record(self, faction_id: int) -> dict[str, int]:
        """Return win/loss/draw record for a faction."""
        record = {"victories": 0, "defeats": 0, "draws": 0}
        for entry in self.raid_history:
            outcome = entry.get("outcome", "draw")
            att = entry.get("attacker_faction_id")
            defe = entry.get("defender_faction_id")
            if att == faction_id:
                if outcome == "attacker_victory":
                    record["victories"] += 1
                elif outcome == "defender_victory":
                    record["defeats"] += 1
                else:
                    record["draws"] += 1
            elif defe == faction_id:
                if outcome == "defender_victory":
                    record["victories"] += 1
                elif outcome == "attacker_victory":
                    record["defeats"] += 1
                else:
                    record["draws"] += 1
        return record

    # ---- Serialization -------------------------------------------------------

    def serialize(self, current_time: float | None = None) -> dict[str, Any]:
        now = current_time or time.time()
        return {
            "active_raids": [r.serialize(now) for r in self.active_raids if not r.resolved],
            "raid_history": list(self.raid_history[-10:]),
            "pair_cooldowns": {
                f"{k[0]}_{k[1]}": round(max(0.0, now - v), 3)
                for k, v in self._pair_cooldowns.items()
            },
        }

    def restore(self, data: dict[str, Any], current_time: float | None = None) -> None:
        """Restore from snapshot data."""
        if not data or not isinstance(data, dict):
            return
        now = current_time or time.time()
        self.active_raids.clear()
        self.raid_history.clear()
        self._pair_cooldowns.clear()

        # Restore raid history
        history = data.get("raid_history", [])
        if isinstance(history, list):
            self.raid_history = list(history[-20:])

        # Restore active raids
        active = data.get("active_raids", [])
        if isinstance(active, list):
            for rd in active:
                if not isinstance(rd, dict):
                    continue
                try:
                    remaining = float(rd.get("remaining_seconds", 0))
                except (TypeError, ValueError):
                    remaining = 0
                if remaining <= 0:
                    continue  # expired during save
                raid = ActiveRaid(
                    raid_id=str(rd.get("raid_id", "")),
                    raid_def_id=str(rd.get("raid_def_id", "")),
                    attacker_faction_id=int(rd.get("attacker_faction_id", 0)),
                    defender_faction_id=int(rd.get("defender_faction_id", 0)),
                    attacker_ids=list(rd.get("attacker_ids", [])),
                    defender_ids=list(rd.get("defender_ids", [])),
                    started_at=now - (float(rd.get("remaining_seconds", 0))),
                    ends_at=now + remaining,
                    current_round=int(rd.get("current_round", 0)),
                    max_rounds=int(rd.get("max_rounds", 4)),
                    resolved=bool(rd.get("resolved", False)),
                    outcome=str(rd.get("outcome", "")),
                    casualties_attacker=list(rd.get("casualties_attacker", [])),
                    casualties_defender=list(rd.get("casualties_defender", [])),
                    fled_attacker=list(rd.get("fled_attacker", [])),
                    fled_defender=list(rd.get("fled_defender", [])),
                    loot_taken=dict(rd.get("loot_taken", {})),
                    buildings_damaged=int(rd.get("buildings_damaged", 0)),
                )
                self.active_raids.append(raid)

        # Restore pair cooldowns
        cooldowns = data.get("pair_cooldowns", {})
        if isinstance(cooldowns, dict):
            for key_str, elapsed in cooldowns.items():
                try:
                    parts = key_str.split("_")
                    fid_a, fid_b = int(parts[0]), int(parts[1])
                    self._pair_cooldowns[(fid_a, fid_b)] = now - float(elapsed)
                except (TypeError, ValueError, IndexError):
                    continue
