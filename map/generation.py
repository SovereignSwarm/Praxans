from __future__ import annotations

import math
import random
from collections import Counter

from map.models import (
    ChunkState,
    Landmark,
    PolityMapState,
    Route,
    SettlementState,
    WorldProfile,
    WorldRegion,
    WorldSeed,
)


BIOME_TYPES = ("plains", "forest", "mountains", "desert", "snow", "swamp", "taiga", "tundra")

_POLITY_DOCTRINES = ("growth", "security", "industry", "exploration", "harmony")
_POLITY_COLORS = (
    (214, 171, 112),
    (118, 156, 204),
    (166, 122, 94),
    (136, 180, 136),
    (188, 152, 198),
    (194, 124, 124),
    (126, 160, 172),
    (214, 190, 130),
)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _lerp(start: float, end: float, t: float) -> float:
    return start + ((end - start) * t)


def _smoothstep(value: float) -> float:
    value = _clamp(value, 0.0, 1.0)
    return value * value * (3.0 - (2.0 * value))


def _hash_noise(ix: int, iy: int, seed: int) -> float:
    value = (ix * 374761393) + (iy * 668265263) + (seed * 2147483647)
    value = (value ^ (value >> 13)) * 1274126177
    value ^= value >> 16
    return (value & 0xFFFFFFFF) / 0xFFFFFFFF


def _value_noise(x: float, y: float, seed: int) -> float:
    x0 = math.floor(x)
    y0 = math.floor(y)
    x1 = x0 + 1
    y1 = y0 + 1
    sx = _smoothstep(x - x0)
    sy = _smoothstep(y - y0)
    n00 = _hash_noise(int(x0), int(y0), seed)
    n10 = _hash_noise(int(x1), int(y0), seed)
    n01 = _hash_noise(int(x0), int(y1), seed)
    n11 = _hash_noise(int(x1), int(y1), seed)
    ix0 = _lerp(n00, n10, sx)
    ix1 = _lerp(n01, n11, sx)
    return (_lerp(ix0, ix1, sy) * 2.0) - 1.0


def _fractal_noise(x: float, y: float, seed: int, *, octaves: int = 4, lacunarity: float = 2.0, gain: float = 0.5) -> float:
    amplitude = 1.0
    frequency = 1.0
    total = 0.0
    normalizer = 0.0
    for octave in range(octaves):
        total += _value_noise(x * frequency, y * frequency, seed + (octave * 31)) * amplitude
        normalizer += amplitude
        amplitude *= gain
        frequency *= lacunarity
    return total / max(0.0001, normalizer)


def build_world_profile(scenario_profile: dict | None, *, chunk_size: int, tile_size: int) -> WorldProfile:
    scenario_profile = dict(scenario_profile or {})
    worldgen = dict(scenario_profile.get("worldgen", {}) or {})
    zoom_bands = tuple(float(level) for level in worldgen.get("zoom_bands", (0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)))
    return WorldProfile(
        chunk_cols=max(4, int(worldgen.get("chunk_cols", 16) or 16)),
        chunk_rows=max(3, int(worldgen.get("chunk_rows", 12) or 12)),
        region_cols=max(2, int(worldgen.get("region_cols", 8) or 8)),
        region_rows=max(2, int(worldgen.get("region_rows", 6) or 6)),
        chunk_size=chunk_size,
        tile_size=tile_size,
        climate_bias=str(worldgen.get("climate_bias", "temperate")),
        ruggedness=_clamp(float(worldgen.get("ruggedness", 0.55) or 0.55), 0.05, 1.0),
        water_abundance=_clamp(float(worldgen.get("water_abundance", 0.5) or 0.5), 0.05, 1.0),
        hazard_density=_clamp(float(worldgen.get("hazard_density", 0.45) or 0.45), 0.05, 1.0),
        polity_count=max(2, int(worldgen.get("polity_count", 5) or 5)),
        polity_cap=max(2, int(worldgen.get("polity_cap", 8) or 8)),
        resource_richness=_clamp(float(worldgen.get("resource_richness", 1.0) or 1.0), 0.2, 2.0),
        mutation_pressure=_clamp(float(worldgen.get("mutation_pressure", scenario_profile.get("mutation_scale", 1.0) or 1.0)), 0.5, 3.0),
        temperature_bias=_clamp(float(worldgen.get("temperature_bias", 0.0) or 0.0), -0.4, 0.4),
        moisture_bias=_clamp(float(worldgen.get("moisture_bias", 0.0) or 0.0), -0.4, 0.4),
        zoom_bands=zoom_bands,
    )


def _climate_bias_adjustments(climate_bias: str) -> tuple[float, float]:
    normalized = str(climate_bias or "temperate").lower()
    if normalized in {"cold", "winter", "frozen"}:
        return (-0.22, -0.04)
    if normalized in {"wet", "floodplain", "verdant"}:
        return (0.02, 0.2)
    if normalized in {"arid", "dry", "desert"}:
        return (0.16, -0.2)
    if normalized in {"tropical", "jungle", "lush"}:
        return (0.12, 0.24)
    if normalized in {"volcanic", "ash", "inferno"}:
        return (0.28, -0.15)
    return (0.0, 0.0)


def _region_center(profile: WorldProfile, col: int, row: int) -> tuple[float, float]:
    return (
        (col * profile.region_width) + (profile.region_width / 2.0),
        (row * profile.region_height) + (profile.region_height / 2.0),
    )


def _neighbor_region_ids(profile: WorldProfile, col: int, row: int) -> list[str]:
    neighbors: list[str] = []
    for offset_x, offset_y in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        next_col = col + offset_x
        next_row = row + offset_y
        if 0 <= next_col < profile.region_cols and 0 <= next_row < profile.region_rows:
            neighbors.append(f"r{next_col}_{next_row}")
    return neighbors


def _pick_biome(elevation: float, temperature: float, moisture: float, coastal: bool, river: bool) -> str:
    if elevation > 0.78:
        return "mountains"
    if temperature < 0.22:
        return "snow" if moisture > 0.4 else "tundra"
    if temperature < 0.34:
        return "taiga" if moisture > 0.36 else "tundra"
    if moisture < 0.18 and temperature > 0.56:
        return "desert"
    if moisture > 0.72 and temperature > 0.36:
        return "swamp" if coastal or river else "forest"
    if moisture > 0.52:
        return "forest"
    return "plains"


def _build_regions(seed: int, profile: WorldProfile) -> dict[str, WorldRegion]:
    climate_temp_bias, climate_moisture_bias = _climate_bias_adjustments(profile.climate_bias)
    regions: dict[str, WorldRegion] = {}
    for row in range(profile.region_rows):
        latitude = row / max(1, profile.region_rows - 1)
        for col in range(profile.region_cols):
            longitude = col / max(1, profile.region_cols - 1)
            region_id = f"r{col}_{row}"
            world_x = col * profile.region_width
            world_y = row * profile.region_height
            nx = longitude * 4.0
            ny = latitude * 4.0

            continental = _fractal_noise(nx + 1.4, ny + 2.1, seed + 11, octaves=5, gain=0.56)
            rugged = _fractal_noise(nx + 6.3, ny + 4.7, seed + 29, octaves=4, gain=0.52)
            moisture_field = _fractal_noise(nx + 9.7, ny + 7.5, seed + 43, octaves=4, gain=0.55)

            spine_x = 0.28 + ((_fractal_noise(longitude * 2.0, 0.5, seed + 17, octaves=2, gain=0.6) + 1.0) * 0.18)
            ridge = max(0.0, 1.0 - abs(longitude - spine_x) * 3.4)
            inland = 1.0 - min(longitude, 1.0 - longitude, latitude, 1.0 - latitude) * 2.4
            elevation = _clamp(0.48 + (continental * 0.22) + (rugged * profile.ruggedness * 0.38) + (ridge ** 1.8) * 0.34 - inland * 0.08, 0.0, 1.0)
            coastal = continental < -0.18 or row in {0, profile.region_rows - 1} or col in {0, profile.region_cols - 1}
            temperature = _clamp(
                0.82
                - (latitude * 0.72)
                - (elevation * 0.24)
                + (climate_temp_bias + profile.temperature_bias)
                - (0.06 if coastal and latitude > 0.65 else 0.0),
                0.0,
                1.0,
            )
            rain_shadow = max(0.0, ridge - 0.45) * 0.18
            moisture = _clamp(
                0.48
                + (moisture_field * 0.26)
                + ((profile.water_abundance - 0.5) * 0.36)
                + (0.14 if coastal else 0.0)
                + climate_moisture_bias
                + profile.moisture_bias
                - rain_shadow,
                0.0,
                1.0,
            )
            river = (elevation > 0.48 and moisture > 0.46 and rugged > -0.12) or (coastal and moisture > 0.54)
            fertility = _clamp((moisture * 0.48) + ((1.0 - abs(temperature - 0.52)) * 0.32) + ((1.0 - elevation) * 0.2), 0.0, 1.0)
            defensibility = _clamp((elevation * 0.58) + (ridge * 0.24) + ((1.0 - inland) * 0.12), 0.0, 1.0)
            water_score = _clamp((moisture * 0.55) + (0.2 if coastal else 0.0) + (0.2 if river else 0.0), 0.0, 1.0)
            frontier_score = _clamp((defensibility * 0.34) + ((1.0 - fertility) * 0.24) + (0.2 if coastal else 0.0) + (0.1 if river else 0.0), 0.0, 1.0)
            route_score = _clamp((fertility * 0.34) + (water_score * 0.28) + ((1.0 - rugged) * 0.16) + (0.12 if coastal else 0.0), 0.0, 1.0)
            biome = _pick_biome(elevation, temperature, moisture, coastal, river)
            regions[region_id] = WorldRegion(
                region_id=region_id,
                col=col,
                row=row,
                world_rect=(world_x, world_y, profile.region_width, profile.region_height),
                biome=biome,
                elevation=elevation,
                moisture=moisture,
                temperature=temperature,
                fertility=fertility,
                defensibility=defensibility,
                water_score=water_score,
                frontier_score=frontier_score,
                route_score=route_score,
                coastal=coastal,
                river=river,
            )
    return regions


def _route_points_between(profile: WorldProfile, start_region: WorldRegion, end_region: WorldRegion) -> tuple[tuple[float, float], ...]:
    col1 = start_region.col
    row1 = start_region.row
    col2 = end_region.col
    row2 = end_region.row
    points: list[tuple[float, float]] = []
    dx = abs(col2 - col1)
    dy = -abs(row2 - row1)
    sx = 1 if col1 < col2 else -1
    sy = 1 if row1 < row2 else -1
    err = dx + dy
    c, r = col1, row1
    while True:
        points.append(_region_center(profile, c, r))
        if c == col2 and r == row2:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            c += sx
        if e2 <= dx:
            err += dx
            r += sy
    return tuple(points)


def _select_home_regions(seed: int, profile: WorldProfile, regions: dict[str, WorldRegion]) -> list[WorldRegion]:
    rng = random.Random(seed + 201)
    candidates = [
        region
        for region in regions.values()
        if region.biome not in {"mountains", "snow"} and region.fertility >= 0.28 and region.water_score >= 0.22
    ]
    candidates.sort(key=lambda region: (region.route_score + region.fertility + region.defensibility), reverse=True)
    selected: list[WorldRegion] = []
    for candidate in candidates:
        if len(selected) >= profile.polity_count:
            break
        if all(abs(candidate.col - other.col) + abs(candidate.row - other.row) >= 2 for other in selected):
            selected.append(candidate)
    while len(selected) < profile.polity_count and candidates:
        selected.append(candidates.pop(rng.randrange(len(candidates))))
    return selected


def _build_polities(seed: int, profile: WorldProfile, regions: dict[str, WorldRegion]) -> tuple[list[SettlementState], list[Route], list[PolityMapState]]:
    homes = _select_home_regions(seed, profile, regions)
    settlements: list[SettlementState] = []
    routes: list[Route] = []
    polities: list[PolityMapState] = []
    for polity_index, home_region in enumerate(homes):
        center_x, center_y = _region_center(profile, home_region.col, home_region.row)
        settlement_id = f"set_{polity_index}"
        settlements.append(
            SettlementState(
                settlement_id=settlement_id,
                region_id=home_region.region_id,
                x=center_x,
                y=center_y,
                settlement_type="capital",
                population=7 + polity_index,
                prosperity=_clamp((home_region.fertility * 0.6) + (home_region.route_score * 0.4), 0.0, 1.0),
                water_access=home_region.water_score,
                route_access=home_region.route_score,
                polity_id=polity_index,
            )
        )

    for source in settlements:
        source_region = regions[source.region_id]
        others = [candidate for candidate in settlements if candidate.settlement_id != source.settlement_id]
        others.sort(key=lambda candidate: abs(regions[candidate.region_id].col - source_region.col) + abs(regions[candidate.region_id].row - source_region.row))
        for target in others[:2]:
            route_id = f"route_{source.settlement_id}_{target.settlement_id}"
            if any(existing.route_id == route_id or existing.route_id == f"route_{target.settlement_id}_{source.settlement_id}" for existing in routes):
                continue
            target_region = regions[target.region_id]
            route_points = _route_points_between(profile, source_region, target_region)
            risk = _clamp((source_region.frontier_score + target_region.frontier_score) * 0.5, 0.0, 1.0)
            routes.append(
                Route(
                    route_id=route_id,
                    route_type="trade",
                    start_region_id=source.region_id,
                    end_region_id=target.region_id,
                    points=route_points,
                    risk=risk,
                )
            )

    claims: dict[int, list[str]] = {index: [] for index in range(len(settlements))}
    for region in regions.values():
        best_owner = None
        best_score = float("-inf")
        for settlement in settlements:
            home = regions[settlement.region_id]
            distance = abs(region.col - home.col) + abs(region.row - home.row)
            score = 2.2 - (distance * 0.42) + (region.route_score * 0.45) + (region.defensibility * 0.18) - (region.frontier_score * 0.16)
            if score > best_score:
                best_score = score
                best_owner = settlement.polity_id
        if best_owner is not None:
            claims[best_owner].append(region.region_id)

    for polity_index, settlement in enumerate(settlements):
        doctrine_bias = _POLITY_DOCTRINES[polity_index % len(_POLITY_DOCTRINES)]
        trade_route_ids = tuple(
            route.route_id
            for route in routes
            if route.start_region_id == settlement.region_id or route.end_region_id == settlement.region_id
        )
        polities.append(
            PolityMapState(
                polity_id=polity_index,
                name=f"Frontier Polity {polity_index + 1}",
                home_region_id=settlement.region_id,
                doctrine_bias=doctrine_bias,
                frontier_pressure=_clamp(regions[settlement.region_id].frontier_score * 100.0, 0.0, 100.0),
                settlement_ids=(settlement.settlement_id,),
                claimed_region_ids=tuple(claims.get(polity_index, [])),
                trade_route_ids=trade_route_ids,
                capital_settlement_id=settlement.settlement_id,
                accent_color=_POLITY_COLORS[polity_index % len(_POLITY_COLORS)],
            )
        )
    return settlements, routes, polities


def _build_landmarks(seed: int, profile: WorldProfile, regions: dict[str, WorldRegion]) -> list[Landmark]:
    rng = random.Random(seed + 401)
    fertile = sorted(regions.values(), key=lambda region: (region.fertility + region.route_score), reverse=True)
    defensive = sorted(regions.values(), key=lambda region: (region.defensibility + region.frontier_score), reverse=True)
    scenic = sorted(regions.values(), key=lambda region: (region.water_score + (0.3 if region.coastal else 0.0)), reverse=True)
    desolate = sorted(regions.values(), key=lambda region: (1.0 - region.fertility + region.elevation * 0.5), reverse=True)
    isolated = sorted(regions.values(), key=lambda region: (1.0 - region.route_score + (0.5 if region.biome == "forest" else 0.0)), reverse=True)
    picks = [
        ("granary", fertile[0] if fertile else None),
        ("citadel", defensive[0] if defensive else None),
        ("crossing", scenic[0] if scenic else None),
        ("ruins", desolate[0] if desolate else None),
        ("sanctuary", isolated[0] if isolated else None),
    ]
    used_region_ids: set[str] = set()
    landmarks: list[Landmark] = []
    for index, (category, region) in enumerate(picks):
        if region is None or region.region_id in used_region_ids:
            continue
        used_region_ids.add(region.region_id)
        x, y = _region_center(profile, region.col, region.row)
        names = {
            "granary": ("Amber Fields", "Harvest Rise", "Saffron Reach"),
            "citadel": ("Stonewatch", "Ridge Crown", "Iron Bastion"),
            "crossing": ("Blueford", "Salt Mouth", "Reed Crossing"),
            "ruins": ("Shattered Spire", "Dust Echoes", "Old Scars"),
            "sanctuary": ("Verdant Hollow", "Silent Grove", "Hidden Shrine"),
        }
        options = names.get(category, ("Frontier Mark",))
        landmarks.append(
            Landmark(
                landmark_id=f"landmark_{index}",
                region_id=region.region_id,
                name=options[rng.randrange(len(options))],
                category=category,
                x=x,
                y=y,
                importance=_clamp(0.55 + (region.route_score * 0.2) + (region.frontier_score * 0.18), 0.0, 1.0),
            )
        )
    return landmarks


def _river_paths(profile: WorldProfile, regions: dict[str, WorldRegion]) -> list[list[tuple[float, float]]]:
    sources = sorted(
        [region for region in regions.values() if region.biome == "mountains" or (region.river and region.elevation > 0.52)],
        key=lambda region: region.elevation,
        reverse=True,
    )[: max(2, (profile.region_cols * profile.region_rows) // 12)]
    paths: list[list[tuple[float, float]]] = []
    for source in sources:
        current = source
        visited = {current.region_id}
        points = [list(_region_center(profile, current.col, current.row))]
        for _ in range(profile.region_cols + profile.region_rows):
            neighbors = [regions[neighbor_id] for neighbor_id in _neighbor_region_ids(profile, current.col, current.row)]
            if not neighbors:
                break
            neighbors.sort(key=lambda region: (region.elevation, 0 if region.coastal else 1))
            next_region = None
            for candidate in neighbors:
                if candidate.region_id not in visited:
                    next_region = candidate
                    break
            if next_region is None:
                break
            current = next_region
            visited.add(current.region_id)
            points.append(list(_region_center(profile, current.col, current.row)))
            if current.coastal:
                break
        if len(points) >= 2:
            paths.append([(float(x), float(y)) for x, y in points])
    return paths


def _distance_squared_to_polyline(x: float, y: float, polyline: list[tuple[float, float]]) -> float:
    best = float("inf")
    for index in range(len(polyline) - 1):
        x1, y1 = polyline[index]
        x2, y2 = polyline[index + 1]
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 0.0001 and abs(dy) < 0.0001:
            best = min(best, (x - x1)**2 + (y - y1)**2)
            continue
        t = _clamp((((x - x1) * dx) + ((y - y1) * dy)) / ((dx * dx) + (dy * dy)), 0.0, 1.0)
        projected_x = x1 + (dx * t)
        projected_y = y1 + (dy * t)
        best = min(best, (x - projected_x)**2 + (y - projected_y)**2)
    return best


def _chunk_tiles(seed: int, profile: WorldProfile, chunk_x: int, chunk_y: int, regions: dict[str, WorldRegion], river_paths: list[list[tuple[float, float]]]) -> ChunkState:
    tiles_per_chunk = profile.chunk_size // profile.tile_size
    world_x = chunk_x * profile.chunk_size
    world_y = chunk_y * profile.chunk_size
    region_col = min(profile.region_cols - 1, int((world_x + (profile.chunk_size / 2)) // profile.region_width))
    region_row = min(profile.region_rows - 1, int((world_y + (profile.chunk_size / 2)) // profile.region_height))
    region = regions[f"r{region_col}_{region_row}"]
    biome_mix_counter: Counter[str] = Counter()
    tiles: dict[tuple[int, int], str] = {}
    water_tiles: list[tuple[int, int]] = []
    river_tiles: list[tuple[int, int]] = []

    for tile_x in range(tiles_per_chunk):
        for tile_y in range(tiles_per_chunk):
            sample_world_x = world_x + (tile_x * profile.tile_size) + (profile.tile_size / 2)
            sample_world_y = world_y + (tile_y * profile.tile_size) + (profile.tile_size / 2)
            nx = sample_world_x / profile.world_width
            ny = sample_world_y / profile.world_height
            local_elevation = _clamp(region.elevation + (_fractal_noise(nx * 9.0, ny * 9.0, seed + 701, octaves=3, gain=0.52) * 0.14), 0.0, 1.0)
            local_temperature = _clamp(region.temperature + (_fractal_noise(nx * 7.0, ny * 7.0, seed + 719, octaves=2, gain=0.5) * 0.08), 0.0, 1.0)
            local_moisture = _clamp(region.moisture + (_fractal_noise(nx * 8.0, ny * 8.0, seed + 733, octaves=3, gain=0.5) * 0.1), 0.0, 1.0)
            distance_to_river_sq = min((_distance_squared_to_polyline(sample_world_x, sample_world_y, path) for path in river_paths), default=999999999.0)
            river_here = distance_to_river_sq <= (profile.tile_size * 1.4) ** 2
            coastal_here = local_elevation < 0.38
            biome = _pick_biome(local_elevation, local_temperature, local_moisture + (0.16 if river_here else 0.0), coastal_here, river_here)
            tiles[(tile_x, tile_y)] = biome
            biome_mix_counter[biome] += 1
            if coastal_here or (river_here and biome not in {"desert", "mountains"}):
                water_tiles.append((tile_x, tile_y))
            if river_here:
                river_tiles.append((tile_x, tile_y))

    total_tiles = float(max(1, tiles_per_chunk * tiles_per_chunk))
    biome_mix = {biome: round(count / total_tiles, 4) for biome, count in biome_mix_counter.items()}
    return ChunkState(
        chunk_x=chunk_x,
        chunk_y=chunk_y,
        world_x=world_x,
        world_y=world_y,
        tiles=tiles,
        biome_mix=biome_mix,
        elevation_avg=region.elevation,
        moisture_avg=region.moisture,
        temperature_avg=region.temperature,
        region_id=region.region_id,
        water_tiles=tuple(water_tiles),
        river_tiles=tuple(river_tiles),
    )


def _build_chunks(seed: int, profile: WorldProfile, regions: dict[str, WorldRegion], river_paths: list[list[tuple[float, float]]]) -> dict[tuple[int, int], ChunkState]:
    chunks: dict[tuple[int, int], ChunkState] = {}
    for chunk_x in range(profile.chunk_cols):
        for chunk_y in range(profile.chunk_rows):
            chunks[(chunk_x, chunk_y)] = _chunk_tiles(seed, profile, chunk_x, chunk_y, regions, river_paths)
    return chunks


def _build_render_layers(profile: WorldProfile, regions: dict[str, WorldRegion], routes: list[Route], landmarks: list[Landmark], polities: list[PolityMapState], river_paths: list[list[tuple[float, float]]]) -> dict[str, object]:
    region_overlay = [region.to_payload() for region in regions.values()]
    route_network = [route.to_payload() for route in routes]
    landmark_markers = [landmark.to_payload() for landmark in landmarks]
    polity_overlay = [polity.to_payload() for polity in polities]
    water_network = [
        {"points": [{"x": round(x, 2), "y": round(y, 2)} for x, y in path]}
        for path in river_paths
    ]
    return {
        "region_overlay": region_overlay,
        "route_network": route_network,
        "landmark_markers": landmark_markers,
        "polity_overlay": polity_overlay,
        "water_network": water_network,
    }


def build_frontier_world(seed_value: int | None, profile: WorldProfile) -> dict[str, object]:
    resolved_seed = int(seed_value if seed_value is not None else 0)
    world_seed = WorldSeed(resolved_seed)
    regions = _build_regions(world_seed.value, profile)
    settlements, routes, polities = _build_polities(world_seed.value, profile, regions)
    landmarks = _build_landmarks(world_seed.value, profile, regions)
    river_paths = _river_paths(profile, regions)
    chunks = _build_chunks(world_seed.value, profile, regions, river_paths)
    render_layers = _build_render_layers(profile, regions, routes, landmarks, polities, river_paths)
    return {
        "seed": world_seed,
        "profile": profile,
        "generation_version": 2,
        "chunks": chunks,
        "regions": regions,
        "settlements": settlements,
        "routes": routes,
        "landmarks": landmarks,
        "polities": polities,
        "river_paths": river_paths,
        "render_layers": render_layers,
    }
