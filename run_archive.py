from __future__ import annotations

import json
import os
from typing import Any

from observer_analytics import build_observer_report
from society_content import END_STATE_DEFINITIONS, RUN_PHASE_DEFINITIONS


ARCHIVE_VERSION = 1


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


def build_run_summary(
    thronglets,
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
) -> dict[str, Any]:
    settlement_state = dict(settlement_state or getattr(advisor, "current_settlement_state", {}) or {})
    observer_report = build_observer_report(thronglets, advisor, faction_manager)
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
        "council": {
            "doctrine": doctrine,
            "strategic_priorities": list((getattr(advisor, "council_state", {}) or {}).get("strategic_priorities", [])),
            "event_framing": str((getattr(advisor, "council_state", {}) or {}).get("event_framing", "")),
        },
    }


def build_run_archive(
    thronglets,
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
) -> dict[str, Any]:
    archive = build_run_summary(
        thronglets=thronglets,
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
    )
    archive["finalized_at"] = round(current_time, 3)
    archive["extinction"] = bool(extinction)
    archive["lineage_history"] = list((getattr(advisor, "session_stats", {}) or {}).get("lineage_events", []))[-16:]
    archive["faction_history"] = list((getattr(advisor, "session_stats", {}) or {}).get("faction_history", []))[-16:]
    archive["timeline"] = list(archive["observer_report"].get("timeline", []))
    return archive


def write_run_archive(log_dir: str, session_id: str, archive: dict[str, Any]) -> str:
    os.makedirs(log_dir, exist_ok=True)
    archive_path = os.path.join(log_dir, f"archive_{session_id}.json")
    with open(archive_path, "w", encoding="utf-8") as archive_file:
        json.dump(archive, archive_file, indent=2)
    return archive_path


def load_run_archive(archive_path: str) -> dict[str, Any]:
    with open(archive_path, "r", encoding="utf-8") as archive_file:
        return json.load(archive_file)


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
        archive = load_run_archive(archive_path)
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
