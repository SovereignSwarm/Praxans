import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from graphics import GraphicsConfig, SceneRenderer, build_render_frame
from graphics.sprites import SpriteLibrary


class _DummyCamera:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.zoom = 1.0
        self.min_zoom = 0.125
        self.max_zoom = 3.0

    def world_to_screen(self, world_x, world_y):
        return (world_x, world_y)


class _DummyFog:
    def __init__(self):
        self.draw_calls = 0

    def is_visible(self, *_args):
        return True

    def draw_fog(self, *_args):
        self.draw_calls += 1


class _DummyTerritory:
    def __init__(self):
        self.draw_calls = 0

    def draw_territory_overlay(self, *_args):
        self.draw_calls += 1


class _DummyCityPlanner:
    def __init__(self):
        self.zones = {(2, 2): "residential", (4, 3): "agricultural"}


class _DummyParticleSystem:
    def __init__(self):
        self.draw_calls = 0

    def draw(self, surface):
        self.draw_calls += 1
        pygame.draw.circle(surface, (255, 255, 255), (20, 20), 4)


class _DummyEntity:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _DummyBuilding(_DummyEntity):
    def draw(self, surface):
        pygame.draw.rect(surface, (180, 120, 80), (int(self.x - 6), int(self.y - 6), 12, 12))


class _DummyResource(_DummyEntity):
    def __init__(self, x, y, resource_type="food", collected=False):
        super().__init__(x, y)
        self.resource_type = resource_type
        self.collected = collected

    def draw(self, surface, _praxans):
        pygame.draw.circle(surface, (210, 90, 90), (int(self.x), int(self.y)), 5)


class _DummyPraxan(_DummyEntity):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.role = "gatherer"
        self.current_action = "gather food"
        self.diseased = False
        self.mutation_count = 1

    def draw(self, surface):
        pygame.draw.circle(surface, (240, 220, 120), (int(self.x), int(self.y)), 7)


class _DummyEncounter(_DummyEntity):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.discovered = True

    def draw(self, surface):
        pygame.draw.rect(surface, (120, 180, 210), (int(self.x - 5), int(self.y - 5), 10, 10), 1)


class _DummyHazard(_DummyEntity):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.active = True
        self.radius = 32
        self.hazard_type = "predator_lair"

    def draw(self, surface):
        pygame.draw.circle(surface, (220, 80, 80), (int(self.x), int(self.y)), int(self.radius), 1)


class _DummyNpc(_DummyEntity):
    def __init__(self, x, y):
        super().__init__(x, y)
        self.visible = True
        self.npc_type = "trader"

    def draw(self, surface):
        pygame.draw.circle(surface, (220, 180, 100), (int(self.x), int(self.y)), 8)


class _DummyFaction:
    def __init__(self):
        self.migration_target = (80.0, 70.0)
        self.primary_doctrine = "growth"

    def get_centroid(self, praxans):
        if not praxans:
            return None
        return (sum(t.x for t in praxans) / len(praxans), sum(t.y for t in praxans) / len(praxans))


class _DummyChunk:
    def __init__(self):
        self.world_x = 0
        self.world_y = 0
        self.tiles = {
            (0, 0): "plains",
            (1, 0): "forest",
            (2, 0): "mountains",
            (3, 0): "desert",
            (0, 1): "swamp",
            (1, 1): "taiga",
            (2, 1): "snow",
            (3, 1): "tundra",
        }


class GraphicsRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_sprite_library_fallback_tile_surface(self):
        library = SpriteLibrary(os.path.join(os.path.dirname(__file__), "..", "assets"))
        tile_surface = library.get_tile_surface("plains", "spring", 8, 0)
        self.assertEqual(tile_surface.get_size(), (8, 8))

    def test_generated_asset_pack_contains_representative_files(self):
        asset_root = os.path.join(os.path.dirname(__file__), "..", "assets")
        expected = [
            os.path.join(asset_root, "tilesets", "terrain", "plains_spring.png"),
            os.path.join(asset_root, "tilesets", "transitions", "forest_north_spring.png"),
            os.path.join(asset_root, "tilesets", "overlays", "residential_0.png"),
            os.path.join(asset_root, "sprites", "thronglets", "gatherer_walk_down_0.png"),
            os.path.join(asset_root, "sprites", "buildings", "house.png"),
            os.path.join(asset_root, "sprites", "resources", "food.png"),
            os.path.join(asset_root, "sprites", "hazards", "predator_lair.png"),
            os.path.join(asset_root, "sprites", "npcs", "trader.png"),
        ]
        for path in expected:
            self.assertTrue(os.path.exists(path), path)

    def test_scene_renderer_smoke_and_cache_reuse(self):
        surface = pygame.Surface((320, 240), pygame.SRCALPHA)
        renderer = SceneRenderer(GraphicsConfig())
        fog = _DummyFog()
        territory = _DummyTerritory()
        particles = _DummyParticleSystem()
        praxan = _DummyPraxan(40, 50)
        frame = build_render_frame(
            world_map=SimpleNamespace(
                chunks={(0, 0): _DummyChunk()},
                region_overlay=[{"region_id": "r0_0", "biome": "plains", "world_rect": [0, 0, 64, 64], "claimed_by": 0}],
                route_network=[{"route_id": "route_a", "start_region_id": "r0_0", "end_region_id": "r0_0", "points": [{"x": 8.0, "y": 8.0}, {"x": 48.0, "y": 48.0}], "risk": 0.1}],
                landmark_markers=[{"landmark_id": "landmark_0", "x": 24.0, "y": 24.0}],
                polity_overlay=[{"polity_id": 0, "accent_color": [180, 120, 90], "claimed_region_ids": ["r0_0"]}],
                water_network=[{"points": [{"x": 0.0, "y": 32.0}, {"x": 64.0, "y": 32.0}]}],
            ),
            camera=_DummyCamera(),
            fog_of_war=fog,
            territory_manager=territory,
            city_planner=_DummyCityPlanner(),
            faction_manager=SimpleNamespace(factions={1: _DummyFaction()}),
            season=SimpleNamespace(current="spring"),
            weather_system=SimpleNamespace(current_weather="rain"),
            settlement_state={"district_identity": "agrarian", "prosperity_score": 0.8, "festival_active": True},
            current_time=40.0,
            game_start_time=0.0,
            frame_count=10,
            window_size=(320, 240),
            chunk_size=32,
            tile_size=8,
            world_size=(320, 240),
            buildings=[_DummyBuilding(60, 70)],
            resources=[_DummyResource(100, 90)],
            praxans=[praxan],
            encounters=[_DummyEncounter(130, 120)],
            hazards=[_DummyHazard(170, 120)],
            npcs=[_DummyNpc(220, 140)],
            selected_entity=praxan,
            particle_system=particles,
            effect_cues=[{"label": "Birth", "category": "growth", "x": 40.0, "y": 50.0, "time": 38.0}],
        )
        renderer.render(surface, frame)
        first_chunk_cache = len(renderer.terrain_renderer._chunk_cache)
        first_scaled_cache = len(renderer.terrain_renderer._scaled_cache)
        renderer.render(surface, frame)

        self.assertGreater(first_chunk_cache, 0)
        self.assertEqual(first_chunk_cache, len(renderer.terrain_renderer._chunk_cache))
        self.assertEqual(first_scaled_cache, len(renderer.terrain_renderer._scaled_cache))
        self.assertGreater(particles.draw_calls, 0)
        self.assertGreater(fog.draw_calls, 0)
        self.assertGreater(territory.draw_calls, 0)
        self.assertIsNotNone(renderer.last_thumbnail)
        self.assertNotEqual(surface.get_at((20, 20)), pygame.Color(0, 0, 0, 0))

    def test_scene_renderer_macro_zoom_smoke(self):
        surface = pygame.Surface((320, 240), pygame.SRCALPHA)
        renderer = SceneRenderer(GraphicsConfig())
        camera = _DummyCamera()
        camera.zoom = 0.25
        frame = build_render_frame(
            world_map=SimpleNamespace(
                chunks={(0, 0): _DummyChunk()},
                region_overlay=[{"region_id": "r0_0", "biome": "forest", "world_rect": [0, 0, 64, 64], "claimed_by": 0}],
                route_network=[{"route_id": "route_a", "start_region_id": "r0_0", "end_region_id": "r0_0", "points": [{"x": 8.0, "y": 8.0}, {"x": 56.0, "y": 56.0}], "risk": 0.1}],
                landmark_markers=[{"landmark_id": "landmark_0", "x": 32.0, "y": 32.0}],
                polity_overlay=[{"polity_id": 0, "accent_color": [180, 120, 90], "claimed_region_ids": ["r0_0"]}],
                water_network=[{"points": [{"x": 0.0, "y": 32.0}, {"x": 64.0, "y": 32.0}]}],
            ),
            camera=camera,
            fog_of_war=_DummyFog(),
            territory_manager=_DummyTerritory(),
            city_planner=_DummyCityPlanner(),
            faction_manager=SimpleNamespace(factions={}),
            season=SimpleNamespace(current="spring"),
            weather_system=SimpleNamespace(current_weather="clear"),
            settlement_state={"district_identity": "agrarian"},
            current_time=10.0,
            game_start_time=0.0,
            frame_count=1,
            window_size=(320, 240),
            chunk_size=32,
            tile_size=8,
            world_size=(320, 240),
            buildings=[],
            resources=[],
            praxans=[],
            encounters=[],
            hazards=[],
            npcs=[],
        )

        renderer.render(surface, frame)

        self.assertNotEqual(surface.get_at((10, 10)), pygame.Color(0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
