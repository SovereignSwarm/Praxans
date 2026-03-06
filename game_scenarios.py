from __future__ import annotations

from copy import deepcopy


DEFAULT_SCENARIO_ID = "standard"


SCENARIO_PRESETS = {
    "standard": {
        "name": "Standard Basin",
        "description": "Balanced autonomous colony growth with baseline weather and mutation pressure.",
        "spawn_biomes": ["plains", "forest"],
        "favorite_biomes": ["plains", "forest", "taiga"],
        "initial_population": 2,
        "starting_resources": {"food": 5, "wood": 3, "stone": 1},
        "queued_resources": {"food": 45, "wood": 32, "stone": 14},
        "season": "summer",
        "weather": "clear",
        "weather_delay_range": (45.0, 90.0),
        "starting_research": 0,
        "starting_diseased": 0,
        "disease_health_penalty": 0.0,
        "morale_bonus": 0.0,
        "inspiration_bonus": 0.0,
        "health_bonus": 0.0,
        "mutation_scale": 1.0,
        "initial_challenges": [],
    },
    "fertile_floodplain": {
        "name": "Fertile Floodplain",
        "description": "Food-rich spring start with gentler mutation pressure and fast early growth.",
        "spawn_biomes": ["plains", "forest", "swamp"],
        "favorite_biomes": ["plains", "forest", "swamp"],
        "initial_population": 3,
        "starting_resources": {"food": 8, "wood": 4, "stone": 2},
        "queued_resources": {"food": 58, "wood": 30, "stone": 10},
        "season": "spring",
        "weather": "rain",
        "weather_delay_range": (55.0, 95.0),
        "starting_research": 10,
        "starting_diseased": 0,
        "disease_health_penalty": 0.0,
        "morale_bonus": 8.0,
        "inspiration_bonus": 6.0,
        "health_bonus": 4.0,
        "mutation_scale": 0.85,
        "initial_challenges": [],
    },
    "harsh_winter_basin": {
        "name": "Harsh Winter Basin",
        "description": "Sparse food, cold terrain, and an early winter climate that pressures survival.",
        "spawn_biomes": ["taiga", "tundra", "plains"],
        "favorite_biomes": ["taiga", "tundra", "plains"],
        "initial_population": 3,
        "starting_resources": {"food": 4, "wood": 6, "stone": 3},
        "queued_resources": {"food": 30, "wood": 38, "stone": 18},
        "season": "winter",
        "weather": "clear",
        "weather_delay_range": (20.0, 45.0),
        "starting_research": 15,
        "starting_diseased": 0,
        "disease_health_penalty": 0.0,
        "morale_bonus": -6.0,
        "inspiration_bonus": 2.0,
        "health_bonus": 0.0,
        "mutation_scale": 1.0,
        "initial_challenges": [],
    },
    "plague_start": {
        "name": "Plague Start",
        "description": "A larger colony begins under disease pressure and must recover without intervention.",
        "spawn_biomes": ["plains", "forest", "swamp"],
        "favorite_biomes": ["plains", "forest", "swamp"],
        "initial_population": 4,
        "starting_resources": {"food": 5, "wood": 3, "stone": 1},
        "queued_resources": {"food": 40, "wood": 28, "stone": 12},
        "season": "summer",
        "weather": "rain",
        "weather_delay_range": (25.0, 50.0),
        "starting_research": 20,
        "starting_diseased": 2,
        "disease_health_penalty": 12.0,
        "morale_bonus": -8.0,
        "inspiration_bonus": 0.0,
        "health_bonus": -4.0,
        "mutation_scale": 1.05,
        "initial_challenges": [
            {"type": "plague", "duration": 55.0, "reward": 80, "active": True},
        ],
    },
    "scarce_stone": {
        "name": "Scarce Stone",
        "description": "Construction is throttled by mineral scarcity, pushing different settlement patterns.",
        "spawn_biomes": ["forest", "plains"],
        "favorite_biomes": ["forest", "plains", "taiga"],
        "initial_population": 3,
        "starting_resources": {"food": 6, "wood": 5, "stone": 0},
        "queued_resources": {"food": 48, "wood": 34, "stone": 5},
        "season": "autumn",
        "weather": "clear",
        "weather_delay_range": (40.0, 80.0),
        "starting_research": 12,
        "starting_diseased": 0,
        "disease_health_penalty": 0.0,
        "morale_bonus": 2.0,
        "inspiration_bonus": 0.0,
        "health_bonus": 0.0,
        "mutation_scale": 1.0,
        "initial_challenges": [],
    },
    "high_mutation": {
        "name": "High Mutation",
        "description": "Larger starting cluster with elevated mutation variance to accelerate divergence.",
        "spawn_biomes": ["plains", "forest", "desert"],
        "favorite_biomes": ["plains", "forest", "desert", "tundra"],
        "initial_population": 5,
        "starting_resources": {"food": 6, "wood": 4, "stone": 2},
        "queued_resources": {"food": 45, "wood": 30, "stone": 14},
        "season": "spring",
        "weather": "aurora",
        "weather_delay_range": (30.0, 60.0),
        "starting_research": 8,
        "starting_diseased": 0,
        "disease_health_penalty": 0.0,
        "morale_bonus": 4.0,
        "inspiration_bonus": 10.0,
        "health_bonus": 0.0,
        "mutation_scale": 1.8,
        "initial_challenges": [],
    },
}


def list_scenario_ids() -> tuple[str, ...]:
    return tuple(SCENARIO_PRESETS.keys())


def format_scenario_help() -> str:
    return ", ".join(f"{scenario_id} ({preset['name']})" for scenario_id, preset in SCENARIO_PRESETS.items())


def get_scenario_profile(scenario_id: str | None = None) -> dict:
    normalized_id = (scenario_id or DEFAULT_SCENARIO_ID).strip().lower()
    if normalized_id not in SCENARIO_PRESETS:
        raise KeyError(f"Unknown scenario: {scenario_id}")
    profile = deepcopy(SCENARIO_PRESETS[normalized_id])
    profile["id"] = normalized_id
    return profile
