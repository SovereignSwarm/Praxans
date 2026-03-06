import unittest

from advisor_contract import advisory_payload_defaults, parse_advisory_payload


class AdvisorContractTests(unittest.TestCase):
    def test_parse_advisory_payload_returns_none_for_no_change_reply(self):
        self.assertIsNone(parse_advisory_payload("Civilization progressing well. Monitoring."))

    def test_parse_advisory_payload_strips_think_and_sanitizes_values(self):
        payload = parse_advisory_payload(
            """
            <think>internal reasoning</think>
            ```json
            {
              "doctrine": {
                "focus": "growth",
                "stance": "urgent",
                "district_priority": "agrarian",
                "crisis_posture": "recover",
                "reasoning": "Push food and shelter."
              },
              "strategic_priorities": [
                {"key": "food_security", "weight": 1.4, "reasoning": "Avoid collapse"},
                {"key": "district_order", "weight": -1, "reasoning": "Should clamp low"}
              ],
              "individual": {"7": "Fortify the farms"},
              "communal": "Keep the colony fed.",
              "team_task": {"faction_id": 1, "task": "Raise a farm ring", "count": 8, "reasoning": "Stabilize food"},
              "conditions": {"low_food": "prioritize farms"},
              "faction_goals": [{"faction_id": 1, "goal": "Expand the agrarian district", "doctrine_key": "growth"}],
              "event_framing": "A tense growth phase."
            }
            ```
            """
        )

        self.assertEqual(payload["doctrine"]["focus"], "growth")
        self.assertEqual(payload["doctrine"]["stance"], "urgent")
        self.assertEqual(payload["strategic_priorities"][0]["weight"], 1.0)
        self.assertEqual(payload["strategic_priorities"][1]["weight"], 0.0)
        self.assertEqual(payload["individual"][7], "Fortify the farms")
        self.assertEqual(payload["team_task"]["count"], 5)
        self.assertEqual(payload["faction_goals"][0]["doctrine_key"], "growth")
        self.assertEqual(payload["event_framing"], "A tense growth phase.")

    def test_parse_advisory_payload_falls_back_to_defaults_on_invalid_json(self):
        self.assertEqual(parse_advisory_payload("{not-json"), advisory_payload_defaults())


if __name__ == "__main__":
    unittest.main()
