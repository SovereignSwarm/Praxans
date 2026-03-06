"""
PolicyManager — Global restriction policies for the colony.

Provides three policy axes that influence pawn behavior:
  - Food: controls meal quality preference
  - Medical: caps tend quality by restricting medicine usage
  - Hostility: determines pawn response when threats appear
"""
from __future__ import annotations


# ---- Food Policies ----
FOOD_LAVISH = "lavish"          # Pawns seek fine / cooked meals first
FOOD_SIMPLE = "simple"          # Pawns eat whatever is available
FOOD_RAW_ONLY = "raw_only"     # No cooking allowed — raw food only

# ---- Medical Policies ----
MED_BEST = "best_available"     # Use best medicine (no cap)
MED_HERBAL = "herbal_only"     # Tend quality capped at 0.6
MED_NONE = "no_medicine"       # No tending allowed

# ---- Hostility Responses ----
HOSTILITY_FLEE = "flee"         # Pawns run to nearest shelter on threat
HOSTILITY_FIGHT = "fight"      # Pawns engage hostile entities
HOSTILITY_IGNORE = "ignore"    # Pawns continue normal work (dangerous)


class PolicyManager:
    """Manages global restriction policies for the colony."""

    def __init__(self):
        self.food_policy = FOOD_SIMPLE
        self.medical_policy = MED_BEST
        self.hostility_policy = HOSTILITY_FLEE

    # ---- Accessors ----

    def get_food_policy(self) -> str:
        return self.food_policy

    def get_medical_policy(self) -> str:
        return self.medical_policy

    def get_hostility_policy(self) -> str:
        return self.hostility_policy

    # ---- Setters ----

    def set_food_policy(self, policy: str):
        if policy in (FOOD_LAVISH, FOOD_SIMPLE, FOOD_RAW_ONLY):
            self.food_policy = policy

    def set_medical_policy(self, policy: str):
        if policy in (MED_BEST, MED_HERBAL, MED_NONE):
            self.medical_policy = policy

    def set_hostility_policy(self, policy: str):
        if policy in (HOSTILITY_FLEE, HOSTILITY_FIGHT, HOSTILITY_IGNORE):
            self.hostility_policy = policy

    # ---- Gameplay Modifiers ----

    def get_tend_quality_cap(self) -> float:
        """Returns the maximum tend quality allowed by current medical policy."""
        if self.medical_policy == MED_HERBAL:
            return 0.6
        elif self.medical_policy == MED_NONE:
            return 0.0
        return 1.0  # best_available

    def should_cook(self) -> bool:
        """Returns True if the food policy allows cooking."""
        return self.food_policy != FOOD_RAW_ONLY

    def allows_fine_meals(self) -> bool:
        """Returns True if lavish meal cooking is allowed."""
        return self.food_policy == FOOD_LAVISH

    def allows_tending(self) -> bool:
        """Returns True if medical tending is allowed."""
        return self.medical_policy != MED_NONE

    def get_threat_response(self) -> str:
        """Returns the current hostility response mode."""
        return self.hostility_policy

    # ---- Cycling (for UI buttons) ----

    def cycle_food(self):
        cycle = [FOOD_SIMPLE, FOOD_LAVISH, FOOD_RAW_ONLY]
        idx = cycle.index(self.food_policy) if self.food_policy in cycle else 0
        self.food_policy = cycle[(idx + 1) % len(cycle)]

    def cycle_medical(self):
        cycle = [MED_BEST, MED_HERBAL, MED_NONE]
        idx = cycle.index(self.medical_policy) if self.medical_policy in cycle else 0
        self.medical_policy = cycle[(idx + 1) % len(cycle)]

    def cycle_hostility(self):
        cycle = [HOSTILITY_FLEE, HOSTILITY_FIGHT, HOSTILITY_IGNORE]
        idx = cycle.index(self.hostility_policy) if self.hostility_policy in cycle else 0
        self.hostility_policy = cycle[(idx + 1) % len(cycle)]

    # ---- Serialization ----

    def to_dict(self) -> dict:
        return {
            "food_policy": self.food_policy,
            "medical_policy": self.medical_policy,
            "hostility_policy": self.hostility_policy,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PolicyManager":
        pm = cls()
        pm.food_policy = data.get("food_policy", FOOD_SIMPLE)
        pm.medical_policy = data.get("medical_policy", MED_BEST)
        pm.hostility_policy = data.get("hostility_policy", HOSTILITY_FLEE)
        return pm
