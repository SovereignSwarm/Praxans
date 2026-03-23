"""Tests for the Reputation & Social Hierarchy system (systems/reputation.py)."""

import unittest
import time

from systems.reputation import (
    ReputationManager,
    get_event_def,
    get_all_event_defs,
    get_tier_for_reputation,
    clear_cache,
    _tier_rank,
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
        self.needs = {"hunger": 80.0, "energy": 80.0, "social": 50.0}
        self.bonds = {}
        self.opinions = {}
        self.moodlets = []
        self.personality = {"curiosity": 0.5, "sociability": 0.7, "diligence": 0.5}
        self.episodic_memory = StubMemory()
        self.traits = []
        self.role = "gatherer"
        self.skills = {"gathering": {"level": 3, "xp": 0.0}}
        self.genetics = {"social_cohesion": 1.0}
        self._pending_reputation_events = []

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


class StubFaction:
    def __init__(self, faction_id=0, member_ids=None, leader_id=None):
        self.id = faction_id
        self.member_ids = list(member_ids or [])
        self.leader_id = leader_id or (self.member_ids[0] if self.member_ids else None)
        self.primary_doctrine = "growth"
        self.cohesion = 60.0


class StubFactionManager:
    def __init__(self, factions=None):
        # Accept list for convenience but store as dict {faction.id: faction}
        # to match the real FactionManager.factions structure.
        if isinstance(factions, list):
            self.factions = {f.id: f for f in factions}
        else:
            self.factions = factions or {}


class StubEventBus:
    def __init__(self):
        self.published = []
        self._subscribers = {}

    def publish(self, event):
        self.published.append(event)

    def subscribe(self, category, handler):
        self._subscribers.setdefault(category, []).append(handler)

    def fire(self, event):
        """Fire event through subscribers (for testing)."""
        category = getattr(event, "category", "")
        for handler in self._subscribers.get(category, []):
            handler(event)
        for handler in self._subscribers.get("*", []):
            handler(event)


class StubGameEvent:
    def __init__(self, category="personal", summary="", praxan_id=None, metadata=None):
        self.category = category
        self.summary = summary
        self.praxan_id = praxan_id
        self.metadata = metadata or {}


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestReputationDefs(unittest.TestCase):
    """Tests for ReputationEventDef and ReputationTierDef loading."""

    def setUp(self):
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")

    def tearDown(self):
        clear_cache()

    def test_event_defs_loaded(self):
        defs = get_all_event_defs()
        self.assertGreater(len(defs), 10, "Should load at least 10 reputation event defs")

    def test_built_structure_def_exists(self):
        edef = get_event_def("built_structure")
        self.assertIsNotNone(edef)
        self.assertEqual(edef["delta"], 3)

    def test_insult_given_def_exists(self):
        edef = get_event_def("insult_given")
        self.assertIsNotNone(edef)
        self.assertLess(edef["delta"], 0, "Insult should have negative delta")

    def test_masterwork_def_exists(self):
        edef = get_event_def("crafted_masterwork")
        self.assertIsNotNone(edef)
        self.assertGreater(edef["delta"], 5, "Masterwork should have high positive delta")

    def test_tier_for_high_reputation(self):
        tier = get_tier_for_reputation(85.0)
        self.assertEqual(tier["id"], "luminary")

    def test_tier_for_medium_reputation(self):
        tier = get_tier_for_reputation(50.0)
        self.assertEqual(tier["id"], "established")

    def test_tier_for_low_reputation(self):
        tier = get_tier_for_reputation(10.0)
        self.assertEqual(tier["id"], "outcast")

    def test_tier_for_marginal_reputation(self):
        tier = get_tier_for_reputation(30.0)
        self.assertEqual(tier["id"], "marginal")

    def test_tier_for_respected_reputation(self):
        tier = get_tier_for_reputation(65.0)
        self.assertEqual(tier["id"], "respected")

    def test_tier_boundary_luminary(self):
        tier = get_tier_for_reputation(80.0)
        self.assertEqual(tier["id"], "luminary")

    def test_tier_boundary_outcast(self):
        tier = get_tier_for_reputation(0.0)
        self.assertEqual(tier["id"], "outcast")

    def test_unknown_event_returns_none(self):
        edef = get_event_def("nonexistent_event_xyz")
        self.assertIsNone(edef)


class TestReputationManager(unittest.TestCase):
    """Tests for the core ReputationManager logic."""

    def setUp(self):
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0
        self.mgr = ReputationManager()

    def tearDown(self):
        clear_cache()

    def test_default_reputation(self):
        self.assertEqual(self.mgr.get_reputation(42), 50.0)

    def test_default_tier(self):
        self.assertEqual(self.mgr.get_tier(42), "established")

    def test_record_positive_event(self):
        delta = self.mgr.record_event(1, "built_structure")
        self.assertGreater(delta, 0)
        self.assertGreater(self.mgr.get_reputation(1), 50.0)

    def test_record_negative_event(self):
        delta = self.mgr.record_event(1, "insult_given")
        self.assertLess(delta, 0)
        self.assertLess(self.mgr.get_reputation(1), 50.0)

    def test_record_unknown_event_returns_zero(self):
        delta = self.mgr.record_event(1, "does_not_exist")
        self.assertEqual(delta, 0.0)

    def test_reputation_clamped_at_100(self):
        self.mgr.set_reputation(1, 98.0)
        self.mgr.record_event(1, "crafted_masterwork")  # +8
        self.assertLessEqual(self.mgr.get_reputation(1), 100.0)

    def test_reputation_clamped_at_0(self):
        self.mgr.set_reputation(1, 2.0)
        self.mgr.record_event(1, "fled_combat")  # -5
        self.assertGreaterEqual(self.mgr.get_reputation(1), 0.0)

    def test_multiplier(self):
        delta1 = self.mgr.record_event(1, "built_structure", multiplier=1.0)
        self.mgr.set_reputation(2, 50.0)
        delta2 = self.mgr.record_event(2, "built_structure", multiplier=2.0)
        self.assertAlmostEqual(delta2, delta1 * 2.0, places=2)

    def test_set_reputation(self):
        self.mgr.set_reputation(1, 75.0)
        self.assertEqual(self.mgr.get_reputation(1), 75.0)

    def test_set_reputation_clamped(self):
        self.mgr.set_reputation(1, 150.0)
        self.assertEqual(self.mgr.get_reputation(1), 100.0)
        self.mgr.set_reputation(1, -20.0)
        self.assertEqual(self.mgr.get_reputation(1), 0.0)

    def test_remove_praxan(self):
        self.mgr.set_reputation(1, 80.0)
        self.mgr.remove_praxan(1)
        self.assertEqual(self.mgr.get_reputation(1), 50.0)  # defaults back

    def test_event_log_bounded(self):
        for i in range(50):
            self.mgr.record_event(1, "built_structure")
        log = self.mgr._event_log.get(1, [])
        self.assertLessEqual(len(log), 30)


class TestReputationTierTransitions(unittest.TestCase):
    """Tests for tier transition detection, moodlets, memory, events."""

    def setUp(self):
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0
        self.mgr = ReputationManager()
        self.bus = StubEventBus()

    def tearDown(self):
        clear_cache()

    def test_tier_transition_to_luminary(self):
        p = StubPraxan()
        self.mgr.set_reputation(p.id, 85.0)
        now = time.time()
        self.mgr._last_eval_time = now - 40  # force tier eval
        self.mgr.update([p], event_bus=self.bus, current_time=now)

        self.assertEqual(self.mgr.get_tier(p.id), "luminary")
        # Check memory was recorded
        memory_cats = [e["category"] for e in p.episodic_memory.entries]
        self.assertIn("became_luminary", memory_cats)

    def test_tier_transition_to_outcast(self):
        p = StubPraxan()
        self.mgr.set_reputation(p.id, 10.0)
        now = time.time()
        self.mgr._last_eval_time = now - 40
        self.mgr.update([p], event_bus=self.bus, current_time=now)

        self.assertEqual(self.mgr.get_tier(p.id), "outcast")
        memory_cats = [e["category"] for e in p.episodic_memory.entries]
        self.assertIn("became_outcast", memory_cats)

    def test_tier_transition_publishes_event(self):
        p = StubPraxan()
        self.mgr.set_reputation(p.id, 85.0)
        now = time.time()
        self.mgr._last_eval_time = now - 40
        self.mgr.update([p], event_bus=self.bus, current_time=now)

        personal_events = [e for e in self.bus.published if e.category == "personal"]
        self.assertGreater(len(personal_events), 0, "Tier transition should publish event")
        self.assertIn("Luminary", personal_events[0].summary)

    def test_rising_tier_gives_positive_moodlet(self):
        p = StubPraxan()
        self.mgr.set_reputation(p.id, 85.0)
        now = time.time()
        self.mgr._last_eval_time = now - 40
        self.mgr.update([p], event_bus=self.bus, current_time=now)

        moodlet_names = [m["name"] for m in p.moodlets]
        self.assertIn("GainedReputation", moodlet_names)

    def test_falling_tier_gives_negative_moodlet(self):
        p = StubPraxan()
        # Start at respected, fall to marginal
        self.mgr.set_reputation(p.id, 65.0)
        self.mgr._tiers[p.id] = "respected"
        self.mgr.set_reputation(p.id, 25.0)
        now = time.time()
        self.mgr._last_eval_time = now - 40
        self.mgr.update([p], event_bus=self.bus, current_time=now)

        moodlet_names = [m["name"] for m in p.moodlets]
        self.assertIn("LostReputation", moodlet_names)

    def test_tier_moodlet_refreshed(self):
        """Tier moodlets should be refreshed on each evaluation."""
        p = StubPraxan()
        self.mgr.set_reputation(p.id, 85.0)
        self.mgr._tiers[p.id] = "luminary"  # already at tier
        now = time.time()
        self.mgr._last_eval_time = now - 40
        self.mgr.update([p], event_bus=self.bus, current_time=now)

        moodlet_names = [m["name"] for m in p.moodlets]
        self.assertIn("Luminary", moodlet_names)

    def test_no_transition_when_tier_unchanged(self):
        p = StubPraxan()
        self.mgr.set_reputation(p.id, 50.0)
        self.mgr._tiers[p.id] = "established"
        now = time.time()
        self.mgr._last_eval_time = now - 40
        self.mgr.update([p], event_bus=self.bus, current_time=now)

        # No transition events should fire
        personal_events = [e for e in self.bus.published if e.category == "personal"]
        self.assertEqual(len(personal_events), 0)


class TestReputationDrift(unittest.TestCase):
    """Tests for natural drift toward 50."""

    def setUp(self):
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0
        self.mgr = ReputationManager()

    def tearDown(self):
        clear_cache()

    def test_high_rep_drifts_down(self):
        p = StubPraxan()
        self.mgr.set_reputation(p.id, 80.0)
        now = time.time()
        self.mgr._last_eval_time = now - 40
        self.mgr.update([p], current_time=now)
        self.assertLess(self.mgr.get_reputation(p.id), 80.0)

    def test_low_rep_drifts_up(self):
        p = StubPraxan()
        self.mgr.set_reputation(p.id, 20.0)
        now = time.time()
        self.mgr._last_eval_time = now - 40
        self.mgr.update([p], current_time=now)
        self.assertGreater(self.mgr.get_reputation(p.id), 20.0)

    def test_no_drift_below_interval(self):
        p = StubPraxan()
        self.mgr.set_reputation(p.id, 80.0)
        now = time.time()
        self.mgr._last_eval_time = now  # just evaluated
        self.mgr.update([p], current_time=now + 5)
        self.assertEqual(self.mgr.get_reputation(p.id), 80.0)


class TestLeadershipBonus(unittest.TestCase):
    """Tests for leadership election score bonus."""

    def setUp(self):
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        clear_cache()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0
        self.mgr = ReputationManager()

    def tearDown(self):
        clear_cache()

    def test_high_rep_gives_positive_bonus(self):
        self.mgr.set_reputation(1, 90.0)
        bonus = self.mgr.leadership_score_bonus(1)
        self.assertGreater(bonus, 0)

    def test_low_rep_gives_negative_bonus(self):
        self.mgr.set_reputation(1, 10.0)
        bonus = self.mgr.leadership_score_bonus(1)
        self.assertLess(bonus, 0)

    def test_default_rep_gives_zero_bonus(self):
        bonus = self.mgr.leadership_score_bonus(42)
        self.assertAlmostEqual(bonus, 0.0, places=2)

    def test_leadership_tenure_grants_rep(self):
        p = StubPraxan()
        fm = StubFactionManager([StubFaction(0, [p.id], leader_id=p.id)])
        self.mgr.set_reputation(p.id, 50.0)
        now = time.time()
        self.mgr._last_eval_time = now - 40
        self.mgr.update([p], faction_manager=fm, current_time=now)
        # Leader should have gained rep from tenure
        self.assertGreater(self.mgr.get_reputation(p.id), 50.0)


class TestSocialWeightModifier(unittest.TestCase):
    """Tests for social interaction target weighting."""

    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = ReputationManager()

    def tearDown(self):
        clear_cache()

    def test_high_rep_increases_weight(self):
        self.mgr.set_reputation(1, 80.0)
        weight = self.mgr.social_weight_modifier(1)
        self.assertGreater(weight, 1.0)

    def test_low_rep_decreases_weight(self):
        self.mgr.set_reputation(1, 20.0)
        weight = self.mgr.social_weight_modifier(1)
        self.assertLess(weight, 1.0)

    def test_default_rep_gives_1x_weight(self):
        weight = self.mgr.social_weight_modifier(42)
        self.assertAlmostEqual(weight, 1.0, places=1)


class TestFactionHierarchy(unittest.TestCase):
    """Tests for faction hierarchy queries."""

    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = ReputationManager()

    def tearDown(self):
        clear_cache()

    def test_hierarchy_sorted_descending(self):
        self.mgr.set_reputation(1, 90.0)
        self.mgr.set_reputation(2, 30.0)
        self.mgr.set_reputation(3, 60.0)
        hierarchy = self.mgr.get_faction_hierarchy([1, 2, 3])
        self.assertEqual([h[0] for h in hierarchy], [1, 3, 2])

    def test_get_luminaries(self):
        self.mgr.set_reputation(1, 85.0)
        self.mgr.set_reputation(2, 40.0)
        self.mgr.set_reputation(3, 92.0)
        luminaries = self.mgr.get_luminaries([1, 2, 3])
        self.assertEqual(sorted(luminaries), [1, 3])

    def test_get_outcasts(self):
        self.mgr.set_reputation(1, 10.0)
        self.mgr.set_reputation(2, 50.0)
        self.mgr.set_reputation(3, 5.0)
        outcasts = self.mgr.get_outcasts([1, 2, 3])
        self.assertEqual(sorted(outcasts), [1, 3])


class TestSerialization(unittest.TestCase):
    """Tests for snapshot serialization and restoration."""

    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = ReputationManager()

    def tearDown(self):
        clear_cache()

    def test_serialize_roundtrip(self):
        self.mgr.set_reputation(1, 85.0)
        self.mgr.set_reputation(2, 25.0)
        self.mgr._tiers[1] = "luminary"
        self.mgr._tiers[2] = "marginal"

        data = self.mgr.serialize()
        mgr2 = ReputationManager()
        mgr2.restore(data)

        self.assertAlmostEqual(mgr2.get_reputation(1), 85.0, places=1)
        self.assertAlmostEqual(mgr2.get_reputation(2), 25.0, places=1)
        self.assertEqual(mgr2._tiers[1], "luminary")
        self.assertEqual(mgr2._tiers[2], "marginal")

    def test_serialize_empty(self):
        data = self.mgr.serialize()
        self.assertEqual(data["scores"], {})
        self.assertEqual(data["tiers"], {})

    def test_restore_clamps_values(self):
        self.mgr.restore({"scores": {"1": 150.0, "2": -20.0}, "tiers": {}})
        self.assertEqual(self.mgr.get_reputation(1), 100.0)
        self.assertEqual(self.mgr.get_reputation(2), 0.0)

    def test_restore_invalid_data_skipped(self):
        self.mgr.restore({"scores": {"not_a_number": 50.0, "abc": "xyz"}, "tiers": {}})
        # Should not crash — invalid entries silently skipped
        self.assertEqual(len(self.mgr._scores), 0)


class TestEventBusIntegration(unittest.TestCase):
    """Tests for EventBus subscription and auto-recording."""

    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0
        self.mgr = ReputationManager()
        self.bus = StubEventBus()
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()

    def test_attach_subscribes_to_categories(self):
        self.assertIn("personal", self.bus._subscribers)
        self.assertIn("death", self.bus._subscribers)
        self.assertIn("disaster", self.bus._subscribers)

    def test_disease_recovery_event(self):
        self.mgr.set_reputation(1, 50.0)
        event = StubGameEvent("personal", "recovered", praxan_id=1,
                              metadata={"type": "disease_recovered"})
        self.bus.fire(event)
        self.assertGreater(self.mgr.get_reputation(1), 50.0)

    def test_insult_interaction_event(self):
        self.mgr.set_reputation(1, 50.0)
        event = StubGameEvent("personal", "insult", praxan_id=None,
                              metadata={"interaction": "insult", "initiator": 1, "target": 2})
        self.bus.fire(event)
        self.assertLess(self.mgr.get_reputation(1), 50.0)

    def test_teach_interaction_event(self):
        self.mgr.set_reputation(1, 50.0)
        event = StubGameEvent("personal", "teach", praxan_id=None,
                              metadata={"interaction": "teach", "initiator": 1, "target": 2})
        self.bus.fire(event)
        self.assertGreater(self.mgr.get_reputation(1), 50.0)

    def test_death_event_removes_praxan(self):
        self.mgr.set_reputation(5, 80.0)
        event = StubGameEvent("death", "died", praxan_id=5)
        self.bus.fire(event)
        # After removal, should return default
        self.assertEqual(self.mgr.get_reputation(5), 50.0)

    def test_disaster_survivors_gain_rep(self):
        self.mgr.set_reputation(1, 50.0)
        self.mgr.set_reputation(2, 50.0)
        event = StubGameEvent("disaster", "earthquake",
                              metadata={"survivors": [1, 2]})
        self.bus.fire(event)
        self.assertGreater(self.mgr.get_reputation(1), 50.0)
        self.assertGreater(self.mgr.get_reputation(2), 50.0)


class TestPendingReputationEvents(unittest.TestCase):
    """Tests for entity-queued reputation events (crafting, mental breaks)."""

    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0
        self.mgr = ReputationManager()

    def tearDown(self):
        clear_cache()

    def test_pending_crafted_item_event_drained(self):
        p = StubPraxan()
        p._pending_reputation_events = ["crafted_item"]
        self.mgr.update([p], current_time=time.time())
        self.assertGreater(self.mgr.get_reputation(p.id), 50.0)
        self.assertEqual(len(p._pending_reputation_events), 0)

    def test_pending_masterwork_event_drained(self):
        p = StubPraxan()
        p._pending_reputation_events = ["crafted_masterwork"]
        self.mgr.update([p], current_time=time.time())
        rep = self.mgr.get_reputation(p.id)
        self.assertGreater(rep, 55.0, "Masterwork should give significant rep boost")

    def test_pending_mental_break_event_drained(self):
        p = StubPraxan()
        p._pending_reputation_events = ["mental_break"]
        self.mgr.update([p], current_time=time.time())
        self.assertLess(self.mgr.get_reputation(p.id), 50.0)

    def test_multiple_pending_events_all_drained(self):
        p = StubPraxan()
        p._pending_reputation_events = ["crafted_item", "crafted_item", "mental_break"]
        now = time.time()
        self.mgr._last_eval_time = now  # prevent drift from interfering
        self.mgr.update([p], current_time=now + 1)
        # Net: +2 +2 -3 = +1
        rep = self.mgr.get_reputation(p.id)
        self.assertAlmostEqual(rep, 51.0, places=1)

    def test_dead_praxan_skipped(self):
        p = StubPraxan()
        p.alive = False
        p._pending_reputation_events = ["crafted_masterwork"]
        self.mgr.update([p], current_time=time.time())
        self.assertEqual(self.mgr.get_reputation(p.id), 50.0)


class TestTierRank(unittest.TestCase):
    """Tests for tier ranking helper."""

    def test_tier_ranks_ordered(self):
        self.assertLess(_tier_rank("outcast"), _tier_rank("marginal"))
        self.assertLess(_tier_rank("marginal"), _tier_rank("established"))
        self.assertLess(_tier_rank("established"), _tier_rank("respected"))
        self.assertLess(_tier_rank("respected"), _tier_rank("luminary"))

    def test_unknown_tier_defaults_to_established(self):
        self.assertEqual(_tier_rank("unknown_tier"), 2)


class TestLeaderElectionIntegration(unittest.TestCase):
    """Tests that reputation affects leader election in Faction.update_leader()."""

    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0
        self.mgr = ReputationManager()

    def tearDown(self):
        clear_cache()

    def test_high_rep_praxan_wins_election(self):
        """When skills are equal, high reputation should win."""
        from systems.society import Faction

        p1 = StubPraxan()
        p2 = StubPraxan()
        # Give equal skills
        p1.skills = {"gathering": {"level": 5, "xp": 0.0}}
        p2.skills = {"gathering": {"level": 5, "xp": 0.0}}
        p1.role = "gatherer"
        p2.role = "gatherer"

        # p1 gets high reputation, p2 gets low
        self.mgr.set_reputation(p1.id, 95.0)
        self.mgr.set_reputation(p2.id, 10.0)

        faction = Faction([p1.id, p2.id])
        faction.update_leader([p1, p2], reputation_manager=self.mgr)

        self.assertEqual(faction.leader_id, p1.id,
                         "High-reputation praxan should win election")

    def test_election_without_reputation_manager(self):
        """Leader election should still work without reputation_manager."""
        from systems.society import Faction

        p1 = StubPraxan()
        p2 = StubPraxan()
        p1.skills = {"gathering": {"level": 5, "xp": 0.0}}
        p2.skills = {"gathering": {"level": 3, "xp": 0.0}}
        p1.role = "gatherer"
        p2.role = "gatherer"

        faction = Faction([p1.id, p2.id])
        faction.update_leader([p1, p2])  # no reputation_manager

        self.assertEqual(faction.leader_id, p1.id,
                         "Skill-based election should still work without rep manager")


if __name__ == "__main__":
    unittest.main()
