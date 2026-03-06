from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graphics.content import (
    BUILDING_FOOTPRINT_ART,
    DISTRICT_OVERLAYS,
    HAZARD_ART,
    NPC_ART,
    RESOURCE_ART,
    ROLE_PALETTES,
    SOURCE_RESOURCE_SIZE,
    SOURCE_THRONGLET_SIZE,
    SOURCE_TILE_SIZE,
    palette_for_biome_and_season,
)
from graphics.palette import darken, lighten, mix_color


ASSETS = ROOT / "assets"
SEASONS = ("spring", "summer", "autumn", "winter")
BIOMES = ("plains", "forest", "mountains", "desert", "snow", "swamp", "taiga", "tundra")
EDGES = ("north", "south", "west", "east")
ROLES = ("default", "gatherer", "builder", "explorer")
ANIMATIONS = ("idle", "walk", "gather", "build", "rest", "celebrate", "sick", "death")
FACINGS = ("down", "up", "left", "right")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_png(surface: pygame.Surface, path: Path) -> None:
    ensure_dir(path.parent)
    pygame.image.save(surface, str(path))


def px(surface: pygame.Surface, color, x: int, y: int, w: int = 1, h: int = 1) -> None:
    pygame.draw.rect(surface, color, (int(x), int(y), int(w), int(h)))


def surface(size: tuple[int, int]) -> pygame.Surface:
    return pygame.Surface(size, pygame.SRCALPHA)


def outlined_rect(surface_obj: pygame.Surface, fill, outline, rect: tuple[int, int, int, int]) -> None:
    pygame.draw.rect(surface_obj, outline, rect)
    inner = pygame.Rect(rect).inflate(-2, -2)
    if inner.w > 0 and inner.h > 0:
        pygame.draw.rect(surface_obj, fill, inner)


def line(surface_obj: pygame.Surface, color, points: list[tuple[int, int]]) -> None:
    if len(points) >= 2:
        pygame.draw.lines(surface_obj, color, False, points, 1)


def shade_rows(surf: pygame.Surface, top_color, bottom_color, strength: float = 0.35) -> None:
    height = surf.get_height()
    width = surf.get_width()
    for y in range(height):
        shade = y / max(1, height - 1)
        row = mix_color(top_color, bottom_color, shade * strength)
        px(surf, row, 0, y, width, 1)


def tufts(surf: pygame.Surface, points: list[tuple[int, int]], light, mid) -> None:
    for x, y in points:
        px(surf, light, x, y, 1, 2)
        px(surf, mid, x + 1, y + 1, 1, 2)


def gem(surf: pygame.Surface, primary, light, x: int, y: int) -> None:
    pygame.draw.polygon(surf, primary, [(x, y + 3), (x + 2, y), (x + 5, y + 3), (x + 2, y + 6)])
    px(surf, light, x + 2, y + 1, 1, 2)


def draw_tile(biome: str, season: str) -> pygame.Surface:
    recipe = palette_for_biome_and_season(biome, season)
    surf = surface((SOURCE_TILE_SIZE, SOURCE_TILE_SIZE))
    surf.fill(recipe.base)
    shade_rows(surf, mix_color(recipe.light, recipe.base, 0.35), recipe.shadow, 0.32)
    px(surf, lighten(recipe.light, 0.08), 0, 0, SOURCE_TILE_SIZE, 1)
    px(surf, darken(recipe.shadow, 0.08), 0, SOURCE_TILE_SIZE - 1, SOURCE_TILE_SIZE, 1)
    if biome == "plains":
        px(surf, mix_color(recipe.mid, recipe.shadow, 0.15), 0, 11, SOURCE_TILE_SIZE, 3)
        tufts(surf, [(1, 11), (4, 8), (7, 10), (10, 6), (13, 9)], lighten(recipe.light, 0.08), recipe.accent)
        px(surf, lighten(recipe.mid, 0.15), 2, 13, 4, 1)
        px(surf, lighten(recipe.mid, 0.15), 9, 12, 5, 1)
        px(surf, recipe.accent, 12, 4, 1, 1)
        px(surf, lighten(recipe.light, 0.12), 13, 4, 1, 1)
        line(surf, darken(recipe.shadow, 0.08), [(0, 10), (3, 9), (7, 10), (11, 9), (15, 10)])
    elif biome == "forest":
        clusters = [(1, 4), (5, 2), (9, 3), (12, 7), (6, 9)]
        for x, y in clusters:
            pygame.draw.circle(surf, darken(recipe.mid, 0.06), (x + 2, y + 2), 2)
            pygame.draw.circle(surf, recipe.mid, (x + 1, y + 1), 2)
            px(surf, lighten(recipe.light, 0.08), x + 1, y, 1, 1)
        for x in (3, 7, 12):
            px(surf, darken(recipe.shadow, 0.1), x, 11, 1, 4)
            px(surf, recipe.accent, x + 1, 11, 1, 4)
        px(surf, darken(recipe.shadow, 0.12), 0, 13, 16, 2)
        line(surf, darken(recipe.shadow, 0.08), [(0, 12), (3, 11), (7, 12), (11, 11), (15, 12)])
    elif biome == "mountains":
        pygame.draw.polygon(surf, darken(recipe.mid, 0.04), [(0, 15), (3, 10), (5, 6), (8, 11), (11, 3), (15, 12), (15, 15)])
        pygame.draw.polygon(surf, recipe.mid, [(0, 15), (3, 11), (5, 7), (8, 11), (11, 4), (15, 12), (15, 15)])
        pygame.draw.polygon(surf, lighten(recipe.light, 0.1), [(1, 15), (3, 12), (5, 8), (7, 11), (11, 5), (13, 10), (13, 15)])
        px(surf, darken(recipe.shadow, 0.12), 8, 8, 3, 6)
        px(surf, lighten(recipe.accent, 0.08), 2, 13, 4, 1)
        if season == "winter":
            px(surf, lighten(recipe.light, 0.16), 4, 8, 3, 1)
            px(surf, lighten(recipe.light, 0.16), 10, 5, 2, 1)
    elif biome == "desert":
        for y in (5, 8, 11, 14):
            line(surf, lighten(recipe.light, 0.08), [(0, y), (4, y - 1), (8, y), (12, y - 1), (15, y)])
        px(surf, recipe.accent, 11, 4, 2, 2)
        px(surf, lighten(recipe.light, 0.08), 12, 4, 1, 1)
        px(surf, darken(recipe.shadow, 0.1), 4, 10, 2, 1)
    elif biome == "snow":
        for x, y in ((2, 4), (7, 6), (11, 3), (5, 12), (12, 10), (9, 8)):
            px(surf, lighten(recipe.light, 0.1), x, y, 2, 1)
        pygame.draw.arc(surf, mix_color(recipe.moisture, recipe.shadow, 0.2), (1, 8, 14, 6), 0.1, 3.1, 1)
        line(surf, mix_color(recipe.moisture, recipe.shadow, 0.2), [(0, 12), (4, 11), (8, 12), (12, 11), (15, 12)])
    elif biome == "swamp":
        pygame.draw.ellipse(surf, recipe.moisture, (1, 3, 10, 6))
        pygame.draw.ellipse(surf, darken(recipe.moisture, 0.12), (8, 7, 7, 5))
        for x in (2, 5, 10, 13):
            px(surf, recipe.accent, x, 11, 1, 4)
            px(surf, lighten(recipe.accent, 0.08), x, 10, 1, 1)
        px(surf, darken(recipe.shadow, 0.08), 0, 13, 16, 2)
    elif biome == "taiga":
        for x, y in ((2, 5), (7, 2), (11, 6)):
            pygame.draw.polygon(surf, recipe.mid, [(x, y + 6), (x + 2, y), (x + 5, y + 6)])
            px(surf, recipe.light, x + 2, y + 1, 1, 3)
            px(surf, darken(recipe.shadow, 0.08), x + 2, y + 6, 1, 2)
        px(surf, recipe.shadow, 1, 13, 14, 2)
    elif biome == "tundra":
        px(surf, recipe.mid, 0, 11, 16, 3)
        line(surf, recipe.light, [(2, 5), (4, 7), (6, 8)])
        line(surf, recipe.light, [(9, 10), (11, 8), (13, 6)])
        px(surf, recipe.moisture, 11, 12, 2, 1)
        px(surf, darken(recipe.shadow, 0.1), 0, 14, 16, 1)
    return surf


def draw_transition(target_biome: str, edge: str, season: str) -> pygame.Surface:
    recipe = palette_for_biome_and_season(target_biome, season)
    surf = surface((SOURCE_TILE_SIZE, SOURCE_TILE_SIZE))
    band = 4
    jag = (0, 1, 0, 2)
    if edge == "north":
        for x in range(0, 16, 4):
            px(surf, (*recipe.mid, 180), x, 0, 4, band + jag[(x // 4) % len(jag)])
        px(surf, (*recipe.light, 130), 0, band, 16, 1)
    elif edge == "south":
        for x in range(0, 16, 4):
            h = band + jag[(x // 4) % len(jag)]
            px(surf, (*recipe.shadow, 180), x, 16 - h, 4, h)
        px(surf, (*recipe.mid, 130), 0, 11, 16, 1)
    elif edge == "west":
        for y in range(0, 16, 4):
            px(surf, (*recipe.mid, 180), 0, y, band + jag[(y // 4) % len(jag)], 4)
        px(surf, (*recipe.light, 130), band, 0, 1, 16)
    elif edge == "east":
        for y in range(0, 16, 4):
            w = band + jag[(y // 4) % len(jag)]
            px(surf, (*recipe.shadow, 180), 16 - w, y, w, 4)
        px(surf, (*recipe.mid, 130), 11, 0, 1, 16)
    return surf


def draw_overlay(zone_type: str, variant: int) -> pygame.Surface:
    overlay = DISTRICT_OVERLAYS[zone_type]
    accent = overlay["accent"]
    style = overlay["style"]
    surf = surface((SOURCE_TILE_SIZE, SOURCE_TILE_SIZE))
    if style == "footpath":
        px(surf, (*accent, 95), 1, 11, 14, 2)
        px(surf, (*lighten(accent, 0.14), 74), 5 + variant, 4, 2, 9)
    elif style == "furrows":
        for x in (2, 5, 8, 11, 14):
            px(surf, (*accent, 84), x, 2, 1, 11)
        px(surf, (*darken(accent, 0.18), 96), 1, 13, 14, 1)
    elif style == "yard":
        px(surf, (*accent, 78), 2, 10, 12, 4)
        px(surf, (*lighten(accent, 0.08), 90), 4 + variant, 6, 3, 2)
        px(surf, (*darken(accent, 0.14), 96), 10, 6, 2, 2)
    else:
        pygame.draw.circle(surf, (*accent, 92), (8, 8), 5, 1)
        px(surf, (*lighten(accent, 0.12), 108), 7, 2, 2, 2)
        px(surf, (*accent, 84), 3, 8, 2, 1)
        px(surf, (*accent, 84), 11, 8, 2, 1)
    return surf


def draw_thronglet(role: str, animation: str, facing: str, frame_idx: int) -> pygame.Surface:
    palette = ROLE_PALETTES.get(role, ROLE_PALETTES["default"])
    surf = surface(SOURCE_THRONGLET_SIZE)
    bounce = 1 if animation in {"walk", "gather", "build", "celebrate"} and frame_idx == 0 else 0
    body = palette.clothing
    skin = palette.skin
    hair = palette.hair
    trim = palette.trim
    shadow = palette.shadow

    if animation == "sick":
        body = mix_color(body, (138, 154, 126), 0.18)
        skin = mix_color(skin, (170, 188, 164), 0.16)
    elif animation == "death":
        body = darken(body, 0.28)
        shadow = darken(shadow, 0.2)

    px(surf, (0, 0, 0, 68), 4, 21 + bounce, 8, 2)
    if animation == "death":
        outlined_rect(surf, body, shadow, (3, 11, 10, 7))
        px(surf, hair, 4, 9, 8, 3)
        px(surf, skin, 5, 12, 6, 3)
        px(surf, shadow, 3, 18, 10, 2)
        return surf

    head_x = 5 if facing != "right" else 6
    if facing == "left":
        head_x = 4
    face_shadow = darken(skin, 0.18)
    px(surf, shadow, head_x - 1, 1 + bounce, 8, 7)
    px(surf, hair, head_x, 1 + bounce, 6, 3)
    px(surf, lighten(hair, 0.08), head_x + 1, 1 + bounce, 3, 1)
    px(surf, skin, head_x, 3 + bounce, 6, 4)
    px(surf, face_shadow, head_x, 6 + bounce, 6, 1)
    if facing == "up":
        px(surf, hair, head_x - 1, 2 + bounce, 8, 4)
        px(surf, lighten(hair, 0.1), head_x + 1, 2 + bounce, 2, 1)
    elif facing == "left":
        px(surf, (42, 34, 31), head_x + 1, 5 + bounce)
        px(surf, lighten(skin, 0.12), head_x + 3, 4 + bounce, 1, 1)
    elif facing == "right":
        px(surf, (42, 34, 31), head_x + 4, 5 + bounce)
        px(surf, lighten(skin, 0.12), head_x + 1, 4 + bounce, 1, 1)
    else:
        px(surf, (42, 34, 31), 6, 5 + bounce)
        px(surf, (42, 34, 31), 9, 5 + bounce)
        px(surf, lighten(skin, 0.12), 7, 4 + bounce, 1, 1)

    torso_y = 8 + bounce
    outlined_rect(surf, body, shadow, (4, torso_y, 8, 9))
    px(surf, lighten(body, 0.08), 5, torso_y + 1, 6, 2)
    px(surf, trim, 4, torso_y + 1, 1, 6)
    px(surf, trim, 11, torso_y + 1, 1, 6)
    px(surf, lighten(trim, 0.18), 6, torso_y + 2, 4, 1)
    px(surf, darken(trim, 0.2), 5, torso_y + 5, 6, 1)

    if animation == "build":
        px(surf, skin, 2, torso_y + 3, 3, 2)
        px(surf, skin, 11, torso_y + 2, 3, 2)
        px(surf, shadow, 13, torso_y + 1, 2, 6)
        px(surf, lighten(trim, 0.12), 13, torso_y + 1, 1, 5)
    elif animation == "gather":
        px(surf, skin, 2, torso_y + 4, 3, 2)
        px(surf, trim, 12, torso_y + 4, 2, 2)
    elif animation == "rest":
        px(surf, skin, 3, torso_y + 5, 10, 2)
    elif animation == "celebrate":
        px(surf, skin, 2, torso_y + 1, 2, 4)
        px(surf, skin, 12, torso_y + 1, 2, 4)
    else:
        px(surf, skin, 3, torso_y + 3, 2, 4)
        px(surf, skin, 11, torso_y + 3, 2, 4)

    leg_y = 16 + bounce
    if animation in {"walk", "celebrate", "gather", "build"}:
        offset = -1 if frame_idx == 0 else 1
        px(surf, shadow, 4 + offset, leg_y, 2, 5)
        px(surf, shadow, 9 - offset, leg_y + 1, 2, 4)
        px(surf, lighten(shadow, 0.12), 4 + offset, leg_y, 1, 2)
        px(surf, lighten(shadow, 0.12), 9 - offset, leg_y + 1, 1, 2)
    elif animation == "rest":
        px(surf, shadow, 4, leg_y + 2, 8, 2)
    else:
        px(surf, shadow, 5, leg_y, 2, 5)
        px(surf, shadow, 9, leg_y, 2, 5)

    if role == "builder":
        px(surf, (92, 68, 48), 1, torso_y + 5, 2, 2)
        px(surf, trim, 2, torso_y + 4, 1, 4)
        px(surf, lighten(trim, 0.16), 1, torso_y + 4, 3, 1)
    elif role == "gatherer":
        px(surf, (180, 89, 102), 11, torso_y + 4, 3, 3)
        px(surf, (106, 154, 86), 2, torso_y + 6, 2, 2)
    elif role == "explorer":
        px(surf, lighten(trim, 0.08), 4, torso_y, 8, 1)
        px(surf, trim, 6, leg_y, 1, 5)
        px(surf, lighten(trim, 0.12), 10, torso_y + 2, 2, 4)
    if animation == "celebrate":
        px(surf, lighten(trim, 0.15), 1, 7 + bounce, 2, 2)
        px(surf, lighten(trim, 0.15), 13, 7 + bounce, 2, 2)
    return surf


def draw_building(building_type: str) -> pygame.Surface:
    recipe = BUILDING_FOOTPRINT_ART[building_type]
    surf = surface(recipe.source_size)
    w, h = recipe.source_size
    if building_type == "house":
        pygame.draw.polygon(surf, darken(recipe.roof, 0.16), [(2, 17), (w // 2, 2), (w - 3, 17)])
        pygame.draw.polygon(surf, recipe.roof, [(4, 17), (w // 2, 4), (w - 5, 17)])
        line(surf, lighten(recipe.roof, 0.16), [(5, 17), (w // 2, 5), (w - 6, 17)])
        for x in range(7, w - 7, 4):
            px(surf, darken(recipe.roof, 0.08), x, 12 + ((x // 4) % 2), 3, 1)
        outlined_rect(surf, recipe.wall, recipe.trim, (6, 17, w - 12, 14))
        px(surf, lighten(recipe.wall, 0.08), 8, 18, w - 16, 2)
        px(surf, recipe.accent, 9, 20, 4, 4)
        px(surf, recipe.accent, 19, 20, 4, 4)
        px(surf, lighten(recipe.accent, 0.12), 10, 20, 2, 1)
        px(surf, darken(recipe.trim, 0.1), 13, 22, 6, 8)
        px(surf, lighten(recipe.trim, 0.08), 14, 23, 2, 3)
        px(surf, recipe.trim, 5, 30, w - 10, 2)
    elif building_type == "storage":
        outlined_rect(surf, recipe.wall, recipe.trim, (4, 13, w - 8, 16))
        px(surf, recipe.roof, 3, 8, w - 6, 6)
        px(surf, recipe.accent, 7, 24, 6, 4)
        px(surf, recipe.accent, 19, 22, 7, 6)
    elif building_type == "farm":
        px(surf, darken(recipe.wall, 0.14), 1, 18, w - 2, 12)
        for x in (4, 8, 12, 16, 20, 24, 28):
            px(surf, recipe.accent, x, 19, 1, 9)
        px(surf, recipe.trim, 23, 8, 6, 9)
        px(surf, recipe.roof, 21, 6, 10, 3)
    elif building_type == "workshop":
        pygame.draw.polygon(surf, darken(recipe.roof, 0.14), [(4, 15), (13, 5), (w - 5, 15), (w - 5, 17), (4, 17)])
        pygame.draw.polygon(surf, recipe.roof, [(6, 15), (13, 7), (w - 7, 15), (w - 7, 16), (6, 16)])
        outlined_rect(surf, recipe.wall, recipe.trim, (5, 17, w - 10, 13))
        px(surf, lighten(recipe.wall, 0.08), 7, 18, w - 14, 2)
        px(surf, darken(recipe.trim, 0.22), w - 11, 8, 3, 10)
        px(surf, recipe.accent, w - 11, 6, 3, 2)
        px(surf, darken(recipe.accent, 0.2), 9, 22, 6, 5)
        px(surf, lighten(recipe.accent, 0.12), 10, 23, 4, 1)
        px(surf, lighten(recipe.wall, 0.08), 19, 21, 4, 4)
    elif building_type == "shrine":
        px(surf, darken(recipe.trim, 0.16), 6, 28, w - 12, 3)
        outlined_rect(surf, recipe.trim, darken(recipe.trim, 0.14), (8, 11, w - 16, 18))
        px(surf, recipe.wall, 11, 5, w - 22, 8)
        px(surf, lighten(recipe.wall, 0.08), 13, 6, w - 26, 2)
        pygame.draw.arc(surf, recipe.accent, (8, 5, w - 16, 20), 3.14, 6.28, 2)
        px(surf, lighten(recipe.accent, 0.08), w // 2 - 2, 17, 4, 7)
        px(surf, lighten(recipe.accent, 0.12), w // 2 - 1, 13, 2, 2)
        px(surf, recipe.wall, 12, 14, 3, 12)
        px(surf, recipe.wall, w - 15, 14, 3, 12)
    elif building_type == "well":
        pygame.draw.ellipse(surf, recipe.trim, (6, 13, w - 12, 9))
        pygame.draw.ellipse(surf, recipe.accent, (8, 15, w - 16, 5))
        px(surf, recipe.roof, 11, 4, 2, 10)
        px(surf, recipe.roof, w - 13, 4, 2, 10)
        px(surf, darken(recipe.roof, 0.12), 10, 4, w - 20, 2)
    return surf


def draw_resource(resource_type: str) -> pygame.Surface:
    recipe = RESOURCE_ART[resource_type]
    surf = surface(SOURCE_RESOURCE_SIZE)
    if recipe.silhouette == "berry_bush":
        px(surf, recipe.primary, 4, 5, 8, 5)
        px(surf, recipe.accent, 5, 3, 6, 3)
        for point in ((4, 8), (7, 6), (10, 9)):
            px(surf, recipe.secondary, point[0], point[1], 2, 2)
    elif recipe.silhouette == "timber":
        px(surf, recipe.secondary, 3, 5, 10, 8)
        px(surf, recipe.primary, 1, 11, 14, 3)
        px(surf, recipe.accent, 5, 3, 6, 2)
    elif recipe.silhouette == "ore":
        pygame.draw.polygon(surf, recipe.primary, [(3, 11), (6, 4), (11, 3), (13, 8), (10, 13), (5, 14)])
        px(surf, recipe.secondary, 8, 4, 2, 2)
        px(surf, recipe.accent, 5, 10, 2, 2)
    else:
        pygame.draw.ellipse(surf, recipe.primary, (3, 7, 10, 7))
        px(surf, recipe.accent, 5, 9, 6, 2)
        px(surf, recipe.secondary, 4, 4, 8, 2)
    return surf


def draw_hazard(hazard_type: str) -> pygame.Surface:
    recipe = HAZARD_ART[hazard_type]
    surf = surface((24, 24))
    pygame.draw.circle(surf, (*recipe.primary, 58), (12, 12), 10)
    pygame.draw.circle(surf, (*recipe.secondary, 116), (12, 12), 7, 1)
    if recipe.emblem == "spiral":
        pygame.draw.arc(surf, recipe.secondary, (6, 6, 12, 12), 0.6, 5.5, 2)
    elif recipe.emblem == "peak":
        pygame.draw.polygon(surf, recipe.secondary, [(6, 16), (12, 6), (18, 16)])
    elif recipe.emblem == "wave":
        pygame.draw.arc(surf, recipe.secondary, (5, 9, 14, 7), 3.14, 6.1, 2)
    else:
        pygame.draw.line(surf, recipe.secondary, (8, 8), (12, 16), 2)
        pygame.draw.line(surf, recipe.secondary, (12, 16), (16, 8), 2)
    return surf


def draw_npc(npc_type: str) -> pygame.Surface:
    recipe = NPC_ART[npc_type]
    surf = surface((18, 24))
    if recipe.silhouette == "wagon":
        px(surf, recipe.clothing, 2, 10, 14, 6)
        px(surf, recipe.accent, 6, 8, 6, 3)
        px(surf, (52, 40, 30), 3, 16, 4, 4)
        px(surf, (52, 40, 30), 11, 16, 4, 4)
    elif recipe.silhouette == "scout":
        px(surf, recipe.clothing, 6, 4, 6, 6)
        px(surf, recipe.accent, 5, 10, 8, 7)
        px(surf, darken(recipe.clothing, 0.22), 6, 17, 2, 4)
        px(surf, darken(recipe.clothing, 0.22), 10, 17, 2, 4)
    else:
        for x, y in ((3, 13), (8, 9), (12, 14)):
            px(surf, recipe.clothing, x, y, 4, 4)
        px(surf, recipe.accent, 7, 6, 4, 2)
    return surf


def draw_placeholder(kind: str, size: tuple[int, int]) -> pygame.Surface:
    surf = surface(size)
    outlined_rect(surf, (142, 122, 100), (92, 72, 54), (0, 0, size[0], size[1]))
    pygame.draw.line(surf, (246, 214, 146), (2, 2), (size[0] - 3, size[1] - 3), 2)
    pygame.draw.line(surf, (246, 214, 146), (size[0] - 3, 2), (2, size[1] - 3), 2)
    return surf


def write_terrain() -> None:
    for biome in BIOMES:
        for season in SEASONS:
            save_png(draw_tile(biome, season), ASSETS / "tilesets" / "terrain" / f"{biome}_{season}.png")
            for edge in EDGES:
                save_png(draw_transition(biome, edge, season), ASSETS / "tilesets" / "transitions" / f"{biome}_{edge}_{season}.png")


def write_overlays() -> None:
    for zone_type in DISTRICT_OVERLAYS:
        for variant in range(3):
            save_png(draw_overlay(zone_type, variant), ASSETS / "tilesets" / "overlays" / f"{zone_type}_{variant}.png")


def write_thronglets() -> None:
    for role in ROLES:
        for animation in ANIMATIONS:
            for facing in FACINGS:
                for frame_idx in range(2):
                    sprite = draw_thronglet(role, animation, facing, frame_idx)
                    save_png(sprite, ASSETS / "sprites" / "thronglets" / f"{role}_{animation}_{facing}_{frame_idx}.png")


def write_buildings() -> None:
    for building_type in BUILDING_FOOTPRINT_ART:
        save_png(draw_building(building_type), ASSETS / "sprites" / "buildings" / f"{building_type}.png")


def write_resources() -> None:
    for resource_type in RESOURCE_ART:
        save_png(draw_resource(resource_type), ASSETS / "sprites" / "resources" / f"{resource_type}.png")


def write_hazards() -> None:
    for hazard_type in HAZARD_ART:
        save_png(draw_hazard(hazard_type), ASSETS / "sprites" / "hazards" / f"{hazard_type}.png")


def write_npcs() -> None:
    for npc_type in NPC_ART:
        save_png(draw_npc(npc_type), ASSETS / "sprites" / "npcs" / f"{npc_type}.png")


def write_placeholders() -> None:
    save_png(draw_placeholder("terrain", (16, 16)), ASSETS / "tilesets" / "placeholders" / "terrain_placeholder.png")
    save_png(draw_placeholder("thronglet", SOURCE_THRONGLET_SIZE), ASSETS / "sprites" / "placeholders" / "thronglet_placeholder.png")
    save_png(draw_placeholder("building", (32, 40)), ASSETS / "sprites" / "placeholders" / "building_placeholder.png")
    save_png(draw_placeholder("resource", SOURCE_RESOURCE_SIZE), ASSETS / "sprites" / "placeholders" / "resource_placeholder.png")
    save_png(draw_placeholder("hazard", (24, 24)), ASSETS / "sprites" / "placeholders" / "hazard_placeholder.png")
    save_png(draw_placeholder("npc", (18, 24)), ASSETS / "sprites" / "placeholders" / "npc_placeholder.png")


def main() -> None:
    pygame.init()
    try:
        write_terrain()
        write_overlays()
        write_thronglets()
        write_buildings()
        write_resources()
        write_hazards()
        write_npcs()
        write_placeholders()
        print("Generated SNES-inspired Thronglets asset pack.")
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
