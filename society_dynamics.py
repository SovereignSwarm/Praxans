from __future__ import annotations

from collections import Counter
from typing import Any


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _avg(values: list[float], default: float = 0.0) -> float:
    return (sum(values) / len(values)) if values else default


def compute_faction_metrics(
    member_snapshots: list[dict[str, Any]],
    avg_bond: float,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not member_snapshots:
        return {
            "ideology": {axis: 0.0 for axis in ("growth", "security", "industry", "exploration", "harmony")},
            "primary_doctrine": "growth",
            "cohesion": 0.0,
            "stability": 0.0,
            "schism_pressure": 0.0,
            "migration_pressure": 0.0,
            "preferred_biome": "plains",
            "resource_stress": 0.0,
            "food_security": 52.0,
            "material_security": 48.0,
            "ecology_fertility": 70.0,
        }

    count = len(member_snapshots)
    avg_health = _avg([float(member.get("health", 100.0)) for member in member_snapshots], 100.0)
    avg_happiness = _avg([float(member.get("happiness", 70.0)) for member in member_snapshots], 70.0)
    avg_morale = _avg([float(member.get("morale", 65.0)) for member in member_snapshots], 65.0)
    avg_curiosity = _avg([float(member.get("curiosity", 0.5)) for member in member_snapshots], 0.5)
    avg_sociability = _avg([float(member.get("sociability", 0.5)) for member in member_snapshots], 0.5)
    avg_learning = _avg([float(member.get("learning_affinity", 1.0)) for member in member_snapshots], 1.0)
    avg_immunity = _avg([float(member.get("immune_strength", 1.0)) for member in member_snapshots], 1.0)
    avg_fertility = _avg([float(member.get("fertility_drive", 1.0)) for member in member_snapshots], 1.0)
    avg_cohesion_trait = _avg([float(member.get("social_cohesion", 1.0)) for member in member_snapshots], 1.0)
    avg_adaptability = _avg([float(member.get("adaptability", 1.0)) for member in member_snapshots], 1.0)
    avg_known_resources = _avg([float(member.get("known_resources_count", 0)) for member in member_snapshots], 0.0)

    diseased_members = sum(1 for member in member_snapshots if member.get("diseased"))
    role_counts = Counter(str(member.get("role") or "unassigned") for member in member_snapshots)
    biome_counts = Counter(str(member.get("favorite_biome") or "plains") for member in member_snapshots)
    builder_share = role_counts.get("builder", 0) / count
    explorer_share = role_counts.get("explorer", 0) / count
    gatherer_share = role_counts.get("gatherer", 0) / count
    role_diversity = len([role for role in role_counts if role != "unassigned"]) / 3.0
    biome_diversity = len(biome_counts) / max(1, count)

    context = dict(context or {})
    food_security = _clamp(float(context.get("food_security", 52.0)), 0.0, 100.0)
    material_security = _clamp(float(context.get("material_security", 48.0)), 0.0, 100.0)
    ecology_fertility = _clamp(float(context.get("ecology_fertility", 70.0)), 0.0, 100.0)
    inferred_stress = _clamp(
        max(0.0, 55.0 - food_security) * 0.9
        + max(0.0, 50.0 - material_security) * 0.55
        + max(0.0, 60.0 - ecology_fertility) * 0.42
        - min(20.0, avg_known_resources * 1.8),
        0.0,
        100.0,
    )
    resource_stress = _clamp(float(context.get("resource_stress", inferred_stress)), 0.0, 100.0)
    scarcity = resource_stress / 100.0

    ideology = {
        "growth": round(
            avg_fertility
            + (avg_morale / 100.0)
            + max(0.0, (count - 2) * 0.08)
            + (food_security / 100.0) * 0.28,
            3,
        ),
        "security": round(
            avg_immunity
            + avg_adaptability
            + (avg_health / 100.0)
            - (diseased_members * 0.08)
            + max(0.0, 58.0 - food_security) * 0.012
            + max(0.0, 54.0 - ecology_fertility) * 0.01,
            3,
        ),
        "industry": round(
            avg_learning
            + builder_share
            + (gatherer_share * 0.45)
            + max(0.0, 62.0 - material_security) * 0.012,
            3,
        ),
        "exploration": round(
            avg_curiosity
            + explorer_share
            + (avg_adaptability * 0.35)
            + min(0.45, avg_known_resources * 0.03)
            + max(0.0, 58.0 - ecology_fertility) * 0.009,
            3,
        ),
        "harmony": round(
            avg_cohesion_trait
            + avg_sociability
            + (avg_bond / 100.0)
            - scarcity * 0.24,
            3,
        ),
    }
    primary_doctrine = max(ideology.items(), key=lambda item: item[1])[0]

    cohesion = _clamp(
        (avg_bond * 0.56)
        + (avg_happiness * 0.18)
        + (avg_cohesion_trait * 18.0)
        - (diseased_members * 4.5)
        - (biome_diversity * 8.0)
        - (resource_stress * 0.18),
        0.0,
        100.0,
    )
    stability = _clamp(
        (cohesion * 0.68)
        + (avg_morale * 0.32)
        - (role_diversity * 8.0)
        - (resource_stress * 0.22),
        0.0,
        100.0,
    )
    ideology_spread = max(ideology.values()) - min(ideology.values())
    schism_pressure = _clamp(
        max(0.0, 62.0 - cohesion) * 0.95
        + max(0.0, count - 3) * 6.5
        + biome_diversity * 26.0
        + role_diversity * 18.0
        + ideology_spread * 8.0
        + (resource_stress * 0.28),
        0.0,
        100.0,
    )
    migration_pressure = _clamp(
        (avg_curiosity * 22.0)
        + (avg_adaptability * 18.0)
        + (avg_known_resources * 6.0)
        + (biome_diversity * 16.0)
        + max(0.0, 58.0 - cohesion) * 0.3
        + (resource_stress * 0.35)
        + max(0.0, 55.0 - food_security) * 0.25
        + (12.0 if primary_doctrine == "exploration" else 0.0)
        + (6.0 if primary_doctrine == "growth" else 0.0)
        - (8.0 if primary_doctrine == "harmony" else 0.0),
        0.0,
        100.0,
    )

    preferred_biome = biome_counts.most_common(1)[0][0] if biome_counts else "plains"
    return {
        "ideology": ideology,
        "primary_doctrine": primary_doctrine,
        "cohesion": round(cohesion, 3),
        "stability": round(stability, 3),
        "schism_pressure": round(schism_pressure, 3),
        "migration_pressure": round(migration_pressure, 3),
        "preferred_biome": preferred_biome,
        "resource_stress": round(resource_stress, 3),
        "food_security": round(food_security, 3),
        "material_security": round(material_security, 3),
        "ecology_fertility": round(ecology_fertility, 3),
    }


def choose_schism_members(
    member_snapshots: list[dict[str, Any]],
    leader_id: int | None,
    preferred_biome: str,
    minimum_size: int = 2,
) -> list[int]:
    if len(member_snapshots) < minimum_size * 2:
        return []

    dissenters: list[tuple[float, int]] = []
    for member in member_snapshots:
        member_id = int(member.get("id", -1))
        if member_id == leader_id:
            continue
        leader_bond = float(member.get("leader_bond", 50.0))
        happiness = float(member.get("happiness", 70.0))
        curiosity = float(member.get("curiosity", 0.5))
        cohesion_trait = float(member.get("social_cohesion", 1.0))
        score = max(0.0, 60.0 - leader_bond) * 0.9
        score += max(0.0, 52.0 - happiness) * 0.45
        score += curiosity * 16.0
        score += max(0.0, 1.0 - cohesion_trait) * 12.0
        if str(member.get("favorite_biome") or "plains") != preferred_biome:
            score += 9.0
        if str(member.get("role") or "") == "explorer":
            score += 5.0
        if score >= 22.0:
            dissenters.append((score, member_id))

    dissenters.sort(key=lambda item: (-item[0], item[1]))
    if len(dissenters) < minimum_size:
        return []

    target_size = min(max(minimum_size, len(dissenters)), max(minimum_size, len(member_snapshots) // 2))
    selected = [member_id for _, member_id in dissenters[:target_size]]
    if len(member_snapshots) - len(selected) < minimum_size:
        return []
    return selected


def choose_migration_target(
    centroid: tuple[float, float] | None,
    member_snapshots: list[dict[str, Any]],
    doctrine_key: str,
    world_width: float,
    world_height: float,
    migration_pressure: float,
    world_map: Any | None = None,
) -> tuple[float, float] | None:
    if centroid is None or migration_pressure < 30.0:
        return None

    if world_map is not None and hasattr(world_map, "get_route_target_for_migration"):
        route_target = world_map.get_route_target_for_migration(centroid, doctrine_key, migration_pressure)
        if route_target:
            return route_target

    known_positions: list[tuple[float, float]] = []
    for member in member_snapshots:
        for resource_pos in member.get("known_resources", []):
            if not isinstance(resource_pos, (list, tuple)) or len(resource_pos) != 2:
                continue
            candidate = (float(resource_pos[0]), float(resource_pos[1]))
            if candidate not in known_positions:
                known_positions.append(candidate)

    if known_positions:
        cx, cy = centroid
        if doctrine_key in {"exploration", "growth", "industry"}:
            target = max(known_positions, key=lambda pos: ((pos[0] - cx) ** 2) + ((pos[1] - cy) ** 2))
        else:
            target = min(known_positions, key=lambda pos: ((pos[0] - cx) ** 2) + ((pos[1] - cy) ** 2))
        return (
            _clamp(target[0], 40.0, max(40.0, world_width - 40.0)),
            _clamp(target[1], 40.0, max(40.0, world_height - 40.0)),
        )

    doctrine_vectors = {
        "growth": (0.0, 1.0),
        "security": (-1.0, 0.0),
        "industry": (1.0, 0.0),
        "exploration": (0.7, -0.7),
        "harmony": (0.0, -1.0),
    }
    vector_x, vector_y = doctrine_vectors.get(doctrine_key, (0.8, 0.2))
    distance = 120.0 + min(120.0, migration_pressure * 1.5)
    return (
        _clamp(centroid[0] + (vector_x * distance), 40.0, max(40.0, world_width - 40.0)),
        _clamp(centroid[1] + (vector_y * distance), 40.0, max(40.0, world_height - 40.0)),
    )

