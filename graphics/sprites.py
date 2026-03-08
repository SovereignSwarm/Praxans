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
    building_lot_tile_span,
    get_building_recipe,
    get_building_lot_profile,
    get_zone_overlay_type,
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

    def _district_building_palette(self, district_identity: str) -> tuple[tuple[int, int, int], str]:
        overlay_key = get_zone_overlay_type(district_identity)
        overlay = DISTRICT_OVERLAYS.get(overlay_key, DISTRICT_OVERLAYS["mixed"])
        return (tuple(overlay["accent"]), str(overlay["style"]))

    def _materialized_building_colors(
        self,
        recipe,
        *,
        material_style: str,
        biome_type: str,
        wear: float,
    ) -> dict[str, tuple[int, int, int]]:
        wall = recipe.wall
        roof = recipe.roof
        trim = recipe.trim
        accent = recipe.accent
        style = str(material_style or "").lower()
        biome = str(biome_type or "").lower()

        if style == "timber":
            wall = mix_color(wall, (132, 98, 70), 0.26)
            roof = mix_color(roof, (110, 76, 58), 0.24)
            trim = mix_color(trim, (86, 58, 40), 0.18)
        elif style == "adobe":
            wall = mix_color(wall, (198, 156, 116), 0.34)
            roof = mix_color(roof, (170, 116, 84), 0.18)
            trim = mix_color(trim, (132, 92, 68), 0.2)
        elif style == "slate":
            wall = mix_color(wall, (132, 140, 154), 0.32)
            roof = mix_color(roof, (104, 112, 126), 0.4)
            trim = mix_color(trim, (84, 92, 110), 0.28)
        elif style == "reed":
            wall = mix_color(wall, (126, 140, 102), 0.22)
            roof = mix_color(roof, (152, 136, 78), 0.32)
            trim = mix_color(trim, (88, 94, 72), 0.14)
        elif style == "frost":
            wall = mix_color(wall, (204, 214, 224), 0.26)
            roof = mix_color(roof, (142, 156, 176), 0.32)
            trim = mix_color(trim, (94, 106, 126), 0.22)
            accent = mix_color(accent, (230, 236, 246), 0.16)
        elif style == "plaster":
            wall = mix_color(wall, (214, 206, 186), 0.2)
            roof = mix_color(roof, (160, 122, 98), 0.14)

        if biome == "swamp":
            wall = mix_color(wall, (110, 128, 106), 0.12)
            roof = darken(roof, 0.06)
        elif biome == "desert":
            wall = lighten(wall, 0.06)
            accent = mix_color(accent, (228, 188, 118), 0.18)
        elif biome in {"snow", "tundra"}:
            roof = mix_color(roof, (170, 182, 200), 0.18)
        elif biome == "forest":
            trim = mix_color(trim, (86, 96, 68), 0.08)

        patina = max(0.0, min(1.0, wear))
        if patina > 0.0:
            wall = mix_color(wall, (102, 96, 86), patina * 0.18)
            roof = mix_color(roof, (84, 80, 78), patina * 0.24)
            trim = mix_color(trim, (76, 70, 66), patina * 0.16)
            accent = mix_color(accent, (142, 134, 118), patina * 0.1)

        return {"wall": wall, "roof": roof, "trim": trim, "accent": accent}

    def _apply_building_state_overlays(
        self,
        sprite: pygame.Surface,
        *,
        building_type: str,
        level: int,
        active: bool,
        occupancy_ratio: float,
        variant_id: int,
        district_identity: str,
        prosperity_score: float,
        material_style: str,
        biome_type: str,
        construction_progress: float,
        wear: float,
        building_age: float,
    ) -> pygame.Surface:
        overlayed = sprite.copy()
        width, height = overlayed.get_size()
        district_accent, district_style = self._district_building_palette(district_identity)
        material_colors = self._materialized_building_colors(
            get_building_recipe(building_type),
            material_style=material_style,
            biome_type=biome_type,
            wear=wear,
        )
        tint_layer = pygame.Surface((width, height), pygame.SRCALPHA)
        tint_layer.fill((*mix_color(material_colors["wall"], material_colors["roof"], 0.3), 32))
        overlayed.blit(tint_layer, (0, 0))
        trim_alpha = 74 if district_style in {"footpath", "mixed"} else 92
        if district_style == "furrows":
            for x in range(2 + (variant_id % 2), max(3, width - 2), max(4, width // 5)):
                pygame.draw.line(overlayed, (*district_accent, 64), (x, height - 5), (x, height - 2), 1)
        elif district_style == "yard":
            pygame.draw.rect(overlayed, (*district_accent, trim_alpha), (2, height - 6, max(4, width - 4), 3), border_radius=2)
        elif district_style == "ring":
            pygame.draw.arc(overlayed, (*district_accent, 88), (max(1, width // 5), height - 10, max(6, width - (width // 2)), 8), 0.0, 3.14, 1)
        else:
            pygame.draw.rect(overlayed, (*district_accent, trim_alpha), (max(1, width // 5), height - 4, max(4, width - (width // 2)), 2), border_radius=1)

        # Subtle, deterministic clutter to break up repeated silhouettes.
        warm_lit = active or occupancy_ratio > 0.0
        door_color = (88, 58, 44)
        if building_type == "house":
            door_w = max(3, width // 7)
            door_h = max(5, height // 5)
            door_x = max(2, (width // 2) - (door_w // 2) + ((variant_id % 3) - 1) * max(1, width // 10))
            door_y = height - door_h - max(3, height // 8)
            pygame.draw.rect(overlayed, darken(door_color, 0.15), (door_x, door_y, door_w, door_h))
            if variant_id % 2 == 0:
                pygame.draw.rect(overlayed, (94, 76, 62, 170), (max(2, width - 8), max(3, height // 6), 2, max(5, height // 5)))
            if prosperity_score > 0.65:
                pygame.draw.rect(overlayed, (*district_accent, 136), (max(2, width // 7), height - 8, max(3, width // 6), 3))
        elif building_type == "storage":
            crate_color = mix_color((118, 86, 61), district_accent, 0.12)
            pygame.draw.rect(overlayed, (*crate_color, 180), (max(2, width - 9), height - 10, max(4, width // 5), max(3, height // 9)))
        elif building_type == "farm":
            hay_color = mix_color((194, 182, 96), district_accent, 0.15)
            pygame.draw.rect(overlayed, (*hay_color, 180), (max(2, width - 8), max(3, height // 2), max(4, width // 6), max(3, height // 8)))
        elif building_type == "workshop":
            vent_x = max(2, width - 7 - (variant_id % 3))
            pygame.draw.rect(overlayed, (86, 70, 58, 185), (vent_x, max(2, height // 7), 2, max(5, height // 4)))
            if warm_lit:
                pygame.draw.rect(overlayed, (255, 177, 104, 150), (vent_x - 1, max(1, height // 9), 4, 3))
        elif building_type == "shrine":
            pygame.draw.circle(overlayed, (*district_accent, 140), (width // 2, max(4, height // 3)), max(2, width // 10))
            if prosperity_score > 0.7:
                pygame.draw.rect(overlayed, (*lighten(district_accent, 0.12), 150), (max(2, width // 2 - 1), max(2, height // 8), 2, max(5, height // 7)))
        elif building_type == "well":
            pygame.draw.line(overlayed, (118, 98, 82, 180), (width // 2, max(4, height // 4)), (width // 2, max(6, height // 2)), 1)
            pygame.draw.circle(overlayed, (190, 170, 140, 180), (max(4, width // 2 + 4), max(5, height // 2)), max(1, width // 14))
        elif building_type == "hospital":
            cross_color = (232, 96, 96)
            cx, cy = width // 2, max(5, height // 2)
            pygame.draw.rect(overlayed, cross_color, (cx - 1, cy - 4, 3, 9))
            pygame.draw.rect(overlayed, cross_color, (cx - 4, cy - 1, 9, 3))
        elif building_type == "school":
            flag_x = max(2, width - 8)
            pygame.draw.rect(overlayed, (92, 82, 74, 170), (flag_x, max(2, height // 6), 1, max(6, height // 3)))
            pygame.draw.polygon(
                overlayed,
                (*mix_color((246, 214, 132), district_accent, 0.25), 180),
                [(flag_x + 1, max(2, height // 6)), (flag_x + 7, max(4, height // 5)), (flag_x + 1, max(6, height // 4))],
            )
        elif building_type == "watchtower":
            beacon = (255, 208, 122) if warm_lit else lighten(district_accent, 0.05)
            pygame.draw.circle(overlayed, (*beacon, 190), (width // 2, max(4, height // 6)), max(2, width // 10))
        elif building_type == "market":
            awning = mix_color((220, 98, 88), district_accent, 0.18)
            awning_y = max(4, height // 3)
            stripe_w = max(3, width // 7)
            for index in range(3):
                pygame.draw.rect(
                    overlayed,
                    (*(awning if index % 2 == 0 else lighten(awning, 0.28)), 150),
                    (max(2, width // 6) + index * stripe_w, awning_y, stripe_w, max(3, height // 10)),
                )

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
            if level > 2:
                pygame.draw.rect(overlayed, (255, 230, 165), (width - 12, 3, 3, 3))
        if prosperity_score > 0.82:
            pennant = pygame.Surface((max(4, width // 4), max(4, height // 5)), pygame.SRCALPHA)
            pygame.draw.polygon(
                pennant,
                (*lighten(district_accent, 0.12), 150),
                [(0, 0), (pennant.get_width() - 1, pennant.get_height() // 2), (0, pennant.get_height() - 1)],
            )
            overlayed.blit(pennant, (max(1, width // 2 - 1), max(2, height // 5)))
        if wear > 0.18:
            crack_color = darken(material_colors["trim"], 0.28)
            for index in range(max(1, min(4, int(wear * 5)))):
                start_x = max(2, int(width * (0.22 + ((variant_id + index) % 5) * 0.13)))
                start_y = max(2, int(height * (0.28 + index * 0.12)))
                pygame.draw.line(
                    overlayed,
                    (*crack_color, 160),
                    (start_x, start_y),
                    (max(1, start_x - 2 + (index % 3)), min(height - 2, start_y + 3 + index)),
                    1,
                )
        if building_age > 180.0 and prosperity_score > 0.58 and building_type in {"house", "shrine", "school"}:
            vine = mix_color(district_accent, (102, 142, 94), 0.38)
            for index in range(1 + (variant_id % 2)):
                vine_x = max(2, width // 5 + index * max(3, width // 6))
                pygame.draw.line(overlayed, (*vine, 120), (vine_x, max(3, height // 4)), (vine_x - 1, height - 4), 1)
                pygame.draw.circle(overlayed, (*vine, 132), (vine_x, min(height - 5, height // 2 + index * 5)), 2)
        progress = max(0.0, min(1.0, construction_progress))
        if progress < 0.995:
            coverage_top = max(0, int(height * (1.0 - progress)))
            unfinished = pygame.Surface((width, max(1, coverage_top + 2)), pygame.SRCALPHA)
            unfinished.fill((82, 66, 54, 118))
            overlayed.blit(unfinished, (0, 0))
            scaffold = mix_color(material_colors["trim"], (170, 132, 88), 0.28)
            scaffold_y = max(4, height // 3)
            for x in (max(3, width // 4), max(6, width // 2), max(8, width - width // 4)):
                pygame.draw.line(overlayed, (*scaffold, 190), (x, scaffold_y), (x, height - 2), 1)
            pygame.draw.line(overlayed, (*scaffold, 190), (2, scaffold_y), (width - 2, scaffold_y), 1)
            for plank_y in range(scaffold_y + 4, height - 2, max(5, height // 6)):
                pygame.draw.line(overlayed, (*scaffold, 120), (3, plank_y), (width - 3, plank_y), 1)
        return overlayed

    def _draw_building_lot_fence(
        self,
        surface: pygame.Surface,
        *,
        fence_style: str,
        base_color: tuple[int, int, int],
        accent_color: tuple[int, int, int],
    ) -> None:
        if fence_style == "open":
            return
        width, height = surface.get_size()
        left, top = 2, 2
        right, bottom = width - 3, height - 3
        gate_half = max(4, width // 10)
        gate_min = max(left + 3, width // 2 - gate_half)
        gate_max = min(right - 3, width // 2 + gate_half)
        if fence_style == "hedge":
            hedge = mix_color(base_color, (94, 132, 86), 0.42)
            for x in range(left, right, max(4, width // 8)):
                if gate_min <= x <= gate_max:
                    continue
                pygame.draw.rect(surface, (*hedge, 200), (x, top, max(3, width // 10), 2), border_radius=1)
                pygame.draw.rect(surface, (*hedge, 200), (x, bottom - 1, max(3, width // 10), 2), border_radius=1)
            for y in range(top + 2, bottom - 1, max(4, height // 7)):
                pygame.draw.rect(surface, (*hedge, 200), (left, y, 2, max(3, height // 10)), border_radius=1)
                pygame.draw.rect(surface, (*hedge, 200), (right - 1, y, 2, max(3, height // 10)), border_radius=1)
            return
        if fence_style == "low_stone":
            stone = mix_color(base_color, (156, 154, 146), 0.28)
            for x in range(left, right, max(4, width // 9)):
                if gate_min <= x <= gate_max:
                    continue
                pygame.draw.rect(surface, (*stone, 200), (x, top, max(3, width // 11), 2))
                pygame.draw.rect(surface, (*stone, 200), (x, bottom - 1, max(3, width // 11), 2))
            for y in range(top + 2, bottom - 1, max(4, height // 8)):
                pygame.draw.rect(surface, (*stone, 200), (left, y, 2, max(3, height // 11)))
                pygame.draw.rect(surface, (*stone, 200), (right - 1, y, 2, max(3, height // 11)))
            return
        if fence_style == "palisade":
            stake = darken(base_color, 0.08)
            for x in range(left, right, max(3, width // 12)):
                if gate_min <= x <= gate_max:
                    continue
                pygame.draw.line(surface, (*stake, 210), (x, top), (x, top + 4), 1)
                pygame.draw.line(surface, (*stake, 210), (x, bottom - 4), (x, bottom), 1)
            pygame.draw.line(surface, (*accent_color, 150), (left, top + 3), (right, top + 3), 1)
            pygame.draw.line(surface, (*accent_color, 150), (left, bottom - 3), (right, bottom - 3), 1)
            pygame.draw.line(surface, (*accent_color, 150), (left + 3, top), (left + 3, bottom), 1)
            pygame.draw.line(surface, (*accent_color, 150), (right - 3, top), (right - 3, bottom), 1)
            return
        rail = darken(base_color, 0.06)
        for x in range(left, right, max(4, width // 9)):
            if gate_min <= x <= gate_max:
                continue
            pygame.draw.line(surface, (*rail, 200), (x, top), (x, top + 3), 1)
            pygame.draw.line(surface, (*rail, 200), (x, bottom - 3), (x, bottom), 1)
        pygame.draw.line(surface, (*accent_color, 140), (left, top + 2), (right, top + 2), 1)
        pygame.draw.line(surface, (*accent_color, 140), (left, bottom - 2), (gate_min, bottom - 2), 1)
        pygame.draw.line(surface, (*accent_color, 140), (gate_max, bottom - 2), (right, bottom - 2), 1)
        pygame.draw.line(surface, (*accent_color, 140), (left + 2, top), (left + 2, bottom), 1)
        pygame.draw.line(surface, (*accent_color, 140), (right - 2, top), (right - 2, bottom), 1)

    def _draw_building_lot_attachment(
        self,
        surface: pygame.Surface,
        *,
        attachment: str,
        index: int,
        variant_id: int,
        wall_color: tuple[int, int, int],
        trim_color: tuple[int, int, int],
        accent_color: tuple[int, int, int],
        foliage_color: tuple[int, int, int],
        prosperity_score: float,
        occupancy_ratio: float,
    ) -> None:
        width, height = surface.get_size()
        base_x = 4 + ((variant_id * 7) + index * 11) % max(6, width - 12)
        base_y = max(4, height // 2 + ((variant_id + index * 3) % max(3, height // 4)))
        if attachment == "shed":
            body = pygame.Rect(base_x, max(4, height // 3), max(7, width // 6), max(5, height // 5))
            roof = [(body.left, body.top), (body.centerx, body.top - 3), (body.right, body.top)]
            pygame.draw.polygon(surface, darken(trim_color, 0.08), roof)
            pygame.draw.rect(surface, (*wall_color, 190), body)
        elif attachment == "laundry" and occupancy_ratio > 0.0:
            pole_y = max(4, height // 3)
            pygame.draw.line(surface, (*trim_color, 180), (base_x, pole_y), (base_x + max(8, width // 6), pole_y + 1), 1)
            for offset in (2, 5, 8):
                cloth = mix_color(accent_color, (226, 214, 178), 0.2 + offset * 0.01)
                pygame.draw.rect(surface, (*cloth, 170), (base_x + offset, pole_y + 1, 2, 3))
        elif attachment == "crates":
            crate = mix_color(trim_color, (138, 102, 72), 0.18)
            for offset in (0, 4):
                pygame.draw.rect(surface, (*crate, 190), (base_x + offset, min(height - 6, base_y), 3, 3))
        elif attachment == "lean_to":
            pygame.draw.polygon(
                surface,
                (*darken(trim_color, 0.08), 180),
                [(base_x, base_y), (base_x + 7, base_y - 4), (base_x + 10, base_y)],
            )
            pygame.draw.line(surface, (*wall_color, 170), (base_x + 1, base_y), (base_x + 1, min(height - 2, base_y + 4)), 1)
            pygame.draw.line(surface, (*wall_color, 170), (base_x + 8, base_y), (base_x + 8, min(height - 2, base_y + 4)), 1)
        elif attachment == "hay":
            pygame.draw.ellipse(surface, (*mix_color(accent_color, (192, 170, 94), 0.28), 190), (base_x, base_y, 6, 4))
        elif attachment == "trough":
            pygame.draw.rect(surface, (*trim_color, 180), (base_x, base_y, max(6, width // 7), 2))
            pygame.draw.rect(surface, (*accent_color, 160), (base_x + 1, base_y + 1, max(4, width // 8), 1))
        elif attachment == "forge_stack":
            pygame.draw.rect(surface, (*trim_color, 190), (base_x, max(3, height // 4 - 6), 3, 7))
            pygame.draw.circle(surface, (*accent_color, 170), (base_x + 1, max(2, height // 4 - 1)), 2)
        elif attachment == "lanterns":
            for offset in (0, 6):
                pygame.draw.circle(surface, (*lighten(accent_color, 0.14), 180), (base_x + offset, max(4, height // 4)), 2)
        elif attachment == "stones":
            stone = mix_color(trim_color, (158, 156, 148), 0.34)
            for offset in (0, 5, 9):
                pygame.draw.ellipse(surface, (*stone, 180), (base_x + offset, min(height - 5, base_y + offset // 4), 4, 2))
        elif attachment == "buckets":
            for offset in (0, 5):
                pygame.draw.circle(surface, (*accent_color, 170), (base_x + offset, min(height - 4, base_y)), 2)
                pygame.draw.line(surface, (*trim_color, 160), (base_x + offset - 1, min(height - 4, base_y - 2)), (base_x + offset + 1, min(height - 4, base_y - 2)), 1)
        elif attachment == "herbs":
            bed = mix_color(foliage_color, accent_color, 0.12)
            for offset in (0, 6):
                pygame.draw.rect(surface, (*darken(trim_color, 0.08), 150), (base_x + offset, base_y, 4, 3))
                pygame.draw.rect(surface, (*bed, 180), (base_x + offset, base_y - 1, 4, 2))
        elif attachment == "beds":
            for offset in (0, 7):
                frame = pygame.Rect(base_x + offset, max(4, base_y - 2), 5, 3)
                pygame.draw.rect(surface, (*trim_color, 170), frame, 1)
                pygame.draw.rect(surface, (*lighten(wall_color, 0.2), 150), frame.inflate(-2, -1))
        elif attachment == "bench":
            pygame.draw.line(surface, (*trim_color, 180), (base_x, base_y), (base_x + 8, base_y), 2)
            pygame.draw.line(surface, (*trim_color, 150), (base_x + 1, base_y), (base_x + 1, base_y + 3), 1)
            pygame.draw.line(surface, (*trim_color, 150), (base_x + 7, base_y), (base_x + 7, base_y + 3), 1)
        elif attachment == "tree":
            pygame.draw.rect(surface, (*trim_color, 170), (base_x + 2, max(4, base_y - 2), 2, 5))
            pygame.draw.circle(surface, (*foliage_color, 190), (base_x + 3, max(4, base_y - 3)), 4)
        elif attachment == "fire":
            ember = mix_color(accent_color, (244, 160, 92), 0.36)
            pygame.draw.circle(surface, (*ember, 190), (base_x + 2, base_y), 3)
            pygame.draw.line(surface, (*trim_color, 170), (base_x - 1, base_y + 2), (base_x + 5, base_y - 1), 1)
            pygame.draw.line(surface, (*trim_color, 170), (base_x - 1, base_y - 1), (base_x + 5, base_y + 2), 1)
        elif attachment == "stalls":
            awning = mix_color(accent_color, wall_color, 0.1)
            span = max(10, width // 4)
            for offset in (0, span + 2):
                pygame.draw.rect(surface, (*trim_color, 160), (base_x + offset, base_y, span, 2))
                for stripe in range(3):
                    stripe_color = awning if stripe % 2 == 0 else lighten(awning, 0.22)
                    pygame.draw.rect(surface, (*stripe_color, 180), (base_x + offset + stripe * max(2, span // 3), base_y - 3, max(2, span // 3), 3))
        elif attachment == "awning":
            awning = mix_color(accent_color, (236, 216, 174), 0.14)
            top = max(4, height // 3)
            pygame.draw.rect(surface, (*trim_color, 155), (base_x, top, max(10, width // 4), 2))
            for stripe in range(4):
                shade = awning if stripe % 2 == 0 else lighten(awning, 0.24)
                pygame.draw.rect(surface, (*shade, 170), (base_x + stripe * 3, top - 4, 3, 4))
        if prosperity_score > 0.7 and attachment in {"garden", "tree", "herbs", "stalls"}:
            pygame.draw.circle(surface, (*lighten(accent_color, 0.2), 140), (min(width - 4, base_x + 3), max(4, base_y - 4)), 2)

    def _building_lot_source(
        self,
        *,
        building_type: str,
        variant_id: int,
        district_identity: str,
        prosperity_score: float,
        material_style: str,
        biome_type: str,
        construction_progress: float,
        wear: float,
        occupancy_ratio: float,
    ) -> pygame.Surface:
        recipe = get_building_recipe(building_type)
        lot_profile = get_building_lot_profile(building_type)
        lot_tiles_w, lot_tiles_h = building_lot_tile_span(building_type)
        width = max(24, lot_tiles_w * SOURCE_TILE_SIZE)
        height = max(24, lot_tiles_h * SOURCE_TILE_SIZE)
        source = _surface((width, height))
        district_accent, district_style = self._district_building_palette(district_identity)
        material_colors = self._materialized_building_colors(
            recipe,
            material_style=material_style,
            biome_type=biome_type,
            wear=wear,
        )
        wall = material_colors["wall"]
        trim = material_colors["trim"]
        accent = material_colors["accent"]
        ground = mix_color(wall, district_accent, 0.16)
        path = mix_color(trim, district_accent, 0.1)
        foliage = mix_color(district_accent, (102, 142, 88), 0.42)
        if biome_type == "desert":
            ground = mix_color(ground, (196, 168, 118), 0.22)
            foliage = mix_color(foliage, (166, 150, 94), 0.28)
        elif biome_type in {"snow", "tundra"}:
            ground = mix_color(ground, (202, 210, 220), 0.3)
        elif biome_type == "swamp":
            ground = mix_color(ground, (112, 124, 102), 0.24)
        parcel = pygame.Rect(2, 2, width - 4, height - 4)
        inner = parcel.inflate(-6, -6)
        pygame.draw.ellipse(source, (*darken(ground, 0.2), 56), parcel.inflate(-2, -4))
        if lot_profile.ground_style == "field":
            pygame.draw.rect(source, (*mix_color(ground, (148, 122, 84), 0.22), 188), parcel, border_radius=3)
            for x in range(inner.left, inner.right, max(5, width // 10)):
                pygame.draw.line(source, (*darken(accent, 0.18), 128), (x, inner.top), (x, inner.bottom), 1)
        elif lot_profile.ground_style == "precinct":
            pygame.draw.rect(source, (*lighten(ground, 0.06), 176), parcel, border_radius=5)
            tile = mix_color(path, (194, 190, 178), 0.2)
            for x in range(inner.left, inner.right, max(5, width // 9)):
                pygame.draw.line(source, (*tile, 120), (x, inner.top), (x, inner.bottom), 1)
            for y in range(inner.top, inner.bottom, max(5, height // 8)):
                pygame.draw.line(source, (*tile, 120), (inner.left, y), (inner.right, y), 1)
            pygame.draw.circle(source, (*lighten(accent, 0.18), 110), parcel.center, max(4, min(width, height) // 7), 1)
        elif lot_profile.ground_style == "bazaar":
            pygame.draw.rect(source, (*mix_color(ground, accent, 0.08), 184), parcel, border_radius=4)
            rug = mix_color(accent, district_accent, 0.14)
            for y in range(inner.top + 2, inner.bottom, max(5, height // 7)):
                pygame.draw.rect(source, (*(rug if (y // 2) % 2 == 0 else lighten(rug, 0.16)), 88), (inner.left, y, inner.width, 2))
        else:
            pygame.draw.rect(source, (*lighten(ground, 0.04), 180), parcel, border_radius=5)
            if lot_profile.ground_style in {"garden", "courtyard", "commons", "watch_post"}:
                path_width = max(5, width // 7)
                path_rect = pygame.Rect(width // 2 - path_width // 2, height // 2, path_width, max(6, height // 2 - 4))
                pygame.draw.rect(source, (*path, 110), path_rect, border_radius=2)
            if lot_profile.ground_style in {"garden", "yard", "commons"}:
                for index in range(3 + (variant_id % 2)):
                    patch_x = 5 + ((variant_id + index * 5) * 9) % max(6, width - 14)
                    patch_y = 5 + ((variant_id + index * 3) * 7) % max(6, height - 14)
                    pygame.draw.ellipse(source, (*foliage, 96), (patch_x, patch_y, 7, 4))
            if lot_profile.ground_style == "watch_post":
                ring = mix_color(trim, (164, 124, 84), 0.18)
                pygame.draw.arc(source, (*ring, 130), (inner.left, inner.top + 3, inner.width, inner.height - 6), 0.0, 3.14, 1)

        if district_style == "furrows" and lot_profile.ground_style != "field":
            for x in range(inner.left, inner.right, max(6, width // 10)):
                pygame.draw.line(source, (*district_accent, 48), (x, inner.top), (x, inner.bottom), 1)
        elif district_style == "ring":
            pygame.draw.circle(source, (*district_accent, 52), parcel.center, max(4, min(width, height) // 4), 1)

        self._draw_building_lot_fence(
            source,
            fence_style=lot_profile.fence_style,
            base_color=trim,
            accent_color=district_accent,
        )

        for index, attachment in enumerate(lot_profile.attachments):
            self._draw_building_lot_attachment(
                source,
                attachment=attachment,
                index=index,
                variant_id=variant_id,
                wall_color=wall,
                trim_color=trim,
                accent_color=accent,
                foliage_color=foliage,
                prosperity_score=prosperity_score,
                occupancy_ratio=occupancy_ratio,
            )

        if prosperity_score > 0.62 and construction_progress >= 0.995:
            flower = mix_color(district_accent, (238, 210, 148), 0.22)
            for index in range(2 + (variant_id % 3)):
                bloom_x = 6 + ((variant_id + index * 4) * 7) % max(6, width - 12)
                bloom_y = max(height // 2, height - 10 - (index % 2) * 3)
                pygame.draw.circle(source, (*flower, 140), (bloom_x, bloom_y), 2)
        if wear > 0.2:
            bare = mix_color(ground, (110, 92, 76), min(0.34, wear * 0.4))
            for index in range(max(1, min(4, int(wear * 6)))):
                patch_x = 5 + ((variant_id + index) * 11) % max(6, width - 12)
                patch_y = 5 + ((variant_id + index * 2) * 5) % max(6, height - 12)
                pygame.draw.ellipse(source, (*bare, 100), (patch_x, patch_y, 6, 4))
        progress = max(0.0, min(1.0, construction_progress))
        if progress < 0.995:
            trench = mix_color(trim, (122, 92, 66), 0.24)
            coverage = pygame.Surface((width, height), pygame.SRCALPHA)
            coverage.fill((70, 56, 42, 42))
            source.blit(coverage, (0, 0))
            for x in range(inner.left, inner.right, max(5, width // 9)):
                pygame.draw.line(source, (*trench, 165), (x, inner.top + 2), (x + 2, inner.bottom - 2), 1)
            for offset in (0, max(6, width // 6)):
                pile_x = max(4, width // 2 - width // 8 + offset - max(6, width // 8))
                pygame.draw.ellipse(source, (*mix_color(accent, trim, 0.22), 180), (pile_x, height - 8, max(6, width // 8), 4))
        return source

    def get_building_lot_sprite(
        self,
        *,
        building_type: str,
        variant_id: int,
        district_identity: str,
        prosperity_score: float,
        material_style: str,
        biome_type: str,
        construction_progress: float,
        wear: float,
        occupancy_ratio: float,
        target_size: tuple[int, int],
    ) -> pygame.Surface:
        progress_bucket = int(round(max(0.0, min(1.0, construction_progress)) * 20))
        wear_bucket = int(round(max(0.0, min(1.0, wear)) * 10))
        cache_key = (
            "building_lot",
            building_type,
            variant_id,
            district_identity,
            round(prosperity_score, 2),
            str(material_style or ""),
            str(biome_type or ""),
            progress_bucket,
            wear_bucket,
            round(occupancy_ratio, 2),
            target_size,
        )
        if cache_key in self._cache:
            return self._cache[cache_key]
        source = self._building_lot_source(
            building_type=building_type,
            variant_id=variant_id,
            district_identity=district_identity,
            prosperity_score=prosperity_score,
            material_style=material_style,
            biome_type=biome_type,
            construction_progress=construction_progress,
            wear=wear,
            occupancy_ratio=occupancy_ratio,
        )
        self._cache[cache_key] = _scale(source, target_size)
        return self._cache[cache_key]

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
        
        import random
        rng = random.Random(hash(biome_type + str(season_name)) + variant * 37)
        
        for _ in range(12):
            x, y = rng.randint(0, SOURCE_TILE_SIZE - 2), rng.randint(0, SOURCE_TILE_SIZE - 2)
            c = rng.choice([recipe.light, recipe.shadow, recipe.mid])
            _px(source, c, x, y, rng.randint(1, 2), rng.randint(1, 2))

        if biome_type == "plains":
            for _ in range(6):
                x, y = rng.randint(1, 13), rng.randint(2, 12)
                _px(source, recipe.light, x, y, 1, 2)
                _px(source, recipe.mid, x + 1, y + 1, 1, 2)
            if variant % 2 == 0:
                _px(source, recipe.accent, rng.randint(2, 12), rng.randint(2, 12))
        elif biome_type == "forest":
            for _ in range(8):
                x, y = rng.randint(1, 12), rng.randint(1, 10)
                _px(source, recipe.mid, x, y, rng.randint(3, 5), rng.randint(2, 4))
                _px(source, darken(recipe.shadow, 0.06), x + 1, y + 1, 2, rng.randint(2, 3))
                if rng.random() > 0.5:
                    _px(source, recipe.light, x, y, 2, 1)
            for _ in range(2):
                x, y = rng.randint(2, 11), rng.randint(2, 11)
                _px(source, recipe.accent, x, y, 2, 3)
        elif biome_type == "mountains":
            for _ in range(4):
                x = rng.randint(0, 8)
                y = rng.randint(2, 8)
                pygame.draw.polygon(source, recipe.mid, [(x, y + 6), (x + 4, y), (x + 8, y + 6), (x + 4, y + 8)])
                pygame.draw.lines(source, recipe.light, False, [(x, y + 6), (x + 4, y), (x + 8, y + 6)], 1)
                _px(source, recipe.shadow, x + 4, y + 2, 2, 4)
        elif biome_type == "desert":
            for _ in range(5):
                y = rng.randint(2, 13)
                x = rng.randint(0, 8)
                pygame.draw.line(source, recipe.light, (x, y), (x + rng.randint(4, 7), y - rng.randint(1, 2)), 1)
            for _ in range(2):
                _px(source, recipe.accent, rng.randint(2, 12), rng.randint(2, 12), 2, 2)
        elif biome_type == "snow":
            for _ in range(8):
                _px(source, recipe.light, rng.randint(1, 14), rng.randint(1, 14), 2, 1)
            for _ in range(2):
                pygame.draw.arc(source, mix_color(recipe.shadow, recipe.moisture, 0.3), (rng.randint(0, 6), rng.randint(2, 10), 6, 4), 0.0, 3.14, 1)
        elif biome_type == "swamp":
            for _ in range(3):
                pygame.draw.ellipse(source, recipe.moisture, (rng.randint(1, 8), rng.randint(1, 8), rng.randint(4, 7), rng.randint(3, 5)))
            for _ in range(4):
                _px(source, recipe.accent, rng.randint(2, 13), rng.randint(2, 13), 1, rng.randint(2, 4))
        elif biome_type == "taiga":
            for _ in range(6):
                x, y = rng.randint(1, 10), rng.randint(1, 10)
                pygame.draw.polygon(source, recipe.mid, [(x, y + 5), (x + 2, y), (x + 4, y + 5)])
                _px(source, recipe.light, x + 2, y + 1, 1, 3)
            for _ in range(2):
                _px(source, recipe.shadow, rng.randint(1, 6), rng.randint(8, 13), rng.randint(4, 8), 2)
        elif biome_type == "tundra":
            for _ in range(4):
                x = rng.randint(1, 8)
                y = rng.randint(2, 10)
                pygame.draw.line(source, recipe.light, (x, y), (x + 4, y + rng.randint(-2, 2)), 1)
            for _ in range(3):
                _px(source, recipe.accent, rng.randint(2, 13), rng.randint(2, 13), 2, 1)

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
        import random
        rng = random.Random(hash(source_biome + target_biome + edge))
        
        for i in range(SOURCE_TILE_SIZE):
            depth = rng.randint(2, 5)
            if target_biome in {"desert", "snow", "water", "swamp"}:
                depth += rng.randint(0, 2)
            for d in range(depth):
                alpha = 200 - (d * 30)
                color = _alpha(target_recipe.mid if d > depth // 2 else target_recipe.shadow, max(0, alpha))
                light = _alpha(target_recipe.light, max(0, alpha - 40))
                
                if edge == "north":
                    _px(source, color, i, d, 1, 1)
                    if d == depth - 1: _px(source, light, i, d + 1, 1, 1)
                elif edge == "south":
                    _px(source, color, i, SOURCE_TILE_SIZE - 1 - d, 1, 1)
                    if d == depth - 1: _px(source, light, i, SOURCE_TILE_SIZE - 2 - d, 1, 1)
                elif edge == "west":
                    _px(source, color, d, i, 1, 1)
                    if d == depth - 1: _px(source, light, d + 1, i, 1, 1)
                elif edge == "east":
                    _px(source, color, SOURCE_TILE_SIZE - 1 - d, i, 1, 1)
                    if d == depth - 1: _px(source, light, SOURCE_TILE_SIZE - 2 - d, i, 1, 1)

        self._cache[cache_key] = _scale(source, (tile_size, tile_size))
        return self._cache[cache_key]

    def get_district_overlay(self, zone_type: str, tile_size: int, variant: int = 0) -> pygame.Surface:
        cache_key = ("district", zone_type, tile_size, variant)
        if cache_key in self._cache:
            return self._cache[cache_key]
        overlay_type = get_zone_overlay_type(zone_type)
        file_surface = self._load_file_surface(
            os.path.join("tilesets", "overlays", f"{overlay_type}_{variant % 3}.png"),
            (tile_size, tile_size),
        )
        if file_surface is not None:
            self._cache[cache_key] = file_surface
            return file_surface
        source = _surface((SOURCE_TILE_SIZE, SOURCE_TILE_SIZE))
        overlay = DISTRICT_OVERLAYS.get(overlay_type, DISTRICT_OVERLAYS["mixed"])
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

    def _building_source(
        self,
        building_type: str,
        level: int,
        active: bool,
        occupancy_ratio: float,
        material_style: str,
        biome_type: str,
        wear: float,
    ) -> pygame.Surface:
        recipe = get_building_recipe(building_type)
        material_colors = self._materialized_building_colors(
            recipe,
            material_style=material_style,
            biome_type=biome_type,
            wear=wear,
        )
        wall = material_colors["wall"]
        roof = material_colors["roof"]
        trim = material_colors["trim"]
        accent = material_colors["accent"]
        source = _surface(recipe.source_size)
        width, height = recipe.source_size
        base_y = height - 10
        if building_type == "house":
            pygame.draw.polygon(source, roof, [(3, 16), (width // 2, 2), (width - 4, 16)])
            pygame.draw.polygon(source, lighten(roof, 0.16), [(4, 16), (width // 2, 4), (width // 2, 16)])
            _px(source, wall, 6, 16, width - 12, 14)
            _px(source, trim, 13, 22, 6, 8)
            window = accent if active or occupancy_ratio > 0 else darken(wall, 0.12)
            _px(source, window, 9, 20, 4, 4)
            _px(source, window, 19, 20, 4, 4)
        elif building_type == "storage":
            _px(source, roof, 4, 9, width - 8, 6)
            _px(source, wall, 5, 15, width - 10, 13)
            _px(source, trim, 8, 18, width - 16, 8)
            _px(source, accent, 8, 28, 5, 3)
            _px(source, accent, 19, 26, 6, 5)
        elif building_type == "farm":
            _px(source, darken(wall, 0.14), 2, 18, width - 4, 12)
            for x in (5, 10, 15, 20, 25):
                _px(source, accent, x, 20, 1, 8)
            _px(source, trim, 23, 9, 5, 9)
            _px(source, lighten(roof, 0.1), 21, 7, 9, 4)
        elif building_type == "workshop":
            pygame.draw.polygon(source, roof, [(4, 15), (13, 6), (width - 5, 15), (width - 5, 17), (4, 17)])
            _px(source, wall, 5, 17, width - 10, 12)
            _px(source, trim, 8, 20, 7, 9)
            _px(source, darken(trim, 0.2), width - 11, 8, 3, 9)
            if active:
                _px(source, accent, width - 11, 6, 3, 2)
                _px(source, _alpha(lighten(accent, 0.2), 140), width - 10, 3, 2, 3)
        elif building_type == "shrine":
            _px(source, trim, 8, 11, width - 16, 18)
            _px(source, wall, 12, 6, width - 24, 7)
            pygame.draw.arc(source, accent, (8, 6, width - 16, 18), 3.14, 6.28, 2)
            _px(source, accent if active else lighten(accent, 0.12), width // 2 - 2, 17, 4, 6)
        elif building_type == "well":
            pygame.draw.ellipse(source, trim, (6, 13, width - 12, 9))
            pygame.draw.ellipse(source, accent, (8, 15, width - 16, 5))
            _px(source, roof, 11, 4, 2, 10)
            _px(source, roof, width - 13, 4, 2, 10)
            _px(source, roof, 10, 5, width - 20, 2)
        elif building_type == "hospital":
            _px(source, wall, 5, 12, width - 10, height - 18)
            _px(source, lighten(wall, 0.12), 8, 16, width - 16, height - 26)
            _px(source, trim, width // 2 - 2, 8, 4, height - 18)
            _px(source, trim, width // 2 - 8, 14, 16, 4)
            _px(source, accent, width // 2 - 1, 10, 2, height - 22)
            _px(source, accent, width // 2 - 6, 15, 12, 2)
        elif building_type == "school":
            pygame.draw.polygon(source, roof, [(6, 15), (width // 2, 6), (width - 6, 15)])
            _px(source, wall, 6, 15, width - 12, height - 20)
            for x in (10, width // 2 - 2, width - 14):
                _px(source, lighten(wall, 0.18), x, 20, 4, 6)
            _px(source, accent, width // 2 - 1, 10, 2, 8)
        elif building_type == "watchtower":
            _px(source, trim, width // 2 - 6, 14, 2, height - 18)
            _px(source, trim, width // 2 + 4, 14, 2, height - 18)
            _px(source, wall, width // 2 - 8, 10, 16, 8)
            _px(source, roof, width // 2 - 10, 8, 20, 3)
            _px(source, accent if active else lighten(accent, 0.08), width // 2 - 1, 5, 2, 3)
        elif building_type == "market":
            _px(source, wall, 5, 16, width - 10, height - 14)
            stripe_w = max(4, (width - 12) // 3)
            for index in range(3):
                stripe_color = roof if index % 2 == 0 else lighten(roof, 0.22)
                _px(source, stripe_color, 6 + index * stripe_w, 10, stripe_w - 1, 7)
            _px(source, trim, 8, 24, width - 16, 4)
        if level > 1:
            _px(source, lighten(accent, 0.18), width - 8, 3, 3, 3)
        if active and building_type in {"house", "shrine", "workshop"}:
            _px(source, _alpha(lighten(accent, 0.15), 120), 3, base_y - 7, width - 6, 2)
        return source

    def get_building_sprite(
        self,
        *,
        building_type: str,
        level: int,
        active: bool,
        occupancy_ratio: float,
        variant_id: int,
        district_identity: str,
        prosperity_score: float,
        material_style: str,
        biome_type: str,
        construction_progress: float,
        wear: float,
        building_age: float,
        target_size: tuple[int, int],
    ) -> pygame.Surface:
        progress_bucket = int(round(max(0.0, min(1.0, construction_progress)) * 20))
        wear_bucket = int(round(max(0.0, min(1.0, wear)) * 10))
        age_bucket = 1 if building_age >= 180.0 else 0
        cache_key = (
            "building",
            building_type,
            level,
            active,
            round(occupancy_ratio, 2),
            variant_id,
            district_identity,
            round(prosperity_score, 2),
            str(material_style or ""),
            str(biome_type or ""),
            progress_bucket,
            wear_bucket,
            age_bucket,
            target_size,
        )
        if cache_key in self._cache:
            return self._cache[cache_key]
        file_surface = self._load_file_surface(os.path.join("sprites", "buildings", f"{building_type}.png"), target_size)
        if file_surface is None:
            source = self._building_source(
                building_type,
                level,
                active,
                occupancy_ratio,
                material_style,
                biome_type,
                wear,
            )
            file_surface = _scale(self._add_shadow(source, skew=0.5, alpha=110), target_size)
        self._cache[cache_key] = self._apply_building_state_overlays(
            file_surface,
            building_type=building_type,
            level=level,
            active=active,
            occupancy_ratio=occupancy_ratio,
            variant_id=variant_id,
            district_identity=district_identity,
            prosperity_score=prosperity_score,
            material_style=material_style,
            biome_type=biome_type,
            construction_progress=construction_progress,
            wear=wear,
            building_age=building_age,
        )
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
