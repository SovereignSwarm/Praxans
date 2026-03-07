"""Tests for the Diplomacy & Relations System."""
import unittest
import time

from systems.diplomacy import (
    DiplomacyManager,
    DiplomaticRelation,
    standing_to_tier,
    TIER_ALLIED,
    TIER_FRIENDLY,
    TIER_NEUTRAL,
    TIER_TENSE,
    TIER_HOSTILE,
    TREATY_TRADE,
    TREATY_NAP,
    TREATY_ALLIANCE,
    TREATY_STANDING_REQ,
)


class TestStandingTiers(unittest.TestCase):
    """Test standing-to-tier mapping."""

    def test_allied(self):
        self.assertEqual(standing_to_tier(61), TIER_ALLIED)
        self.assertEqual(standing_to_tier(100), TIER_ALLIED)

    def test_friendly(self):
        self.assertEqual(standing_to_tier(21), TIER_FRIENDLY)
        self.assertEqual(standing_to_tier(60), TIER_FRIENDLY)

    def test_neutral(self):
        self.assertEqual(standing_to_tier(0), TIER_NEUTRAL)
        self.assertEqual(standing_to_tier(20), TIER_NEUTRAL)
        self.assertEqual(standing_to_tier(-20), TIER_NEUTRAL)

    def test_tense(self):
        self.assertEqual(standing_to_tier(-21), TIER_TENSE)
        self.assertEqual(standing_to_tier(-60), TIER_TENSE)

    def test_hostile(self):
        self.assertEqual(standing_to_tier(-61), TIER_HOSTILE)
        self.assertEqual(standing_to_tier(-100), TIER_HOSTILE)


class TestDiplomaticRelation(unittest.TestCase):
    """Test individual DiplomaticRelation behavior."""

    def test_initial_state(self):
        rel = DiplomaticRelation(0, 1)
        self.assertEqual(rel.standing, 0.0)
        self.assertEqual(rel.tier, TIER_NEUTRAL)
        self.assertEqual(rel.treaties, [])
        self.assertEqual(rel.trade_count, 0)

    def test_canonical_key_order(self):
        """Faction IDs should be stored in ascending order."""
        rel = DiplomaticRelation(5, 2)
        self.assertEqual(rel.faction_a_id, 2)
        self.assertEqual(rel.faction_b_id, 5)

    def test_shift_standing_clamped(self):
        rel = DiplomaticRelation(0, 1)
        rel.shift_standing(200)
        self.assertEqual(rel.standing, 100.0)
        rel.shift_standing(-300)
        self.assertEqual(rel.standing, -100.0)

    def test_shift_standing_returns_tier_change(self):
        rel = DiplomaticRelation(0, 1, initial_standing=19.0)
        # 19 -> 22 crosses from neutral to friendly
        changed = rel.shift_standing(3.0, time.time())
        self.assertTrue(changed)
        self.assertEqual(rel.tier, TIER_FRIENDLY)

    def test_shift_standing_no_tier_change(self):
        rel = DiplomaticRelation(0, 1, initial_standing=5.0)
        changed = rel.shift_standing(2.0, time.time())
        self.assertFalse(changed)

    def test_add_treaty_success(self):
        rel = DiplomaticRelation(0, 1, initial_standing=10.0)
        result = rel.add_treaty(TREATY_TRADE, time.time())
        self.assertTrue(result)
        self.assertTrue(rel.has_treaty(TREATY_TRADE))

    def test_add_treaty_duplicate_fails(self):
        rel = DiplomaticRelation(0, 1, initial_standing=10.0)
        rel.add_treaty(TREATY_TRADE, time.time())
        result = rel.add_treaty(TREATY_TRADE, time.time())
        self.assertFalse(result)

    def test_add_treaty_standing_too_low(self):
        rel = DiplomaticRelation(0, 1, initial_standing=-50.0)
        result = rel.add_treaty(TREATY_TRADE, time.time())
        self.assertFalse(result)

    def test_alliance_requires_high_standing(self):
        rel = DiplomaticRelation(0, 1, initial_standing=30.0)
        result = rel.add_treaty(TREATY_ALLIANCE, time.time())
        self.assertFalse(result)

        rel2 = DiplomaticRelation(0, 1, initial_standing=50.0)
        result2 = rel2.add_treaty(TREATY_ALLIANCE, time.time())
        self.assertTrue(result2)

    def test_expire_treaties(self):
        rel = DiplomaticRelation(0, 1, initial_standing=10.0)
        now = time.time()
        rel.add_treaty(TREATY_TRADE, now - 200)  # Already expired
        expired = rel.expire_treaties(now)
        self.assertIn(TREATY_TRADE, expired)
        self.assertFalse(rel.has_treaty(TREATY_TRADE))

    def test_can_trade(self):
        rel_neutral = DiplomaticRelation(0, 1, initial_standing=0.0)
        self.assertTrue(rel_neutral.can_trade())

        rel_tense = DiplomaticRelation(0, 1, initial_standing=-30.0)
        self.assertFalse(rel_tense.can_trade())

        rel_friendly = DiplomaticRelation(0, 1, initial_standing=50.0)
        self.assertTrue(rel_friendly.can_trade())

    def test_record_trade(self):
        rel = DiplomaticRelation(0, 1)
        rel.record_trade()
        rel.record_trade()
        self.assertEqual(rel.trade_count, 2)

    def test_record_incident_capped(self):
        rel = DiplomaticRelation(0, 1)
        now = time.time()
        for i in range(15):
            rel.record_incident(f"test_{i}", f"Test {i}", -5.0, now + i)
        self.assertEqual(len(rel.incident_log), 10)

    def test_serialize_roundtrip(self):
        rel = DiplomaticRelation(2, 5, initial_standing=42.0)
        rel.record_trade()
        rel.add_treaty(TREATY_TRADE, time.time())
        data = rel.serialize()
        self.assertEqual(data["faction_a_id"], 2)
        self.assertEqual(data["faction_b_id"], 5)
        self.assertEqual(data["standing"], 42.0)
        self.assertEqual(data["tier"], TIER_FRIENDLY)
        self.assertEqual(data["trade_count"], 1)


class TestDiplomacyManager(unittest.TestCase):
    """Test DiplomacyManager operations."""

    def test_get_relation_creates_new(self):
        dm = DiplomacyManager()
        rel = dm.get_relation(0, 1)
        self.assertIsInstance(rel, DiplomaticRelation)
        self.assertEqual(rel.standing, 0.0)

    def test_get_relation_canonical_key(self):
        dm = DiplomacyManager()
        rel_a = dm.get_relation(3, 1)
        rel_b = dm.get_relation(1, 3)
        self.assertIs(rel_a, rel_b)

    def test_set_initial_standing(self):
        dm = DiplomacyManager()
        dm.set_initial_standing(0, 1, 75.0)
        rel = dm.get_relation(0, 1)
        self.assertEqual(rel.standing, 75.0)

    def test_register_schism(self):
        dm = DiplomacyManager()
        dm.register_schism(0, 1, time.time())
        rel = dm.get_relation(0, 1)
        self.assertEqual(rel.standing, DiplomacyManager.SCHISM_INITIAL_STANDING)
        self.assertEqual(rel.tier, TIER_TENSE)

    def test_register_trade_improves_standing(self):
        dm = DiplomacyManager()
        dm.register_trade(0, 1, time.time())
        rel = dm.get_relation(0, 1)
        self.assertGreater(rel.standing, 0.0)

    def test_cleanup_dissolved(self):
        dm = DiplomacyManager()
        dm.get_relation(0, 1)
        dm.get_relation(0, 2)
        dm.get_relation(1, 2)
        # Faction 2 dissolved
        dm._cleanup_dissolved([0, 1])
        self.assertEqual(len(dm.relations), 1)
        self.assertIn((0, 1), dm.relations)

    def test_serialize_deserialize(self):
        dm = DiplomacyManager()
        dm.set_initial_standing(0, 1, 50.0)
        dm.register_trade(0, 1, time.time())
        dm.get_relation(0, 1).add_treaty(TREATY_TRADE, time.time())
        data = dm.serialize()

        dm2 = DiplomacyManager()
        dm2.deserialize(data)
        rel = dm2.get_relation(0, 1)
        self.assertAlmostEqual(rel.standing, 51.5, places=1)
        self.assertEqual(rel.trade_count, 1)
        self.assertTrue(rel.has_treaty(TREATY_TRADE))

    def test_faction_relations_summary(self):
        dm = DiplomacyManager()
        dm.set_initial_standing(0, 1, 30.0)
        dm.set_initial_standing(0, 2, -40.0)
        summaries = dm.get_faction_relations_summary(0)
        self.assertEqual(len(summaries), 2)
        # Should be sorted by standing descending
        self.assertEqual(summaries[0]["faction_id"], 1)
        self.assertEqual(summaries[1]["faction_id"], 2)

    def test_get_all_relations_for_llm(self):
        dm = DiplomacyManager()
        dm.set_initial_standing(0, 1, 30.0)
        lines = dm.get_all_relations_for_llm()
        self.assertEqual(len(lines), 1)
        self.assertIn("Friendly", lines[0])

    def test_ideology_affinity_same_ideology(self):
        dm = DiplomacyManager()

        class MockFaction:
            def __init__(self, ideology):
                self.ideology = ideology

        fa = MockFaction({"growth": 0.8, "security": 0.2, "industry": 0.5,
                          "exploration": 0.3, "harmony": 0.7})
        fb = MockFaction({"growth": 0.8, "security": 0.2, "industry": 0.5,
                          "exploration": 0.3, "harmony": 0.7})
        affinity = dm._compute_ideology_affinity(fa, fb)
        self.assertAlmostEqual(affinity, 1.0, places=1)

    def test_ideology_affinity_opposite(self):
        dm = DiplomacyManager()

        class MockFaction:
            def __init__(self, ideology):
                self.ideology = ideology

        fa = MockFaction({"growth": 1.0, "security": 1.0, "industry": 1.0,
                          "exploration": 1.0, "harmony": 1.0})
        fb = MockFaction({"growth": 0.0, "security": 0.0, "industry": 0.0,
                          "exploration": 0.0, "harmony": 0.0})
        affinity = dm._compute_ideology_affinity(fa, fb)
        self.assertAlmostEqual(affinity, -1.0, places=1)


if __name__ == "__main__":
    unittest.main()
