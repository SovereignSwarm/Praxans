"""Tests for LLM memory layers (serialize/deserialize round-trips)."""

import unittest

from llm.memory import (
    CivilizationMemory,
    FactionMemory,
    MapMemory,
    LLMMemory,
)


class CivilizationMemoryTests(unittest.TestCase):
    def test_record_and_recent_text(self):
        mem = CivilizationMemory()
        mem.record("doctrine", "Switched to growth", 10.0)
        mem.record("crisis", "Food shortage detected", 20.0)
        text = mem.recent_text()
        self.assertIn("growth", text)
        self.assertIn("shortage", text)

    def test_bounded_entries(self):
        mem = CivilizationMemory()
        for i in range(30):
            mem.record("test", f"event {i}", float(i))
        self.assertLessEqual(len(mem.entries), CivilizationMemory.MAX_ENTRIES)

    def test_digest(self):
        mem = CivilizationMemory()
        mem.set_digest("Colony is growing steadily.")
        self.assertIn("growing", mem.digest_text())

    def test_serialize_roundtrip(self):
        mem = CivilizationMemory()
        mem.record("doctrine", "Growth phase", 10.0)
        mem.set_digest("Test digest")

        data = mem.to_dict()
        restored = CivilizationMemory.from_dict(data)
        self.assertEqual(len(restored.entries), 1)
        self.assertEqual(len(restored.digests), 1)
        self.assertIn("Growth", restored.recent_text())


class FactionMemoryTests(unittest.TestCase):
    def test_record_per_faction(self):
        mem = FactionMemory()
        mem.record(0, "schism", "Faction 0 split", 10.0)
        mem.record(1, "migration", "Faction 1 moved east", 15.0)
        self.assertIn("split", mem.recent_text(0))
        self.assertIn("east", mem.recent_text(1))
        self.assertEqual(mem.recent_text(99), "(no faction events)")

    def test_bounded_per_faction(self):
        mem = FactionMemory()
        for i in range(20):
            mem.record(0, "test", f"event {i}")
        self.assertLessEqual(
            len(mem._entries.get(0, [])),
            FactionMemory.MAX_ENTRIES_PER_FACTION,
        )

    def test_serialize_roundtrip(self):
        mem = FactionMemory()
        mem.record(0, "test", "Faction zero event", 10.0)
        mem.set_digest(0, "F0 survived a schism")

        data = mem.to_dict()
        restored = FactionMemory.from_dict(data)
        self.assertIn("zero", restored.recent_text(0))
        self.assertIn("schism", restored.digest_text(0))

    def test_all_faction_ids(self):
        mem = FactionMemory()
        mem.record(2, "test", "event")
        mem.set_digest(5, "digest")
        ids = mem.all_faction_ids()
        self.assertIn(2, ids)
        self.assertIn(5, ids)


class MapMemoryTests(unittest.TestCase):
    def test_record_and_text(self):
        mem = MapMemory()
        mem.record("landmark", "Sacred grove discovered", 10.0)
        self.assertIn("grove", mem.recent_text())

    def test_serialize_roundtrip(self):
        mem = MapMemory()
        mem.record("hazard", "Swamp corridor dangerous", 10.0)
        mem.set_digest("Northern frontier stabilized")

        data = mem.to_dict()
        restored = MapMemory.from_dict(data)
        self.assertIn("Swamp", restored.recent_text())
        self.assertIn("stabilized", restored.digest_text())


class LLMMemoryTests(unittest.TestCase):
    def test_aggregate_serialize_roundtrip(self):
        mem = LLMMemory()
        mem.civilization.record("test", "civ event", 1.0)
        mem.factions.record(0, "test", "faction event", 2.0)
        mem.map.record("test", "map event", 3.0)

        data = mem.to_dict()
        restored = LLMMemory.from_dict(data)
        self.assertIn("civ", restored.civilization.recent_text())
        self.assertIn("faction", restored.factions.recent_text(0))
        self.assertIn("map", restored.map.recent_text())

    def test_from_dict_with_none(self):
        restored = LLMMemory.from_dict(None)
        self.assertEqual(restored.civilization.recent_text(), "(no recent events)")

    def test_from_dict_with_empty(self):
        restored = LLMMemory.from_dict({})
        self.assertEqual(len(restored.civilization.entries), 0)


if __name__ == "__main__":
    unittest.main()
