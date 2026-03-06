import unittest

from game_scenarios import get_scenario_profile
from map import build_frontier_world, build_world_profile


class MapGenerationTests(unittest.TestCase):
    def test_frontier_world_generation_is_deterministic_for_same_seed(self):
        profile = build_world_profile(get_scenario_profile("standard"), chunk_size=512, tile_size=32)
        world_a = build_frontier_world(7, profile)
        world_b = build_frontier_world(7, profile)

        self.assertEqual(world_a["seed"].value, world_b["seed"].value)
        self.assertEqual(
            [region.to_payload() for region in world_a["regions"].values()],
            [region.to_payload() for region in world_b["regions"].values()],
        )
        self.assertEqual(
            [route.to_payload() for route in world_a["routes"]],
            [route.to_payload() for route in world_b["routes"]],
        )
        self.assertEqual(world_a["chunks"][(0, 0)].tiles, world_b["chunks"][(0, 0)].tiles)

    def test_frontier_world_generation_changes_with_seed(self):
        profile = build_world_profile(get_scenario_profile("high_mutation"), chunk_size=512, tile_size=32)
        world_a = build_frontier_world(7, profile)
        world_b = build_frontier_world(9, profile)

        region_biomes_a = [region.biome for region in world_a["regions"].values()]
        region_biomes_b = [region.biome for region in world_b["regions"].values()]

        self.assertNotEqual(region_biomes_a, region_biomes_b)
        self.assertNotEqual(world_a["chunks"][(0, 0)].tiles, world_b["chunks"][(0, 0)].tiles)


if __name__ == "__main__":
    unittest.main()
