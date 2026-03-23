"""Social Interaction Engine — executes InteractionDef outcomes between Praxans.

The interaction definitions live in ``defs/core/interactions.json`` and are
loaded via ``DefDatabase``.  This module provides:

- **Precondition checking** against opinion, bond, life stage, food, mood,
  skill gap, and trait boosts.
- **Personality-weighted selection** so sociable Praxans prefer different
  interactions than solitary ones.
- **Outcome application**: social need, moodlets, bond/opinion changes,
  hunger, comfort, XP, episodic memory, and EventBus publishing.
- **Per-praxan cooldown tracking** so the same interaction can't spam.
"""

from __future__ import annotations

import random
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Interaction cache (lazily loaded from DefDatabase)
# ---------------------------------------------------------------------------

_interaction_cache: list[dict[str, Any]] = []


def _load_interactions() -> list[dict[str, Any]]:
    """Load all InteractionDefs from DefDatabase (cached)."""
    global _interaction_cache
    if _interaction_cache:
        return _interaction_cache
    try:
        from systems.def_database import DefDatabase
        defs = DefDatabase.get_all("InteractionDef")
        if defs:
            _interaction_cache = list(defs.values())
    except Exception:
        pass
    return _interaction_cache


def clear_cache() -> None:
    """Clear cached interaction defs (for testing)."""
    global _interaction_cache
    _interaction_cache = []


# ---------------------------------------------------------------------------
# Precondition checks
# ---------------------------------------------------------------------------

def check_preconditions(
    interaction: dict[str, Any],
    initiator: Any,
    target: Any,
) -> bool:
    """Return True if *initiator* can perform *interaction* on *target*."""
    prec = interaction.get("preconditions", {})

    # Life stage gate
    allowed_stages = prec.get("life_stages")
    if allowed_stages:
        stage = getattr(initiator, "life_stage", "adult")
        if stage not in allowed_stages:
            return False

    # Opinion gates
    opinion = initiator.opinions.get(target.id, 0)
    if "min_opinion" in prec and opinion < prec["min_opinion"]:
        return False
    if "max_opinion" in prec and opinion > prec["max_opinion"]:
        return False

    # Bond gate
    if "min_bond" in prec:
        bond = initiator.bonds.get(target.id, 0)
        if bond < prec["min_bond"]:
            return False

    # Initiator has food (for share_meal)
    if prec.get("initiator_has_food"):
        has_food = getattr(initiator, "needs", {}).get("hunger", 0) > 50
        if not has_food:
            return False

    # Target low mood (for comfort)
    if prec.get("target_low_mood"):
        target_mood = getattr(target, "happiness", 50)
        if target_mood > 35:
            return False

    # Skill gap required (for teach)
    if prec.get("skill_gap_required"):
        if not _has_skill_gap(initiator, target):
            return False

    return True


def _has_skill_gap(initiator: Any, target: Any) -> bool:
    """Return True if initiator has at least one skill 2+ levels above target."""
    i_skills = getattr(initiator, "skills", {})
    t_skills = getattr(target, "skills", {})
    for skill_name, i_data in i_skills.items():
        i_level = i_data.get("level", 1) if isinstance(i_data, dict) else 1
        t_data = t_skills.get(skill_name, {})
        t_level = t_data.get("level", 1) if isinstance(t_data, dict) else 1
        if i_level >= t_level + 2:
            return True
    return False


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def _personality_score(interaction: dict, initiator: Any) -> float:
    """Compute a personality-weighted desirability score for *interaction*."""
    weights = interaction.get("initiator_weights", {})
    personality = getattr(initiator, "personality", {})
    score = 1.0
    for trait_key, weight in weights.items():
        trait_val = personality.get(trait_key, 0.5)
        score += weight * trait_val
    # Trait boost (e.g. Volatile boosts insult chance)
    # praxan.traits is a list of strings (trait names), not dicts
    trait_boost = interaction.get("preconditions", {}).get("trait_boost", [])
    if trait_boost:
        praxan_traits = list(getattr(initiator, "traits", []))
        if any(t in praxan_traits for t in trait_boost):
            chance = interaction.get("precondition_trait_chance", 0.3)
            score += chance * 3  # Notable bump for trait match
    return max(0.05, score)


def select_interaction(
    initiator: Any,
    target: Any,
    cooldowns: Optional[dict[str, float]] = None,
) -> Optional[dict[str, Any]]:
    """Pick the best valid interaction from loaded InteractionDefs.

    Uses personality-weighted random selection among interactions whose
    preconditions pass and whose cooldown has expired.

    Returns None if no valid interaction is available.
    """
    interactions = _load_interactions()
    if not interactions:
        return None

    now = time.time()
    candidates: list[tuple[dict, float]] = []

    for idef in interactions:
        # Cooldown check
        iid = idef.get("id", "")
        if cooldowns:
            last_used = cooldowns.get(iid, 0)
            cooldown = idef.get("cooldown", 15.0)
            if now - last_used < cooldown:
                continue

        if check_preconditions(idef, initiator, target):
            weight = _personality_score(idef, initiator)
            candidates.append((idef, weight))

    if not candidates:
        return None

    # Weighted random pick
    total = sum(w for _, w in candidates)
    roll = random.random() * total
    cumulative = 0.0
    for idef, w in candidates:
        cumulative += w
        if roll <= cumulative:
            return idef
    return candidates[-1][0]


# ---------------------------------------------------------------------------
# Outcome application
# ---------------------------------------------------------------------------

def _apply_side_outcomes(
    praxan: Any,
    outcomes: dict[str, Any],
    current_time: float,
    moodlet_name: str,
    moodlet_duration: float = 120.0,
) -> None:
    """Apply outcomes to one side (initiator or target)."""
    # Social need
    social_gain = outcomes.get("social_need", 0)
    if social_gain and hasattr(praxan, "needs"):
        praxan.needs["social"] = max(0, min(100, praxan.needs.get("social", 50) + social_gain))

    # Mood offset → moodlet
    mood_offset = outcomes.get("mood_offset", 0)
    if mood_offset and hasattr(praxan, "add_moodlet"):
        praxan.add_moodlet(moodlet_name, mood_offset, moodlet_duration, current_time)

    # Hunger change
    hunger_change = outcomes.get("hunger_change", 0)
    if hunger_change and hasattr(praxan, "needs"):
        praxan.needs["hunger"] = max(0, min(100, praxan.needs.get("hunger", 50) + hunger_change))

    # Comfort change
    comfort_change = outcomes.get("comfort_change", 0)
    if comfort_change and hasattr(praxan, "needs"):
        praxan.needs["comfort"] = max(0, min(100, praxan.needs.get("comfort", 50) + comfort_change))

    # XP gain (teach interaction)
    xp_gain = outcomes.get("xp_gain", 0)
    if xp_gain and hasattr(praxan, "gain_skill_xp"):
        # Pick the target's lowest skill to teach
        skills = getattr(praxan, "skills", {})
        if skills:
            lowest_skill = min(skills, key=lambda s: skills[s].get("level", 1) if isinstance(skills[s], dict) else 1)
            praxan.gain_skill_xp(lowest_skill, xp_gain)


def execute_interaction(
    initiator: Any,
    target: Any,
    interaction: dict[str, Any],
    event_bus: Any = None,
) -> dict[str, Any]:
    """Execute an interaction and apply all outcomes.

    Returns a summary dict with what happened (for logging / narrative).
    """
    current_time = time.time()
    iid = interaction.get("id", "unknown")
    label = interaction.get("label", iid)
    outcomes = interaction.get("outcomes", {})

    # Moodlet names per interaction id
    MOODLET_NAMES = {
        "chat": "HadChat",
        "deep_conversation": "HadDeepTalk",
        "argument": "HadArgument",
        "share_meal": "SharedMeal",
        "teach": "TaughtSomeone",
        "comfort": "GaveComfort",
        "play": "HadFun",
        "insult": "WasInsulted",
    }
    TARGET_MOODLET_NAMES = {
        "teach": "LearnedFromMentor",
        "comfort": "WasComforted",
        "insult": "WasInsulted",
    }

    moodlet_init = MOODLET_NAMES.get(iid, f"Social_{label}")
    moodlet_targ = TARGET_MOODLET_NAMES.get(iid, moodlet_init)
    duration = interaction.get("duration", 3.0) * 40  # Game-seconds moodlet duration

    # Apply initiator outcomes
    init_outcomes = outcomes.get("initiator", {})
    _apply_side_outcomes(initiator, init_outcomes, current_time, moodlet_init, duration)

    # Apply target outcomes
    targ_outcomes = outcomes.get("target", {})
    _apply_side_outcomes(target, targ_outcomes, current_time, moodlet_targ, duration)

    # Bond changes
    init_bond_change = init_outcomes.get("bond_change", 0)
    targ_bond_change = targ_outcomes.get("bond_change", 0)
    avg_bond_change = (init_bond_change + targ_bond_change) / 2.0

    if hasattr(initiator, "bonds"):
        if target.id not in initiator.bonds:
            initiator.bonds[target.id] = 0
        initiator.bonds[target.id] = max(0, min(100, initiator.bonds[target.id] + avg_bond_change))

    if hasattr(target, "bonds"):
        if initiator.id not in target.bonds:
            target.bonds[initiator.id] = 0
        target.bonds[initiator.id] = max(0, min(100, target.bonds[initiator.id] + avg_bond_change))

    # Opinion changes (random within range)
    opinion_range = outcomes.get("opinion_change", [0, 0])
    if opinion_range and len(opinion_range) == 2:
        opinion_delta = random.uniform(opinion_range[0], opinion_range[1])

        if hasattr(initiator, "opinions"):
            if target.id not in initiator.opinions:
                initiator.opinions[target.id] = 0
            initiator.opinions[target.id] = max(-100, min(100, initiator.opinions[target.id] + opinion_delta))

        if hasattr(target, "opinions"):
            if initiator.id not in target.opinions:
                target.opinions[initiator.id] = 0
            target.opinions[initiator.id] = max(-100, min(100, target.opinions[initiator.id] + opinion_delta))

    # Memory event
    memory_event = interaction.get("memory_event")
    if memory_event:
        i_name = getattr(initiator, "name", f"Praxan {initiator.id}")
        t_name = getattr(target, "name", f"Praxan {target.id}")
        if hasattr(initiator, "episodic_memory"):
            initiator.episodic_memory.record(
                memory_event,
                f"{i_name} had a {label.lower()} with {t_name}",
                related_ids=[target.id],
                metadata={"interaction": iid},
            )
        if hasattr(target, "episodic_memory"):
            target.episodic_memory.record(
                memory_event,
                f"{t_name} had a {label.lower()} with {i_name}",
                related_ids=[initiator.id],
                metadata={"interaction": iid},
            )

    # EventBus publish (if drama_weight > 2 or narrative_chance fires)
    drama_weight = interaction.get("drama_weight", 1)
    narrative_chance = interaction.get("narrative_chance", 0.0)
    should_narrate = drama_weight > 2 or (narrative_chance > 0 and random.random() < narrative_chance)

    if event_bus and should_narrate:
        try:
            from events.bus import GameEvent, CATEGORY_PERSONAL
            i_name = getattr(initiator, "name", f"Praxan {initiator.id}")
            t_name = getattr(target, "name", f"Praxan {target.id}")
            event_bus.publish(GameEvent(
                category=CATEGORY_PERSONAL,
                description=f"{i_name} and {t_name}: {label}",
                data={"interaction": iid, "initiator": initiator.id, "target": target.id},
                drama_weight=drama_weight,
            ))
        except Exception:
            pass

    # Queue personality shifts from this interaction
    try:
        from systems.personality_evolution import queue_interaction_shifts
        queue_interaction_shifts(initiator, target, iid)
    except Exception:
        pass

    return {
        "interaction": iid,
        "label": label,
        "initiator_id": initiator.id,
        "target_id": target.id,
        "opinion_delta": opinion_delta if opinion_range and len(opinion_range) == 2 else 0,
        "bond_change": avg_bond_change,
        "narrated": should_narrate,
    }


# ---------------------------------------------------------------------------
# High-level API used by Praxan.decide_action
# ---------------------------------------------------------------------------

def attempt_interaction(
    initiator: Any,
    target: Any,
    cooldowns: Optional[dict[str, float]] = None,
    event_bus: Any = None,
) -> Optional[dict[str, Any]]:
    """Select and execute an interaction if one is valid.

    Updates *cooldowns* in-place with the current timestamp for the chosen
    interaction's id.

    Returns the execution summary dict, or None if no valid interaction.
    """
    interaction = select_interaction(initiator, target, cooldowns)
    if interaction is None:
        return None

    result = execute_interaction(initiator, target, interaction, event_bus)

    # Record cooldown
    if cooldowns is not None:
        cooldowns[interaction["id"]] = time.time()

    return result
