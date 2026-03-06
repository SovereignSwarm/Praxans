from __future__ import annotations

from copy import deepcopy
from systems.def_database import DefDatabase

BUILDING_ORDER = ["house", "farm", "storage", "workshop", "shrine", "well", "hospital", "school", "watchtower", "market"]

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
    return {k: dict(v) for k, v in DefDatabase.get_all("TechDef").items()}


def clone_abilities():
    return {k: dict(v) for k, v in DefDatabase.get_all("AbilityDef").items()}


def clone_legacy_bonuses():
    return deepcopy(LEGACY_BONUS_DEFINITIONS)


def get_building_cost(building_type):
    building_data = DefDatabase.get("BuildingDef", building_type, {})
    cost = building_data.get("cost", {})
    return cost.get("wood", 0), cost.get("stone", 0)


def format_building_prompt_lines():
    lines = []
    for building_type in BUILDING_ORDER:
        building_data = DefDatabase.get("BuildingDef", building_type)
        if not building_data: continue
        wood_cost, stone_cost = get_building_cost(building_type)
        cost_parts = []
        if wood_cost:
            cost_parts.append(f"{wood_cost} wood")
        if stone_cost:
            cost_parts.append(f"{stone_cost} stone")
        cost_text = ", ".join(cost_parts) if cost_parts else "no cost"
        lines.append(
            f"- {building_data.get('name', building_type).upper()} (cost: {cost_text}): {building_data.get('prompt_summary', '')}"
        )
    return lines


def format_goal_type_lines():
    return [f"- {goal_type}: {description}" for goal_type, description in GOAL_TYPE_DEFINITIONS]
