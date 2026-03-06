"""Compact state view builders that format game state for LLM prompts.

Each builder takes plain dicts/lists (never game objects directly) and returns
a formatted string ready to embed in a prompt template.  This keeps the prompt
assembly completely independent of pygame and the game class hierarchy.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Council view (doctrine, macro decisions)
# ---------------------------------------------------------------------------

def build_council_view(
    *,
    population: int,
    buildings: dict[str, int],
    resources_on_map: dict[str, int],
    resources_carried: dict[str, int],
    avg_needs: dict[str, float],
    diseased_count: int,
    settlement: dict[str, Any],
    faction_summaries: list[dict[str, Any]],
    thronglet_snapshot: list[dict[str, Any]],
    crisis_flags: list[str],
    summary_text: str,
    intervention_reason: str,
    current_focus: str,
    memory_civ_digest: str,
    memory_faction_digest: str,
    building_prompt_lines: list[str],
) -> str:
    bldg = ", ".join(f"{k}:{v}" for k, v in buildings.items())
    res_map = ", ".join(f"{k}={v}" for k, v in resources_on_map.items())
    res_carry = ", ".join(f"{k}={v}" for k, v in resources_carried.items())
    needs = ", ".join(f"{k}={v:.0f}" for k, v in avg_needs.items())

    thronglet_lines = "\n".join(
        f"- {t.get('id', '?')}: role={t.get('role', 'unassigned')}, hunger={t.get('hunger', 0):.0f}, "
        f"energy={t.get('energy', 0):.0f}, health={t.get('health', 0):.0f}, morale={t.get('morale', 65):.0f}"
        for t in thronglet_snapshot[:8]
    ) or "- none"

    faction_lines = "\n".join(
        f"- F{f.get('id', '?')}: doctrine={f.get('doctrine', '?')}, cohesion={f.get('cohesion', 0):.0f}, "
        f"members={f.get('member_count', 0)}, rivals={f.get('rivals', [])}"
        for f in faction_summaries[:4]
    ) or "- none"

    return f"""Review trigger: {intervention_reason}
State: {summary_text}
Crisis: {', '.join(crisis_flags) or 'none'}
Focus: {current_focus}

Colony:
- Population: {population}
- Buildings: {bldg}
- Map resources: {res_map}
- Carrying: {res_carry}
- Avg needs: {needs}
- Diseased: {diseased_count}
- District: {settlement.get('district_identity', 'homestead')}
- Prosperity: {int(settlement.get('prosperity_score', 0) * 100)}%
- Culture: {int(settlement.get('culture_score', 0) * 100)}%

Factions:
{faction_lines}

Thronglets:
{thronglet_lines}

Buildings:
{chr(10).join(building_prompt_lines)}

Civilization memory:
{memory_civ_digest}

Faction memory:
{memory_faction_digest}"""


# ---------------------------------------------------------------------------
# Faction leader view (per-faction intent)
# ---------------------------------------------------------------------------

def build_faction_view(
    *,
    faction_id: int,
    faction_name: str,
    doctrine: str,
    cohesion: float,
    member_count: int,
    rival_ids: list[int],
    leader_id: int | None,
    schism_pressure: float,
    migration_pressure: float,
    preferred_biome: str,
    recent_events: str,
    faction_digest: str,
    colony_population: int,
    colony_prosperity: float,
) -> str:
    return f"""Faction {faction_id} ({faction_name}):
- Doctrine: {doctrine}
- Cohesion: {cohesion:.0f}
- Members: {member_count}
- Leader: {leader_id if leader_id is not None else 'none'}
- Rivals: {rival_ids or 'none'}
- Schism pressure: {schism_pressure:.0f}
- Migration pressure: {migration_pressure:.0f}
- Preferred biome: {preferred_biome}

Colony context:
- Total population: {colony_population}
- Prosperity: {int(colony_prosperity * 100)}%

Recent faction events:
{recent_events}

Faction memory:
{faction_digest}"""


# ---------------------------------------------------------------------------
# Historian view (narrative framing)
# ---------------------------------------------------------------------------

def build_historian_view(
    *,
    recent_events: list[dict[str, Any]],
    population: int,
    settlement_summary: str,
    faction_count: int,
    memory_civ_digest: str,
    trigger_event: str,
) -> str:
    event_lines = "\n".join(
        f"- [{e.get('category', 'sim')}] {e.get('summary', '')}"
        for e in recent_events[-8:]
    ) or "- (no recent events)"

    return f"""Trigger: {trigger_event}
Population: {population}
Settlement: {settlement_summary}
Active factions: {faction_count}

Recent events:
{event_lines}

Civilization memory digest:
{memory_civ_digest}"""


# ---------------------------------------------------------------------------
# Memory summarizer view
# ---------------------------------------------------------------------------

def build_memory_view(
    *,
    civ_recent: str,
    faction_recent: dict[int, str],
    map_recent: str,
    current_civ_digest: str,
    current_map_digest: str,
) -> str:
    faction_text = "\n".join(
        f"  Faction {fid}:\n  {text}"
        for fid, text in faction_recent.items()
    ) or "  (no faction events)"

    return f"""Summarise the following recent events into concise memory digests.

Civilization events (recent):
{civ_recent}

Faction events (recent):
{faction_text}

Map events (recent):
{map_recent}

Previous civilization digest:
{current_civ_digest}

Previous map digest:
{current_map_digest}"""
