from __future__ import annotations

from copy import deepcopy


BUILDING_ORDER = ["house", "farm", "storage", "workshop", "shrine", "well"]

BUILDING_DEFINITIONS = {
    "house": {
        "name": "House",
        "cost": {"wood": 4, "stone": 0},
        "prompt_summary": "Base capacity 2 thronglets, capacity scales with building level, restores energy while inside.",
    },
    "farm": {
        "name": "Farm",
        "cost": {"wood": 5, "stone": 0},
        "prompt_summary": "Auto-produces food over time and becomes stronger inside developed districts.",
    },
    "storage": {
        "name": "Storage",
        "cost": {"wood": 3, "stone": 0},
        "prompt_summary": "Stores gathered resources and supports industrial districts.",
    },
    "workshop": {
        "name": "Workshop",
        "cost": {"wood": 6, "stone": 4},
        "prompt_summary": "Boosts production and inspiration in developed districts.",
    },
    "shrine": {
        "name": "Shrine",
        "cost": {"wood": 8, "stone": 5},
        "prompt_summary": "Raises happiness, morale, inspiration, and cultural growth.",
    },
    "well": {
        "name": "Well",
        "cost": {"wood": 0, "stone": 3},
        "prompt_summary": "Supports thirst management and lowers hygiene pressure.",
    },
}

TECH_TREE_DEFINITIONS = {
    "agriculture_1": {"cost": 100, "name": "Efficient Farming", "effect": {"farm_production_rate": 1.5}},
    "agriculture_2": {
        "cost": 250,
        "name": "Advanced Irrigation",
        "effect": {"farm_production_rate": 2.0},
        "requires": ["agriculture_1"],
    },
    "architecture_1": {"cost": 150, "name": "Improved Housing", "effect": {"house_capacity": 1.5}},
    "medicine_1": {"cost": 200, "name": "Basic Medicine", "effect": {"disease_recovery_rate": 2.0, "health_regen": 1.0}},
    "medicine_2": {
        "cost": 400,
        "name": "Advanced Healthcare",
        "effect": {"disease_recovery_rate": 4.0, "health_regen": 2.0},
        "requires": ["medicine_1"],
    },
    "social_1": {"cost": 100, "name": "Community Building", "effect": {"happiness_base": 1.2, "bond_decay": 0.7}},
    "exploration_1": {"cost": 150, "name": "Scout Training", "effect": {"thronglet_speed": 1.3}},
    "industry_1": {"cost": 200, "name": "Workshop Efficiency", "effect": {"workshop_bonus": 1.25, "build_speed": 1.2}},
}

ABILITY_DEFINITIONS = {
    "speed_burst": {"cost": 50, "duration": 30, "effect": {"thronglet_speed": 2.0}},
    "workers_focus": {"cost": 75, "duration": 60, "effect": {"gather_rate": 1.5, "build_speed": 1.3}},
    "heal_wave": {"cost": 100, "instant": True},
    "resource_blessing": {"cost": 80, "instant": True},
}

LEGACY_BONUS_DEFINITIONS = {
    "head_start": {"unlocked": False, "effect": "Start with 5 thronglets"},
    "wise_elders": {"unlocked": False, "effect": "Start with level 2 skills"},
    "prepared": {"unlocked": False, "effect": "Start with 10 food, 5 wood"},
    "architect": {"unlocked": False, "effect": "Start with 1 house, 1 storage"},
}

GOAL_TYPE_DEFINITIONS = [
    ("gather_food", "Collect food resources"),
    ("gather_wood", "Collect wood for buildings"),
    ("gather_stone", "Collect stone for advanced buildings"),
    ("explore_north", "Explore north of spawn"),
    ("explore_east", "Explore east of spawn"),
    ("reproduce", "Find mate and reproduce"),
    ("build_house", "Build a house"),
    ("build_farm", "Build a farm"),
    ("build_well", "Build a well"),
    ("rest", "Rest at a house"),
]


def clone_tech_tree():
    return deepcopy(TECH_TREE_DEFINITIONS)


def clone_abilities():
    return deepcopy(ABILITY_DEFINITIONS)


def clone_legacy_bonuses():
    return deepcopy(LEGACY_BONUS_DEFINITIONS)


def get_building_cost(building_type):
    building_data = BUILDING_DEFINITIONS.get(building_type, {})
    cost = building_data.get("cost", {})
    return cost.get("wood", 0), cost.get("stone", 0)


def format_building_prompt_lines():
    lines = []
    for building_type in BUILDING_ORDER:
        building_data = BUILDING_DEFINITIONS[building_type]
        wood_cost, stone_cost = get_building_cost(building_type)
        cost_parts = []
        if wood_cost:
            cost_parts.append(f"{wood_cost} wood")
        if stone_cost:
            cost_parts.append(f"{stone_cost} stone")
        cost_text = ", ".join(cost_parts) if cost_parts else "no cost"
        lines.append(
            f"- {building_data['name'].upper()} (cost: {cost_text}): {building_data['prompt_summary']}"
        )
    return lines


def format_goal_type_lines():
    return [f"- {goal_type}: {description}" for goal_type, description in GOAL_TYPE_DEFINITIONS]
