from __future__ import annotations

from copy import deepcopy
from systems.def_database import DefDatabase

BUILDING_ORDER = ["house", "farm", "storage", "workshop", "shrine", "well", "hospital", "school", "watchtower", "market"]

# Compatibility shim: other modules still reference this constant.
# After DefDatabase.initialize(), this returns the same dict shape as the old hardcoded definitions.
def _get_building_definitions():
    """Lazy accessor so it works both before and after DefDatabase.initialize()."""
    return DefDatabase.get_all("BuildingDef")

class _BuildingDefsProxy(dict):
    """Dict-like proxy that always reads from DefDatabase at access time."""
    def __getitem__(self, key):
        return _get_building_definitions()[key]
    def get(self, key, default=None):
        return _get_building_definitions().get(key, default)
    def __contains__(self, key):
        return key in _get_building_definitions()
    def __iter__(self):
        return iter(_get_building_definitions())
    def __len__(self):
        return len(_get_building_definitions())
    def items(self):
        return _get_building_definitions().items()
    def keys(self):
        return _get_building_definitions().keys()
    def values(self):
        return _get_building_definitions().values()

BUILDING_DEFINITIONS = _BuildingDefsProxy()


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
# Now loaded from defs/core/items.json via DefDatabase

class _DefProxy(dict):
    """Dict-like proxy that always reads from DefDatabase at access time."""
    def __init__(self, def_type):
        self._def_type = def_type
    def _data(self):
        return DefDatabase.get_all(self._def_type)
    def __getitem__(self, key):
        return self._data()[key]
    def get(self, key, default=None):
        return self._data().get(key, default)
    def __contains__(self, key):
        return key in self._data()
    def __iter__(self):
        return iter(self._data())
    def __len__(self):
        return len(self._data())
    def items(self):
        return self._data().items()
    def keys(self):
        return self._data().keys()
    def values(self):
        return self._data().values()

ARMOR_DEFS = _DefProxy("ArmorDef")
WEAPON_DEFS = _DefProxy("WeaponDef")

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

JOB_DEFS = _DefProxy("JobDef")

MOOD_DEFS = _DefProxy("MoodDef")



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
