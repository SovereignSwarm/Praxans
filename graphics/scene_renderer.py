from __future__ import annotations

import os

import pygame

from graphics.effects_renderer import EffectsRenderer
from graphics.entity_renderer import EntityRenderer
from graphics.sprites import SpriteLibrary
from graphics.terrain_renderer import TerrainRenderer


class SceneRenderer:
    def __init__(self, config, asset_root: str | None = None):
        self.config = config
        self.sprite_library = SpriteLibrary(asset_root or os.path.join(os.path.dirname(__file__), "..", "assets"), config)
        self.terrain_renderer = TerrainRenderer(self.sprite_library, config)
        self.entity_renderer = EntityRenderer(self.sprite_library, config)
        self.effects_renderer = EffectsRenderer(config)
        self.last_thumbnail = None

    def render(self, surface, frame) -> None:
        surface.fill((24, 28, 33))
        self.terrain_renderer.render(surface, frame)
        
        # Draw animals between terrain and entities
        if hasattr(frame.world, 'world_map') and frame.world.world_map and getattr(frame.world.world_map, 'zoology_manager', None):
            frame.world.world_map.zoology_manager.draw(surface, frame.world.camera)
            
        self.entity_renderer.render(surface, frame)
        self.effects_renderer.render(surface, frame)
        if self.config.enable_scene_thumbnails:
            self.last_thumbnail = pygame.transform.scale(surface, (192, 108))
