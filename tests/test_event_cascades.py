"""Tests for the Event Cascade System (systems/event_cascades.py).

Covers:
- CascadeDef loading from DefDatabase
- Each cascade evaluator (mass_death_trauma, combat_death_mourning,
  epidemic_anxiety, disaster_resource_stress, crisis_resilience,
  famine_warning, warfare_escalation, birth_celebration)
- Cooldown enforcement
- Pending effect queuing and application
- Serialization / deserialization
- Edge cases (no faction manager, empty praxans, etc.)
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from events.bus import (
    CATEGORY_BIRTH,
    CATEGORY_DEATH,
    CATEGORY_DISASTER,
    CATEGORY_PERSONAL,
    CATEGORY_WARFARE,
    EventBus,
    GameEvent,
)
from systems.def_database import DefDatabase
from systems.event_cascades import (
    EventCascadeManager,
    clear_cache,
    get_all_cascade_defs,
    get_cascade_def,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockPraxan:
    """Minimal praxan stand-in for cascade testing."""

    def __init__(self, pid=1, faction_id=0, alive=True):
        self.id = pid
        self.faction_id = faction_id
        self.alive = alive
        self.health = 100.0
        self.happiness = 70.0
        self.morale = 65.0
        self.resilience = 1.0
        self.bonds = {}
        self.moodlets = []
        self.episodic_memory = MockMemory()

    def add_moodlet(self, name, offset, duration, now):
        self.moodlets.append({
            "id": name, "name": name, "value": offset,
            "duration": duration, "start_time": now,
        })


class MockMemory:
    def __init__(self):
        self.entries = []

    def record(self, event_type, text, **kwargs):
        self.entries.append({"event_type": event_type, "text": text, **kwargs})


class MockFaction:
    def __init__(self, fid=0):
        self.id = fid
        self.cohesion = 80.0
        self.stability = 70.0
        self.resource_stress = 20.0
        self.migration_pressure = 10.0


class MockFactionManager:
    def __init__(self, factions=None):
        self.factions = factions or {}


class MockRitualManager:
    def __init__(self):
        self.death_signals = []
        self.birth_signals = []
        self.crisis_signals = []

    def signal_death(self, fid, t):
        self.death_signals.append((fid, t))

    def signal_birth(self, fid, t):
        self.birth_signals.append((fid, t))

    def signal_crisis_survived(self, fid, t):
        self.crisis_signals.append((fid, t))


class MockDiplomacyManager:
    def __init__(self):
        self.standing_changes = []

    def modify_standing(self, fid_a, fid_b, delta):
        self.standing_changes.append((fid_a, fid_b, delta))


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestCascadeDefLoading(unittest.TestCase):
    """Test CascadeDef loading from DefDatabase."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_cascade_defs_load(self):
        defs = get_all_cascade_defs()
        self.assertGreaterEqual(len(defs), 8, "Should have at least 8 cascade defs")

    def test_specific_cascade_defs_exist(self):
        expected = [
            "mass_death_trauma", "combat_death_mourning", "epidemic_anxiety",
            "disaster_resource_stress", "ecology_famine_warning",
            "crisis_resilience", "warfare_escalation", "birth_celebration",
        ]
        for cid in expected:
            cdef = get_cascade_def(cid)
            self.assertIsNotNone(cdef, f"Missing cascade def: {cid}")
            self.assertIn("parameters", cdef)
            self.assertIn("cooldown_seconds", cdef)

    def test_cascade_def_has_required_fields(self):
        defs = get_all_cascade_defs()
        for cid, cdef in defs.items():
            self.assertIn("id", cdef, f"{cid} missing 'id'")
            self.assertIn("label", cdef, f"{cid} missing 'label'")
            self.assertIn("trigger_category", cdef, f"{cid} missing 'trigger_category'")
            self.assertIn("effect_type", cdef, f"{cid} missing 'effect_type'")
            self.assertIn("parameters", cdef, f"{cid} missing 'parameters'")
            self.assertIn("cooldown_seconds", cdef, f"{cid} missing 'cooldown_seconds'")


class TestEventCascadeManagerInit(unittest.TestCase):
    """Test EventCascadeManager initialization and setup."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_init_defaults(self):
        mgr = EventCascadeManager()
        self.assertEqual(mgr.total_cascades_fired, 0)
        self.assertEqual(mgr.cascade_history, [])
        self.assertEqual(mgr.recent_death_count, 0)

    def test_set_systems(self):
        mgr = EventCascadeManager()
        fm = MockFactionManager()
        rm = MockRitualManager()
        dm = MockDiplomacyManager()
        mgr.set_systems(faction_manager=fm, ritual_manager=rm, diplomacy_manager=dm)
        self.assertIs(mgr._faction_manager, fm)
        self.assertIs(mgr._ritual_manager, rm)
        self.assertIs(mgr._diplomacy_manager, dm)

    def test_attach_event_bus(self):
        mgr = EventCascadeManager()
        bus = EventBus()
        mgr.attach_event_bus(bus)
        self.assertIs(mgr._event_bus, bus)
        # Check subscriptions exist
        self.assertGreater(len(bus._subscribers.get(CATEGORY_DEATH, [])), 0)
        self.assertGreater(len(bus._subscribers.get(CATEGORY_DISASTER, [])), 0)
        self.assertGreater(len(bus._subscribers.get(CATEGORY_WARFARE, [])), 0)
        self.assertGreater(len(bus._subscribers.get(CATEGORY_BIRTH, [])), 0)


class TestMassDeathTrauma(unittest.TestCase):
    """Test the mass_death_trauma cascade."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = EventCascadeManager()
        self.bus = EventBus()
        self.faction = MockFaction(fid=0)
        self.fm = MockFactionManager({0: self.faction})
        self.rm = MockRitualManager()
        self.mgr.set_systems(faction_manager=self.fm, ritual_manager=self.rm)
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_no_trigger_below_threshold(self):
        now = time.time()
        # Publish 2 deaths (threshold is 3)
        for i in range(2):
            self.bus.publish(GameEvent(
                category=CATEGORY_DEATH,
                summary=f"Praxan {i} died",
                praxan_id=i,
                faction_id=0,
                timestamp=now,
                metadata={"cause": "starvation"},
            ))
        self.assertEqual(self.mgr.total_cascades_fired, 0)
        self.assertEqual(len(self.mgr._pending_effects), 0)

    def test_trigger_at_threshold(self):
        now = time.time()
        for i in range(3):
            self.bus.publish(GameEvent(
                category=CATEGORY_DEATH,
                summary=f"Praxan {i} died",
                praxan_id=i,
                faction_id=0,
                timestamp=now + i * 0.1,
                metadata={"cause": "starvation"},
            ))
        # Mass death trauma should fire on the 3rd death
        self.assertGreaterEqual(self.mgr.total_cascades_fired, 1)
        # Should have queued a pending effect
        self.assertGreater(len(self.mgr._pending_effects), 0)
        effect = self.mgr._pending_effects[0]
        self.assertEqual(effect["cascade_type"], "mass_death_trauma")
        self.assertEqual(effect["scope"], "faction")

    def test_cohesion_penalty_applied(self):
        now = time.time()
        initial_cohesion = self.faction.cohesion
        for i in range(4):
            self.bus.publish(GameEvent(
                category=CATEGORY_DEATH,
                summary=f"Praxan {i} died",
                praxan_id=i, faction_id=0, timestamp=now,
                metadata={"cause": "disaster"},
            ))
        self.assertLess(self.faction.cohesion, initial_cohesion)

    def test_mourning_signal_sent(self):
        now = time.time()
        for i in range(3):
            self.bus.publish(GameEvent(
                category=CATEGORY_DEATH,
                summary=f"Praxan {i} died",
                praxan_id=i, faction_id=0, timestamp=now,
                metadata={"cause": "disease"},
            ))
        self.assertGreater(len(self.rm.death_signals), 0)

    def test_cooldown_prevents_rapid_refire(self):
        now = time.time()
        for i in range(3):
            self.bus.publish(GameEvent(
                category=CATEGORY_DEATH,
                summary=f"Praxan {i} died",
                praxan_id=i, faction_id=0, timestamp=now,
                metadata={"cause": "x"},
            ))
        first_count = self.mgr.total_cascades_fired
        # Fire 3 more deaths immediately — should not trigger again (cooldown)
        for i in range(3, 6):
            self.bus.publish(GameEvent(
                category=CATEGORY_DEATH,
                summary=f"Praxan {i} died",
                praxan_id=i, faction_id=0, timestamp=now + 0.5,
                metadata={"cause": "x"},
            ))
        self.assertEqual(self.mgr.total_cascades_fired, first_count)


class TestCombatDeathMourning(unittest.TestCase):
    """Test the combat_death_mourning cascade."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = EventCascadeManager()
        self.bus = EventBus()
        self.rm = MockRitualManager()
        self.fm = MockFactionManager({0: MockFaction(0)})
        self.mgr.set_systems(ritual_manager=self.rm, faction_manager=self.fm)
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_combat_death_triggers_mourning(self):
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Warrior fell",
            praxan_id=1, faction_id=0, timestamp=now,
            metadata={"cause": "combat"},
        ))
        self.assertGreater(len(self.rm.death_signals), 0)
        # Check queued effect
        combat_effects = [e for e in self.mgr._pending_effects
                          if e.get("cascade_type") == "combat_death_mourning"]
        self.assertGreater(len(combat_effects), 0)

    def test_non_combat_death_no_mourning(self):
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Died of old age",
            praxan_id=1, faction_id=0, timestamp=now,
            metadata={"cause": "age"},
        ))
        # Should not trigger combat mourning cascade
        combat_effects = [e for e in self.mgr._pending_effects
                          if e.get("cascade_type") == "combat_death_mourning"]
        self.assertEqual(len(combat_effects), 0)

    def test_no_faction_id_no_mourning(self):
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Warrior fell",
            praxan_id=1, faction_id=None, timestamp=now,
            metadata={"cause": "combat"},
        ))
        combat_effects = [e for e in self.mgr._pending_effects
                          if e.get("cascade_type") == "combat_death_mourning"]
        self.assertEqual(len(combat_effects), 0)


class TestEpidemicAnxiety(unittest.TestCase):
    """Test the epidemic_anxiety cascade."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = EventCascadeManager()
        self.bus = EventBus()
        self.faction = MockFaction(0)
        self.fm = MockFactionManager({0: self.faction})
        self.mgr.set_systems(faction_manager=self.fm)
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_epidemic_triggers_anxiety(self):
        now = time.time()
        initial_cohesion = self.faction.cohesion
        self.bus.publish(GameEvent(
            category=CATEGORY_DISASTER,
            summary="Epidemic! Gut Rot has infected 5 praxans",
            timestamp=now,
            metadata={"type": "epidemic", "disease_id": "gut_rot", "infected_count": 5},
        ))
        self.assertLess(self.faction.cohesion, initial_cohesion)
        # Check pending effect queued
        anxiety_effects = [e for e in self.mgr._pending_effects
                           if e.get("cascade_type") == "epidemic_anxiety"]
        self.assertGreater(len(anxiety_effects), 0)

    def test_non_epidemic_disaster_no_anxiety(self):
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_DISASTER,
            summary="Earthquake struck!",
            timestamp=now,
            metadata={"type": "disaster", "disaster_id": "earthquake"},
        ))
        anxiety_effects = [e for e in self.mgr._pending_effects
                           if e.get("cascade_type") == "epidemic_anxiety"]
        self.assertEqual(len(anxiety_effects), 0)


class TestDisasterResourceStress(unittest.TestCase):
    """Test the disaster_resource_stress cascade."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = EventCascadeManager()
        self.bus = EventBus()
        self.faction = MockFaction(0)
        self.fm = MockFactionManager({0: self.faction})
        self.mgr.set_systems(faction_manager=self.fm)
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    @patch("systems.event_cascades.random")
    def test_disaster_spikes_resource_stress(self, mock_random):
        mock_random.random.return_value = 0.0  # Always pass probability check
        now = time.time()
        initial_stress = self.faction.resource_stress
        self.bus.publish(GameEvent(
            category=CATEGORY_DISASTER,
            summary="Flood struck! 3 buildings damaged",
            timestamp=now,
            metadata={"type": "disaster", "affected_buildings": 3, "severity": 0.7},
        ))
        self.assertGreater(self.faction.resource_stress, initial_stress)

    def test_no_buildings_damaged_no_stress(self):
        now = time.time()
        initial_stress = self.faction.resource_stress
        self.bus.publish(GameEvent(
            category=CATEGORY_DISASTER,
            summary="Minor tremor",
            timestamp=now,
            metadata={"type": "disaster", "affected_buildings": 0, "severity": 0.3},
        ))
        self.assertEqual(self.faction.resource_stress, initial_stress)


class TestCrisisResilience(unittest.TestCase):
    """Test the crisis_resilience cascade."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = EventCascadeManager()
        self.bus = EventBus()
        self.rm = MockRitualManager()
        self.fm = MockFactionManager({0: MockFaction(0)})
        self.mgr.set_systems(ritual_manager=self.rm, faction_manager=self.fm)
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    @patch("systems.event_cascades.random")
    def test_severe_disaster_triggers_resilience(self, mock_random):
        mock_random.random.return_value = 0.0
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_DISASTER,
            summary="Devastating wildfire!",
            timestamp=now,
            metadata={"type": "disaster", "severity": 0.8, "survivors": [1, 2, 3],
                       "affected_buildings": 2},
        ))
        resilience_effects = [e for e in self.mgr._pending_effects
                              if e.get("cascade_type") == "crisis_resilience"]
        self.assertGreater(len(resilience_effects), 0)
        self.assertGreater(resilience_effects[0].get("resilience_boost", 0), 0)

    def test_mild_disaster_no_resilience(self):
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_DISASTER,
            summary="Minor dust storm",
            timestamp=now,
            metadata={"type": "disaster", "severity": 0.2, "affected_buildings": 1},
        ))
        resilience_effects = [e for e in self.mgr._pending_effects
                              if e.get("cascade_type") == "crisis_resilience"]
        self.assertEqual(len(resilience_effects), 0)

    @patch("systems.event_cascades.random")
    def test_crisis_signals_rituals(self, mock_random):
        mock_random.random.return_value = 0.0
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_DISASTER,
            summary="Severe blizzard!",
            timestamp=now,
            metadata={"type": "disaster", "severity": 0.9, "affected_buildings": 2},
        ))
        self.assertGreater(len(self.rm.crisis_signals), 0)


class TestWarfareEscalation(unittest.TestCase):
    """Test the warfare_escalation cascade."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = EventCascadeManager()
        self.bus = EventBus()
        self.dm = MockDiplomacyManager()
        self.fm = MockFactionManager({0: MockFaction(0), 1: MockFaction(1)})
        self.mgr.set_systems(diplomacy_manager=self.dm, faction_manager=self.fm)
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    @patch("systems.event_cascades.random")
    def test_raid_triggers_diplomacy_spiral(self, mock_random):
        mock_random.random.return_value = 0.0
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_WARFARE,
            summary="Faction 0 raids Faction 1",
            timestamp=now,
            metadata={"attacker_faction_id": 0, "defender_faction_id": 1, "outcome": "victory"},
        ))
        # Should modify standings for both factions
        self.assertGreater(len(self.dm.standing_changes), 0)
        # Should queue effects for both factions
        escalation_effects = [e for e in self.mgr._pending_effects
                              if e.get("cascade_type") == "warfare_escalation"]
        self.assertEqual(len(escalation_effects), 2)  # one for each faction

    def test_missing_faction_ids_no_trigger(self):
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_WARFARE,
            summary="Unknown raid",
            timestamp=now,
            metadata={"outcome": "victory"},
        ))
        escalation_effects = [e for e in self.mgr._pending_effects
                              if e.get("cascade_type") == "warfare_escalation"]
        self.assertEqual(len(escalation_effects), 0)


class TestBirthCelebration(unittest.TestCase):
    """Test the birth_celebration cascade."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = EventCascadeManager()
        self.bus = EventBus()
        self.rm = MockRitualManager()
        self.fm = MockFactionManager({0: MockFaction(0)})
        self.mgr.set_systems(ritual_manager=self.rm, faction_manager=self.fm)
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    @patch("systems.event_cascades.random")
    def test_birth_triggers_celebration(self, mock_random):
        mock_random.random.return_value = 0.0
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_BIRTH,
            summary="A new praxan is born",
            faction_id=0,
            timestamp=now,
        ))
        birth_effects = [e for e in self.mgr._pending_effects
                         if e.get("cascade_type") == "birth_celebration"]
        self.assertGreater(len(birth_effects), 0)
        self.assertGreater(birth_effects[0].get("mood_offset", 0), 0)

    @patch("systems.event_cascades.random")
    def test_birth_signals_ritual(self, mock_random):
        mock_random.random.return_value = 0.0
        now = time.time()
        self.bus.publish(GameEvent(
            category=CATEGORY_BIRTH,
            summary="Birth",
            faction_id=0, timestamp=now,
        ))
        self.assertGreater(len(self.rm.birth_signals), 0)


class TestApplyPendingEffects(unittest.TestCase):
    """Test the apply_pending_effects method."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = EventCascadeManager()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_apply_moodlet_to_all(self):
        p1 = MockPraxan(1, faction_id=0)
        p2 = MockPraxan(2, faction_id=1)
        self.mgr._pending_effects.append({
            "scope": "all",
            "cascade_type": "epidemic_anxiety",
            "moodlet_id": "EpidemicFear",
            "mood_offset": -10,
            "duration": 240,
        })
        applied = self.mgr.apply_pending_effects([p1, p2], time.time())
        self.assertEqual(applied, 2)
        self.assertEqual(len(p1.moodlets), 1)
        self.assertEqual(p1.moodlets[0]["id"], "EpidemicFear")
        self.assertEqual(len(p2.moodlets), 1)

    def test_apply_moodlet_faction_scoped(self):
        p1 = MockPraxan(1, faction_id=0)
        p2 = MockPraxan(2, faction_id=1)
        self.mgr._pending_effects.append({
            "scope": "faction",
            "faction_id": 0,
            "cascade_type": "combat_death_mourning",
            "moodlet_id": "FallenInBattle",
            "mood_offset": -8,
            "duration": 300,
        })
        applied = self.mgr.apply_pending_effects([p1, p2], time.time())
        self.assertEqual(applied, 1)
        self.assertEqual(len(p1.moodlets), 1)
        self.assertEqual(len(p2.moodlets), 0)

    def test_apply_moodlet_survivors_scoped(self):
        p1 = MockPraxan(1)
        p2 = MockPraxan(2)
        p3 = MockPraxan(3)
        self.mgr._pending_effects.append({
            "scope": "survivors",
            "survivor_ids": [1, 3],
            "cascade_type": "crisis_resilience",
            "moodlet_id": "HardenedByCrisis",
            "mood_offset": 4,
            "duration": 600,
            "resilience_boost": 0.15,
        })
        self.mgr.apply_pending_effects([p1, p2, p3], time.time())
        self.assertEqual(len(p1.moodlets), 1)
        self.assertEqual(len(p2.moodlets), 0)
        self.assertEqual(len(p3.moodlets), 1)
        self.assertAlmostEqual(p1.resilience, 1.15, places=2)
        self.assertAlmostEqual(p2.resilience, 1.0, places=2)

    def test_apply_memory_event(self):
        p = MockPraxan(1)
        self.mgr._pending_effects.append({
            "scope": "all",
            "cascade_type": "mass_death_trauma",
            "moodlet_id": "CollectiveTrauma",
            "mood_offset": -12,
            "duration": 360,
            "memory_event": "collective_trauma",
            "memory_text": "A wave of death shook the colony",
        })
        self.mgr.apply_pending_effects([p], time.time())
        self.assertEqual(len(p.episodic_memory.entries), 1)
        self.assertEqual(p.episodic_memory.entries[0]["event_type"], "collective_trauma")

    def test_apply_morale_penalty(self):
        p = MockPraxan(1)
        initial_morale = p.morale
        self.mgr._pending_effects.append({
            "scope": "all",
            "cascade_type": "epidemic_anxiety",
            "morale_penalty": 10.0,
        })
        self.mgr.apply_pending_effects([p], time.time())
        self.assertLess(p.morale, initial_morale)

    def test_apply_bond_boost(self):
        p1 = MockPraxan(1, faction_id=0)
        p2 = MockPraxan(2, faction_id=0)
        p3 = MockPraxan(3, faction_id=1)
        self.mgr._pending_effects.append({
            "scope": "faction",
            "faction_id": 0,
            "cascade_type": "birth_celebration",
            "moodlet_id": "NewLifeJoy",
            "mood_offset": 4,
            "duration": 180,
            "bond_boost": 5.0,
        })
        self.mgr.apply_pending_effects([p1, p2, p3], time.time())
        # p1 should have bond boost with p2 (same faction)
        self.assertGreater(p1.bonds.get(2, 50.0), 50.0)
        # p1 should NOT have bond boost with p3 (different faction)
        self.assertNotIn(3, p1.bonds)

    def test_dead_praxans_skipped(self):
        p_alive = MockPraxan(1)
        p_dead = MockPraxan(2, alive=False)
        self.mgr._pending_effects.append({
            "scope": "all",
            "moodlet_id": "Test",
            "mood_offset": -5,
            "duration": 60,
        })
        applied = self.mgr.apply_pending_effects([p_alive, p_dead], time.time())
        self.assertEqual(applied, 1)
        self.assertEqual(len(p_alive.moodlets), 1)
        self.assertEqual(len(p_dead.moodlets), 0)

    def test_pending_effects_cleared_after_apply(self):
        self.mgr._pending_effects.append({
            "scope": "all",
            "moodlet_id": "Test",
            "mood_offset": -5,
            "duration": 60,
        })
        self.mgr.apply_pending_effects([], time.time())
        self.assertEqual(len(self.mgr._pending_effects), 0)

    def test_no_pending_returns_zero(self):
        applied = self.mgr.apply_pending_effects([MockPraxan(1)], time.time())
        self.assertEqual(applied, 0)


class TestSerialization(unittest.TestCase):
    """Test cascade manager serialization / deserialization."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_serialize_empty(self):
        mgr = EventCascadeManager()
        data = mgr.serialize()
        self.assertEqual(data["total_cascades_fired"], 0)
        self.assertEqual(data["cascade_history"], [])
        self.assertEqual(data["cooldowns"], {})
        self.assertEqual(data["recent_deaths"], [])

    def test_serialize_with_state(self):
        mgr = EventCascadeManager()
        now = time.time()
        mgr.total_cascades_fired = 5
        mgr._cooldowns["mass_death_trauma"] = now - 30.0
        mgr._recent_deaths.append({
            "time": now - 10.0, "faction_id": 0, "praxan_id": 1, "cause": "combat",
        })
        data = mgr.serialize()
        self.assertEqual(data["total_cascades_fired"], 5)
        self.assertIn("mass_death_trauma", data["cooldowns"])
        self.assertEqual(len(data["recent_deaths"]), 1)

    def test_restore_roundtrip(self):
        mgr = EventCascadeManager()
        now = time.time()
        mgr.total_cascades_fired = 3
        mgr._cooldowns["epidemic_anxiety"] = now - 20.0
        mgr._recent_deaths.append({
            "time": now - 5.0, "faction_id": 1, "praxan_id": 7, "cause": "disease",
        })
        mgr.cascade_history.append({
            "cascade_id": "epidemic_anxiety", "label": "Epidemic Anxiety",
            "time": now - 20.0, "detail": "test",
        })
        data = mgr.serialize()

        mgr2 = EventCascadeManager()
        mgr2.restore(data)
        self.assertEqual(mgr2.total_cascades_fired, 3)
        self.assertEqual(len(mgr2.cascade_history), 1)
        self.assertIn("epidemic_anxiety", mgr2._cooldowns)
        self.assertEqual(len(mgr2._recent_deaths), 1)
        self.assertEqual(mgr2._recent_deaths[0]["faction_id"], 1)

    def test_restore_empty_data(self):
        mgr = EventCascadeManager()
        mgr.restore({})
        self.assertEqual(mgr.total_cascades_fired, 0)

    def test_restore_none_data(self):
        mgr = EventCascadeManager()
        mgr.restore(None)
        self.assertEqual(mgr.total_cascades_fired, 0)


class TestCooldowns(unittest.TestCase):
    """Test cooldown enforcement across cascades."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_cooldown_check(self):
        mgr = EventCascadeManager()
        now = time.time()
        self.assertTrue(mgr._check_cooldown("test_cascade", 60.0, now))
        mgr._cooldowns["test_cascade"] = now
        self.assertFalse(mgr._check_cooldown("test_cascade", 60.0, now + 30.0))
        self.assertTrue(mgr._check_cooldown("test_cascade", 60.0, now + 61.0))

    def test_fire_cascade_updates_cooldown(self):
        mgr = EventCascadeManager()
        now = time.time()
        mgr._fire_cascade("test_id", now, "test detail")
        self.assertEqual(mgr._cooldowns["test_id"], now)
        self.assertEqual(mgr.total_cascades_fired, 1)
        self.assertEqual(len(mgr.cascade_history), 1)
        self.assertEqual(mgr.cascade_history[0]["cascade_id"], "test_id")


class TestQueryHelpers(unittest.TestCase):
    """Test query and helper methods."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_recent_cascades(self):
        mgr = EventCascadeManager()
        now = time.time()
        for i in range(5):
            mgr._fire_cascade(f"cascade_{i}", now + i, f"detail {i}")
        recent = mgr.recent_cascades(3)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[-1]["cascade_id"], "cascade_4")

    def test_recent_death_count(self):
        mgr = EventCascadeManager()
        self.assertEqual(mgr.recent_death_count, 0)
        mgr._recent_deaths.append({"time": time.time(), "faction_id": 0, "praxan_id": 1, "cause": "x"})
        self.assertEqual(mgr.recent_death_count, 1)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and robustness."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_no_faction_manager_no_crash(self):
        mgr = EventCascadeManager()
        bus = EventBus()
        mgr.attach_event_bus(bus)
        # No faction manager set — should not crash
        now = time.time()
        for i in range(5):
            bus.publish(GameEvent(
                category=CATEGORY_DEATH,
                summary=f"Died {i}",
                praxan_id=i, faction_id=0, timestamp=now,
                metadata={"cause": "combat"},
            ))
        # Should fire but not crash
        self.assertGreaterEqual(mgr.total_cascades_fired, 0)

    def test_no_event_bus_no_crash(self):
        mgr = EventCascadeManager()
        # No event bus attached
        mgr.apply_pending_effects([], time.time())

    def test_empty_praxans_list(self):
        mgr = EventCascadeManager()
        mgr._pending_effects.append({
            "scope": "all",
            "moodlet_id": "Test",
            "mood_offset": -5,
            "duration": 60,
        })
        applied = mgr.apply_pending_effects([], time.time())
        self.assertEqual(applied, 0)

    def test_pending_effects_bounded(self):
        mgr = EventCascadeManager()
        for i in range(100):
            mgr._queue_effect({"scope": "all", "id": i})
        self.assertLessEqual(len(mgr._pending_effects), mgr._max_pending)

    def test_recent_deaths_bounded(self):
        mgr = EventCascadeManager()
        bus = EventBus()
        mgr.attach_event_bus(bus)
        now = time.time()
        for i in range(50):
            bus.publish(GameEvent(
                category=CATEGORY_DEATH,
                summary=f"Died {i}",
                praxan_id=i, faction_id=0, timestamp=now,
                metadata={"cause": "x"},
            ))
        self.assertLessEqual(len(mgr._recent_deaths), mgr._max_recent_deaths)

    def test_famine_warning_with_no_migration_pressure_attr(self):
        """Factions without migration_pressure should not crash."""
        mgr = EventCascadeManager()
        bus = EventBus()
        faction = MockFaction(0)
        delattr(faction, "migration_pressure")
        fm = MockFactionManager({0: faction})
        mgr.set_systems(faction_manager=fm)
        mgr.attach_event_bus(bus)
        now = time.time()
        # This should not crash even without migration_pressure
        bus.publish(GameEvent(
            category=CATEGORY_DISASTER,
            summary="Ecology degradation",
            timestamp=now,
            metadata={"type": "ecology_degradation"},
        ))


if __name__ == "__main__":
    unittest.main()
