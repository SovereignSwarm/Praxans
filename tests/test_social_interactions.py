"""Tests for the Social Interaction Engine.

Verifies:
- Precondition checking (opinion, bond, life stage, food, mood, skill gap)
- Personality-weighted selection
- Outcome application (moodlets, bonds, opinions, social need, XP, memory)
- Cooldown enforcement
- attempt_interaction high-level API
- _should_socialize and _pick_social_target helper methods
"""
from __future__ import annotations

import os
import sys
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pygame
pygame.init()
pygame.display.set_mode((1, 1))

from systems.def_database import DefDatabase
DefDatabase.initialize("defs")

# praxans_game parses sys.argv at import time; neutralise unittest's args.
_saved_argv = sys.argv
sys.argv = sys.argv[:1]
import praxans_game  # noqa: F401 — needed so wildcard import in praxan.py works
sys.argv = _saved_argv

from entities.praxan import Praxan
from systems.social_interactions import (
    check_preconditions,
    select_interaction,
    execute_interaction,
    attempt_interaction,
    _has_skill_gap,
    _personality_score,
    clear_cache,
    _load_interactions,
)


def _make_praxan(x=100, y=100, **overrides):
    """Create a test praxan with sensible defaults."""
    p = Praxan(x, y)
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


class TestPreconditions(unittest.TestCase):
    """Test check_preconditions for various interaction types."""

    def setUp(self):
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        clear_cache()
        self.interactions = {d["id"]: d for d in _load_interactions()}

    def test_chat_passes_for_adults(self):
        a = _make_praxan()
        a.age = 100  # adult
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 0
        self.assertTrue(check_preconditions(self.interactions["chat"], a, b))

    def test_chat_fails_for_infants(self):
        a = _make_praxan()
        a.age = 5  # infant
        b = _make_praxan(x=110)
        b.age = 100
        self.assertFalse(check_preconditions(self.interactions["chat"], a, b))

    def test_deep_conversation_requires_bond(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 20
        a.bonds[b.id] = 10  # Below min_bond of 30
        self.assertFalse(check_preconditions(self.interactions["deep_conversation"], a, b))

        a.bonds[b.id] = 40  # Above min_bond
        self.assertTrue(check_preconditions(self.interactions["deep_conversation"], a, b))

    def test_argument_requires_low_opinion(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 10  # Too high for argument (max_opinion=-15)
        self.assertFalse(check_preconditions(self.interactions["argument"], a, b))

        a.opinions[b.id] = -20  # Below max_opinion
        self.assertTrue(check_preconditions(self.interactions["argument"], a, b))

    def test_insult_requires_very_low_opinion(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = -10  # max_opinion is -30
        self.assertFalse(check_preconditions(self.interactions["insult"], a, b))

        a.opinions[b.id] = -40
        self.assertTrue(check_preconditions(self.interactions["insult"], a, b))

    def test_comfort_requires_target_low_mood(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 10
        a.bonds[b.id] = 20
        b.happiness = 60  # Too happy to comfort
        self.assertFalse(check_preconditions(self.interactions["comfort"], a, b))

        b.happiness = 25  # Low enough
        self.assertTrue(check_preconditions(self.interactions["comfort"], a, b))

    def test_share_meal_requires_food(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 10
        a.needs["hunger"] = 30  # Not enough food
        self.assertFalse(check_preconditions(self.interactions["share_meal"], a, b))

        a.needs["hunger"] = 70  # Has food
        self.assertTrue(check_preconditions(self.interactions["share_meal"], a, b))

    def test_teach_requires_skill_gap(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 10
        # Both at level 1 — no gap
        self.assertFalse(check_preconditions(self.interactions["teach"], a, b))

        # Create a skill gap
        a.skills["building"]["level"] = 4
        b.skills["building"]["level"] = 1
        self.assertTrue(check_preconditions(self.interactions["teach"], a, b))


class TestSkillGap(unittest.TestCase):
    """Test _has_skill_gap helper."""

    def test_no_gap(self):
        a = _make_praxan()
        b = _make_praxan(x=110)
        self.assertFalse(_has_skill_gap(a, b))

    def test_gap_of_two(self):
        a = _make_praxan()
        b = _make_praxan(x=110)
        a.skills["crafting"]["level"] = 4
        b.skills["crafting"]["level"] = 2
        self.assertTrue(_has_skill_gap(a, b))

    def test_gap_of_one_not_enough(self):
        a = _make_praxan()
        b = _make_praxan(x=110)
        a.skills["crafting"]["level"] = 3
        b.skills["crafting"]["level"] = 2
        self.assertFalse(_has_skill_gap(a, b))


class TestSelection(unittest.TestCase):
    """Test select_interaction weighted selection."""

    def setUp(self):
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        clear_cache()

    def test_returns_none_when_no_valid_interactions(self):
        a = _make_praxan()
        a.age = 5  # infant — excluded from all interactions
        b = _make_praxan(x=110)
        b.age = 100
        result = select_interaction(a, b)
        self.assertIsNone(result)

    def test_returns_an_interaction_for_valid_pair(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 0
        result = select_interaction(a, b)
        self.assertIsNotNone(result)
        self.assertIn("id", result)

    def test_cooldown_blocks_interaction(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 0

        # Block all interactions with recent cooldowns
        cooldowns = {}
        interactions = _load_interactions()
        now = time.time()
        for idef in interactions:
            cooldowns[idef["id"]] = now

        result = select_interaction(a, b, cooldowns=cooldowns)
        self.assertIsNone(result)


class TestExecution(unittest.TestCase):
    """Test execute_interaction outcome application."""

    def setUp(self):
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        clear_cache()
        self.interactions = {d["id"]: d for d in _load_interactions()}

    def test_chat_applies_social_need(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.needs["social"] = 30
        b.needs["social"] = 30

        result = execute_interaction(a, b, self.interactions["chat"])

        self.assertGreater(a.needs["social"], 30)
        self.assertGreater(b.needs["social"], 30)
        self.assertEqual(result["interaction"], "chat")

    def test_chat_applies_moodlet(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100

        execute_interaction(a, b, self.interactions["chat"])

        moodlet_names = [m["name"] for m in a.moodlets]
        self.assertIn("HadChat", moodlet_names)

    def test_argument_applies_negative_moodlet(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100

        execute_interaction(a, b, self.interactions["argument"])

        moodlet_names = [m["name"] for m in a.moodlets]
        self.assertIn("HadArgument", moodlet_names)
        # Target gets the same moodlet name
        target_moodlets = [m["name"] for m in b.moodlets]
        self.assertIn("HadArgument", target_moodlets)

    def test_insult_gives_target_negative_moodlet(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100

        execute_interaction(a, b, self.interactions["insult"])

        target_moodlets = [m["name"] for m in b.moodlets]
        self.assertIn("WasInsulted", target_moodlets)

    def test_bonds_change(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.bonds[b.id] = 10
        b.bonds[a.id] = 10

        execute_interaction(a, b, self.interactions["chat"])

        # Chat has bond_change +2 for both sides
        self.assertGreater(a.bonds[b.id], 10)
        self.assertGreater(b.bonds[a.id], 10)

    def test_opinion_changes(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 0
        b.opinions[a.id] = 0

        execute_interaction(a, b, self.interactions["chat"])

        # Chat opinion_change is [1, 3] — should increase
        self.assertGreater(a.opinions[b.id], 0)
        self.assertGreater(b.opinions[a.id], 0)

    def test_argument_decreases_opinion(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 0
        b.opinions[a.id] = 0

        execute_interaction(a, b, self.interactions["argument"])

        # Argument opinion_change is [-8, -3] — should decrease
        self.assertLess(a.opinions[b.id], 0)

    def test_deep_conversation_records_memory(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100

        execute_interaction(a, b, self.interactions["deep_conversation"])

        # deep_conversation has memory_event = "friendship"
        categories = [e.category for e in a.episodic_memory.entries]
        self.assertIn("friendship", categories)
        categories_b = [e.category for e in b.episodic_memory.entries]
        self.assertIn("friendship", categories_b)

    def test_share_meal_changes_hunger(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.needs["hunger"] = 80
        b.needs["hunger"] = 40

        execute_interaction(a, b, self.interactions["share_meal"])

        # Initiator loses 10 hunger, target gains 20
        self.assertLess(a.needs["hunger"], 80)
        self.assertGreater(b.needs["hunger"], 40)

    def test_teach_gives_target_xp(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        # Snapshot target's total XP before
        total_xp_before = sum(
            s["xp"] for s in b.skills.values() if isinstance(s, dict)
        )

        execute_interaction(a, b, self.interactions["teach"])

        total_xp_after = sum(
            s["xp"] for s in b.skills.values() if isinstance(s, dict)
        )
        self.assertGreater(total_xp_after, total_xp_before)

    def test_comfort_gives_target_positive_moodlet(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100

        execute_interaction(a, b, self.interactions["comfort"])

        target_moodlets = {m["name"]: m["value"] for m in b.moodlets}
        self.assertIn("WasComforted", target_moodlets)
        self.assertGreater(target_moodlets["WasComforted"], 0)


class TestAttemptInteraction(unittest.TestCase):
    """Test the high-level attempt_interaction API."""

    def setUp(self):
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        clear_cache()

    def test_attempt_returns_result_on_success(self):
        a = _make_praxan()
        a.age = 100
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = 0
        cooldowns = {}
        result = attempt_interaction(a, b, cooldowns=cooldowns)
        self.assertIsNotNone(result)
        self.assertIn("interaction", result)
        # Cooldown should have been recorded
        self.assertGreater(len(cooldowns), 0)

    def test_attempt_returns_none_for_invalid_pair(self):
        a = _make_praxan()
        a.age = 5  # infant
        b = _make_praxan(x=110)
        b.age = 100
        result = attempt_interaction(a, b)
        self.assertIsNone(result)


class TestPersonalityScore(unittest.TestCase):
    """Regression tests for _personality_score with string-list traits."""

    def setUp(self):
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        clear_cache()
        self.interactions = {d["id"]: d for d in _load_interactions()}

    def test_trait_boost_with_string_traits_no_crash(self):
        """_personality_score must not crash when praxan.traits is a list of strings.

        Regression: previously tried t.get('name', '') on each trait string,
        raising AttributeError: 'str' object has no attribute 'get'.
        """
        a = _make_praxan()
        a.age = 100
        a.traits = ["Volatile", "Optimist"]  # strings, as stored in production
        insult = self.interactions["insult"]
        # Must not raise; should return a positive float
        score = _personality_score(insult, a)
        self.assertIsInstance(score, float)
        self.assertGreater(score, 0.0)

    def test_trait_boost_matched_increases_score(self):
        """A praxan with the 'Volatile' trait should score higher on 'insult'."""
        a_volatile = _make_praxan()
        a_volatile.age = 100
        a_volatile.traits = ["Volatile"]
        a_volatile.personality["sociability"] = 0.5  # neutral for baseline

        a_plain = _make_praxan()
        a_plain.age = 100
        a_plain.traits = []

        insult = self.interactions["insult"]
        score_volatile = _personality_score(insult, a_volatile)
        score_plain = _personality_score(insult, a_plain)
        self.assertGreater(score_volatile, score_plain)

    def test_no_trait_boost_interaction_unaffected(self):
        """Interactions without trait_boost should score the same regardless of traits."""
        a = _make_praxan()
        a.age = 100
        a.traits = ["Optimist"]
        b = _make_praxan()
        b.age = 100
        b.traits = []
        chat = self.interactions["chat"]
        # Both should produce valid scores without crashing
        self.assertGreater(_personality_score(chat, a), 0.0)
        self.assertGreater(_personality_score(chat, b), 0.0)

    def test_insult_select_with_volatile_praxan_no_crash(self):
        """select_interaction must succeed for a Volatile praxan with low opinion."""
        a = _make_praxan()
        a.age = 100
        a.traits = ["Volatile"]
        b = _make_praxan(x=110)
        b.age = 100
        a.opinions[b.id] = -50  # enables insult (max_opinion=-30)
        # Must not raise AttributeError
        result = select_interaction(a, b)
        # Result could be insult or another valid interaction — just must not crash
        self.assertIsNotNone(result)


class TestShouldSocialize(unittest.TestCase):
    """Test the _should_socialize helper on Praxan."""

    def test_low_social_need_triggers(self):
        p = _make_praxan()
        p.needs["social"] = 30
        self.assertTrue(p._should_socialize())

    def test_high_social_need_and_low_sociability_does_not_trigger(self):
        p = _make_praxan()
        p.needs["social"] = 90
        p.personality["sociability"] = 0.1
        # With high social need and low sociability, should almost never trigger
        # Test 20 times — should mostly be False
        results = [p._should_socialize() for _ in range(20)]
        # At least 15 out of 20 should be False (sociability*0.15 = 0.015 = 1.5% chance)
        self.assertGreater(results.count(False), 14)


class TestPickSocialTarget(unittest.TestCase):
    """Test _pick_social_target helper."""

    def test_picks_nearby_praxan(self):
        a = _make_praxan(x=100, y=100)
        b = _make_praxan(x=120, y=100)
        b.alive = True
        result = a._pick_social_target([a, b])
        self.assertEqual(result.id, b.id)

    def test_excludes_dead_praxans(self):
        a = _make_praxan(x=100, y=100)
        b = _make_praxan(x=120, y=100)
        b.alive = False
        result = a._pick_social_target([a, b])
        self.assertIsNone(result)

    def test_excludes_distant_praxans(self):
        a = _make_praxan(x=100, y=100)
        b = _make_praxan(x=500, y=500)  # > 200 px away
        b.alive = True
        result = a._pick_social_target([a, b])
        self.assertIsNone(result)

    def test_excludes_downed_praxans(self):
        a = _make_praxan(x=100, y=100)
        b = _make_praxan(x=120, y=100)
        b.alive = True
        b.downed = True
        result = a._pick_social_target([a, b])
        self.assertIsNone(result)

    def test_prefers_bonded_praxans(self):
        a = _make_praxan(x=100, y=100)
        b = _make_praxan(x=120, y=100)
        c = _make_praxan(x=120, y=110)
        b.alive = True
        c.alive = True
        a.bonds[b.id] = 80  # Strong bond
        a.bonds[c.id] = 0

        # Run 50 trials — bonded praxan should be picked most of the time
        picks = {"b": 0, "c": 0}
        for _ in range(50):
            result = a._pick_social_target([a, b, c])
            if result and result.id == b.id:
                picks["b"] += 1
            elif result and result.id == c.id:
                picks["c"] += 1
        self.assertGreater(picks["b"], picks["c"])


if __name__ == "__main__":
    unittest.main()
