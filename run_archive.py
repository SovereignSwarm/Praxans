from __future__ import annotations

import json
import os
from typing import Any

from observer_analytics import build_observer_report
from society_content import END_STATE_DEFINITIONS, RUN_PHASE_DEFINITIONS


ARCHIVE_VERSION = 3


def _phase_label(phase_id: str) -> str:
    return RUN_PHASE_DEFINITIONS.get(phase_id, RUN_PHASE_DEFINITIONS["founding"])["label"]


def _end_state_payload(end_state_id: str) -> dict[str, str]:
    definition = END_STATE_DEFINITIONS.get(end_state_id, END_STATE_DEFINITIONS["brittle_survival"])
    return {"id": end_state_id, "label": definition["label"], "summary": definition["summary"]}


def classify_run_phase(elapsed_seconds: float, population: int, building_count: int, faction_count: int, crisis_count: int) -> str:
    if crisis_count > 0 or (elapsed_seconds > 240 and (population <= 3 or faction_count >= 2)):
        return "crisis_endgame"
    if faction_count > 0 or population >= 8 or elapsed_seconds > 180:
        return "societal_divergence"
    if building_count >= 3 or population >= 4 or elapsed_seconds > 60:
        return "expansion"
    return "founding"


def classify_end_state(
    population: int,
    settlement_state: dict[str, Any],
    observer_report: dict[str, Any],
    current_phase: str,
    extinction: bool = False,
) -> str:
    deaths_by_cause = {
        item.get("cause_id", ""): int(item.get("count", 0))
        for item in observer_report.get("mortality", [])
        if isinstance(item, dict)
    }
    total_deaths = max(0, int(observer_report.get("deaths_total", 0)))
    plague_share = deaths_by_cause.get("health_failure", 0) / max(1, total_deaths)
    prosperity = float(settlement_state.get("prosperity_score", 0.0) or 0.0)
    culture = float(settlement_state.get("culture_score", 0.0) or 0.0)
    births_total = int(observer_report.get("births_total", 0))
    peak_factions = int(observer_report.get("peak_factions", 0))
    faction_loss = int(observer_report.get("factions_dissolved", 0))

    if extinction:
        if plague_share >= 0.45:
            return "plague_collapse"
        if peak_factions >= 2 and faction_loss > 0:
            return "ideological_fracture"
        if prosperity < 0.35:
            return "ecological_collapse"
        return "lineage_extinction"

    if population >= 10 and prosperity >= 0.7 and culture >= 0.5 and total_deaths <= max(2, births_total):
        return "thriving_civilization"
    if peak_factions >= 2 and faction_loss > 0 and current_phase == "crisis_endgame":
        return "ideological_fracture"
    if plague_share >= 0.4 and total_deaths >= 3:
        return "plague_collapse"
    if prosperity < 0.4 and current_phase == "crisis_endgame":
        return "ecological_collapse"
    return "brittle_survival"


def calculate_run_score(observer_report: dict[str, Any], settlement_state: dict[str, Any], end_state_id: str) -> int:
    prosperity = float(settlement_state.get("prosperity_score", 0.0) or 0.0)
    culture = float(settlement_state.get("culture_score", 0.0) or 0.0)
    population = int(observer_report.get("population", 0))
    max_population = int(observer_report.get("max_population", population))
    births_total = int(observer_report.get("births_total", 0))
    deaths_total = int(observer_report.get("deaths_total", 0))
    peak_factions = int(observer_report.get("peak_factions", 0))
    top_lineage_size = int(observer_report.get("top_lineages", [{}])[0].get("count", 0)) if observer_report.get("top_lineages") else 0

    score = 0.0
    score += min(25.0, max_population * 1.8)
    score += min(18.0, births_total * 1.2)
    score += prosperity * 24.0
    score += culture * 16.0
    score += min(8.0, peak_factions * 2.5)
    score += min(9.0, top_lineage_size * 1.1)
    score -= min(18.0, deaths_total * 1.8)

    if end_state_id == "thriving_civilization":
        score += 12.0
    elif end_state_id == "brittle_survival":
        score += 4.0
    else:
        score -= 6.0

    return max(0, min(100, int(round(score))))


def _key_moments(observer_report: dict[str, Any], session_stats: dict[str, Any]) -> list[dict[str, Any]]:
    timeline = list(observer_report.get("timeline", []))
    if not timeline:
        timeline = list(session_stats.get("timeline_events", []))
    important = [event for event in timeline if str(event.get("category", "")) in {"scenario", "birth", "faction", "migration", "crisis", "extinction", "resume"}]
    if len(important) < 8:
        important = timeline[-8:]
    return [dict(event) for event in important[-10:]]


def _phase_history(phase_id: str, elapsed_seconds: float) -> list[dict[str, Any]]:
    ordered_phases = ["founding", "expansion", "societal_divergence", "crisis_endgame"]
    current_index = ordered_phases.index(phase_id) if phase_id in ordered_phases else 0
    completed = []
    for index, candidate in enumerate(ordered_phases[: current_index + 1]):
        completed.append(
            {
                "id": candidate,
                "label": _phase_label(candidate),
                "elapsed_seconds": round(max(0.0, elapsed_seconds * ((index + 1) / max(1, current_index + 1))), 3),
            }
        )
    return completed


def _population_curve(session_stats: dict[str, Any], observer_report: dict[str, Any]) -> list[dict[str, Any]]:
    curve = []
    for sample in list(session_stats.get("generation_history", []))[-12:]:
        curve.append(
            {
                "elapsed_seconds": round(float(sample.get("elapsed_seconds", 0.0) or 0.0), 3),
                "population": int(sample.get("population", 0) or 0),
                "avg_generation": round(float(sample.get("avg_generation", 0.0) or 0.0), 3),
            }
        )
    if curve:
        return curve
    return [
        {
            "elapsed_seconds": 0.0,
            "population": int(observer_report.get("population", 0) or 0),
            "avg_generation": 0.0,
        }
    ]


def _death_cause_breakdown(observer_report: dict[str, Any]) -> list[dict[str, Any]]:
    breakdown = []
    for cause in observer_report.get("mortality", []):
        if not isinstance(cause, dict):
            continue
        breakdown.append(
            {
                "cause_id": str(cause.get("cause_id", "unknown")),
                "label": str(cause.get("label", "Unknown")),
                "count": int(cause.get("count", 0) or 0),
                "share": round(float(cause.get("share", 0.0) or 0.0), 3),
            }
        )
    return breakdown


def _lineage_highlights(observer_report: dict[str, Any], session_stats: dict[str, Any]) -> list[dict[str, Any]]:
    highlights = []
    for lineage in observer_report.get("top_lineages", [])[:4]:
        highlights.append(
            {
                "lineage_id": int(lineage.get("lineage_id", 0) or 0),
                "count": int(lineage.get("count", 0) or 0),
                "share": round(float(lineage.get("share", 0.0) or 0.0), 3),
            }
        )
    for event in list(session_stats.get("lineage_events", []))[-4:]:
        highlights.append(
            {
                "event": str(event.get("summary") or event.get("label") or "lineage_event"),
                "time": round(float(event.get("time", 0.0) or 0.0), 3),
            }
        )
    return highlights


def _faction_highlights(observer_report: dict[str, Any], session_stats: dict[str, Any]) -> list[dict[str, Any]]:
    highlights = []
    for faction in observer_report.get("active_factions", [])[:4]:
        highlights.append(
            {
                "id": int(faction.get("id", 0) or 0),
                "members": int(faction.get("members", 0) or 0),
                "doctrine": str(faction.get("doctrine", "survival")),
                "cohesion": round(float(faction.get("cohesion", 0.0) or 0.0), 3),
            }
        )
    for event in list(session_stats.get("faction_history", []))[-4:]:
        highlights.append(
            {
                "faction_id": int(event.get("faction_id", 0) or 0),
                "action": str(event.get("action", "shift")),
                "members": int(event.get("members", 0) or 0),
                "time": round(float(event.get("time", 0.0) or 0.0), 3),
            }
        )
    return highlights


def _focus_moments(key_moments: list[dict[str, Any]], camera_bookmarks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    focus_moments = []
    for bookmark in list(camera_bookmarks or [])[:4]:
        focus_moments.append(
            {
                "label": str(bookmark.get("label", "Moment")),
                "category": str(bookmark.get("category", "event")),
                "x": round(float(bookmark.get("x", 0.0) or 0.0), 2),
                "y": round(float(bookmark.get("y", 0.0) or 0.0), 2),
                "time": round(float(bookmark.get("time", 0.0) or 0.0), 3),
            }
        )
    for event in key_moments:
        if len(focus_moments) >= 6:
            break
        focus_moments.append(
            {
                "label": str(event.get("summary") or event.get("label") or event.get("category") or "moment"),
                "category": str(event.get("category", "event")),
                "time": round(float(event.get("time", 0.0) or 0.0), 3),
            }
        )
    return focus_moments


def _scene_thumbnail_key(session_id: str | None, phase_id: str, end_state_id: str) -> str | None:
    if not session_id:
        return None
    return f"thumb_{session_id}_{phase_id}_{end_state_id}.png"


def build_run_summary(
    praxans,
    buildings,
    advisor,
    current_time: float,
    game_start_time: float,
    settlement_state: dict[str, Any] | None = None,
    faction_manager=None,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
    selected_model: str | None = None,
    seed: int | None = None,
    session_id: str | None = None,
    extinction: bool = False,
    camera_bookmarks: list[dict[str, Any]] | None = None,
    scene_thumbnail_key: str | None = None,
) -> dict[str, Any]:
    settlement_state = dict(settlement_state or getattr(advisor, "current_settlement_state", {}) or {})
    session_stats = dict(getattr(advisor, "session_stats", {}) or {})
    observer_report = build_observer_report(praxans, advisor, faction_manager)
    elapsed_seconds = max(0.0, current_time - game_start_time)
    phase_id = classify_run_phase(
        elapsed_seconds=elapsed_seconds,
        population=observer_report["population"],
        building_count=len(buildings),
        faction_count=len(observer_report.get("active_factions", [])),
        crisis_count=len(getattr(advisor, "active_challenges", []) or []),
    )
    end_state_id = classify_end_state(
        population=observer_report["population"],
        settlement_state=settlement_state,
        observer_report=observer_report,
        current_phase=phase_id,
        extinction=extinction,
    )
    score = calculate_run_score(observer_report, settlement_state, end_state_id)
    doctrine = dict(getattr(advisor, "council_state", {}) or {}).get("doctrine", {})
    dominant_faction = observer_report.get("active_factions", [{}])[0] if observer_report.get("active_factions") else {}
    key_moments = _key_moments(observer_report, session_stats)
    population_curve = _population_curve(session_stats, observer_report)
    focus_moments = _focus_moments(key_moments, camera_bookmarks)

    return {
        "archive_version": ARCHIVE_VERSION,
        "session_id": session_id,
        "seed": seed,
        "selected_model": selected_model,
        "scenario": {"id": scenario_id, "name": scenario_name},
        "elapsed_seconds": round(elapsed_seconds, 3),
        "current_phase": {"id": phase_id, "label": _phase_label(phase_id)},
        "end_state": {**_end_state_payload(end_state_id), "score": score},
        "summary_card": {
            "headline": f"{_phase_label(phase_id)} -> {_end_state_payload(end_state_id)['label']}",
            "score": score,
            "population_peak": observer_report["max_population"],
            "births_total": observer_report["births_total"],
            "deaths_total": observer_report["deaths_total"],
        },
        "settlement": {
            "district_identity": settlement_state.get("district_identity", "homestead"),
            "prosperity_score": round(float(settlement_state.get("prosperity_score", 0.0) or 0.0), 3),
            "culture_score": round(float(settlement_state.get("culture_score", 0.0) or 0.0), 3),
            "festival_readiness": round(float(settlement_state.get("festival_readiness", 0.0) or 0.0), 3),
        },
        "dominant_lineage": observer_report.get("top_lineages", [{}])[0] if observer_report.get("top_lineages") else {},
        "dominant_faction": dominant_faction,
        "observer_report": observer_report,
        "key_moments": key_moments,
        "phase_history": _phase_history(phase_id, elapsed_seconds),
        "population_curve": population_curve,
        "death_cause_breakdown": _death_cause_breakdown(observer_report),
        "lineage_highlights": _lineage_highlights(observer_report, session_stats),
        "faction_highlights": _faction_highlights(observer_report, session_stats),
        "camera_bookmarks": list(camera_bookmarks or []),
        "focus_moments": focus_moments,
        "scene_thumbnail_key": scene_thumbnail_key or _scene_thumbnail_key(session_id, phase_id, end_state_id),
        "council": {
            "doctrine": doctrine,
            "strategic_priorities": list((getattr(advisor, "council_state", {}) or {}).get("strategic_priorities", [])),
            "event_framing": str((getattr(advisor, "council_state", {}) or {}).get("event_framing", "")),
            "doctrine_history": list(getattr(advisor, "advisory_history", []))[-6:],
        },
        "llm_channels": {
            "channel_stats": (
                getattr(advisor, "llm_scheduler", None) and advisor.llm_scheduler.get_stats() or {}
            ),
            "memory_digest": {
                "civilization": (
                    getattr(advisor, "llm_memory", None)
                    and advisor.llm_memory.civilization.digest_text()
                    or ""
                ),
                "map": (
                    getattr(advisor, "llm_memory", None)
                    and advisor.llm_memory.map.digest_text()
                    or ""
                ),
            },
        },
    }


def build_run_archive(
    praxans,
    buildings,
    advisor,
    current_time: float,
    game_start_time: float,
    settlement_state: dict[str, Any] | None = None,
    faction_manager=None,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
    selected_model: str | None = None,
    seed: int | None = None,
    session_id: str | None = None,
    extinction: bool = False,
    camera_bookmarks: list[dict[str, Any]] | None = None,
    scene_thumbnail_key: str | None = None,
) -> dict[str, Any]:
    archive = build_run_summary(
        praxans=praxans,
        buildings=buildings,
        advisor=advisor,
        current_time=current_time,
        game_start_time=game_start_time,
        settlement_state=settlement_state,
        faction_manager=faction_manager,
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        selected_model=selected_model,
        seed=seed,
        session_id=session_id,
        extinction=extinction,
        camera_bookmarks=camera_bookmarks,
        scene_thumbnail_key=scene_thumbnail_key,
    )
    archive["finalized_at"] = round(current_time, 3)
    archive["extinction"] = bool(extinction)
    archive["lineage_history"] = list((getattr(advisor, "session_stats", {}) or {}).get("lineage_events", []))[-16:]
    archive["faction_history"] = list((getattr(advisor, "session_stats", {}) or {}).get("faction_history", []))[-16:]
    archive["timeline"] = list(archive["observer_report"].get("timeline", []))
    # LLM V2: serialize full memory state for archival replay
    archive["llm_memory"] = (
        getattr(advisor, "llm_memory", None) and advisor.llm_memory.serialize() or {}
    )
    # Emergent culture derived from genetic drift
    evo_summary = dict(archive.get("observer_report", {}).get("trait_outliers", [{}])[0] if archive.get("observer_report", {}).get("trait_outliers") else {})
    archive["cultural_profile"] = getattr(advisor, "session_stats", {}).get("cultural_profile", {})
    return archive


def write_run_archive(log_dir: str, session_id: str, archive: dict[str, Any]) -> str:
    os.makedirs(log_dir, exist_ok=True)
    archive_path = os.path.join(log_dir, f"archive_{session_id}.json")
    with open(archive_path, "w", encoding="utf-8") as archive_file:
        json.dump(archive, archive_file, indent=2)
    return archive_path


def load_run_archive(archive_path: str) -> dict[str, Any]:
    with open(archive_path, "r", encoding="utf-8") as archive_file:
        archive = json.load(archive_file)
    if not isinstance(archive, dict):
        raise ValueError(f"Archive file is not a JSON object: {archive_path}")
    return archive


def find_recent_archives(log_dir: str, limit: int = 3) -> list[str]:
    if not os.path.isdir(log_dir):
        return []
    archive_paths = [
        os.path.join(log_dir, entry)
        for entry in os.listdir(log_dir)
        if entry.startswith("archive_") and entry.endswith(".json")
    ]
    archive_paths.sort(key=lambda path: (os.path.getmtime(path), os.path.basename(path)), reverse=True)
    return archive_paths[: max(1, limit)]


def build_archive_comparison(current_summary: dict[str, Any], archive_paths: list[str]) -> list[dict[str, Any]]:
    comparisons = []
    for archive_path in archive_paths:
        try:
            archive = load_run_archive(archive_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        summary_card = dict(archive.get("summary_card", {}))
        comparisons.append(
            {
                "session_id": archive.get("session_id"),
                "scenario_name": archive.get("scenario", {}).get("name", "Unknown"),
                "phase_label": archive.get("current_phase", {}).get("label", "Unknown"),
                "end_state_label": archive.get("end_state", {}).get("label", "Unknown"),
                "score": int(summary_card.get("score", archive.get("end_state", {}).get("score", 0)) or 0),
                "population_peak": int(summary_card.get("population_peak", 0) or 0),
            }
        )

    current_score = int(current_summary.get("end_state", {}).get("score", 0) or 0)
    for comparison in comparisons:
        comparison["score_delta"] = current_score - comparison["score"]
    return comparisons
