"""Tests for deterministic LLM interpreters."""

import unittest
from unittest.mock import MagicMock

from llm.interpreters import (
    apply_council_payload,
    apply_faction_intent,
    apply_diplomacy,
    apply_historian,
    apply_memory_summary,
)
from llm.contracts import council_payload_defaults
from llm.memory import LLMMemory


class CouncilInterpreterTests(unittest.TestCase):
    def test_applies_doctrine_and_focus(self):
        payload = council_payload_defaults()
        payload["doctrine"]["focus"] = "territory"
        payload["doctrine"]["stance"] = "expansive"

        state = {
            "council_state": {},
            "current_focus": "resources",
            "json_directives": {},
            "directives": [],
            "advisory_history": [],
            "session_stats": {},
        }

        result = apply_council_payload(payload, state)
        self.assertEqual(state["current_focus"], "territory")
        self.assertEqual(state["council_state"]["doctrine"]["stance"], "expansive")

    def test_applies_individual_directives(self):
        payload = council_payload_defaults()
        payload["individual"] = {0: "gather wood", 1: "build farm"}

        state = {
            "council_state": {},
            "current_focus": "resources",
            "json_directives": {},
            "directives": [],
            "advisory_history": [],
            "session_stats": {},
        }

        result = apply_council_payload(payload, state)
        self.assertEqual(state["json_directives"]["individual"][0], "gather wood")
        self.assertTrue(result["intervened"])

    def test_no_intervention_on_empty_payload(self):
        payload = council_payload_defaults()

        state = {
            "council_state": {},
            "current_focus": "resources",
            "json_directives": {},
            "directives": [],
            "advisory_history": [],
            "session_stats": {},
        }

        result = apply_council_payload(payload, state)
        self.assertFalse(result["intervened"])

    def test_applies_faction_goals(self):
        payload = council_payload_defaults()
        payload["faction_goals"] = [
            {"faction_id": 0, "goal": "secure water", "reasoning": "needed", "doctrine_key": "security"}
        ]

        faction = MagicMock()
        faction.shared_goals = []
        faction.primary_doctrine = "security"

        fm = MagicMock()
        fm.factions = {0: faction}
        fm.get_faction.return_value = faction

        state = {
            "council_state": {},
            "current_focus": "resources",
            "json_directives": {},
            "directives": [],
            "advisory_history": [],
            "session_stats": {},
        }

        apply_council_payload(payload, state, faction_manager_proxy=fm)
        faction.assign_shared_goal.assert_called_once()


class FactionIntentInterpreterTests(unittest.TestCase):
    def test_sets_shared_goal(self):
        faction = MagicMock()
        faction.primary_doctrine = "exploration"
        faction.id = 0

        payload = {
            "faction_id": 0,
            "intent": "expand",
            "migration_posture": "probe",
            "rivalry_targets": [1],
            "cooperation_targets": [],
            "goal": "push east",
            "reasoning": "resources there",
        }

        result = apply_faction_intent(payload, faction)
        faction.assign_shared_goal.assert_called_once()
        self.assertEqual(result["intent"], "expand")
        self.assertTrue(result["applied_goal"])

    def test_no_goal_no_assignment(self):
        faction = MagicMock()
        faction.primary_doctrine = "security"

        payload = {
            "faction_id": 0,
            "intent": "consolidate",
            "migration_posture": "stay",
            "rivalry_targets": [],
            "cooperation_targets": [],
            "goal": "",
            "reasoning": "",
        }

        result = apply_faction_intent(payload, faction)
        faction.assign_shared_goal.assert_not_called()
        self.assertFalse(result["applied_goal"])


class DiplomacyInterpreterTests(unittest.TestCase):
    def test_hostile_adds_rivals(self):
        fa = MagicMock()
        fa.rival_faction_ids = set()
        fb = MagicMock()
        fb.rival_faction_ids = set()

        fm = MagicMock()
        fm.get_faction.side_effect = lambda fid: {0: fa, 1: fb}.get(fid)

        payload = {
            "stance_changes": [
                {"faction_a": 0, "faction_b": 1, "delta": -0.5, "reason": "war"}
            ],
            "frontier_policy": {},
        }

        result = apply_diplomacy(payload, fm)
        self.assertEqual(result["applied_stance_changes"], 1)
        self.assertIn(1, fa.rival_faction_ids)
        self.assertIn(0, fb.rival_faction_ids)

    def test_cooperative_removes_rivals(self):
        fa = MagicMock()
        fa.rival_faction_ids = {1}
        fb = MagicMock()
        fb.rival_faction_ids = {0}

        fm = MagicMock()
        fm.get_faction.side_effect = lambda fid: {0: fa, 1: fb}.get(fid)

        payload = {
            "stance_changes": [
                {"faction_a": 0, "faction_b": 1, "delta": 0.5, "reason": "peace"}
            ],
            "frontier_policy": {},
        }

        result = apply_diplomacy(payload, fm)
        self.assertEqual(result["applied_stance_changes"], 1)
        self.assertNotIn(1, fa.rival_faction_ids)


class HistorianInterpreterTests(unittest.TestCase):
    def test_adds_to_narrative(self):
        panel = MagicMock()
        memory = LLMMemory()

        payload = {
            "summary": "A great fire swept the colony.",
            "moment_type": "disaster",
            "why": "Dry season",
            "archive_note": "Fire crisis",
        }

        result = apply_historian(payload, narrative_panel=panel, memory=memory)
        panel.add_message.assert_called_once_with("A great fire swept the colony.", "Chronicle")
        self.assertTrue(result["summary_added"])
        self.assertGreater(len(memory.civilization.entries), 0)

    def test_empty_summary_no_side_effects(self):
        panel = MagicMock()

        result = apply_historian({"summary": "", "moment_type": "other", "why": "", "archive_note": ""}, narrative_panel=panel)
        panel.add_message.assert_not_called()
        self.assertFalse(result["summary_added"])


class MemorySummaryInterpreterTests(unittest.TestCase):
    def test_applies_digests(self):
        memory = LLMMemory()
        payload = {
            "civilization_digest": "Colony growing steadily.",
            "faction_digests": ["F0 expanded east"],
            "map_digest": "Plains secured.",
        }

        result = apply_memory_summary(payload, memory)
        self.assertTrue(result["civ_updated"])
        self.assertTrue(result["map_updated"])
        self.assertIn("growing", memory.civilization.digest_text())
        self.assertIn("secured", memory.map.digest_text())


if __name__ == "__main__":
    unittest.main()
