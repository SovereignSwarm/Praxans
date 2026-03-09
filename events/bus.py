"""Publish-subscribe event bus for the Praxans narrative engine.

All game subsystems publish typed events.  Subscribers (historian, narrative
panel, cinematic director, archive) react to events with cascading rules.

Usage:
    bus = EventBus()
    bus.subscribe("schism", my_handler)
    bus.publish(GameEvent("schism", summary="Faction 0 collapsed", ...))
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event categories
# ---------------------------------------------------------------------------

CATEGORY_BIRTH = "birth"
CATEGORY_DEATH = "death"
CATEGORY_SCHISM = "schism"
CATEGORY_MIGRATION = "migration"
CATEGORY_DOCTRINE = "doctrine_change"
CATEGORY_TRADE = "trade"
CATEGORY_DIPLOMACY = "diplomacy"
CATEGORY_BUILDING = "building"
CATEGORY_MILESTONE = "milestone"
CATEGORY_CULTURAL_SHIFT = "cultural_shift"
CATEGORY_DISASTER = "disaster"
CATEGORY_EXTINCTION = "extinction"
CATEGORY_PERSONAL = "personal"

ALL_CATEGORIES = (
    CATEGORY_BIRTH, CATEGORY_DEATH, CATEGORY_SCHISM, CATEGORY_MIGRATION,
    CATEGORY_DOCTRINE, CATEGORY_TRADE, CATEGORY_DIPLOMACY, CATEGORY_BUILDING,
    CATEGORY_MILESTONE, CATEGORY_CULTURAL_SHIFT, CATEGORY_DISASTER,
    CATEGORY_EXTINCTION, CATEGORY_PERSONAL,
)

# Drama weight: how "cinematic" is this event type?
_DRAMA_WEIGHTS: dict[str, int] = {
    CATEGORY_BIRTH: 1,
    CATEGORY_DEATH: 3,
    CATEGORY_SCHISM: 8,
    CATEGORY_MIGRATION: 5,
    CATEGORY_DOCTRINE: 4,
    CATEGORY_TRADE: 2,
    CATEGORY_DIPLOMACY: 4,
    CATEGORY_BUILDING: 2,
    CATEGORY_MILESTONE: 6,
    CATEGORY_CULTURAL_SHIFT: 7,
    CATEGORY_DISASTER: 9,
    CATEGORY_EXTINCTION: 10,
    CATEGORY_PERSONAL: 3,
}


# ---------------------------------------------------------------------------
# GameEvent
# ---------------------------------------------------------------------------

@dataclass
class GameEvent:
    """A typed, timestamped game event."""

    category: str
    summary: str
    detail: str = ""
    location: tuple[float, float] | None = None  # world (x, y) for camera
    faction_id: int | None = None
    praxan_id: int | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def drama(self) -> int:
        """0-10 drama score based on category."""
        return _DRAMA_WEIGHTS.get(self.category, 1)

    @property
    def is_high_drama(self) -> bool:
        return self.drama >= 6

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "summary": self.summary,
            "detail": self.detail,
            "location": list(self.location) if self.location else None,
            "faction_id": self.faction_id,
            "praxan_id": self.praxan_id,
            "timestamp": self.timestamp,
            "drama": self.drama,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------

# Type alias for event handlers
EventHandler = Callable[[GameEvent], None]


class EventBus:
    """Central publish-subscribe bus for all game events.

    Features:
    - Per-category subscribers
    - Wildcard subscribers ("*") that receive all events
    - Rolling event log (capped) for the historian LLM channel
    - Drama-ranked recent events for cinematic hooks
    """

    def __init__(self, max_log: int = 100):
        self._subscribers: dict[str, list[EventHandler]] = {"*": []}
        self._log: list[GameEvent] = []
        self._max_log = max_log

    # ---- publishing -------------------------------------------------------

    def publish(self, event: GameEvent) -> None:
        """Publish an event to all matching subscribers."""
        self._log.append(event)
        if len(self._log) > self._max_log:
            del self._log[: len(self._log) - self._max_log]

        # Category-specific handlers
        for handler in self._subscribers.get(event.category, []):
            try:
                handler(event)
            except Exception:
                _logger.warning(
                    "Category subscriber failed during EventBus.publish",
                    extra={"event_category": event.category, "handler": getattr(handler, "__name__", repr(handler))},
                    exc_info=True,
                )

        # Wildcard handlers
        for handler in self._subscribers.get("*", []):
            try:
                handler(event)
            except Exception:
                _logger.warning(
                    "Wildcard subscriber failed during EventBus.publish",
                    extra={"event_category": event.category, "handler": getattr(handler, "__name__", repr(handler))},
                    exc_info=True,
                )

    # ---- subscribing ------------------------------------------------------

    def subscribe(self, category: str, handler: EventHandler) -> None:
        """Subscribe a handler to a specific category, or '*' for all."""
        self._subscribers.setdefault(category, []).append(handler)

    def unsubscribe(self, category: str, handler: EventHandler) -> None:
        handlers = self._subscribers.get(category, [])
        if handler in handlers:
            handlers.remove(handler)

    # ---- querying ---------------------------------------------------------

    def recent(self, count: int = 10) -> list[GameEvent]:
        """Return the most recent N events."""
        return list(self._log[-count:])

    def recent_by_category(self, category: str, count: int = 5) -> list[GameEvent]:
        return [e for e in self._log if e.category == category][-count:]

    def recent_high_drama(self, count: int = 3) -> list[GameEvent]:
        """Return the most recent high-drama events (drama >= 6)."""
        return [e for e in self._log if e.is_high_drama][-count:]

    def recent_for_historian(self, count: int = 8) -> list[dict[str, Any]]:
        """Return recent events as dicts suitable for historian LLM view."""
        return [e.to_dict() for e in self._log[-count:]]

    def drain_high_drama_since(self, since: float) -> list[GameEvent]:
        """Return high-drama events since a timestamp (for cinematic director)."""
        return [e for e in self._log if e.is_high_drama and e.timestamp > since]

    @property
    def event_count(self) -> int:
        return len(self._log)

    def serialize(self) -> list[dict[str, Any]]:
        """Serialize the last 20 events for snapshot/archive."""
        return [e.to_dict() for e in self._log[-20:]]
