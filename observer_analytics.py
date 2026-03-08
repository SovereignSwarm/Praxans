from __future__ import annotations

from typing import Any


def _try_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rounded_float_attr(entity: Any, attr_name: str, default: float = 0.0) -> float:
    value = _try_float(getattr(entity, attr_name, default))
    return round(value if value is not None else default, 2)

def _count_lineages(praxans) -> dict[int, int]:
    lineage_counts: dict[int, int] = {}
    for praxan in praxans:
        lineage_id = int(getattr(praxan, "lineage_id", getattr(praxan, "id", 0)))
        lineage_counts[lineage_id] = lineage_counts.get(lineage_id, 0) + 1
    return lineage_counts


def _format_cause_label(cause_name: str) -> str:
    return cause_name.replace("_", " ").strip().title() or "Unknown"


def _build_faction_snapshots(praxans, faction_manager) -> list[dict[str, Any]]:
    if faction_manager is None:
        return []

    praxan_lookup = {
        int(getattr(praxan, "id", -1)): praxan
        for praxan in praxans
        if hasattr(praxan, "id")
    }
    faction_snapshots = []
    for faction_id, faction in getattr(faction_manager, "factions", {}).items():
        member_ids = [int(member_id) for member_id in getattr(faction, "member_ids", [])]
        members = [praxan_lookup[member_id] for member_id in member_ids if member_id in praxan_lookup]
        avg_generation = (
            round(sum(getattr(member, "generation", 0) for member in members) / len(members), 2)
            if members
            else 0.0
        )
        faction_snapshots.append(
            {
                "id": int(faction_id),
                "members": len(member_ids),
                "leader_id": getattr(faction, "leader_id", None),
                "shared_goals": len(getattr(faction, "shared_goals", [])),
                "avg_generation": avg_generation,
                "doctrine": getattr(faction, "primary_doctrine", "growth"),
                "cohesion": _rounded_float_attr(faction, "cohesion"),
                "stability": _rounded_float_attr(faction, "stability"),
                "schism_pressure": _rounded_float_attr(faction, "schism_pressure"),
                "migration_pressure": _rounded_float_attr(faction, "migration_pressure"),
                "rival_count": len(getattr(faction, "rival_faction_ids", []) or []),
                "succession_count": int(getattr(faction, "succession_count", 0) or 0),
                "resource_stress": _rounded_float_attr(faction, "resource_stress"),
                "food_security": _rounded_float_attr(faction, "food_security", default=52.0),
                "material_security": _rounded_float_attr(faction, "material_security", default=48.0),
                "ecology_fertility": _rounded_float_attr(faction, "ecology_fertility", default=70.0),
            }
        )

    faction_snapshots.sort(key=lambda faction: (-faction["members"], -faction["avg_generation"], faction["id"]))
    return faction_snapshots


def _build_timeline(session_stats: dict[str, Any], advisor_events) -> list[dict[str, Any]]:
    timeline_events = []
    if session_stats.get("timeline_events"):
        timeline_events.extend(event for event in session_stats.get("timeline_events", []) if isinstance(event, dict))
    else:
        for event in session_stats.get("lineage_events", []):
            if not isinstance(event, dict):
                continue
            timeline_events.append(
                {
                    "time": event.get("time", 0.0),
                    "category": "lineage",
                    "summary": event.get("label", "Lineage event"),
                }
            )
        for event in advisor_events:
            if not isinstance(event, dict):
                continue
            timeline_events.append(
                {
                    "time": event.get("time", 0.0),
                    "category": "simulation",
                    "summary": event.get("description", "Simulation event"),
                }
            )

    normalized_events = []
    for event in timeline_events:
        if not isinstance(event.get("summary"), str):
            continue
        normalized_event = dict(event)
        normalized_time = _try_float(normalized_event.get("time", 0.0))
        normalized_event["time"] = normalized_time if normalized_time is not None else 0.0
        normalized_events.append(normalized_event)

    normalized_events.sort(key=lambda event: event["time"])
    return normalized_events[-8:]


def build_observer_report(praxans, advisor, faction_manager=None) -> dict[str, Any]:
    session_stats = dict(getattr(advisor, "session_stats", {}) or {})
    summary = dict(session_stats.get("current_evolution_summary", {}) or {})
    lineage_counts = dict(summary.get("lineage_counts", {}) or _count_lineages(praxans))
    population = max(0, len(praxans))

    top_lineages = []
    for lineage_id, count in sorted(lineage_counts.items(), key=lambda item: (-item[1], item[0]))[:5]:
        top_lineages.append(
            {
                "lineage_id": int(lineage_id),
                "count": int(count),
                "share": round(int(count) / max(1, population), 3),
            }
        )

    deaths_by_cause = {
        str(cause_name): int(count)
        for cause_name, count in session_stats.get("deaths_by_cause", {}).items()
        if int(count) > 0
    }
    total_deaths = max(int(getattr(advisor, "total_deaths", 0) or 0), sum(deaths_by_cause.values()))
    mortality = []
    for cause_name, count in sorted(deaths_by_cause.items(), key=lambda item: (-item[1], item[0]))[:4]:
        mortality.append(
            {
                "cause_id": cause_name,
                "label": _format_cause_label(cause_name),
                "count": count,
                "share": round(count / max(1, total_deaths), 3),
            }
        )

    avg_traits = dict(summary.get("avg_traits", {}) or {})
    trait_outliers = []
    for trait_name, value in avg_traits.items():
        numeric_value = _try_float(value)
        if numeric_value is None:
            continue
        trait_outliers.append(
            {
                "trait_name": str(trait_name),
                "value": numeric_value,
                "delta_pct": round((numeric_value - 1.0) * 100.0, 1),
            }
        )
    trait_outliers.sort(key=lambda item: (abs(item["delta_pct"]), item["trait_name"]), reverse=True)

    faction_snapshots = _build_faction_snapshots(praxans, faction_manager)

    return {
        "population": population,
        "max_population": int(session_stats.get("max_population", population) or population),
        "births_total": int(session_stats.get("births_total", 0) or 0),
        "deaths_total": total_deaths,
        "avg_survival_time": float(session_stats.get("avg_survival_time", 0.0) or 0.0),
        "peak_factions": int(session_stats.get("peak_factions", len(faction_snapshots)) or len(faction_snapshots)),
        "factions_formed": int(session_stats.get("factions_formed", 0) or 0),
        "factions_dissolved": int(session_stats.get("factions_dissolved", 0) or 0),
        "faction_schisms": int(session_stats.get("faction_schisms", 0) or 0),
        "faction_successions": int(session_stats.get("faction_successions", 0) or 0),
        "migration_events": int(session_stats.get("migration_events", 0) or 0),
        "active_group_tasks": len(getattr(advisor, "group_tasks", []) or []),
        "top_lineages": top_lineages,
        "mortality": mortality,
        "trait_outliers": trait_outliers[:4],
        "timeline": _build_timeline(session_stats, getattr(advisor, "events_history", []) or []),
        "generation_history": list(session_stats.get("evolution_history", []))[-6:],
        "faction_history": list(session_stats.get("faction_history", []))[-6:],
        "active_factions": faction_snapshots,
    }

