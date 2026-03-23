"""Tests for the Mentorship & Apprenticeship System (systems/mentorship.py).

Covers:
- MentorshipDef loading from DefDatabase
- Mentor-apprentice matching and pair scoring
- Session XP grants and bond growth
- Graduation detection and consequences
- Mentorship breakage on death/faction change
- Cooldown enforcement
- Proximity-based XP multiplier
- Manager serialization/restoration
- Praxan entity integration (mentorship field, XP mult)
- EventBus integration
- Edge cases (no eligible pairs, max global cap, etc.)
"""

import time
import unittest
from unittest.mock import MagicMock

from events.bus import (
    CATEGORY_DEATH,
    CATEGORY_PERSONAL,
    EventBus,
    GameEvent,
)
from systems.def_database import DefDatabase
from systems.mentorship import (
    MentorshipManager,
    clear_cache,
    get_all_mentorship_defs,
    get_mentorship_def,
    get_def_for_skill,
    _score_pair,
    _distance,
    _EVAL_INTERVAL,
    _APPRENTICE_COOLDOWN,
    _MAX_GLOBAL_MENTORSHIPS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockPraxan:
    def __init__(self, pid=0, x=0.0, y=0.0, skill_levels=None, faction_id=0):
        self.id = pid
        self.x = x
        self.y = y
        self.alive = True
        self.name = f"Praxan_{pid}"
        self.faction_id = faction_id
        self.skills = {}
        for skill in ("gathering", "building", "exploring", "medical", "crafting", "cooking"):
            level = (skill_levels or {}).get(skill, 1)
            self.skills[skill] = {"level": level, "xp": 0}
        self.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        self.traits = []
        self.bonds = {}
        self.opinions = {}
        self.relationships = {}
        self.moodlets = []
        self.life_stage = "adult"
        self.mentorship = None
        self._mentorship_xp_mult = {}
        self._pending_reputation_events = []
        self.episodic_memory = MagicMock()

    @property
    def life_stage_modifiers(self):
        return {"xp_mult": 1.0}

    def add_moodlet(self, name, value, duration, current_time):
        self.moodlets.append({"name": name, "value": value, "duration": duration, "start_time": current_time})

    def gain_skill_xp(self, skill_type, amount):
        if skill_type in self.skills:
            mult = self._mentorship_xp_mult.get(skill_type, 1.0)
            self.skills[skill_type]["xp"] += amount * mult
            threshold = 100 * self.skills[skill_type]["level"]
            if self.skills[skill_type]["xp"] >= threshold:
                self.skills[skill_type]["level"] += 1
                self.skills[skill_type]["xp"] = 0


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


class MockReputationManager:
    def __init__(self):
        self._events = []

    def record_event(self, praxan_id, event_id, multiplier=1.0):
        self._events.append((praxan_id, event_id))
        return 1.0

    def get_reputation(self, praxan_id):
        return 50.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMentorshipDefLoading(unittest.TestCase):
    """Test that MentorshipDefs load correctly from DefDatabase."""

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_defs_loaded(self):
        defs = get_all_mentorship_defs()
        self.assertGreater(len(defs), 0, "Should load at least one MentorshipDef")

    def test_six_skill_defs(self):
        defs = get_all_mentorship_defs()
        skills = {d["skill"] for d in defs.values()}
        expected = {"gathering", "building", "exploring", "medical", "crafting", "cooking"}
        self.assertEqual(skills, expected)

    def test_def_has_required_fields(self):
        defs = get_all_mentorship_defs()
        for def_id, d in defs.items():
            self.assertIn("skill", d)
            self.assertIn("mentor_min_level", d)
            self.assertIn("apprentice_max_level", d)
            self.assertIn("xp_multiplier", d)
            self.assertIn("graduation_level", d)
            self.assertIn("proximity_radius", d)
            self.assertIn("session_xp", d)
            self.assertIn("session_interval", d)

    def test_get_def_by_id(self):
        d = get_mentorship_def("gathering_apprentice")
        self.assertIsNotNone(d)
        self.assertEqual(d["skill"], "gathering")

    def test_get_def_for_skill(self):
        d = get_def_for_skill("medical")
        self.assertIsNotNone(d)
        self.assertEqual(d["id"], "medical_apprentice")

    def test_get_def_for_unknown_skill_returns_none(self):
        self.assertIsNone(get_def_for_skill("teleportation"))


class TestDistanceHelper(unittest.TestCase):
    def test_same_position(self):
        a = MockPraxan(0, x=10, y=20)
        b = MockPraxan(1, x=10, y=20)
        self.assertAlmostEqual(_distance(a, b), 0.0)

    def test_known_distance(self):
        a = MockPraxan(0, x=0, y=0)
        b = MockPraxan(1, x=3, y=4)
        self.assertAlmostEqual(_distance(a, b), 5.0)


class TestScorePair(unittest.TestCase):
    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_same_faction_bonus(self):
        mdef = get_mentorship_def("gathering_apprentice")
        mentor = MockPraxan(0, faction_id=1)
        app1 = MockPraxan(1, faction_id=1)
        app2 = MockPraxan(2, faction_id=2)
        score_same = _score_pair(mentor, app1, mdef)
        score_diff = _score_pair(mentor, app2, mdef)
        # On average, same faction should score higher (faction bonus = 0.4)
        # Run multiple times due to jitter
        same_total = sum(_score_pair(mentor, app1, mdef) for _ in range(50))
        diff_total = sum(_score_pair(mentor, app2, mdef) for _ in range(50))
        self.assertGreater(same_total, diff_total)

    def test_trait_affinity_bonus(self):
        mdef = get_mentorship_def("gathering_apprentice")
        mentor_with = MockPraxan(0, faction_id=1)
        mentor_with.traits = ["Industrious"]
        mentor_without = MockPraxan(1, faction_id=1)
        mentor_without.traits = []
        app = MockPraxan(2, faction_id=1)
        # Average over runs
        with_total = sum(_score_pair(mentor_with, app, mdef) for _ in range(50))
        without_total = sum(_score_pair(mentor_without, app, mdef) for _ in range(50))
        self.assertGreater(with_total, without_total)


class TestMentorshipManager(unittest.TestCase):
    """Core manager tests."""

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = MentorshipManager()
        self.mgr.attach_event_bus(self.bus)
        self.rep = MockReputationManager()
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def _make_mentor(self, pid=0, skill="gathering", level=4, faction_id=0):
        return MockPraxan(pid, skill_levels={skill: level}, faction_id=faction_id)

    def _make_apprentice(self, pid=1, skill="gathering", level=1, faction_id=0):
        return MockPraxan(pid, skill_levels={skill: level}, faction_id=faction_id)

    def test_initial_state(self):
        self.assertEqual(self.mgr.active_count(), 0)
        self.assertFalse(self.mgr.is_mentor(0))
        self.assertFalse(self.mgr.is_apprentice(0))

    def test_form_mentorship_on_update(self):
        mentor = self._make_mentor(pid=0, level=4)
        apprentice = self._make_apprentice(pid=1, level=1)
        praxans = [mentor, apprentice]
        # Force eval by setting last_eval far in the past
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update(praxans, reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 1)
        self.assertTrue(self.mgr.is_mentor(0))
        self.assertTrue(self.mgr.is_apprentice(1))

    def test_mentor_relationship_set(self):
        mentor = self._make_mentor(pid=0, level=4)
        apprentice = self._make_apprentice(pid=1, level=1)
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(mentor.relationships.get(1), "mentor")
        self.assertEqual(apprentice.relationships.get(0), "apprentice")

    def test_apprentice_mentorship_field_set(self):
        mentor = self._make_mentor(pid=0, level=4)
        apprentice = self._make_apprentice(pid=1, level=1)
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertIsNotNone(apprentice.mentorship)
        self.assertEqual(apprentice.mentorship["mentor_id"], 0)
        self.assertEqual(apprentice.mentorship["skill"], "gathering")

    def test_no_mentorship_if_skill_too_low(self):
        mentor = self._make_mentor(pid=0, level=2)  # Below min level 3
        apprentice = self._make_apprentice(pid=1, level=1)
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 0)

    def test_no_mentorship_if_apprentice_too_skilled(self):
        mentor = self._make_mentor(pid=0, level=4)
        apprentice = self._make_apprentice(pid=1, level=3)  # Above max level 2
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 0)

    def test_no_mentorship_cross_faction(self):
        mentor = self._make_mentor(pid=0, level=4, faction_id=0)
        apprentice = self._make_apprentice(pid=1, level=1, faction_id=1)
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 0)

    def test_no_double_apprenticeship(self):
        mentor1 = self._make_mentor(pid=0, skill="gathering", level=4)
        mentor2 = self._make_mentor(pid=2, skill="building", level=4)
        apprentice = self._make_apprentice(pid=1, skill="gathering", level=1)
        apprentice.skills["building"] = {"level": 1, "xp": 0}
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor1, mentor2, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        # Apprentice should only have one mentorship
        self.assertEqual(self.mgr.active_count(), 1)

    def test_elder_can_mentor(self):
        mentor = self._make_mentor(pid=0, level=4)
        mentor.life_stage = "elder"
        apprentice = self._make_apprentice(pid=1, level=1)
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 1)

    def test_youth_can_be_apprentice(self):
        mentor = self._make_mentor(pid=0, level=4)
        apprentice = self._make_apprentice(pid=1, level=1)
        apprentice.life_stage = "youth"
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 1)

    def test_infant_cannot_be_apprentice(self):
        mentor = self._make_mentor(pid=0, level=4)
        apprentice = self._make_apprentice(pid=1, level=1)
        apprentice.life_stage = "infant"
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 0)


class TestTrainingSessions(unittest.TestCase):
    """Test session XP grants, bond growth, and moodlets."""

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = MentorshipManager()
        self.mgr.attach_event_bus(self.bus)
        self.rep = MockReputationManager()
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def _setup_pair(self):
        mentor = MockPraxan(0, x=50, y=50, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, x=55, y=55, skill_levels={"gathering": 1})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        return mentor, apprentice

    def test_session_grants_xp(self):
        mentor, apprentice = self._setup_pair()
        xp_before = apprentice.skills["gathering"]["xp"]
        # Advance time past session interval
        future = self.now + 15.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        xp_after = apprentice.skills["gathering"]["xp"]
        self.assertGreater(xp_after, xp_before)

    def test_session_grows_bond(self):
        mentor, apprentice = self._setup_pair()
        bond_before = mentor.bonds.get(1, 0)
        future = self.now + 15.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        bond_after = mentor.bonds.get(1, 0)
        self.assertGreater(bond_after, bond_before)

    def test_session_applies_moodlets(self):
        mentor, apprentice = self._setup_pair()
        future = self.now + 15.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        mentor_moods = [m["name"] for m in mentor.moodlets]
        apprentice_moods = [m["name"] for m in apprentice.moodlets]
        self.assertIn("TeachingApprentice", mentor_moods)
        self.assertIn("LearningFromMentor", apprentice_moods)

    def test_no_session_when_too_far(self):
        mentor, apprentice = self._setup_pair()
        # Move apprentice far away
        apprentice.x = 5000
        apprentice.y = 5000
        xp_before = apprentice.skills["gathering"]["xp"]
        future = self.now + 15.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        xp_after = apprentice.skills["gathering"]["xp"]
        self.assertEqual(xp_after, xp_before)

    def test_session_reputation_event(self):
        mentor, apprentice = self._setup_pair()
        self.rep._events.clear()
        future = self.now + 15.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        rep_events = [(pid, eid) for pid, eid in self.rep._events if eid == "mentorship_session"]
        self.assertTrue(len(rep_events) > 0)

    def test_session_increments_count(self):
        mentor, apprentice = self._setup_pair()
        m = self.mgr.get_mentorship(1)
        self.assertEqual(m["sessions_count"], 0)
        future = self.now + 15.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        m = self.mgr.get_mentorship(1)
        self.assertEqual(m["sessions_count"], 1)


class TestGraduation(unittest.TestCase):
    """Test graduation detection and consequences."""

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = MentorshipManager()
        self.mgr.attach_event_bus(self.bus)
        self.rep = MockReputationManager()
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_graduation_on_level_up(self):
        mentor = MockPraxan(0, x=50, y=50, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, x=55, y=55, skill_levels={"gathering": 2})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 1)

        # Manually set apprentice skill to graduation level
        apprentice.skills["gathering"]["level"] = 3
        future = self.now + 15.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        # Should have graduated and been removed
        self.assertEqual(self.mgr.active_count(), 0)

    def test_graduation_moodlets(self):
        mentor = MockPraxan(0, x=50, y=50, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, x=55, y=55, skill_levels={"gathering": 2})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        apprentice.skills["gathering"]["level"] = 3
        future = self.now + 1.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        app_moods = [m["name"] for m in apprentice.moodlets]
        mentor_moods = [m["name"] for m in mentor.moodlets]
        self.assertIn("ApprenticeGraduated", app_moods)
        self.assertIn("MentorProud", mentor_moods)

    def test_graduation_reputation_event(self):
        mentor = MockPraxan(0, x=50, y=50, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, x=55, y=55, skill_levels={"gathering": 2})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.rep._events.clear()
        apprentice.skills["gathering"]["level"] = 3
        future = self.now + 1.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        grad_events = [(pid, eid) for pid, eid in self.rep._events if eid == "graduated_apprentice"]
        self.assertEqual(len(grad_events), 1)
        self.assertEqual(grad_events[0][0], 0)  # Mentor ID

    def test_graduation_sets_former_relationships(self):
        mentor = MockPraxan(0, x=50, y=50, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, x=55, y=55, skill_levels={"gathering": 2})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        apprentice.skills["gathering"]["level"] = 3
        future = self.now + 1.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        self.assertEqual(mentor.relationships.get(1), "former_mentor")
        self.assertEqual(apprentice.relationships.get(0), "former_apprentice")

    def test_graduation_records_episodic_memory(self):
        mentor = MockPraxan(0, x=50, y=50, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, x=55, y=55, skill_levels={"gathering": 2})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        apprentice.skills["gathering"]["level"] = 3
        future = self.now + 1.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        # Memory should have been called for both
        apprentice.episodic_memory.record.assert_called()
        mentor.episodic_memory.record.assert_called()


class TestMentorshipBreakage(unittest.TestCase):
    """Test mentorship ending on death, missing, or explicit break."""

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = MentorshipManager()
        self.mgr.attach_event_bus(self.bus)
        self.rep = MockReputationManager()
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def _setup_pair(self):
        mentor = MockPraxan(0, x=50, y=50, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, x=55, y=55, skill_levels={"gathering": 1})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        return mentor, apprentice

    def test_break_on_apprentice_death(self):
        mentor, apprentice = self._setup_pair()
        self.assertEqual(self.mgr.active_count(), 1)
        # Simulate death event
        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Apprentice died",
            praxan_id=1,
        ))
        self.assertEqual(self.mgr.active_count(), 0)

    def test_break_on_mentor_death(self):
        mentor, apprentice = self._setup_pair()
        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Mentor died",
            praxan_id=0,
        ))
        self.assertEqual(self.mgr.active_count(), 0)

    def test_break_sets_cooldown(self):
        mentor, apprentice = self._setup_pair()
        self.mgr.break_mentorship(1, reason="test")
        self.assertEqual(self.mgr.active_count(), 0)
        # Cooldown should prevent immediate reassignment
        self.assertIn(1, self.mgr._cooldowns)

    def test_cooldown_blocks_reassignment(self):
        mentor, apprentice = self._setup_pair()
        self.mgr.break_mentorship(1, reason="test")
        # Try to form again immediately
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 0)

    def test_cooldown_expires(self):
        mentor, apprentice = self._setup_pair()
        self.mgr.break_mentorship(1, reason="test")
        # Advance past cooldown
        future = self.now + _APPRENTICE_COOLDOWN + 1
        self.mgr._last_eval_time = future - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        self.assertEqual(self.mgr.active_count(), 1)

    def test_break_removes_missing_praxan(self):
        mentor, apprentice = self._setup_pair()
        # Update with only mentor alive
        apprentice.alive = False
        future = self.now + 1.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        self.assertEqual(self.mgr.active_count(), 0)


class TestXPMultiplier(unittest.TestCase):
    """Test proximity-based XP multiplier queries."""

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = MentorshipManager()
        self.mgr.attach_event_bus(self.bus)
        self.rep = MockReputationManager()
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def _setup_pair(self):
        mentor = MockPraxan(0, x=50, y=50, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, x=55, y=55, skill_levels={"gathering": 1})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        return mentor, apprentice

    def test_multiplier_in_range(self):
        mentor, apprentice = self._setup_pair()
        mult = self.mgr.get_xp_multiplier(1, "gathering")
        self.assertGreater(mult, 1.0)

    def test_multiplier_default_for_non_apprentice(self):
        mult = self.mgr.get_xp_multiplier(999, "gathering")
        self.assertEqual(mult, 1.0)

    def test_multiplier_default_for_wrong_skill(self):
        mentor, apprentice = self._setup_pair()
        mult = self.mgr.get_xp_multiplier(1, "building")
        self.assertEqual(mult, 1.0)

    def test_is_near_mentor_in_range(self):
        mentor, apprentice = self._setup_pair()
        alive_map = {0: mentor, 1: apprentice}
        self.assertTrue(self.mgr.is_near_mentor(1, alive_map))

    def test_is_near_mentor_out_of_range(self):
        mentor, apprentice = self._setup_pair()
        apprentice.x = 5000
        alive_map = {0: mentor, 1: apprentice}
        self.assertFalse(self.mgr.is_near_mentor(1, alive_map))


class TestSerialization(unittest.TestCase):
    """Test snapshot serialization and restoration."""

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = MentorshipManager()
        self.mgr.attach_event_bus(self.bus)
        self.rep = MockReputationManager()
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def _setup_pair(self):
        mentor = MockPraxan(0, x=50, y=50, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, x=55, y=55, skill_levels={"gathering": 1})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        return mentor, apprentice

    def test_serialize_empty(self):
        data = self.mgr.serialize(current_time=self.now)
        self.assertEqual(data["active"], {})
        self.assertEqual(data["cooldowns"], {})

    def test_serialize_with_mentorship(self):
        self._setup_pair()
        data = self.mgr.serialize(current_time=self.now)
        self.assertEqual(len(data["active"]), 1)
        entry = data["active"]["1"]
        self.assertEqual(entry["mentor_id"], 0)
        self.assertEqual(entry["skill"], "gathering")
        self.assertFalse(entry["graduated"])

    def test_restore_round_trip(self):
        self._setup_pair()
        data = self.mgr.serialize(current_time=self.now)

        # Create fresh manager and restore
        mgr2 = MentorshipManager()
        mgr2.restore(data, current_time=self.now + 5.0)
        self.assertEqual(mgr2.active_count(), 1)
        self.assertTrue(mgr2.is_mentor(0))
        self.assertTrue(mgr2.is_apprentice(1))

    def test_restore_praxan_mentorships(self):
        mentor, apprentice = self._setup_pair()
        data = self.mgr.serialize(current_time=self.now)

        # Reset praxan state
        apprentice.mentorship = None
        mentor.relationships = {}
        apprentice.relationships = {}

        mgr2 = MentorshipManager()
        mgr2.restore(data, current_time=self.now)
        mgr2.restore_praxan_mentorships([mentor, apprentice])

        self.assertIsNotNone(apprentice.mentorship)
        self.assertEqual(apprentice.mentorship["mentor_id"], 0)
        self.assertEqual(mentor.relationships.get(1), "mentor")
        self.assertEqual(apprentice.relationships.get(0), "apprentice")

    def test_restore_cooldowns(self):
        self._setup_pair()
        self.mgr.break_mentorship(1, reason="test")
        data = self.mgr.serialize(current_time=self.now)

        mgr2 = MentorshipManager()
        mgr2.restore(data, current_time=self.now)
        # Cooldown should be restored
        self.assertIn(1, mgr2._cooldowns)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = MentorshipManager()
        self.mgr.attach_event_bus(self.bus)
        self.rep = MockReputationManager()
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_no_praxans(self):
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 0)

    def test_single_praxan(self):
        p = MockPraxan(0, skill_levels={"gathering": 5})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([p], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertEqual(self.mgr.active_count(), 0)

    def test_max_global_cap(self):
        praxans = []
        for i in range(50):
            if i % 2 == 0:
                p = MockPraxan(i, skill_levels={"gathering": 4})
            else:
                p = MockPraxan(i, skill_levels={"gathering": 1})
            praxans.append(p)
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update(praxans, reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        self.assertLessEqual(self.mgr.active_count(), _MAX_GLOBAL_MENTORSHIPS)

    def test_get_mentor_apprentices(self):
        mentor = MockPraxan(0, skill_levels={"gathering": 4})
        app1 = MockPraxan(1, skill_levels={"gathering": 1})
        app2 = MockPraxan(2, skill_levels={"gathering": 1})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, app1, app2], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        apprentices = self.mgr.get_mentor_apprentices(0)
        # Max 2 per mentor for gathering def
        self.assertLessEqual(len(apprentices), 2)
        self.assertGreaterEqual(len(apprentices), 1)

    def test_get_stats(self):
        mentor = MockPraxan(0, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, skill_levels={"gathering": 1})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        stats = self.mgr.get_stats()
        self.assertEqual(stats["active_count"], 1)
        self.assertIn("gathering", stats["by_skill"])

    def test_eventbus_publishes_on_formation(self):
        events = []
        self.bus.subscribe(CATEGORY_PERSONAL, lambda e: events.append(e))
        mentor = MockPraxan(0, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, skill_levels={"gathering": 1})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        formation_events = [e for e in events if getattr(e, "metadata", {}).get("type") == "mentorship_formed"]
        self.assertEqual(len(formation_events), 1)

    def test_eventbus_publishes_on_graduation(self):
        events = []
        self.bus.subscribe(CATEGORY_PERSONAL, lambda e: events.append(e))
        mentor = MockPraxan(0, x=50, y=50, skill_levels={"gathering": 4})
        apprentice = MockPraxan(1, x=55, y=55, skill_levels={"gathering": 2})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        apprentice.skills["gathering"]["level"] = 3
        future = self.now + 1.0
        self.mgr.update([mentor, apprentice], reputation_manager=self.rep, event_bus=self.bus, current_time=future)
        grad_events = [e for e in events if getattr(e, "metadata", {}).get("type") == "mentorship_graduated"]
        self.assertEqual(len(grad_events), 1)


class TestMentorCapacity(unittest.TestCase):
    """Test max_apprentices_per_mentor enforcement."""

    def setUp(self):
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        self.bus = EventBus()
        self.mgr = MentorshipManager()
        self.mgr.attach_event_bus(self.bus)
        self.rep = MockReputationManager()
        self.now = time.time()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_medical_max_one_apprentice(self):
        """Medical mentorship allows max 1 apprentice."""
        mentor = MockPraxan(0, skill_levels={"medical": 4})
        app1 = MockPraxan(1, skill_levels={"medical": 1})
        app2 = MockPraxan(2, skill_levels={"medical": 1})
        app3 = MockPraxan(3, skill_levels={"medical": 1})
        self.mgr._last_eval_time = self.now - _EVAL_INTERVAL - 1
        self.mgr.update([mentor, app1, app2, app3], reputation_manager=self.rep, event_bus=self.bus, current_time=self.now)
        apprentices = self.mgr.get_mentor_apprentices(0)
        self.assertEqual(len(apprentices), 1)


if __name__ == "__main__":
    unittest.main()
