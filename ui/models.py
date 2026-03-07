from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldNote:
    category: str
    title: str
    body: str
    age_seconds: float
    pinned: bool = False


@dataclass(frozen=True)
class RunHudModel:
    scenario_name: str
    phase_label: str
    doctrine_label: str
    llm_status: str
    speed_label: str
    follow_label: str
    camera_mode_label: str
    crisis_label: str
    overlay_label: str
    observer_score: int
    cue_label: str = ""


@dataclass(frozen=True)
class InspectSection:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NeedBar:
    label: str
    value: float  # 0-100
    max_value: float = 100.0
    color: tuple[int, int, int] = (100, 200, 100)


@dataclass(frozen=True)
class InspectCommand:
    id: str
    label: str
    action: str
    payload: Any = None


@dataclass(frozen=True)
class InspectViewModel:
    title: str
    subtitle: str
    entity_type: str
    accent: tuple[int, int, int]
    tabs: list[tuple[str, str]]
    active_tab: str
    sections: list[InspectSection]
    need_bars: list[NeedBar] = field(default_factory=list)
    commands: list[InspectCommand] = field(default_factory=list)


@dataclass(frozen=True)
class ArchiveCard:
    session_id: str
    scenario_name: str
    end_state_label: str
    score: int
    population_peak: int
    duration_seconds: float
    headline: str
    payload: dict[str, Any]


_field_notes_cache_events: list[dict[str, Any]] = []
_field_notes_cache_len: int = -1

def build_field_notes(timeline: list[dict[str, Any]], current_time: float, limit: int = 5) -> list[FieldNote]:
    global _field_notes_cache_events, _field_notes_cache_len
    t_len = len(timeline) if timeline else 0
    
    if t_len != _field_notes_cache_len:
        _field_notes_cache_len = t_len
        seen_keys: set[tuple[str, str]] = set()
        events_to_cache = []
        for event in reversed(list(timeline or [])):
            category = str(event.get("category", "sim"))
            summary = str(event.get("summary", "Event")).strip()
            if not summary:
                continue
            dedupe_key = (category, summary)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            events_to_cache.append(event)
            if len(events_to_cache) >= limit:
                break
        _field_notes_cache_events = list(reversed(events_to_cache))

    notes: list[FieldNote] = []
    for event in _field_notes_cache_events:
        category = str(event.get("category", "sim"))
        summary = str(event.get("summary", "Event")).strip()
        time_val = float(event.get("time", current_time) or current_time)
        notes.append(
            FieldNote(
                category=category,
                title=category.replace("_", " ").title(),
                body=summary,
                age_seconds=max(0.0, current_time - time_val),
                pinned=category in {"crisis", "extinction", "faction", "birth", "migration",
                                     "trade", "diplomacy", "disaster", "cultural_shift",
                                     "doctrine_change", "schism", "building", "milestone", "death"},
            )
        )
    return notes


def build_archive_card(archive: dict[str, Any]) -> ArchiveCard:
    summary_card = dict(archive.get("summary_card", {}) or {})
    return ArchiveCard(
        session_id=str(archive.get("session_id", "unknown")),
        scenario_name=str(archive.get("scenario", {}).get("name", "Unknown")),
        end_state_label=str(archive.get("end_state", {}).get("label", "Unknown")),
        score=int(summary_card.get("score", archive.get("end_state", {}).get("score", 0)) or 0),
        population_peak=int(summary_card.get("population_peak", 0) or 0),
        duration_seconds=float(archive.get("elapsed_seconds", 0.0) or 0.0),
        headline=str(summary_card.get("headline", "Observer run")),
        payload=dict(archive),
    )
