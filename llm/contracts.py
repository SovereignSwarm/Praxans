"""Payload schemas, parsing, and validation for all five LLM channels.

Every channel has:
  - A *_payload_defaults() function that returns a safe fallback dict.
  - A parse_*_payload(response_text) that returns a validated dict, or
    None when the model explicitly says "No changes".
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NO_CHANGE_PHRASES = frozenset({
    "no changes",
    "no intervention",
    "monitoring",
    "civilization progressing well. monitoring.",
})

CONTRACT_VERSION = 2  # bump when schema changes


def _clean_response_text(response_text: str | None) -> str:
    cleaned = (response_text or "").strip()
    cleaned = re.sub(
        r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE
    ).strip()
    if re.search(r"</think>", cleaned, flags=re.IGNORECASE):
        cleaned = re.split(r"</think>", cleaned, maxsplit=1, flags=re.IGNORECASE)[-1]
    cleaned = cleaned.strip()
    cleaned = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip("`").strip()
    return cleaned


def _extract_json_object(text: str) -> str | None:
    fenced = re.search(
        r"```json\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE
    )
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    return text[start : end + 1]


def _try_parse_json(text: str) -> dict | None:
    blob = _extract_json_object(text)
    if not blob:
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def _clamp_float(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _safe_str(value: Any, max_len: int = 220) -> str:
    return str(value or "").strip()[:max_len]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validate_enum(value: Any, allowed: set[str], default: str) -> str:
    s = str(value or "").strip().lower()
    return s if s in allowed else default


def _is_no_change(text: str) -> bool:
    return text.lower() in _NO_CHANGE_PHRASES


# =====================================================================
# 1. Council Payload
# =====================================================================

_VALID_DOCTRINE_FOCUS = {
    "survival", "growth", "industry", "territory", "culture", "health", "stability",
}
_VALID_STANCES = {"measured", "urgent", "expansive", "defensive", "restorative"}
_VALID_DISTRICTS = {
    "homestead", "agrarian", "industrial", "frontier", "civic", "sanctuary",
}
_VALID_CRISIS_POSTURES = {"stabilize", "expand", "recover", "fortify", "consolidate"}


_VALID_BUILDING_TYPES = {
    "house", "farm", "workshop", "storage", "hospital", "school", "shrine",
    "watchtower", "well", "market",
}


def council_payload_defaults() -> dict[str, Any]:
    return {
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
        "building_priority": [],
        "event_framing": "",
    }


def _normalize_doctrine(raw: Any) -> dict[str, str]:
    d = dict(raw) if isinstance(raw, dict) else {}
    return {
        "focus": _validate_enum(d.get("focus"), _VALID_DOCTRINE_FOCUS, "survival"),
        "stance": _validate_enum(d.get("stance"), _VALID_STANCES, "measured"),
        "district_priority": _validate_enum(
            d.get("district_priority"), _VALID_DISTRICTS, "homestead"
        ),
        "crisis_posture": _validate_enum(
            d.get("crisis_posture"), _VALID_CRISIS_POSTURES, "stabilize"
        ),
        "reasoning": _safe_str(d.get("reasoning"), 220),
    }


def _normalize_priorities(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:4]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip().lower().replace(" ", "_")
        if not key:
            continue
        out.append({
            "key": key[:40],
            "weight": _clamp_float(item.get("weight", 0.5)),
            "reasoning": _safe_str(item.get("reasoning"), 180),
        })
    return out


def _normalize_individual(raw: Any) -> dict[int, str]:
    norm: dict[int, str] = {}
    if not isinstance(raw, dict):
        return norm
    for tid, instr in list(raw.items())[:2]:
        try:
            norm[int(tid)] = _safe_str(instr, 120)
        except (TypeError, ValueError):
            continue
    return norm


def _normalize_conditions(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        _safe_str(k, 32): _safe_str(v, 140)
        for k, v in list(raw.items())[:4]
    }


def _normalize_team_task(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    try:
        faction_id = int(raw.get("faction_id"))
    except (TypeError, ValueError):
        return {}
    task = _safe_str(raw.get("task"), 120)
    if not task:
        return {}
    count = max(1, min(5, _safe_int(raw.get("count", 3), 3)))
    return {
        "faction_id": faction_id,
        "task": task,
        "count": count,
        "reasoning": _safe_str(raw.get("reasoning"), 180),
    }


def _normalize_faction_goals(raw: Any, valid_doctrines: set[str] | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    valid = valid_doctrines or set()
    goals: list[dict[str, Any]] = []
    for item in raw[:4]:
        if not isinstance(item, dict):
            continue
        try:
            fid = int(item.get("faction_id"))
        except (TypeError, ValueError):
            continue
        dk = str(item.get("doctrine_key", "")).strip().lower()
        if dk and valid and dk not in valid:
            dk = ""
        goals.append({
            "faction_id": fid,
            "goal": _safe_str(item.get("goal"), 120),
            "reasoning": _safe_str(item.get("reasoning"), 180),
            "doctrine_key": dk,
        })
    return goals


def _normalize_building_priority(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [
        bt for bt in (str(b).strip().lower() for b in raw[:3])
        if bt in _VALID_BUILDING_TYPES
    ]


def parse_council_payload(
    response_text: str | None,
    valid_doctrines: set[str] | None = None,
) -> dict[str, Any] | None:
    cleaned = _clean_response_text(response_text)
    if not cleaned:
        return council_payload_defaults()
    if _is_no_change(cleaned):
        return None

    parsed = _try_parse_json(cleaned)
    if parsed is None:
        return council_payload_defaults()

    payload = council_payload_defaults()
    payload["doctrine"] = _normalize_doctrine(parsed.get("doctrine"))
    payload["strategic_priorities"] = _normalize_priorities(parsed.get("strategic_priorities"))
    payload["individual"] = _normalize_individual(parsed.get("individual"))
    payload["communal"] = _safe_str(parsed.get("communal"), 140)
    payload["team_task"] = _normalize_team_task(parsed.get("team_task"))
    payload["conditions"] = _normalize_conditions(parsed.get("conditions"))
    payload["faction_goals"] = _normalize_faction_goals(
        parsed.get("faction_goals"), valid_doctrines
    )
    payload["building_priority"] = _normalize_building_priority(
        parsed.get("building_priority")
    )
    payload["event_framing"] = _safe_str(parsed.get("event_framing"), 220)
    return payload


# =====================================================================
# 2. Faction Intent Payload
# =====================================================================

_VALID_FACTION_INTENTS = {"expand", "consolidate", "migrate", "compete", "cooperate"}
_VALID_MIGRATION_POSTURES = {"stay", "probe", "commit"}


def faction_intent_defaults() -> dict[str, Any]:
    return {
        "faction_id": -1,
        "intent": "consolidate",
        "migration_posture": "stay",
        "rivalry_targets": [],
        "cooperation_targets": [],
        "goal": "",
        "reasoning": "",
    }


def parse_faction_intent_payload(response_text: str | None) -> dict[str, Any] | None:
    cleaned = _clean_response_text(response_text)
    if not cleaned:
        return faction_intent_defaults()
    if _is_no_change(cleaned):
        return None

    parsed = _try_parse_json(cleaned)
    if parsed is None:
        return faction_intent_defaults()

    fid = _safe_int(parsed.get("faction_id"), -1)
    intent = _validate_enum(parsed.get("intent"), _VALID_FACTION_INTENTS, "consolidate")
    migration = _validate_enum(
        parsed.get("migration_posture"), _VALID_MIGRATION_POSTURES, "stay"
    )

    def _int_list(raw: Any, cap: int = 4) -> list[int]:
        if not isinstance(raw, list):
            return []
        out: list[int] = []
        for v in raw[:cap]:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                pass
        return out

    return {
        "faction_id": fid,
        "intent": intent,
        "migration_posture": migration,
        "rivalry_targets": _int_list(parsed.get("rivalry_targets")),
        "cooperation_targets": _int_list(parsed.get("cooperation_targets")),
        "goal": _safe_str(parsed.get("goal"), 120),
        "reasoning": _safe_str(parsed.get("reasoning"), 180),
    }


# =====================================================================
# 3. Diplomacy Payload
# =====================================================================

_VALID_CORRIDOR_PREFS = {"north", "south", "east", "west", "nearest", "safest"}
_VALID_SETTLEMENT_EXPANSION = {"aggressive", "cautious", "hold"}
_VALID_ROUTE_SECURITY = {"patrol", "ignore", "fortify"}


def diplomacy_payload_defaults() -> dict[str, Any]:
    return {
        "stance_changes": [],
        "frontier_policy": {
            "corridor_preference": "nearest",
            "settlement_expansion": "cautious",
            "route_security": "ignore",
        },
    }


def parse_diplomacy_payload(response_text: str | None) -> dict[str, Any] | None:
    cleaned = _clean_response_text(response_text)
    if not cleaned:
        return diplomacy_payload_defaults()
    if _is_no_change(cleaned):
        return None

    parsed = _try_parse_json(cleaned)
    if parsed is None:
        return diplomacy_payload_defaults()

    stance_changes: list[dict[str, Any]] = []
    for sc in (parsed.get("stance_changes") or [])[:6]:
        if not isinstance(sc, dict):
            continue
        try:
            fa = int(sc["faction_a"])
            fb = int(sc["faction_b"])
        except (KeyError, TypeError, ValueError):
            continue
        delta = _clamp_float(sc.get("delta", 0), -1.0, 1.0)
        stance_changes.append({
            "faction_a": fa,
            "faction_b": fb,
            "delta": delta,
            "reason": _safe_str(sc.get("reason"), 120),
        })

    fp_raw = parsed.get("frontier_policy") if isinstance(parsed.get("frontier_policy"), dict) else {}
    frontier_policy = {
        "corridor_preference": _validate_enum(
            fp_raw.get("corridor_preference"), _VALID_CORRIDOR_PREFS, "nearest"
        ),
        "settlement_expansion": _validate_enum(
            fp_raw.get("settlement_expansion"), _VALID_SETTLEMENT_EXPANSION, "cautious"
        ),
        "route_security": _validate_enum(
            fp_raw.get("route_security"), _VALID_ROUTE_SECURITY, "ignore"
        ),
    }

    return {
        "stance_changes": stance_changes,
        "frontier_policy": frontier_policy,
    }


# =====================================================================
# 4. Historian Payload
# =====================================================================

_VALID_MOMENT_TYPES = {
    "birth", "schism", "landmark", "migration", "disaster", "extinction", "other",
}


def historian_payload_defaults() -> dict[str, Any]:
    return {
        "summary": "",
        "moment_type": "other",
        "why": "",
        "archive_note": "",
    }


def parse_historian_payload(response_text: str | None) -> dict[str, Any] | None:
    cleaned = _clean_response_text(response_text)
    if not cleaned:
        return historian_payload_defaults()
    if _is_no_change(cleaned):
        return None

    parsed = _try_parse_json(cleaned)
    if parsed is None:
        return historian_payload_defaults()

    return {
        "summary": _safe_str(parsed.get("summary"), 256),
        "moment_type": _validate_enum(
            parsed.get("moment_type"), _VALID_MOMENT_TYPES, "other"
        ),
        "why": _safe_str(parsed.get("why"), 180),
        "archive_note": _safe_str(parsed.get("archive_note"), 120),
    }


# =====================================================================
# 5. Memory Summary Payload
# =====================================================================


def memory_summary_defaults() -> dict[str, Any]:
    return {
        "civilization_digest": "",
        "faction_digests": [],
        "map_digest": "",
    }


def parse_memory_summary_payload(response_text: str | None) -> dict[str, Any] | None:
    cleaned = _clean_response_text(response_text)
    if not cleaned:
        return memory_summary_defaults()
    if _is_no_change(cleaned):
        return None

    parsed = _try_parse_json(cleaned)
    if parsed is None:
        return memory_summary_defaults()

    faction_digests: list[str] = []
    raw_fd = parsed.get("faction_digests")
    if isinstance(raw_fd, list):
        for fd in raw_fd[:8]:
            faction_digests.append(_safe_str(fd, 200))

    return {
        "civilization_digest": _safe_str(parsed.get("civilization_digest"), 300),
        "faction_digests": faction_digests,
        "map_digest": _safe_str(parsed.get("map_digest"), 200),
    }


# =====================================================================
# Legacy compatibility — aliases for advisor_contract.py shim
# =====================================================================

advisory_payload_defaults = council_payload_defaults
parse_advisory_payload = parse_council_payload
