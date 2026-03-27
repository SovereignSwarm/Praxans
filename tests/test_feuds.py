"""Tests for the Feuds & Grudges system (systems/feuds.py)."""

import unittest
import time

from systems.feuds import (
    FeudsManager,
    get_grudge_def,
    get_all_grudge_defs,
    get_stage_for_weight,
    clear_cache,
    _pair_key,
    _stage_severity,
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
        self.health = 100.0
        self.happiness = 70.0
        self.needs = {"hunger": 80.0, "energy": 80.0, "social": 50.0}
        self.bonds = {}
        self.opinions = {}
        self.moodlets = []
        self.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        self.episodic_memory = StubMemory()
        self.traits = []
        self.relationships = {}
        self._pending_reputation_events = []
        self.name = f"Praxan_{self.id}"
        self.life_stage = "adult"

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
            "metadata": metadata or {},
        })


class StubFaction:
    def __init__(self, faction_id=0, member_ids=None, leader_id=None):
        self.id = faction_id
        self.member_ids = list(member_ids or [])
        self.leader_id = leader_id
        self.cohesion = 60.0
        self.primary_doctrine = "growth"


class StubFactionManager:
    def __init__(self, factions=None):
        self.factions = factions or {}


class StubDiplomacyManager:
    def __init__(self):
        self._standings = {}

    def adjust_standing(self, fid_a, fid_b, delta):
        key = _pair_key(fid_a, fid_b)
        old = self._standings.get(key, 0)
        self._standings[key] = old + delta

    def get_standing(self, fid_a, fid_b):
        return self._standings.get(_pair_key(fid_a, fid_b), 0)


class StubEventBus:
    def __init__(self):
        self.events = []
        self._subs = {}

    def subscribe(self, category, handler):
        self._subs.setdefault(category, []).append(handler)

    def publish(self, event):
        self.events.append(event)


class StubEvent:
    def __init__(self, category="personal", data=None, metadata=None):
        self.category = category
        self.data = data or {}
        self.metadata = metadata or data or {}


# ---------------------------------------------------------------------------
# Setup helper
# ---------------------------------------------------------------------------

def _load_defs():
    """Ensure feuds defs are loaded from defs/core/feuds.json."""
    from systems.def_database import DefDatabase
    DefDatabase.clear()
    DefDatabase.initialize("defs")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDefLoading(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()

    def test_grudge_defs_loaded(self):
        defs = get_all_grudge_defs()
        self.assertGreater(len(defs), 0)
        self.assertIn("insult_grudge", defs)
        self.assertIn("kin_slayer_grudge", defs)

    def test_grudge_def_has_required_fields(self):
        gdef = get_grudge_def("insult_grudge")
        self.assertIsNotNone(gdef)
        self.assertIn("weight", gdef)
        self.assertIn("decay_rate", gdef)
        self.assertIn("personality_weights", gdef)

    def test_stage_defs_loaded(self):
        # simmering at 15, hostile at 35, vendetta at 60, blood_feud at 90
        self.assertIsNone(get_stage_for_weight(10))
        stage = get_stage_for_weight(15)
        self.assertIsNotNone(stage)
        self.assertEqual(stage["id"], "simmering")

    def test_stage_escalation_thresholds(self):
        self.assertEqual(get_stage_for_weight(20)["id"], "simmering")
        self.assertEqual(get_stage_for_weight(35)["id"], "hostile")
        self.assertEqual(get_stage_for_weight(60)["id"], "vendetta")
        self.assertEqual(get_stage_for_weight(90)["id"], "blood_feud")

    def test_stage_severity_ordering(self):
        self.assertLess(_stage_severity("simmering"), _stage_severity("hostile"))
        self.assertLess(_stage_severity("hostile"), _stage_severity("vendetta"))
        self.assertLess(_stage_severity("vendetta"), _stage_severity("blood_feud"))


class TestPairKey(unittest.TestCase):
    def test_canonical_order(self):
        self.assertEqual(_pair_key(5, 3), (3, 5))
        self.assertEqual(_pair_key(3, 5), (3, 5))
        self.assertEqual(_pair_key(2, 2), (2, 2))


class TestGrudgeRecording(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()

    def test_record_grudge_basic(self):
        weight = self.mgr.record_grudge(1, 2, "insult_grudge")
        self.assertGreater(weight, 0)
        self.assertGreater(self.mgr.get_total_weight(1, 2), 0)

    def test_record_grudge_self_rejected(self):
        weight = self.mgr.record_grudge(1, 1, "insult_grudge")
        self.assertEqual(weight, 0)

    def test_record_unknown_grudge(self):
        weight = self.mgr.record_grudge(1, 2, "nonexistent_grudge")
        self.assertEqual(weight, 0)

    def test_grudges_are_directed(self):
        self.mgr.record_grudge(1, 2, "insult_grudge")
        self.assertGreater(self.mgr.get_total_weight(1, 2), 0)
        self.assertEqual(self.mgr.get_total_weight(2, 1), 0)

    def test_grudges_accumulate(self):
        self.mgr.record_grudge(1, 2, "insult_grudge")
        w1 = self.mgr.get_total_weight(1, 2)
        self.mgr.record_grudge(1, 2, "argument_grudge")
        w2 = self.mgr.get_total_weight(1, 2)
        self.assertGreater(w2, w1)

    def test_multiplier_scales_weight(self):
        self.mgr.record_grudge(1, 2, "insult_grudge", multiplier=2.0)
        gdef = get_grudge_def("insult_grudge")
        expected = gdef["weight"] * 2.0
        self.assertAlmostEqual(self.mgr.get_total_weight(1, 2), expected)


class TestFeudStages(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()

    def test_no_feud_below_threshold(self):
        self.mgr.record_grudge(1, 2, "rival_grudge")  # weight 8
        self.assertIsNone(self.mgr.get_feud_stage_id(1, 2))
        self.assertFalse(self.mgr.has_feud_with(1, 2))

    def test_simmering_stage(self):
        self.mgr.record_grudge(1, 2, "insult_grudge")  # weight 15
        self.assertEqual(self.mgr.get_feud_stage_id(1, 2), "simmering")

    def test_hostile_stage(self):
        # insult(15) + argument(10) + argument(10) = 35
        self.mgr.record_grudge(1, 2, "insult_grudge")
        self.mgr.record_grudge(1, 2, "argument_grudge")
        self.mgr.record_grudge(1, 2, "argument_grudge")
        self.assertEqual(self.mgr.get_feud_stage_id(1, 2), "hostile")

    def test_vendetta_stage(self):
        # heirloom_theft(30) + betrayal(25) + rival(8) = 63
        self.mgr.record_grudge(1, 2, "heirloom_theft_grudge")
        self.mgr.record_grudge(1, 2, "betrayal_grudge")
        self.mgr.record_grudge(1, 2, "rival_grudge")
        self.assertEqual(self.mgr.get_feud_stage_id(1, 2), "vendetta")

    def test_blood_feud_stage(self):
        # kin_slayer(40) + heirloom_theft(30) + betrayal(25) = 95
        self.mgr.record_grudge(1, 2, "kin_slayer_grudge")
        self.mgr.record_grudge(1, 2, "heirloom_theft_grudge")
        self.mgr.record_grudge(1, 2, "betrayal_grudge")
        self.assertEqual(self.mgr.get_feud_stage_id(1, 2), "blood_feud")


class TestSocialAvoidance(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        self.mgr = FeudsManager()

    def test_no_avoidance_without_feud(self):
        self.assertFalse(self.mgr.should_avoid_socially(1, 2))

    def test_avoidance_with_simmering_feud(self):
        self.mgr.record_grudge(1, 2, "insult_grudge")
        self.assertTrue(self.mgr.should_avoid_socially(1, 2))

    def test_avoidance_bidirectional(self):
        """If A has feud with B, B also avoids A."""
        self.mgr.record_grudge(1, 2, "insult_grudge")
        self.assertTrue(self.mgr.should_avoid_socially(2, 1))


class TestInsultChanceBoost(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        self.mgr = FeudsManager()

    def test_no_boost_without_feud(self):
        self.assertEqual(self.mgr.get_insult_chance_boost(1, 2), 0.0)

    def test_boost_at_hostile_stage(self):
        # 35 weight = hostile → insult_chance 0.3
        self.mgr.record_grudge(1, 2, "insult_grudge")
        self.mgr.record_grudge(1, 2, "argument_grudge")
        self.mgr.record_grudge(1, 2, "argument_grudge")
        boost = self.mgr.get_insult_chance_boost(1, 2)
        self.assertGreater(boost, 0)


class TestRemovePraxan(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        self.mgr = FeudsManager()

    def test_remove_cleans_all_grudges(self):
        self.mgr.record_grudge(1, 2, "insult_grudge")
        self.mgr.record_grudge(3, 1, "argument_grudge")
        self.mgr.remove_praxan(1)
        self.assertEqual(self.mgr.get_total_weight(1, 2), 0)
        self.assertEqual(self.mgr.get_total_weight(3, 1), 0)


class TestUpdateEffects(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()
        self.p1 = StubPraxan(faction_id=0)
        self.p2 = StubPraxan(faction_id=0)
        self.bus = StubEventBus()
        self.faction = StubFaction(faction_id=0, member_ids=[self.p1.id, self.p2.id])
        self.fm = StubFactionManager({0: self.faction})
        self.dm = StubDiplomacyManager()

    def test_moodlet_applied_on_update(self):
        self.mgr.record_grudge(self.p1.id, self.p2.id, "insult_grudge")
        now = time.time()
        self.mgr.update(
            [self.p1, self.p2], self.fm, self.dm, self.bus, now,
        )
        moodlet_names = [m["name"] for m in self.p1.moodlets]
        self.assertIn("FeudSimmering", moodlet_names)

    def test_opinion_drift_on_update(self):
        self.p1.opinions[self.p2.id] = 0
        self.mgr.record_grudge(self.p1.id, self.p2.id, "insult_grudge")
        now = time.time()
        self.mgr.update(
            [self.p1, self.p2], self.fm, self.dm, self.bus, now,
        )
        self.assertLess(self.p1.opinions[self.p2.id], 0)

    def test_cohesion_penalty_same_faction(self):
        # Vendetta stage has cohesion_penalty
        self.mgr.record_grudge(self.p1.id, self.p2.id, "heirloom_theft_grudge")
        self.mgr.record_grudge(self.p1.id, self.p2.id, "betrayal_grudge")
        self.mgr.record_grudge(self.p1.id, self.p2.id, "rival_grudge")
        old_cohesion = self.faction.cohesion
        now = time.time()
        self.mgr.update(
            [self.p1, self.p2], self.fm, self.dm, self.bus, now,
        )
        self.assertLess(self.faction.cohesion, old_cohesion)

    def test_diplomacy_penalty_cross_faction(self):
        self.p2.faction_id = 1
        faction2 = StubFaction(faction_id=1, member_ids=[self.p2.id])
        self.fm.factions[1] = faction2
        # Vendetta stage has diplomacy_penalty
        self.mgr.record_grudge(self.p1.id, self.p2.id, "heirloom_theft_grudge")
        self.mgr.record_grudge(self.p1.id, self.p2.id, "betrayal_grudge")
        self.mgr.record_grudge(self.p1.id, self.p2.id, "rival_grudge")
        now = time.time()
        self.mgr.update(
            [self.p1, self.p2], self.fm, self.dm, self.bus, now,
        )
        standing = self.dm.get_standing(0, 1)
        self.assertLess(standing, 0)

    def test_stage_transition_publishes_event(self):
        self.mgr.record_grudge(self.p1.id, self.p2.id, "insult_grudge")
        now = time.time()
        self.mgr.update(
            [self.p1, self.p2], self.fm, self.dm, self.bus, now,
        )
        self.assertGreater(len(self.bus.events), 0)

    def test_stage_transition_records_memory(self):
        self.mgr.record_grudge(self.p1.id, self.p2.id, "insult_grudge")
        now = time.time()
        self.mgr.update(
            [self.p1, self.p2], self.fm, self.dm, self.bus, now,
        )
        categories = [e["category"] for e in self.p1.episodic_memory.entries]
        self.assertIn("feud_escalated", categories)


class TestDecay(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()
        self.p1 = StubPraxan(faction_id=0)
        self.p2 = StubPraxan(faction_id=0)

    def test_grudge_decays_over_time(self):
        self.mgr.record_grudge(self.p1.id, self.p2.id, "argument_grudge")
        w_before = self.mgr.get_total_weight(self.p1.id, self.p2.id)
        # Force decay by setting last_decay_time far in the past
        self.mgr._last_decay_time = 0.0
        self.mgr._last_eval_time = time.time()  # skip eval
        alive_map = {self.p1.id: self.p1, self.p2.id: self.p2}
        self.mgr._apply_decay(alive_map)
        w_after = self.mgr.get_total_weight(self.p1.id, self.p2.id)
        self.assertLess(w_after, w_before)

    def test_high_sociability_faster_decay(self):
        self.p1.personality["sociability"] = 1.0
        self.p1.personality["diligence"] = 0.0
        self.mgr.record_grudge(self.p1.id, self.p2.id, "insult_grudge")

        p3 = StubPraxan()
        p3.personality["sociability"] = 0.0
        p3.personality["diligence"] = 1.0
        self.mgr.record_grudge(p3.id, self.p2.id, "insult_grudge")

        alive_map = {self.p1.id: self.p1, self.p2.id: self.p2, p3.id: p3}
        self.mgr._apply_decay(alive_map)

        w_sociable = self.mgr.get_total_weight(self.p1.id, self.p2.id)
        w_diligent = self.mgr.get_total_weight(p3.id, self.p2.id)
        self.assertLess(w_sociable, w_diligent)

    def test_near_zero_grudges_pruned(self):
        self.mgr.record_grudge(self.p1.id, self.p2.id, "rival_grudge")  # weight 8
        alive_map = {self.p1.id: self.p1, self.p2.id: self.p2}
        # Decay many times until pruned
        for _ in range(50):
            self.mgr._apply_decay(alive_map)
        self.assertEqual(self.mgr.get_total_weight(self.p1.id, self.p2.id), 0)


class TestDeadPraxanCleanup(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()

    def test_dead_praxans_cleaned_on_update(self):
        p1 = StubPraxan()
        p2 = StubPraxan()
        self.mgr.record_grudge(p1.id, p2.id, "insult_grudge")
        p1.alive = False
        now = time.time()
        self.mgr.update([p1, p2], current_time=now)
        self.assertEqual(self.mgr.get_active_feud_count(), 0)


class TestEventBusAutoRecording(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()
        self.bus = StubEventBus()
        self.mgr.attach_event_bus(self.bus)

    def test_insult_triggers_grudge(self):
        event = StubEvent(data={"interaction": "insult", "initiator": 1, "target": 2})
        self.mgr._on_personal_event(event)
        # Target (2) should hold grudge against initiator (1)
        self.assertGreater(self.mgr.get_total_weight(2, 1), 0)

    def test_argument_triggers_mutual_grudge(self):
        event = StubEvent(data={"interaction": "argument", "initiator": 1, "target": 2})
        self.mgr._on_personal_event(event)
        self.assertGreater(self.mgr.get_total_weight(1, 2), 0)
        self.assertGreater(self.mgr.get_total_weight(2, 1), 0)

    def test_kin_killed_triggers_grudge(self):
        event = StubEvent(data={
            "sub_type": "combat_kill",
            "killer_id": 5,
            "victim_id": 3,
            "victim_kin_ids": [1, 2],
        })
        self.mgr._on_warfare_event(event)
        self.assertGreater(self.mgr.get_total_weight(1, 5), 0)
        self.assertGreater(self.mgr.get_total_weight(2, 5), 0)

    def test_heirloom_looted_triggers_grudge(self):
        event = StubEvent(data={
            "sub_type": "heirloom_looted",
            "owner_id": 1,
            "looter_id": 3,
        })
        self.mgr._on_warfare_event(event)
        self.assertGreater(self.mgr.get_total_weight(1, 3), 0)

    def test_defection_triggers_betrayal(self):
        event = StubEvent(data={
            "sub_type": "defected",
            "praxan_id": 5,
            "affected_friend_ids": [1, 2],
            "affected_family_ids": [3],
        })
        self.mgr._on_migration_event(event)
        self.assertGreater(self.mgr.get_total_weight(1, 5), 0)
        self.assertGreater(self.mgr.get_total_weight(3, 5), 0)


class TestQueryHelpers(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()

    def test_get_all_feuds_for(self):
        self.mgr.record_grudge(1, 2, "insult_grudge")
        self.mgr.record_grudge(1, 3, "betrayal_grudge")
        feuds = self.mgr.get_all_feuds_for(1)
        target_ids = [f["target_id"] for f in feuds]
        self.assertIn(2, target_ids)
        self.assertIn(3, target_ids)

    def test_get_feuding_pairs(self):
        self.mgr.record_grudge(1, 2, "insult_grudge")
        pairs = self.mgr.get_feuding_pairs()
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][:2], (1, 2))

    def test_get_faction_feuds(self):
        p1 = StubPraxan(faction_id=0)
        p2 = StubPraxan(faction_id=0)
        p3 = StubPraxan(faction_id=1)
        self.mgr.record_grudge(p1.id, p2.id, "insult_grudge")
        self.mgr.record_grudge(p1.id, p3.id, "betrayal_grudge")
        faction_feuds = self.mgr.get_faction_feuds(0, [p1, p2, p3])
        internal = [f for f in faction_feuds if f["is_internal"]]
        external = [f for f in faction_feuds if not f["is_internal"]]
        self.assertEqual(len(internal), 1)
        self.assertEqual(len(external), 1)


class TestConfrontation(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0

    def test_confrontation_applies_damage(self):
        mgr = FeudsManager()
        p1 = StubPraxan()
        p2 = StubPraxan()
        mgr._trigger_confrontation(p1, p2, time.time())
        total_hp = p1.health + p2.health
        self.assertLess(total_hp, 200)

    def test_confrontation_records_memory(self):
        mgr = FeudsManager()
        p1 = StubPraxan()
        p2 = StubPraxan()
        mgr._trigger_confrontation(p1, p2, time.time())
        all_categories = (
            [e["category"] for e in p1.episodic_memory.entries]
            + [e["category"] for e in p2.episodic_memory.entries]
        )
        self.assertIn("feud_confrontation", all_categories)

    def test_confrontation_queues_reputation_events(self):
        mgr = FeudsManager()
        p1 = StubPraxan()
        p2 = StubPraxan()
        mgr._trigger_confrontation(p1, p2, time.time())
        all_events = p1._pending_reputation_events + p2._pending_reputation_events
        self.assertTrue(
            "feud_confrontation_won" in all_events and "feud_confrontation_lost" in all_events
        )


class TestFeudResolution(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()
        self.p1 = StubPraxan()
        self.p2 = StubPraxan()
        self.bus = StubEventBus()

    def test_feud_resolution_on_decay(self):
        self.mgr.record_grudge(self.p1.id, self.p2.id, "rival_grudge")  # w=8, below simmering
        # First eval to register
        self.mgr.update([self.p1, self.p2], event_bus=self.bus, current_time=time.time())
        # No stage should be set since 8 < 15
        self.assertIsNone(self.mgr.get_feud_stage_id(self.p1.id, self.p2.id))


class TestSerialization(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()

    def test_serialize_and_restore(self):
        self.mgr.record_grudge(1, 2, "insult_grudge")
        self.mgr.record_grudge(1, 2, "argument_grudge")
        self.mgr.record_grudge(3, 4, "kin_slayer_grudge")
        now = time.time()
        data = self.mgr.serialize(current_time=now)

        mgr2 = FeudsManager()
        mgr2.restore(data, current_time=now)

        self.assertAlmostEqual(
            mgr2.get_total_weight(1, 2),
            self.mgr.get_total_weight(1, 2),
            places=1,
        )
        self.assertAlmostEqual(
            mgr2.get_total_weight(3, 4),
            self.mgr.get_total_weight(3, 4),
            places=1,
        )

    def test_restore_preserves_stages(self):
        self.mgr.record_grudge(1, 2, "insult_grudge")
        self.mgr._stages[(1, 2)] = "simmering"
        data = self.mgr.serialize()

        mgr2 = FeudsManager()
        mgr2.restore(data)
        self.assertEqual(mgr2._stages.get((1, 2)), "simmering")

    def test_serialize_empty(self):
        data = self.mgr.serialize()
        self.assertEqual(data["grudges"], {})

    def test_restore_malformed_keys_ignored(self):
        mgr2 = FeudsManager()
        mgr2.restore({
            "grudges": {"bad_key": [{"grudge_id": "x", "weight": 5, "age_seconds": 0}]},
            "stages": {},
        })
        self.assertEqual(mgr2.get_active_feud_count(), 0)


class TestAllyRecruitment(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()

    def test_ally_recruitment_adds_rival_grudge(self):
        p1 = StubPraxan()
        p2 = StubPraxan()
        friend = StubPraxan()
        p1.relationships = {friend.id: ["friend"]}
        # Use a high multiplier seed to make recruitment deterministic
        import random
        random.seed(42)
        # Try multiple times since recruitment is probabilistic
        for _ in range(20):
            self.mgr._try_recruit_allies(p1, p2, "hostile", time.time())
        # Friend should have picked up at least one rival grudge
        self.assertGreater(self.mgr.get_total_weight(friend.id, p2.id), 0)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        clear_cache()
        _load_defs()
        StubPraxan._next_id = 0
        self.mgr = FeudsManager()

    def test_update_with_empty_praxans(self):
        """Update with no praxans should not crash."""
        self.mgr.update([], current_time=time.time())

    def test_update_with_no_grudges(self):
        p1 = StubPraxan()
        self.mgr.update([p1], current_time=time.time())

    def test_multiple_grudge_types_same_pair(self):
        self.mgr.record_grudge(1, 2, "insult_grudge")
        self.mgr.record_grudge(1, 2, "argument_grudge")
        self.mgr.record_grudge(1, 2, "betrayal_grudge")
        total = self.mgr.get_total_weight(1, 2)
        expected = 15 + 10 + 25
        self.assertEqual(total, expected)

    def test_get_all_feuds_for_nonexistent(self):
        feuds = self.mgr.get_all_feuds_for(999)
        self.assertEqual(feuds, [])


if __name__ == "__main__":
    unittest.main()
