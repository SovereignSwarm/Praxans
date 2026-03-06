from __future__ import annotations

from dataclasses import dataclass


Color = tuple[int, int, int]


@dataclass(frozen=True)
class BiomeMaterial:
    name: str
    base: Color
    highlight: Color
    shadow: Color
    accent: Color
    moisture: Color


def clamp_channel(value: float) -> int:
    return max(0, min(255, int(value)))


def mix_color(color_a: Color, color_b: Color, amount: float) -> Color:
    amount = max(0.0, min(1.0, float(amount)))
    return (
        clamp_channel(color_a[0] + (color_b[0] - color_a[0]) * amount),
        clamp_channel(color_a[1] + (color_b[1] - color_a[1]) * amount),
        clamp_channel(color_a[2] + (color_b[2] - color_a[2]) * amount),
    )


def lighten(color: Color, amount: float) -> Color:
    return mix_color(color, (255, 255, 255), amount)


def darken(color: Color, amount: float) -> Color:
    return mix_color(color, (0, 0, 0), amount)


BIOME_MATERIALS: dict[str, BiomeMaterial] = {
    "forest": BiomeMaterial("forest", (69, 112, 76), (111, 154, 94), (43, 68, 49), (128, 163, 111), (48, 94, 76)),
    "plains": BiomeMaterial("plains", (106, 152, 88), (146, 188, 110), (72, 103, 61), (188, 173, 110), (90, 132, 102)),
    "mountains": BiomeMaterial("mountains", (118, 128, 138), (159, 170, 180), (72, 80, 90), (154, 126, 96), (113, 127, 145)),
    "desert": BiomeMaterial("desert", (193, 165, 120), (227, 199, 152), (126, 99, 63), (196, 122, 77), (140, 134, 86)),
    "snow": BiomeMaterial("snow", (222, 232, 239), (244, 249, 252), (153, 170, 182), (171, 198, 214), (178, 208, 214)),
    "swamp": BiomeMaterial("swamp", (71, 92, 70), (109, 132, 93), (42, 58, 43), (118, 107, 66), (54, 98, 103)),
    "taiga": BiomeMaterial("taiga", (72, 109, 88), (113, 149, 110), (46, 68, 55), (138, 161, 144), (76, 116, 126)),
    "tundra": BiomeMaterial("tundra", (155, 181, 189), (197, 217, 223), (106, 128, 136), (180, 165, 128), (137, 178, 186)),
}

DISTRICT_COLORS: dict[str, Color] = {
    "residential": (207, 189, 160),
    "agricultural": (138, 170, 102),
    "industrial": (176, 123, 92),
    "spiritual": (159, 156, 205),
}

DOCTRINE_COLORS: dict[str, Color] = {
    "growth": (224, 183, 108),
    "security": (111, 177, 220),
    "industry": (210, 132, 99),
    "exploration": (179, 149, 223),
    "harmony": (136, 201, 169),
    "survival": (214, 124, 107),
}

RESOURCE_COLORS: dict[str, Color] = {
    "food": (209, 96, 89),
    "wood": (138, 105, 78),
    "stone": (159, 166, 173),
}

HAZARD_COLORS: dict[str, Color] = {
    "quicksand": (163, 120, 65),
    "avalanche_zone": (241, 244, 248),
    "flood_zone": (87, 143, 206),
    "predator_lair": (204, 79, 79),
}

NPC_COLORS: dict[str, Color] = {
    "trader": (216, 179, 92),
    "rival_tribe": (170, 84, 74),
    "wildlife_herd": (166, 128, 96),
}


def doctrine_color(doctrine: str | None) -> Color:
    return DOCTRINE_COLORS.get(str(doctrine or "").lower(), (220, 220, 220))


def season_tint(season_name: str | None) -> Color:
    name = str(season_name or "spring").lower()
    if name == "winter":
        return (188, 208, 224)
    if name == "autumn":
        return (214, 182, 134)
    if name == "summer":
        return (244, 214, 146)
    return (181, 214, 173)


def weather_tint(weather_name: str | None) -> Color:
    name = str(weather_name or "clear").lower()
    if name == "storm":
        return (83, 96, 114)
    if name == "rain":
        return (103, 126, 156)
    if name == "snow":
        return (220, 230, 236)
    if name == "heatwave":
        return (222, 154, 96)
    return (0, 0, 0)
