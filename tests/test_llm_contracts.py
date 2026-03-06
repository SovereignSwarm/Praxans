"""Tests for all five LLM channel contracts in llm.contracts."""

import unittest

from llm.contracts import (
    council_payload_defaults,
    parse_council_payload,
    faction_intent_defaults,
    parse_faction_intent_payload,
    diplomacy_payload_defaults,
    parse_diplomacy_payload,
    historian_payload_defaults,
    parse_historian_payload,
    memory_summary_defaults,
    parse_memory_summary_payload,
)


class CouncilContractTests(unittest.TestCase):
    def test_no_change_returns_none(self):
        self.assertIsNone(parse_council_payload("No changes"))
        self.assertIsNone(parse_council_payload("Civilization progressing well. Monitoring."))
        self.assertIsNone(parse_council_payload("  no intervention  "))

    def test_empty_returns_defaults(self):
        self.assertEqual(parse_council_payload(""), council_payload_defaults())
        self.assertEqual(parse_council_payload(None), council_payload_defaults())

    def test_malformed_json_returns_defaults(self):
        self.assertEqual(parse_council_payload("{not-json}"), council_payload_defaults())

    def test_valid_json_parses_doctrine(self):
        payload = parse_council_payload('{"doctrine": {"focus": "growth", "stance": "urgent"}}')
        self.assertEqual(payload["doctrine"]["focus"], "growth")
        self.assertEqual(payload["doctrine"]["stance"], "urgent")
        self.assertEqual(payload["doctrine"]["district_priority"], "homestead")

    def test_invalid_enums_clamped(self):
        payload = parse_council_payload('{"doctrine": {"focus": "INVALID", "stance": "magic"}}')
        self.assertEqual(payload["doctrine"]["focus"], "survival")
        self.assertEqual(payload["doctrine"]["stance"], "measured")

    def test_priority_weight_clamped(self):
        payload = parse_council_payload(
            '{"strategic_priorities": [{"key": "food", "weight": 1.5}, {"key": "wood", "weight": -1}]}'
        )
        self.assertEqual(payload["strategic_priorities"][0]["weight"], 1.0)
        self.assertEqual(payload["strategic_priorities"][1]["weight"], 0.0)

    def test_individual_capped_at_2(self):
        payload = parse_council_payload(
            '{"individual": {"0": "a", "1": "b", "2": "c", "3": "d"}}'
        )
        self.assertEqual(len(payload["individual"]), 2)

    def test_oversized_strings_truncated(self):
        long_text = "x" * 500
        payload = parse_council_payload(f'{{"event_framing": "{long_text}"}}')
        self.assertLessEqual(len(payload["event_framing"]), 220)

    def test_team_task_count_clamped(self):
        payload = parse_council_payload(
            '{"team_task": {"faction_id": 0, "task": "build", "count": 99}}'
        )
        self.assertEqual(payload["team_task"]["count"], 5)

    def test_strips_think_tags(self):
        payload = parse_council_payload(
            '<think>internal</think>{"doctrine": {"focus": "territory"}}'
        )
        self.assertEqual(payload["doctrine"]["focus"], "territory")

    def test_strips_markdown_fences(self):
        payload = parse_council_payload(
            '```json\n{"doctrine": {"focus": "culture"}}\n```'
        )
        self.assertEqual(payload["doctrine"]["focus"], "culture")


class FactionIntentContractTests(unittest.TestCase):
    def test_no_change_returns_none(self):
        self.assertIsNone(parse_faction_intent_payload("No changes"))

    def test_empty_returns_defaults(self):
        self.assertEqual(parse_faction_intent_payload(""), faction_intent_defaults())

    def test_valid_json(self):
        payload = parse_faction_intent_payload(
            '{"faction_id": 2, "intent": "migrate", "migration_posture": "commit", '
            '"rivalry_targets": [1], "cooperation_targets": [3], "goal": "move east"}'
        )
        self.assertEqual(payload["faction_id"], 2)
        self.assertEqual(payload["intent"], "migrate")
        self.assertEqual(payload["migration_posture"], "commit")
        self.assertEqual(payload["rivalry_targets"], [1])
        self.assertEqual(payload["goal"], "move east")

    def test_invalid_intent_defaults(self):
        payload = parse_faction_intent_payload('{"intent": "destroy"}')
        self.assertEqual(payload["intent"], "consolidate")


class DiplomacyContractTests(unittest.TestCase):
    def test_no_change_returns_none(self):
        self.assertIsNone(parse_diplomacy_payload("No changes"))

    def test_empty_returns_defaults(self):
        d = parse_diplomacy_payload("")
        self.assertEqual(d["stance_changes"], [])
        self.assertEqual(d["frontier_policy"]["corridor_preference"], "nearest")

    def test_valid_stance_changes(self):
        payload = parse_diplomacy_payload(
            '{"stance_changes": [{"faction_a": 0, "faction_b": 1, "delta": -0.5, "reason": "war"}]}'
        )
        self.assertEqual(len(payload["stance_changes"]), 1)
        self.assertEqual(payload["stance_changes"][0]["delta"], -0.5)

    def test_delta_clamped(self):
        payload = parse_diplomacy_payload(
            '{"stance_changes": [{"faction_a": 0, "faction_b": 1, "delta": 5.0}]}'
        )
        self.assertEqual(payload["stance_changes"][0]["delta"], 1.0)

    def test_frontier_policy_enum_validated(self):
        payload = parse_diplomacy_payload(
            '{"frontier_policy": {"corridor_preference": "INVALID", "settlement_expansion": "nuke"}}'
        )
        self.assertEqual(payload["frontier_policy"]["corridor_preference"], "nearest")
        self.assertEqual(payload["frontier_policy"]["settlement_expansion"], "cautious")


class HistorianContractTests(unittest.TestCase):
    def test_no_change_returns_none(self):
        self.assertIsNone(parse_historian_payload("No changes"))

    def test_valid_json(self):
        payload = parse_historian_payload(
            '{"summary": "A great fire swept the plains.", "moment_type": "disaster", '
            '"why": "Food stores destroyed.", "archive_note": "Fire crisis."}'
        )
        self.assertEqual(payload["moment_type"], "disaster")
        self.assertIn("fire", payload["summary"].lower())

    def test_invalid_moment_type_defaults(self):
        payload = parse_historian_payload('{"moment_type": "magic"}')
        self.assertEqual(payload["moment_type"], "other")

    def test_oversized_summary_truncated(self):
        long_text = "z" * 500
        payload = parse_historian_payload(f'{{"summary": "{long_text}"}}')
        self.assertLessEqual(len(payload["summary"]), 256)


class MemorySummaryContractTests(unittest.TestCase):
    def test_no_change_returns_none(self):
        self.assertIsNone(parse_memory_summary_payload("No changes"))

    def test_valid_json(self):
        payload = parse_memory_summary_payload(
            '{"civilization_digest": "The colony grew steadily.", '
            '"faction_digests": ["F0 expanded east"], "map_digest": "Plains secured."}'
        )
        self.assertEqual(payload["civilization_digest"], "The colony grew steadily.")
        self.assertEqual(len(payload["faction_digests"]), 1)

    def test_oversized_digests_truncated(self):
        big = "a" * 500
        payload = parse_memory_summary_payload(f'{{"civilization_digest": "{big}"}}')
        self.assertLessEqual(len(payload["civilization_digest"]), 300)


if __name__ == "__main__":
    unittest.main()
