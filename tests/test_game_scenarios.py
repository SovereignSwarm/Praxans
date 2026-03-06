import unittest

from game_scenarios import (
    DEFAULT_SCENARIO_ID,
    SCENARIO_PRESETS,
    format_scenario_help,
    get_scenario_profile,
    list_scenario_ids,
)


class GameScenarioTests(unittest.TestCase):
    def test_default_scenario_exists_in_registry(self):
        self.assertIn(DEFAULT_SCENARIO_ID, SCENARIO_PRESETS)
        self.assertIn(DEFAULT_SCENARIO_ID, list_scenario_ids())

    def test_get_scenario_profile_returns_independent_copy(self):
        profile = get_scenario_profile("high_mutation")
        profile["starting_resources"]["food"] = 999
        profile["initial_challenges"].append({"type": "test"})

        fresh_profile = get_scenario_profile("high_mutation")
        self.assertEqual(fresh_profile["starting_resources"]["food"], 6)
        self.assertEqual(fresh_profile["initial_challenges"], [])

    def test_format_scenario_help_lists_named_presets(self):
        help_text = format_scenario_help()
        self.assertIn("standard (Standard Basin)", help_text)
        self.assertIn("plague_start (Plague Start)", help_text)

    def test_unknown_scenario_raises_key_error(self):
        with self.assertRaises(KeyError):
            get_scenario_profile("does_not_exist")


if __name__ == "__main__":
    unittest.main()
