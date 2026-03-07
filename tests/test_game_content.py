import unittest

from systems.def_database import DefDatabase
from game_content import (
    BUILDING_DEFINITIONS,
    clone_abilities,
    clone_tech_tree,
    format_building_prompt_lines,
    get_building_cost,
)


class GameContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    @classmethod
    def tearDownClass(cls):
        DefDatabase.clear()
    def test_building_costs_match_expected_definitions(self):
        self.assertEqual(get_building_cost("house"), (4, 0))
        self.assertEqual(get_building_cost("farm"), (5, 0))
        self.assertEqual(get_building_cost("storage"), (3, 0))
        self.assertEqual(get_building_cost("workshop"), (6, 4))
        self.assertEqual(get_building_cost("shrine"), (8, 5))
        self.assertEqual(get_building_cost("well"), (0, 3))

    def test_prompt_lines_cover_all_buildings(self):
        prompt_lines = format_building_prompt_lines()
        self.assertEqual(len(prompt_lines), len(BUILDING_DEFINITIONS))
        self.assertTrue(any("HOUSES" in line or "HOUSE" in line for line in prompt_lines))
        self.assertTrue(any("WELL" in line for line in prompt_lines))

    def test_content_clones_are_independent(self):
        tech_tree = clone_tech_tree()
        abilities = clone_abilities()
        tech_tree["agriculture_1"]["cost"] = 999
        abilities["speed_burst"]["cost"] = 999

        self.assertNotEqual(clone_tech_tree()["agriculture_1"]["cost"], 999)
        self.assertNotEqual(clone_abilities()["speed_burst"]["cost"], 999)


if __name__ == "__main__":
    unittest.main()
