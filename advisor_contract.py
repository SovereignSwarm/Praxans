from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from society_content import FACTION_DOCTRINE_PROFILES


DEFAULT_ADVISORY_PAYLOAD = {
    "doctrine": {
        "focus": "survival",
        "stance": "measured",
        "district_priority": "homestead",
        "crisis_posture": "stabilize",
        "reasoning": "",
    },
    "strategic_priorities": [],
    "individual": {},
    "communal": "",
    "team_task": {},
    "conditions": {},
    "faction_goals": [],
    "event_framing": "",
}

_VALID_DOCTRINE_FOCUS = {
    "survival",
    "growth",
    "industry",
    "territory",
    "culture",
    "health",
    "stability",
}
_VALID_STANCES = {"measured", "urgent", "expansive", "defensive", "restorative"}
_VALID_DISTRICTS = {"homestead", "agrarian", "industrial", "frontier", "civic", "sanctuary"}
_VALID_CRISIS_POSTURES = {"stabilize", "expand", "recover", "fortify", "consolidate"}


def advisory_payload_defaults() -> dict[str, Any]:
    return deepcopy(DEFAULT_ADVISORY_PAYLOAD)


def _clean_response_text(response_text: str | None) -> str:
    cleaned = (response_text or "").strip()
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE).strip()
    return cleaned


def _extract_json_object(response_text: str) -> str | None:
    fenced_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        return fenced_match.group(1)

    brace_start = response_text.find("{")
    brace_end = response_text.rfind("}")
    if brace_start == -1 or brace_end <= brace_start:
        return None
    return response_text[brace_start : brace_end + 1]


def _clamp_priority_weight(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.5
    return max(0.0, min(1.0, numeric))


def _normalize_doctrine(raw: Any) -> dict[str, str]:
    doctrine = dict(raw) if isinstance(raw, dict) else {}
    focus = str(doctrine.get("focus", "survival")).strip().lower()
    stance = str(doctrine.get("stance", "measured")).strip().lower()
    district_priority = str(doctrine.get("district_priority", "homestead")).strip().lower()
    crisis_posture = str(doctrine.get("crisis_posture", "stabilize")).strip().lower()
    if focus not in _VALID_DOCTRINE_FOCUS:
        focus = "survival"
    if stance not in _VALID_STANCES:
        stance = "measured"
    if district_priority not in _VALID_DISTRICTS:
        district_priority = "homestead"
    if crisis_posture not in _VALID_CRISIS_POSTURES:
        crisis_posture = "stabilize"
    return {
        "focus": focus,
        "stance": stance,
        "district_priority": district_priority,
        "crisis_posture": crisis_posture,
        "reasoning": str(doctrine.get("reasoning", "")).strip()[:220],
    }


def _normalize_priorities(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    priorities = []
    for item in raw[:4]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip().lower().replace(" ", "_")
        if not key:
            continue
        priorities.append(
            {
                "key": key[:40],
                "weight": _clamp_priority_weight(item.get("weight", 0.5)),
                "reasoning": str(item.get("reasoning", "")).strip()[:180],
            }
        )
    return priorities


def _normalize_individual(raw: Any) -> dict[int, str]:
    normalized: dict[int, str] = {}
    if not isinstance(raw, dict):
        return normalized
    for thronglet_id, instruction in list(raw.items())[:2]:
        try:
            normalized[int(thronglet_id)] = str(instruction).strip()[:120]
        except (TypeError, ValueError):
            continue
    return normalized


def _normalize_conditions(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    normalized = {}
    for condition, behavior in list(raw.items())[:4]:
        normalized[str(condition).strip()[:32]] = str(behavior).strip()[:140]
    return normalized


def _normalize_team_task(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    try:
        faction_id = int(raw.get("faction_id"))
    except (TypeError, ValueError):
        faction_id = None

    task = str(raw.get("task", "")).strip()[:120]
    try:
        count = int(raw.get("count", 3))
    except (TypeError, ValueError):
        count = 3
    count = max(1, min(5, count))
    reasoning = str(raw.get("reasoning", "")).strip()[:180]

    if faction_id is None or not task:
        return {}

    return {
        "faction_id": faction_id,
        "task": task,
        "count": count,
        "reasoning": reasoning,
    }


def _normalize_faction_goals(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    goals = []
    for item in raw[:4]:
        if not isinstance(item, dict):
            continue
        try:
            faction_id = int(item.get("faction_id"))
        except (TypeError, ValueError):
            continue
        doctrine_key = str(item.get("doctrine_key", "")).strip().lower()
        if doctrine_key and doctrine_key not in FACTION_DOCTRINE_PROFILES:
            doctrine_key = ""
        goals.append(
            {
                "faction_id": faction_id,
                "goal": str(item.get("goal", "")).strip()[:120],
                "reasoning": str(item.get("reasoning", "")).strip()[:180],
                "doctrine_key": doctrine_key,
            }
        )
    return goals


def parse_advisory_payload(response_text: str | None) -> dict[str, Any] | None:
    cleaned = _clean_response_text(response_text)
    if not cleaned:
        return advisory_payload_defaults()
    if cleaned.lower() in {"no changes", "no intervention", "monitoring", "civilization progressing well. monitoring."}:
        return None

    json_blob = _extract_json_object(cleaned)
    if not json_blob:
        return advisory_payload_defaults()

    try:
        parsed = json.loads(json_blob)
    except json.JSONDecodeError:
        return advisory_payload_defaults()

    advisory = advisory_payload_defaults()
    advisory["doctrine"] = _normalize_doctrine(parsed.get("doctrine"))
    advisory["strategic_priorities"] = _normalize_priorities(parsed.get("strategic_priorities"))
    advisory["individual"] = _normalize_individual(parsed.get("individual"))
    advisory["communal"] = str(parsed.get("communal", "")).strip()[:140]
    advisory["team_task"] = _normalize_team_task(parsed.get("team_task"))
    advisory["conditions"] = _normalize_conditions(parsed.get("conditions"))
    advisory["faction_goals"] = _normalize_faction_goals(parsed.get("faction_goals"))
    advisory["event_framing"] = str(parsed.get("event_framing", "")).strip()[:220]
    return advisory
