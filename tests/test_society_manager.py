import math
import unittest

from systems.society import Faction, FactionManager


class _Member:
    def __init__(self):
        self.id = 1
        self.x = 0.0
        self.y = 0.0
        self.inventory = {"food": "unknown", "wood": 2, "stone": "1"}
        self.bonds = {}
        self.role = "builder"
        self.skills = {}
        self.health = 100
        self.happiness = 70
        self.morale = 65
        self.genetics = {}


class FactionManagerResourceContextTests(unittest.TestCase):
    def test_build_resource_context_ignores_non_numeric_inventory_values(self):
        manager = FactionManager()
        faction = Faction([1])

        context = manager._build_resource_context(faction, [_Member()])

        self.assertEqual(context["food_security"], 0.0)
        self.assertAlmostEqual(context["material_security"], 78.0)
        self.assertTrue(math.isfinite(context["resource_stress"]))


if __name__ == "__main__":
    unittest.main()
