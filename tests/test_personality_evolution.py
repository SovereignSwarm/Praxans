"""Tests for the Personality Evolution System (systems/personality_evolution.py).

Covers:
- PersonalityShiftDef loading from DefDatabase
- Entity queue draining with life-stage scaling
- Interaction shift queuing (via queue_interaction_shifts)
- EventBus death/ritual handlers
- Natural drift toward 0.5
- Threshold crossing detection (zone transitions → memory + moodlet)
- Serialization/restoration
- Edge cases (no defs, empty queue, infant immunity, etc.)
"""

import time
import unittest
from unittest.mock import MagicMock

from events.bus import (
    CATEGORY_DEATH,
    CATEGORY_CULTURAL_SHIFT,
    EventBus,
    GameEvent,
)
from systems.def_database import DefDatabase
from systems.personality_evolution import (
    PersonalityEvolutionManager,
    clear_cache,
    get_shift_def,
    get_interaction_shifts,
    get_entity_shifts,
    queue_interaction_shifts,
    _zone,
    _clamp,
    _EVAL_INTERVAL,
    _DRIFT_RATE,
    _TRAITS,
    _STAGE_SCALE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockPraxan:
    def __init__(self, pid=0, x=0.0, y=0.0, faction_id=0):
        self.id = pid
        self.x = x
        self.y = y
        self.alive = True
        self.name = f"Praxan_{pid}"
        self.faction_id = faction_id
        self.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        self.traits = []
        self.moodlets = []
        self.life_stage = "adult"
        self.relationships = {}
        self._pending_personality_shifts = []
        self.episodic_memory = MagicMock()

    def add_moodlet(self, name, value, duration, current_time):
        self.moodlets.append({
            "name": name,
            "value": value,
            "duration": duration,
            "start_time": current_time,
        })


# ---------------------------------------------------------------------------
# Tests — Def Loading
# ---------------------------------------------------------------------------

class TestPersonalityShiftDefLoading(unittest.TestCase):

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_defs_loaded(self):
        """PersonalityShiftDef entries load from DefDatabase."""
        sdef = get_shift_def("deep_conversation_sociability")
        self.assertIsNotNone(sdef)
        self.assertEqual(sdef["trait"], "sociability")

    def test_shift_value_is_float(self):
        sdef = get_shift_def("deep_conversation_sociability")
        self.assertIsInstance(sdef["shift"], (int, float))
        self.assertGreater(sdef["shift"], 0)

    def test_all_defs_have_required_fields(self):
        from systems.personality_evolution import _load_defs, _shift_def_cache
        _load_defs()
        for def_id, sdef in _shift_def_cache.items():
            self.assertIn("id", sdef, f"{def_id} missing 'id'")
            self.assertIn("trait", sdef, f"{def_id} missing 'trait'")
            self.assertIn("shift", sdef, f"{def_id} missing 'shift'")
            self.assertIn("trigger", sdef, f"{def_id} missing 'trigger'")
            self.assertIn(sdef["trait"], _TRAITS, f"{def_id} has invalid trait '{sdef['trait']}'")

    def test_interaction_shift_map(self):
        """Interaction shifts load correctly."""
        shifts = get_interaction_shifts("deep_conversation")
        self.assertTrue(len(shifts) > 0)
        self.assertEqual(shifts[0]["trait"], "sociability")

    def test_entity_shift_map(self):
        """Entity shifts load correctly."""
        shifts = get_entity_shifts("skill_level_up")
        self.assertTrue(len(shifts) > 0)
        traits = {s["trait"] for s in shifts}
        self.assertIn("curiosity", traits)

    def test_unknown_interaction_returns_empty(self):
        shifts = get_interaction_shifts("nonexistent_interaction")
        self.assertEqual(shifts, [])

    def test_unknown_entity_trigger_returns_empty(self):
        shifts = get_entity_shifts("nonexistent_trigger")
        self.assertEqual(shifts, [])


# ---------------------------------------------------------------------------
# Tests — Utility Functions
# ---------------------------------------------------------------------------

class TestUtilities(unittest.TestCase):

    def test_clamp_within_range(self):
        self.assertEqual(_clamp(0.5), 0.5)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-0.1), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(1.5), 1.0)

    def test_zone_boundaries(self):
        self.assertEqual(_zone(0.0), 0)
        self.assertEqual(_zone(0.24), 0)
        self.assertEqual(_zone(0.25), 1)
        self.assertEqual(_zone(0.49), 1)
        self.assertEqual(_zone(0.50), 2)
        self.assertEqual(_zone(0.74), 2)
        self.assertEqual(_zone(0.75), 3)
        self.assertEqual(_zone(1.0), 3)


# ---------------------------------------------------------------------------
# Tests — Entity Queue Draining
# ---------------------------------------------------------------------------

class TestEntityQueue(unittest.TestCase):

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = PersonalityEvolutionManager()
        self.mgr.attach_event_bus(self.bus)
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_drain_skill_level_up(self):
        """Draining entity:skill_level_up shifts curiosity and diligence."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        p._pending_personality_shifts = ["entity:skill_level_up"]
        self.mgr.update([p], current_time=self.now)
        # Both curiosity and diligence should increase
        self.assertGreater(p.personality["curiosity"], 0.5)
        self.assertGreater(p.personality["diligence"], 0.5)
        self.assertEqual(p.personality["sociability"], 0.5)

    def test_drain_mental_break(self):
        """Draining entity:mental_break reduces diligence and sociability."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        p._pending_personality_shifts = ["entity:mental_break"]
        self.mgr.update([p], current_time=self.now)
        self.assertLess(p.personality["diligence"], 0.5)
        self.assertLess(p.personality["sociability"], 0.5)

    def test_drain_clears_queue(self):
        """Queue is emptied after draining."""
        p = MockPraxan(pid=0)
        p._pending_personality_shifts = ["entity:skill_level_up"]
        self.mgr.update([p], current_time=self.now)
        self.assertEqual(len(p._pending_personality_shifts), 0)

    def test_youth_amplified_shift(self):
        """Youth receive 1.5x shift magnitude."""
        adult = MockPraxan(pid=0)
        adult.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        adult._pending_personality_shifts = ["entity:skill_level_up"]

        youth = MockPraxan(pid=1)
        youth.life_stage = "youth"
        youth.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        youth._pending_personality_shifts = ["entity:skill_level_up"]

        self.mgr.update([adult, youth], current_time=self.now)

        adult_delta = adult.personality["curiosity"] - 0.5
        youth_delta = youth.personality["curiosity"] - 0.5
        self.assertAlmostEqual(youth_delta / adult_delta, 1.5, places=2)

    def test_elder_reduced_shift(self):
        """Elders receive 0.3x shift magnitude."""
        adult = MockPraxan(pid=0)
        adult.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        adult._pending_personality_shifts = ["entity:skill_level_up"]

        elder = MockPraxan(pid=1)
        elder.life_stage = "elder"
        elder.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        elder._pending_personality_shifts = ["entity:skill_level_up"]

        self.mgr.update([adult, elder], current_time=self.now)

        adult_delta = adult.personality["curiosity"] - 0.5
        elder_delta = elder.personality["curiosity"] - 0.5
        self.assertAlmostEqual(elder_delta / adult_delta, 0.3, places=2)

    def test_infant_immune(self):
        """Infants don't evolve personality."""
        p = MockPraxan(pid=0)
        p.life_stage = "infant"
        p.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        p._pending_personality_shifts = ["entity:skill_level_up"]
        self.mgr.update([p], current_time=self.now)
        self.assertEqual(p.personality["curiosity"], 0.5)
        self.assertEqual(p._pending_personality_shifts, [])

    def test_multiple_shifts_accumulate(self):
        """Multiple queued shifts apply additively."""
        # Prevent drift by setting last_eval_time close to now
        self.mgr._last_eval_time = self.now

        p_double = MockPraxan(pid=0)
        p_double.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        p_double._pending_personality_shifts = [
            "entity:skill_level_up",
            "entity:skill_level_up",
        ]

        p_single = MockPraxan(pid=1)
        p_single.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        p_single._pending_personality_shifts = ["entity:skill_level_up"]

        self.mgr.update([p_double, p_single], current_time=self.now)

        double_delta = p_double.personality["curiosity"] - 0.5
        single_delta = p_single.personality["curiosity"] - 0.5
        self.assertAlmostEqual(double_delta / single_delta, 2.0, places=2)

    def test_shift_clamped_at_bounds(self):
        """Shifts clamp personality to [0, 1]."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.99, "sociability": 0.5, "diligence": 0.5}
        p._pending_personality_shifts = ["entity:skill_level_up"]
        self.mgr.update([p], current_time=self.now)
        self.assertLessEqual(p.personality["curiosity"], 1.0)

    def test_dead_praxan_skipped(self):
        """Dead praxans are not processed."""
        p = MockPraxan(pid=0)
        p.alive = False
        p.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        p._pending_personality_shifts = ["entity:skill_level_up"]
        self.mgr.update([p], current_time=self.now)
        self.assertEqual(p.personality["curiosity"], 0.5)


# ---------------------------------------------------------------------------
# Tests — Interaction Shift Queuing
# ---------------------------------------------------------------------------

class TestInteractionShiftQueuing(unittest.TestCase):

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_deep_conversation_queues_both(self):
        """Deep conversation queues shifts on both initiator and target."""
        init = MockPraxan(pid=0)
        targ = MockPraxan(pid=1)
        queue_interaction_shifts(init, targ, "deep_conversation")
        self.assertTrue(len(init._pending_personality_shifts) > 0)
        self.assertTrue(len(targ._pending_personality_shifts) > 0)

    def test_insult_queues_target_only(self):
        """Insult queues shift on target only (not initiator)."""
        init = MockPraxan(pid=0)
        targ = MockPraxan(pid=1)
        queue_interaction_shifts(init, targ, "insult")
        # Insult target: sociability -0.015 on target only
        targ_triggers = targ._pending_personality_shifts
        init_triggers = init._pending_personality_shifts
        # Target should have the insult trigger
        self.assertTrue(any("insult" in t for t in targ_triggers))
        # Initiator should NOT have the insult-target trigger
        insult_target_def = get_shift_def("insult_target_sociability")
        self.assertIsNotNone(insult_target_def)
        self.assertEqual(insult_target_def.get("target"), "target")

    def test_comfort_queues_initiator(self):
        """Comfort queues shift on initiator (the one comforting)."""
        init = MockPraxan(pid=0)
        targ = MockPraxan(pid=1)
        queue_interaction_shifts(init, targ, "comfort")
        self.assertTrue(len(init._pending_personality_shifts) > 0)

    def test_unknown_interaction_no_queue(self):
        """Unknown interaction doesn't queue anything."""
        init = MockPraxan(pid=0)
        targ = MockPraxan(pid=1)
        queue_interaction_shifts(init, targ, "nonexistent")
        self.assertEqual(len(init._pending_personality_shifts), 0)
        self.assertEqual(len(targ._pending_personality_shifts), 0)

    def test_no_crash_without_queue_attribute(self):
        """Gracefully handles praxan without _pending_personality_shifts."""
        class NakedPraxan:
            id = 0
        init = NakedPraxan()
        targ = NakedPraxan()
        # Should not raise
        queue_interaction_shifts(init, targ, "deep_conversation")


# ---------------------------------------------------------------------------
# Tests — Natural Drift
# ---------------------------------------------------------------------------

class TestDrift(unittest.TestCase):

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = PersonalityEvolutionManager()
        self.mgr.attach_event_bus(self.bus)
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_drift_toward_center(self):
        """Traits drift toward 0.5 over time."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.8, "sociability": 0.2, "diligence": 0.5}
        # Force eval by setting last_eval far in past
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=self.now)
        self.assertLess(p.personality["curiosity"], 0.8)
        self.assertGreater(p.personality["sociability"], 0.2)
        # Diligence at 0.5 should stay put (within drift tolerance)
        self.assertAlmostEqual(p.personality["diligence"], 0.5, places=3)

    def test_drift_not_applied_before_interval(self):
        """Drift only applies when eval interval has elapsed."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.8, "sociability": 0.5, "diligence": 0.5}
        self.mgr._last_eval_time = self.now  # just evaluated
        self.mgr.update([p], current_time=self.now + 1)  # only 1 second later
        # No drift should have happened (no queued shifts either)
        self.assertEqual(p.personality["curiosity"], 0.8)


# ---------------------------------------------------------------------------
# Tests — Threshold Crossing
# ---------------------------------------------------------------------------

class TestThresholdCrossing(unittest.TestCase):

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = PersonalityEvolutionManager()
        self.mgr.attach_event_bus(self.bus)
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_upward_crossing_records_memory(self):
        """Crossing from zone 2 (0.50-0.75) to zone 3 (0.75+) records memory."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.74, "sociability": 0.5, "diligence": 0.5}

        # First update — records initial zones (no crossings)
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=self.now)
        p.episodic_memory.record.reset_mock()

        # Push curiosity past 0.75 threshold
        p.personality["curiosity"] = 0.76
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=self.now + _EVAL_INTERVAL + 1)

        # Should have recorded a memory
        p.episodic_memory.record.assert_called()
        call_args = p.episodic_memory.record.call_args
        self.assertIn("curiosity_grew", call_args[0][0])

    def test_downward_crossing_records_memory(self):
        """Crossing from zone 1 (0.25-0.50) to zone 0 (<0.25) records memory."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.5, "sociability": 0.26, "diligence": 0.5}

        # First update — records initial zones
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=self.now)
        p.episodic_memory.record.reset_mock()

        # Push sociability below 0.25
        p.personality["sociability"] = 0.23
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=self.now + _EVAL_INTERVAL + 1)

        p.episodic_memory.record.assert_called()
        call_args = p.episodic_memory.record.call_args
        self.assertIn("sociability_faded", call_args[0][0])

    def test_crossing_applies_moodlet(self):
        """Threshold crossing applies PersonalityGrowth or PersonalityDecline moodlet."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.74, "sociability": 0.5, "diligence": 0.5}

        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=self.now)

        p.personality["curiosity"] = 0.76
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=self.now + _EVAL_INTERVAL + 1)

        moodlet_names = [m["name"] for m in p.moodlets]
        self.assertIn("PersonalityGrowth", moodlet_names)

    def test_no_crossing_no_memory(self):
        """No threshold crossing means no memory or moodlet."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.6, "sociability": 0.6, "diligence": 0.6}

        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=self.now)
        p.episodic_memory.record.reset_mock()

        # Move slightly but stay in same zone (2)
        p.personality["curiosity"] = 0.65
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=self.now + _EVAL_INTERVAL + 1)

        p.episodic_memory.record.assert_not_called()
        self.assertEqual(len(p.moodlets), 0)

    def test_first_update_no_crossing(self):
        """First update only records initial zones, no crossings."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.8, "sociability": 0.1, "diligence": 0.5}

        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=self.now)

        # No memory should be recorded on first encounter
        p.episodic_memory.record.assert_not_called()
        self.assertEqual(len(p.moodlets), 0)


# ---------------------------------------------------------------------------
# Tests — EventBus Death Handler
# ---------------------------------------------------------------------------

class TestDeathHandler(unittest.TestCase):

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = PersonalityEvolutionManager()
        self.mgr.attach_event_bus(self.bus)
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_partner_death_reduces_sociability(self):
        """Partner death reduces surviving partner's sociability."""
        survivor = MockPraxan(pid=0)
        survivor.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        survivor.relationships = {1: "partner"}

        # Publish death event for praxan 1
        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Praxan_1 died",
            praxan_id=1,
        ))

        self.mgr.update([survivor], current_time=self.now)
        self.assertLess(survivor.personality["sociability"], 0.5)

    def test_child_death_reduces_sociability(self):
        """Child death reduces parent's sociability."""
        parent = MockPraxan(pid=0)
        parent.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        parent.relationships = {2: "child"}

        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Praxan_2 died",
            praxan_id=2,
        ))

        self.mgr.update([parent], current_time=self.now)
        self.assertLess(parent.personality["sociability"], 0.5)

    def test_unrelated_death_no_effect(self):
        """Death of unrelated praxan has no personality effect."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        p.relationships = {}

        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Praxan_3 died",
            praxan_id=3,
        ))

        self.mgr.update([p], current_time=self.now)
        self.assertEqual(p.personality["sociability"], 0.5)


# ---------------------------------------------------------------------------
# Tests — EventBus Ritual Handler
# ---------------------------------------------------------------------------

class TestRitualHandler(unittest.TestCase):

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = PersonalityEvolutionManager()
        self.mgr.attach_event_bus(self.bus)
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_ritual_boosts_faction_sociability(self):
        """Ritual event boosts sociability for faction members."""
        p = MockPraxan(pid=0, faction_id=1)
        p.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}

        self.bus.publish(GameEvent(
            category=CATEGORY_CULTURAL_SHIFT,
            summary="Harvest Thanksgiving",
            metadata={"ritual_id": "harvest_thanksgiving", "participants": 5},
            faction_id=1,
        ))

        self.mgr.update([p], current_time=self.now)
        self.assertGreater(p.personality["sociability"], 0.5)

    def test_ritual_no_effect_on_other_faction(self):
        """Ritual doesn't affect praxans from other factions."""
        p = MockPraxan(pid=0, faction_id=2)  # Different faction
        p.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}

        self.bus.publish(GameEvent(
            category=CATEGORY_CULTURAL_SHIFT,
            summary="Harvest Thanksgiving",
            metadata={"ritual_id": "harvest_thanksgiving", "participants": 5},
            faction_id=1,
        ))

        self.mgr.update([p], current_time=self.now)
        self.assertEqual(p.personality["sociability"], 0.5)


# ---------------------------------------------------------------------------
# Tests — Serialization
# ---------------------------------------------------------------------------

class TestSerialization(unittest.TestCase):

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_serialize_empty(self):
        mgr = PersonalityEvolutionManager()
        data = mgr.serialize()
        self.assertIn("prev_zones", data)
        self.assertEqual(len(data["prev_zones"]), 0)

    def test_serialize_with_zones(self):
        mgr = PersonalityEvolutionManager()
        mgr._prev_zones = {0: {"curiosity": 2, "sociability": 1, "diligence": 3}}
        data = mgr.serialize()
        self.assertIn("0", data["prev_zones"])
        self.assertEqual(data["prev_zones"]["0"]["curiosity"], 2)

    def test_restore_round_trip(self):
        mgr1 = PersonalityEvolutionManager()
        mgr1._prev_zones = {0: {"curiosity": 2, "sociability": 1, "diligence": 3}}
        data = mgr1.serialize()

        mgr2 = PersonalityEvolutionManager()
        mgr2.restore(data, current_time=time.time())
        self.assertEqual(mgr2._prev_zones[0]["curiosity"], 2)

    def test_restore_empty(self):
        mgr = PersonalityEvolutionManager()
        mgr.restore({}, current_time=time.time())
        self.assertEqual(len(mgr._prev_zones), 0)


# ---------------------------------------------------------------------------
# Tests — Cleanup
# ---------------------------------------------------------------------------

class TestCleanup(unittest.TestCase):

    def test_cleanup_praxan(self):
        mgr = PersonalityEvolutionManager()
        mgr._prev_zones = {0: {"curiosity": 2}, 1: {"curiosity": 3}}
        mgr.cleanup_praxan(0)
        self.assertNotIn(0, mgr._prev_zones)
        self.assertIn(1, mgr._prev_zones)

    def test_cleanup_noop_for_unknown_id(self):
        """cleanup_praxan on an untracked id doesn't raise."""
        mgr = PersonalityEvolutionManager()
        mgr._prev_zones = {0: {"curiosity": 2}}
        mgr.cleanup_praxan(999)  # id not in _prev_zones — should not raise
        self.assertIn(0, mgr._prev_zones)

    def test_dead_praxan_zones_not_retained_after_update(self):
        """After cleanup_praxan is called for a dead entity, its zone data is gone."""
        mgr = PersonalityEvolutionManager()
        # Seed zone data for praxan 0 as if it had been tracked
        mgr._prev_zones = {0: {"curiosity": 2, "sociability": 1, "diligence": 3}}
        mgr.cleanup_praxan(0)
        # After cleanup the serialized snapshot must not contain the dead praxan's zones
        snapshot = mgr.serialize()
        self.assertNotIn("0", snapshot["prev_zones"])


# ---------------------------------------------------------------------------
# Tests — End-to-End Integration
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = PersonalityEvolutionManager()
        self.mgr.attach_event_bus(self.bus)
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_social_praxan_becomes_more_social(self):
        """A praxan with many deep conversations becomes more sociable over time."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}

        # Simulate 10 deep conversations
        for _ in range(10):
            p._pending_personality_shifts.append("interaction:deep_conversation")

        self.mgr.update([p], current_time=self.now)
        self.assertGreater(p.personality["sociability"], 0.6)

    def test_hardworking_praxan_grows_diligent(self):
        """Building and crafting increases diligence."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}

        # Simulate building + masterwork craft
        p._pending_personality_shifts.extend([
            "entity:built_structure",
            "entity:built_structure",
            "entity:crafted_masterwork",
        ])

        self.mgr.update([p], current_time=self.now)
        self.assertGreater(p.personality["diligence"], 0.54)

    def test_argument_reduces_sociability(self):
        """Arguments make praxans less sociable."""
        p = MockPraxan(pid=0)
        p.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}

        for _ in range(5):
            p._pending_personality_shifts.append("interaction:argument")

        self.mgr.update([p], current_time=self.now)
        self.assertLess(p.personality["sociability"], 0.5)


if __name__ == "__main__":
    unittest.main()
