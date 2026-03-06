"""Deterministic interpreters that convert LLM payloads into game-state mutations.

Every interpreter:
- Receives a validated payload dict (from contracts.py)
- Clamps values, rejects invalid enums
- Never invents mechanics, spawns content, or directly modifies stats
- Returns a result dict summarising what changed
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Council interpreter
# ---------------------------------------------------------------------------

_FOCUS_TO_GAME_FOCUS = {
    "survival": "population",
    "growth": "population",
    "industry": "infrastructure",
    "territory": "territory",
    "culture": "population",
    "health": "resources",
    "stability": "resources",
}


def apply_council_payload(
    payload: dict[str, Any],
    advisor_state: dict[str, Any],
    faction_manager_proxy: Any | None = None,
) -> dict[str, Any]:
    """Apply a council payload to the advisor state.

    *advisor_state* is a mutable dict (or advisor-like object) with keys:
        council_state, current_focus, json_directives, directives,
        advisory_history, session_stats
    *faction_manager_proxy* must expose .factions (dict) and .get_faction(id).
    """
    doctrine = dict(payload.get("doctrine") or {})
    advisor_state["council_state"] = payload
    advisor_state["current_focus"] = _FOCUS_TO_GAME_FOCUS.get(
        doctrine.get("focus"), advisor_state.get("current_focus", "resources")
    )
    advisor_state["json_directives"] = {
        "individual": dict(payload.get("individual") or {}),
        "communal": str(payload.get("communal") or ""),
        "conditions": dict(payload.get("conditions") or {}),
    }
    if payload.get("team_task"):
        advisor_state["json_directives"]["team_task"] = dict(payload["team_task"])

    # Convert strategic priorities to legacy-style directives
    directives = []
    for p in (payload.get("strategic_priorities") or [])[:3]:
        if not isinstance(p, dict):
            continue
        weight = max(0.0, min(1.0, float(p.get("weight", 0.5))))
        directives.append({
            "priority": max(1, min(10, int(round(weight * 10)))),
            "action": str(p.get("key", "monitor")),
            "reasoning": str(p.get("reasoning", "Council priority")),
        })
    advisor_state["directives"] = directives

    # Apply faction goals
    if faction_manager_proxy is not None:
        for faction in faction_manager_proxy.factions.values():
            faction.shared_goals = []
        for goal in (payload.get("faction_goals") or []):
            faction = faction_manager_proxy.get_faction(goal.get("faction_id"))
            if faction is None:
                continue
            dk = goal.get("doctrine_key") or getattr(faction, "primary_doctrine", "")
            faction.assign_shared_goal(
                goal.get("goal", ""),
                goal.get("reasoning", ""),
                dk,
            )

    # Record in advisory history
    import time
    history = advisor_state.setdefault("advisory_history", [])
    history.append({
        "time": time.time(),
        "doctrine": doctrine,
        "strategic_priorities": list(payload.get("strategic_priorities") or []),
        "event_framing": str(payload.get("event_framing") or ""),
    })
    if len(history) > 10:
        del history[:-10]

    advisor_state.setdefault("session_stats", {})["current_doctrine"] = doctrine
    advisor_state.setdefault("session_stats", {})["current_advisory_priorities"] = list(
        payload.get("strategic_priorities") or []
    )

    # Store building priority for CityPlanner to consume
    building_priority = list(payload.get("building_priority") or [])
    advisor_state.setdefault("session_stats", {})["building_priority"] = building_priority
    advisor_state["json_directives"]["building_priority"] = building_priority

    intervened = bool(
        advisor_state["json_directives"].get("individual")
        or advisor_state["json_directives"].get("communal")
        or advisor_state["json_directives"].get("conditions")
        or advisor_state["json_directives"].get("team_task")
        or payload.get("faction_goals")
        or directives
        or building_priority
    )
    return {"intervened": intervened}


# ---------------------------------------------------------------------------
# Faction intent interpreter
# ---------------------------------------------------------------------------

def apply_faction_intent(
    payload: dict[str, Any],
    faction: Any,
    faction_manager: Any | None = None,
) -> dict[str, Any]:
    """Apply faction intent payload to a faction object.

    Updates:
    - faction.shared_goals (from goal field)
    - faction.rivalry -> additive signals (does not replace, just records)
    - Returns migration bias info for the planner to use
    """
    intent = payload.get("intent", "consolidate")
    migration_posture = payload.get("migration_posture", "stay")
    goal = payload.get("goal", "")
    reasoning = payload.get("reasoning", "")

    # Set shared goal if provided
    if goal:
        faction.assign_shared_goal(goal, reasoning, getattr(faction, "primary_doctrine", ""))

    # Update rivalry targets on the faction manager
    rivalry_targets = payload.get("rivalry_targets") or []
    cooperation_targets = payload.get("cooperation_targets") or []

    if faction_manager is not None and hasattr(faction_manager, "_update_rivalries"):
        for rival_id in rivalry_targets[:4]:
            if isinstance(rival_id, int):
                if not hasattr(faction, "rival_faction_ids"):
                    faction.rival_faction_ids = set()
                faction.rival_faction_ids.add(rival_id)

    return {
        "faction_id": payload.get("faction_id", getattr(faction, "id", -1)),
        "intent": intent,
        "migration_posture": migration_posture,
        "rivalry_targets": rivalry_targets,
        "cooperation_targets": cooperation_targets,
        "applied_goal": bool(goal),
    }


# ---------------------------------------------------------------------------
# Diplomacy interpreter
# ---------------------------------------------------------------------------

def apply_diplomacy(
    payload: dict[str, Any],
    faction_manager: Any | None = None,
) -> dict[str, Any]:
    """Apply diplomacy stance changes and frontier policy.

    Stance changes update rivalry scores on factions.
    Does NOT create new factions or modify faction membership.
    """
    applied_changes = 0
    stance_changes = payload.get("stance_changes") or []

    if faction_manager is not None:
        for sc in stance_changes[:6]:
            fa = sc.get("faction_a")
            fb = sc.get("faction_b")
            delta = sc.get("delta", 0)
            if fa is None or fb is None:
                continue

            faction_a = faction_manager.get_faction(fa)
            faction_b = faction_manager.get_faction(fb)
            if faction_a is None or faction_b is None:
                continue

            # Positive delta = more cooperative, negative = more hostile
            if delta < -0.3:
                if not hasattr(faction_a, "rival_faction_ids"):
                    faction_a.rival_faction_ids = set()
                faction_a.rival_faction_ids.add(fb)
                if not hasattr(faction_b, "rival_faction_ids"):
                    faction_b.rival_faction_ids = set()
                faction_b.rival_faction_ids.add(fa)
                applied_changes += 1
            elif delta > 0.3:
                # Remove from rivals if cooperating
                if hasattr(faction_a, "rival_faction_ids"):
                    faction_a.rival_faction_ids.discard(fb)
                if hasattr(faction_b, "rival_faction_ids"):
                    faction_b.rival_faction_ids.discard(fa)
                applied_changes += 1

    frontier = payload.get("frontier_policy") or {}
    return {
        "applied_stance_changes": applied_changes,
        "frontier_policy": frontier,
    }


# ---------------------------------------------------------------------------
# Historian interpreter
# ---------------------------------------------------------------------------

def apply_historian(
    payload: dict[str, Any],
    narrative_panel: Any | None = None,
    memory: Any | None = None,
) -> dict[str, Any]:
    """Apply historian payload to narrative and memory.

    Adds framing to the narrative panel and records archive notes in memory.
    """
    summary = payload.get("summary", "")
    archive_note = payload.get("archive_note", "")
    moment_type = payload.get("moment_type", "other")

    if summary and narrative_panel is not None:
        if hasattr(narrative_panel, "add_message"):
            narrative_panel.add_message(summary, "Chronicle")

    if memory is not None and hasattr(memory, "civilization"):
        import time
        if summary:
            memory.civilization.record("historian", summary, time.time())
        if archive_note:
            memory.civilization.record("archive", archive_note, time.time())

    return {
        "summary_added": bool(summary),
        "moment_type": moment_type,
    }


# ---------------------------------------------------------------------------
# Memory summary interpreter
# ---------------------------------------------------------------------------

def apply_memory_summary(
    payload: dict[str, Any],
    memory: Any,
) -> dict[str, Any]:
    """Apply compressed memory digests from the summarizer channel."""
    civ_digest = payload.get("civilization_digest", "")
    if civ_digest and hasattr(memory, "civilization"):
        memory.civilization.set_digest(civ_digest)

    faction_digests = payload.get("faction_digests") or []
    if hasattr(memory, "factions"):
        for i, digest in enumerate(faction_digests):
            if digest:
                memory.factions.set_digest(i, digest)

    map_digest = payload.get("map_digest", "")
    if map_digest and hasattr(memory, "map"):
        memory.map.set_digest(map_digest)

    return {
        "civ_updated": bool(civ_digest),
        "faction_count": len(faction_digests),
        "map_updated": bool(map_digest),
    }
