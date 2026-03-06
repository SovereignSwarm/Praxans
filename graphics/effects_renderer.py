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
        self._draw_event_beacons(surface, frame)
        self._draw_focus_flare(surface, frame)
