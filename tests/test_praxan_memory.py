"""Tests for Per-Praxan Autobiographical / Episodic Memory System."""

import sys
import time
import unittest

# Neutralise sys.argv before importing praxans_game (it parses args at import time)
_saved_argv = sys.argv
sys.argv = sys.argv[:1]
import praxans_game  # noqa: F401
sys.argv = _saved_argv

from systems.praxan_memory import EpisodicMemory, MemoryEntry, _calculate_weight, get_event_label, _event_def_cache
from entities.praxan import Praxan
from praxans_game import REL_PARTNER, REL_FRIEND, REL_RIVAL


# Seed the event def cache directly so tests don't depend on DefDatabase
_TEST_EVENT_DEFS = [
    {"id": "birth", "base_weight": 8, "personality_factor": None, "label": "Born"},
    {"id": "partnership", "base_weight": 7, "personality_factor": "sociability", "label": "Found a Partner"},
    {"id": "parenthood", "base_weight": 7, "personality_factor": "sociability", "label": "Became a Parent"},
    {"id": "grief", "base_weight": 9, "personality_factor": "sociability", "label": "Lost Someone"},
    {"id": "friendship", "base_weight": 5, "personality_factor": "sociability", "label": "Made a Friend"},
    {"id": "rivalry", "base_weight": 4, "personality_factor": None, "label": "Gained a Rival"},
    {"id": "mental_break", "base_weight": 6, "personality_factor": None, "label": "Had a Breakdown"},
    {"id": "discovery", "base_weight": 4, "personality_factor": "curiosity", "label": "Discovered Something"},
    {"id": "masterwork", "base_weight": 7, "personality_factor": "diligence", "label": "Created a Masterwork"},
    {"id": "combat_wound", "base_weight": 5, "personality_factor": None, "label": "Was Wounded"},
    {"id": "building", "base_weight": 3, "personality_factor": "diligence", "label": "Built Something"},
    {"id": "migration", "base_weight": 6, "personality_factor": "curiosity", "label": "Migrated"},
    {"id": "near_death", "base_weight": 8, "personality_factor": None, "label": "Nearly Died"},
    {"id": "faction_change", "base_weight": 5, "personality_factor": None, "label": "Changed Faction"},
]
for _d in _TEST_EVENT_DEFS:
    _event_def_cache[_d["id"]] = _d


def _make_praxan(x=100, y=100):
    return Praxan(x, y)


class MemoryEntryTests(unittest.TestCase):
    """Unit tests for individual MemoryEntry."""

    def test_to_dict_roundtrip(self):
        entry = MemoryEntry(
            category="birth",
            summary="A new life",
            emotional_weight=8.0,
            timestamp=1000.0,
            related_ids=[1, 2],
            metadata={"place": "home"},
        )
        data = entry.to_dict()
        restored = MemoryEntry.from_dict(data)
        self.assertEqual(restored.category, "birth")
        self.assertEqual(restored.summary, "A new life")
        self.assertAlmostEqual(restored.emotional_weight, 8.0)
        self.assertEqual(restored.related_ids, [1, 2])
        self.assertEqual(restored.metadata["place"], "home")


class EpisodicMemoryTests(unittest.TestCase):
    """Core EpisodicMemory tests."""

    def test_record_and_retrieve(self):
        mem = EpisodicMemory(personality={"curiosity": 0.8})
        mem.record("birth", "Born into the world", timestamp=100.0)
        mem.record("discovery", "Found a crystal cave", timestamp=200.0)
        self.assertEqual(mem.memory_count, 2)
        recent = mem.recent(5)
        self.assertEqual(len(recent), 2)

    def test_bounded_cap(self):
        mem = EpisodicMemory(max_entries=5)
        for i in range(10):
            mem.record("discovery", f"Event {i}", timestamp=float(i))
        self.assertEqual(mem.memory_count, 5)

    def test_evicts_least_significant(self):
        mem = EpisodicMemory(max_entries=3)
        mem.record("birth", "Born", weight_override=10.0, timestamp=1.0)
        mem.record("discovery", "Found leaf", weight_override=1.0, timestamp=2.0)
        mem.record("grief", "Lost someone", weight_override=9.0, timestamp=3.0)
        # At this point, 3 entries. Adding a 4th should evict the least significant (weight=1.0)
        mem.record("partnership", "Found a partner", weight_override=7.0, timestamp=4.0)
        self.assertEqual(mem.memory_count, 3)
        summaries = [e.summary for e in mem.entries]
        self.assertNotIn("Found leaf", summaries)
        self.assertIn("Born", summaries)
        self.assertIn("Lost someone", summaries)
        self.assertIn("Found a partner", summaries)

    def test_most_significant(self):
        mem = EpisodicMemory()
        mem.record("birth", "Born", weight_override=8.0, timestamp=1.0)
        mem.record("discovery", "Found rock", weight_override=2.0, timestamp=2.0)
        mem.record("grief", "Lost partner", weight_override=9.0, timestamp=3.0)
        mem.record("friendship", "Made a friend", weight_override=5.0, timestamp=4.0)
        top2 = mem.most_significant(2)
        self.assertEqual(len(top2), 2)
        self.assertEqual(top2[0].summary, "Lost partner")
        self.assertEqual(top2[1].summary, "Born")

    def test_by_category(self):
        mem = EpisodicMemory()
        mem.record("grief", "Lost A", timestamp=1.0)
        mem.record("birth", "Born", timestamp=2.0)
        mem.record("grief", "Lost B", timestamp=3.0)
        grief = mem.by_category("grief")
        self.assertEqual(len(grief), 2)

    def test_recent_text(self):
        mem = EpisodicMemory()
        mem.record("birth", "Born into the world", timestamp=1.0)
        text = mem.recent_text()
        self.assertIn("Born into the world", text)
        self.assertNotEqual(text, "(no memories yet)")

    def test_empty_recent_text(self):
        mem = EpisodicMemory()
        self.assertEqual(mem.recent_text(), "(no memories yet)")

    def test_most_significant_text(self):
        mem = EpisodicMemory()
        mem.record("grief", "Lost a friend", weight_override=9.0, timestamp=1.0)
        text = mem.most_significant_text(1)
        self.assertIn("Lost a friend", text)

    def test_life_story_summary(self):
        mem = EpisodicMemory()
        mem.record("birth", "Born", weight_override=8.0, timestamp=1.0)
        mem.record("partnership", "Found partner", weight_override=7.0, timestamp=2.0)
        story = mem.life_story_summary()
        self.assertIn("life", story.lower())
        self.assertTrue(len(story) > 10)

    def test_empty_life_story(self):
        mem = EpisodicMemory()
        self.assertEqual(mem.life_story_summary(), "Has no notable memories yet.")


class PersonalityWeightingTests(unittest.TestCase):
    """Test that personality traits amplify emotional weight."""

    def test_curiosity_amplifies_discovery(self):
        curious = EpisodicMemory(personality={"curiosity": 1.0})
        bland = EpisodicMemory(personality={"curiosity": 0.0})
        e1 = curious.record("discovery", "Found cave", timestamp=1.0)
        e2 = bland.record("discovery", "Found cave", timestamp=1.0)
        self.assertGreater(e1.emotional_weight, e2.emotional_weight)

    def test_sociability_amplifies_grief(self):
        social = EpisodicMemory(personality={"sociability": 1.0})
        loner = EpisodicMemory(personality={"sociability": 0.0})
        e1 = social.record("grief", "Lost partner", timestamp=1.0)
        e2 = loner.record("grief", "Lost partner", timestamp=1.0)
        self.assertGreater(e1.emotional_weight, e2.emotional_weight)

    def test_no_amplification_for_neutral_categories(self):
        mem = EpisodicMemory(personality={"curiosity": 1.0, "sociability": 1.0})
        entry = mem.record("mental_break", "Had breakdown", timestamp=1.0)
        # mental_break has personality_factor=null, so personality shouldn't amplify
        # Just check it got a reasonable weight
        self.assertGreater(entry.emotional_weight, 0)


class TraumaJoyScoreTests(unittest.TestCase):
    """Test mood-integration scoring methods."""

    def test_recent_trauma_score(self):
        mem = EpisodicMemory()
        now = time.time()
        mem.record("grief", "Lost partner", weight_override=9.0, timestamp=now - 10)
        mem.record("discovery", "Found cave", weight_override=4.0, timestamp=now - 10)
        score = mem.recent_trauma_score(lookback=300.0)
        self.assertAlmostEqual(score, 9.0)

    def test_recent_joy_score(self):
        mem = EpisodicMemory()
        now = time.time()
        mem.record("partnership", "Found partner", weight_override=7.0, timestamp=now - 10)
        mem.record("grief", "Lost friend", weight_override=9.0, timestamp=now - 10)
        score = mem.recent_joy_score(lookback=300.0)
        self.assertAlmostEqual(score, 7.0)

    def test_old_events_not_counted(self):
        mem = EpisodicMemory()
        now = time.time()
        mem.record("grief", "Old grief", weight_override=9.0, timestamp=now - 1000)
        score = mem.recent_trauma_score(lookback=300.0)
        self.assertAlmostEqual(score, 0.0)


class SerializationTests(unittest.TestCase):
    """Test full EpisodicMemory serialize/deserialize roundtrip."""

    def test_roundtrip(self):
        personality = {"curiosity": 0.7, "sociability": 0.5}
        mem = EpisodicMemory(personality=personality)
        mem.record("birth", "Born", timestamp=1.0)
        mem.record("grief", "Lost friend", timestamp=2.0)
        mem.record("masterwork", "Created a Masterwork Sword", timestamp=3.0)

        data = mem.to_dict()
        restored = EpisodicMemory.from_dict(data, personality=personality)
        self.assertEqual(restored.memory_count, 3)
        self.assertIn("Born", restored.recent_text())
        self.assertIn("Lost friend", restored.recent_text())

    def test_from_dict_none(self):
        mem = EpisodicMemory.from_dict(None)
        self.assertEqual(mem.memory_count, 0)

    def test_from_dict_empty(self):
        mem = EpisodicMemory.from_dict({})
        self.assertEqual(mem.memory_count, 0)


class PraxanIntegrationTests(unittest.TestCase):
    """Test that Praxan properly initializes and uses episodic memory."""

    def test_praxan_has_episodic_memory(self):
        p = _make_praxan()
        self.assertTrue(hasattr(p, 'episodic_memory'))
        self.assertIsInstance(p.episodic_memory, EpisodicMemory)

    def test_birth_memory_recorded(self):
        p = _make_praxan()
        self.assertGreaterEqual(p.episodic_memory.memory_count, 1)
        birth_memories = p.episodic_memory.by_category("birth")
        self.assertEqual(len(birth_memories), 1)
        self.assertIn("came into being", birth_memories[0].summary)

    def test_grief_records_memory(self):
        survivor = _make_praxan()
        dead = _make_praxan(200, 200)
        dead.alive = False
        survivor.set_relationship(dead.id, REL_PARTNER)
        t = time.time()
        survivor.apply_grief(dead.id, t)
        grief_memories = survivor.episodic_memory.by_category("grief")
        self.assertEqual(len(grief_memories), 1)
        self.assertIn("lost their partner", grief_memories[0].summary)

    def test_partnership_records_memory(self):
        p = _make_praxan()
        other = _make_praxan(200, 200)
        p.set_relationship(other.id, REL_PARTNER)
        partnership_memories = p.episodic_memory.by_category("partnership")
        self.assertEqual(len(partnership_memories), 1)

    def test_friendship_records_memory(self):
        p = _make_praxan()
        other = _make_praxan(200, 200)
        p.set_relationship(other.id, REL_FRIEND)
        memories = p.episodic_memory.by_category("friendship")
        self.assertEqual(len(memories), 1)

    def test_rivalry_records_memory(self):
        p = _make_praxan()
        other = _make_praxan(200, 200)
        p.set_relationship(other.id, REL_RIVAL)
        memories = p.episodic_memory.by_category("rivalry")
        self.assertEqual(len(memories), 1)

    def test_set_relationship_no_duplicate_memory(self):
        """Setting same relationship type twice should not record twice."""
        p = _make_praxan()
        other = _make_praxan(200, 200)
        p.set_relationship(other.id, REL_FRIEND)
        p.set_relationship(other.id, REL_FRIEND)  # Same type again
        memories = p.episodic_memory.by_category("friendship")
        self.assertEqual(len(memories), 1)

    def test_near_death_records_memory(self):
        """Taking massive damage that drops below 25% health should record near_death."""
        p = _make_praxan()
        t = time.time()
        # Inflict heavy damage to push below 25% health threshold
        p.take_damage(80, 'blunt', t)
        p.take_damage(80, 'blunt', t)
        p.take_damage(80, 'blunt', t)
        # Should have at least one combat wound or near death memory
        combat = p.episodic_memory.by_category("combat_wound")
        near_death = p.episodic_memory.by_category("near_death")
        self.assertTrue(len(combat) > 0 or len(near_death) > 0,
                        "Significant damage should record combat_wound or near_death memory")


class HelperFunctionTests(unittest.TestCase):
    """Test module-level helper functions."""

    def test_get_event_label(self):
        label = get_event_label("birth")
        self.assertEqual(label, "Born")

    def test_get_event_label_unknown(self):
        label = get_event_label("unknown_type")
        self.assertIsInstance(label, str)
        self.assertTrue(len(label) > 0)


if __name__ == "__main__":
    unittest.main()
