"""Tests for autonomous tech research system (systems/tech_research.py)."""

import unittest
import time
import io
from contextlib import redirect_stdout

from systems.tech_research import (
    TechResearchManager,
    DOCTRINE_TECH_PRIORITIES,
    MIN_POINTS_TO_RESEARCH,
    RESEARCH_EVAL_INTERVAL,
    POST_UNLOCK_COOLDOWN,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight stubs that mirror the real advisor/faction/event bus
# ---------------------------------------------------------------------------

class StubGameModifiers:
    def __init__(self):
        self.tech_unlocked = set()
        self.permanent = {}

    def get_modifier(self, name):
        return self.permanent.get(name, 1.0)


class StubAdvisor:
    def __init__(self, research_points=0):
        self.research_points = research_points
        self.points_spent = 0
        self.game_modifiers = StubGameModifiers()
        self.tech_tree = {
            "agriculture_1": {
                "id": "agriculture_1",
                "cost": 100,
                "name": "Efficient Farming",
                "effect": {"farm_production_rate": 1.5},
            },
            "agriculture_2": {
                "id": "agriculture_2",
                "cost": 250,
                "name": "Advanced Irrigation",
                "effect": {"farm_production_rate": 2.0},
                "requires": ["agriculture_1"],
            },
            "medicine_1": {
                "id": "medicine_1",
                "cost": 200,
                "name": "Basic Medicine",
                "effect": {"disease_recovery_rate": 2.0, "health_regen": 1.0},
            },
            "medicine_2": {
                "id": "medicine_2",
                "cost": 400,
                "name": "Advanced Healthcare",
                "effect": {"disease_recovery_rate": 4.0, "health_regen": 2.0},
                "requires": ["medicine_1"],
            },
            "social_1": {
                "id": "social_1",
                "cost": 100,
                "name": "Community Building",
                "effect": {"happiness_base": 1.2, "bond_decay": 0.7},
            },
            "social_2": {
                "id": "social_2",
                "cost": 300,
                "name": "Diplomatic Doctrine",
                "effect": {"happiness_base": 1.4, "bond_decay": 0.5},
                "requires": ["social_1"],
            },
            "exploration_1": {
                "id": "exploration_1",
                "cost": 150,
                "name": "Scout Training",
                "effect": {"praxan_speed": 1.3},
            },
            "industry_1": {
                "id": "industry_1",
                "cost": 200,
                "name": "Workshop Efficiency",
                "effect": {"workshop_bonus": 1.25, "build_speed": 1.2},
            },
            "architecture_1": {
                "id": "architecture_1",
                "cost": 150,
                "name": "Improved Housing",
                "effect": {"house_capacity": 1.5},
            },
        }
        # Stub timeline
        self.observer_timeline = []


class StubFaction:
    def __init__(self, doctrine="growth", member_count=5):
        self.primary_doctrine = doctrine
        self.member_ids = list(range(member_count))


class StubNarrativePanel:
    def __init__(self):
        self.messages = []

    def add_message(self, text, category=""):
        self.messages.append((text, category))


class StubEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTechResearchManager(unittest.TestCase):

    def setUp(self):
        self.mgr = TechResearchManager()
        # Reset timing so first call can evaluate
        self.mgr.last_eval_time = 0.0
        self.mgr.last_unlock_time = 0.0

    # --- Doctrine priority mapping ---

    def test_doctrine_priorities_cover_all_doctrines(self):
        for doctrine in ("growth", "security", "industry", "exploration", "harmony"):
            self.assertIn(doctrine, DOCTRINE_TECH_PRIORITIES)
            self.assertGreater(len(DOCTRINE_TECH_PRIORITIES[doctrine]), 0)

    # --- Dominant doctrine selection ---

    def test_dominant_doctrine_defaults_to_growth(self):
        self.assertEqual(self.mgr._get_dominant_doctrine(None), "growth")
        self.assertEqual(self.mgr._get_dominant_doctrine([]), "growth")

    def test_dominant_doctrine_picks_largest_faction(self):
        factions = [
            StubFaction("security", 3),
            StubFaction("harmony", 10),
            StubFaction("growth", 5),
        ]
        self.assertEqual(self.mgr._get_dominant_doctrine(factions), "harmony")

    # --- Can-research checks ---

    def test_can_research_affordable_no_prereqs(self):
        advisor = StubAdvisor(research_points=200)
        self.assertTrue(self.mgr._can_research(
            "agriculture_1", advisor.tech_tree, advisor.game_modifiers.tech_unlocked, 200
        ))

    def test_cannot_research_too_expensive(self):
        advisor = StubAdvisor(research_points=50)
        self.assertFalse(self.mgr._can_research(
            "agriculture_1", advisor.tech_tree, advisor.game_modifiers.tech_unlocked, 50
        ))

    def test_cannot_research_missing_prereqs(self):
        advisor = StubAdvisor(research_points=500)
        self.assertFalse(self.mgr._can_research(
            "agriculture_2", advisor.tech_tree, advisor.game_modifiers.tech_unlocked, 500
        ))

    def test_can_research_with_prereqs_met(self):
        advisor = StubAdvisor(research_points=500)
        advisor.game_modifiers.tech_unlocked.add("agriculture_1")
        self.assertTrue(self.mgr._can_research(
            "agriculture_2", advisor.tech_tree, advisor.game_modifiers.tech_unlocked, 500
        ))

    def test_cannot_research_already_unlocked(self):
        advisor = StubAdvisor(research_points=500)
        advisor.game_modifiers.tech_unlocked.add("agriculture_1")
        self.assertFalse(self.mgr._can_research(
            "agriculture_1", advisor.tech_tree, advisor.game_modifiers.tech_unlocked, 500
        ))

    # --- Tech selection ---

    def test_select_tech_follows_doctrine_priority(self):
        advisor = StubAdvisor(research_points=200)
        # Growth doctrine: agriculture_1 is first priority
        tech = self.mgr._select_tech("growth", advisor.tech_tree, set(), 200)
        self.assertEqual(tech, "agriculture_1")

    def test_select_tech_security_picks_medicine(self):
        advisor = StubAdvisor(research_points=300)
        tech = self.mgr._select_tech("security", advisor.tech_tree, set(), 300)
        self.assertEqual(tech, "medicine_1")

    def test_select_tech_harmony_picks_social(self):
        advisor = StubAdvisor(research_points=200)
        tech = self.mgr._select_tech("harmony", advisor.tech_tree, set(), 200)
        self.assertEqual(tech, "social_1")

    def test_select_tech_exploration_picks_exploration(self):
        advisor = StubAdvisor(research_points=200)
        tech = self.mgr._select_tech("exploration", advisor.tech_tree, set(), 200)
        self.assertEqual(tech, "exploration_1")

    def test_select_tech_industry_picks_industry(self):
        advisor = StubAdvisor(research_points=300)
        tech = self.mgr._select_tech("industry", advisor.tech_tree, set(), 300)
        self.assertEqual(tech, "industry_1")

    def test_select_tech_skips_unlocked_in_priority(self):
        advisor = StubAdvisor(research_points=300)
        unlocked = {"agriculture_1"}
        # Growth: agriculture_1 done, next is agriculture_2 (cost 250, affordable)
        tech = self.mgr._select_tech("growth", advisor.tech_tree, unlocked, 300)
        self.assertEqual(tech, "agriculture_2")

    def test_select_tech_fallback_to_cheapest(self):
        # Unknown doctrine falls back to cheapest available
        advisor = StubAdvisor(research_points=200)
        tech = self.mgr._select_tech("unknown_doctrine", advisor.tech_tree, set(), 200)
        # Cheapest are agriculture_1 and social_1 at 100
        self.assertIn(tech, ("agriculture_1", "social_1"))

    def test_select_tech_none_when_all_unlocked(self):
        advisor = StubAdvisor(research_points=9999)
        all_techs = set(advisor.tech_tree.keys())
        tech = self.mgr._select_tech("growth", advisor.tech_tree, all_techs, 9999)
        self.assertIsNone(tech)

    # --- Full update cycle ---

    def test_update_unlocks_tech_when_affordable(self):
        advisor = StubAdvisor(research_points=150)
        factions = [StubFaction("growth", 5)]
        panel = StubNarrativePanel()
        bus = StubEventBus()

        result = self.mgr.update(100.0, advisor, factions, bus, panel)

        self.assertEqual(result, "agriculture_1")
        self.assertIn("agriculture_1", advisor.game_modifiers.tech_unlocked)
        self.assertEqual(advisor.research_points, 50)  # 150 - 100
        self.assertEqual(advisor.game_modifiers.permanent["farm_production_rate"], 1.5)
        self.assertTrue(len(panel.messages) > 0)
        self.assertIn("Efficient Farming", panel.messages[0][0])
        self.assertTrue(len(bus.events) > 0)

    def test_update_does_not_write_stdout_on_unlock(self):
        advisor = StubAdvisor(research_points=150)
        factions = [StubFaction("growth", 5)]

        stream = io.StringIO()
        with redirect_stdout(stream):
            result = self.mgr.update(100.0, advisor, factions, None, None)

        self.assertEqual(result, "agriculture_1")
        self.assertEqual(stream.getvalue(), "")


    def test_update_respects_min_points(self):
        advisor = StubAdvisor(research_points=30)  # Below MIN_POINTS_TO_RESEARCH
        result = self.mgr.update(100.0, advisor, [], None, None)
        self.assertIsNone(result)

    def test_update_respects_eval_interval(self):
        advisor = StubAdvisor(research_points=200)
        self.mgr.last_eval_time = 95.0  # Only 5s ago
        result = self.mgr.update(100.0, advisor, [], None, None)
        self.assertIsNone(result)

    def test_update_respects_post_unlock_cooldown(self):
        advisor = StubAdvisor(research_points=200)
        self.mgr.last_unlock_time = 80.0  # Only 20s ago, cooldown is 45s
        result = self.mgr.update(100.0, advisor, [], None, None)
        self.assertIsNone(result)

    def test_update_returns_none_for_none_advisor(self):
        result = self.mgr.update(100.0, None, [], None, None)
        self.assertIsNone(result)

    def test_update_returns_none_when_all_unlocked(self):
        advisor = StubAdvisor(research_points=9999)
        advisor.game_modifiers.tech_unlocked = set(advisor.tech_tree.keys())
        result = self.mgr.update(100.0, advisor, [], None, None)
        self.assertIsNone(result)

    def test_multiple_unlocks_across_time(self):
        advisor = StubAdvisor(research_points=500)
        factions = [StubFaction("growth", 5)]

        # First unlock at t=100
        result1 = self.mgr.update(100.0, advisor, factions, None, None)
        self.assertEqual(result1, "agriculture_1")

        # Too soon at t=130
        result2 = self.mgr.update(130.0, advisor, factions, None, None)
        self.assertIsNone(result2)

        # Ready at t=200 (cooldowns reset)
        result3 = self.mgr.update(200.0, advisor, factions, None, None)
        self.assertEqual(result3, "agriculture_2")
        self.assertEqual(advisor.research_points, 150)  # 500 - 100 - 250

    def test_doctrine_drives_different_tech_paths(self):
        # Growth faction unlocks agriculture
        advisor_g = StubAdvisor(research_points=200)
        mgr_g = TechResearchManager()
        r1 = mgr_g.update(100.0, advisor_g, [StubFaction("growth")], None, None)
        self.assertEqual(r1, "agriculture_1")

        # Security faction unlocks medicine
        advisor_s = StubAdvisor(research_points=300)
        mgr_s = TechResearchManager()
        r2 = mgr_s.update(100.0, advisor_s, [StubFaction("security")], None, None)
        self.assertEqual(r2, "medicine_1")

    # --- Serialization ---

    def test_serialize_roundtrip(self):
        self.mgr.last_eval_time = 42.0
        self.mgr.last_unlock_time = 37.0
        self.mgr.research_log = [
            {"tech_id": "agriculture_1", "name": "Efficient Farming", "time": 40.0, "doctrine": "growth", "cost": 100}
        ]

        data = self.mgr.serialize()
        new_mgr = TechResearchManager()
        new_mgr.restore(data)

        self.assertAlmostEqual(new_mgr.last_eval_time, 42.0)
        self.assertAlmostEqual(new_mgr.last_unlock_time, 37.0)
        self.assertEqual(len(new_mgr.research_log), 1)
        self.assertEqual(new_mgr.research_log[0]["tech_id"], "agriculture_1")

    def test_restore_empty_data(self):
        new_mgr = TechResearchManager()
        new_mgr.restore({})
        self.assertEqual(new_mgr.last_eval_time, 0.0)
        self.assertEqual(new_mgr.research_log, [])


    def test_restore_ignores_malformed_payloads(self):
        new_mgr = TechResearchManager()

        new_mgr.restore(None)
        self.assertEqual(new_mgr.last_eval_time, 0.0)
        self.assertEqual(new_mgr.last_unlock_time, 0.0)
        self.assertEqual(new_mgr.research_log, [])

        new_mgr.restore({
            "last_eval_time": "abc",
            "last_unlock_time": [],
            "research_log": [
                {"tech_id": "agriculture_1", "name": "Efficient Farming"},
                "bad-entry",
            ],
        })
        self.assertEqual(new_mgr.last_eval_time, 0.0)
        self.assertEqual(new_mgr.last_unlock_time, 0.0)
        self.assertEqual(len(new_mgr.research_log), 1)
        self.assertEqual(new_mgr.research_log[0]["tech_id"], "agriculture_1")

        new_mgr.restore({"research_log": {"not": "a-list"}})
        self.assertEqual(new_mgr.research_log, [])

    # --- Research log ---

    def test_unlock_records_log_entry(self):
        advisor = StubAdvisor(research_points=200)
        self.mgr.update(100.0, advisor, [StubFaction("growth")], None, None)

        self.assertEqual(len(self.mgr.research_log), 1)
        entry = self.mgr.research_log[0]
        self.assertEqual(entry["tech_id"], "agriculture_1")
        self.assertEqual(entry["doctrine"], "growth")
        self.assertEqual(entry["cost"], 100)

    # --- GameModifiers integration ---

    def test_permanent_modifiers_applied(self):
        advisor = StubAdvisor(research_points=200)
        self.mgr.update(100.0, advisor, [StubFaction("harmony")], None, None)

        # social_1 effects
        self.assertEqual(advisor.game_modifiers.permanent["happiness_base"], 1.2)
        self.assertEqual(advisor.game_modifiers.permanent["bond_decay"], 0.7)

    # --- Research progress summary ---

    def test_get_research_progress(self):
        advisor = StubAdvisor(research_points=300)
        advisor.game_modifiers.tech_unlocked.add("agriculture_1")

        progress = self.mgr.get_research_progress(advisor)
        self.assertEqual(progress["unlocked"], 1)
        self.assertEqual(progress["total"], 9)
        self.assertEqual(progress["points"], 300)
        self.assertIsNotNone(progress["next_tech"])

    def test_get_research_progress_none_advisor(self):
        self.assertEqual(self.mgr.get_research_progress(None), {})

    # --- EventBus integration ---

    def test_eventbus_publishes_milestone(self):
        advisor = StubAdvisor(research_points=200)
        bus = StubEventBus()
        self.mgr.update(100.0, advisor, [StubFaction("growth")], bus, None)

        self.assertEqual(len(bus.events), 1)
        evt = bus.events[0]
        self.assertEqual(evt.category, "milestone")
        self.assertIn("Efficient Farming", evt.summary)

    # --- Edge cases ---

    def test_prereq_chain_respected(self):
        """Cannot unlock agriculture_2 without agriculture_1, even with enough points."""
        advisor = StubAdvisor(research_points=500)
        # Growth priority: agriculture_1 first
        result = self.mgr._select_tech("growth", advisor.tech_tree, set(), 500)
        self.assertEqual(result, "agriculture_1")

    def test_points_spent_tracked(self):
        advisor = StubAdvisor(research_points=200)
        self.mgr.update(100.0, advisor, [StubFaction("growth")], None, None)
        self.assertEqual(advisor.points_spent, 100)


if __name__ == "__main__":
    unittest.main()
