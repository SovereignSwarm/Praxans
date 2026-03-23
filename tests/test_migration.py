"""Tests for the Individual Migration & Faction Defection System (systems/migration.py).

Covers:
- MigrationDef loading from DefDatabase
- Push factor calculations (happiness, cohesion, reputation, friends, rivals,
  warfare, health, epidemic, family separation, doctrine mismatch)
- Pull factor calculations (cohesion, standing, family, friends, doctrine,
  warfare, epidemic)
- Defection execution (faction transfer, moodlets, cohesion, diplomacy, memory,
  EventBus, stats)
- Cooldowns and rate limiting
- Leader immunity
- Min faction size guard
- EventBus signal handling (warfare, death, disaster)
- Snapshot serialization / restoration
- Edge cases
"""

import time
import unittest

from events.bus import (
    CATEGORY_DEATH,
    CATEGORY_DISASTER,
    CATEGORY_MIGRATION,
    CATEGORY_WARFARE,
    EventBus,
    GameEvent,
)
from systems.def_database import DefDatabase
from systems.migration import (
    MigrationManager,
    clear_cache,
    get_all_migration_defs,
    get_migration_def,
    EVAL_INTERVAL,
    PER_FACTION_COOLDOWN,
    MAX_DEFECTIONS_PER_EVAL,
    MIN_FACTION_SIZE,
    LEADER_IMMUNE,
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
    def __init__(self, fid, member_ids=None, cohesion=50.0, leader_id=None,
                 primary_doctrine="growth"):
        self.id = fid
        self.member_ids = list(member_ids or [])
        self.cohesion = cohesion
        self.leader_id = leader_id
        self.primary_doctrine = primary_doctrine
        self.stability = 50.0

    def add_member(self, pid):
        if pid not in self.member_ids:
            self.member_ids.append(pid)

    def remove_member(self, pid):
        if pid in self.member_ids:
            self.member_ids.remove(pid)

    def get_members(self, praxans):
        return [p for p in praxans if p.id in self.member_ids]


class MockPraxan:
    def __init__(self, pid, faction_id=None, happiness=70.0, health=100.0,
                 relationships=None, personality=None, life_stage="adult",
                 alive=True, name=None, bonds=None, opinions=None):
        self.id = pid
        self.faction_id = faction_id
        self.happiness = happiness
        self.health = health
        self.relationships = relationships or {}
        self.personality = personality or {"curiosity": 0.5, "sociability": 0.5,
                                           "diligence": 0.5, "bravery": 0.5}
        self.life_stage = life_stage
        self.alive = alive
        self.name = name or f"Praxan_{pid}"
        self.bonds = bonds or {}
        self.opinions = opinions or {}
        self.moodlets = []
        self.morale = 65.0
        self._pending_reputation_events = []
        self.memory = MockMemory()

    def add_moodlet(self, name, value, duration, current_time):
        self.moodlets.append({
            "name": name, "value": value, "duration": duration,
            "start_time": current_time, "offset": value,
            "label": name, "applied_at": current_time,
        })


class MockMemory:
    def __init__(self):
        self.entries = []

    def record(self, category="", summary="", timestamp=None, metadata=None,
               related_ids=None, weight_override=None):
        self.entries.append({
            "category": category, "summary": summary,
            "timestamp": timestamp, "metadata": metadata,
        })


class MockFactionManager:
    def __init__(self, factions):
        self.factions = {f.id: f for f in factions}


class MockReputationManager:
    def __init__(self):
        self._reps = {}

    def get_reputation(self, pid):
        return self._reps.get(pid, 50)

    def set_reputation(self, pid, value):
        self._reps[pid] = value

    def record_event(self, pid, event_id):
        pass


class MockAdvisor:
    def __init__(self):
        self.observer_timeline = []


class MockNarrativePanel:
    def __init__(self):
        self.messages = []

    def add_message(self, text, category=""):
        self.messages.append({"text": text, "category": category})


# ---------------------------------------------------------------------------
# Test: Def Loading
# ---------------------------------------------------------------------------

class TestDefLoading(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_load_migration_defs(self):
        defs = get_all_migration_defs()
        self.assertGreater(len(defs), 0)

    def test_known_def_ids(self):
        defs = get_all_migration_defs()
        expected = {
            "discontent_defection", "war_refugee", "plague_flight",
            "family_reunion", "ideological_exile",
        }
        self.assertTrue(expected.issubset(set(defs.keys())))

    def test_get_single_def(self):
        mdef = get_migration_def("discontent_defection")
        self.assertIsNotNone(mdef)
        self.assertEqual(mdef["name"], "Discontent Defection")

    def test_get_missing_def(self):
        self.assertIsNone(get_migration_def("nonexistent"))

    def test_def_has_push_pull_factors(self):
        mdef = get_migration_def("war_refugee")
        self.assertIn("push_factors", mdef)
        self.assertIn("pull_factors", mdef)
        self.assertIn("discontent_threshold", mdef)
        self.assertIn("attraction_threshold", mdef)


# ---------------------------------------------------------------------------
# Test: Push Factor Calculation
# ---------------------------------------------------------------------------

class TestPushFactors(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = MigrationManager()
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_low_happiness_increases_discontent(self):
        mdef = get_migration_def("discontent_defection")
        praxan = MockPraxan(1, faction_id=0, happiness=20.0)
        faction = MockFaction(0, member_ids=[1, 2, 3, 4])

        score = self.manager._calc_discontent(
            praxan, faction, 0, mdef, self.now, {1: praxan}, None
        )
        self.assertGreater(score, 0.0)

    def test_high_happiness_no_discontent(self):
        mdef = get_migration_def("discontent_defection")
        # Give praxan friends in faction so "no_friends" doesn't fire
        praxan = MockPraxan(1, faction_id=0, happiness=90.0,
                             relationships={2: "friend"})
        faction = MockFaction(0, member_ids=[1, 2, 3, 4], cohesion=80.0)

        score = self.manager._calc_discontent(
            praxan, faction, 0, mdef, self.now, {1: praxan}, None
        )
        self.assertEqual(score, 0.0)

    def test_low_cohesion_adds_discontent(self):
        mdef = get_migration_def("discontent_defection")
        praxan = MockPraxan(1, faction_id=0, happiness=90.0)
        faction = MockFaction(0, member_ids=[1, 2, 3, 4], cohesion=10.0)

        score = self.manager._calc_discontent(
            praxan, faction, 0, mdef, self.now, {1: praxan}, None
        )
        self.assertGreater(score, 0.0)

    def test_outcast_reputation_adds_discontent(self):
        mdef = get_migration_def("discontent_defection")
        praxan = MockPraxan(1, faction_id=0, happiness=90.0)
        faction = MockFaction(0, member_ids=[1, 2, 3, 4], cohesion=80.0)
        rep_mgr = MockReputationManager()
        rep_mgr.set_reputation(1, 10)  # very low rep

        score = self.manager._calc_discontent(
            praxan, faction, 0, mdef, self.now, {1: praxan}, rep_mgr
        )
        self.assertGreater(score, 0.0)

    def test_no_friends_adds_discontent(self):
        mdef = get_migration_def("discontent_defection")
        praxan = MockPraxan(1, faction_id=0, happiness=90.0, relationships={})
        faction = MockFaction(0, member_ids=[1, 2, 3, 4], cohesion=80.0)

        score = self.manager._calc_discontent(
            praxan, faction, 0, mdef, self.now, {1: praxan}, None
        )
        # "no_friends" factor should add weight
        self.assertGreater(score, 0.0)

    def test_many_rivals_adds_discontent(self):
        mdef = get_migration_def("discontent_defection")
        praxan = MockPraxan(1, faction_id=0, happiness=90.0,
                             relationships={2: "rival", 3: "rival"})
        faction = MockFaction(0, member_ids=[1, 2, 3, 4], cohesion=80.0)

        score = self.manager._calc_discontent(
            praxan, faction, 0, mdef, self.now, {1: praxan}, None
        )
        self.assertGreater(score, 0.0)

    def test_recent_warfare_adds_discontent(self):
        mdef = get_migration_def("war_refugee")
        praxan = MockPraxan(1, faction_id=0, happiness=30.0)
        faction = MockFaction(0, member_ids=[1, 2, 3, 4])
        self.manager._recent_warfare[0] = [self.now - 10, self.now - 5]

        score = self.manager._calc_discontent(
            praxan, faction, 0, mdef, self.now, {1: praxan}, None
        )
        self.assertGreater(score, 0.0)

    def test_active_epidemic_adds_discontent(self):
        mdef = get_migration_def("plague_flight")
        praxan = MockPraxan(1, faction_id=0, happiness=50.0)
        faction = MockFaction(0, member_ids=[1, 2, 3, 4])
        self.manager._active_epidemics.add(0)

        score = self.manager._calc_discontent(
            praxan, faction, 0, mdef, self.now, {1: praxan}, None
        )
        self.assertGreater(score, 0.0)

    def test_family_in_other_faction_adds_discontent(self):
        mdef = get_migration_def("family_reunion")
        other = MockPraxan(2, faction_id=1)
        praxan = MockPraxan(1, faction_id=0, relationships={2: "partner"})
        faction = MockFaction(0, member_ids=[1, 3, 4, 5])

        score = self.manager._calc_discontent(
            praxan, faction, 0, mdef, self.now, {1: praxan, 2: other}, None
        )
        self.assertGreater(score, 0.0)

    def test_doctrine_mismatch_adds_discontent(self):
        mdef = get_migration_def("ideological_exile")
        # Low diligence/bravery praxan in security-focused faction
        praxan = MockPraxan(1, faction_id=0, happiness=40.0,
                             personality={"bravery": 0.1, "diligence": 0.1,
                                          "curiosity": 0.9, "sociability": 0.9})
        faction = MockFaction(0, member_ids=[1, 2, 3, 4],
                              primary_doctrine="security", cohesion=30.0)

        score = self.manager._calc_discontent(
            praxan, faction, 0, mdef, self.now, {1: praxan}, None
        )
        self.assertGreater(score, 0.0)


# ---------------------------------------------------------------------------
# Test: Pull Factor Calculation
# ---------------------------------------------------------------------------

class TestPullFactors(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = MigrationManager()
        self.diplo = MockDiplomacyManager()
        self.manager.set_systems(diplomacy_manager=self.diplo)
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_high_cohesion_attracts(self):
        mdef = get_migration_def("discontent_defection")
        praxan = MockPraxan(1, faction_id=0)
        target = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=80.0)

        score = self.manager._calc_attraction(
            praxan, target, 1, 0, mdef, {1: praxan}
        )
        self.assertGreater(score, 0.0)

    def test_friendly_standing_attracts(self):
        mdef = get_migration_def("discontent_defection")
        praxan = MockPraxan(1, faction_id=0)
        target = MockFaction(1, member_ids=[10, 11, 12, 13])
        self.diplo.set_standing(0, 1, 50)

        score = self.manager._calc_attraction(
            praxan, target, 1, 0, mdef, {1: praxan}
        )
        self.assertGreater(score, 0.0)

    def test_hostile_standing_no_attraction(self):
        mdef = get_migration_def("discontent_defection")
        praxan = MockPraxan(1, faction_id=0)
        target = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=30.0)
        self.diplo.set_standing(0, 1, -50)

        score = self.manager._calc_attraction(
            praxan, target, 1, 0, mdef, {1: praxan}
        )
        # No friendly standing bonus, low cohesion — minimal attraction
        self.assertLess(score, 2.0)

    def test_family_present_attracts(self):
        mdef = get_migration_def("family_reunion")
        partner = MockPraxan(2, faction_id=1)
        praxan = MockPraxan(1, faction_id=0, relationships={2: "partner"})
        target = MockFaction(1, member_ids=[2, 10, 11, 12])

        score = self.manager._calc_attraction(
            praxan, target, 1, 0, mdef, {1: praxan, 2: partner}
        )
        self.assertGreater(score, 3.0)  # family_present has weight 5.0

    def test_no_epidemic_attracts_for_plague_flight(self):
        mdef = get_migration_def("plague_flight")
        praxan = MockPraxan(1, faction_id=0)
        target = MockFaction(1, member_ids=[10, 11, 12, 13])
        # Target has no epidemic
        self.manager._active_epidemics = {0}  # source has epidemic

        score = self.manager._calc_attraction(
            praxan, target, 1, 0, mdef, {1: praxan}
        )
        self.assertGreater(score, 0.0)

    def test_no_warfare_attracts_for_war_refugee(self):
        mdef = get_migration_def("war_refugee")
        praxan = MockPraxan(1, faction_id=0)
        target = MockFaction(1, member_ids=[10, 11, 12, 13])
        # Source at war, target not
        self.manager._recent_warfare[0] = [self.now - 10]

        score = self.manager._calc_attraction(
            praxan, target, 1, 0, mdef, {1: praxan}
        )
        self.assertGreater(score, 0.0)

    def test_doctrine_match_attracts(self):
        mdef = get_migration_def("ideological_exile")
        # High curiosity praxan attracted to exploration faction
        praxan = MockPraxan(1, faction_id=0,
                             personality={"curiosity": 0.9, "sociability": 0.5,
                                          "diligence": 0.5, "bravery": 0.5})
        target = MockFaction(1, member_ids=[10, 11, 12, 13],
                             primary_doctrine="exploration")

        score = self.manager._calc_attraction(
            praxan, target, 1, 0, mdef, {1: praxan}
        )
        self.assertGreater(score, 0.0)


# ---------------------------------------------------------------------------
# Test: Defection Execution
# ---------------------------------------------------------------------------

class TestDefectionExecution(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = MigrationManager()
        self.diplo = MockDiplomacyManager()
        self.manager.set_systems(diplomacy_manager=self.diplo)
        self.bus = EventBus()
        self.manager._event_bus = self.bus
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def _make_defection_scenario(self):
        """Create a standard scenario: praxan 1 defecting from faction 0 to 1."""
        mdef = get_migration_def("discontent_defection")
        praxan = MockPraxan(1, faction_id=0, happiness=20.0, name="TestPraxan")
        source = MockFaction(0, member_ids=[1, 2, 3, 4], cohesion=50.0)
        target = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=60.0)
        praxans = [
            praxan,
            MockPraxan(2, faction_id=0), MockPraxan(3, faction_id=0),
            MockPraxan(4, faction_id=0),
            MockPraxan(10, faction_id=1), MockPraxan(11, faction_id=1),
            MockPraxan(12, faction_id=1), MockPraxan(13, faction_id=1),
        ]
        return mdef, praxan, source, target, praxans

    def test_faction_membership_transferred(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        self.assertNotIn(1, source.member_ids)
        self.assertIn(1, target.member_ids)
        self.assertEqual(praxan.faction_id, 1)

    def test_defector_gets_moodlet(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        mood_names = [m["name"] for m in praxan.moodlets]
        self.assertIn("DefectorAnxiety", mood_names)

    def test_source_members_get_moodlet(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        # Praxan 2 is in source faction
        p2 = next(p for p in praxans if p.id == 2)
        mood_names = [m["name"] for m in p2.moodlets]
        self.assertIn("MemberDefected", mood_names)

    def test_target_members_get_moodlet(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        p10 = next(p for p in praxans if p.id == 10)
        mood_names = [m["name"] for m in p10.moodlets]
        self.assertIn("NewcomerArrival", mood_names)

    def test_cohesion_impacts(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        source_before = source.cohesion
        target_before = target.cohesion
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        self.assertLess(source.cohesion, source_before)
        self.assertGreater(target.cohesion, target_before)

    def test_diplomacy_penalty(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        self.diplo.set_standing(0, 1, 0)
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        self.assertLess(self.diplo.get_standing(0, 1), 0)

    def test_reputation_event_queued(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        rep_mgr = MockReputationManager()
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans,
            reputation_manager=rep_mgr,
        )
        self.assertIn("defected_faction", praxan._pending_reputation_events)

    def test_episodic_memory_recorded(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        self.assertTrue(len(praxan.memory.entries) > 0)
        self.assertEqual(praxan.memory.entries[0]["category"], "migration")

    def test_eventbus_published(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        published = []
        self.bus.subscribe(CATEGORY_MIGRATION, lambda e: published.append(e))
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].metadata["type"], "individual_defection")

    def test_narrative_panel_notified(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        panel = MockNarrativePanel()
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans,
            narrative_panel=panel,
        )
        self.assertTrue(any("defected" in m["text"].lower() for m in panel.messages))

    def test_observer_timeline_updated(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        advisor = MockAdvisor()
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans,
            advisor=advisor,
        )
        self.assertTrue(len(advisor.observer_timeline) > 0)

    def test_stats_updated(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        self.assertEqual(self.manager.total_defections, 0)
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        self.assertEqual(self.manager.total_defections, 1)
        self.assertEqual(len(self.manager.defection_history), 1)

    def test_history_record_contains_details(self):
        mdef, praxan, source, target, praxans = self._make_defection_scenario()
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        record = self.manager.defection_history[0]
        self.assertEqual(record["praxan_id"], 1)
        self.assertEqual(record["source_faction_id"], 0)
        self.assertEqual(record["target_faction_id"], 1)

    def test_family_reunion_defector_gets_positive_mood(self):
        """Regression: FamilyReunion moodlet must use MoodDef offset (+8), not
        the hardcoded -5 that was incorrectly applied to all migration types."""
        mdef = get_migration_def("family_reunion")
        praxan = MockPraxan(1, faction_id=0, happiness=60.0, name="TestPraxan")
        source = MockFaction(0, member_ids=[1, 2, 3, 4], cohesion=50.0)
        target = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=60.0)
        praxans = [
            praxan,
            MockPraxan(2, faction_id=0), MockPraxan(3, faction_id=0),
            MockPraxan(4, faction_id=0),
            MockPraxan(10, faction_id=1), MockPraxan(11, faction_id=1),
            MockPraxan(12, faction_id=1), MockPraxan(13, faction_id=1),
        ]
        self.manager._execute_defection(
            praxan, source, 0, target, 1, mdef, self.now, praxans
        )
        defector_moodlets = [m for m in praxan.moodlets if m["name"] == "FamilyReunion"]
        self.assertEqual(len(defector_moodlets), 1)
        # Must be positive (+8 per MoodDef), not the old hardcoded -5
        self.assertGreater(defector_moodlets[0]["value"], 0,
                           "FamilyReunion defector moodlet must be positive")

    def test_moodlet_offsets_match_mooddefs(self):
        """All migration types' moodlets must use the offset from MoodDef."""
        from systems.def_database import DefDatabase
        mood_defs = DefDatabase.get_all("MoodDef")

        migration_moodlet_pairs = [
            ("discontent_defection", "moodlet_defector"),
            ("war_refugee",          "moodlet_defector"),
            ("plague_flight",        "moodlet_defector"),
            ("family_reunion",       "moodlet_defector"),
            ("ideological_exile",    "moodlet_defector"),
            ("family_reunion",       "moodlet_source_faction"),
            ("family_reunion",       "moodlet_target_faction"),
        ]

        for mdef_id, moodlet_key in migration_moodlet_pairs:
            mdef = get_migration_def(mdef_id)
            moodlet_id = mdef.get(moodlet_key)
            if moodlet_id not in mood_defs:
                continue
            expected_offset = mood_defs[moodlet_id].get("mood_offset")
            if expected_offset is None:
                continue

            praxan = MockPraxan(1, faction_id=0, name="TestPraxan")
            source = MockFaction(0, member_ids=[1, 2, 3, 4], cohesion=50.0)
            target = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=60.0)
            praxans = [
                praxan,
                MockPraxan(2, faction_id=0), MockPraxan(3, faction_id=0),
                MockPraxan(4, faction_id=0),
                MockPraxan(10, faction_id=1), MockPraxan(11, faction_id=1),
                MockPraxan(12, faction_id=1), MockPraxan(13, faction_id=1),
            ]
            self.manager._execute_defection(
                praxan, source, 0, target, 1, mdef, self.now, praxans
            )

            if moodlet_key == "moodlet_defector":
                applied = [m for m in praxan.moodlets if m["name"] == moodlet_id]
            elif moodlet_key == "moodlet_source_faction":
                p2 = next(p for p in praxans if p.id == 2)
                applied = [m for m in p2.moodlets if m["name"] == moodlet_id]
            else:
                p10 = next(p for p in praxans if p.id == 10)
                applied = [m for m in p10.moodlets if m["name"] == moodlet_id]

            self.assertTrue(
                len(applied) > 0,
                f"{mdef_id}.{moodlet_key} ({moodlet_id}) produced no moodlet"
            )
            self.assertAlmostEqual(
                applied[0]["value"], expected_offset, places=3,
                msg=(f"{mdef_id}.{moodlet_key} ({moodlet_id}): "
                     f"expected offset {expected_offset}, got {applied[0]['value']}")
            )


# ---------------------------------------------------------------------------
# Test: Update Guards (cooldowns, leader, min size, life stage)
# ---------------------------------------------------------------------------

class TestUpdateGuards(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = MigrationManager()
        self.diplo = MockDiplomacyManager()
        self.manager.set_systems(diplomacy_manager=self.diplo)
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_eval_interval_respected(self):
        """Update should not evaluate if interval hasn't passed."""
        self.manager._last_eval = self.now - 10  # only 10s ago
        faction0 = MockFaction(0, member_ids=[1, 2, 3, 4])
        faction1 = MockFaction(1, member_ids=[10, 11, 12, 13])
        fm = MockFactionManager([faction0, faction1])
        praxans = [MockPraxan(i, faction_id=0, happiness=10.0) for i in [1, 2, 3, 4]]
        praxans += [MockPraxan(i, faction_id=1) for i in [10, 11, 12, 13]]

        self.manager.update(
            faction_manager=fm, praxans=praxans, current_time=self.now
        )
        self.assertEqual(self.manager.total_defections, 0)

    def test_leader_immune(self):
        """Faction leaders should not defect."""
        self.manager._last_eval = 0.0
        faction0 = MockFaction(0, member_ids=[1, 2, 3, 4, 5], leader_id=1, cohesion=10.0)
        faction1 = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=80.0)
        self.diplo.set_standing(0, 1, 50)
        fm = MockFactionManager([faction0, faction1])

        # Praxan 1 is the leader — very unhappy but should not defect
        p1 = MockPraxan(1, faction_id=0, happiness=5.0, relationships={2: "rival", 3: "rival"})
        praxans = [
            p1,
            MockPraxan(2, faction_id=0, happiness=90.0),
            MockPraxan(3, faction_id=0, happiness=90.0),
            MockPraxan(4, faction_id=0, happiness=90.0),
            MockPraxan(5, faction_id=0, happiness=90.0),
            MockPraxan(10, faction_id=1), MockPraxan(11, faction_id=1),
            MockPraxan(12, faction_id=1), MockPraxan(13, faction_id=1),
        ]

        self.manager.update(
            faction_manager=fm, diplomacy_manager=self.diplo,
            praxans=praxans, current_time=self.now
        )
        # Leader should not have defected
        self.assertIn(1, faction0.member_ids)

    def test_min_faction_size_guard(self):
        """Factions at or below MIN_FACTION_SIZE don't lose members."""
        self.manager._last_eval = 0.0
        # Faction 0 has exactly MIN_FACTION_SIZE members
        faction0 = MockFaction(0, member_ids=list(range(MIN_FACTION_SIZE)), cohesion=10.0)
        faction1 = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=80.0)
        self.diplo.set_standing(0, 1, 50)
        fm = MockFactionManager([faction0, faction1])

        praxans = [MockPraxan(i, faction_id=0, happiness=5.0) for i in range(MIN_FACTION_SIZE)]
        praxans += [MockPraxan(i, faction_id=1) for i in [10, 11, 12, 13]]

        self.manager.update(
            faction_manager=fm, diplomacy_manager=self.diplo,
            praxans=praxans, current_time=self.now
        )
        self.assertEqual(self.manager.total_defections, 0)

    def test_infant_cannot_defect(self):
        """Infants should not be evaluated for migration."""
        self.manager._last_eval = 0.0
        faction0 = MockFaction(0, member_ids=[1, 2, 3, 4, 5], cohesion=10.0)
        faction1 = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=80.0)
        self.diplo.set_standing(0, 1, 50)
        fm = MockFactionManager([faction0, faction1])

        # Only unhappy praxan is an infant
        praxans = [
            MockPraxan(1, faction_id=0, happiness=5.0, life_stage="infant"),
            MockPraxan(2, faction_id=0, happiness=90.0),
            MockPraxan(3, faction_id=0, happiness=90.0),
            MockPraxan(4, faction_id=0, happiness=90.0),
            MockPraxan(5, faction_id=0, happiness=90.0),
            MockPraxan(10, faction_id=1), MockPraxan(11, faction_id=1),
            MockPraxan(12, faction_id=1), MockPraxan(13, faction_id=1),
        ]

        self.manager.update(
            faction_manager=fm, diplomacy_manager=self.diplo,
            praxans=praxans, current_time=self.now
        )
        self.assertEqual(self.manager.total_defections, 0)

    def test_single_faction_no_migration(self):
        """Need at least 2 factions for migration."""
        self.manager._last_eval = 0.0
        faction0 = MockFaction(0, member_ids=[1, 2, 3, 4], cohesion=10.0)
        fm = MockFactionManager([faction0])

        praxans = [MockPraxan(i, faction_id=0, happiness=5.0) for i in [1, 2, 3, 4]]

        self.manager.update(
            faction_manager=fm, praxans=praxans, current_time=self.now
        )
        self.assertEqual(self.manager.total_defections, 0)

    def test_per_faction_cooldown(self):
        """After a defection, same-faction cooldown is enforced."""
        self.manager._last_eval = 0.0
        self.manager._faction_cooldowns[0] = self.now - 10  # cooled down 10s ago (too recent)

        faction0 = MockFaction(0, member_ids=[1, 2, 3, 4, 5], cohesion=10.0)
        faction1 = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=80.0)
        self.diplo.set_standing(0, 1, 50)
        fm = MockFactionManager([faction0, faction1])

        praxans = [MockPraxan(i, faction_id=0, happiness=5.0) for i in [1, 2, 3, 4, 5]]
        praxans += [MockPraxan(i, faction_id=1) for i in [10, 11, 12, 13]]

        self.manager.update(
            faction_manager=fm, diplomacy_manager=self.diplo,
            praxans=praxans, current_time=self.now
        )
        self.assertEqual(self.manager.total_defections, 0)

    def test_dead_praxan_skipped(self):
        """Dead praxans should not be evaluated."""
        self.manager._last_eval = 0.0
        faction0 = MockFaction(0, member_ids=[1, 2, 3, 4, 5], cohesion=10.0)
        faction1 = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=80.0)
        self.diplo.set_standing(0, 1, 50)
        fm = MockFactionManager([faction0, faction1])

        praxans = [
            MockPraxan(1, faction_id=0, happiness=5.0, alive=False),
            MockPraxan(2, faction_id=0, happiness=90.0),
            MockPraxan(3, faction_id=0, happiness=90.0),
            MockPraxan(4, faction_id=0, happiness=90.0),
            MockPraxan(5, faction_id=0, happiness=90.0),
            MockPraxan(10, faction_id=1), MockPraxan(11, faction_id=1),
            MockPraxan(12, faction_id=1), MockPraxan(13, faction_id=1),
        ]

        self.manager.update(
            faction_manager=fm, diplomacy_manager=self.diplo,
            praxans=praxans, current_time=self.now
        )
        self.assertEqual(self.manager.total_defections, 0)


# ---------------------------------------------------------------------------
# Test: EventBus Signal Handling
# ---------------------------------------------------------------------------

class TestEventBusHandlers(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = MigrationManager()
        self.bus = EventBus()
        self.manager.attach_event_bus(self.bus)
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_warfare_event_recorded(self):
        event = GameEvent(
            category=CATEGORY_WARFARE,
            summary="Raid occurred",
            timestamp=self.now,
            metadata={"attacker_faction_id": 0, "defender_faction_id": 1},
        )
        self.bus.publish(event)
        self.assertIn(0, self.manager._recent_warfare)
        self.assertIn(1, self.manager._recent_warfare)

    def test_death_event_recorded(self):
        event = GameEvent(
            category=CATEGORY_DEATH,
            summary="Praxan died",
            faction_id=0,
            timestamp=self.now,
        )
        self.bus.publish(event)
        self.assertIn(0, self.manager._recent_deaths)

    def test_epidemic_event_recorded(self):
        event = GameEvent(
            category=CATEGORY_DISASTER,
            summary="Epidemic started",
            faction_id=0,
            timestamp=self.now,
            metadata={"type": "epidemic"},
        )
        self.bus.publish(event)
        self.assertIn(0, self.manager._active_epidemics)

    def test_epidemic_ended_clears(self):
        self.manager._active_epidemics.add(0)
        event = GameEvent(
            category=CATEGORY_DISASTER,
            summary="Epidemic ended",
            faction_id=0,
            timestamp=self.now,
            metadata={"type": "epidemic_ended"},
        )
        self.bus.publish(event)
        self.assertNotIn(0, self.manager._active_epidemics)


# ---------------------------------------------------------------------------
# Test: Serialization
# ---------------------------------------------------------------------------

class TestSerialization(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = MigrationManager()
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_serialize_empty(self):
        data = self.manager.serialize(self.now)
        self.assertIn("total_defections", data)
        self.assertEqual(data["total_defections"], 0)

    def test_serialize_with_state(self):
        self.manager.total_defections = 3
        self.manager.defection_history = [
            {"type": "test", "praxan_id": 1, "source_faction_id": 0,
             "target_faction_id": 1, "time": self.now},
        ]
        self.manager._faction_cooldowns[0] = self.now - 30.0
        self.manager._active_epidemics = {0, 1}
        self.manager._last_eval = self.now - 15.0

        data = self.manager.serialize(self.now)
        self.assertEqual(data["total_defections"], 3)
        self.assertEqual(len(data["history"]), 1)
        self.assertEqual(len(data["active_epidemics"]), 2)
        self.assertAlmostEqual(data["last_eval_elapsed"], 15.0, places=1)

    def test_restore_round_trip(self):
        self.manager.total_defections = 5
        self.manager._faction_cooldowns[0] = self.now - 60.0
        self.manager._active_epidemics = {2}
        self.manager._last_eval = self.now - 20.0

        data = self.manager.serialize(self.now)

        new_mgr = MigrationManager()
        restore_time = self.now + 10.0  # simulate time passing
        new_mgr.restore(data, restore_time)

        self.assertEqual(new_mgr.total_defections, 5)
        self.assertIn(2, new_mgr._active_epidemics)
        # Cooldown was 60s before self.now; serialized as 60s elapsed.
        # Restored at restore_time (self.now + 10): cooldown_time = restore_time - 60 = self.now - 50
        # So elapsed from restore_time = 60s (not 70s, because snapshot stores elapsed from save time)
        self.assertAlmostEqual(
            restore_time - new_mgr._faction_cooldowns[0], 60.0, delta=1.0
        )

    def test_restore_preserves_history(self):
        self.manager.defection_history = [
            {"type": "test", "praxan_id": 1, "source_faction_id": 0,
             "target_faction_id": 1, "time": self.now},
        ]
        data = self.manager.serialize(self.now)

        new_mgr = MigrationManager()
        new_mgr.restore(data, self.now)
        self.assertEqual(len(new_mgr.defection_history), 1)


# ---------------------------------------------------------------------------
# Test: Queries
# ---------------------------------------------------------------------------

class TestQueries(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = MigrationManager()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_get_recent_defections_empty(self):
        self.assertEqual(self.manager.get_recent_defections(), [])

    def test_get_recent_defections(self):
        self.manager.defection_history = [
            {"type": "test", "praxan_id": 1, "source_faction_id": 0,
             "target_faction_id": 1, "time": 100.0},
            {"type": "test", "praxan_id": 2, "source_faction_id": 0,
             "target_faction_id": 1, "time": 200.0},
        ]
        result = self.manager.get_recent_defections(1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["praxan_id"], 2)

    def test_get_faction_defection_count(self):
        self.manager.defection_history = [
            {"type": "a", "praxan_id": 1, "source_faction_id": 0, "target_faction_id": 1},
            {"type": "b", "praxan_id": 2, "source_faction_id": 0, "target_faction_id": 2},
            {"type": "c", "praxan_id": 3, "source_faction_id": 1, "target_faction_id": 0},
        ]
        self.assertEqual(self.manager.get_faction_defection_count(0), 2)
        self.assertEqual(self.manager.get_faction_defection_count(1), 1)

    def test_get_faction_immigration_count(self):
        self.manager.defection_history = [
            {"type": "a", "praxan_id": 1, "source_faction_id": 0, "target_faction_id": 1},
            {"type": "b", "praxan_id": 2, "source_faction_id": 0, "target_faction_id": 1},
        ]
        self.assertEqual(self.manager.get_faction_immigration_count(1), 2)
        self.assertEqual(self.manager.get_faction_immigration_count(0), 0)


# ---------------------------------------------------------------------------
# Test: Doctrine Mismatch Helper
# ---------------------------------------------------------------------------

class TestDoctrineMismatch(unittest.TestCase):
    def test_perfect_match(self):
        praxan = MockPraxan(1, personality={"curiosity": 0.9, "sociability": 0.5,
                                             "diligence": 0.5, "bravery": 0.5})
        faction = MockFaction(0, primary_doctrine="exploration")
        score = MigrationManager._doctrine_mismatch_score(praxan, faction)
        self.assertLess(score, 0.2)  # low mismatch = good match

    def test_total_mismatch(self):
        praxan = MockPraxan(1, personality={"curiosity": 0.1, "sociability": 0.1,
                                             "diligence": 0.1, "bravery": 0.1})
        faction = MockFaction(0, primary_doctrine="exploration")
        score = MigrationManager._doctrine_mismatch_score(praxan, faction)
        self.assertGreater(score, 0.8)  # high mismatch

    def test_no_personality(self):
        praxan = MockPraxan(1, personality={})
        faction = MockFaction(0, primary_doctrine="growth")
        score = MigrationManager._doctrine_mismatch_score(praxan, faction)
        self.assertEqual(score, 0.5)  # neutral


# ---------------------------------------------------------------------------
# Test: Cleanup
# ---------------------------------------------------------------------------

class TestCleanup(unittest.TestCase):
    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = MigrationManager()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_remove_faction_clears_state(self):
        self.manager._faction_cooldowns[5] = 100.0
        self.manager._recent_warfare[5] = [100.0]
        self.manager._recent_deaths[5] = [100.0]
        self.manager._active_epidemics.add(5)

        self.manager.remove_faction(5)

        self.assertNotIn(5, self.manager._faction_cooldowns)
        self.assertNotIn(5, self.manager._recent_warfare)
        self.assertNotIn(5, self.manager._recent_deaths)
        self.assertNotIn(5, self.manager._active_epidemics)


# ---------------------------------------------------------------------------
# Test: Full Integration Scenario
# ---------------------------------------------------------------------------

class TestFullIntegration(unittest.TestCase):
    """End-to-end test: set up a scenario where defection should happen."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.manager = MigrationManager()
        self.diplo = MockDiplomacyManager()
        self.bus = EventBus()
        self.manager.set_systems(diplomacy_manager=self.diplo)
        self.manager.attach_event_bus(self.bus)
        self.now = 5000.0

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_unhappy_praxan_defects_to_friendly_faction(self):
        """Very unhappy praxan with many push factors should defect to a
        friendly faction with pull factors."""
        self.manager._last_eval = 0.0

        # Source: very low cohesion, praxan very unhappy, has rivals
        source = MockFaction(0, member_ids=[1, 2, 3, 4, 5], cohesion=5.0)
        # Target: high cohesion, very friendly standing
        target = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=90.0)
        self.diplo.set_standing(0, 1, 80)  # allied-level

        fm = MockFactionManager([source, target])

        # Praxan 1: extremely unhappy, low cohesion, rivals, no friends,
        # outcast rep — maximal push factors
        praxans = [
            MockPraxan(1, faction_id=0, happiness=5.0,
                       relationships={2: "rival", 3: "rival", 4: "rival"}),
            MockPraxan(2, faction_id=0, happiness=80.0),
            MockPraxan(3, faction_id=0, happiness=80.0),
            MockPraxan(4, faction_id=0, happiness=80.0),
            MockPraxan(5, faction_id=0, happiness=80.0),
            MockPraxan(10, faction_id=1), MockPraxan(11, faction_id=1),
            MockPraxan(12, faction_id=1), MockPraxan(13, faction_id=1),
        ]

        rep_mgr = MockReputationManager()
        rep_mgr.set_reputation(1, 5)  # deeply outcast

        self.manager.update(
            faction_manager=fm, diplomacy_manager=self.diplo,
            praxans=praxans, current_time=self.now,
            reputation_manager=rep_mgr,
        )

        self.assertEqual(self.manager.total_defections, 1)
        self.assertNotIn(1, source.member_ids)
        self.assertIn(1, target.member_ids)

    def test_family_reunion_migration(self):
        """Praxan with partner in other faction should migrate for reunion."""
        self.manager._last_eval = 0.0

        source = MockFaction(0, member_ids=[1, 2, 3, 4, 5], cohesion=40.0)
        target = MockFaction(1, member_ids=[10, 11, 12, 13], cohesion=60.0)
        self.diplo.set_standing(0, 1, 0)  # neutral

        fm = MockFactionManager([source, target])

        partner = MockPraxan(10, faction_id=1)
        praxans = [
            MockPraxan(1, faction_id=0, happiness=35.0,
                       relationships={10: "partner"}),
            MockPraxan(2, faction_id=0, happiness=80.0),
            MockPraxan(3, faction_id=0, happiness=80.0),
            MockPraxan(4, faction_id=0, happiness=80.0),
            MockPraxan(5, faction_id=0, happiness=80.0),
            partner, MockPraxan(11, faction_id=1),
            MockPraxan(12, faction_id=1), MockPraxan(13, faction_id=1),
        ]

        self.manager.update(
            faction_manager=fm, diplomacy_manager=self.diplo,
            praxans=praxans, current_time=self.now,
        )

        self.assertEqual(self.manager.total_defections, 1)
        self.assertIn(1, target.member_ids)
