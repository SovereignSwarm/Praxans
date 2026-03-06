from __future__ import annotations

import math

import pygame

from graphics.content import ANIMATION_TIMINGS, snap_zoom_level
from graphics.palette import HAZARD_COLORS, NPC_COLORS, doctrine_color, lighten


class EntityRenderer:
    def __init__(self, sprite_library, config):
        self.sprite_library = sprite_library
        self.config = config

    def _zoom_band(self, frame) -> float:
        return snap_zoom_level(frame.world.camera.zoom, self.config.snap_zoom_levels)

    def _screen_point(self, frame, world_x: float, world_y: float) -> tuple[int, int]:
        zoom = self._zoom_band(frame)
        return (int((world_x - frame.world.camera.x) * zoom), int((world_y - frame.world.camera.y) * zoom))

    def _is_visible(self, frame, entity_state, margin: int = 80) -> bool:
        entity = entity_state.entity
        if entity_state.entity_type in {"building", "resource", "encounter", "npc", "hazard"}:
            if hasattr(frame.world.fog_of_war, "is_visible") and not frame.world.fog_of_war.is_visible(entity.x, entity.y):
                return False
        screen_x, screen_y = self._screen_point(frame, entity.x, entity.y)
        extra = max(120, int(120 * self._zoom_band(frame)))
        if entity_state.entity_type == "hazard":
            extra = max(extra, int(getattr(entity, "radius", 32) * self._zoom_band(frame)))
        return -extra <= screen_x <= frame.world.window_size[0] + extra and -extra <= screen_y <= frame.world.window_size[1] + extra

    def _draw_selection_ring(self, surface: pygame.Surface, frame, entity_state, radius: int) -> None:
        pulse = 0.5 + 0.5 * math.sin(frame.world.current_time * (2 * math.pi / self.config.selection_pulse_seconds))
        screen_x, screen_y = self._screen_point(frame, entity_state.entity.x, entity_state.entity.y)
        ring = pygame.Surface((radius * 2 + 12, radius * 2 + 12), pygame.SRCALPHA)
        gold = (246, 223, 171)
        pygame.draw.circle(ring, (*gold, 120 + int(pulse * 55)), (radius + 6, radius + 6), radius, 2)
        pygame.draw.circle(ring, (*gold, 46 + int(pulse * 36)), (radius + 6, radius + 6), max(4, radius // 2), 1)
        surface.blit(ring, (screen_x - radius - 6, screen_y - radius - 6))

    def _frame_index(self, frame, animation_state: str) -> int:
        duration = ANIMATION_TIMINGS.get(animation_state, 0.4)
        return int(frame.world.current_time / max(0.05, duration)) % 2

    def _draw_buildings(self, surface: pygame.Surface, frame) -> None:
        zoom = self._zoom_band(frame)
        for entity_state in frame.buildings:
            if not self._is_visible(frame, entity_state):
                continue
            building = entity_state.entity
            active = entity_state.animation_state == "active"
            target_size = (
                max(28, int(34 * zoom)),
                max(28, int(40 * zoom)),
            )
            occupancy = len(getattr(building, "occupants", []) or []) / max(1, 2 + max(0, int(getattr(building, "level", 1)) - 1))
            sprite = self.sprite_library.get_building_sprite(
                building_type=str(getattr(building, "building_type", "house")),
                level=int(getattr(building, "level", 1) or 1),
                active=active,
                occupancy_ratio=occupancy,
                target_size=target_size,
            )
            screen_x, screen_y = self._screen_point(frame, building.x, building.y)
            surface.blit(sprite, (screen_x - sprite.get_width() // 2, screen_y - int(sprite.get_height() * 0.62)))
            if entity_state.selected:
                self._draw_selection_ring(surface, frame, entity_state, max(16, int(18 * zoom)))

    def _draw_migration_vectors(self, surface: pygame.Surface, frame) -> None:
        faction_manager = frame.world.faction_manager
        if faction_manager is None:
            return
        for faction in getattr(faction_manager, "factions", {}).values():
            if not getattr(faction, "migration_target", None):
                continue
            centroid = faction.get_centroid([state.entity for state in frame.thronglets])
            if not centroid:
                continue
            start_x, start_y = self._screen_point(frame, centroid[0], centroid[1])
            target_x, target_y = self._screen_point(frame, faction.migration_target[0], faction.migration_target[1])
            route_color = doctrine_color(getattr(faction, "primary_doctrine", "survival"))
            guide = pygame.Surface(frame.world.window_size, pygame.SRCALPHA)
            pygame.draw.line(guide, (*route_color, 128), (start_x, start_y), (target_x, target_y), 2)
            pygame.draw.circle(guide, (*lighten(route_color, 0.2), 168), (target_x, target_y), 6, 2)
            surface.blit(guide, (0, 0))

    def _draw_resources(self, surface: pygame.Surface, frame) -> None:
        zoom = self._zoom_band(frame)
        for entity_state in frame.resources:
            resource = entity_state.entity
            if getattr(resource, "collected", False) or not self._is_visible(frame, entity_state):
                continue
            target_size = (max(12, int(22 * zoom)), max(12, int(22 * zoom)))
            sprite = self.sprite_library.get_resource_sprite(
                resource_type=str(getattr(resource, "resource_type", "food")),
                target_size=target_size,
                depleted=bool(getattr(resource, "collected", False)),
            )
            screen_x, screen_y = self._screen_point(frame, resource.x, resource.y)
            surface.blit(sprite, (screen_x - sprite.get_width() // 2, screen_y - int(sprite.get_height() * 0.7)))
            if entity_state.selected:
                self._draw_selection_ring(surface, frame, entity_state, max(11, int(12 * zoom)))

    def _draw_thronglets(self, surface: pygame.Surface, frame) -> None:
        factions = getattr(frame.world.faction_manager, "factions", {}) if frame.world.faction_manager is not None else {}
        zoom = self._zoom_band(frame)
        for entity_state in frame.thronglets:
            if not self._is_visible(frame, entity_state):
                continue
            thronglet = entity_state.entity
            faction = factions.get(getattr(thronglet, "faction_id", None))
            doctrine = getattr(faction, "primary_doctrine", None) if faction is not None else None
            frame_index = self._frame_index(frame, entity_state.animation_state)
            sprite = self.sprite_library.get_thronglet_sprite(
                role=getattr(thronglet, "role", None),
                animation_state=entity_state.animation_state,
                facing=entity_state.facing,
                doctrine=doctrine,
                variant_id=entity_state.variant_id,
                health_state=entity_state.health_state,
                mutated=bool(getattr(thronglet, "mutation_count", 0) > 0),
                target_size=(max(16, int(32 * zoom)), max(24, int(48 * zoom))),
                frame_index=frame_index,
            )
            screen_x, screen_y = self._screen_point(frame, thronglet.x, thronglet.y)
            surface.blit(sprite, (screen_x - sprite.get_width() // 2, screen_y - sprite.get_height() + int(10 * zoom)))
            if entity_state.selected:
                self._draw_selection_ring(surface, frame, entity_state, max(12, int(14 * zoom)))
            if entity_state.selected and self.config.show_role_pennants:
                pennant = self.sprite_library.get_role_pennant(getattr(thronglet, "role", ""), doctrine, size=max(10, int(12 * zoom)))
                surface.blit(pennant, (screen_x + int(10 * zoom), screen_y - sprite.get_height() // 2))
            if entity_state.selected and self.config.show_action_badges:
                badge = self.sprite_library.get_action_marker(str(getattr(thronglet, "current_action", "")), size=max(14, int(18 * zoom)))
                surface.blit(badge, (screen_x - badge.get_width() // 2, screen_y - sprite.get_height() - max(8, int(6 * zoom))))

    def _draw_encounters(self, surface: pygame.Surface, frame) -> None:
        zoom = self._zoom_band(frame)
        for entity_state in frame.encounters:
            encounter = entity_state.entity
            if not getattr(encounter, "discovered", False) or not self._is_visible(frame, entity_state):
                continue
            sprite = self.sprite_library.get_encounter_sprite(
                encounter_type=str(getattr(encounter, "encounter_type", "ruins")),
                target_size=(max(14, int(26 * zoom)), max(16, int(28 * zoom))),
                explored=bool(getattr(encounter, "explored", False)),
            )
            screen_x, screen_y = self._screen_point(frame, encounter.x, encounter.y)
            surface.blit(sprite, (screen_x - sprite.get_width() // 2, screen_y - int(sprite.get_height() * 0.7)))
            if entity_state.selected:
                self._draw_selection_ring(surface, frame, entity_state, max(14, int(15 * zoom)))

    def _draw_hazards(self, surface: pygame.Surface, frame) -> None:
        zoom = self._zoom_band(frame)
        for entity_state in frame.hazards:
            hazard = entity_state.entity
            if not getattr(hazard, "active", False) or not self._is_visible(frame, entity_state):
                continue
            screen_x, screen_y = self._screen_point(frame, hazard.x, hazard.y)
            radius = max(18, int(getattr(hazard, "radius", 32) * zoom))
            color = HAZARD_COLORS.get(getattr(hazard, "hazard_type", ""), (224, 113, 102))
            field = pygame.Surface((radius * 2 + 12, radius * 2 + 12), pygame.SRCALPHA)
            pygame.draw.circle(field, (*color, 38), (radius + 6, radius + 6), radius)
            pygame.draw.circle(field, (*color, 118), (radius + 6, radius + 6), radius, 2)
            surface.blit(field, (screen_x - radius - 6, screen_y - radius - 6))
            icon = self.sprite_library.get_hazard_sprite(
                hazard_type=str(getattr(hazard, "hazard_type", "predator_lair")),
                target_size=(max(18, int(28 * zoom)), max(18, int(28 * zoom))),
            )
            surface.blit(icon, (screen_x - icon.get_width() // 2, screen_y - icon.get_height() // 2))
            if entity_state.selected:
                self._draw_selection_ring(surface, frame, entity_state, max(radius, int(18 * zoom)))

    def _draw_npcs(self, surface: pygame.Surface, frame) -> None:
        zoom = self._zoom_band(frame)
        for entity_state in frame.npcs:
            npc = entity_state.entity
            if not getattr(npc, "visible", False) or not self._is_visible(frame, entity_state):
                continue
            sprite = self.sprite_library.get_npc_sprite(
                npc_type=str(getattr(npc, "npc_type", "trader")),
                target_size=(max(16, int(28 * zoom)), max(20, int(34 * zoom))),
                frame_index=self._frame_index(frame, "walk"),
            )
            screen_x, screen_y = self._screen_point(frame, npc.x, npc.y)
            surface.blit(sprite, (screen_x - sprite.get_width() // 2, screen_y - int(sprite.get_height() * 0.82)))
            marker_color = NPC_COLORS.get(getattr(npc, "npc_type", ""), (216, 216, 216))
            pygame.draw.circle(surface, marker_color, (screen_x, screen_y - int(18 * zoom)), max(2, int(3 * zoom)))
            if entity_state.selected:
                self._draw_selection_ring(surface, frame, entity_state, max(14, int(16 * zoom)))

    def render(self, surface: pygame.Surface, frame) -> None:
        self._draw_buildings(surface, frame)
        self._draw_migration_vectors(surface, frame)
        self._draw_resources(surface, frame)
        self._draw_thronglets(surface, frame)
        self._draw_encounters(surface, frame)
        self._draw_hazards(surface, frame)
        self._draw_npcs(surface, frame)
