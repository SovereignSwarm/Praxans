from __future__ import annotations

import json
import os
from typing import Any


SNAPSHOT_VERSION = 6


def _sanitize_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json_value(item) for item in value]
    return str(value)


def _serialize_personality_traits(thronglet) -> dict[str, float]:
    personality = getattr(thronglet, "personality", {})
    return {
        str(trait_name): round(float(trait_value), 4)
        for trait_name, trait_value in personality.items()
        if isinstance(trait_value, (int, float))
    }


def _serialize_genetics(thronglet) -> dict[str, float]:
    genetics = getattr(thronglet, "genetics", {})
    return {
        str(trait_name): round(float(trait_value), 4)
        for trait_name, trait_value in genetics.items()
        if isinstance(trait_value, (int, float))
    }


def _serialize_skills(thronglet) -> dict[str, dict[str, float | int]]:
    serialized: dict[str, dict[str, float | int]] = {}
    skills = getattr(thronglet, "skills", {})
    for skill_name, skill_data in skills.items():
        if not isinstance(skill_data, dict):
            continue
        serialized[str(skill_name)] = {
            "level": max(1, int(skill_data.get("level", 1))),
            "xp": round(max(0.0, float(skill_data.get("xp", 0.0))), 3),
        }
    return serialized


def _serialize_bonds(thronglet) -> dict[str, float]:
    bonds = getattr(thronglet, "bonds", {})
    return {
        str(other_id): round(max(0.0, float(strength)), 3)
        for other_id, strength in bonds.items()
        if isinstance(strength, (int, float))
    }


def _serialize_known_resources(thronglet) -> list[dict[str, float]]:
    known_resources = []
    for resource_pos in getattr(thronglet, "known_resources", []):
        if not isinstance(resource_pos, (list, tuple)) or len(resource_pos) != 2:
            continue
        known_resources.append(
            {
                "x": round(float(resource_pos[0]), 2),
                "y": round(float(resource_pos[1]), 2),
            }
        )
    return known_resources


def _serialize_celebration_state(celebration_state: dict[str, Any] | None, current_time: float) -> dict[str, Any]:
    if not celebration_state:
        return {"active_remaining": 0.0, "cooldown_remaining": 0.0, "center": None}

    center = celebration_state.get("center")
    if isinstance(center, (list, tuple)) and len(center) == 2:
        serialized_center = {"x": round(float(center[0]), 2), "y": round(float(center[1]), 2)}
    else:
        serialized_center = None

    active_until = float(celebration_state.get("active_until", 0.0) or 0.0)
    cooldown_until = float(celebration_state.get("cooldown_until", 0.0) or 0.0)
    return {
        "active_remaining": round(max(0.0, active_until - current_time), 3),
        "cooldown_remaining": round(max(0.0, cooldown_until - current_time), 3),
        "center": serialized_center,
    }


def _serialize_camera_state(camera) -> dict[str, Any] | None:
    if camera is None:
        return None
    return {
        "x": round(float(getattr(camera, "x", 0.0)), 2),
        "y": round(float(getattr(camera, "y", 0.0)), 2),
        "zoom": round(float(getattr(camera, "zoom", 1.0)), 3),
        "follow_mode": bool(getattr(camera, "follow_mode", False)),
    }


def _serialize_active_challenges(advisor, current_time: float) -> list[dict[str, Any]]:
    serialized = []
    for challenge in getattr(advisor, "active_challenges", []):
        if not isinstance(challenge, dict):
            continue
        start_time = float(challenge.get("start_time", current_time) or current_time)
        duration = max(0.0, float(challenge.get("duration", 0.0) or 0.0))
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
    serialized = []
    for task in getattr(advisor, "group_tasks", []):
        serialized.append(
            {
                "task_type": getattr(task, "task_type", None),
                "description": getattr(task, "description", ""),
                "required_count": int(getattr(task, "required_count", 1)),
                "target_location": _sanitize_json_value(getattr(task, "target_location", None)),
                "target_building_type": getattr(task, "target_building_type", None),
                "assigned_thronglets": [
                    int(thronglet_id)
                    for thronglet_id in getattr(task, "assigned_thronglets", [])
                    if isinstance(thronglet_id, (int, float))
                ],
                "active": bool(getattr(task, "active", True)),
                "faction_id": getattr(task, "faction_id", None),
                "created_elapsed": round(
                    max(0.0, current_time - float(getattr(task, "created_time", current_time) or current_time)),
                    3,
                ),
            }
        )
    return serialized


def _serialize_factions(faction_manager, current_time: float) -> list[dict[str, Any]]:
    if faction_manager is None:
        return []
    serialized = []
    for faction_id, faction in getattr(faction_manager, "factions", {}).items():
        raw_migration_target = getattr(faction, "migration_target", None)
        if isinstance(raw_migration_target, (list, tuple)) and len(raw_migration_target) == 2:
            migration_target = {
                "x": round(float(raw_migration_target[0]), 2),
                "y": round(float(raw_migration_target[1]), 2),
            }
        elif isinstance(raw_migration_target, dict):
            migration_target = {
                "x": round(float(raw_migration_target.get("x", 0.0)), 2),
                "y": round(float(raw_migration_target.get("y", 0.0)), 2),
            }
        else:
            migration_target = None
        serialized.append(
            {
                "id": int(faction_id),
                "member_ids": [
                    int(member_id)
                    for member_id in getattr(faction, "member_ids", [])
                    if isinstance(member_id, (int, float))
                ],
                "leader_id": getattr(faction, "leader_id", None),
                "shared_goals": _sanitize_json_value(list(getattr(faction, "shared_goals", []))),
                "ideology": _sanitize_json_value(dict(getattr(faction, "ideology", {}))),
                "cohesion": round(float(getattr(faction, "cohesion", 0.0)), 3),
                "stability": round(float(getattr(faction, "stability", 0.0)), 3),
                "schism_pressure": round(float(getattr(faction, "schism_pressure", 0.0)), 3),
                "migration_pressure": round(float(getattr(faction, "migration_pressure", 0.0)), 3),
                "primary_doctrine": getattr(faction, "primary_doctrine", None),
                "preferred_biome": getattr(faction, "preferred_biome", None),
                "migration_target": migration_target,
                "succession_count": int(getattr(faction, "succession_count", 0) or 0),
                "rival_faction_ids": _sanitize_json_value(list(getattr(faction, "rival_faction_ids", []))),
                "last_succession_elapsed": round(
                    max(0.0, current_time - float(getattr(faction, "last_succession_time", 0.0) or 0.0))
                    if getattr(faction, "last_succession_time", 0.0)
                    else 0.0,
                    3,
                ),
                "last_schism_elapsed": round(
                    max(0.0, current_time - float(getattr(faction, "last_schism_time", 0.0) or 0.0))
                    if getattr(faction, "last_schism_time", 0.0)
                    else 0.0,
                    3,
                ),
                "last_migration_elapsed": round(
                    max(0.0, current_time - float(getattr(faction, "last_migration_time", 0.0) or 0.0))
                    if getattr(faction, "last_migration_time", 0.0)
                    else 0.0,
                    3,
                ),
                "formed_elapsed": round(
                    max(0.0, current_time - float(getattr(faction, "formed_time", current_time) or current_time)),
                    3,
                ),
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
    tiles = []
    for tile_pos, data in getattr(territory_manager, "territory_grid", {}).items():
        if not isinstance(tile_pos, tuple) or len(tile_pos) != 2 or not isinstance(data, dict):
            continue
        claimed_time = float(data.get("claimed_time", current_time) or current_time)
        tiles.append(
            {
                "x": int(tile_pos[0]),
                "y": int(tile_pos[1]),
                "claim_strength": round(max(0.0, float(data.get("claim_strength", 0.0) or 0.0)), 3),
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
    serialized: dict[str, dict[str, float]] = {}
    modifiers = getattr(getattr(advisor, "game_modifiers", None), "temporary", {})
    for modifier_name, modifier_value in modifiers.items():
        if not isinstance(modifier_value, tuple) or len(modifier_value) != 2:
            continue
        multiplier, end_time = modifier_value
        remaining_seconds = max(0.0, float(end_time) - current_time)
        if remaining_seconds <= 0.0:
            continue
        serialized[modifier_name] = {
            "value": float(multiplier),
            "remaining_seconds": round(remaining_seconds, 3),
        }
    return serialized


def build_run_snapshot(
    thronglets,
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
):
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "saved_at": round(current_time, 3),
        "elapsed_seconds": round(max(0.0, current_time - game_start_time), 3),
        "scenario_id": scenario_id,
        "run_summary": _sanitize_json_value(run_summary),
        "season": getattr(season, "current", "summer"),
        "weather": getattr(weather_system, "current_weather", "clear"),
        "weather_next_event_in": round(max(0.0, getattr(weather_system, "next_event_time", current_time) - current_time), 3),
        "selected_model": selected_model,
        "population": len(thronglets),
        "camera": _serialize_camera_state(camera),
        "celebration": _serialize_celebration_state(celebration_state, current_time),
        "fog_of_war": _serialize_fog_of_war(fog_of_war),
        "territory": _serialize_territory(territory_manager, current_time),
        "factions": _serialize_factions(faction_manager, current_time),
        "city_planner": _serialize_city_planner(city_planner, current_time),
        "world": _serialize_world_state(world_map, current_time),
        "thronglets": [
            {
                "id": thronglet.id,
                "role": thronglet.role,
                "x": round(thronglet.x, 2),
                "y": round(thronglet.y, 2),
                "health": round(thronglet.health, 2),
                "happiness": round(getattr(thronglet, "happiness", 0.0), 2),
                "morale": round(getattr(thronglet, "morale", 0.0), 2),
                "inspiration": round(getattr(thronglet, "inspiration", 0.0), 2),
                "favorite_biome": getattr(thronglet, "favorite_biome", None),
                "age_seconds": round(getattr(thronglet, "age", 0.0), 2),
                "diseased": bool(getattr(thronglet, "diseased", False)),
                "resilience": round(getattr(thronglet, "resilience", 1.0), 3),
                "settlement_prosperity": round(getattr(thronglet, "settlement_prosperity", 0.5), 3),
                "inventory": dict(thronglet.inventory),
                "needs": dict(thronglet.needs),
                "state": getattr(thronglet, "state", None),
                "current_action": getattr(thronglet, "current_action", None),
                "personal_goal": _sanitize_json_value(getattr(thronglet, "personal_goal", None)),
                "goal_progress": round(getattr(thronglet, "goal_progress", 0.0), 3),
                "personality": _serialize_personality_traits(thronglet),
                "genetics": _serialize_genetics(thronglet),
                "generation": max(0, int(getattr(thronglet, "generation", 0))),
                "parent_ids": [int(parent_id) for parent_id in getattr(thronglet, "parent_ids", []) if isinstance(parent_id, (int, float))],
                "lineage_id": int(getattr(thronglet, "lineage_id", thronglet.id)),
                "mutation_count": max(0, int(getattr(thronglet, "mutation_count", 0))),
                "birth_origin": getattr(thronglet, "birth_origin", "founder"),
                "skills": _serialize_skills(thronglet),
                "bonds": _serialize_bonds(thronglet),
                "faction_id": getattr(thronglet, "faction_id", None),
                "known_resources": _serialize_known_resources(thronglet),
                "disease_elapsed": round(
                    max(0.0, current_time - float(getattr(thronglet, "disease_start_time", 0.0)))
                    if bool(getattr(thronglet, "diseased", False)) and getattr(thronglet, "disease_start_time", 0.0)
                    else 0.0,
                    3,
                ),
                "last_reproduction_elapsed": round(
                    max(0.0, current_time - float(getattr(thronglet, "last_reproduction_time", 0.0)))
                    if getattr(thronglet, "last_reproduction_time", 0.0)
                    else 0.0,
                    3,
                ),
                "goal_assigned_elapsed": round(
                    max(0.0, current_time - float(getattr(thronglet, "goal_assigned_time", 0.0)))
                    if getattr(thronglet, "goal_assigned_time", 0.0)
                    else 0.0,
                    3,
                ),
            }
            for thronglet in thronglets
        ],
        "buildings": [
            {
                "type": building.building_type,
                "x": round(building.x, 2),
                "y": round(building.y, 2),
                "level": getattr(building, "level", 1),
                "built_by": getattr(building, "built_by", None),
                "aura_strength": round(getattr(building, "aura_strength", 0.0), 3),
                "stored_resources": dict(building.stored_resources),
                "occupant_ids": [
                    int(occupant.id)
                    for occupant in getattr(building, "occupants", [])
                    if hasattr(occupant, "id")
                ],
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
