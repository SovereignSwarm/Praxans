"""Tests for the Cultural Heritage & Traditions System (systems/traditions.py).

Covers:
- TraditionDef loading from DefDatabase
- FactionTradition serialization/deserialization
- TraditionManager event recording and formation
- Tradition reinforcement
- Tradition decay and removal
- Max traditions per faction enforcement
- Cultural exchange between factions
- Diplomacy effects (shared/conflicting traditions)
- Query methods (get_faction_traditions, get_tradition_effects, etc.)
- Full manager serialization/restoration
- Edge cases
"""

import time
import unittest
from unittest.mock import MagicMock

from events.bus import (
    CATEGORY_CULTURAL_SHIFT,
    CATEGORY_DEATH,
    CATEGORY_DISASTER,
    CATEGORY_WARFARE,
    CATEGORY_BUILDING,
    CATEGORY_MILESTONE,
    CATEGORY_TRADE,
    CATEGORY_DIPLOMACY,
    CATEGORY_PERSONAL,
    EventBus,
    GameEvent,
)
from systems.def_database import DefDatabase
from systems.traditions import (
    TraditionManager,
    FactionTradition,
    clear_cache,
    get_all_tradition_defs,
    get_tradition_def,
    MAX_TRADITIONS_PER_FACTION,
    MIN_STRENGTH_ALIVE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockDiplomacyManager:
    def __init__(self):
        self._standings = {}

    def get_standing(self, fid_a, fid_b):
        key = (min(fid_a, fid_b), max(fid_a, fid_b))
        return self._standings.get(key, 0)

    def set_standing(self, fid_a, fid_b, value):
        key = (min(fid_a, fid_b), max(fid_a, fid_b))
        self._standings[key] = value

    def adjust_standing(self, fid_a, fid_b, delta):
        key = (min(fid_a, fid_b), max(fid_a, fid_b))
        current = self._standings.get(key, 0)
        self._standings[key] = max(-100, min(100, current + delta))


class MockFaction:
    def __init__(self, fid=0):
        self.id = fid
        self.member_ids = []
        self.primary_doctrine = "growth"


class MockFactionManager:
    def __init__(self, factions=None):
        self.factions = {}
        if factions:
            for f in factions:
                self.factions[f.id] = f


class MockNarrativePanel:
    def __init__(self):
        self.messages = []

    def add_message(self, text, category=""):
        self.messages.append({"text": text, "category": category})


class MockAdvisor:
    def __init__(self):
        self.observer_timeline = []


# ---------------------------------------------------------------------------
# Test: Def Loading
# ---------------------------------------------------------------------------

class TestTraditionDefLoading(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_all_defs_loaded(self):
        defs = get_all_tradition_defs()
        self.assertGreaterEqual(len(defs), 10)

    def test_each_def_has_required_fields(self):
        defs = get_all_tradition_defs()
        for tid, tdef in defs.items():
            self.assertIn("id", tdef, f"Missing 'id' in {tid}")
            self.assertIn("name", tdef, f"Missing 'name' in {tid}")
            self.assertIn("trigger_events", tdef, f"Missing 'trigger_events' in {tid}")
            self.assertIn("trigger_threshold", tdef, f"Missing 'trigger_threshold' in {tid}")
            self.assertIn("effects", tdef, f"Missing 'effects' in {tid}")
            self.assertIn("moodlet", tdef, f"Missing 'moodlet' in {tid}")

    def test_get_specific_def(self):
        tdef = get_tradition_def("warrior_spirit")
        self.assertIsNotNone(tdef)
        self.assertEqual(tdef["name"], "Warrior Spirit")

    def test_get_nonexistent_def(self):
        tdef = get_tradition_def("nonexistent_tradition")
        self.assertIsNone(tdef)

    def test_conflicts_are_symmetric(self):
        """If A conflicts with B, B should conflict with A."""
        defs = get_all_tradition_defs()
        for tid, tdef in defs.items():
            for cid in tdef.get("conflicts_with", []):
                conflict_def = defs.get(cid)
                self.assertIsNotNone(conflict_def, f"{tid} conflicts with {cid} but {cid} not found")
                self.assertIn(
                    tid, conflict_def.get("conflicts_with", []),
                    f"{tid} conflicts with {cid} but not vice versa"
                )


# ---------------------------------------------------------------------------
# Test: FactionTradition
# ---------------------------------------------------------------------------

class TestFactionTradition(unittest.TestCase):
    def test_create(self):
        now = 1000.0
        ft = FactionTradition("warrior_spirit", 30.0, now)
        self.assertEqual(ft.tradition_id, "warrior_spirit")
        self.assertEqual(ft.strength, 30.0)
        self.assertEqual(ft.formed_at, now)
        self.assertEqual(ft.last_reinforced, now)

    def test_serialize_deserialize(self):
        now = 1000.0
        ft = FactionTradition("warrior_spirit", 65.0, now - 100, now - 20, now - 5)
        data = ft.to_dict(now)
        self.assertAlmostEqual(data["age_seconds"], 100.0, places=1)
        self.assertAlmostEqual(data["since_reinforced_seconds"], 20.0, places=1)
        self.assertEqual(data["tradition_id"], "warrior_spirit")
        self.assertAlmostEqual(data["strength"], 65.0, places=1)

        restore_time = 2000.0
        restored = FactionTradition.from_dict(data, restore_time)
        self.assertEqual(restored.tradition_id, "warrior_spirit")
        self.assertAlmostEqual(restored.strength, 65.0, places=1)
        self.assertAlmostEqual(restored.formed_at, restore_time - 100.0, places=1)
        self.assertAlmostEqual(restored.last_reinforced, restore_time - 20.0, places=1)


# ---------------------------------------------------------------------------
# Test: TraditionManager — Event Recording & Formation
# ---------------------------------------------------------------------------

class TestTraditionFormation(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_record_event_creates_log(self):
        self.manager.record_event(0, "warfare", self.now)
        self.assertIn(0, self.manager._event_log)

    def test_tradition_forms_when_threshold_met(self):
        """Warrior Spirit needs 3 warfare events in 300s window."""
        for i in range(3):
            self.manager.record_event(0, "warfare", self.now + i)

        # Force evaluation
        self.manager._last_update = 0.0
        fm = MockFactionManager([MockFaction(0)])
        self.manager.update(
            faction_manager=fm,
            current_time=self.now + 5,
        )

        self.assertTrue(self.manager.has_tradition(0, "warrior_spirit"))
        self.assertEqual(self.manager.total_traditions_formed, 1)

    def test_tradition_does_not_form_below_threshold(self):
        """Only 2 events — below threshold of 3."""
        for i in range(2):
            self.manager.record_event(0, "warfare", self.now + i)

        self.manager._last_update = 0.0
        fm = MockFactionManager([MockFaction(0)])
        self.manager.update(faction_manager=fm, current_time=self.now + 5)

        self.assertFalse(self.manager.has_tradition(0, "warrior_spirit"))

    def test_tradition_does_not_form_outside_window(self):
        """Events spread beyond the trigger window should not count."""
        tdef = get_tradition_def("warrior_spirit")
        window = tdef["trigger_window_seconds"]

        self.manager.record_event(0, "warfare", self.now - window - 10)
        self.manager.record_event(0, "warfare", self.now - window - 5)
        self.manager.record_event(0, "warfare", self.now)

        self.manager._last_update = 0.0
        fm = MockFactionManager([MockFaction(0)])
        self.manager.update(faction_manager=fm, current_time=self.now + 1)

        # Only 1 event within the window — not enough
        self.assertFalse(self.manager.has_tradition(0, "warrior_spirit"))

    def test_tradition_publishes_event(self):
        bus = EventBus()
        published = []
        bus.subscribe(CATEGORY_CULTURAL_SHIFT, lambda e: published.append(e))
        self.manager._event_bus = bus

        for i in range(3):
            self.manager.record_event(0, "warfare", self.now + i)

        self.manager._last_update = 0.0
        fm = MockFactionManager([MockFaction(0)])
        self.manager.update(faction_manager=fm, current_time=self.now + 5)

        self.assertTrue(len(published) >= 1)
        self.assertEqual(published[0].metadata["type"], "tradition_formed")

    def test_narrative_panel_notified(self):
        panel = MockNarrativePanel()
        for i in range(3):
            self.manager.record_event(0, "warfare", self.now + i)

        self.manager._last_update = 0.0
        fm = MockFactionManager([MockFaction(0)])
        self.manager.update(
            faction_manager=fm, current_time=self.now + 5,
            narrative_panel=panel,
        )

        self.assertTrue(any("tradition" in m["text"].lower() for m in panel.messages))

    def test_history_recorded_on_formation(self):
        for i in range(3):
            self.manager.record_event(0, "warfare", self.now + i)

        self.manager._last_update = 0.0
        fm = MockFactionManager([MockFaction(0)])
        self.manager.update(faction_manager=fm, current_time=self.now + 5)

        self.assertTrue(len(self.manager.tradition_history) >= 1)
        self.assertEqual(self.manager.tradition_history[0]["type"], "formed")


# ---------------------------------------------------------------------------
# Test: Reinforcement
# ---------------------------------------------------------------------------

class TestTraditionReinforcement(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0
        # Force-create a warrior_spirit tradition
        tdef = get_tradition_def("warrior_spirit")
        ft = FactionTradition("warrior_spirit", 30.0, self.now)
        self.manager._traditions[0] = [ft]

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_reinforcement_on_matching_event(self):
        initial = self.manager._traditions[0][0].strength
        self.manager.record_event(0, "warfare", self.now + 10)
        self.assertGreater(self.manager._traditions[0][0].strength, initial)

    def test_reinforcement_capped_at_max(self):
        self.manager._traditions[0][0].strength = 98.0
        self.manager.record_event(0, "warfare", self.now + 10)
        self.assertLessEqual(self.manager._traditions[0][0].strength, 100.0)

    def test_no_reinforcement_for_non_matching_event(self):
        initial = self.manager._traditions[0][0].strength
        self.manager.record_event(0, "trade_completed", self.now + 10)
        self.assertEqual(self.manager._traditions[0][0].strength, initial)


# ---------------------------------------------------------------------------
# Test: Decay
# ---------------------------------------------------------------------------

class TestTraditionDecay(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_decay_reduces_strength(self):
        ft = FactionTradition("warrior_spirit", 50.0, self.now, self.now, self.now)
        self.manager._traditions[0] = [ft]

        # Advance time past decay interval (60s)
        future = self.now + 120.0
        self.manager._apply_decay(0, future)

        self.assertLess(ft.strength, 50.0)

    def test_tradition_removed_when_strength_too_low(self):
        ft = FactionTradition("warrior_spirit", 5.5, self.now, self.now, self.now)
        self.manager._traditions[0] = [ft]

        # Advance enough to decay below MIN_STRENGTH_ALIVE (0.3/60s × 4 intervals = 1.2)
        future = self.now + 240.0
        self.manager._apply_decay(0, future)

        self.assertEqual(len(self.manager._traditions.get(0, [])), 0)
        self.assertEqual(self.manager.total_traditions_lost, 1)

    def test_decay_history_recorded(self):
        ft = FactionTradition("warrior_spirit", 5.5, self.now, self.now, self.now)
        self.manager._traditions[0] = [ft]

        self.manager._apply_decay(0, self.now + 240.0)

        history = [h for h in self.manager.tradition_history if h["type"] == "lost"]
        self.assertTrue(len(history) >= 1)
        self.assertEqual(history[0]["reason"], "decayed")


# ---------------------------------------------------------------------------
# Test: Max traditions per faction
# ---------------------------------------------------------------------------

class TestMaxTraditions(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_weakest_dropped_when_max_exceeded(self):
        # Manually add MAX traditions
        defs = get_all_tradition_defs()
        tids = list(defs.keys())[:MAX_TRADITIONS_PER_FACTION]

        traditions = []
        for i, tid in enumerate(tids):
            ft = FactionTradition(tid, 30.0 + i * 10, self.now)
            traditions.append(ft)
        self.manager._traditions[0] = traditions
        self.assertEqual(len(self.manager._traditions[0]), MAX_TRADITIONS_PER_FACTION)

        # Now form one more via the _form_tradition method
        extra_tid = list(defs.keys())[MAX_TRADITIONS_PER_FACTION]
        extra_def = defs[extra_tid]
        self.manager._form_tradition(0, extra_tid, extra_def, self.now + 10)

        # Still at max
        self.assertEqual(len(self.manager._traditions[0]), MAX_TRADITIONS_PER_FACTION)
        # The weakest (30.0) should be gone
        ids = {t.tradition_id for t in self.manager._traditions[0]}
        self.assertNotIn(tids[0], ids)
        self.assertIn(extra_tid, ids)


# ---------------------------------------------------------------------------
# Test: Cultural Exchange
# ---------------------------------------------------------------------------

class TestCulturalExchange(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0
        self.diplo = MockDiplomacyManager()
        self.manager.set_systems(diplomacy_manager=self.diplo)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_exchange_requires_friendly_standing(self):
        # Faction 0 has warrior_spirit at strength 60
        ft = FactionTradition("warrior_spirit", 60.0, self.now)
        self.manager._traditions[0] = [ft]
        self.manager._traditions[1] = []

        # Neutral standing — should not spread
        self.diplo.set_standing(0, 1, 0)

        factions = {0: MockFaction(0), 1: MockFaction(1)}
        # Run exchange many times to overcome randomness
        for _ in range(50):
            self.manager._evaluate_cultural_exchange(factions, self.now + 1)

        self.assertFalse(self.manager.has_tradition(1, "warrior_spirit"))

    def test_exchange_can_spread_tradition(self):
        ft = FactionTradition("warrior_spirit", 60.0, self.now)
        self.manager._traditions[0] = [ft]
        self.manager._traditions[1] = []

        # Friendly standing
        self.diplo.set_standing(0, 1, 50)

        factions = {0: MockFaction(0), 1: MockFaction(1)}
        # Run many times to overcome 15% chance
        for i in range(200):
            self.manager._evaluate_cultural_exchange(factions, self.now + i)
            if self.manager.has_tradition(1, "warrior_spirit"):
                break

        self.assertTrue(self.manager.has_tradition(1, "warrior_spirit"))

    def test_exchange_spreads_at_reduced_strength(self):
        ft = FactionTradition("warrior_spirit", 80.0, self.now)
        self.manager._traditions[0] = [ft]
        self.manager._traditions[1] = []

        self.diplo.set_standing(0, 1, 60)

        factions = {0: MockFaction(0), 1: MockFaction(1)}
        for i in range(200):
            self.manager._evaluate_cultural_exchange(factions, self.now + i)
            if self.manager.has_tradition(1, "warrior_spirit"):
                break

        if self.manager.has_tradition(1, "warrior_spirit"):
            spread_strength = self.manager.get_tradition_strength(1, "warrior_spirit")
            self.assertLess(spread_strength, 80.0)


# ---------------------------------------------------------------------------
# Test: Diplomacy Effects
# ---------------------------------------------------------------------------

class TestDiplomacyEffects(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0
        self.diplo = MockDiplomacyManager()
        self.manager.set_systems(diplomacy_manager=self.diplo)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_shared_traditions_improve_standing(self):
        # Both factions have warrior_spirit
        self.manager._traditions[0] = [FactionTradition("warrior_spirit", 50.0, self.now)]
        self.manager._traditions[1] = [FactionTradition("warrior_spirit", 50.0, self.now)]

        self.diplo.set_standing(0, 1, 0)
        factions = {0: MockFaction(0), 1: MockFaction(1)}
        self.manager._apply_diplomacy_effects(factions)

        self.assertGreater(self.diplo.get_standing(0, 1), 0)

    def test_conflicting_traditions_decrease_standing(self):
        # Faction 0 has warrior_spirit, faction 1 has peacekeepers_way
        self.manager._traditions[0] = [FactionTradition("warrior_spirit", 50.0, self.now)]
        self.manager._traditions[1] = [FactionTradition("peacekeepers_way", 50.0, self.now)]

        self.diplo.set_standing(0, 1, 0)
        factions = {0: MockFaction(0), 1: MockFaction(1)}
        self.manager._apply_diplomacy_effects(factions)

        self.assertLess(self.diplo.get_standing(0, 1), 0)


# ---------------------------------------------------------------------------
# Test: Query Methods
# ---------------------------------------------------------------------------

class TestTraditionQueries(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0
        self.manager._traditions[0] = [
            FactionTradition("warrior_spirit", 80.0, self.now),
            FactionTradition("harvest_pride", 50.0, self.now),
        ]

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_get_faction_traditions(self):
        result = self.manager.get_faction_traditions(0)
        self.assertEqual(len(result), 2)
        names = {r["name"] for r in result}
        self.assertIn("Warrior Spirit", names)
        self.assertIn("Harvest Pride", names)

    def test_get_tradition_effects_aggregated(self):
        effects = self.manager.get_tradition_effects(0)
        # Both provide mood_offset effects
        self.assertIn("mood_offset", effects)
        # Warrior spirit at 80% strength: 3 * 0.8 = 2.4
        # Harvest pride at 50% strength: 4 * 0.5 = 2.0
        # Total: 4.4
        self.assertAlmostEqual(effects["mood_offset"], 4.4, places=1)

    def test_get_tradition_effects_skill_xp_bonus(self):
        effects = self.manager.get_tradition_effects(0)
        self.assertIn("skill_xp_bonus", effects)
        xp = effects["skill_xp_bonus"]
        # Warrior: combat 0.2 * 0.8 = 0.16
        self.assertAlmostEqual(xp.get("combat", 0), 0.16, places=2)
        # Harvest: gathering 0.15 * 0.5 = 0.075
        self.assertAlmostEqual(xp.get("gathering", 0), 0.075, places=3)

    def test_get_tradition_moodlets(self):
        moodlets = self.manager.get_tradition_moodlets(0)
        self.assertEqual(len(moodlets), 2)
        ids = {m["id"] for m in moodlets}
        self.assertIn("TraditionWarriorSpirit", ids)
        self.assertIn("TraditionHarvestPride", ids)

    def test_has_tradition(self):
        self.assertTrue(self.manager.has_tradition(0, "warrior_spirit"))
        self.assertFalse(self.manager.has_tradition(0, "scholars_path"))
        self.assertFalse(self.manager.has_tradition(1, "warrior_spirit"))

    def test_get_tradition_strength(self):
        self.assertAlmostEqual(
            self.manager.get_tradition_strength(0, "warrior_spirit"), 80.0
        )
        self.assertEqual(
            self.manager.get_tradition_strength(0, "nonexistent"), 0.0
        )

    def test_get_all_faction_ids_with_traditions(self):
        ids = self.manager.get_all_faction_ids_with_traditions()
        self.assertIn(0, ids)
        self.assertNotIn(1, ids)

    def test_empty_faction_returns_empty(self):
        self.assertEqual(self.manager.get_faction_traditions(99), [])
        self.assertEqual(self.manager.get_tradition_effects(99), {})
        self.assertEqual(self.manager.get_tradition_moodlets(99), [])


# ---------------------------------------------------------------------------
# Test: Serialization / Restoration
# ---------------------------------------------------------------------------

class TestTraditionSerialization(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_serialize_empty(self):
        data = self.manager.serialize(self.now)
        self.assertIn("traditions", data)
        self.assertEqual(len(data["traditions"]), 0)

    def test_serialize_with_traditions(self):
        self.manager._traditions[0] = [
            FactionTradition("warrior_spirit", 65.0, self.now - 50, self.now - 10),
        ]
        self.manager.total_traditions_formed = 3
        self.manager.total_traditions_lost = 1

        data = self.manager.serialize(self.now)
        self.assertIn("0", data["traditions"])
        self.assertEqual(len(data["traditions"]["0"]), 1)
        self.assertEqual(data["total_formed"], 3)
        self.assertEqual(data["total_lost"], 1)

    def test_restore_round_trip(self):
        self.manager._traditions[0] = [
            FactionTradition("warrior_spirit", 65.0, self.now - 50, self.now - 10),
            FactionTradition("harvest_pride", 40.0, self.now - 30, self.now - 5),
        ]
        self.manager._traditions[2] = [
            FactionTradition("scholars_path", 55.0, self.now - 100),
        ]
        self.manager.total_traditions_formed = 5
        self.manager.total_traditions_lost = 2

        data = self.manager.serialize(self.now)

        # Restore into fresh manager
        new_mgr = TraditionManager()
        restore_time = self.now + 100.0
        new_mgr.restore(data, restore_time)

        self.assertTrue(new_mgr.has_tradition(0, "warrior_spirit"))
        self.assertTrue(new_mgr.has_tradition(0, "harvest_pride"))
        self.assertTrue(new_mgr.has_tradition(2, "scholars_path"))
        self.assertEqual(new_mgr.total_traditions_formed, 5)
        self.assertEqual(new_mgr.total_traditions_lost, 2)

        # Check strength preserved
        self.assertAlmostEqual(
            new_mgr.get_tradition_strength(0, "warrior_spirit"), 65.0, places=1
        )

    def test_restore_preserves_timing(self):
        self.manager._traditions[0] = [
            FactionTradition("warrior_spirit", 50.0, self.now - 200, self.now - 30, self.now - 10),
        ]
        data = self.manager.serialize(self.now)

        new_mgr = TraditionManager()
        restore_time = 8000.0
        new_mgr.restore(data, restore_time)

        ft = new_mgr._traditions[0][0]
        self.assertAlmostEqual(ft.formed_at, restore_time - 200.0, places=1)
        self.assertAlmostEqual(ft.last_reinforced, restore_time - 30.0, places=1)
        self.assertAlmostEqual(ft.last_decay_time, restore_time - 10.0, places=1)


# ---------------------------------------------------------------------------
# Test: EventBus Integration
# ---------------------------------------------------------------------------

class TestEventBusIntegration(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.bus = EventBus()
        self.manager.attach_event_bus(self.bus)
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_death_event_logged(self):
        event = GameEvent(
            category=CATEGORY_DEATH,
            summary="Praxan died",
            faction_id=0,
            praxan_id=1,
            timestamp=self.now,
            metadata={"cause": "starvation"},
        )
        self.bus.publish(event)
        self.assertIn("death", self.manager._event_log.get(0, {}))

    def test_combat_death_logged_separately(self):
        event = GameEvent(
            category=CATEGORY_DEATH,
            summary="Praxan died in combat",
            faction_id=0,
            praxan_id=1,
            timestamp=self.now,
            metadata={"cause": "combat"},
        )
        self.bus.publish(event)
        logs = self.manager._event_log.get(0, {})
        self.assertIn("death", logs)
        self.assertIn("combat_death", logs)

    def test_warfare_event_logged_for_both_factions(self):
        event = GameEvent(
            category=CATEGORY_WARFARE,
            summary="Raid completed",
            timestamp=self.now,
            metadata={
                "attacker_faction_id": 0,
                "defender_faction_id": 1,
            },
        )
        self.bus.publish(event)
        self.assertIn("warfare", self.manager._event_log.get(0, {}))
        self.assertIn("warfare", self.manager._event_log.get(1, {}))

    def test_building_event_logged(self):
        event = GameEvent(
            category=CATEGORY_BUILDING,
            summary="Building completed",
            faction_id=0,
            timestamp=self.now,
        )
        self.bus.publish(event)
        self.assertIn("building_completed", self.manager._event_log.get(0, {}))

    def test_milestone_tech_event_logged(self):
        event = GameEvent(
            category=CATEGORY_MILESTONE,
            summary="Tech unlocked",
            faction_id=0,
            timestamp=self.now,
            metadata={"type": "tech_unlocked"},
        )
        self.bus.publish(event)
        self.assertIn("tech_unlocked", self.manager._event_log.get(0, {}))

    def test_trade_event_logged_both_factions(self):
        event = GameEvent(
            category=CATEGORY_TRADE,
            summary="Trade completed",
            faction_id=0,
            timestamp=self.now,
            metadata={"other_faction_id": 1},
        )
        self.bus.publish(event)
        self.assertIn("trade_completed", self.manager._event_log.get(0, {}))
        self.assertIn("trade_completed", self.manager._event_log.get(1, {}))

    def test_diplomacy_treaty_event_logged(self):
        event = GameEvent(
            category=CATEGORY_DIPLOMACY,
            summary="Treaty signed",
            faction_id=0,
            timestamp=self.now,
            metadata={"type": "treaty_signed", "other_faction_id": 1},
        )
        self.bus.publish(event)
        self.assertIn("treaty_signed", self.manager._event_log.get(0, {}))
        self.assertIn("treaty_signed", self.manager._event_log.get(1, {}))


# ---------------------------------------------------------------------------
# Test: Full Update Cycle
# ---------------------------------------------------------------------------

class TestFullUpdateCycle(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_update_interval_respected(self):
        """Update should be skipped if called too soon."""
        fm = MockFactionManager([MockFaction(0)])
        self.manager._last_update = self.now - 10.0  # Only 10s ago
        self.manager.record_event(0, "warfare", self.now)
        self.manager.record_event(0, "warfare", self.now + 1)
        self.manager.record_event(0, "warfare", self.now + 2)

        self.manager.update(faction_manager=fm, current_time=self.now + 5)
        # Should NOT have formed — update was too recent
        self.assertFalse(self.manager.has_tradition(0, "warrior_spirit"))

    def test_full_lifecycle(self):
        """Form → reinforce → decay → removal."""
        fm = MockFactionManager([MockFaction(0)])

        # Form
        for i in range(3):
            self.manager.record_event(0, "warfare", self.now + i)
        self.manager._last_update = 0.0
        self.manager.update(faction_manager=fm, current_time=self.now + 5)
        self.assertTrue(self.manager.has_tradition(0, "warrior_spirit"))

        # Reinforce
        initial = self.manager.get_tradition_strength(0, "warrior_spirit")
        self.manager.record_event(0, "warfare", self.now + 50)
        reinforced = self.manager.get_tradition_strength(0, "warrior_spirit")
        self.assertGreater(reinforced, initial)

        # Decay — advance time far enough
        self.manager._last_update = 0.0
        far_future = self.now + 50000.0  # very far future
        self.manager.update(faction_manager=fm, current_time=far_future)
        # Should have decayed to nothing
        self.assertFalse(self.manager.has_tradition(0, "warrior_spirit"))

    def test_observer_timeline_updated(self):
        advisor = MockAdvisor()
        fm = MockFactionManager([MockFaction(0)])

        for i in range(3):
            self.manager.record_event(0, "warfare", self.now + i)
        self.manager._last_update = 0.0
        self.manager.update(
            faction_manager=fm, current_time=self.now + 5, advisor=advisor
        )

        self.assertTrue(len(advisor.observer_timeline) >= 1)


# ---------------------------------------------------------------------------
# Test: Faction Cleanup
# ---------------------------------------------------------------------------

class TestFactionCleanup(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_remove_faction_cleans_traditions(self):
        self.manager._traditions[0] = [
            FactionTradition("warrior_spirit", 50.0, self.now),
        ]
        self.manager._event_log[0] = {"warfare": [self.now]}

        self.manager.remove_faction(0)

        self.assertNotIn(0, self.manager._traditions)
        self.assertNotIn(0, self.manager._event_log)

    def test_remove_nonexistent_faction_no_error(self):
        self.manager.remove_faction(999)  # Should not raise


# ---------------------------------------------------------------------------
# Test: Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = TraditionManager()
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_update_with_no_factions(self):
        """Should not crash with empty faction manager."""
        fm = MockFactionManager([])
        self.manager._last_update = 0.0
        self.manager.update(faction_manager=fm, current_time=self.now)

    def test_update_with_no_faction_manager(self):
        """Should not crash with None faction manager."""
        self.manager._last_update = 0.0
        self.manager.update(faction_manager=None, current_time=self.now)

    def test_record_event_with_none_faction(self):
        """Should silently ignore None faction_id."""
        self.manager._log_event(None, "warfare", self.now)
        self.assertEqual(len(self.manager._event_log), 0)

    def test_multiple_traditions_form_independently(self):
        """Different tradition types can form for the same faction."""
        fm = MockFactionManager([MockFaction(0)])

        # Trigger warrior_spirit (3 warfare events)
        for i in range(3):
            self.manager.record_event(0, "warfare", self.now + i)

        # Trigger builders_legacy (5 building events)
        for i in range(5):
            self.manager.record_event(0, "building_completed", self.now + i)

        self.manager._last_update = 0.0
        self.manager.update(faction_manager=fm, current_time=self.now + 10)

        self.assertTrue(self.manager.has_tradition(0, "warrior_spirit"))
        self.assertTrue(self.manager.has_tradition(0, "builders_legacy"))

    def test_restore_with_empty_data(self):
        """Restore from empty dict should not crash."""
        self.manager.restore({}, self.now)
        self.assertEqual(len(self.manager._traditions), 0)

    def test_restore_with_invalid_faction_id(self):
        """Non-integer faction IDs in snapshot should be skipped."""
        data = {
            "traditions": {
                "not_a_number": [{"tradition_id": "warrior_spirit", "strength": 50}],
            }
        }
        self.manager.restore(data, self.now)
        self.assertEqual(len(self.manager._traditions), 0)

    def test_duplicate_tradition_not_formed(self):
        """A tradition that already exists should not form again."""
        ft = FactionTradition("warrior_spirit", 50.0, self.now)
        self.manager._traditions[0] = [ft]

        for i in range(5):
            self.manager.record_event(0, "warfare", self.now + i)

        self.manager._last_update = 0.0
        fm = MockFactionManager([MockFaction(0)])
        self.manager.update(faction_manager=fm, current_time=self.now + 10)

        warrior_count = sum(
            1 for t in self.manager._traditions.get(0, [])
            if t.tradition_id == "warrior_spirit"
        )
        self.assertEqual(warrior_count, 1)

    def test_event_log_pruned_on_update(self):
        """Old events beyond max window should be pruned."""
        self.manager.record_event(0, "warfare", self.now - 9999)

        self.manager._last_update = 0.0
        fm = MockFactionManager([MockFaction(0)])
        self.manager.update(faction_manager=fm, current_time=self.now)

        # Old event should be pruned
        logs = self.manager._event_log.get(0, {})
        warfare_times = logs.get("warfare", [])
        self.assertEqual(len(warfare_times), 0)


if __name__ == "__main__":
    unittest.main()
