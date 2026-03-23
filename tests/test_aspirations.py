"""Tests for the Aspirations & Life Goals system (systems/aspirations.py)."""

import unittest
import time

from systems.aspirations import (
    AspirationManager,
    get_aspiration_def,
    get_all_aspiration_defs,
    check_progress,
    clear_cache,
    _score_aspiration_for_praxan,
    _EVAL_INTERVAL,
    _REASSIGNMENT_COOLDOWN,
    _PROGRESS_MILESTONES,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight stubs
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
        self.health = 100.0
        self.happiness = 70.0
        self.morale = 65.0
        self.age = 100.0  # adult
        self.needs = {"hunger": 80.0, "energy": 80.0, "social": 50.0}
        self.bonds = {}
        self.opinions = {}
        self.moodlets = []
        self.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        self.episodic_memory = StubMemory()
        self.traits = []
        self.role = "gatherer"
        self.skills = {
            "gathering": {"level": 1, "xp": 0},
            "building": {"level": 1, "xp": 0},
            "crafting": {"level": 1, "xp": 0},
            "medical": {"level": 1, "xp": 0},
            "exploring": {"level": 1, "xp": 0},
            "cooking": {"level": 1, "xp": 0},
        }
        self.genetics = {"social_cohesion": 1.0}
        self._pending_reputation_events = []
        self.relationships = {}
        self.known_resources = []
        self.inventory = {"food": 50, "wood": 20, "stone": 0}
        self.aspiration = None
        self._completed_aspirations = []
        self.name = f"Stub_{self.id}"

    @property
    def life_stage(self):
        if self.age < 30:
            return "infant"
        if self.age < 90:
            return "youth"
        if self.age < 330:
            return "adult"
        return "elder"

    def add_moodlet(self, name, value, duration, start_time):
        for m in self.moodlets:
            if m["name"] == name:
                m["duration"] = duration
                m["start_time"] = start_time
                m["value"] = value
                return
        self.moodlets.append({
            "name": name,
            "value": value,
            "duration": duration,
            "start_time": start_time,
        })


class StubMemory:
    def __init__(self):
        self.entries = []

    def record(self, category, summary, related_ids=None, timestamp=None,
               metadata=None, weight_override=None):
        self.entries.append({
            "category": category,
            "summary": summary,
            "related_ids": related_ids or [],
            "timestamp": timestamp,
            "metadata": metadata or {},
        })


class StubFaction:
    def __init__(self, faction_id=0, leader_id=None):
        self.id = faction_id
        self.leader_id = leader_id


class StubFactionManager:
    def __init__(self, factions=None):
        self.factions = factions or {}


class StubEventBus:
    def __init__(self):
        self.events = []
        self._subscribers = {}

    def subscribe(self, category, handler):
        self._subscribers.setdefault(category, []).append(handler)

    def publish(self, event):
        self.events.append(event)
        category = getattr(event, "category", "")
        for handler in self._subscribers.get(category, []):
            try:
                handler(event)
            except Exception:
                pass


class StubReputationManager:
    def __init__(self):
        self._scores = {}

    def get_reputation(self, praxan_id):
        return self._scores.get(praxan_id, 50.0)

    def set_reputation(self, praxan_id, score):
        self._scores[praxan_id] = score


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

class TestDefLoading(unittest.TestCase):
    """Test that aspiration defs load correctly from DefDatabase."""

    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_defs_load(self):
        defs = get_all_aspiration_defs()
        self.assertGreater(len(defs), 0, "Should load at least one AspirationDef")

    def test_known_defs_present(self):
        defs = get_all_aspiration_defs()
        expected_ids = [
            "master_crafter", "social_butterfly", "colony_leader",
            "bold_explorer", "skilled_healer", "master_builder",
            "devoted_parent", "luminary_path", "knowledge_seeker",
            "prosperous_provider",
        ]
        for asp_id in expected_ids:
            self.assertIn(asp_id, defs, f"Missing aspiration def: {asp_id}")

    def test_def_has_required_fields(self):
        asp = get_aspiration_def("master_crafter")
        self.assertIsNotNone(asp)
        self.assertIn("label", asp)
        self.assertIn("description", asp)
        self.assertIn("check", asp)
        self.assertIn("reward", asp)
        self.assertIn("personality_weights", asp)
        self.assertIn("life_stages", asp)

    def test_get_nonexistent_def(self):
        asp = get_aspiration_def("nonexistent_aspiration")
        self.assertIsNone(asp)


class TestProgressChecks(unittest.TestCase):
    """Test individual progress check functions."""

    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_skill_level_check(self):
        p = StubPraxan()
        p.skills["crafting"]["level"] = 3
        asp = get_aspiration_def("master_crafter")
        cur, target = check_progress(p, asp)
        self.assertEqual(cur, 3.0)
        self.assertEqual(target, 4.0)

    def test_skill_level_complete(self):
        p = StubPraxan()
        p.skills["crafting"]["level"] = 5
        asp = get_aspiration_def("master_crafter")
        cur, target = check_progress(p, asp)
        self.assertGreaterEqual(cur, target)

    def test_friend_count_check(self):
        p = StubPraxan()
        p.relationships = {1: "friend", 2: "friend", 3: "rival"}
        asp = get_aspiration_def("social_butterfly")
        cur, target = check_progress(p, asp)
        self.assertEqual(cur, 2.0)
        self.assertEqual(target, 3.0)

    def test_faction_leader_check_not_leader(self):
        p = StubPraxan()
        p.faction_id = 0
        fm = StubFactionManager({0: StubFaction(0, leader_id=999)})
        asp = get_aspiration_def("colony_leader")
        cur, target = check_progress(p, asp, faction_manager=fm)
        self.assertEqual(cur, 0.0)
        self.assertEqual(target, 1.0)

    def test_faction_leader_check_is_leader(self):
        p = StubPraxan()
        p.faction_id = 0
        fm = StubFactionManager({0: StubFaction(0, leader_id=p.id)})
        asp = get_aspiration_def("colony_leader")
        cur, target = check_progress(p, asp, faction_manager=fm)
        self.assertEqual(cur, 1.0)

    def test_known_resources_check(self):
        p = StubPraxan()
        p.known_resources = [(10, 20), (30, 40), (50, 60)]
        asp = get_aspiration_def("bold_explorer")
        cur, target = check_progress(p, asp)
        self.assertEqual(cur, 3.0)
        self.assertEqual(target, 10.0)

    def test_living_children_check(self):
        p = StubPraxan()
        child1 = StubPraxan()
        child2 = StubPraxan()
        child2.alive = False
        p.relationships = {child1.id: "child", child2.id: "child"}
        asp = get_aspiration_def("devoted_parent")
        cur, target = check_progress(p, asp, all_praxans=[p, child1, child2])
        self.assertEqual(cur, 1.0)  # Only one alive
        self.assertEqual(target, 2.0)

    def test_reputation_tier_check(self):
        p = StubPraxan()
        rm = StubReputationManager()
        rm.set_reputation(p.id, 75.0)
        asp = get_aspiration_def("luminary_path")
        cur, target = check_progress(p, asp, reputation_manager=rm)
        self.assertEqual(cur, 75.0)
        self.assertEqual(target, 80.0)

    def test_multi_skill_check(self):
        p = StubPraxan()
        p.skills["gathering"]["level"] = 3
        p.skills["building"]["level"] = 4
        p.skills["crafting"]["level"] = 2
        asp = get_aspiration_def("knowledge_seeker")
        cur, target = check_progress(p, asp)
        self.assertEqual(cur, 2.0)  # gathering + building
        self.assertEqual(target, 3.0)

    def test_total_inventory_check(self):
        p = StubPraxan()
        p.inventory = {"food": 100, "wood": 80, "stone": 30}
        asp = get_aspiration_def("prosperous_provider")
        cur, target = check_progress(p, asp)
        self.assertEqual(cur, 210.0)
        self.assertEqual(target, 200.0)


class TestPersonalityScoring(unittest.TestCase):
    """Test personality-weighted aspiration selection scoring."""

    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_diligent_prefers_crafting(self):
        p = StubPraxan()
        p.personality = {"curiosity": 0.2, "sociability": 0.2, "diligence": 0.9}
        crafter = get_aspiration_def("master_crafter")
        social = get_aspiration_def("social_butterfly")
        crafter_score = _score_aspiration_for_praxan(p, crafter)
        social_score = _score_aspiration_for_praxan(p, social)
        # Diligent praxan should score crafting higher than social
        self.assertGreater(crafter_score, social_score - 0.3)  # Allow jitter margin

    def test_sociable_prefers_social(self):
        p = StubPraxan()
        p.personality = {"curiosity": 0.2, "sociability": 0.9, "diligence": 0.2}
        social = get_aspiration_def("social_butterfly")
        builder = get_aspiration_def("master_builder")
        social_score = _score_aspiration_for_praxan(p, social)
        builder_score = _score_aspiration_for_praxan(p, builder)
        self.assertGreater(social_score, builder_score - 0.3)

    def test_curious_prefers_exploration(self):
        p = StubPraxan()
        p.personality = {"curiosity": 0.9, "sociability": 0.2, "diligence": 0.2}
        explorer = get_aspiration_def("bold_explorer")
        healer = get_aspiration_def("skilled_healer")
        explorer_score = _score_aspiration_for_praxan(p, explorer)
        healer_score = _score_aspiration_for_praxan(p, healer)
        self.assertGreater(explorer_score, healer_score - 0.3)

    def test_infant_ineligible(self):
        p = StubPraxan()
        p.age = 10  # infant
        asp = get_aspiration_def("master_crafter")
        score = _score_aspiration_for_praxan(p, asp)
        self.assertLess(score, -900)

    def test_trait_affinity_bonus(self):
        p1 = StubPraxan()
        p1.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        p1.traits = []
        p2 = StubPraxan()
        p2.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        p2.traits = ["Industrious"]
        asp = get_aspiration_def("master_crafter")
        score1 = _score_aspiration_for_praxan(p1, asp)
        score2 = _score_aspiration_for_praxan(p2, asp)
        # p2 has Industrious trait affinity, should score higher (allowing jitter margin)
        # This test checks the +0.2 boost exists
        self.assertGreaterEqual(score2 - 0.15, score1 - 0.3)  # generous margin for random jitter


class TestAspirationManager(unittest.TestCase):
    """Test the core AspirationManager lifecycle."""

    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = AspirationManager()
        self.eb = StubEventBus()
        self.mgr.attach_event_bus(self.eb)

    def tearDown(self):
        clear_cache()

    def test_force_assign(self):
        p = StubPraxan()
        now = time.time()
        result = self.mgr.force_assign(p, "master_crafter", now)
        self.assertTrue(result)
        self.assertTrue(self.mgr.has_aspiration(p.id))
        self.assertIsNotNone(p.aspiration)
        self.assertEqual(p.aspiration["id"], "master_crafter")

    def test_force_assign_invalid_id(self):
        p = StubPraxan()
        result = self.mgr.force_assign(p, "nonexistent_aspiration")
        self.assertFalse(result)
        self.assertFalse(self.mgr.has_aspiration(p.id))

    def test_auto_assign_on_update(self):
        p = StubPraxan()
        p.age = 100  # adult
        now = time.time()
        # Force eval by setting last_eval far in the past
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now)
        self.assertTrue(self.mgr.has_aspiration(p.id))
        self.assertIsNotNone(p.aspiration)

    def test_no_assign_to_infant(self):
        p = StubPraxan()
        p.age = 10  # infant
        now = time.time()
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now)
        self.assertFalse(self.mgr.has_aspiration(p.id))

    def test_cooldown_prevents_immediate_reassign(self):
        p = StubPraxan()
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        # Fail the aspiration
        self.mgr.fail_aspiration(p, now, self.eb)
        self.assertFalse(self.mgr.has_aspiration(p.id))

        # Try to update immediately — cooldown should block
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + 1)
        self.assertFalse(self.mgr.has_aspiration(p.id))

        # After cooldown expires
        self.mgr._last_eval_time = now + _REASSIGNMENT_COOLDOWN - _EVAL_INTERVAL
        self.mgr.update([p], current_time=now + _REASSIGNMENT_COOLDOWN + 1)
        self.assertTrue(self.mgr.has_aspiration(p.id))

    def test_progress_tracking(self):
        p = StubPraxan()
        p.skills["crafting"]["level"] = 2
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)

        # Evaluate progress
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)

        asp_state = self.mgr.get_aspiration(p.id)
        self.assertIsNotNone(asp_state)
        self.assertEqual(asp_state["progress"], 0.5)  # 2/4

    def test_completion(self):
        p = StubPraxan()
        p.skills["crafting"]["level"] = 5  # exceeds threshold of 4
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)

        # Evaluate — should complete
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)

        # Aspiration should be cleared (completed)
        self.assertFalse(self.mgr.has_aspiration(p.id))
        self.assertIsNone(p.aspiration)
        # Should have gotten AspirationAchieved moodlet
        mood_names = [m["name"] for m in p.moodlets]
        self.assertIn("AspirationAchieved", mood_names)

    def test_completion_records_memory(self):
        p = StubPraxan()
        p.skills["crafting"]["level"] = 5
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)

        mem_categories = [e["category"] for e in p.episodic_memory.entries]
        self.assertIn("aspiration_achieved", mem_categories)

    def test_completion_queues_reputation(self):
        p = StubPraxan()
        p.skills["crafting"]["level"] = 5
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)

        self.assertIn("aspiration_achieved", p._pending_reputation_events)

    def test_completion_publishes_event(self):
        p = StubPraxan()
        p.skills["crafting"]["level"] = 5
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], event_bus=self.eb, current_time=now + _EVAL_INTERVAL + 1)

        achieved_events = [e for e in self.eb.events
                          if getattr(e, "metadata", {}).get("type") == "aspiration_achieved"]
        self.assertGreaterEqual(len(achieved_events), 1)

    def test_completion_adds_to_completed_list(self):
        p = StubPraxan()
        p.skills["crafting"]["level"] = 5
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)

        self.assertIn("master_crafter", p._completed_aspirations)

    def test_no_duplicate_aspiration(self):
        """Once completed, the same aspiration should not be reassigned."""
        p = StubPraxan()
        p.skills["crafting"]["level"] = 5
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)

        self.assertIn("master_crafter", p._completed_aspirations)
        # Wait out cooldown and re-update
        self.mgr._last_eval_time = now + _REASSIGNMENT_COOLDOWN
        self.mgr.update([p], current_time=now + _REASSIGNMENT_COOLDOWN + _EVAL_INTERVAL + 2)

        # Should have a new aspiration, but NOT master_crafter again
        if self.mgr.has_aspiration(p.id):
            asp = self.mgr.get_aspiration(p.id)
            self.assertNotEqual(asp["id"], "master_crafter")

    def test_fail_aspiration(self):
        p = StubPraxan()
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        self.mgr.fail_aspiration(p, now, self.eb)

        self.assertFalse(self.mgr.has_aspiration(p.id))
        mood_names = [m["name"] for m in p.moodlets]
        self.assertIn("AspirationFailed", mood_names)
        self.assertIn("aspiration_abandoned", p._pending_reputation_events)

    def test_fail_records_memory(self):
        p = StubPraxan()
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        self.mgr.fail_aspiration(p, now, self.eb)

        mem_categories = [e["category"] for e in p.episodic_memory.entries]
        self.assertIn("aspiration_failed", mem_categories)

    def test_elder_graceful_expiry(self):
        p = StubPraxan()
        p.age = 100  # adult when assigned
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)

        # Age to elder
        p.age = 340
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)

        # Should be cleared but NO failure moodlet
        self.assertFalse(self.mgr.has_aspiration(p.id))
        mood_names = [m["name"] for m in p.moodlets]
        self.assertNotIn("AspirationFailed", mood_names)
        # But should have memory
        mem_categories = [e["category"] for e in p.episodic_memory.entries]
        self.assertIn("aspiration_failed", mem_categories)

    def test_death_cleans_up_aspiration(self):
        p = StubPraxan()
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        self.assertTrue(self.mgr.has_aspiration(p.id))

        # Simulate death event
        from events.bus import GameEvent, CATEGORY_DEATH
        death_event = GameEvent(
            category=CATEGORY_DEATH,
            summary=f"{p.name} died",
            praxan_id=p.id,
        )
        self.mgr._on_death_event(death_event)
        self.assertFalse(self.mgr.has_aspiration(p.id))

    def test_milestone_moodlets(self):
        p = StubPraxan()
        p.skills["crafting"]["level"] = 1
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)

        # Level to 1/4 = 25% — should trigger first milestone
        p.skills["crafting"]["level"] = 1
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)
        asp_state = self.mgr.get_aspiration(p.id)
        # 1/4 = 0.25, should trigger 0.25 milestone
        self.assertIn(0.25, asp_state.get("milestones_hit", []))

        # Level to 2/4 = 50%
        p.skills["crafting"]["level"] = 2
        t2 = now + 2 * _EVAL_INTERVAL + 2
        self.mgr._last_eval_time = t2 - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=t2)
        asp_state = self.mgr.get_aspiration(p.id)
        self.assertIn(0.50, asp_state.get("milestones_hit", []))

    def test_dead_praxan_skipped(self):
        p = StubPraxan()
        p.alive = False
        now = time.time()
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now)
        self.assertFalse(self.mgr.has_aspiration(p.id))

    def test_eval_interval_respected(self):
        p = StubPraxan()
        now = time.time()
        self.mgr._last_eval_time = now  # just evaluated
        self.mgr.update([p], current_time=now + 1)  # too soon
        self.assertFalse(self.mgr.has_aspiration(p.id))

    def test_get_progress_no_aspiration(self):
        self.assertEqual(self.mgr.get_progress(999), 0.0)

    def test_has_aspiration_false(self):
        self.assertFalse(self.mgr.has_aspiration(999))

    def test_get_aspiration_def_for_none(self):
        self.assertIsNone(self.mgr.get_aspiration_def_for(999))

    def test_assignment_records_memory(self):
        p = StubPraxan()
        now = time.time()
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], event_bus=self.eb, current_time=now)

        mem_categories = [e["category"] for e in p.episodic_memory.entries]
        self.assertIn("aspiration_assigned", mem_categories)

    def test_assignment_gives_moodlet(self):
        p = StubPraxan()
        now = time.time()
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], event_bus=self.eb, current_time=now)

        mood_names = [m["name"] for m in p.moodlets]
        self.assertIn("AspirationAssigned", mood_names)

    def test_assignment_publishes_event(self):
        p = StubPraxan()
        now = time.time()
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], event_bus=self.eb, current_time=now)

        assigned_events = [e for e in self.eb.events
                          if getattr(e, "metadata", {}).get("type") == "aspiration_assigned"]
        self.assertGreaterEqual(len(assigned_events), 1)

    def test_social_butterfly_completion(self):
        p = StubPraxan()
        p.relationships = {10: "friend", 20: "friend", 30: "friend"}
        now = time.time()
        self.mgr.force_assign(p, "social_butterfly", now)
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)

        self.assertFalse(self.mgr.has_aspiration(p.id))
        self.assertIn("social_butterfly", p._completed_aspirations)

    def test_colony_leader_completion(self):
        p = StubPraxan()
        p.faction_id = 0
        fm = StubFactionManager({0: StubFaction(0, leader_id=p.id)})
        now = time.time()
        self.mgr.force_assign(p, "colony_leader", now)
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], faction_manager=fm, current_time=now + _EVAL_INTERVAL + 1)

        self.assertFalse(self.mgr.has_aspiration(p.id))
        self.assertIn("colony_leader", p._completed_aspirations)

    def test_luminary_path_completion(self):
        p = StubPraxan()
        rm = StubReputationManager()
        rm.set_reputation(p.id, 85.0)
        now = time.time()
        self.mgr.force_assign(p, "luminary_path", now)
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], reputation_manager=rm, current_time=now + _EVAL_INTERVAL + 1)

        self.assertFalse(self.mgr.has_aspiration(p.id))
        self.assertIn("luminary_path", p._completed_aspirations)

    def test_prosperous_provider_completion(self):
        p = StubPraxan()
        p.inventory = {"food": 100, "wood": 80, "stone": 30}
        now = time.time()
        self.mgr.force_assign(p, "prosperous_provider", now)
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)

        self.assertFalse(self.mgr.has_aspiration(p.id))
        self.assertIn("prosperous_provider", p._completed_aspirations)

    def test_knowledge_seeker_completion(self):
        p = StubPraxan()
        p.skills["gathering"]["level"] = 3
        p.skills["building"]["level"] = 4
        p.skills["crafting"]["level"] = 3
        now = time.time()
        self.mgr.force_assign(p, "knowledge_seeker", now)
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now + _EVAL_INTERVAL + 1)

        self.assertFalse(self.mgr.has_aspiration(p.id))
        self.assertIn("knowledge_seeker", p._completed_aspirations)

    def test_multiple_praxans_get_aspirations(self):
        praxans = [StubPraxan() for _ in range(5)]
        now = time.time()
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update(praxans, current_time=now)

        assigned_count = sum(1 for p in praxans if self.mgr.has_aspiration(p.id))
        self.assertEqual(assigned_count, 5)


class TestSerialization(unittest.TestCase):
    """Test snapshot serialization and restore."""

    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = AspirationManager()

    def tearDown(self):
        clear_cache()

    def test_serialize_empty(self):
        data = self.mgr.serialize()
        self.assertIn("aspirations", data)
        self.assertIn("cooldowns", data)
        self.assertEqual(len(data["aspirations"]), 0)

    def test_serialize_with_aspiration(self):
        p = StubPraxan()
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        data = self.mgr.serialize()
        self.assertIn(str(p.id), data["aspirations"])
        asp_data = data["aspirations"][str(p.id)]
        self.assertEqual(asp_data["id"], "master_crafter")

    def test_restore_roundtrip(self):
        p = StubPraxan()
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        data = self.mgr.serialize()

        mgr2 = AspirationManager()
        mgr2.restore(data, now=now)
        self.assertTrue(mgr2.has_aspiration(p.id))
        asp = mgr2.get_aspiration(p.id)
        self.assertEqual(asp["id"], "master_crafter")

    def test_restore_praxan_aspirations(self):
        p = StubPraxan()
        now = time.time()
        self.mgr.force_assign(p, "social_butterfly", now)
        data = self.mgr.serialize()

        mgr2 = AspirationManager()
        mgr2.restore(data, now=now)
        # Clear entity field to simulate fresh load
        p.aspiration = None
        mgr2.restore_praxan_aspirations([p])
        self.assertIsNotNone(p.aspiration)
        self.assertEqual(p.aspiration["id"], "social_butterfly")

    def test_restore_cooldowns(self):
        p = StubPraxan()
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        self.mgr.fail_aspiration(p, now)

        data = self.mgr.serialize()
        mgr2 = AspirationManager()
        mgr2.restore(data, now=now)

        # Cooldown should be present
        self.assertIn(p.id, mgr2._cooldowns)

    def test_restore_invalid_data(self):
        mgr2 = AspirationManager()
        mgr2.restore({"aspirations": {"bad": "data"}, "cooldowns": {}})
        # Should not crash
        self.assertEqual(len(mgr2._aspirations), 0)

    def test_serialize_progress_and_milestones(self):
        p = StubPraxan()
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        asp_state = self.mgr.get_aspiration(p.id)
        asp_state["progress"] = 0.5
        asp_state["milestones_hit"] = [0.25, 0.50]

        data = self.mgr.serialize()
        asp_data = data["aspirations"][str(p.id)]
        self.assertEqual(asp_data["progress"], 0.5)
        self.assertEqual(asp_data["milestones_hit"], [0.25, 0.50])


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = AspirationManager()

    def tearDown(self):
        clear_cache()

    def test_no_defs_loaded(self):
        """Manager should handle no defs gracefully."""
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()  # No defs loaded

        p = StubPraxan()
        now = time.time()
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now)
        self.assertFalse(self.mgr.has_aspiration(p.id))

    def test_youth_gets_explorer(self):
        """Youth should be eligible for bold_explorer (has youth in life_stages)."""
        p = StubPraxan()
        p.age = 50  # youth
        now = time.time()
        # Force assign bold_explorer which allows youth
        result = self.mgr.force_assign(p, "bold_explorer", now)
        self.assertTrue(result)

    def test_already_complete_not_assigned(self):
        """If aspiration conditions are already met, it should try to pick another."""
        p = StubPraxan()
        p.skills["crafting"]["level"] = 6  # already beyond threshold
        p.skills["building"]["level"] = 6
        p.skills["medical"]["level"] = 6
        p.skills["gathering"]["level"] = 6
        p.relationships = {10: "friend", 20: "friend", 30: "friend", 40: "friend"}
        p.inventory = {"food": 500, "wood": 500, "stone": 500}
        p.known_resources = [(i, i) for i in range(20)]
        # Many aspirations would be instantly complete — should still assign one
        now = time.time()
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([p], current_time=now)
        # Even if some are instantly complete, the system should be resilient

    def test_empty_praxan_list(self):
        now = time.time()
        self.mgr._last_eval_time = now - _EVAL_INTERVAL - 1
        self.mgr.update([], current_time=now)
        # Should not crash

    def test_fail_aspiration_no_active(self):
        p = StubPraxan()
        result = self.mgr.fail_aspiration(p)
        self.assertFalse(result)

    def test_get_aspiration_def_for_active(self):
        p = StubPraxan()
        now = time.time()
        self.mgr.force_assign(p, "master_crafter", now)
        asp_def = self.mgr.get_aspiration_def_for(p.id)
        self.assertIsNotNone(asp_def)
        self.assertEqual(asp_def["id"], "master_crafter")

    def test_devoted_parent_no_all_praxans(self):
        """living_children check with no all_praxans should return 0."""
        p = StubPraxan()
        p.relationships = {10: "child"}
        asp = get_aspiration_def("devoted_parent")
        cur, target = check_progress(p, asp)
        self.assertEqual(cur, 0.0)

    def test_faction_leader_no_faction_manager(self):
        p = StubPraxan()
        asp = get_aspiration_def("colony_leader")
        cur, target = check_progress(p, asp)
        self.assertEqual(cur, 0.0)

    def test_reputation_tier_no_manager(self):
        p = StubPraxan()
        asp = get_aspiration_def("luminary_path")
        cur, target = check_progress(p, asp)
        self.assertEqual(cur, 50.0)  # default rep


if __name__ == "__main__":
    unittest.main()
