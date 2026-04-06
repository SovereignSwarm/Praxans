"""Legends & Chronicle System — persistent historical narrative layer.

Subscribes to *all* EventBus categories and maintains a rolling chronicle of
significant events.  From this chronicle the system derives:

- **Historical Eras** — named periods (Age of War, Golden Age, …) defined by
  the dominant event category over a rolling window.
- **Legendary Deeds** — per-Praxan tallies of extraordinary achievements.
- **Legend Tiers** — Notable → Renowned → Legendary, with moodlets, reputation
  boosts, and episodic memories.

The system is fully data-driven via ``defs/core/chronicle.json`` (EraDef,
LegendaryDeedDef, LegendTierDef) loaded through ``DefDatabase``.

Integration points:
    - ``ChronicleManager.attach_event_bus()`` wires subscriptions to all categories
    - ``update()`` called every frame (self-manages 30s eval interval)
    - Publishes CATEGORY_MILESTONE on era transitions and legend crownings
    - Applies moodlets, reputation events, episodic memory
    - Snapshot: ``serialize()`` / ``restore()``
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from events.bus import (
    ALL_CATEGORIES,
    CATEGORY_BIRTH,
    CATEGORY_BUILDING,
    CATEGORY_CULTURAL_SHIFT,
    CATEGORY_DEATH,
    CATEGORY_DIPLOMACY,
    CATEGORY_DISASTER,
    CATEGORY_MILESTONE,
    CATEGORY_PERSONAL,
    CATEGORY_SCHISM,
    CATEGORY_TRADE,
    CATEGORY_WARFARE,
    CATEGORY_MIGRATION,
    GameEvent,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Def caches (lazily loaded from DefDatabase)
# ---------------------------------------------------------------------------

_era_def_cache: dict[str, dict[str, Any]] = {}
_deed_def_cache: dict[str, dict[str, Any]] = {}
_legend_tier_cache: list[dict[str, Any]] = []


def _load_defs() -> None:
    """Populate caches from DefDatabase."""
    if _era_def_cache:
        return
    try:
        from systems.def_database import DefDatabase

        era_defs = DefDatabase.get_all("EraDef")
        if era_defs:
            for def_id, def_data in era_defs.items():
                _era_def_cache[def_id] = def_data

        deed_defs = DefDatabase.get_all("LegendaryDeedDef")
        if deed_defs:
            for def_id, def_data in deed_defs.items():
                _deed_def_cache[def_id] = def_data

        tier_defs = DefDatabase.get_all("LegendTierDef")
        if tier_defs:
            _legend_tier_cache.extend(
                sorted(
                    tier_defs.values(),
                    key=lambda t: t.get("min_legend_points", 0),
                    reverse=True,
                )
            )
    except Exception:
        pass


def get_era_def(era_id: str) -> Optional[dict[str, Any]]:
    """Return an EraDef by id, or None."""
    _load_defs()
    return _era_def_cache.get(era_id)


def get_all_era_defs() -> dict[str, dict[str, Any]]:
    """Return all EraDefs."""
    _load_defs()
    return dict(_era_def_cache)


def get_all_deed_defs() -> dict[str, dict[str, Any]]:
    """Return all LegendaryDeedDefs."""
    _load_defs()
    return dict(_deed_def_cache)


def get_legend_tier(legend_points: int) -> Optional[dict[str, Any]]:
    """Return the LegendTierDef matching *legend_points*, or None if below all tiers."""
    _load_defs()
    for tier in _legend_tier_cache:
        if legend_points >= tier.get("min_legend_points", 0):
            return tier
    return None


def clear_cache() -> None:
    """Clear cached defs (for testing)."""
    global _era_def_cache, _deed_def_cache, _legend_tier_cache
    _era_def_cache = {}
    _deed_def_cache = {}
    _legend_tier_cache = []


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How often the manager evaluates eras and legendary status (seconds)
_EVAL_INTERVAL = 30.0

# Rolling window for era classification (seconds)
_ERA_WINDOW = 300.0  # 5 minutes

# Maximum chronicle entries kept in memory
_MAX_CHRONICLE_ENTRIES = 200

# Maximum deed events tracked per praxan per deed type
_MAX_DEED_LOG = 30

# Minimum time between era moodlet re-applications (seconds)
_ERA_MOODLET_INTERVAL = 120.0

# Minimum time between legend tier moodlet re-applications (seconds)
_LEGEND_MOODLET_INTERVAL = 300.0


# ---------------------------------------------------------------------------
# ChronicleEntry
# ---------------------------------------------------------------------------

class ChronicleEntry:
    """A single significant event in the colony's history."""

    __slots__ = ("category", "summary", "timestamp", "drama_weight",
                 "faction_id", "praxan_id", "era_id")

    def __init__(
        self,
        category: str,
        summary: str,
        timestamp: float,
        drama_weight: int = 1,
        faction_id: int | None = None,
        praxan_id: int | None = None,
        era_id: str | None = None,
    ):
        self.category = category
        self.summary = summary
        self.timestamp = timestamp
        self.drama_weight = drama_weight
        self.faction_id = faction_id
        self.praxan_id = praxan_id
        self.era_id = era_id

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "category": self.category,
            "summary": self.summary,
            "timestamp": self.timestamp,
            "drama_weight": self.drama_weight,
        }
        if self.faction_id is not None:
            d["faction_id"] = self.faction_id
        if self.praxan_id is not None:
            d["praxan_id"] = self.praxan_id
        if self.era_id is not None:
            d["era_id"] = self.era_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChronicleEntry":
        return cls(
            category=data.get("category", ""),
            summary=data.get("summary", ""),
            timestamp=data.get("timestamp", 0.0),
            drama_weight=data.get("drama_weight", 1),
            faction_id=data.get("faction_id"),
            praxan_id=data.get("praxan_id"),
            era_id=data.get("era_id"),
        )


# ---------------------------------------------------------------------------
# ChronicleManager
# ---------------------------------------------------------------------------

class ChronicleManager:
    """Manages the colony chronicle, historical eras, and legendary Praxans.

    Typical lifecycle::

        mgr = ChronicleManager()
        mgr.attach_event_bus(event_bus)
        # Every frame:
        mgr.update(praxans, faction_manager, reputation_manager, event_bus, current_time)
    """

    def __init__(self) -> None:
        # Rolling chronicle of significant events
        self._entries: list[ChronicleEntry] = []

        # Current era classification
        self._current_era: str = "age_of_founding"
        self._era_start_time: float = 0.0

        # Per-era history: [(era_id, start_time, end_time | None)]
        self._era_history: list[tuple[str, float, float | None]] = []

        # Per-praxan deed tracking: {praxan_id: {deed_id: count}}
        self._deed_counts: dict[int, dict[str, int]] = {}

        # Per-praxan legend points
        self._legend_points: dict[int, int] = {}

        # Per-praxan current legend tier id (for detecting transitions)
        self._legend_tiers: dict[int, str] = {}

        # Completed deed IDs per praxan (to avoid double-counting)
        self._completed_deeds: dict[int, set[str]] = {}

        # Per-praxan event log for deed matching: {praxan_id: [(event_type, timestamp)]}
        self._deed_event_log: dict[int, list[tuple[str, float]]] = {}

        # Timing
        self._last_eval_time: float = 0.0
        self._last_era_moodlet_time: float = 0.0
        self._last_legend_moodlet_time: float = 0.0

        # EventBus reference
        self._event_bus: Any = None

    # ---- EventBus auto-subscription ---------------------------------------

    def attach_event_bus(self, event_bus: Any) -> None:
        """Subscribe to all EventBus categories to build the chronicle."""
        self._event_bus = event_bus
        if event_bus is None:
            return
        # Subscribe to every category
        for category in ALL_CATEGORIES:
            try:
                event_bus.subscribe(category, self._on_event)
            except Exception:
                pass

    def _on_event(self, event: Any) -> None:
        """Record significant events into the chronicle and deed logs."""
        category = getattr(event, "category", "")
        summary = getattr(event, "summary", "")
        drama = getattr(event, "drama", 1)
        timestamp = getattr(event, "timestamp", time.time())
        faction_id = getattr(event, "faction_id", None)
        praxan_id = getattr(event, "praxan_id", None)
        metadata = getattr(event, "metadata", {}) or {}

        # Only chronicle events with drama >= 2 (skip mundane noise)
        if drama < 2:
            return

        entry = ChronicleEntry(
            category=category,
            summary=summary,
            timestamp=timestamp,
            drama_weight=drama,
            faction_id=faction_id,
            praxan_id=praxan_id,
            era_id=self._current_era,
        )
        self._entries.append(entry)
        if len(self._entries) > _MAX_CHRONICLE_ENTRIES:
            del self._entries[: len(self._entries) - _MAX_CHRONICLE_ENTRIES]

        # Track deed-relevant events per praxan
        if praxan_id is not None:
            event_type = metadata.get("type", category)
            log = self._deed_event_log.setdefault(praxan_id, [])
            log.append((event_type, timestamp))
            if len(log) > _MAX_DEED_LOG:
                del log[:-_MAX_DEED_LOG]

    # ---- public queries ---------------------------------------------------

    def get_current_era(self) -> str:
        """Return the current era id."""
        return self._current_era

    def get_current_era_label(self) -> str:
        """Return human-readable label for the current era."""
        edef = get_era_def(self._current_era)
        if edef:
            return edef.get("label", self._current_era)
        return self._current_era.replace("_", " ").title()

    def get_era_history(self) -> list[tuple[str, float, float | None]]:
        """Return the list of past eras: [(era_id, start_time, end_time)]."""
        return list(self._era_history)

    def get_legend_points(self, praxan_id: int) -> int:
        """Return the legend points for a given praxan."""
        return self._legend_points.get(praxan_id, 0)

    def get_legend_tier(self, praxan_id: int) -> Optional[str]:
        """Return the legend tier id for a given praxan, or None."""
        return self._legend_tiers.get(praxan_id)

    def get_legend_tier_label(self, praxan_id: int) -> Optional[str]:
        """Return human-readable legend tier label, or None."""
        pts = self._legend_points.get(praxan_id, 0)
        tier = get_legend_tier(pts)
        if tier:
            return tier.get("label")
        return None

    def get_completed_deeds(self, praxan_id: int) -> list[str]:
        """Return list of completed deed IDs for a praxan."""
        return list(self._completed_deeds.get(praxan_id, set()))

    def get_recent_entries(self, count: int = 10) -> list[ChronicleEntry]:
        """Return the *count* most recent chronicle entries."""
        return list(self._entries[-count:])

    def get_high_drama_entries(self, count: int = 5) -> list[ChronicleEntry]:
        """Return the top *count* entries by drama weight."""
        return sorted(self._entries, key=lambda e: e.drama_weight, reverse=True)[:count]

    def get_all_legends(self) -> dict[int, dict[str, Any]]:
        """Return all praxans with legend points > 0."""
        result = {}
        for pid, pts in self._legend_points.items():
            tier = get_legend_tier(pts)
            if tier:
                result[pid] = {
                    "legend_points": pts,
                    "tier": tier.get("id", "notable"),
                    "tier_label": tier.get("label", "Notable"),
                    "deeds": list(self._completed_deeds.get(pid, set())),
                }
        return result

    # ---- update (called every frame, self-throttled) ----------------------

    def update(
        self,
        praxans: list,
        faction_manager: Any = None,
        reputation_manager: Any = None,
        event_bus: Any = None,
        current_time: float | None = None,
        advisor: Any = None,
    ) -> None:
        """Evaluate eras and legendary status on a 30s cadence."""
        now = current_time if current_time is not None else time.time()

        if now - self._last_eval_time < _EVAL_INTERVAL:
            return
        self._last_eval_time = now

        _load_defs()

        # 1. Evaluate era classification
        self._evaluate_era(now, event_bus, advisor)

        # 2. Apply era moodlets to all praxans
        if now - self._last_era_moodlet_time >= _ERA_MOODLET_INTERVAL:
            self._apply_era_moodlets(praxans, now)
            self._last_era_moodlet_time = now

        # 3. Evaluate legendary deeds for all living praxans
        alive_praxans = [p for p in praxans if getattr(p, "alive", True)]
        self._evaluate_deeds(alive_praxans, now)

        # 4. Evaluate legend tier transitions
        self._evaluate_legend_tiers(
            alive_praxans, reputation_manager, event_bus, now, advisor
        )

        # 5. Apply legend tier moodlets
        if now - self._last_legend_moodlet_time >= _LEGEND_MOODLET_INTERVAL:
            self._apply_legend_moodlets(alive_praxans, now)
            self._last_legend_moodlet_time = now

        # 6. Clean up dead praxans
        alive_ids = {getattr(p, "id", None) for p in alive_praxans}
        dead_ids = [pid for pid in self._legend_points if pid not in alive_ids]
        for pid in dead_ids:
            # Keep legend data for historical record but stop updating
            pass

    # ---- era evaluation ---------------------------------------------------

    def _evaluate_era(self, now: float, event_bus: Any, advisor: Any) -> None:
        """Classify the current era based on event distribution in the rolling window."""
        window_start = now - _ERA_WINDOW
        recent = [e for e in self._entries if e.timestamp >= window_start]

        if not recent:
            return  # Not enough data to reclassify

        # Count events per category, weighted by drama
        category_scores: dict[str, float] = {}
        for entry in recent:
            cat = entry.category
            category_scores[cat] = category_scores.get(cat, 0) + entry.drama_weight

        # Evaluate each era def
        best_era: str | None = None
        best_score: float = 0
        best_priority: int = 0

        for era_id, edef in _era_def_cache.items():
            dominant_cats = edef.get("dominant_categories", [])
            threshold = edef.get("threshold", 5)
            priority = edef.get("priority", 1)

            era_score = sum(category_scores.get(cat, 0) for cat in dominant_cats)
            if era_score >= threshold:
                # Higher priority wins ties; higher score breaks priority ties
                if (priority > best_priority) or (
                    priority == best_priority and era_score > best_score
                ):
                    best_era = era_id
                    best_score = era_score
                    best_priority = priority

        if best_era is None:
            return  # No era qualifies — keep current

        if best_era != self._current_era:
            old_era = self._current_era
            # Close previous era
            if self._era_history:
                last = self._era_history[-1]
                if last[2] is None:
                    self._era_history[-1] = (last[0], last[1], now)
            else:
                self._era_history.append((old_era, self._era_start_time, now))

            # Start new era
            self._current_era = best_era
            self._era_start_time = now
            self._era_history.append((best_era, now, None))

            # Publish era transition event
            new_label = get_era_def(best_era) or {}
            old_label = get_era_def(old_era) or {}
            _logger.info(
                "Era transition: %s → %s",
                old_label.get("label", old_era),
                new_label.get("label", best_era),
            )

            if event_bus is not None:
                try:
                    event_bus.publish(GameEvent(
                        category=CATEGORY_MILESTONE,
                        summary=f"A new era begins: {new_label.get('label', best_era)}",
                        detail=new_label.get("description", ""),
                        timestamp=now,
                        metadata={
                            "type": "era_transition",
                            "old_era": old_era,
                            "new_era": best_era,
                        },
                    ))
                except Exception:
                    pass

            # Add to advisor observer timeline if available
            if advisor is not None:
                try:
                    timeline = getattr(advisor, "observer_timeline", None)
                    if timeline is not None:
                        timeline.append({
                            "time": now,
                            "event": f"Era transition: {new_label.get('label', best_era)}",
                            "category": "chronicle",
                        })
                except Exception:
                    pass

    def _apply_era_moodlets(self, praxans: list, now: float) -> None:
        """Apply era-specific moodlets to all living praxans."""
        edef = get_era_def(self._current_era)
        if edef is None:
            return

        moodlet_id = edef.get("moodlet")
        mood_offset = edef.get("mood_offset", 0)
        mood_duration = edef.get("mood_duration", 120)

        if not moodlet_id or mood_offset == 0:
            return

        for p in praxans:
            if not getattr(p, "alive", True):
                continue
            try:
                add_moodlet = getattr(p, "add_moodlet", None)
                if add_moodlet:
                    add_moodlet(moodlet_id, mood_offset, mood_duration, now)
            except Exception:
                pass

    # ---- legendary deeds evaluation ---------------------------------------

    def _evaluate_deeds(self, praxans: list, now: float) -> None:
        """Check all living praxans for newly completed legendary deeds."""
        if not _deed_def_cache:
            return

        for p in praxans:
            pid = getattr(p, "id", None)
            if pid is None:
                continue

            event_log = self._deed_event_log.get(pid, [])
            if not event_log:
                continue

            completed = self._completed_deeds.setdefault(pid, set())

            for deed_id, ddef in _deed_def_cache.items():
                if deed_id in completed:
                    continue

                required_count = ddef.get("required_count", 3)
                event_category = ddef.get("event_category", "")
                event_types = ddef.get("event_types", [])

                # Count matching events
                count = 0
                for event_type, _ts in event_log:
                    if event_types:
                        if event_type in event_types:
                            count += 1
                    elif event_type == event_category:
                        count += 1

                if count >= required_count:
                    # Deed completed!
                    completed.add(deed_id)
                    legend_pts = ddef.get("legend_points", 3)
                    self._legend_points[pid] = self._legend_points.get(pid, 0) + legend_pts

                    # Record in deed counts
                    deed_counts = self._deed_counts.setdefault(pid, {})
                    deed_counts[deed_id] = count

                    # Record episodic memory
                    try:
                        memory = getattr(p, "memory", None)
                        if memory and hasattr(memory, "record"):
                            memory.record(
                                category="legendary_deed",
                                summary=f"Achieved the deed: {ddef.get('label', deed_id)}",
                                emotional_weight=8.0,
                                related_ids=[],
                                metadata={"deed_id": deed_id},
                            )
                    except Exception:
                        pass

    def _evaluate_legend_tiers(
        self,
        praxans: list,
        reputation_manager: Any,
        event_bus: Any,
        now: float,
        advisor: Any,
    ) -> None:
        """Check for legend tier transitions and apply effects."""
        for p in praxans:
            pid = getattr(p, "id", None)
            if pid is None:
                continue

            pts = self._legend_points.get(pid, 0)
            if pts <= 0:
                continue

            tier = get_legend_tier(pts)
            if tier is None:
                continue

            tier_id = tier.get("id", "notable")
            old_tier_id = self._legend_tiers.get(pid)

            if tier_id != old_tier_id:
                self._legend_tiers[pid] = tier_id

                if old_tier_id is not None:
                    # Tier transition — publish event
                    label = tier.get("label", tier_id)
                    name = getattr(p, "name", f"Praxan {pid}")

                    _logger.info(
                        "Legend tier transition: %s is now %s (%d pts)",
                        name, label, pts,
                    )

                    # Reputation bonus
                    if reputation_manager is not None:
                        try:
                            reputation_manager.record_event(pid, "became_legend")
                        except Exception:
                            pass

                    # EventBus
                    if event_bus is not None:
                        try:
                            event_bus.publish(GameEvent(
                                category=CATEGORY_MILESTONE,
                                summary=f"{name} has become {label}",
                                detail=f"With {pts} legend points and {len(self._completed_deeds.get(pid, set()))} deeds",
                                praxan_id=pid,
                                faction_id=getattr(p, "faction_id", None),
                                timestamp=now,
                                metadata={
                                    "type": "legend_tier_transition",
                                    "tier": tier_id,
                                    "legend_points": pts,
                                },
                            ))
                        except Exception:
                            pass

                    # Episodic memory
                    try:
                        memory = getattr(p, "memory", None)
                        if memory and hasattr(memory, "record"):
                            memory.record(
                                category="legend_status",
                                summary=f"Became {label} — a living legend",
                                emotional_weight=9.0,
                                related_ids=[],
                                metadata={"tier": tier_id, "legend_points": pts},
                            )
                    except Exception:
                        pass

                    # Observer timeline
                    if advisor is not None:
                        try:
                            timeline = getattr(advisor, "observer_timeline", None)
                            if timeline is not None:
                                timeline.append({
                                    "time": now,
                                    "event": f"{name} became {label}",
                                    "category": "chronicle",
                                })
                        except Exception:
                            pass

    def _apply_legend_moodlets(self, praxans: list, now: float) -> None:
        """Apply legend-tier moodlets to qualifying praxans."""
        for p in praxans:
            pid = getattr(p, "id", None)
            if pid is None:
                continue

            tier_id = self._legend_tiers.get(pid)
            if tier_id is None:
                continue

            pts = self._legend_points.get(pid, 0)
            tier = get_legend_tier(pts)
            if tier is None:
                continue

            moodlet_id = tier.get("moodlet")
            mood_offset = tier.get("mood_offset", 0)
            mood_duration = tier.get("mood_duration", 300)

            if moodlet_id and mood_offset:
                try:
                    add_moodlet = getattr(p, "add_moodlet", None)
                    if add_moodlet:
                        add_moodlet(moodlet_id, mood_offset, mood_duration, now)
                except Exception:
                    pass

    # ---- cleanup ----------------------------------------------------------

    def remove_praxan(self, praxan_id: int) -> None:
        """Remove active tracking for a dead praxan (legend data preserved)."""
        # We keep _legend_points, _legend_tiers, _completed_deeds for
        # historical queries, but stop deed tracking
        self._deed_event_log.pop(praxan_id, None)

    # ---- serialization ----------------------------------------------------

    def serialize(self, current_time: float | None = None) -> dict[str, Any]:
        """Serialize the chronicle state for snapshots."""
        now = current_time if current_time is not None else time.time()
        return {
            "entries": [e.to_dict() for e in self._entries[-100:]],  # Keep last 100
            "current_era": self._current_era,
            "era_start_seconds_ago": round(now - self._era_start_time, 3),
            "era_history": [
                {
                    "era_id": era_id,
                    "start_seconds_ago": round(now - start, 3),
                    "end_seconds_ago": round(now - end, 3) if end is not None else None,
                }
                for era_id, start, end in self._era_history
            ],
            "deed_counts": {
                str(pid): dict(deeds)
                for pid, deeds in self._deed_counts.items()
            },
            "legend_points": {str(pid): pts for pid, pts in self._legend_points.items()},
            "legend_tiers": {str(pid): tid for pid, tid in self._legend_tiers.items()},
            "completed_deeds": {
                str(pid): list(deeds)
                for pid, deeds in self._completed_deeds.items()
            },
            "deed_event_log": {
                str(pid): [
                    {"type": etype, "seconds_ago": round(now - ts, 3)}
                    for etype, ts in events
                ]
                for pid, events in self._deed_event_log.items()
            },
            "last_eval_seconds_ago": round(now - self._last_eval_time, 3),
            "last_era_moodlet_seconds_ago": round(now - self._last_era_moodlet_time, 3),
            "last_legend_moodlet_seconds_ago": round(now - self._last_legend_moodlet_time, 3),
        }

    def restore(self, data: dict[str, Any], current_time: float | None = None) -> None:
        """Restore chronicle state from a snapshot."""
        now = current_time if current_time is not None else time.time()

        # Restore entries
        self._entries = [
            ChronicleEntry.from_dict(e)
            for e in data.get("entries", [])
        ]

        # Restore current era
        self._current_era = data.get("current_era", "age_of_founding")
        era_start_ago = data.get("era_start_seconds_ago", 0.0)
        self._era_start_time = now - max(0.0, float(era_start_ago))

        # Restore era history
        self._era_history = []
        for eh in data.get("era_history", []):
            start_ago = float(eh.get("start_seconds_ago", 0))
            end_ago = eh.get("end_seconds_ago")
            self._era_history.append((
                eh.get("era_id", ""),
                now - max(0.0, start_ago),
                now - max(0.0, float(end_ago)) if end_ago is not None else None,
            ))

        # Restore deed counts
        self._deed_counts = {
            int(pid): dict(deeds)
            for pid, deeds in data.get("deed_counts", {}).items()
        }

        # Restore legend points
        self._legend_points = {
            int(pid): int(pts)
            for pid, pts in data.get("legend_points", {}).items()
        }

        # Restore legend tiers
        self._legend_tiers = {
            int(pid): str(tid)
            for pid, tid in data.get("legend_tiers", {}).items()
        }

        # Restore completed deeds
        self._completed_deeds = {
            int(pid): set(deeds)
            for pid, deeds in data.get("completed_deeds", {}).items()
        }

        # Restore deed event log
        self._deed_event_log = {}
        for pid, events in data.get("deed_event_log", {}).items():
            self._deed_event_log[int(pid)] = [
                (ev.get("type", ""), now - max(0.0, float(ev.get("seconds_ago", 0))))
                for ev in events
            ]

        # Restore timing
        self._last_eval_time = now - max(
            5.0, float(data.get("last_eval_seconds_ago", _EVAL_INTERVAL))
        )
        self._last_era_moodlet_time = now - max(
            5.0, float(data.get("last_era_moodlet_seconds_ago", _ERA_MOODLET_INTERVAL))
        )
        self._last_legend_moodlet_time = now - max(
            5.0, float(data.get("last_legend_moodlet_seconds_ago", _LEGEND_MOODLET_INTERVAL))
        )
