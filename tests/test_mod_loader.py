import unittest

from systems.mod_loader import ModInfo, ModLoader


class ModLoaderTests(unittest.TestCase):
    def test_get_mod_by_id_finds_non_first_entry(self):
        loader = ModLoader()
        loader.discovered_mods = [
            ModInfo(mod_id="core_pack", name="Core", path="mods/core"),
            ModInfo(mod_id="weather_plus", name="Weather+", path="mods/weather"),
            ModInfo(mod_id="biomes_xl", name="Biomes XL", path="mods/biomes"),
        ]

        found = loader.get_mod_by_id("biomes_xl")

        self.assertIsNotNone(found)
        self.assertEqual("biomes_xl", found.mod_id)


if __name__ == "__main__":
    unittest.main()
