from __future__ import annotations

from dataclasses import dataclass

from graphics.palette import BIOME_MATERIALS, darken, doctrine_color, lighten, mix_color


Color = tuple[int, int, int]

SOURCE_TILE_SIZE = 16
SOURCE_THRONGLET_SIZE = (16, 24)
SOURCE_RESOURCE_SIZE = (16, 16)
SOURCE_ICON_SIZE = (16, 16)
SNAP_ZOOM_LEVELS = (0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)


@dataclass(frozen=True)
class TileRecipe:
    biome: str
    motif: str
    transition_style: str
    base: Color
    mid: Color
    light: Color
    shadow: Color
    accent: Color
    moisture: Color


@dataclass(frozen=True)
class ActorPalette:
    skin: Color
    hair: Color
    clothing: Color
    shadow: Color
    trim: Color


@dataclass(frozen=True)
class BuildingRecipe:
    building_type: str
    source_size: tuple[int, int]
    footprint_tiles: tuple[int, int]
    silhouette: str
    wall: Color
    roof: Color
    trim: Color
    accent: Color


@dataclass(frozen=True)
class ResourceRecipe:
    resource_type: str
    silhouette: str
    primary: Color
    secondary: Color
    accent: Color


@dataclass(frozen=True)
class HazardRecipe:
    hazard_type: str
    emblem: str
    primary: Color
    secondary: Color


@dataclass(frozen=True)
class NpcRecipe:
    npc_type: str
    silhouette: str
    clothing: Color
    accent: Color


def _tile_recipe(biome: str, motif: str, transition_style: str) -> TileRecipe:
    material = BIOME_MATERIALS[biome]
    return TileRecipe(
        biome=biome,
        motif=motif,
        transition_style=transition_style,
        base=material.base,
        mid=mix_color(material.base, material.accent, 0.25),
        light=material.highlight,
        shadow=material.shadow,
        accent=material.accent,
        moisture=material.moisture,
    )


TILE_ATLASES: dict[str, dict[str, object]] = {
    "plains": {"folder": "tilesets/terrain", "file": "plains.png", "source_size": (16, 16), "variants": 3},
    "forest": {"folder": "tilesets/terrain", "file": "forest.png", "source_size": (16, 16), "variants": 3},
    "mountains": {"folder": "tilesets/terrain", "file": "mountains.png", "source_size": (16, 16), "variants": 3},
    "desert": {"folder": "tilesets/terrain", "file": "desert.png", "source_size": (16, 16), "variants": 3},
    "snow": {"folder": "tilesets/terrain", "file": "snow.png", "source_size": (16, 16), "variants": 3},
    "swamp": {"folder": "tilesets/terrain", "file": "swamp.png", "source_size": (16, 16), "variants": 3},
    "taiga": {"folder": "tilesets/terrain", "file": "taiga.png", "source_size": (16, 16), "variants": 3},
    "tundra": {"folder": "tilesets/terrain", "file": "tundra.png", "source_size": (16, 16), "variants": 3},
}

SPRITE_ATLASES: dict[str, dict[str, object]] = {
    "thronglets": {
        "folder": "sprites/thronglets",
        "source_size": SOURCE_THRONGLET_SIZE,
        "animations": ("idle", "walk", "gather", "build", "rest", "celebrate", "sick", "death"),
        "facings": ("down", "up", "left", "right"),
    },
    "buildings": {
        "folder": "sprites/buildings",
        "source_size": (32, 40),
        "variants": ("house", "storage", "farm", "workshop", "shrine", "well"),
    },
    "resources": {"folder": "sprites/resources", "source_size": SOURCE_RESOURCE_SIZE},
    "hazards": {"folder": "sprites/hazards", "source_size": (24, 24)},
    "npcs": {"folder": "sprites/npcs", "source_size": (18, 24)},
    "effects": {"folder": "sprites/effects", "source_size": SOURCE_ICON_SIZE},
}

ANIMATION_TIMINGS: dict[str, float] = {
    "idle": 0.65,
    "walk": 0.18,
    "gather": 0.2,
    "build": 0.22,
    "rest": 0.8,
    "celebrate": 0.16,
    "sick": 0.45,
    "death": 0.5,
}

BIOME_PALETTE_FAMILIES: dict[str, TileRecipe] = {
    "plains": _tile_recipe("plains", "grassland", "soft"),
    "forest": _tile_recipe("forest", "canopy", "rooted"),
    "mountains": _tile_recipe("mountains", "cliff", "rocky"),
    "desert": _tile_recipe("desert", "dune", "wind"),
    "snow": _tile_recipe("snow", "drift", "snow"),
    "swamp": _tile_recipe("swamp", "mire", "wet"),
    "taiga": _tile_recipe("taiga", "conifer", "needled"),
    "tundra": _tile_recipe("tundra", "frost", "cold"),
}

ROLE_PALETTES: dict[str, ActorPalette] = {
    "gatherer": ActorPalette((238, 201, 173), (104, 68, 44), (171, 112, 86), (86, 54, 36), (201, 162, 74)),
    "builder": ActorPalette((233, 196, 168), (80, 58, 44), (126, 110, 144), (60, 50, 76), (222, 180, 109)),
    "explorer": ActorPalette((230, 192, 162), (94, 70, 52), (95, 137, 152), (48, 76, 85), (198, 160, 110)),
    "default": ActorPalette((236, 198, 172), (82, 62, 50), (150, 148, 121), (66, 62, 56), (214, 190, 125)),
}

BUILDING_FOOTPRINT_ART: dict[str, BuildingRecipe] = {
    "house": BuildingRecipe("house", (32, 40), (1, 1), "cottage", (150, 116, 84), (132, 70, 56), (82, 56, 46), (242, 197, 136)),
    "storage": BuildingRecipe("storage", (34, 34), (1, 1), "storehouse", (120, 112, 96), (118, 86, 61), (74, 60, 51), (183, 162, 110)),
    "farm": BuildingRecipe("farm", (32, 32), (1, 1), "field", (130, 96, 68), (118, 86, 48), (81, 55, 34), (150, 172, 89)),
    "workshop": BuildingRecipe("workshop", (34, 40), (1, 1), "forge", (110, 100, 112), (92, 76, 62), (58, 52, 64), (214, 168, 111)),
    "shrine": BuildingRecipe("shrine", (36, 44), (1, 1), "sanctum", (165, 155, 173), (112, 88, 124), (80, 64, 88), (246, 216, 142)),
    "well": BuildingRecipe("well", (28, 28), (1, 1), "well", (116, 112, 106), (88, 76, 68), (58, 54, 48), (110, 175, 204)),
}

RESOURCE_ART: dict[str, ResourceRecipe] = {
    "food": ResourceRecipe("food", "berry_bush", (150, 112, 84), (171, 72, 88), (96, 132, 77)),
    "wood": ResourceRecipe("wood", "timber", (128, 95, 63), (86, 58, 38), (112, 146, 89)),
    "stone": ResourceRecipe("stone", "ore", (148, 154, 161), (108, 115, 124), (204, 192, 152)),
    "water": ResourceRecipe("water", "spring", (88, 155, 194), (62, 110, 154), (205, 230, 240)),
}

HAZARD_ART: dict[str, HazardRecipe] = {
    "quicksand": HazardRecipe("quicksand", "spiral", (178, 135, 82), (121, 84, 52)),
    "avalanche_zone": HazardRecipe("avalanche_zone", "peak", (233, 241, 246), (150, 167, 183)),
    "flood_zone": HazardRecipe("flood_zone", "wave", (84, 136, 194), (52, 94, 151)),
    "predator_lair": HazardRecipe("predator_lair", "fang", (190, 84, 86), (116, 42, 46)),
}

NPC_ART: dict[str, NpcRecipe] = {
    "trader": NpcRecipe("trader", "wagon", (186, 140, 76), (241, 205, 128)),
    "rival_tribe": NpcRecipe("rival_tribe", "scout", (132, 74, 70), (226, 154, 114)),
    "wildlife_herd": NpcRecipe("wildlife_herd", "herd", (154, 112, 76), (210, 180, 126)),
}

DISTRICT_OVERLAYS: dict[str, dict[str, object]] = {
    "residential": {"style": "footpath", "accent": (211, 180, 136)},
    "agricultural": {"style": "furrows", "accent": (148, 167, 91)},
    "industrial": {"style": "yard", "accent": (186, 122, 92)},
    "spiritual": {"style": "ring", "accent": (171, 149, 204)},
}

FALLBACK_PLACEHOLDERS: dict[str, str] = {
    "terrain": "tilesets/placeholders/terrain_placeholder.png",
    "thronglet": "sprites/placeholders/thronglet_placeholder.png",
    "building": "sprites/placeholders/building_placeholder.png",
    "resource": "sprites/placeholders/resource_placeholder.png",
    "hazard": "sprites/placeholders/hazard_placeholder.png",
    "npc": "sprites/placeholders/npc_placeholder.png",
}


def snap_zoom_level(zoom: float, levels: tuple[float, ...] = SNAP_ZOOM_LEVELS) -> float:
    zoom = float(zoom or 1.0)
    return min(levels, key=lambda candidate: abs(candidate - zoom))


def time_of_day_for_elapsed(elapsed_seconds: float) -> str:
    phase = max(0.0, float(elapsed_seconds)) % 160.0
    if phase < 24.0:
        return "dawn"
    if phase < 92.0:
        return "day"
    if phase < 124.0:
        return "dusk"
    return "night"


def tint_for_time_of_day(time_of_day: str) -> tuple[Color, float]:
    name = str(time_of_day or "day").lower()
    if name == "dawn":
        return (238, 195, 148), 0.12
    if name == "dusk":
        return (209, 158, 130), 0.18
    if name == "night":
        return (70, 92, 132), 0.28
    return (250, 239, 197), 0.0


def palette_for_biome_and_season(biome: str, season_name: str) -> TileRecipe:
    recipe = BIOME_PALETTE_FAMILIES.get(biome, BIOME_PALETTE_FAMILIES["plains"])
    season_key = str(season_name or "spring").lower()
    if season_key == "winter":
        return TileRecipe(
            biome=recipe.biome,
            motif=recipe.motif,
            transition_style=recipe.transition_style,
            base=lighten(recipe.base, 0.16),
            mid=lighten(recipe.mid, 0.12),
            light=lighten(recipe.light, 0.08),
            shadow=mix_color(recipe.shadow, (110, 134, 160), 0.15),
            accent=lighten(recipe.accent, 0.08),
            moisture=lighten(recipe.moisture, 0.1),
        )
    if season_key == "autumn":
        return TileRecipe(
            biome=recipe.biome,
            motif=recipe.motif,
            transition_style=recipe.transition_style,
            base=mix_color(recipe.base, (165, 124, 82), 0.12),
            mid=mix_color(recipe.mid, (196, 146, 94), 0.2),
            light=mix_color(recipe.light, (216, 176, 111), 0.22),
            shadow=recipe.shadow,
            accent=mix_color(recipe.accent, (186, 121, 77), 0.25),
            moisture=darken(recipe.moisture, 0.04),
        )
    if season_key == "summer":
        return TileRecipe(
            biome=recipe.biome,
            motif=recipe.motif,
            transition_style=recipe.transition_style,
            base=lighten(recipe.base, 0.08),
            mid=lighten(recipe.mid, 0.06),
            light=lighten(recipe.light, 0.04),
            shadow=darken(recipe.shadow, 0.04),
            accent=lighten(recipe.accent, 0.08),
            moisture=darken(recipe.moisture, 0.05),
        )
    return recipe


def doctrine_trim(doctrine: str | None) -> tuple[Color, Color]:
    accent = doctrine_color(doctrine)
    return accent, darken(accent, 0.35)
