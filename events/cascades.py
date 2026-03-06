"""Cascading rules and cinematic hooks for the EventBus.

When a high-drama event fires, these rules trigger downstream effects:
- Narrative panel emphasis (title cards)
- Camera focus requests
- Historian LLM channel wake-up
- Particle burst requests

Usage:
    from events.cascades import attach_default_cascades
    attach_default_cascades(event_bus, narrative_panel, camera_director)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from events.bus import (
    GameEvent,
    EventBus,
    CATEGORY_SCHISM,
    CATEGORY_MIGRATION,
    CATEGORY_EXTINCTION,
    CATEGORY_DISASTER,
    CATEGORY_CULTURAL_SHIFT,
    CATEGORY_MILESTONE,
    CATEGORY_DEATH,
    CATEGORY_DIPLOMACY,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Title card overlay data (consumed by the HUD renderer)
# ---------------------------------------------------------------------------

class TitleCardQueue:
    """Holds pending title cards for the HUD to render."""

    def __init__(self, max_display_time: float = 4.0):
        self.pending: list[dict[str, Any]] = []
        self.max_display_time = max_display_time

    def push(self, title: str, subtitle: str = "", drama: int = 5) -> None:
        self.pending.append({
            "title": title,
            "subtitle": subtitle,
            "drama": drama,
            "remaining": self.max_display_time,
        })

    def pop_expired(self, dt: float) -> list[dict[str, Any]]:
        """Tick all cards and return those that expired."""
        expired = []
        alive = []
        for card in self.pending:
            card["remaining"] -= dt
            if card["remaining"] <= 0:
                expired.append(card)
            else:
                alive.append(card)
        self.pending = alive
        return expired

    @property
    def active_card(self) -> dict[str, Any] | None:
        return self.pending[0] if self.pending else None


# ---------------------------------------------------------------------------
# Camera focus request queue
# ---------------------------------------------------------------------------

class CameraFocusQueue:
    """Queue of (x, y) positions the camera should smoothly pan to."""

    def __init__(self):
        self.requests: list[tuple[float, float, float]] = []  # (x, y, urgency)

    def request_focus(self, x: float, y: float, urgency: float = 5.0) -> None:
        self.requests.append((x, y, urgency))

    def pop_highest(self) -> tuple[float, float] | None:
        if not self.requests:
            return None
        self.requests.sort(key=lambda r: r[2], reverse=True)
        x, y, _ = self.requests.pop(0)
        return (x, y)


# ---------------------------------------------------------------------------
# Default cascade rules
# ---------------------------------------------------------------------------

_TITLE_TEMPLATES: dict[str, str] = {
    CATEGORY_SCHISM: "THE GREAT SCHISM",
    CATEGORY_MIGRATION: "THE EXODUS",
    CATEGORY_EXTINCTION: "EXTINCTION",
    CATEGORY_DISASTER: "CATASTROPHE",
    CATEGORY_CULTURAL_SHIFT: "CULTURAL AWAKENING",
    CATEGORY_MILESTONE: "MILESTONE",
}


def attach_default_cascades(
    bus: EventBus,
    title_cards: TitleCardQueue,
    camera_focus: CameraFocusQueue,
    narrative_panel: Any | None = None,
) -> None:
    """Wire default cascading rules into the event bus."""

    def _on_high_drama(event: GameEvent) -> None:
        """Handle any high-drama event with title card + camera focus."""
        if not event.is_high_drama:
            return

        # Title card
        title = _TITLE_TEMPLATES.get(event.category, event.category.upper())
        title_cards.push(title, event.summary[:80], event.drama)

        # Camera focus
        if event.location:
            camera_focus.request_focus(
                event.location[0], event.location[1],
                urgency=float(event.drama),
            )

        # Narrative panel emphasis
        if narrative_panel is not None and hasattr(narrative_panel, "add_message"):
            prefix = f"[{event.category.upper()}]"
            narrative_panel.add_message(f"{prefix} {event.summary}", "Chronicle")

    def _on_death(event: GameEvent) -> None:
        """Deaths get narrative mention if drama >= 3."""
        if event.drama >= 3 and narrative_panel and hasattr(narrative_panel, "add_message"):
            narrative_panel.add_message(event.summary, "Chronicle")

    def _on_trade(event: GameEvent) -> None:
        """Trade events get a brief narrative mention."""
        if narrative_panel and hasattr(narrative_panel, "add_message"):
            narrative_panel.add_message(event.summary, "Trade")

    # Subscribe
    bus.subscribe("*", _on_high_drama)
    bus.subscribe(CATEGORY_DEATH, _on_death)
    bus.subscribe(CATEGORY_DIPLOMACY, _on_trade)

    logger.debug("[Cascades] Default narrative cascades attached")
