from __future__ import annotations

from copy import deepcopy


BUILDING_ORDER = ["house", "farm", "storage", "workshop", "shrine", "well", "hospital", "school", "watchtower", "market"]

BUILDING_DEFINITIONS = {
    "house": {
        "name": "House",
        "cost": {"wood": 4, "stone": 0},
        "beauty": 5,
        "prompt_summary": "Base capacity 2 praxans, capacity scales with building level, restores energy while inside.",
    },
    "farm": {
        "name": "Farm",
        "cost": {"wood": 5, "stone": 0},
        "beauty": 2,
        "prompt_summary": "Auto-produces food over time and becomes stronger inside developed districts.",
    },
    "storage": {
        "name": "Storage",
        "cost": {"wood": 3, "stone": 0},
        "beauty": -2,
        "prompt_summary": "Stores gathered resources and supports industrial districts.",
    },
    "workshop": {
        "name": "Workshop",
        "cost": {"wood": 6, "stone": 4},
        "beauty": 1,
        "prompt_summary": "Boosts production and inspiration in developed districts.",
    },
    "shrine": {
        "name": "Shrine",
        "cost": {"wood": 8, "stone": 5},
        "beauty": 15,
        "prompt_summary": "Raises happiness, morale, inspiration, and cultural growth.",
    },
    "well": {
        "name": "Well",
        "cost": {"wood": 0, "stone": 3},
        "beauty": 3,
        "prompt_summary": "Supports thirst management and lowers hygiene pressure.",
    },
    "hospital": {
        "name": "Hospital",
        "cost": {"wood": 10, "stone": 8},
        "beauty": 8,
        "prompt_summary": "Greatly accelerates disease recovery and passively restores health.",
    },
    "school": {
        "name": "School",
        "cost": {"wood": 12, "stone": 6},
        "beauty": 10,
        "prompt_summary": "Accelerates skill acquisition and experience gain for nearby praxans.",
    },
    "watchtower": {
        "name": "Watchtower",
        "cost": {"wood": 15, "stone": 15},
        "beauty": 5,
        "prompt_summary": "Expands territory claims significantly and provides massive visibility radius.",
    },
    "market": {
        "name": "Market",
        "cost": {"wood": 20, "stone": 10},
        "beauty": 12,
        "prompt_summary": "Boosts faction cohesion, distributes resources, and raises prosperity.",
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
    "social_2": {
        "cost": 300,
        "name": "Diplomatic Doctrine",
        "effect": {"happiness_base": 1.4, "bond_decay": 0.5},
        "requires": ["social_1"],
    },
    "exploration_1": {"cost": 150, "name": "Scout Training", "effect": {"praxan_speed": 1.3}},
    "industry_1": {"cost": 200, "name": "Workshop Efficiency", "effect": {"workshop_bonus": 1.25, "build_speed": 1.2}},
}

ABILITY_DEFINITIONS = {
    "speed_burst": {"cost": 50, "duration": 30, "effect": {"praxan_speed": 2.0}},
    "workers_focus": {"cost": 75, "duration": 60, "effect": {"gather_rate": 1.5, "build_speed": 1.3}},
    "heal_wave": {"cost": 100, "instant": True},
    "resource_blessing": {"cost": 80, "instant": True},
}

LEGACY_BONUS_DEFINITIONS = {
    "head_start": {"unlocked": False, "effect": "Start with 5 praxans"},
    "wise_elders": {"unlocked": False, "effect": "Start with level 2 skills"},
    "prepared": {"unlocked": False, "effect": "Start with 10 food, 5 wood"},
    "architect": {"unlocked": False, "effect": "Start with 1 house, 1 storage"},
    "iron_stomach": {"unlocked": False, "effect": "Start with 10% disease resistance"},
    "sprinter": {"unlocked": False, "effect": "Start with +10 base speed"},
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

# ---- Phase 3B: Armor & Weapons ----

ARMOR_DEFS = {
    "cloth_tunic":   {"name": "Cloth Tunic",   "armor_rating": 0.15, "move_penalty": 0.0,  "cost": {"wood": 0, "stone": 0}},
    "leather_vest":  {"name": "Leather Vest",  "armor_rating": 0.30, "move_penalty": 0.02, "cost": {"wood": 2, "stone": 0}},
    "chain_mail":    {"name": "Chain Mail",    "armor_rating": 0.55, "move_penalty": 0.08, "cost": {"wood": 0, "stone": 5}},
    "plate_armor":   {"name": "Plate Armor",   "armor_rating": 0.75, "move_penalty": 0.15, "cost": {"wood": 0, "stone": 10}},
}

WEAPON_DEFS = {
    "fists":        {"name": "Fists",        "damage": 5,  "penetration": 0.0,  "speed": 1.0,  "range": 1},
    "club":         {"name": "Club",         "damage": 10, "penetration": 0.05, "speed": 0.8,  "range": 1},
    "spear":        {"name": "Spear",        "damage": 12, "penetration": 0.20, "speed": 0.9,  "range": 2},
    "sword":        {"name": "Sword",        "damage": 15, "penetration": 0.35, "speed": 1.0,  "range": 1},
    "short_bow":    {"name": "Short Bow",    "damage": 8,  "penetration": 0.15, "speed": 1.2,  "range": 8},
}

# ---- Phase 3C: Item Quality & Crafting ----

QUALITY_LEVELS = ['Awful', 'Poor', 'Normal', 'Good', 'Excellent', 'Masterwork', 'Legendary']

QUALITY_MULTIPLIERS = {
    'Awful':       0.5,
    'Poor':        0.75,
    'Normal':      1.0,
    'Good':        1.15,
    'Excellent':   1.3,
    'Masterwork':  1.5,
    'Legendary':   2.0,
}

JOB_DEFS = {
    "CookMeal": {
        "work_type": "Cooking",
        "station": "farm",
        "ingredients": [{"type": "food", "amount": 1}],
        "output": "meal",
        "skill_factor": "cooking",
        "base_work": 400,
    },
    "SmithArmor": {
        "work_type": "Crafting",
        "station": "workshop",
        "ingredients": [{"type": "stone", "amount": 5}],
        "output": "chain_mail",
        "skill_factor": "crafting",
        "base_work": 800,
    },
    "CraftWeapon": {
        "work_type": "Crafting",
        "station": "workshop",
        "ingredients": [{"type": "wood", "amount": 3}, {"type": "stone", "amount": 2}],
        "output": "spear",
        "skill_factor": "crafting",
        "base_work": 600,
    },
}

MOOD_DEFS = {
    "AteRawFood":         {"mood_offset": -7, "duration": 86400},
    "AteFineFood":        {"mood_offset": 5,  "duration": 86400},
    "Catharsis":          {"mood_offset": 30, "duration": 300},
    "FoughtOffInfection": {"mood_offset": 5,  "duration": 120},
}



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
