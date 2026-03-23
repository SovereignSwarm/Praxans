from __future__ import annotations

import json
import os
from typing import Any


SNAPSHOT_VERSION = 9


def _sanitize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json_value(item) for item in value]
    return str(value)


def _serialize_personality_traits(praxan) -> dict[str, float]:
    personality = getattr(praxan, "personality", {})
    return {
        str(trait_name): round(float(trait_value), 4)
        for trait_name, trait_value in personality.items()
        if isinstance(trait_value, (int, float))
    }


def _serialize_genetics(praxan) -> dict[str, float]:
    genetics = getattr(praxan, "genetics", {})
    return {
        str(trait_name): round(float(trait_value), 4)
        for trait_name, trait_value in genetics.items()
        if isinstance(trait_value, (int, float))
    }


def _serialize_skills(praxan) -> dict[str, dict[str, float | int]]:
    serialized: dict[str, dict[str, float | int]] = {}
    skills = getattr(praxan, "skills", {})
    for skill_name, skill_data in skills.items():
        if not isinstance(skill_data, dict):
            continue
        try:
            level = int(skill_data.get("level", 1))
        except (TypeError, ValueError):
            level = 1
        try:
            xp = float(skill_data.get("xp", 0.0))
        except (TypeError, ValueError):
            xp = 0.0
        serialized[str(skill_name)] = {
            "level": max(1, level),
            "xp": round(max(0.0, xp), 3),
        }
    return serialized


def _serialize_bonds(praxan) -> dict[str, float]:
    bonds = getattr(praxan, "bonds", {})
    return {
        str(other_id): round(max(0.0, float(strength)), 3)
        for other_id, strength in bonds.items()
        if isinstance(strength, (int, float))
    }


def _serialize_opinions(praxan) -> dict[str, float]:
    opinions = getattr(praxan, "opinions", {})
    return {
        str(other_id): round(max(-100.0, min(100.0, float(score))), 3)
        for other_id, score in opinions.items()
        if isinstance(score, (int, float))
    }


def _serialize_typed_diseases(praxan) -> list[dict]:
    try:
        from systems.disease import DiseaseManager
        return DiseaseManager.serialize_diseases(praxan)
    except Exception:
        return []


def _serialize_disease_immunities(praxan) -> dict[str, float]:
    try:
        from systems.disease import DiseaseManager
        return DiseaseManager.serialize_immunities(praxan)
    except Exception:
        return {}


def _serialize_known_resources(praxan) -> list[dict[str, float]]:
    known_resources = []
    for resource_pos in getattr(praxan, "known_resources", []):
        if not isinstance(resource_pos, (list, tuple)) or len(resource_pos) != 2:
            continue
        try:
            x = float(resource_pos[0])
            y = float(resource_pos[1])
        except (TypeError, ValueError):
            continue
        known_resources.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
            }
        )
    return known_resources

def _serialize_celebration_state(celebration_state: dict[str, Any] | None, current_time: float) -> dict[str, Any]:
    if not celebration_state:
        return {"active_remaining": 0.0, "cooldown_remaining": 0.0, "center": None}

    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    center = celebration_state.get("center")
    if isinstance(center, (list, tuple)) and len(center) == 2:
        center_x = _coerce_float(center[0])
        center_y = _coerce_float(center[1])
        serialized_center = {"x": round(center_x, 2), "y": round(center_y, 2)}
    else:
        serialized_center = None

    active_until = _coerce_float(celebration_state.get("active_until", 0.0) or 0.0)
    cooldown_until = _coerce_float(celebration_state.get("cooldown_until", 0.0) or 0.0)
    return {
        "active_remaining": round(max(0.0, active_until - current_time), 3),
        "cooldown_remaining": round(max(0.0, cooldown_until - current_time), 3),
        "center": serialized_center,
    }

def _serialize_camera_state(camera) -> dict[str, Any] | None:
    if camera is None:
        return None

    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    return {
        "x": round(_coerce_float(getattr(camera, "x", 0.0), 0.0), 2),
        "y": round(_coerce_float(getattr(camera, "y", 0.0), 0.0), 2),
        "zoom": round(_coerce_float(getattr(camera, "zoom", 1.0), 1.0), 3),
        "follow_mode": bool(getattr(camera, "follow_mode", False)),
    }


def _serialize_active_challenges(advisor, current_time: float) -> list[dict[str, Any]]:
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    serialized = []
    for challenge in getattr(advisor, "active_challenges", []):
        if not isinstance(challenge, dict):
            continue
        start_time = _coerce_float(challenge.get("start_time", current_time), current_time)
        duration = max(0.0, _coerce_float(challenge.get("duration", 0.0), 0.0))
        remaining_seconds = max(0.0, duration - max(0.0, current_time - start_time))
        if remaining_seconds <= 0.0:
            continue
        challenge_copy = _sanitize_json_value(dict(challenge))
        challenge_copy["remaining_seconds"] = round(remaining_seconds, 3)
        challenge_copy.pop("start_time", None)
        challenge_copy.pop("duration", None)
        serialized.append(challenge_copy)
    return serialized


def _serialize_group_tasks(advisor, current_time: float) -> list[dict[str, Any]]:
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    serialized = []
    for task in getattr(advisor, "group_tasks", []):
        created_time = _coerce_float(getattr(task, "created_time", current_time), current_time)
        serialized.append(
            {
                "task_type": getattr(task, "task_type", None),
                "description": getattr(task, "description", ""),
                "required_count": max(1, _coerce_int(getattr(task, "required_count", 1), 1)),
                "target_location": _sanitize_json_value(getattr(task, "target_location", None)),
                "target_building_type": getattr(task, "target_building_type", None),
                "assigned_praxans": [
                    int(praxan_id)
                    for praxan_id in getattr(task, "assigned_praxans", [])
                    if isinstance(praxan_id, (int, float))
                ],
                "active": bool(getattr(task, "active", True)),
                "faction_id": getattr(task, "faction_id", None),
                "created_elapsed": round(max(0.0, current_time - created_time), 3),
            }
        )
    return serialized


def _serialize_factions(faction_manager, current_time: float) -> list[dict[str, Any]]:
    if faction_manager is None:
        return []

    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _coerce_non_negative_int(value: Any, default: int = 0) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(0, parsed)

    def _elapsed_or_zero(value: Any) -> float:
        if not value:
            return 0.0
        return round(max(0.0, current_time - _coerce_float(value, current_time)), 3)

    def _elapsed_or_now(value: Any) -> float:
        return round(max(0.0, current_time - _coerce_float(value, current_time)), 3)

    serialized = []
    for faction_id, faction in getattr(faction_manager, "factions", {}).items():
        serialized_faction_id = _coerce_non_negative_int(
            faction_id,
            _coerce_non_negative_int(getattr(faction, "id", 0), 0),
        )
        raw_migration_target = getattr(faction, "migration_target", None)
        if isinstance(raw_migration_target, (list, tuple)) and len(raw_migration_target) == 2:
            migration_target = {
                "x": round(_coerce_float(raw_migration_target[0]), 2),
                "y": round(_coerce_float(raw_migration_target[1]), 2),
            }
        elif isinstance(raw_migration_target, dict):
            migration_target = {
                "x": round(_coerce_float(raw_migration_target.get("x", 0.0)), 2),
                "y": round(_coerce_float(raw_migration_target.get("y", 0.0)), 2),
            }
        else:
            migration_target = None
        serialized.append(
            {
                "id": serialized_faction_id,
                "member_ids": [
                    int(member_id)
                    for member_id in getattr(faction, "member_ids", [])
                    if isinstance(member_id, (int, float))
                ],
                "leader_id": getattr(faction, "leader_id", None),
                "shared_goals": _sanitize_json_value(list(getattr(faction, "shared_goals", []))),
                "ideology": _sanitize_json_value(dict(getattr(faction, "ideology", {}))),
                "cohesion": round(_coerce_float(getattr(faction, "cohesion", 0.0)), 3),
                "stability": round(_coerce_float(getattr(faction, "stability", 0.0)), 3),
                "schism_pressure": round(_coerce_float(getattr(faction, "schism_pressure", 0.0)), 3),
                "migration_pressure": round(_coerce_float(getattr(faction, "migration_pressure", 0.0)), 3),
                "primary_doctrine": getattr(faction, "primary_doctrine", None),
                "preferred_biome": getattr(faction, "preferred_biome", None),
                "migration_target": migration_target,
                "succession_count": _coerce_non_negative_int(getattr(faction, "succession_count", 0) or 0),
                "rival_faction_ids": _sanitize_json_value(list(getattr(faction, "rival_faction_ids", []))),
                "last_succession_elapsed": _elapsed_or_zero(getattr(faction, "last_succession_time", 0.0)),
                "last_schism_elapsed": _elapsed_or_zero(getattr(faction, "last_schism_time", 0.0)),
                "last_migration_elapsed": _elapsed_or_zero(getattr(faction, "last_migration_time", 0.0)),
                "last_resource_crisis_elapsed": _elapsed_or_zero(getattr(faction, "last_resource_crisis_time", 0.0)),
                "formed_elapsed": _elapsed_or_now(getattr(faction, "formed_time", current_time)),
            }
        )
    return serialized


def _serialize_fog_of_war(fog_of_war) -> dict[str, Any] | None:
    if fog_of_war is None:
        return None
    tiles = []
    for tile_pos, visibility in getattr(fog_of_war, "fog_grid", {}).items():
        if not isinstance(tile_pos, tuple) or len(tile_pos) != 2:
            continue
        tiles.append(
            {
                "x": int(tile_pos[0]),
                "y": int(tile_pos[1]),
                "visibility": int(visibility),
            }
        )
    return {
        "visibility_radius": int(getattr(fog_of_war, "visibility_radius", 60)),
        "tiles": tiles,
    }


def _serialize_territory(territory_manager, current_time: float) -> dict[str, Any] | None:
    if territory_manager is None:
        return None

    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _coerce_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    tiles = []
    for tile_pos, data in getattr(territory_manager, "territory_grid", {}).items():
        if not isinstance(tile_pos, tuple) or len(tile_pos) != 2 or not isinstance(data, dict):
            continue
        claimed_time = _coerce_float(data.get("claimed_time", current_time) or current_time, current_time)
        tiles.append(
            {
                "x": _coerce_int(tile_pos[0], 0),
                "y": _coerce_int(tile_pos[1], 0),
                "claim_strength": round(max(0.0, _coerce_float(data.get("claim_strength", 0.0) or 0.0, 0.0)), 3),
                "center_type": data.get("center_type", "exploration"),
                "claimed_elapsed": round(max(0.0, current_time - claimed_time), 3),
            }
        )
    return {
        "tiles": tiles,
    }


def _serialize_city_planner(city_planner, current_time: float) -> dict[str, Any] | None:
    if city_planner is None:
        return None
    zones = []
    for tile_pos, zone_type in getattr(city_planner, "zones", {}).items():
        if not isinstance(tile_pos, tuple) or len(tile_pos) != 2:
            continue
        zones.append(
            {
                "x": int(tile_pos[0]),
                "y": int(tile_pos[1]),
                "zone_type": str(zone_type),
            }
        )
    return {
        "zones": zones,
        "current_plan": _sanitize_json_value(getattr(city_planner, "current_plan", None)),
        "last_plan_elapsed": round(
            max(0.0, current_time - float(getattr(city_planner, "last_plan_update", 0.0) or 0.0))
            if getattr(city_planner, "last_plan_update", 0.0)
            else 0.0,
            3,
        ),
    }


def _serialize_world_state(world_map, current_time: float) -> dict[str, Any] | None:
    if world_map is None:
        return None
    return {
        "generation_version": int(getattr(world_map, "generation_version", 0) or 0),
        "world_seed": int(getattr(world_map, "world_seed", 0) or 0),
        "world_profile": _sanitize_json_value(getattr(getattr(world_map, "world_profile", None), "to_payload", lambda: None)()),
        "discovered_chunks": [
            {"chunk_x": int(chunk_x), "chunk_y": int(chunk_y)}
            for chunk_x, chunk_y in sorted(getattr(world_map, "discovered_chunks", set()))
        ],
        "regions": _sanitize_json_value(list(getattr(world_map, "regions", []))),
        "routes": _sanitize_json_value(list(getattr(world_map, "route_network", []))),
        "landmarks": _sanitize_json_value(list(getattr(world_map, "landmarks", []))),
        "settlements": _sanitize_json_value(list(getattr(world_map, "settlements", []))),
        "polities": _sanitize_json_value(list(getattr(world_map, "polities", []))),
        "water_network": _sanitize_json_value(list(getattr(world_map, "water_network", []))),
        "encounters": [
            {
                "x": round(float(getattr(encounter, "x", 0.0)), 2),
                "y": round(float(getattr(encounter, "y", 0.0)), 2),
                "encounter_type": getattr(encounter, "encounter_type", "ruins"),
                "discovered": bool(getattr(encounter, "discovered", False)),
                "explored": bool(getattr(encounter, "explored", False)),
                "reward_given": bool(getattr(encounter, "reward_given", False)),
            }
            for encounter in getattr(world_map, "encounters", [])
        ],
        "hazards": [
            {
                "x": round(float(getattr(hazard, "x", 0.0)), 2),
                "y": round(float(getattr(hazard, "y", 0.0)), 2),
                "hazard_type": getattr(hazard, "hazard_type", "predator_lair"),
                "radius": round(float(getattr(hazard, "radius", 100.0)), 2),
                "active": bool(getattr(hazard, "active", True)),
                "damage_rate": round(float(getattr(hazard, "damage_rate", 0.5)), 3),
            }
            for hazard in getattr(world_map, "hazards", [])
        ],
        "npcs": [
            {
                "x": round(float(getattr(npc, "x", 0.0)), 2),
                "y": round(float(getattr(npc, "y", 0.0)), 2),
                "npc_type": getattr(npc, "npc_type", "trader"),
                "visible": bool(getattr(npc, "visible", True)),
                "inventory": _sanitize_json_value(dict(getattr(npc, "inventory", {}))),
                "trade_rates": _sanitize_json_value(dict(getattr(npc, "trade_rates", {}))),
                "hostile": bool(getattr(npc, "hostile", False)),
                "reputation": int(getattr(npc, "reputation", 0)),
                "last_interaction_elapsed": round(
                    max(0.0, current_time - float(getattr(npc, "last_interaction", 0.0) or 0.0))
                    if getattr(npc, "last_interaction", 0.0)
                    else 0.0,
                    3,
                ),
            }
            for npc in getattr(world_map, "npcs", [])
        ],
    }


def _serialize_temporary_modifiers(advisor, current_time: float) -> dict[str, dict[str, float]]:
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    serialized: dict[str, dict[str, float]] = {}
    modifiers = getattr(getattr(advisor, "game_modifiers", None), "temporary", {})
    for modifier_name, modifier_value in modifiers.items():
        if not isinstance(modifier_value, tuple) or len(modifier_value) != 2:
            continue
        multiplier, end_time = modifier_value
        remaining_seconds = max(0.0, _coerce_float(end_time, current_time) - current_time)
        if remaining_seconds <= 0.0:
            continue
        serialized[modifier_name] = {
            "value": _coerce_float(multiplier, 1.0),
            "remaining_seconds": round(remaining_seconds, 3),
        }
    return serialized

def _serialize_global_climate(global_climate) -> dict[str, Any]:
    """Serialize GlobalClimate epoch drift state for snapshot persistence."""
    if global_climate is None:
        return {}
    return {
        "epoch": getattr(global_climate, "epoch", "Holocene"),
        "global_temp_offset": round(float(getattr(global_climate, "global_temp_offset", 0.0)), 4),
        "global_moisture_offset": round(float(getattr(global_climate, "global_moisture_offset", 0.0)), 4),
        "target_temp_offset": round(float(getattr(global_climate, "target_temp_offset", 0.0)), 4),
        "target_moisture_offset": round(float(getattr(global_climate, "target_moisture_offset", 0.0)), 4),
    }


def build_run_snapshot(
    praxans,
    buildings,
    resources,
    advisor,
    season,
    weather_system,
    current_time,
    game_start_time,
    selected_model: str | None = None,
    resource_respawn_time: float = 30.0,
    celebration_state: dict[str, Any] | None = None,
    camera=None,
    world_map=None,
    fog_of_war=None,
    territory_manager=None,
    faction_manager=None,
    city_planner=None,
    scenario_id: str | None = None,
    run_summary: dict[str, Any] | None = None,
    camera_bookmarks: list[dict[str, Any]] | None = None,
    scene_thumbnail_key: str | None = None,
    focus_moments: list[dict[str, Any]] | None = None,
    quest_manager=None,
    diplomacy_manager=None,
    tech_research_manager=None,
    disaster_manager=None,
    ritual_manager=None,
    ecology_manager=None,
    global_climate=None,
    reputation_manager=None,
    aspiration_manager=None,
    warfare_manager=None,
    cascade_manager=None,
    tradition_manager=None,
    migration_manager=None,
):
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "saved_at": round(current_time, 3),
        "elapsed_seconds": round(max(0.0, current_time - game_start_time), 3),
        "scenario_id": scenario_id,
        "run_summary": _sanitize_json_value(run_summary),
        "graphics": {
            "camera_bookmarks": _sanitize_json_value(list(camera_bookmarks or [])),
            "scene_thumbnail_key": scene_thumbnail_key,
            "focus_moments": _sanitize_json_value(list(focus_moments or [])),
        },
        "season": getattr(season, "current", "summer"),
        "weather": getattr(weather_system, "current_weather", "clear"),
        "weather_next_event_in": round(max(0.0, getattr(weather_system, "next_event_time", current_time) - current_time), 3),
        "weather_active_event_ends_in": round(max(0.0, getattr(weather_system, "active_event_end", 0.0) - current_time), 3),
        "selected_model": selected_model,
        "population": len(praxans),
        "camera": _serialize_camera_state(camera),
        "celebration": _serialize_celebration_state(celebration_state, current_time),
        "fog_of_war": _serialize_fog_of_war(fog_of_war),
        "territory": _serialize_territory(territory_manager, current_time),
        "factions": _serialize_factions(faction_manager, current_time),
        "city_planner": _serialize_city_planner(city_planner, current_time),
        "world": _serialize_world_state(world_map, current_time),
        "quests": quest_manager.to_dict() if quest_manager is not None else {},
        "diplomacy": diplomacy_manager.serialize(current_time=current_time) if diplomacy_manager is not None else {},
        "tech_research": tech_research_manager.serialize() if tech_research_manager is not None else {},
        "disasters": disaster_manager.serialize() if disaster_manager is not None else {},
        "rituals": ritual_manager.serialize() if ritual_manager is not None else {},
        "reputation": reputation_manager.serialize() if reputation_manager is not None else {},
        "aspirations": aspiration_manager.serialize() if aspiration_manager is not None else {},
        "ecology": ecology_manager.serialize() if ecology_manager is not None and hasattr(ecology_manager, "serialize") else {},
        "global_climate": _serialize_global_climate(global_climate),
        "warfare": warfare_manager.serialize(current_time=current_time) if warfare_manager is not None else {},
        "cascades": cascade_manager.serialize() if cascade_manager is not None else {},
        "traditions": tradition_manager.serialize(current_time=current_time) if tradition_manager is not None else {},
        "migration": migration_manager.serialize(current_time=current_time) if migration_manager is not None else {},
        "praxans": [
            {
                "id": praxan.id,
                "role": praxan.role,
                "x": round(praxan.x, 2),
                "y": round(praxan.y, 2),
                "health": round(praxan.health, 2),
                "happiness": round(getattr(praxan, "happiness", 0.0), 2),
                "base_mood": round(getattr(praxan, "base_mood", 50.0), 2),
                "morale": round(getattr(praxan, "morale", 0.0), 2),
                "inspiration": round(getattr(praxan, "inspiration", 0.0), 2),
                "favorite_biome": getattr(praxan, "favorite_biome", None),
                "age_seconds": round(getattr(praxan, "age", 0.0), 2),
                "diseased": bool(getattr(praxan, "diseased", False)),
                "resilience": round(getattr(praxan, "resilience", 1.0), 3),
                "settlement_prosperity": round(getattr(praxan, "settlement_prosperity", 0.5), 3),
                "inventory": dict(praxan.inventory),
                "needs": dict(praxan.needs),
                "state": getattr(praxan, "state", None),
                "current_action": getattr(praxan, "current_action", None),
                "personal_goal": _sanitize_json_value(getattr(praxan, "personal_goal", None)),
                "goal_progress": round(getattr(praxan, "goal_progress", 0.0), 3),
                "personality": _serialize_personality_traits(praxan),
                "genetics": _serialize_genetics(praxan),
                "generation": max(0, int(getattr(praxan, "generation", 0))),
                "parent_ids": [int(parent_id) for parent_id in getattr(praxan, "parent_ids", []) if isinstance(parent_id, (int, float))],
                "lineage_id": int(getattr(praxan, "lineage_id", praxan.id)),
                "mutation_count": max(0, int(getattr(praxan, "mutation_count", 0))),
                "birth_origin": getattr(praxan, "birth_origin", "founder"),
                "skills": _serialize_skills(praxan),
                "bonds": _serialize_bonds(praxan),
                "opinions": _serialize_opinions(praxan),
                "relationships": {str(k): v for k, v in getattr(praxan, "relationships", {}).items()},
                "traits": list(getattr(praxan, "traits", [])),
                "name": getattr(praxan, "name", None),
                "faction_id": getattr(praxan, "faction_id", None),
                "known_resources": _serialize_known_resources(praxan),
                "episodic_memory": (
                    praxan.episodic_memory.to_dict()
                    if hasattr(praxan, "episodic_memory") and praxan.episodic_memory is not None
                    else None
                ),
                "disease_elapsed": round(
                    max(0.0, current_time - float(getattr(praxan, "disease_start_time", 0.0)))
                    if bool(getattr(praxan, "diseased", False)) and getattr(praxan, "disease_start_time", 0.0)
                    else 0.0,
                    3,
                ),
                "typed_diseases": _serialize_typed_diseases(praxan),
                "disease_immunities": _serialize_disease_immunities(praxan),
                "last_reproduction_elapsed": round(
                    max(0.0, current_time - float(getattr(praxan, "last_reproduction_time", 0.0)))
                    if getattr(praxan, "last_reproduction_time", 0.0)
                    else 0.0,
                    3,
                ),
                "goal_assigned_elapsed": round(
                    max(0.0, current_time - float(getattr(praxan, "goal_assigned_time", 0.0)))
                    if getattr(praxan, "goal_assigned_time", 0.0)
                    else 0.0,
                    3,
                ),
                "equipment": getattr(praxan, "equipment", {'armor': None, 'weapon': None}),
                "aspiration": _sanitize_json_value(getattr(praxan, "aspiration", None)),
                "completed_aspirations": list(getattr(praxan, "_completed_aspirations", [])),
            }
            for praxan in praxans
        ],
        "buildings": [
            {
                "type": building.building_type,
                "x": round(building.x, 2),
                "y": round(building.y, 2),
                "level": getattr(building, "level", 1),
                "built_elapsed": round(
                    max(0.0, current_time - float(getattr(building, "built_at", current_time) or current_time)),
                    3,
                ),
                "built_by": getattr(building, "built_by", None),
                "aura_strength": round(getattr(building, "aura_strength", 0.0), 3),
                "origin_biome": getattr(building, "origin_biome", None),
                "material_style": getattr(building, "material_style", None),
                "wear": round(float(getattr(building, "wear", 0.0) or 0.0), 3),
                "construction_progress": round(float(getattr(building, "construction_progress", 1.0) or 1.0), 3),
                "stored_resources": dict(building.stored_resources),
                "occupant_ids": [
                    int(occupant.id)
                    for occupant in getattr(building, "occupants", [])
                    if hasattr(occupant, "id")
                ],
                "bills": list(getattr(building, "bills", [])),
            }
            for building in buildings
        ],
        "resources": [
            {
                "type": resource.resource_type,
                "x": round(resource.x, 2),
                "y": round(resource.y, 2),
                "collected": bool(resource.collected),
                "respawn_remaining": round(
                    max(
                        0.0,
                        getattr(resource, "collect_time", 0.0)
                        and (resource_respawn_time - (current_time - getattr(resource, "collect_time", 0.0))),
                    ),
                    3,
                )
                if bool(resource.collected) and getattr(resource, "resource_type", "") == "food"
                else 0.0,
            }
            for resource in resources
        ],
        "advisor": {
            "research_points": getattr(advisor, "research_points", 0),
            "points_spent": getattr(advisor, "points_spent", 0),
            "stability_counter": getattr(advisor, "stability_counter", 0),
            "current_focus": getattr(advisor, "current_focus", None),
            "directives": _sanitize_json_value(list(getattr(advisor, "directives", []))),
            "json_directives": _sanitize_json_value(dict(getattr(advisor, "json_directives", {}))),
            "council_state": _sanitize_json_value(dict(getattr(advisor, "council_state", {}))),
            "advisory_history": _sanitize_json_value(list(getattr(advisor, "advisory_history", []))),
            "session_stats": _sanitize_json_value(dict(getattr(advisor, "session_stats", {}))),
            "settlement_state": _sanitize_json_value(dict(getattr(advisor, "current_settlement_state", {}))),
            "query_count": getattr(advisor, "query_count", 0),
            "intervention_stats": _sanitize_json_value(dict(getattr(advisor, "intervention_stats", {}))),
            "tech_unlocked": sorted(getattr(getattr(advisor, "game_modifiers", None), "tech_unlocked", set())),
            "permanent_modifiers": dict(getattr(getattr(advisor, "game_modifiers", None), "permanent", {})),
            "temporary_modifiers": _serialize_temporary_modifiers(advisor, current_time),
            "active_challenges": _serialize_active_challenges(advisor, current_time),
            "group_tasks": _serialize_group_tasks(advisor, current_time),
            "civilization_age": int(getattr(advisor, "civilization_age", 0)),
            "total_deaths": int(getattr(advisor, "total_deaths", 0)),
            "achievements": _sanitize_json_value(list(getattr(advisor, "achievements", []))),
            "history": _sanitize_json_value(list(getattr(advisor, "history", []))),
            "events_history": _sanitize_json_value(list(getattr(advisor, "events_history", []))),
            "last_model_used": getattr(advisor, "last_model_used", None),
            "llm_memory": _sanitize_json_value(
                getattr(advisor, "llm_memory", None) and advisor.llm_memory.serialize() or {}
            ),
            "llm_channel_stats": _sanitize_json_value(
                getattr(advisor, "llm_scheduler", None) and advisor.llm_scheduler.get_stats() or {}
            ),
            "doctrine_history": _sanitize_json_value(list(getattr(advisor, "advisory_history", []))[-10:]),
        },
    }


def write_run_snapshot(log_dir: str, session_id: str, snapshot: dict[str, Any]) -> str:
    os.makedirs(log_dir, exist_ok=True)
    snapshot_path = os.path.join(log_dir, f"snapshot_{session_id}.json")
    with open(snapshot_path, "w", encoding="utf-8") as snapshot_file:
        json.dump(snapshot, snapshot_file, indent=2)
    return snapshot_path


def load_run_snapshot(snapshot_path: str) -> dict[str, Any]:
    with open(snapshot_path, "r", encoding="utf-8") as snapshot_file:
        snapshot = json.load(snapshot_file)
    if not isinstance(snapshot, dict):
        raise ValueError(f"Snapshot file is not a JSON object: {snapshot_path}")
    snapshot_version = int(snapshot.get("snapshot_version", 0) or 0)
    if snapshot_version > SNAPSHOT_VERSION:
        raise ValueError(
            f"Snapshot version {snapshot_version} is newer than supported version {SNAPSHOT_VERSION}: {snapshot_path}"
        )
    return snapshot


def find_latest_snapshot(log_dir: str) -> str | None:
    if not os.path.isdir(log_dir):
        return None

    snapshot_paths = [
        os.path.join(log_dir, entry)
        for entry in os.listdir(log_dir)
        if entry.startswith("snapshot_") and entry.endswith(".json")
    ]
    if not snapshot_paths:
        return None

    snapshot_paths.sort(key=lambda path: (os.path.getmtime(path), os.path.basename(path)), reverse=True)
    return snapshot_paths[0]


def resolve_snapshot_path(log_dir: str, snapshot_file: str | None = None, load_latest: bool = False) -> str | None:
    if snapshot_file:
        candidates = [snapshot_file]
        if not os.path.isabs(snapshot_file):
            candidates.append(os.path.join(log_dir, snapshot_file))
        for candidate in candidates:
            if os.path.exists(candidate):
                return os.path.abspath(candidate)
        return os.path.abspath(candidates[0])

    if load_latest:
        latest_snapshot = find_latest_snapshot(log_dir)
        return os.path.abspath(latest_snapshot) if latest_snapshot else None

    return None


