from __future__ import annotations

import os

import pygame

from graphics.content import (
    ANIMATION_TIMINGS,
    BUILDING_FOOTPRINT_ART,
    DISTRICT_OVERLAYS,
    HAZARD_ART,
    NPC_ART,
    RESOURCE_ART,
    ROLE_PALETTES,
    SOURCE_RESOURCE_SIZE,
    SOURCE_PRAXAN_SIZE,
    SOURCE_TILE_SIZE,
    TILE_ATLASES,
    palette_for_biome_and_season,
)
from graphics.content import doctrine_trim
from graphics.palette import darken, doctrine_color, lighten, mix_color


def _surface(size: tuple[int, int]) -> pygame.Surface:
    return pygame.Surface(size, pygame.SRCALPHA)


def _px(surface: pygame.Surface, color, x: int, y: int, w: int = 1, h: int = 1) -> None:
    pygame.draw.rect(surface, color, (int(x), int(y), int(w), int(h)))


def _scale(surface: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
    if surface.get_size() == size:
        return surface.copy()
    return pygame.transform.scale(surface, size)


def _blit_if(surface: pygame.Surface, sprite: pygame.Surface, pos: tuple[int, int]) -> None:
    if sprite is not None:
        surface.blit(sprite, pos)


def _alpha(color: tuple[int, int, int], value: int) -> tuple[int, int, int, int]:
    return (color[0], color[1], color[2], value)


class SpriteLibrary:
    def __init__(self, asset_root: str, config=None):
        self.asset_root = asset_root
        self.config = config
        self._cache: dict[tuple, pygame.Surface] = {}

    def _add_shadow(self, surface: pygame.Surface, skew: float = 0.4, alpha: int = 100) -> pygame.Surface:
        """Bakes a skewed parallax drop shadow beneath the given surface sprite."""
        w, h = surface.get_size()
        shadow_h = int(h * 0.4)  # Shadow is shorter
        skew_offset = int(shadow_h * skew)
        
        # Extract silhouette
        mask = pygame.mask.from_surface(surface)
        shadow_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        if mask.count() > 0:
            for x in range(w):
                for y in range(h):
                    if mask.get_at((x, y)):
                        shadow_surf.set_at((x, y), (0, 0, 0, alpha))
                        
        # Scale and skew
        shadow_surf = pygame.transform.scale(shadow_surf, (w, shadow_h))
        
        # Apply skew manually (Pygame doesn't natively support oblique shear)
        skewed = pygame.Surface((w + skew_offset, shadow_h), pygame.SRCALPHA)
        for y in range(shadow_h):
            offset = int((shadow_h - y) * skew)
            line = shadow_surf.subsurface((0, y, w, 1))
            skewed.blit(line, (offset, y))
            
        # Composite - symmetrically padded horizontally to preserve exact center anchor!
        final_w = w + skew_offset * 2
        final_h = h  # Keep height identical so bottom anchor is preserved
        
        composite = pygame.Surface((final_w, final_h), pygame.SRCALPHA)
        # Blit shadow behind the entity, anchored to the bottom feet (y = h - shadow_h)
        composite.blit(skewed, (skew_offset, h - shadow_h))
        # Blit main sprite centered
        composite.blit(surface, (skew_offset, 0))
        return composite

    def _load_file_surface(self, relative_path: str, size: tuple[int, int]) -> pygame.Surface | None:
        surface_path = os.path.join(self.asset_root, relative_path)
        if not os.path.exists(surface_path):
            return None
        cache_key = ("file", surface_path, size)
        if cache_key not in self._cache:
            loaded = pygame.image.load(surface_path)
            if pygame.display.get_surface() is not None:
                loaded = loaded.convert_alpha()
            self._cache[cache_key] = _scale(loaded, size)
        return self._cache[cache_key]

    def _placeholder_surface(self, label: str, size: tuple[int, int], primary=(176, 146, 108), accent=(245, 211, 138)) -> pygame.Surface:
        key = ("placeholder", label, size, primary, accent)
        if key in self._cache:
            return self._cache[key]
        surface = _surface(size)
        pygame.draw.rect(surface, darken(primary, 0.38), surface.get_rect(), 2)
        pygame.draw.rect(surface, _alpha(primary, 140), surface.get_rect().inflate(-4, -4), border_radius=2)
        pygame.draw.line(surface, accent, (4, 4), (size[0] - 4, size[1] - 4), 2)
        pygame.draw.line(surface, accent, (size[0] - 4, 4), (4, size[1] - 4), 2)
        self._cache[key] = surface
        return surface

    def _apply_praxan_state_overlays(self, sprite: pygame.Surface, *, doctrine, health_state: str, mutated: bool) -> pygame.Surface:
        overlayed = sprite.copy()
        accent, accent_shadow = doctrine_trim(doctrine)
        width, height = overlayed.get_size()
        sash_rect = pygame.Rect(max(1, width // 4), max(1, height // 3), max(2, width // 8), max(2, height // 3))
        pygame.draw.rect(overlayed, accent_shadow, sash_rect.move(1, 0))
        pygame.draw.rect(overlayed, accent, sash_rect)
        if health_state == "critical":
            pygame.draw.rect(overlayed, (138, 86, 82, 120), overlayed.get_rect(), 2)
        elif health_state == "sick":
            pygame.draw.circle(overlayed, (126, 178, 112, 180), (max(4, width - 6), 6), 3)
        if mutated:
            pygame.draw.circle(overlayed, (192, 148, 224, 160), (width - 5, 4), 2)
        return overlayed

    def _apply_building_state_overlays(self, sprite: pygame.Surface, *, level: int, active: bool, occupancy_ratio: float) -> pygame.Surface:
        overlayed = sprite.copy()
        width, height = overlayed.get_size()
        if active:
            glow = pygame.Surface((width, height), pygame.SRCALPHA)
            pygame.draw.rect(glow, (244, 204, 132, 34), glow.get_rect(), border_radius=4)
            overlayed.blit(glow, (0, 0))
            pygame.draw.rect(
                overlayed,
                (246, 214, 140, 120),
                (max(2, width // 3), max(2, height // 2), max(4, width // 6), max(4, height // 7)),
            )
        if occupancy_ratio > 0.0:
            count = max(1, min(3, int(round(occupancy_ratio * 3))))
            for index in range(count):
                pygame.draw.circle(overlayed, (244, 223, 151), (max(5, width - 7), height - 5 - index * 4), 2)
        if level > 1:
            pygame.draw.rect(overlayed, (255, 230, 165), (width - 7, 3, 3, 3))
        return overlayed

    def _apply_resource_state_overlays(self, sprite: pygame.Surface, *, depleted: bool) -> pygame.Surface:
        if not depleted:
            return sprite
        overlayed = sprite.copy()
        shade = pygame.Surface(overlayed.get_size(), pygame.SRCALPHA)
        shade.fill((34, 28, 22, 90))
        overlayed.blit(shade, (0, 0))
        return overlayed

    def _seasonal_tile_surface(self, biome_type: str, season_name: str, variant: int) -> pygame.Surface:
        recipe = palette_for_biome_and_season(biome_type, season_name)
        source = _surface((SOURCE_TILE_SIZE, SOURCE_TILE_SIZE))
        source.fill(recipe.base)
        _px(source, recipe.light, 0, 0, SOURCE_TILE_SIZE, 2)
        _px(source, recipe.shadow, 0, SOURCE_TILE_SIZE - 2, SOURCE_TILE_SIZE, 2)
        _px(source, mix_color(recipe.base, recipe.shadow, 0.2), 0, SOURCE_TILE_SIZE - 1, SOURCE_TILE_SIZE, 1)

        if biome_type == "plains":
            for x in (2, 6, 10, 13):
                _px(source, recipe.light, x, (variant + x) % 5 + 5, 1, 2)
                _px(source, recipe.mid, x + 1, (variant + x * 2) % 6 + 8, 1, 2)
            if variant % 2 == 0:
                _px(source, recipe.accent, 4, 10)
                _px(source, recipe.accent, 11, 6)
        elif biome_type == "forest":
            for x, y in ((3, 4), (8, 3), (12, 7), (5, 11), (10, 12)):
                _px(source, recipe.mid, x, y, 3, 2)
                _px(source, darken(recipe.shadow, 0.06), x + 1, y + 1, 2, 2)
            _px(source, recipe.accent, 6, 9, 2, 3)
        elif biome_type == "mountains":
            pygame.draw.polygon(source, recipe.mid, [(0, 12), (4, 6), (7, 10), (10, 3), (15, 11), (15, 15), (0, 15)])
            pygame.draw.lines(source, recipe.light, False, [(0, 12), (4, 6), (7, 10), (10, 3), (15, 11)], 1)
            _px(source, recipe.shadow, 8, 8, 2, 5)
            _px(source, recipe.accent, 2, 13, 3, 1)
        elif biome_type == "desert":
            for y in (4, 7, 10, 13):
                pygame.draw.line(source, recipe.light, (0, y), (15, max(0, y - 2)), 1)
            _px(source, recipe.accent, 12, 11, 2, 2)
            _px(source, darken(recipe.shadow, 0.08), 4, 8, 1, 1)
        elif biome_type == "snow":
            for x, y in ((2, 5), (7, 3), (11, 8), (5, 12), (13, 13)):
                _px(source, recipe.light, x, y, 2, 1)
            pygame.draw.arc(source, mix_color(recipe.shadow, recipe.moisture, 0.3), (1, 8, 14, 6), 0.0, 3.14, 1)
        elif biome_type == "swamp":
            pygame.draw.ellipse(source, recipe.moisture, (2, 3, 8, 6))
            pygame.draw.ellipse(source, darken(recipe.moisture, 0.12), (7, 8, 7, 4))
            for x in (3, 6, 11):
                _px(source, recipe.accent, x, 12, 1, 3)
        elif biome_type == "taiga":
            for x, y in ((3, 5), (7, 3), (12, 6)):
                pygame.draw.polygon(source, recipe.mid, [(x, y + 4), (x + 2, y), (x + 4, y + 4)])
                _px(source, recipe.light, x + 2, y + 1, 1, 2)
            _px(source, recipe.shadow, 1, 12, 14, 2)
        elif biome_type == "tundra":
            pygame.draw.line(source, recipe.light, (2, 4), (6, 8), 1)
            pygame.draw.line(source, recipe.light, (8, 10), (13, 6), 1)
            _px(source, recipe.accent, 4, 12, 2, 1)
            _px(source, recipe.moisture, 11, 12, 2, 1)

        return source

    def get_tile_surface(self, biome_type: str, season_name: str, tile_size: int, variant: int = 0) -> pygame.Surface:
        cache_key = ("tile", biome_type, season_name, tile_size, variant)
        if cache_key in self._cache:
            return self._cache[cache_key]
        atlas = TILE_ATLASES.get(biome_type)
        if atlas is not None:
            relative_path = os.path.join(str(atlas["folder"]), f"{biome_type}_{str(season_name or 'spring').lower()}.png")
            file_surface = self._load_file_surface(relative_path, (tile_size, tile_size))
            if file_surface is not None:
                self._cache[cache_key] = file_surface
                return file_surface
        source = self._seasonal_tile_surface(biome_type, season_name, variant)
        self._cache[cache_key] = _scale(source, (tile_size, tile_size))
        return self._cache[cache_key]

    def get_transition_surface(self, source_biome: str, target_biome: str, edge: str, season_name: str, tile_size: int) -> pygame.Surface:
        cache_key = ("transition", source_biome, target_biome, edge, season_name, tile_size)
        if cache_key in self._cache:
            return self._cache[cache_key]
        file_surface = self._load_file_surface(
            os.path.join("tilesets", "transitions", f"{target_biome}_{edge}_{str(season_name or 'spring').lower()}.png"),
            (tile_size, tile_size),
        )
        if file_surface is not None:
            self._cache[cache_key] = file_surface
            return file_surface
        source = _surface((SOURCE_TILE_SIZE, SOURCE_TILE_SIZE))
        target_recipe = palette_for_biome_and_season(target_biome, season_name)
        band = 3
        if edge == "north":
            _px(source, _alpha(target_recipe.mid, 150), 0, 0, SOURCE_TILE_SIZE, band)
            _px(source, _alpha(target_recipe.light, 110), 0, band, SOURCE_TILE_SIZE, 1)
        elif edge == "south":
            _px(source, _alpha(target_recipe.shadow, 150), 0, SOURCE_TILE_SIZE - band, SOURCE_TILE_SIZE, band)
            _px(source, _alpha(target_recipe.mid, 120), 0, SOURCE_TILE_SIZE - band - 1, SOURCE_TILE_SIZE, 1)
        elif edge == "west":
            _px(source, _alpha(target_recipe.mid, 150), 0, 0, band, SOURCE_TILE_SIZE)
            _px(source, _alpha(target_recipe.light, 110), band, 0, 1, SOURCE_TILE_SIZE)
        elif edge == "east":
            _px(source, _alpha(target_recipe.shadow, 150), SOURCE_TILE_SIZE - band, 0, band, SOURCE_TILE_SIZE)
            _px(source, _alpha(target_recipe.mid, 110), SOURCE_TILE_SIZE - band - 1, 0, 1, SOURCE_TILE_SIZE)

        if target_biome in {"swamp", "snow", "desert", "mountains"}:
            for offset in range(0, SOURCE_TILE_SIZE, 4):
                if edge in {"north", "south"}:
                    _px(source, _alpha(target_recipe.accent, 115), offset, 1 if edge == "north" else SOURCE_TILE_SIZE - 2, 2, 1)
                else:
                    _px(source, _alpha(target_recipe.accent, 115), 1 if edge == "west" else SOURCE_TILE_SIZE - 2, offset, 1, 2)
        self._cache[cache_key] = _scale(source, (tile_size, tile_size))
        return self._cache[cache_key]

    def get_district_overlay(self, zone_type: str, tile_size: int, variant: int = 0) -> pygame.Surface:
        cache_key = ("district", zone_type, tile_size, variant)
        if cache_key in self._cache:
            return self._cache[cache_key]
        file_surface = self._load_file_surface(
            os.path.join("tilesets", "overlays", f"{str(zone_type)}_{variant % 3}.png"),
            (tile_size, tile_size),
        )
        if file_surface is not None:
            self._cache[cache_key] = file_surface
            return file_surface
        source = _surface((SOURCE_TILE_SIZE, SOURCE_TILE_SIZE))
        overlay = DISTRICT_OVERLAYS.get(str(zone_type), DISTRICT_OVERLAYS["residential"])
        accent = overlay["accent"]
        style = overlay["style"]
        if style == "footpath":
            _px(source, _alpha(accent, 96), 2, 12, 12, 2)
            _px(source, _alpha(lighten(accent, 0.15), 72), 5, 6, 2, 7)
        elif style == "furrows":
            for x in (3, 6, 9, 12):
                _px(source, _alpha(accent, 90), x, 3, 1, 10)
            _px(source, _alpha(lighten(accent, 0.15), 72), 2, 13, 12, 1)
        elif style == "yard":
            _px(source, _alpha(accent, 88), 2, 11, 12, 3)
            _px(source, _alpha(darken(accent, 0.2), 96), 4 + (variant % 5), 7, 2, 2)
            _px(source, _alpha(lighten(accent, 0.08), 80), 10, 6, 3, 2)
        elif style == "ring":
            pygame.draw.circle(source, _alpha(accent, 88), (8, 8), 5, 1)
            _px(source, _alpha(lighten(accent, 0.15), 104), 7, 2, 2, 2)
        self._cache[cache_key] = _scale(source, (tile_size, tile_size))
        return self._cache[cache_key]

    def _praxan_source(self, role: str | None, animation_state: str, facing: str, doctrine, frame_index: int, health_state: str, mutated: bool) -> pygame.Surface:
        palette = ROLE_PALETTES.get(str(role or "").lower(), ROLE_PALETTES["default"])
        accent, accent_shadow = doctrine_trim(doctrine)
        skin = palette.skin
        hair = palette.hair
        clothing = palette.clothing
        if health_state == "critical":
            clothing = darken(clothing, 0.18)
            skin = mix_color(skin, (168, 170, 158), 0.18)
        elif health_state == "sick":
            clothing = mix_color(clothing, (138, 154, 126), 0.16)
            skin = mix_color(skin, (170, 188, 164), 0.16)
        source = _surface(SOURCE_PRAXAN_SIZE)
        mid_x = 8
        bounce = 1 if animation_state in {"walk", "celebrate"} and frame_index % 2 == 0 else 0
        leg_shift = -1 if frame_index % 2 == 0 else 1

        # Breathing: subtle torso lift on alternating idle frames
        breathe = 0
        if animation_state == "idle" and frame_index % 4 < 2:
            breathe = 1

        _px(source, (0, 0, 0, 74), 4, 20 + bounce, 8 + (1 if breathe else 0), 2)
        _px(source, hair, 5, 1 + bounce, 6, 3)
        _px(source, skin, 5, 3 + bounce, 6, 4)
        if facing == "up":
            _px(source, hair, 4, 2 + bounce, 8, 4)
        elif facing in {"left", "right"}:
            head_x = 4 if facing == "left" else 6
            _px(source, hair, head_x, 1 + bounce, 5, 4)
            _px(source, skin, head_x + 1, 3 + bounce, 4, 4)
            eye_x = head_x + (1 if facing == "left" else 4)
            _px(source, (44, 32, 28), eye_x, 5 + bounce)
        else:
            _px(source, (42, 34, 31), 6, 5 + bounce)
            _px(source, (42, 34, 31), 9, 5 + bounce)

        torso_y = 8 + bounce
        _px(source, palette.shadow, 4, torso_y, 8, 8)
        _px(source, clothing, 5, torso_y + 1, 6, 6)
        _px(source, accent_shadow, 4, torso_y + 3, 8, 1)
        _px(source, accent, 4, torso_y + 1, 1, 5)
        _px(source, accent, 11, torso_y + 1, 1, 5)
        _px(source, palette.trim, 6, torso_y + 2, 4, 1)

        if animation_state == "celebrate":
            _px(source, skin, 2, torso_y + 1, 2, 4)
            _px(source, skin, 12, torso_y + 1, 2, 4)
        elif animation_state == "build":
            arm_y = torso_y + 3
            _px(source, skin, 2, arm_y, 3, 2)
            _px(source, skin, 11, arm_y + 1, 3, 2)
            _px(source, accent_shadow, 13, arm_y, 2, 5)
        elif animation_state == "gather":
            arm_y = torso_y + 4
            _px(source, skin, 2, arm_y, 3, 2)
            _px(source, palette.trim, 12, arm_y + 1, 2, 2)
        elif animation_state == "rest":
            _px(source, skin, 3, torso_y + 5, 10, 2)
        else:
            _px(source, skin, 3, torso_y + 3, 2, 4)
            _px(source, skin, 11, torso_y + 3, 2, 4)

        leg_y = 16 + bounce
        if animation_state in {"walk", "celebrate"}:
            _px(source, palette.shadow, mid_x - 4 + leg_shift, leg_y, 2, 5)
            _px(source, palette.shadow, mid_x + 1 - leg_shift, leg_y + 1, 2, 4)
        elif animation_state == "rest":
            _px(source, palette.shadow, 4, leg_y + 2, 8, 2)
        else:
            _px(source, palette.shadow, mid_x - 3, leg_y, 2, 5)
            _px(source, palette.shadow, mid_x + 1, leg_y, 2, 5)

        if role == "builder":
            _px(source, accent_shadow, 1, torso_y + 5, 2, 2)
            _px(source, palette.trim, 2, torso_y + 4, 1, 4)
        elif role == "gatherer":
            _px(source, palette.trim, 11, torso_y + 4, 3, 3)
        elif role == "explorer":
            _px(source, accent, 4, torso_y, 8, 1)
            _px(source, accent_shadow, 6, leg_y, 1, 5)

        if health_state == "sick":
            _px(source, (124, 173, 110), 3, 3 + bounce, 1, 1)
        if mutated:
            _px(source, (198, 149, 230), 12, 2 + bounce, 2, 1)

        return source

    def get_praxan_sprite(
        self,
        *,
        role: str | None,
        animation_state: str,
        facing: str,
        doctrine,
        variant_id: int,
        health_state: str,
        mutated: bool,
        target_size: tuple[int, int],
        frame_index: int,
    ) -> pygame.Surface:
        cache_key = (
            "praxan",
            role,
            animation_state,
            facing,
            doctrine,
            variant_id,
            health_state,
            mutated,
            target_size,
            frame_index,
        )
        if cache_key in self._cache:
            return self._cache[cache_key]
        file_surface = self._load_file_surface(
            os.path.join("sprites", "praxans", f"{str(role or 'default').lower()}_{animation_state}_{facing}_{frame_index}.png"),
            target_size,
        )
        if file_surface is not None:
            self._cache[cache_key] = self._apply_praxan_state_overlays(
                file_surface,
                doctrine=doctrine,
                health_state=health_state,
                mutated=mutated,
            )
            return self._cache[cache_key]
        source = self._praxan_source(role, animation_state, facing, doctrine, frame_index, health_state, mutated)
        shadowed = self._add_shadow(source, skew=0.3, alpha=80)
        self._cache[cache_key] = _scale(shadowed, target_size)
        return self._cache[cache_key]

    def _building_source(self, building_type: str, level: int, active: bool, occupancy_ratio: float) -> pygame.Surface:
        recipe = BUILDING_FOOTPRINT_ART.get(building_type, BUILDING_FOOTPRINT_ART["house"])
        source = _surface(recipe.source_size)
        width, height = recipe.source_size
        base_y = height - 10
        if building_type == "house":
            pygame.draw.polygon(source, recipe.roof, [(3, 16), (width // 2, 2), (width - 4, 16)])
            pygame.draw.polygon(source, lighten(recipe.roof, 0.16), [(4, 16), (width // 2, 4), (width // 2, 16)])
            _px(source, recipe.wall, 6, 16, width - 12, 14)
            _px(source, recipe.trim, 13, 22, 6, 8)
            window = recipe.accent if active or occupancy_ratio > 0 else darken(recipe.wall, 0.12)
            _px(source, window, 9, 20, 4, 4)
            _px(source, window, 19, 20, 4, 4)
        elif building_type == "storage":
            _px(source, recipe.roof, 4, 9, width - 8, 6)
            _px(source, recipe.wall, 5, 15, width - 10, 13)
            _px(source, recipe.trim, 8, 18, width - 16, 8)
            _px(source, recipe.accent, 8, 28, 5, 3)
            _px(source, recipe.accent, 19, 26, 6, 5)
        elif building_type == "farm":
            _px(source, darken(recipe.wall, 0.14), 2, 18, width - 4, 12)
            for x in (5, 10, 15, 20, 25):
                _px(source, recipe.accent, x, 20, 1, 8)
            _px(source, recipe.trim, 23, 9, 5, 9)
            _px(source, lighten(recipe.roof, 0.1), 21, 7, 9, 4)
        elif building_type == "workshop":
            pygame.draw.polygon(source, recipe.roof, [(4, 15), (13, 6), (width - 5, 15), (width - 5, 17), (4, 17)])
            _px(source, recipe.wall, 5, 17, width - 10, 12)
            _px(source, recipe.trim, 8, 20, 7, 9)
            _px(source, darken(recipe.trim, 0.2), width - 11, 8, 3, 9)
            if active:
                _px(source, recipe.accent, width - 11, 6, 3, 2)
                _px(source, _alpha(lighten(recipe.accent, 0.2), 140), width - 10, 3, 2, 3)
        elif building_type == "shrine":
            _px(source, recipe.trim, 8, 11, width - 16, 18)
            _px(source, recipe.wall, 12, 6, width - 24, 7)
            pygame.draw.arc(source, recipe.accent, (8, 6, width - 16, 18), 3.14, 6.28, 2)
            _px(source, recipe.accent if active else lighten(recipe.accent, 0.12), width // 2 - 2, 17, 4, 6)
        elif building_type == "well":
            pygame.draw.ellipse(source, recipe.trim, (6, 13, width - 12, 9))
            pygame.draw.ellipse(source, recipe.accent, (8, 15, width - 16, 5))
            _px(source, recipe.roof, 11, 4, 2, 10)
            _px(source, recipe.roof, width - 13, 4, 2, 10)
            _px(source, recipe.roof, 10, 5, width - 20, 2)
        if level > 1:
            _px(source, lighten(recipe.accent, 0.18), width - 8, 3, 3, 3)
        if active and building_type in {"house", "shrine", "workshop"}:
            _px(source, _alpha(lighten(recipe.accent, 0.15), 120), 3, base_y - 7, width - 6, 2)
        return source

    def get_building_sprite(
        self,
        *,
        building_type: str,
        level: int,
        active: bool,
        occupancy_ratio: float,
        target_size: tuple[int, int],
    ) -> pygame.Surface:
        cache_key = ("building", building_type, level, active, round(occupancy_ratio, 2), target_size)
        if cache_key in self._cache:
            return self._cache[cache_key]
        file_surface = self._load_file_surface(os.path.join("sprites", "buildings", f"{building_type}.png"), target_size)
        if file_surface is not None:
            self._cache[cache_key] = self._apply_building_state_overlays(
                file_surface,
                level=level,
                active=active,
                occupancy_ratio=occupancy_ratio,
            )
            return self._cache[cache_key]
        source = self._building_source(building_type, level, active, occupancy_ratio)
        self._cache[cache_key] = _scale(self._add_shadow(source, skew=0.5, alpha=110), target_size)
        return self._cache[cache_key]

    def _resource_source(self, resource_type: str, depleted: bool) -> pygame.Surface:
        recipe = RESOURCE_ART.get(resource_type, RESOURCE_ART["food"])
        source = _surface(SOURCE_RESOURCE_SIZE)
        if recipe.silhouette == "berry_bush":
            _px(source, recipe.primary, 5, 5, 6, 6)
            _px(source, recipe.accent, 6, 4, 4, 2)
            _px(source, recipe.secondary, 4, 10, 8, 4)
            if not depleted:
                for point in ((4, 8), (7, 6), (10, 9)):
                    _px(source, recipe.secondary, point[0], point[1], 2, 2)
        elif recipe.silhouette == "timber":
            _px(source, recipe.secondary, 4, 5, 8, 9)
            _px(source, recipe.primary, 2, 11, 12, 3)
            _px(source, recipe.accent, 5, 3, 6, 2)
        elif recipe.silhouette == "ore":
            pygame.draw.polygon(source, recipe.primary, [(3, 11), (6, 4), (11, 3), (13, 8), (10, 13), (5, 14)])
            _px(source, recipe.secondary, 8, 4, 2, 2)
            _px(source, recipe.accent, 5, 10, 2, 2)
        elif recipe.silhouette == "spring":
            pygame.draw.ellipse(source, recipe.primary, (3, 7, 10, 7))
            _px(source, recipe.accent, 5, 9, 6, 2)
            _px(source, recipe.secondary, 4, 4, 8, 2)
        return source

    def get_resource_sprite(self, *, resource_type: str, target_size: tuple[int, int], depleted: bool) -> pygame.Surface:
        cache_key = ("resource", resource_type, target_size, depleted)
        if cache_key in self._cache:
            return self._cache[cache_key]
        file_surface = self._load_file_surface(os.path.join("sprites", "resources", f"{resource_type}.png"), target_size)
        if file_surface is not None:
            self._cache[cache_key] = self._apply_resource_state_overlays(file_surface, depleted=depleted)
            return self._cache[cache_key]
        source = self._resource_source(resource_type, depleted)
        self._cache[cache_key] = _scale(self._add_shadow(source, skew=0.4, alpha=90), target_size)
        return self._cache[cache_key]

    def get_encounter_sprite(self, *, encounter_type: str, target_size: tuple[int, int], explored: bool) -> pygame.Surface:
        cache_key = ("encounter", encounter_type, target_size, explored)
        if cache_key in self._cache:
            return self._cache[cache_key]
        source = _surface((16, 18))
        if encounter_type == "ruins":
            _px(source, (123, 96, 77), 3, 8, 10, 7)
            _px(source, (168, 140, 118), 5, 5, 6, 4)
        elif encounter_type == "mineral_vein":
            pygame.draw.polygon(source, (170, 178, 190), [(8, 2), (13, 8), (9, 15), (4, 13), (3, 6)])
            _px(source, (222, 230, 240), 7, 6, 2, 2)
        elif encounter_type == "oasis":
            pygame.draw.ellipse(source, (90, 166, 196), (3, 8, 10, 5))
            _px(source, (76, 140, 102), 2, 4, 2, 7)
            _px(source, (76, 140, 102), 12, 5, 2, 6)
        else:
            pygame.draw.circle(source, (88, 132, 92), (8, 10), 5)
            _px(source, (168, 208, 152), 7, 3, 2, 4)
        if explored:
            overlay = _surface(source.get_size())
            overlay.fill((0, 0, 0, 70))
            source.blit(overlay, (0, 0))
        self._cache[cache_key] = _scale(self._add_shadow(source, skew=0.35, alpha=100), target_size)
        return self._cache[cache_key]

    def get_hazard_sprite(self, *, hazard_type: str, target_size: tuple[int, int]) -> pygame.Surface:
        cache_key = ("hazard", hazard_type, target_size)
        if cache_key in self._cache:
            return self._cache[cache_key]
        recipe = HAZARD_ART.get(hazard_type, next(iter(HAZARD_ART.values())))
        source = _surface((24, 24))
        pygame.draw.circle(source, _alpha(recipe.primary, 62), (12, 12), 10)
        pygame.draw.circle(source, _alpha(recipe.secondary, 124), (12, 12), 7, 1)
        if recipe.emblem == "spiral":
            pygame.draw.arc(source, recipe.secondary, (6, 6, 12, 12), 0.6, 5.6, 2)
        elif recipe.emblem == "peak":
            pygame.draw.polygon(source, recipe.secondary, [(6, 16), (12, 6), (18, 16)])
        elif recipe.emblem == "wave":
            pygame.draw.arc(source, recipe.secondary, (5, 9, 14, 7), 3.14, 6.1, 2)
        else:
            pygame.draw.line(source, recipe.secondary, (8, 8), (12, 16), 2)
            pygame.draw.line(source, recipe.secondary, (12, 16), (16, 8), 2)
        self._cache[cache_key] = _scale(self._add_shadow(source, skew=0.2, alpha=60), target_size)
        return self._cache[cache_key]

    def get_npc_sprite(self, *, npc_type: str, target_size: tuple[int, int], frame_index: int) -> pygame.Surface:
        cache_key = ("npc", npc_type, target_size, frame_index)
        if cache_key in self._cache:
            return self._cache[cache_key]
        recipe = NPC_ART.get(npc_type, NPC_ART["trader"])
        source = _surface((18, 24))
        if recipe.silhouette == "wagon":
            _px(source, recipe.clothing, 2, 10, 14, 6)
            _px(source, recipe.accent, 6, 8, 6, 3)
            _px(source, (52, 40, 30), 3, 16, 4, 4)
            _px(source, (52, 40, 30), 11, 16, 4, 4)
        elif recipe.silhouette == "scout":
            _px(source, recipe.clothing, 6, 4, 6, 6)
            _px(source, recipe.accent, 5, 10, 8, 7)
            _px(source, darken(recipe.clothing, 0.22), 6 + (frame_index % 2), 17, 2, 4)
            _px(source, darken(recipe.clothing, 0.22), 10 - (frame_index % 2), 17, 2, 4)
        else:
            for x, y in ((3, 13), (8, 9), (12, 14)):
                _px(source, recipe.clothing, x, y, 4, 4)
            _px(source, recipe.accent, 7, 6, 4, 2)
        self._cache[cache_key] = _scale(self._add_shadow(source, skew=0.3, alpha=80), target_size)
        return self._cache[cache_key]

    def get_action_marker(self, action: str, size: int = 18) -> pygame.Surface:
        key = ("action", action, size)
        if key in self._cache:
            return self._cache[key]
        source = _surface((10, 10))
        normalized = str(action or "").lower()
        accent = doctrine_color("growth")
        if "build" in normalized:
            _px(source, (84, 58, 42), 4, 1, 2, 8)
            _px(source, accent, 2, 4, 6, 2)
        elif "gather" in normalized or "food" in normalized:
            pygame.draw.circle(source, accent, (5, 5), 3)
            _px(source, (84, 130, 72), 4, 1, 2, 3)
        elif "rest" in normalized:
            _px(source, (178, 168, 208), 2, 6, 6, 2)
            _px(source, (126, 118, 162), 6, 3, 2, 3)
        else:
            pygame.draw.circle(source, (214, 214, 214), (5, 5), 3, 1)
        self._cache[key] = _scale(source, (size, size))
        return self._cache[key]

    def get_role_pennant(self, role: str | None, doctrine: str | None, size: int = 11) -> pygame.Surface:
        key = ("role", role, doctrine, size)
        if key in self._cache:
            return self._cache[key]
        source = _surface((8, 8))
        accent, accent_shadow = doctrine_trim(doctrine)
        _px(source, accent_shadow, 1, 1, 1, 6)
        pygame.draw.polygon(source, accent, [(2, 2), (7, 4), (2, 6)])
        if str(role or "").lower() == "builder":
            _px(source, (82, 60, 44), 4, 3, 1, 3)
        elif str(role or "").lower() == "gatherer":
            _px(source, (183, 96, 102), 4, 4, 2, 2)
        elif str(role or "").lower() == "explorer":
            _px(source, (210, 214, 223), 4, 4, 1, 2)
        self._cache[key] = _scale(source, (size, size))
        return self._cache[key]
