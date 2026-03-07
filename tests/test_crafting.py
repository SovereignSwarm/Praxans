"""Tests for the crafting completion loop.

Verifies:
- Ingredient checking in buildings
- Ingredient deduction from building stored_resources
- Quality roll and equipment storage as dicts
- Auto-bill population
- Meal crafting with cooked-food flag
- MoodDef application on food consumption
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
from praxans_game import Building, JOB_DEFS
sys.argv = _saved_argv

from entities.praxan import Praxan, _building_has_ingredients


class TestBuildingHasIngredients(unittest.TestCase):
    """Test the _building_has_ingredients helper."""

    def test_sufficient_resources(self):
        b = Building(100, 100, "workshop")
        b.stored_resources = {"food": 0, "wood": 10, "stone": 10}
        job_def = JOB_DEFS.get("CraftWeapon")  # needs 3 wood + 2 stone
        self.assertTrue(_building_has_ingredients(b, job_def))

    def test_insufficient_resources(self):
        b = Building(100, 100, "workshop")
        b.stored_resources = {"food": 0, "wood": 1, "stone": 10}
        job_def = JOB_DEFS.get("CraftWeapon")  # needs 3 wood
        self.assertFalse(_building_has_ingredients(b, job_def))

    def test_empty_ingredients(self):
        b = Building(100, 100, "workshop")
        b.stored_resources = {"food": 0, "wood": 0, "stone": 0}
        # A job with no ingredients should always pass
        self.assertTrue(_building_has_ingredients(b, {"ingredients": []}))


class TestAutoBillPopulation(unittest.TestCase):
    """Test that buildings auto-populate bills when resources are available."""

    def test_workshop_auto_populates_with_resources(self):
        b = Building(100, 100, "workshop")
        b.stored_resources = {"food": 0, "wood": 5, "stone": 5}
        b._auto_populate_bills()
        self.assertEqual(len(b.bills), 1)
        # Should queue either CraftWeapon or SmithArmor (both have station=workshop)
        self.assertIn(b.bills[0], ["CraftWeapon", "SmithArmor"])

    def test_workshop_no_bills_without_resources(self):
        b = Building(100, 100, "workshop")
        b.stored_resources = {"food": 0, "wood": 0, "stone": 0}
        b._auto_populate_bills()
        self.assertEqual(len(b.bills), 0)

    def test_no_double_population(self):
        b = Building(100, 100, "workshop")
        b.stored_resources = {"food": 0, "wood": 10, "stone": 10}
        b._auto_populate_bills()
        first_bill = b.bills[0]
        b._auto_populate_bills()  # Should not add another
        self.assertEqual(len(b.bills), 1)
        self.assertEqual(b.bills[0], first_bill)

    def test_farm_auto_populates_cook_meal(self):
        b = Building(100, 100, "farm")
        b.stored_resources = {"food": 5, "wood": 0, "stone": 0}
        b._auto_populate_bills()
        self.assertEqual(len(b.bills), 1)
        self.assertEqual(b.bills[0], "CookMeal")


class TestCraftItemCompletion(unittest.TestCase):
    """Test that craft_item produces proper output."""

    def setUp(self):
        self.praxan = Praxan(100, 100)
        self.building = Building(100, 100, "workshop")
        self.building.stored_resources = {"food": 0, "wood": 10, "stone": 10}
        self.building.bills = ["CraftWeapon"]

    def test_craft_weapon_produces_dict_equipment(self):
        """After crafting completes, equipment should be a dict with def data."""
        self.praxan.target_building = self.building
        self.praxan.current_bill = "CraftWeapon"
        # Place praxan at building
        self.praxan.x, self.praxan.y = 100, 100

        # First call: starts crafting (deducts ingredients)
        self.praxan.craft_item([self.building])
        self.assertTrue(hasattr(self.praxan, "crafting_start_time"))

        # Resources should have been deducted (3 wood, 2 stone)
        self.assertEqual(self.building.stored_resources["wood"], 7)
        self.assertEqual(self.building.stored_resources["stone"], 8)

        # Force completion by backdating start time
        self.praxan.crafting_start_time = time.time() - 100
        self.praxan.craft_item([self.building])

        # Equipment should now be a dict
        weapon = self.praxan.equipment.get("weapon")
        self.assertIsNotNone(weapon)
        self.assertIsInstance(weapon, dict)
        self.assertIn("quality", weapon)
        self.assertIn("damage", weapon)
        self.assertIn("id", weapon)
        self.assertEqual(weapon["id"], "spear")

        # Bill should be consumed
        self.assertEqual(len(self.building.bills), 0)

    def test_craft_meal_sets_cooked_flag(self):
        """Cooking a meal should set _has_cooked_food on the praxan."""
        farm = Building(100, 100, "farm")
        farm.stored_resources = {"food": 5, "wood": 0, "stone": 0}
        farm.bills = ["CookMeal"]

        self.praxan.target_building = farm
        self.praxan.current_bill = "CookMeal"
        self.praxan.x, self.praxan.y = 100, 100

        # Start crafting
        self.praxan.craft_item([farm])
        # Force completion
        self.praxan.crafting_start_time = time.time() - 100
        self.praxan.craft_item([farm])

        self.assertTrue(getattr(self.praxan, "_has_cooked_food", False))
        self.assertGreater(self.praxan.inventory["food"], 0)

    def test_craft_armor_stores_armor_rating(self):
        """SmithArmor should produce equipment with armor_rating."""
        self.building.bills = ["SmithArmor"]
        self.building.stored_resources = {"food": 0, "wood": 0, "stone": 10}
        self.praxan.target_building = self.building
        self.praxan.current_bill = "SmithArmor"
        self.praxan.x, self.praxan.y = 100, 100

        self.praxan.craft_item([self.building])
        self.praxan.crafting_start_time = time.time() - 100
        self.praxan.craft_item([self.building])

        armor = self.praxan.equipment.get("armor")
        self.assertIsNotNone(armor)
        self.assertIsInstance(armor, dict)
        self.assertIn("armor_rating", armor)
        self.assertGreater(armor["armor_rating"], 0)

    def test_craft_aborts_if_ingredients_vanish(self):
        """If ingredients are taken before crafting starts, should abort."""
        self.building.stored_resources = {"food": 0, "wood": 0, "stone": 0}
        self.praxan.target_building = self.building
        self.praxan.current_bill = "CraftWeapon"
        self.praxan.x, self.praxan.y = 100, 100

        self.praxan.craft_item([self.building])
        # Should have transitioned back to idle
        self.assertIsNone(self.praxan.current_bill)


class TestEquipmentInCombat(unittest.TestCase):
    """Test that dict-format equipment works with take_damage armor check."""

    def test_armor_dict_deflection(self):
        """Armor stored as dict should work in take_damage."""
        praxan = Praxan(100, 100)
        praxan.equipment["armor"] = {
            "id": "chain_mail",
            "name": "Chain Mail",
            "armor_rating": 1.0,  # Very high for test — guarantees deflect
            "quality": "Legendary",
            "quality_mult": 2.0,
        }
        initial_health = praxan.health
        # With armor_rating=1.0, deflect chance = 0.4, mitigate chance = 0.3
        # Run multiple times to verify no crash
        for _ in range(20):
            praxan.take_damage(5, current_time=time.time())
        # Should not crash — that's the main assertion
        self.assertIsNotNone(praxan.health)


if __name__ == "__main__":
    unittest.main()
