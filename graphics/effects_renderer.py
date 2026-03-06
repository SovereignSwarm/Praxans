from __future__ import annotations

import math
import random

import pygame

from graphics.content import tint_for_time_of_day
from graphics.palette import doctrine_color, mix_color, season_tint, weather_tint


class EffectsRenderer:
    def __init__(self, config):
        self.config = config

    def _draw_time_of_day_pass(self, surface: pygame.Surface, frame) -> None:
        tint, amount = tint_for_time_of_day(frame.world.time_of_day)
        if amount <= 0.0:
            return
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        pygame.draw.rect(overlay, (*tint, int(255 * amount)), overlay.get_rect())
        if frame.world.time_of_day == "night":
            vignette = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            for radius in range(0, max(surface.get_width(), surface.get_height()), 80):
                alpha = min(70, 12 + radius // 20)
                pygame.draw.circle(
                    vignette,
                    (22, 28, 42, alpha),
                    (surface.get_width() // 2, surface.get_height() // 2),
                    max(surface.get_width(), surface.get_height()) // 2 + radius,
                    18,
                )
            overlay.blit(vignette, (0, 0))
        surface.blit(overlay, (0, 0))

        # Dynamic point lighting: buildings emit warm glow at night/dusk
        if frame.world.time_of_day in ("night", "dusk"):
            self._draw_point_lights(surface, frame, amount)

    def _draw_point_lights(self, surface: pygame.Surface, frame, darkness: float) -> None:
        """Draw warm radial glows around occupied buildings at night/dusk."""
        zoom = max(0.5, float(frame.world.camera.zoom or 1.0))
        camera = frame.world.camera
        width, height = frame.world.window_size
        light_layer = pygame.Surface((width, height), pygame.SRCALPHA)

        _LIGHT_COLORS = {
            "house": (255, 210, 140),
            "workshop": (255, 180, 100),
            "shrine": (180, 170, 230),
            "well": (140, 190, 220),
            "storage": (220, 195, 140),
            "farm": (200, 190, 130),
            "hospital": (255, 240, 240),
            "school": (180, 200, 255),
            "watchtower": (255, 200, 100),
            "market": (255, 160, 80),
        }
        light_count = 0

        for entity_state in frame.buildings:
            if light_count >= 40:
                break
            building = entity_state.entity
            active = bool(getattr(building, "occupants", None) or getattr(building, "aura_strength", 0) > 0.05)
            if not active:
                continue

            bx = float(getattr(building, "x", 0))
            by = float(getattr(building, "y", 0))
            sx = int((bx - camera.x) * zoom)
            sy = int((by - camera.y) * zoom)

            if not (-80 <= sx <= width + 80 and -80 <= sy <= height + 80):
                continue

            btype = str(getattr(building, "building_type", "house"))
            base_color = _LIGHT_COLORS.get(btype, (255, 210, 140))

            # Outer soft glow
            outer_radius = max(20, int(48 * zoom * darkness))
            outer_alpha = max(8, int(22 * darkness))
            pygame.draw.circle(light_layer, (*base_color, outer_alpha), (sx, sy), outer_radius)

            # Inner bright core
            inner_radius = max(6, int(16 * zoom * darkness))
            inner_alpha = max(12, int(42 * darkness))
            pygame.draw.circle(light_layer, (*base_color, inner_alpha), (sx, sy), inner_radius)

            # Window pixel — tiny bright amber square
            if btype in ("house", "workshop") and frame.world.time_of_day == "night":
                win_size = max(2, int(3 * zoom))
                pygame.draw.rect(light_layer, (255, 220, 120, int(160 * darkness)),
                                 (sx - win_size // 2, sy - int(4 * zoom), win_size, win_size))

            light_count += 1

        surface.blit(light_layer, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _draw_daylight_orb(self, surface: pygame.Surface, elapsed_seconds: float, season_name: str, time_of_day: str) -> None:
        width, height = surface.get_size()
        if time_of_day == "night":
            orb_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            pygame.draw.circle(orb_surface, (228, 232, 246, 66), (int(width * 0.82), int(height * 0.18)), 28)
            surface.blit(orb_surface, (0, 0))
            return
        orb_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        day_progress = (elapsed_seconds % 160.0) / 160.0
        arc = math.sin(day_progress * math.pi)
        orb_x = int(width * (0.08 + 0.84 * day_progress))
        orb_y = int(height * (0.18 + (1.0 - arc) * 0.28))
        base_color = season_tint(season_name)
        if time_of_day == "dusk":
            glow_color = mix_color(base_color, (255, 181, 142), 0.42)
        elif time_of_day == "dawn":
            glow_color = mix_color(base_color, (252, 213, 162), 0.36)
        else:
            glow_color = mix_color(base_color, (255, 236, 188), 0.4)
        pygame.draw.circle(orb_surface, (*glow_color, 38), (orb_x, orb_y), 74)
        pygame.draw.circle(orb_surface, (*glow_color, 118), (orb_x, orb_y), 28)
        surface.blit(orb_surface, (0, 0))

    def _draw_weather_pass(self, surface: pygame.Surface, frame) -> None:
        if not self.config.enable_weather_pass:
            return
        weather_name = str(getattr(frame.world.weather_system, "current_weather", "clear"))
        width, height = surface.get_size()
        if weather_name in {"rain", "storm"}:
            rain_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            count = max(24, width // 26)
            tone = weather_tint(weather_name)
            for index in range(count):
                x = (index * 47 + int(frame.world.current_time * 92)) % (width + 36) - 18
                y = (index * 29 + int(frame.world.current_time * 168)) % (height + 36) - 18
                pygame.draw.line(rain_surface, (*tone, 106), (x, y), (x + 6, y + 14), 2 if weather_name == "storm" else 1)
            surface.blit(rain_surface, (0, 0))
        elif weather_name == "snow":
            snow_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            for index in range(max(22, width // 42)):
                x = (index * 53 + int(frame.world.current_time * 20)) % width
                y = (index * 29 + int(frame.world.current_time * 13)) % height
                pygame.draw.circle(snow_surface, (246, 248, 252, 110), (x, y), 2)
            surface.blit(snow_surface, (0, 0))
        elif weather_name == "heatwave":
            shimmer = pygame.Surface((width, height), pygame.SRCALPHA)
            for y in range(0, height, 28):
                pygame.draw.line(shimmer, (255, 214, 155, 22), (0, y), (width, y + 10), 2)
            surface.blit(shimmer, (0, 0))

    def _draw_settlement_pass(self, surface: pygame.Surface, frame) -> None:
        settlement = frame.world.settlement_state
        prosperity = float(settlement.get("prosperity_score", 0.0) or 0.0)
        festival = bool(settlement.get("festival_active", False))
        width, height = surface.get_size()
        if prosperity > 0.55:
            prosperity_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            accent_alpha = max(10, min(26, int(10 + prosperity * 18)))
            pygame.draw.rect(prosperity_surface, (244, 217, 137, accent_alpha), prosperity_surface.get_rect(), 6)
            surface.blit(prosperity_surface, (0, 0))
        if festival:
            festival_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            rng = random.Random(int(frame.world.current_time * 3))
            for _ in range(26):
                confetti_x = rng.randint(0, max(4, width - 4))
                confetti_y = rng.randint(0, max(8, height - 8))
                confetti_color = doctrine_color(rng.choice(["growth", "exploration", "harmony"]))
                pygame.draw.rect(festival_surface, (*confetti_color, 96), (confetti_x, confetti_y, 3, 5))
            surface.blit(festival_surface, (0, 0))

    def _draw_event_beacons(self, surface: pygame.Surface, frame) -> None:
        if not self.config.enable_event_beacons:
            return
        for cue in frame.effect_cues[-4:]:
            zoom = max(0.5, float(frame.world.camera.zoom or 1.0))
            screen_x = int((cue.x - frame.world.camera.x) * zoom)
            screen_y = int((cue.y - frame.world.camera.y) * zoom)
            if not (-90 <= screen_x <= frame.world.window_size[0] + 90 and -90 <= screen_y <= frame.world.window_size[1] + 90):
                continue
            beacon_color = doctrine_color(cue.category if cue.category in {"growth", "security", "industry", "exploration", "harmony"} else "exploration")
            beacon = pygame.Surface((72, 72), pygame.SRCALPHA)
            pygame.draw.circle(beacon, (*beacon_color, 24), (36, 36), 24)
            pygame.draw.circle(beacon, (*beacon_color, 86), (36, 36), 11, 2)
            pygame.draw.circle(beacon, (*mix_color(beacon_color, (255, 255, 255), 0.2), 54), (36, 36), 18, 1)
            surface.blit(beacon, (screen_x - 36, screen_y - 36))

    def _draw_focus_flare(self, surface: pygame.Surface, frame) -> None:
        focus = frame.world.focus_event
        if not focus:
            return
        elapsed = max(0.0, frame.world.current_time - float(focus.get("time", frame.world.current_time) or frame.world.current_time))
        if elapsed > self.config.focus_cue_seconds:
            return
        zoom = max(0.5, float(frame.world.camera.zoom or 1.0))
        screen_x = int((float(focus.get("x", 0.0)) - frame.world.camera.x) * zoom)
        screen_y = int((float(focus.get("y", 0.0)) - frame.world.camera.y) * zoom)
        pulse = 1.0 - min(1.0, elapsed / max(0.1, self.config.focus_cue_seconds))
        flare = pygame.Surface((120, 120), pygame.SRCALPHA)
        color = doctrine_color(str(focus.get("category", "exploration")))
        pygame.draw.circle(flare, (*color, int(26 * pulse)), (60, 60), int(18 + 18 * pulse))
        pygame.draw.circle(flare, (*color, int(124 * pulse)), (60, 60), int(8 + 8 * pulse), 2)
        surface.blit(flare, (screen_x - 60, screen_y - 60))

    def _draw_title_card(self, surface: pygame.Surface, frame) -> None:
        """Draw cinematic title card overlay from EventBus TitleCardQueue."""
        card = frame.title_card
        if not card:
            return
        width, height = surface.get_size()
        remaining = float(card.get("remaining", 0.0))
        max_time = float(card.get("max_time", 4.0) or 4.0)
        if remaining <= 0:
            return

        # Fade: quick in (0.3s), hold, quick out (0.5s)
        progress = 1.0 - (remaining / max_time)
        if progress < 0.08:
            alpha = progress / 0.08  # fade in
        elif remaining < 0.5:
            alpha = remaining / 0.5  # fade out
        else:
            alpha = 1.0

        bar_height = int(height * 0.14)
        bar_y = int(height * 0.08)
        bar_surface = pygame.Surface((width, bar_height), pygame.SRCALPHA)
        pygame.draw.rect(bar_surface, (12, 12, 18, int(180 * alpha)), bar_surface.get_rect())

        # Title text
        title = str(card.get("title", ""))
        subtitle = str(card.get("subtitle", ""))
        drama = int(card.get("drama", 5))

        try:
            title_font = pygame.font.SysFont("segoeui", max(18, int(bar_height * 0.42)), bold=True)
            sub_font = pygame.font.SysFont("segoeui", max(12, int(bar_height * 0.24)))
        except Exception:
            title_font = pygame.font.Font(None, max(18, int(bar_height * 0.42)))
            sub_font = pygame.font.Font(None, max(12, int(bar_height * 0.24)))

        # Drama accent color
        if drama >= 8:
            title_color = (255, 180, 100, int(255 * alpha))
        elif drama >= 6:
            title_color = (220, 230, 255, int(255 * alpha))
        else:
            title_color = (255, 255, 255, int(255 * alpha))

        title_surf = title_font.render(title[:50], True, title_color[:3])
        title_surf.set_alpha(int(255 * alpha))
        tx = (width - title_surf.get_width()) // 2
        ty = (bar_height - title_surf.get_height()) // 2 - 4

        bar_surface.blit(title_surf, (tx, ty))

        if subtitle:
            sub_surf = sub_font.render(subtitle[:80], True, (200, 200, 210))
            sub_surf.set_alpha(int(200 * alpha))
            sx = (width - sub_surf.get_width()) // 2
            sy = ty + title_surf.get_height() + 2
            bar_surface.blit(sub_surf, (sx, sy))

        # Accent line at bottom of bar
        accent_color = doctrine_color("exploration") if drama < 6 else doctrine_color("security") if drama < 8 else doctrine_color("survival")
        line_alpha = int(160 * alpha)
        pygame.draw.line(bar_surface, (*accent_color, line_alpha), (int(width * 0.15), bar_height - 1), (int(width * 0.85), bar_height - 1), 2)

        surface.blit(bar_surface, (0, bar_y))

    def _draw_ghost_markers(self, surface: pygame.Surface, frame) -> None:
        """Draw translucent building outlines at CityPlanner proposed sites."""
        if not frame.ghost_markers:
            return
        zoom = max(0.5, float(frame.world.camera.zoom or 1.0))
        pulse = 0.6 + 0.4 * abs(math.sin(frame.world.current_time * 2.5))

        for marker in frame.ghost_markers[:6]:
            wx = float(marker.get("x", 0.0))
            wy = float(marker.get("y", 0.0))
            screen_x = int((wx - frame.world.camera.x) * zoom)
            screen_y = int((wy - frame.world.camera.y) * zoom)

            # Viewport culling
            if not (-60 <= screen_x <= frame.world.window_size[0] + 60 and -60 <= screen_y <= frame.world.window_size[1] + 60):
                continue

            btype = str(marker.get("building_type", "house"))
            size = int(28 * zoom)
            ghost = pygame.Surface((size, size), pygame.SRCALPHA)

            # Building silhouette — translucent
            base_alpha = int(50 * pulse)
            accent = doctrine_color(str(marker.get("doctrine", "growth")))
            pygame.draw.rect(ghost, (*accent, base_alpha), (2, size // 3, size - 4, size - size // 3 - 2))
            # Roof triangle
            pygame.draw.polygon(ghost, (*accent, int(base_alpha * 0.8)), [
                (0, size // 3),
                (size // 2, 1),
                (size - 1, size // 3),
            ])
            # Pulsing border
            border_alpha = int(120 * pulse)
            pygame.draw.rect(ghost, (*accent, border_alpha), (1, size // 3, size - 2, size - size // 3 - 1), 1)

            # Label
            try:
                label_font = pygame.font.SysFont("segoeui", max(9, int(10 * zoom)))
                label = label_font.render(btype[:8], True, (*accent, int(200 * pulse)))
                surface.blit(label, (screen_x - label.get_width() // 2, screen_y + size // 2 + 2))
            except Exception:
                pass

            surface.blit(ghost, (screen_x - size // 2, screen_y - size // 2))

    def render(self, surface: pygame.Surface, frame) -> None:
        if frame.particle_system is not None:
            frame.particle_system.draw(surface)
        if frame.world.elapsed_seconds > self.config.fog_delay_seconds and hasattr(frame.world.fog_of_war, "draw_fog"):
            frame.world.fog_of_war.draw_fog(surface, frame.world.camera, frame.world.world_map)
        if hasattr(frame.world.territory_manager, "draw_territory_overlay"):
            frame.world.territory_manager.draw_territory_overlay(surface, frame.world.camera, frame.world.fog_of_war)
        base_tint = season_tint(getattr(frame.world.season, "current", "spring"))
        weather_name = getattr(frame.world.weather_system, "current_weather", "clear")
        weather_color = weather_tint(weather_name)
        mix = mix_color(base_tint, weather_color, 0.22 if weather_name not in {None, "clear"} else 0.0)
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        pygame.draw.rect(overlay, (*mix, 14), overlay.get_rect())
        surface.blit(overlay, (0, 0))
        self._draw_daylight_orb(surface, frame.world.elapsed_seconds, getattr(frame.world.season, "current", "spring"), frame.world.time_of_day)
        self._draw_time_of_day_pass(surface, frame)
        self._draw_weather_pass(surface, frame)
        self._draw_settlement_pass(surface, frame)
        self._draw_ambient_life(surface, frame)
        self._draw_building_fx(surface, frame)
        self._draw_event_beacons(surface, frame)
        self._draw_focus_flare(surface, frame)
        self._draw_ghost_markers(surface, frame)
        self._draw_title_card(surface, frame)

    # ---- Ambient life & building FX (GFX-3 / GFX-4) ----------------------

    def _draw_ambient_life(self, surface: pygame.Surface, frame) -> None:
        """Draw environmental micro-animations: grass sway, falling leaves, water ripples."""
        world_map = frame.world.world_map
        if world_map is None or not hasattr(world_map, "tiles"):
            return
        camera = frame.world.camera
        zoom = max(0.25, float(camera.zoom or 1.0))
        if zoom < 0.25:
            return  # Too zoomed out for ambient particles

        tile_size = max(1, frame.world.tile_size)
        t = frame.world.current_time
        width, height = frame.world.window_size

        # Calculate visible tile range
        cam_x, cam_y = float(camera.x), float(camera.y)
        start_tx = max(0, int(cam_x / tile_size) - 1)
        start_ty = max(0, int(cam_y / tile_size) - 1)
        end_tx = min(getattr(world_map, "width", 40), int((cam_x + width / zoom) / tile_size) + 2)
        end_ty = min(getattr(world_map, "height", 40), int((cam_y + height / zoom) / tile_size) + 2)

        particle_surf = pygame.Surface((width, height), pygame.SRCALPHA)
        particle_count = 0

        for ty in range(start_ty, end_ty, 2):  # Skip every other row for perf
            for tx in range(start_tx, end_tx, 2):
                if particle_count >= 30:
                    break
                tile_row = world_map.tiles[ty] if ty < len(world_map.tiles) else None
                if tile_row is None:
                    continue
                tile = tile_row[tx] if tx < len(tile_row) else None
                if tile is None:
                    continue

                biome = getattr(tile, "biome_type", "plains")
                world_x = tx * tile_size + tile_size // 2
                world_y = ty * tile_size + tile_size // 2
                sx = int((world_x - cam_x) * zoom)
                sy = int((world_y - cam_y) * zoom)

                if not (0 <= sx <= width and 0 <= sy <= height):
                    continue

                seed = (tx * 997 + ty * 131) & 0xFFFF

                if biome in ("plains", "taiga", "tundra"):
                    # Grass sway — sinusoidal offset dots
                    sway = int(2 * zoom * math.sin(t * 1.5 + seed * 0.01))
                    color = (146, 188, 110, 60) if biome == "plains" else (113, 149, 110, 50)
                    pygame.draw.circle(particle_surf, color, (sx + sway, sy), max(1, int(1.5 * zoom)))
                    particle_count += 1

                elif biome == "forest":
                    # Falling leaf — slow descent
                    leaf_y = sy + int(((t * 8 + seed) % 40) * zoom)
                    leaf_x = sx + int(3 * zoom * math.sin(t * 0.8 + seed))
                    if 0 <= leaf_y <= height:
                        color = (180, 140, 80, 80) if ((seed + int(t)) % 3 == 0) else (140, 100, 60, 70)
                        pygame.draw.circle(particle_surf, color, (leaf_x, leaf_y), max(1, int(1.2 * zoom)))
                        particle_count += 1

                elif biome in ("swamp", "snow"):
                    # Water ripple — expanding circle
                    ripple_phase = (t * 0.6 + seed * 0.02) % 3.0
                    if ripple_phase < 2.0:
                        radius = max(2, int(ripple_phase * 4 * zoom))
                        alpha = max(10, int(60 * (1.0 - ripple_phase / 2.0)))
                        color = (88, 155, 194, alpha) if biome == "swamp" else (200, 220, 240, alpha)
                        pygame.draw.circle(particle_surf, color, (sx, sy), radius, 1)
                        particle_count += 1

            if particle_count >= 30:
                break

        surface.blit(particle_surf, (0, 0))

    def _draw_building_fx(self, surface: pygame.Surface, frame) -> None:
        """Draw building smoke and shrine glow effects."""
        zoom = max(0.5, float(frame.world.camera.zoom or 1.0))
        if zoom < 0.4:
            return
        t = frame.world.current_time
        camera = frame.world.camera

        for entity_state in frame.buildings:
            building = entity_state.entity
            btype = str(getattr(building, "building_type", ""))
            screen_x = int((float(getattr(building, "x", 0)) - camera.x) * zoom)
            screen_y = int((float(getattr(building, "y", 0)) - camera.y) * zoom)

            if not (-40 <= screen_x <= frame.world.window_size[0] + 40 and -40 <= screen_y <= frame.world.window_size[1] + 40):
                continue

            if btype in ("workshop", "house"):
                # Chimney smoke — 2-3 small gray circles rising
                active = bool(getattr(building, "occupants", None) or getattr(building, "aura_strength", 0) > 0.1)
                if active:
                    smoke_surf = pygame.Surface((20, 40), pygame.SRCALPHA)
                    for i in range(3):
                        smoke_y = int(35 - ((t * 12 + i * 8 + getattr(building, "id", 0)) % 30))
                        smoke_x = 10 + int(2 * math.sin(t * 0.8 + i * 2))
                        alpha = max(15, int(55 - smoke_y * 1.5))
                        radius = max(1, int(1.5 * zoom + (35 - smoke_y) * 0.05))
                        pygame.draw.circle(smoke_surf, (180, 175, 170, alpha), (smoke_x, smoke_y), radius)
                    surface.blit(smoke_surf, (screen_x - 10, screen_y - int(36 * zoom)))

            elif btype == "shrine":
                # Aura glow — pulsing doctrine-colored circle beneath
                aura = float(getattr(building, "aura_strength", 0.0) or 0.0)
                if aura > 0.05:
                    faction_id = getattr(building, "faction_id", None)
                    factions = getattr(frame.world.faction_manager, "factions", {}) if frame.world.faction_manager else {}
                    faction = factions.get(faction_id)
                    doctrine = getattr(faction, "primary_doctrine", None) if faction else None
                    color = doctrine_color(doctrine)
                    pulse = 0.6 + 0.4 * abs(math.sin(t * 2.0 + getattr(building, "id", 0)))
                    radius = max(8, int(16 * zoom * pulse * aura))
                    glow = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                    pygame.draw.circle(glow, (*color, int(28 * pulse * aura)), (radius, radius), radius)
                    pygame.draw.circle(glow, (*color, int(64 * pulse * aura)), (radius, radius), max(2, radius // 2))
                    surface.blit(glow, (screen_x - radius, screen_y - radius + int(4 * zoom)))

            elif btype == "farm":
                # Crop sparkle during summer
                season = str(getattr(frame.world.season, "current", "spring")).lower()
                if season == "summer":
                    sparkle_surf = pygame.Surface((8, 8), pygame.SRCALPHA)
                    if int(t * 3 + getattr(building, "id", 0)) % 4 == 0:
                        pygame.draw.circle(sparkle_surf, (200, 220, 100, 100), (4, 4), max(1, int(1.5 * zoom)))
                        surface.blit(sparkle_surf, (screen_x - 2, screen_y - int(8 * zoom)))


