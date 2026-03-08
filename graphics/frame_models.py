from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graphics.content import SNAP_ZOOM_LEVELS, doctrine_trim, snap_zoom_level, time_of_day_for_elapsed


@dataclass(frozen=True)
class GraphicsConfig:
    target_fps: int = 30
    fog_delay_seconds: float = 2.0
    chunk_cache_limit: int = 96
    scaled_cache_limit: int = 160
    selection_pulse_seconds: float = 0.6
    pixel_scale: int = 2
    snap_zoom_levels: tuple[float, ...] = SNAP_ZOOM_LEVELS
    debug_procedural_fallbacks: bool = False
    focus_cue_seconds: float = 1.5
    enable_scene_thumbnails: bool = True
    show_action_badges: bool = False
    show_role_pennants: bool = False
    enable_event_beacons: bool = True
    enable_weather_pass: bool = True
    enable_settlement_overlays: bool = True


@dataclass(frozen=True)
class EffectCue:
    label: str
    category: str
    x: float
    y: float
    time: float


@dataclass(frozen=True)
class EntityVisualState:
    entity: Any
    entity_type: str
    selected: bool = False
    animation_state: str = "idle"
    facing: str = "down"
    variant_id: int = 0
    faction_accent: tuple[int, int, int] | None = None
    health_state: str = "healthy"
    highlight_state: str = "normal"


@dataclass(frozen=True)
class WorldLayerState:
    world_map: Any
    camera: Any
    fog_of_war: Any
    territory_manager: Any
    city_planner: Any
    faction_manager: Any
    season: Any
    weather_system: Any
    settlement_state: dict[str, Any]
    elapsed_seconds: float
    current_time: float
    frame_count: int
    window_size: tuple[int, int]
    chunk_size: int
    tile_size: int
    world_size: tuple[int, int]
    time_of_day: str
    camera_mode: str
    active_overlay: str
    zoom_band: float
    region_overlay: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    water_network: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    route_network: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    polity_overlay: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    landmark_markers: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    focus_event: dict[str, Any] | None = None


@dataclass(frozen=True)
class RenderFrame:
    world: WorldLayerState
    buildings: tuple[EntityVisualState, ...] = field(default_factory=tuple)
    resources: tuple[EntityVisualState, ...] = field(default_factory=tuple)
    praxans: tuple[EntityVisualState, ...] = field(default_factory=tuple)
    encounters: tuple[EntityVisualState, ...] = field(default_factory=tuple)
    hazards: tuple[EntityVisualState, ...] = field(default_factory=tuple)
    npcs: tuple[EntityVisualState, ...] = field(default_factory=tuple)
    particle_system: Any = None
    effect_cues: tuple[EffectCue, ...] = field(default_factory=tuple)
    camera_bookmarks: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    screen_fx_state: dict[str, Any] = field(default_factory=dict)
    title_card: dict[str, Any] | None = None
    ghost_markers: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def _derive_facing(entity) -> str:
    vx = float(getattr(entity, "vx", 0.0) or 0.0)
    vy = float(getattr(entity, "vy", 0.0) or 0.0)
    if abs(vx) > abs(vy):
        return "right" if vx >= 0 else "left"
    if abs(vy) > 0.04:
        return "down" if vy >= 0 else "up"
    return "down"


def _derive_animation_state(entity, entity_type: str) -> str:
    if entity_type == "praxan":
        if not bool(getattr(entity, "alive", True)):
            return "death"
        if bool(getattr(entity, "diseased", False)):
            return "sick"
        action = str(getattr(entity, "current_action", "idle") or "idle").lower()
        if "celebrat" in action or getattr(entity, "inspiration", 0) > 60:
            return "celebrate"
        if "rest" in action or "sleep" in action:
            return "rest"
        if "build" in action:
            return "build"
        if "gather" in action or "collect" in action or "food" in action or "wood" in action or "stone" in action:
            return "gather"
        moving = abs(float(getattr(entity, "vx", 0.0) or 0.0)) + abs(float(getattr(entity, "vy", 0.0) or 0.0))
        return "walk" if moving > 0.08 else "idle"
    if entity_type == "building":
        return "active" if getattr(entity, "occupants", None) or getattr(entity, "aura_strength", 0.0) > 0.1 else "idle"
    return "idle"


def _derive_health_state(entity, entity_type: str) -> str:
    if entity_type == "praxan":
        if not bool(getattr(entity, "alive", True)):
            return "dead"
        if bool(getattr(entity, "diseased", False)):
            return "sick"
        health = float(getattr(entity, "health", 100.0) or 100.0)
        if health < 35:
            return "critical"
        if health < 65:
            return "strained"
    return "healthy"


def _derive_faction_accent(entity, faction_manager) -> tuple[int, int, int] | None:
    if faction_manager is None:
        return None
    faction_id = getattr(entity, "faction_id", None)
    if faction_id is None:
        return None
    faction = getattr(faction_manager, "factions", {}).get(faction_id)
    if faction is None:
        return None
    accent, _shadow = doctrine_trim(getattr(faction, "primary_doctrine", None))
    return accent


def _derive_variant_id(entity, entity_type: str) -> int:
    if entity_type == "building":
        x = int(round(float(getattr(entity, "x", 0.0) or 0.0)))
        y = int(round(float(getattr(entity, "y", 0.0) or 0.0)))
        level = int(getattr(entity, "level", 1) or 1)
        built_by_raw = getattr(entity, "built_by", None)
        built_by = int(built_by_raw) if built_by_raw is not None else -1
        return abs((x * 17) + (y * 31) + (level * 7) + (built_by * 13)) % 8
    return int(getattr(entity, "id", 0) or 0) % 4


def _build_entity_states(entities, entity_type: str, selected_entity, faction_manager=None) -> tuple[EntityVisualState, ...]:
    return tuple(
        EntityVisualState(
            entity=entity,
            entity_type=entity_type,
            selected=entity is selected_entity,
            animation_state=_derive_animation_state(entity, entity_type),
            facing=_derive_facing(entity),
            variant_id=_derive_variant_id(entity, entity_type),
            faction_accent=_derive_faction_accent(entity, faction_manager),
            health_state=_derive_health_state(entity, entity_type),
            highlight_state="selected" if entity is selected_entity else "normal",
        )
        for entity in entities
    )


def build_render_frame(
    *,
    world_map,
    camera,
    fog_of_war,
    territory_manager,
    city_planner,
    faction_manager,
    season,
    weather_system,
    settlement_state,
    current_time: float,
    game_start_time: float,
    frame_count: int,
    window_size: tuple[int, int],
    chunk_size: int,
    tile_size: int,
    world_size: tuple[int, int],
    buildings,
    resources,
    praxans,
    encounters,
    hazards,
    npcs,
    selected_entity=None,
    particle_system=None,
    effect_cues=None,
    active_overlay: str = "districts",
    camera_bookmarks=None,
    title_card: dict | None = None,
    ghost_markers=None,
) -> RenderFrame:
    elapsed_seconds = max(0.0, current_time - game_start_time)
    focus_event = None
    cues = []
    normalized_ghost_markers = list(ghost_markers or [])
    if not normalized_ghost_markers and city_planner is not None:
        for site in list(getattr(city_planner, "proposed_sites", []) or []):
            if isinstance(site, (list, tuple)) and len(site) >= 3:
                normalized_ghost_markers.append(
                    {"x": float(site[0]), "y": float(site[1]), "building_type": str(site[2])}
                )
    for cue in list(effect_cues or []):
        if not isinstance(cue, dict):
            continue
        normalized = EffectCue(
            label=str(cue.get("label", "Moment")),
            category=str(cue.get("category", "event")),
            x=float(cue.get("x", 0.0) or 0.0),
            y=float(cue.get("y", 0.0) or 0.0),
            time=float(cue.get("time", current_time) or current_time),
        )
        cues.append(normalized)
    if cues:
        focus_event = {
            "label": cues[-1].label,
            "category": cues[-1].category,
            "x": cues[-1].x,
            "y": cues[-1].y,
            "time": cues[-1].time,
        }
    world_state = WorldLayerState(
        world_map=world_map,
        camera=camera,
        fog_of_war=fog_of_war,
        territory_manager=territory_manager,
        city_planner=city_planner,
        faction_manager=faction_manager,
        season=season,
        weather_system=weather_system,
        settlement_state=dict(settlement_state or {}),
        elapsed_seconds=elapsed_seconds,
        current_time=current_time,
        frame_count=frame_count,
        window_size=window_size,
        chunk_size=chunk_size,
        tile_size=tile_size,
        world_size=world_size,
        time_of_day=time_of_day_for_elapsed(elapsed_seconds),
        camera_mode="follow" if bool(getattr(camera, "follow_mode", False)) else "free",
        active_overlay=str(active_overlay or "districts"),
        zoom_band=snap_zoom_level(float(getattr(camera, "zoom", 1.0) or 1.0), SNAP_ZOOM_LEVELS),
        region_overlay=tuple(dict(region) for region in list(getattr(world_map, "region_overlay", []) or [])),
        water_network=tuple(dict(segment) for segment in list(getattr(world_map, "water_network", []) or [])),
        route_network=tuple(dict(route) for route in list(getattr(world_map, "route_network", []) or [])),
        polity_overlay=tuple(dict(polity) for polity in list(getattr(world_map, "polity_overlay", []) or [])),
        landmark_markers=tuple(dict(landmark) for landmark in list(getattr(world_map, "landmark_markers", []) or [])),
        focus_event=focus_event,
    )
    return RenderFrame(
        world=world_state,
        buildings=_build_entity_states(buildings, "building", selected_entity, faction_manager),
        resources=_build_entity_states(resources, "resource", selected_entity, faction_manager),
        praxans=_build_entity_states(praxans, "praxan", selected_entity, faction_manager),
        encounters=_build_entity_states(encounters, "encounter", selected_entity, faction_manager),
        hazards=_build_entity_states(hazards, "hazard", selected_entity, faction_manager),
        npcs=_build_entity_states(npcs, "npc", selected_entity, faction_manager),
        particle_system=particle_system,
        effect_cues=tuple(cues),
        camera_bookmarks=tuple(dict(bookmark) for bookmark in list(camera_bookmarks or [])),
        screen_fx_state={
            "time_of_day": time_of_day_for_elapsed(elapsed_seconds),
            "festival_active": bool((settlement_state or {}).get("festival_active", False)),
            "prosperity_score": round(float((settlement_state or {}).get("prosperity_score", 0.0) or 0.0), 3),
        },
        title_card=dict(title_card) if title_card else None,
        ghost_markers=tuple(dict(gm) for gm in normalized_ghost_markers),
    )
