from __future__ import annotations

import pygame

from graphics.content import snap_zoom_level


class TerrainRenderer:
    def __init__(self, sprite_library, config):
        self.sprite_library = sprite_library
        self.config = config
        self._chunk_cache: dict[tuple, pygame.Surface] = {}
        self._scaled_cache: dict[tuple, pygame.Surface] = {}

    def _trim_cache(self, cache: dict, limit: int) -> None:
        while len(cache) > limit:
            cache.pop(next(iter(cache)))

    def _chunk_zone_signature(self, chunk, city_planner, tile_size: int, chunk_size: int) -> tuple[str, ...]:
        zones = getattr(city_planner, "zones", {})
        hits: list[str] = []
        for zone_pos, zone_type in zones.items():
            if not isinstance(zone_pos, tuple) or len(zone_pos) != 2:
                continue
            zone_world_x = int(zone_pos[0]) * tile_size
            zone_world_y = int(zone_pos[1]) * tile_size
            if chunk.world_x <= zone_world_x < chunk.world_x + chunk_size and chunk.world_y <= zone_world_y < chunk.world_y + chunk_size:
                hits.append(f"{zone_type}:{zone_pos[0]}:{zone_pos[1]}")
        return tuple(hits[:32])

    def _chunk_signature(self, chunk, world_state) -> tuple:
        season_name = str(getattr(world_state.season, "current", "spring"))
        weather_name = str(getattr(world_state.weather_system, "current_weather", "clear"))
        district = str(world_state.settlement_state.get("district_identity", "homestead"))
        zone_signature = self._chunk_zone_signature(chunk, world_state.city_planner, world_state.tile_size, world_state.chunk_size)
        center_tile = getattr(
            chunk,
            "tiles",
            {},
        ).get((world_state.chunk_size // max(1, world_state.tile_size) // 2, world_state.chunk_size // max(1, world_state.tile_size) // 2), "plains")
        water_signature = (len(getattr(chunk, "water_tiles", ())), len(getattr(chunk, "river_tiles", ())), getattr(chunk, "region_id", None))
        return (chunk.world_x, chunk.world_y, center_tile, season_name, weather_name, district, zone_signature, water_signature)

    def _draw_transition_edges(self, surface: pygame.Surface, chunk, world_state) -> None:
        tile_size = world_state.tile_size
        for (tile_x, tile_y), biome_type in getattr(chunk, "tiles", {}).items():
            local_x = tile_x * tile_size
            local_y = tile_y * tile_size
            neighbors = {
                "north": chunk.tiles.get((tile_x, tile_y - 1)),
                "south": chunk.tiles.get((tile_x, tile_y + 1)),
                "west": chunk.tiles.get((tile_x - 1, tile_y)),
                "east": chunk.tiles.get((tile_x + 1, tile_y)),
            }
            for edge, neighbor_biome in neighbors.items():
                if neighbor_biome and neighbor_biome != biome_type:
                    overlay = self.sprite_library.get_transition_surface(
                        biome_type,
                        neighbor_biome,
                        edge,
                        getattr(world_state.season, "current", "spring"),
                        tile_size,
                    )
                    surface.blit(overlay, (local_x, local_y))

    def _draw_district_overlays(self, surface: pygame.Surface, chunk, world_state) -> None:
        zones = getattr(world_state.city_planner, "zones", {})
        tile_size = world_state.tile_size
        chunk_size = world_state.chunk_size
        for zone_pos, zone_type in zones.items():
            if not isinstance(zone_pos, tuple) or len(zone_pos) != 2:
                continue
            zone_world_x = int(zone_pos[0]) * tile_size
            zone_world_y = int(zone_pos[1]) * tile_size
            if not (chunk.world_x <= zone_world_x < chunk.world_x + chunk_size and chunk.world_y <= zone_world_y < chunk.world_y + chunk_size):
                continue
            local_x = zone_world_x - chunk.world_x
            local_y = zone_world_y - chunk.world_y
            overlay = self.sprite_library.get_district_overlay(str(zone_type), tile_size, variant=(zone_pos[0] + zone_pos[1]) % 3)
            surface.blit(overlay, (local_x, local_y))

    def _draw_water_features(self, surface: pygame.Surface, chunk, world_state) -> None:
        tile_size = world_state.tile_size
        import random
        chunk_seed_x, chunk_seed_y = self._chunk_seed_coords(chunk, world_state)
        for tile_x, tile_y in getattr(chunk, "water_tiles", ()):
            local_x = tile_x * tile_size
            local_y = tile_y * tile_size
            rng = random.Random(hash((chunk_seed_x, chunk_seed_y, tile_x, tile_y)))
            for _ in range(4):
                cx = local_x + rng.randint(3, tile_size - 3)
                cy = local_y + rng.randint(3, tile_size - 3)
                cr = rng.randint(tile_size // 4, int(tile_size // 1.5))
                pygame.draw.circle(surface, (62, 108, 156, 180), (cx, cy), cr)
                pygame.draw.circle(surface, (130, 186, 220, 100), (cx, cy), cr, max(1, cr // 4))
                
        for tile_x, tile_y in getattr(chunk, "river_tiles", ()):
            local_x = tile_x * tile_size
            local_y = tile_y * tile_size
            rng = random.Random(hash((chunk_seed_x, chunk_seed_y, tile_x, tile_y)))
            pts = [
                (local_x + rng.randint(4, tile_size - 4), local_y - 2),
                (local_x + rng.randint(4, tile_size - 4), local_y + tile_size // 2),
                (local_x + rng.randint(4, tile_size - 4), local_y + tile_size + 2)
            ]
            pygame.draw.lines(surface, (106, 178, 220, 160), False, pts, max(3, tile_size // 4))

    def _draw_weather_patina(self, surface: pygame.Surface, world_state) -> None:
        weather_name = str(getattr(world_state.weather_system, "current_weather", "clear"))
        if weather_name == "clear":
            return
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        if weather_name in {"rain", "storm"}:
            overlay.fill((72, 86, 108, 30 if weather_name == "rain" else 42))
        elif weather_name == "snow":
            overlay.fill((214, 224, 231, 36))
        elif weather_name == "heatwave":
            overlay.fill((224, 174, 112, 24))
        surface.blit(overlay, (0, 0))

    def _get_slope(self, chunk, tile_x: int, tile_y: int) -> float:
        elevations = getattr(chunk, "elevations", {})
        if not elevations:
            return 0.0
        e = elevations.get((tile_x, tile_y), getattr(chunk, "elevation_avg", 0.0))
        nw = elevations.get((tile_x - 1, tile_y - 1), e)
        se = elevations.get((tile_x + 1, tile_y + 1), e)
        return se - nw

    def _draw_procedural_clutter(self, surface: pygame.Surface, chunk, world_state) -> None:
        tile_size = world_state.tile_size
        import random
        chunk_seed_x, chunk_seed_y = self._chunk_seed_coords(chunk, world_state)
        seed_base = hash((chunk_seed_x, chunk_seed_y))
        
        for (tile_x, tile_y), biome_type in getattr(chunk, "tiles", {}).items():
            if biome_type in {"mountains", "snow", "water", "desert", "tundra"}:
                continue
            rng = random.Random(seed_base + tile_x * 73 + tile_y * 191)
            if rng.random() < 0.4:
                clutter_type = rng.choice(["grass", "pebble", "flower"])
                local_x = tile_x * tile_size + rng.randint(2, tile_size - 6)
                local_y = tile_y * tile_size + rng.randint(2, tile_size - 6)
                
                if clutter_type == "grass":
                    pygame.draw.line(surface, (110, 150, 80, 180), (local_x, local_y + 4), (local_x - 1, local_y), 1)
                    pygame.draw.line(surface, (120, 160, 90, 180), (local_x, local_y + 4), (local_x + 1, local_y), 1)
                elif clutter_type == "pebble":
                    pygame.draw.circle(surface, (140, 140, 140, 180), (local_x, local_y), 1)
                elif clutter_type == "flower" and biome_type in {"plains", "forest"}:
                    pygame.draw.circle(surface, rng.choice([(250, 100, 100, 200), (200, 200, 250, 200), (250, 250, 100, 200)]), (local_x, local_y), 1)


    def _chunk_seed_coords(self, chunk, world_state) -> tuple[int, int]:
        chunk_x = getattr(chunk, "chunk_x", None)
        chunk_y = getattr(chunk, "chunk_y", None)
        if isinstance(chunk_x, int) and isinstance(chunk_y, int):
            return (chunk_x, chunk_y)
        chunk_size = max(1, int(getattr(world_state, "chunk_size", 1) or 1))
        world_x = int(getattr(chunk, "world_x", 0) or 0)
        world_y = int(getattr(chunk, "world_y", 0) or 0)
        return (world_x // chunk_size, world_y // chunk_size)

    def _build_chunk_surface(self, chunk, world_state) -> pygame.Surface:
        tile_size = world_state.tile_size
        chunk_size = world_state.chunk_size
        season_name = getattr(world_state.season, "current", "spring")
        surface = pygame.Surface((chunk_size, chunk_size), pygame.SRCALPHA)
        for (tile_x, tile_y), biome_type in getattr(chunk, "tiles", {}).items():
            local_x = tile_x * tile_size
            local_y = tile_y * tile_size
            variant = ((chunk.world_x // max(1, tile_size)) + tile_x * 17 + (chunk.world_y // max(1, tile_size)) + tile_y * 13) % 3
            tile_surface = self.sprite_library.get_tile_surface(biome_type, season_name, tile_size, variant)
            
            slope = self._get_slope(chunk, tile_x, tile_y)
            shade_alpha = max(0, min(140, int(abs(slope) * 2000)))
            if shade_alpha > 0:
                shade = pygame.Surface((tile_size, tile_size), pygame.SRCALPHA)
                if slope > 0:
                    shade.fill((255, 255, 255, int(shade_alpha * 0.5)))
                else:
                    shade.fill((0, 0, 0, shade_alpha))
                tile_surface = tile_surface.copy()
                tile_surface.blit(shade, (0, 0))
                
            surface.blit(tile_surface, (local_x, local_y))
        self._draw_transition_edges(surface, chunk, world_state)
        self._draw_water_features(surface, chunk, world_state)
        self._draw_procedural_clutter(surface, chunk, world_state)
        if self.config.enable_settlement_overlays:
            self._draw_district_overlays(surface, chunk, world_state)
        self._draw_weather_patina(surface, world_state)
        return surface

    def _world_to_band(self, x: float, y: float, world_state) -> tuple[int, int]:
        zoom_band = float(world_state.zoom_band or 1.0)
        return (int((x - world_state.camera.x) * zoom_band), int((y - world_state.camera.y) * zoom_band))

    def _render_local_chunks(self, surface: pygame.Surface, world_state, zoom_band: float) -> None:
        for chunk in getattr(world_state.world_map, "chunks", {}).values():
            draw_x = int((chunk.world_x - world_state.camera.x) * zoom_band)
            draw_y = int((chunk.world_y - world_state.camera.y) * zoom_band)
            draw_w = max(1, int(world_state.chunk_size * zoom_band))
            draw_h = max(1, int(world_state.chunk_size * zoom_band))
            if not (draw_x + draw_w > 0 and draw_x < world_state.window_size[0] and draw_y + draw_h > 0 and draw_y < world_state.window_size[1]):
                continue
            signature = self._chunk_signature(chunk, world_state)
            if signature not in self._chunk_cache:
                self._chunk_cache[signature] = self._build_chunk_surface(chunk, world_state)
                self._trim_cache(self._chunk_cache, self.config.chunk_cache_limit)
            scaled_key = (signature, (draw_w, draw_h))
            if scaled_key not in self._scaled_cache:
                self._scaled_cache[scaled_key] = pygame.transform.scale(self._chunk_cache[signature], (draw_w, draw_h))
                self._trim_cache(self._scaled_cache, self.config.scaled_cache_limit)
            surface.blit(self._scaled_cache[scaled_key], (draw_x, draw_y))

    def _draw_routes(self, surface: pygame.Surface, world_state, *, width: int, color: tuple[int, int, int]) -> None:
        for route in world_state.route_network:
            points = []
            for point in route.get("points", []):
                try:
                    points.append(self._world_to_band(float(point.get("x", 0.0)), float(point.get("y", 0.0)), world_state))
                except (AttributeError, TypeError, ValueError):
                    continue
            if len(points) >= 2:
                pygame.draw.lines(surface, color, False, points, width)

    def _draw_water_network(self, surface: pygame.Surface, world_state, *, width: int, color: tuple[int, int, int]) -> None:
        for segment in world_state.water_network:
            points = []
            for point in segment.get("points", []):
                try:
                    points.append(self._world_to_band(float(point.get("x", 0.0)), float(point.get("y", 0.0)), world_state))
                except (AttributeError, TypeError, ValueError):
                    continue
            if len(points) >= 2:
                pygame.draw.lines(surface, color, False, points, width)

    def _draw_landmarks(self, surface: pygame.Surface, world_state, *, radius: int) -> None:
        for landmark in world_state.landmark_markers:
            try:
                screen_x, screen_y = self._world_to_band(float(landmark.get("x", 0.0)), float(landmark.get("y", 0.0)), world_state)
            except (TypeError, ValueError):
                continue
            pygame.draw.circle(surface, (236, 205, 146), (screen_x, screen_y), radius)
            pygame.draw.circle(surface, (96, 70, 48), (screen_x, screen_y), radius, 1)

    def _render_macro_map(self, surface: pygame.Surface, world_state) -> None:
        for region in world_state.region_overlay:
            rect_data = region.get("world_rect")
            if not isinstance(rect_data, (list, tuple)) or len(rect_data) != 4:
                continue
            world_x, world_y, world_w, world_h = rect_data
            screen_x, screen_y = self._world_to_band(float(world_x), float(world_y), world_state)
            draw_w = max(2, int(float(world_w) * world_state.zoom_band))
            draw_h = max(2, int(float(world_h) * world_state.zoom_band))
            if not (screen_x + draw_w > 0 and screen_x < world_state.window_size[0] and screen_y + draw_h > 0 and screen_y < world_state.window_size[1]):
                continue
            biome = str(region.get("biome", "plains"))
            preview = self.sprite_library.get_tile_surface(biome, getattr(world_state.season, "current", "spring"), 8, 0)
            preview = pygame.transform.scale(preview, (draw_w, draw_h))
            surface.blit(preview, (screen_x, screen_y))
            polity_id = region.get("claimed_by")
            if polity_id is not None:
                for polity in world_state.polity_overlay:
                    if polity.get("polity_id") == polity_id:
                        accent = tuple(polity.get("accent_color", (180, 160, 120)))
                        overlay = pygame.Surface((draw_w, draw_h), pygame.SRCALPHA)
                        overlay.fill((*accent[:3], 42))
                        surface.blit(overlay, (screen_x, screen_y))
                        break
            pygame.draw.rect(surface, (34, 38, 42), (screen_x, screen_y, draw_w, draw_h), 1)
        self._draw_water_network(surface, world_state, width=2, color=(100, 168, 214))
        self._draw_routes(surface, world_state, width=1, color=(168, 138, 104))
        self._draw_landmarks(surface, world_state, radius=4)

    def _render_frontier_map(self, surface: pygame.Surface, world_state, zoom_band: float) -> None:
        self._render_local_chunks(surface, world_state, zoom_band)
        self._draw_water_network(surface, world_state, width=2, color=(106, 178, 220))
        self._draw_routes(surface, world_state, width=2, color=(188, 154, 118))
        self._draw_landmarks(surface, world_state, radius=5)
        for polity in world_state.polity_overlay:
            accent = tuple(polity.get("accent_color", (170, 150, 120)))
            for region_id in polity.get("claimed_region_ids", []):
                matching = next((region for region in world_state.region_overlay if region.get("region_id") == region_id), None)
                if matching is None:
                    continue
                rect_data = matching.get("world_rect")
                if not isinstance(rect_data, (list, tuple)) or len(rect_data) != 4:
                    continue
                world_x, world_y, world_w, world_h = rect_data
                screen_x, screen_y = self._world_to_band(float(world_x), float(world_y), world_state)
                draw_w = max(1, int(float(world_w) * world_state.zoom_band))
                draw_h = max(1, int(float(world_h) * world_state.zoom_band))
                pygame.draw.rect(surface, accent, (screen_x, screen_y, draw_w, draw_h), 1)

    def render(self, surface: pygame.Surface, frame) -> None:
        world_state = frame.world
        camera = world_state.camera
        zoom = max(camera.min_zoom, min(camera.max_zoom, float(camera.zoom or 1.0)))
        zoom_band = snap_zoom_level(zoom, self.config.snap_zoom_levels)
        if zoom_band <= 0.25:
            self._render_macro_map(surface, world_state)
            return
        if zoom_band <= 0.75:
            self._render_frontier_map(surface, world_state, zoom_band)
            return
        self._render_local_chunks(surface, world_state, zoom_band)
