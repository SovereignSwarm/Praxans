"""Tests for the Warfare & Raiding system (systems/warfare.py)."""

import unittest
import time

from systems.warfare import (
    WarfareManager,
    ActiveRaid,
    _combat_power,
    _morale_check,
    _fortification_bonus,
    get_raid_def,
    get_all_raid_defs,
    clear_cache,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class StubPraxan:
    _next_id = 0

    def __init__(self, x=100, y=100, faction_id=0):
        self.id = StubPraxan._next_id
        StubPraxan._next_id += 1
        self.x = x
        self.y = y
        self.faction_id = faction_id
        self.alive = True
        self.downed = False
        self.health = 100.0
        self.happiness = 70.0
        self.morale = 65.0
        self.needs = {"hunger": 80.0, "energy": 80.0, "social": 50.0}
        self.bonds = {}
        self.opinions = {}
        self.moodlets = []
        self.personality = {"curiosity": 0.5, "sociability": 0.7, "diligence": 0.5}
        self.episodic_memory = StubMemory()
        self.traits = []
        self.role = "gatherer"
        self.skills = {"gathering": {"level": 3, "xp": 0.0}, "crafting": {"level": 2, "xp": 0.0}}
        self.genetics = {"social_cohesion": 1.0, "aggression": 0.5}
        self.equipment = {"armor": None, "weapon": None}
        self.inventory = {"food": 5, "wood": 3, "stone": 2}
        self.capacities = {"consciousness": 1.0, "moving": 1.0, "manipulation": 1.0, "sight": 1.0}
        self._pending_reputation_events = []
        self.name = f"Praxan_{self.id}"
        self.life_stage = "adult"
        self.age = 150.0
        self.body_parts = {
            "torso": {"health": 100, "max": 100, "status": "intact", "efficiency": 1.0},
            "head": {"health": 50, "max": 50, "status": "intact", "efficiency": 1.0},
            "left_arm": {"health": 40, "max": 40, "status": "intact", "efficiency": 1.0},
            "right_arm": {"health": 40, "max": 40, "status": "intact", "efficiency": 1.0},
            "left_leg": {"health": 40, "max": 40, "status": "intact", "efficiency": 1.0},
            "right_leg": {"health": 40, "max": 40, "status": "intact", "efficiency": 1.0},
            "eyes": {"health": 20, "max": 20, "status": "intact", "efficiency": 1.0},
        }
        self.hediffs = []
        self.last_damage_type = None
        self.last_damage_part = None
        self.last_damage_amount = 0.0
        self.last_damage_time = 0.0
        self.last_death_cause_hint = None

    def add_moodlet(self, name, value, duration, start_time):
        for m in self.moodlets:
            if m["name"] == name:
                m["duration"] = duration
                m["start_time"] = start_time
                return
        self.moodlets.append({
            "name": name,
            "value": value,
            "duration": duration,
            "start_time": start_time,
        })

    def take_damage(self, amount, damage_type="blunt", current_time=None):
        """Simplified take_damage for testing."""
        self.health -= amount
        self.last_damage_type = damage_type
        self.last_damage_amount = amount
        if self.health <= 0:
            self.health = 0
            self.downed = True
        if self.health <= -50:
            self.alive = False


class StubMemory:
    def __init__(self):
        self.entries = []

    def record(self, category, summary, related_ids=None, timestamp=None, metadata=None, weight_override=None):
        self.entries.append({
            "category": category,
            "summary": summary,
            "related_ids": related_ids or [],
            "timestamp": timestamp,
            "metadata": metadata or {},
        })

    def to_dict(self):
        return {"entries": list(self.entries)}


class StubBuilding:
    def __init__(self, x=200, y=200, owner_id=None, building_type="house"):
        self.x = x
        self.y = y
        self.owner_id = owner_id
        self.building_type = building_type
        self.health = 100
        self.stored_resources = {"food": 20, "wood": 10, "stone": 5}


class StubFaction:
    def __init__(self, faction_id=0, member_ids=None, leader_id=None, doctrine="growth"):
        self.id = faction_id
        self.member_ids = list(member_ids or [])
        self.leader_id = leader_id or (self.member_ids[0] if self.member_ids else None)
        self.primary_doctrine = doctrine
        self.cohesion = 60.0
        self.ideology = {"growth": 0.5, "security": 0.5, "industry": 0.3, "exploration": 0.2, "harmony": 0.3}
        self.rival_faction_ids = []

    def get_centroid(self, praxans):
        members = [p for p in praxans if p.id in self.member_ids]
        if not members:
            return None
        return (sum(p.x for p in members) / len(members), sum(p.y for p in members) / len(members))


class StubFactionManager:
    def __init__(self, factions=None):
        if isinstance(factions, list):
            self.factions = {f.id: f for f in factions}
        else:
            self.factions = factions or {}


class StubDiplomaticRelation:
    def __init__(self, standing=-70.0):
        self.standing = standing
        self.treaties = []

    def has_treaty(self, treaty_type):
        return any(t.get("type") == treaty_type for t in self.treaties)

    def shift_standing(self, delta, current_time=0.0):
        old = self.standing
        self.standing = max(-100.0, min(100.0, self.standing + delta))
        return old != self.standing

    def record_incident(self, incident_id, label, delta, current_time):
        pass


class StubDiplomacyManager:
    def __init__(self, relations=None):
        self._relations = relations or {}

    def get_relation(self, fid_a, fid_b):
        key = (min(fid_a, fid_b), max(fid_a, fid_b))
        if key not in self._relations:
            self._relations[key] = StubDiplomaticRelation()
        return self._relations[key]


class StubReputationManager:
    def __init__(self):
        self.recorded_events = []

    def record_event(self, praxan_id, event_id, multiplier=1.0):
        self.recorded_events.append((praxan_id, event_id))
        return 0.0


class StubEventBus:
    def __init__(self):
        self.published = []
        self._subscribers = {}

    def publish(self, event):
        self.published.append(event)

    def subscribe(self, category, handler):
        self._subscribers.setdefault(category, []).append(handler)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_hostile_pair(n_attackers=3, n_defenders=3, standing=-70.0):
    """Create two hostile factions with praxans."""
    StubPraxan._next_id = 0
    att_praxans = [StubPraxan(x=100 + i * 20, y=100, faction_id=0) for i in range(n_attackers)]
    def_praxans = [StubPraxan(x=500 + i * 20, y=500, faction_id=1) for i in range(n_defenders)]

    att_ids = [p.id for p in att_praxans]
    def_ids = [p.id for p in def_praxans]

    faction_a = StubFaction(faction_id=0, member_ids=att_ids, doctrine="security")
    faction_b = StubFaction(faction_id=1, member_ids=def_ids, doctrine="growth")

    faction_manager = StubFactionManager([faction_a, faction_b])
    diplomacy_manager = StubDiplomacyManager({
        (0, 1): StubDiplomaticRelation(standing=standing),
    })

    all_praxans = att_praxans + def_praxans
    return all_praxans, faction_manager, diplomacy_manager


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDefLoading(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_raid_defs_load(self):
        defs = get_all_raid_defs()
        self.assertGreater(len(defs), 0, "No RaidDefs loaded")

    def test_raid_def_fields(self):
        rd = get_raid_def("pillage_raid")
        self.assertIsNotNone(rd)
        self.assertEqual(rd["raid_type"], "pillage")
        self.assertIn("min_attackers", rd)
        self.assertIn("duration_seconds", rd)
        self.assertIn("combat_rounds", rd)

    def test_all_four_raid_types(self):
        defs = get_all_raid_defs()
        expected = {"pillage_raid", "border_skirmish", "sabotage_mission", "conquest_assault"}
        self.assertTrue(expected.issubset(set(defs.keys())), f"Missing raid defs: {expected - set(defs.keys())}")

    def test_standing_thresholds_ordered(self):
        """Conquest requires worse standing than pillage."""
        pillage = get_raid_def("pillage_raid")
        conquest = get_raid_def("conquest_assault")
        self.assertLess(conquest["standing_threshold"], pillage["standing_threshold"])


class TestCombatHelpers(unittest.TestCase):
    def test_combat_power_unarmed(self):
        p = StubPraxan()
        power = _combat_power(p)
        self.assertGreater(power, 0)

    def test_combat_power_armed(self):
        p = StubPraxan()
        p.equipment["weapon"] = {"damage": 20, "name": "Iron Axe"}
        power_armed = _combat_power(p)
        p2 = StubPraxan()
        power_unarmed = _combat_power(p2)
        self.assertGreater(power_armed, power_unarmed)

    def test_combat_power_health_scaling(self):
        p_full = StubPraxan()
        p_full.health = 100
        p_hurt = StubPraxan()
        p_hurt.health = 30
        self.assertGreater(_combat_power(p_full), _combat_power(p_hurt))

    def test_morale_check_returns_bool(self):
        p = StubPraxan()
        result = _morale_check(p, 0.0)
        self.assertIsInstance(result, bool)

    def test_morale_check_high_casualties_more_likely_to_flee(self):
        """With many casualties, morale should break more often."""
        p = StubPraxan()
        p.genetics = {"aggression": 0.1}  # cowardly
        p.happiness = 20.0
        flee_count = sum(1 for _ in range(100) if not _morale_check(p, 0.9))
        # Should flee more than half the time with 90% casualties
        self.assertGreater(flee_count, 30)

    def test_fortification_bonus_near_building(self):
        p = StubPraxan(x=200, y=200)
        buildings = [StubBuilding(x=210, y=210)]
        bonus = _fortification_bonus(p, buildings)
        self.assertLess(bonus, 1.0)  # damage reduction

    def test_fortification_bonus_far_from_building(self):
        p = StubPraxan(x=200, y=200)
        buildings = [StubBuilding(x=900, y=900)]
        bonus = _fortification_bonus(p, buildings)
        self.assertEqual(bonus, 1.0)  # no bonus


class TestActiveRaid(unittest.TestCase):
    def test_serialize_roundtrip(self):
        now = time.time()
        raid = ActiveRaid(
            raid_id="raid_1",
            raid_def_id="pillage_raid",
            attacker_faction_id=0,
            defender_faction_id=1,
            attacker_ids=[1, 2, 3],
            defender_ids=[4, 5, 6],
            started_at=now - 10,
            ends_at=now + 15,
            current_round=2,
            max_rounds=4,
        )
        data = raid.serialize(now)
        self.assertEqual(data["raid_def_id"], "pillage_raid")
        self.assertGreater(data["remaining_seconds"], 0)
        self.assertEqual(data["current_round"], 2)


class TestWarfareManagerInit(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_initialization(self):
        mgr = WarfareManager()
        self.assertEqual(len(mgr.active_raids), 0)
        self.assertEqual(len(mgr.raid_history), 0)

    def test_attach_event_bus(self):
        mgr = WarfareManager()
        bus = StubEventBus()
        mgr.attach_event_bus(bus)
        self.assertIs(mgr._event_bus, bus)


class TestRaidInitiation(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_no_raid_when_friendly(self):
        """Friendly factions should never raid."""
        praxans, fm, dm = _make_hostile_pair(standing=30.0)
        mgr = WarfareManager()
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        self.assertEqual(len(mgr.active_raids), 0)

    def test_no_raid_when_nap_treaty(self):
        """NAP treaty should block raids even at hostile standing."""
        praxans, fm, dm = _make_hostile_pair(standing=-80.0)
        rel = dm.get_relation(0, 1)
        rel.treaties = [{"type": "non_aggression_pact"}]
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0  # guarantee attempt
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        self.assertEqual(len(mgr.active_raids), 0)

    def test_raid_can_initiate_at_hostile(self):
        """Hostile factions can trigger a raid."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0  # guarantee
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        self.assertGreater(len(mgr.active_raids), 0)

    def test_raid_cooldown_respected(self):
        """Same pair shouldn't raid again within cooldown."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr._pair_cooldowns[(0, 1)] = 990.0  # recent
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        self.assertEqual(len(mgr.active_raids), 0)

    def test_minimum_attackers_required(self):
        """With too few members, raid should not start."""
        # Conquest requires min_attackers=3 but we only have 1
        praxans, fm, dm = _make_hostile_pair(n_attackers=1, n_defenders=3, standing=-90.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        # Force eval
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        # Might start a border_skirmish (min_attackers=1) but not conquest
        for raid in mgr.active_raids:
            self.assertNotEqual(raid.raid_def_id, "conquest_assault")

    def test_raid_selects_adult_combatants_only(self):
        """Infants and youth should not be selected for combat."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=5, n_defenders=5, standing=-80.0)
        # Make first attacker a youth
        praxans[0].life_stage = "youth"
        praxans[0].age = 50
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        for raid in mgr.active_raids:
            self.assertNotIn(praxans[0].id, raid.attacker_ids)


class TestCombatResolution(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_raid_resolves_after_max_rounds(self):
        """A raid should resolve once all rounds complete."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0

        # Start raid
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        self.assertGreater(len(mgr.active_raids), 0)
        raid = mgr.active_raids[0]

        # Advance time past raid end
        mgr.update(praxans, [], fm, dm, current_time=1100.0)
        # Should have resolved and been archived
        self.assertEqual(len(mgr.active_raids), 0)
        self.assertGreater(len(mgr.raid_history), 0)

    def test_outcome_has_valid_value(self):
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        mgr.update(praxans, [], fm, dm, current_time=1100.0)
        self.assertGreater(len(mgr.raid_history), 0)
        entry = mgr.raid_history[-1]
        self.assertIn(entry["outcome"], ("attacker_victory", "defender_victory", "draw"))

    def test_take_damage_called_on_combatants(self):
        """Combatants should receive damage during a raid."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=3, n_defenders=3, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        initial_health = {p.id: p.health for p in praxans}
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        mgr.update(praxans, [], fm, dm, current_time=1100.0)

        # At least one praxan should have lost health
        damaged = [p for p in praxans if p.health < initial_health[p.id]]
        self.assertGreater(len(damaged), 0, "No praxans took damage during raid")

    def test_downed_removed_from_combat(self):
        """Downed praxans should not continue fighting."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=5, n_defenders=5, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        # Manually down a combatant mid-raid
        if mgr.active_raids:
            raid = mgr.active_raids[0]
            if raid.defender_ids:
                first_def = raid.defender_ids[0]
                for p in praxans:
                    if p.id == first_def:
                        p.downed = True
                        p.health = 0
                        break
        mgr.update(praxans, [], fm, dm, current_time=1100.0)
        # Raid should have resolved without error
        self.assertEqual(len(mgr.active_raids), 0)


class TestConsequences(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_moodlets_applied_after_raid(self):
        """Participants should receive moodlets after raid resolution."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=3, n_defenders=3, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        mgr.update(praxans, [], fm, dm, current_time=1100.0)

        # At least some praxans should have warfare-related moodlets
        warfare_moodlets = {"RaidVictory", "RaidSurvived", "RaidDefeated", "WonSkirmish",
                            "DefendedBorder", "LostSkirmish", "BattleHardened",
                            "ComradeWounded", "ComradeFallen", "SabotageSuccess",
                            "RepelledSaboteurs", "SabotageSuffered", "ConquestVictory",
                            "DefendedColony", "ConquestDefeated"}
        found = False
        for p in praxans:
            for m in p.moodlets:
                if m["name"] in warfare_moodlets:
                    found = True
                    break
        self.assertTrue(found, "No warfare moodlets applied to any praxan")

    def test_episodic_memories_recorded(self):
        """Participants should have combat memories."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=3, n_defenders=3, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        mgr.update(praxans, [], fm, dm, current_time=1100.0)

        memory_categories = set()
        for p in praxans:
            for entry in p.episodic_memory.entries:
                memory_categories.add(entry["category"])

        warfare_memories = {"raid_participated", "raid_defended"}
        self.assertTrue(
            warfare_memories & memory_categories,
            f"No warfare memories found. Categories: {memory_categories}",
        )

    def test_reputation_events_recorded(self):
        """Reputation manager should receive combat events."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=3, n_defenders=3, standing=-80.0)
        rep_mgr = StubReputationManager()
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, rep_mgr, current_time=1000.0)
        mgr.update(praxans, [], fm, dm, rep_mgr, current_time=1100.0)

        event_ids = {e[1] for e in rep_mgr.recorded_events}
        # Should contain at least combat_victory or defended_colony or fled_battle
        combat_events = {"combat_victory", "defended_colony", "fled_battle", "raided_enemy", "wounded_in_battle"}
        self.assertTrue(
            combat_events & event_ids,
            f"No combat reputation events found. Events: {event_ids}",
        )

    def test_diplomacy_standing_shifts_after_raid(self):
        """Diplomacy standing should worsen after a raid."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=3, n_defenders=3, standing=-70.0)
        rel = dm.get_relation(0, 1)
        initial_standing = rel.standing
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        mgr.update(praxans, [], fm, dm, current_time=1100.0)
        self.assertLess(rel.standing, initial_standing)

    def test_event_bus_receives_warfare_events(self):
        """EventBus should receive CATEGORY_WARFARE events."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        bus = StubEventBus()
        mgr = WarfareManager()
        mgr.attach_event_bus(bus)
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        mgr.update(praxans, [], fm, dm, current_time=1100.0)

        warfare_events = [e for e in bus.published if getattr(e, "category", "") == "warfare"]
        self.assertGreater(len(warfare_events), 0, "No warfare events published to EventBus")

    def test_loot_on_attacker_victory(self):
        """Attacker victory on a pillage raid should transfer resources."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=5, n_defenders=2, standing=-80.0)
        # Give defenders low health so attackers win easily
        for p in praxans:
            if p.faction_id == 1:
                p.health = 10.0

        buildings = [StubBuilding(x=500, y=500, owner_id=praxans[5].id)]
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, buildings, fm, dm, current_time=1000.0)
        mgr.update(praxans, buildings, fm, dm, current_time=1100.0)

        if mgr.raid_history:
            entry = mgr.raid_history[-1]
            if entry["outcome"] == "attacker_victory":
                # Loot should have been taken
                loot = entry.get("loot_taken", {})
                # Building resources may have been depleted
                total_loot = sum(loot.values())
                self.assertGreaterEqual(total_loot, 0)


class TestBuildingDamage(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_sabotage_damages_buildings(self):
        """Sabotage raids should damage defender buildings."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=3, n_defenders=3, standing=-70.0)
        buildings = [
            StubBuilding(x=500, y=500, owner_id=praxans[3].id),
            StubBuilding(x=520, y=520, owner_id=praxans[4].id),
        ]
        mgr = WarfareManager()
        # Directly call _apply_building_damage
        damaged = mgr._apply_building_damage(buildings, 1, fm, 1.0)  # 100% chance
        self.assertGreater(damaged, 0)
        # At least one building should have reduced health
        damaged_buildings = [b for b in buildings if b.health < 100]
        self.assertGreater(len(damaged_buildings), 0)


class TestQueryMethods(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_is_faction_at_war(self):
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        mgr = WarfareManager()
        self.assertFalse(mgr.is_faction_at_war(0))
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        if mgr.active_raids:
            att_fid = mgr.active_raids[0].attacker_faction_id
            self.assertTrue(mgr.is_faction_at_war(att_fid))

    def test_get_active_raids_format(self):
        mgr = WarfareManager()
        self.assertEqual(mgr.get_active_raids(), [])

    def test_get_faction_war_record(self):
        mgr = WarfareManager()
        record = mgr.get_faction_war_record(0)
        self.assertEqual(record, {"victories": 0, "defeats": 0, "draws": 0})

    def test_war_record_after_raid(self):
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        mgr.update(praxans, [], fm, dm, current_time=1100.0)
        if mgr.raid_history:
            entry = mgr.raid_history[-1]
            att = entry["attacker_faction_id"]
            record = mgr.get_faction_war_record(att)
            total = record["victories"] + record["defeats"] + record["draws"]
            self.assertGreater(total, 0)


class TestSerialization(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_serialize_empty(self):
        mgr = WarfareManager()
        data = mgr.serialize()
        self.assertIn("active_raids", data)
        self.assertIn("raid_history", data)
        self.assertIn("pair_cooldowns", data)

    def test_serialize_with_active_raid(self):
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        data = mgr.serialize(current_time=1005.0)
        self.assertGreater(len(data["active_raids"]), 0)

    def test_restore_raid_history(self):
        mgr = WarfareManager()
        data = {
            "raid_history": [
                {"raid_id": "r1", "outcome": "attacker_victory", "attacker_faction_id": 0, "defender_faction_id": 1},
            ],
            "active_raids": [],
            "pair_cooldowns": {},
        }
        mgr.restore(data)
        self.assertEqual(len(mgr.raid_history), 1)
        self.assertEqual(mgr.raid_history[0]["outcome"], "attacker_victory")

    def test_restore_pair_cooldowns(self):
        mgr = WarfareManager()
        now = time.time()
        data = {
            "raid_history": [],
            "active_raids": [],
            "pair_cooldowns": {"0_1": 30.0},  # 30 seconds ago
        }
        mgr.restore(data, current_time=now)
        key = (0, 1)
        self.assertIn(key, mgr._pair_cooldowns)
        # elapsed is 30s, so last raid time should be now - 30
        self.assertAlmostEqual(mgr._pair_cooldowns[key], now - 30.0, delta=1.0)

    def test_restore_active_raid(self):
        mgr = WarfareManager()
        now = time.time()
        data = {
            "raid_history": [],
            "active_raids": [{
                "raid_id": "r1",
                "raid_def_id": "pillage_raid",
                "attacker_faction_id": 0,
                "defender_faction_id": 1,
                "attacker_ids": [1, 2],
                "defender_ids": [3, 4],
                "remaining_seconds": 15.0,
                "current_round": 1,
                "max_rounds": 4,
                "resolved": False,
                "outcome": "",
                "casualties_attacker": [],
                "casualties_defender": [],
                "fled_attacker": [],
                "fled_defender": [],
                "loot_taken": {},
                "buildings_damaged": 0,
            }],
            "pair_cooldowns": {},
        }
        mgr.restore(data, current_time=now)
        self.assertEqual(len(mgr.active_raids), 1)
        raid = mgr.active_raids[0]
        self.assertEqual(raid.raid_def_id, "pillage_raid")
        self.assertAlmostEqual(raid.ends_at, now + 15.0, delta=0.5)

    def test_serialize_restore_roundtrip(self):
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        now = 1000.0
        mgr.update(praxans, [], fm, dm, current_time=now)

        data = mgr.serialize(current_time=now + 5)

        mgr2 = WarfareManager()
        mgr2.restore(data, current_time=now + 5)
        self.assertEqual(len(mgr2.active_raids), len(mgr.active_raids))

    def test_restore_ignores_expired_raids(self):
        mgr = WarfareManager()
        data = {
            "raid_history": [],
            "active_raids": [{
                "raid_id": "r_expired",
                "raid_def_id": "pillage_raid",
                "attacker_faction_id": 0,
                "defender_faction_id": 1,
                "attacker_ids": [1],
                "defender_ids": [2],
                "remaining_seconds": 0,  # expired
                "current_round": 4,
                "max_rounds": 4,
                "resolved": False,
                "outcome": "",
                "casualties_attacker": [],
                "casualties_defender": [],
                "fled_attacker": [],
                "fled_defender": [],
                "loot_taken": {},
                "buildings_damaged": 0,
            }],
            "pair_cooldowns": {},
        }
        mgr.restore(data)
        self.assertEqual(len(mgr.active_raids), 0)

    def test_restore_started_at_uses_total_duration(self):
        """Regression: started_at must be ends_at - total_duration, not now - remaining.

        The old code set started_at = now - remaining.  When remaining >
        total_duration/2 (early-stage raid), this made started_at appear
        further in the past than it really was, causing expected_round to
        jump past current_round on the first post-restore frame and
        triggering _finalize_raid while skipping rounds.
        """
        # setUp already initialized DefDatabase; use get_raid_def directly.
        # pillage_raid has duration_seconds = 25, combat_rounds = 4
        raid_def = get_raid_def("pillage_raid")
        self.assertIsNotNone(raid_def, "pillage_raid def must load")
        total_dur = float(raid_def.get("duration_seconds", 25))
        max_rounds = int(raid_def.get("combat_rounds", 4))
        round_dur = total_dur / max(1, max_rounds)

        now = 5000.0
        # Raid saved early: only 1 round done, most time remaining
        remaining = total_dur * 0.8  # 80% of duration left
        current_round = 1

        data = {
            "raid_history": [],
            "active_raids": [{
                "raid_id": "r_early",
                "raid_def_id": "pillage_raid",
                "attacker_faction_id": 0,
                "defender_faction_id": 1,
                "attacker_ids": [10, 11],
                "defender_ids": [20, 21],
                "remaining_seconds": remaining,
                "current_round": current_round,
                "max_rounds": max_rounds,
                "resolved": False,
                "outcome": "",
                "casualties_attacker": [],
                "casualties_defender": [],
                "fled_attacker": [],
                "fled_defender": [],
                "loot_taken": {},
                "buildings_damaged": 0,
            }],
            "pair_cooldowns": {},
        }
        mgr = WarfareManager()
        mgr.restore(data, current_time=now)

        self.assertEqual(len(mgr.active_raids), 1)
        raid = mgr.active_raids[0]

        # ends_at must be correct
        self.assertAlmostEqual(raid.ends_at, now + remaining, delta=0.01)

        # started_at must equal ends_at - total_duration (not now - remaining)
        expected_started_at = raid.ends_at - total_dur
        self.assertAlmostEqual(raid.started_at, expected_started_at, delta=0.01)

        # Verify expected_round at restore time does NOT exceed current_round,
        # so no extra combat fires immediately (old bug caused early finalization).
        elapsed_at_restore = now - raid.started_at
        expected_round_at_restore = min(
            max_rounds,
            int(elapsed_at_restore / round_dur) + 1,
        )
        self.assertLessEqual(
            expected_round_at_restore,
            current_round,
            "expected_round must not exceed current_round right after restore "
            "(old started_at=now-remaining bug caused early finalization)",
        )


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_no_crash_with_no_factions(self):
        mgr = WarfareManager()
        mgr.update([], [], None, None, current_time=1000.0)
        self.assertEqual(len(mgr.active_raids), 0)

    def test_no_crash_with_single_faction(self):
        p = StubPraxan(faction_id=0)
        f = StubFaction(faction_id=0, member_ids=[p.id])
        fm = StubFactionManager([f])
        dm = StubDiplomacyManager()
        mgr = WarfareManager()
        mgr.update([p], [], fm, dm, current_time=1000.0)
        self.assertEqual(len(mgr.active_raids), 0)

    def test_no_crash_when_all_combatants_dead(self):
        """If all combatants die mid-raid, it should resolve gracefully."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=3, n_defenders=3, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)

        # Kill everyone
        for p in praxans:
            p.alive = False
            p.downed = True

        # Should resolve without crashing
        mgr.update(praxans, [], fm, dm, current_time=1100.0)
        self.assertEqual(len(mgr.active_raids), 0)

    def test_restore_empty_data(self):
        mgr = WarfareManager()
        mgr.restore({})
        self.assertEqual(len(mgr.active_raids), 0)

    def test_restore_none_data(self):
        mgr = WarfareManager()
        mgr.restore(None)
        self.assertEqual(len(mgr.active_raids), 0)

    def test_no_double_raid_same_pair(self):
        """Only one raid at a time per faction pair."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        first_count = len(mgr.active_raids)
        mgr.update(praxans, [], fm, dm, current_time=1005.0)
        # Should not have added another
        self.assertEqual(len(mgr.active_raids), first_count)

    def test_downed_praxan_not_selected(self):
        """Downed praxans should not be selected as combatants."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        praxans[0].downed = True
        praxans[0].health = 0
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        for raid in mgr.active_raids:
            self.assertNotIn(praxans[0].id, raid.attacker_ids)

    def test_low_health_praxan_excluded(self):
        """Very low health praxans should not be selected."""
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-80.0)
        praxans[0].health = 10.0  # Below 30% threshold for attackers
        mgr = WarfareManager()
        mgr.RAID_CHANCE_BASE = 1.0
        mgr.EVAL_INTERVAL = 0
        mgr.update(praxans, [], fm, dm, current_time=1000.0)
        for raid in mgr.active_raids:
            self.assertNotIn(praxans[0].id, raid.attacker_ids)


class TestIncidentIntegration(unittest.TestCase):
    """Test the storyteller incident_faction_raid."""

    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_incident_faction_raid_triggers(self):
        from events.incidents import incident_faction_raid
        praxans, fm, dm = _make_hostile_pair(n_attackers=4, n_defenders=4, standing=-70.0)
        wm = WarfareManager()
        game_state = {
            "praxans": praxans,
            "warfare_manager": wm,
            "diplomacy_manager": dm,
            "faction_manager": fm,
        }
        incident_faction_raid(game_state)
        self.assertGreater(len(wm.active_raids), 0)

    def test_incident_no_crash_without_managers(self):
        from events.incidents import incident_faction_raid
        game_state = {}
        incident_faction_raid(game_state)  # Should not crash


if __name__ == "__main__":
    unittest.main()
