"""Autonomous tech research system.

Factions autonomously research technologies based on their doctrine,
spending accumulated research points without requiring LLM input.
Each faction's doctrine guides which tech branch it prioritizes,
creating a doctrine -> tech -> modifier feedback loop.

Usage:
    from systems.tech_research import TechResearchManager
    tech_mgr = TechResearchManager()
    tech_mgr.update(current_time, advisor, factions, event_bus, narrative_panel)
"""

from __future__ import annotations

import time
import random
from typing import Any

# Doctrine -> ordered tech priority.  Each faction tries to unlock techs
# in this order, falling back to any affordable tech if none match.
DOCTRINE_TECH_PRIORITIES: dict[str, list[str]] = {
    "growth":       ["agriculture_1", "agriculture_2", "architecture_1", "social_1", "medicine_1"],
    "security":     ["medicine_1", "medicine_2", "architecture_1", "social_1", "agriculture_1"],
    "industry":     ["industry_1", "agriculture_1", "architecture_1", "exploration_1", "medicine_1"],
    "exploration":  ["exploration_1", "industry_1", "agriculture_1", "medicine_1", "social_1"],
    "harmony":      ["social_1", "social_2", "medicine_1", "architecture_1", "agriculture_1"],
}

# Minimum research points to start considering auto-research.
# Prevents trivially spending points before any meaningful accumulation.
MIN_POINTS_TO_RESEARCH = 50

# How often (seconds) the manager evaluates research candidates.
RESEARCH_EVAL_INTERVAL = 30.0

# After unlocking a tech, wait at least this long before next unlock.
POST_UNLOCK_COOLDOWN = 45.0


class TechResearchManager:
    """Autonomously researches technologies based on faction doctrine."""

    def __init__(self):
        self.last_eval_time: float = 0.0
        self.last_unlock_time: float = 0.0
        self.research_log: list[dict[str, Any]] = []  # [{tech_id, time, faction_doctrine, cost}]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        current_time: float,
        advisor,
        factions: list | None = None,
        event_bus=None,
        narrative_panel=None,
    ) -> str | None:
        """Evaluate and potentially unlock a tech.  Returns tech_id if unlocked, else None."""
        if advisor is None:
            return None

        # Throttle evaluation
        if current_time - self.last_eval_time < RESEARCH_EVAL_INTERVAL:
            return None
        self.last_eval_time = current_time

        # Post-unlock cooldown
        if current_time - self.last_unlock_time < POST_UNLOCK_COOLDOWN:
            return None

        # Need minimum points
        if advisor.research_points < MIN_POINTS_TO_RESEARCH:
            return None

        tech_tree = getattr(advisor, "tech_tree", {})
        unlocked = getattr(advisor.game_modifiers, "tech_unlocked", set())

        if not tech_tree:
            return None

        # All techs already unlocked?
        available = {tid for tid in tech_tree if tid not in unlocked}
        if not available:
            return None

        # Determine dominant doctrine
        doctrine = self._get_dominant_doctrine(factions)

        # Pick best tech candidate
        tech_id = self._select_tech(doctrine, tech_tree, unlocked, advisor.research_points)
        if tech_id is None:
            return None

        # Unlock it
        self._unlock_tech(tech_id, current_time, advisor, doctrine, event_bus, narrative_panel)
        return tech_id

    def serialize(self) -> dict[str, Any]:
        return {
            "last_eval_time": self.last_eval_time,
            "last_unlock_time": self.last_unlock_time,
            "research_log": list(self.research_log),
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.last_eval_time = float(data.get("last_eval_time", 0.0))
        self.last_unlock_time = float(data.get("last_unlock_time", 0.0))
        self.research_log = list(data.get("research_log", []))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_dominant_doctrine(self, factions: list | None) -> str:
        """Return the doctrine of the largest faction, defaulting to 'growth'."""
        if not factions:
            return "growth"

        best_faction = None
        best_size = -1
        for f in factions:
            size = len(getattr(f, "member_ids", []))
            if size > best_size:
                best_size = size
                best_faction = f

        if best_faction is None:
            return "growth"

        return getattr(best_faction, "primary_doctrine", "growth")

    def _can_research(self, tech_id: str, tech_tree: dict, unlocked: set, points: int) -> bool:
        """Check if a tech can be researched (prerequisites met and affordable)."""
        if tech_id not in tech_tree:
            return False
        if tech_id in unlocked:
            return False

        tech = tech_tree[tech_id]
        cost = tech.get("cost", 0)
        if points < cost:
            return False

        # Check prerequisites
        requires = tech.get("requires", [])
        for req in requires:
            if req not in unlocked:
                return False

        return True

    def _select_tech(
        self,
        doctrine: str,
        tech_tree: dict,
        unlocked: set,
        points: int,
    ) -> str | None:
        """Select the best tech to research based on doctrine priority."""
        # 1. Try doctrine-prioritized techs in order
        priorities = DOCTRINE_TECH_PRIORITIES.get(doctrine, [])
        for tech_id in priorities:
            if self._can_research(tech_id, tech_tree, unlocked, points):
                return tech_id

        # 2. Fallback: any affordable tech sorted by cost (cheapest first)
        fallback = []
        for tech_id, tech_data in tech_tree.items():
            if self._can_research(tech_id, tech_tree, unlocked, points):
                fallback.append((tech_data.get("cost", 0), tech_id))

        if fallback:
            fallback.sort()
            return fallback[0][1]

        return None

    def _unlock_tech(
        self,
        tech_id: str,
        current_time: float,
        advisor,
        doctrine: str,
        event_bus,
        narrative_panel,
    ) -> None:
        """Unlock a tech: deduct points, apply modifiers, notify systems."""
        tech_tree = advisor.tech_tree
        tech = tech_tree[tech_id]
        cost = tech.get("cost", 0)
        name = tech.get("name", tech_id)

        # Deduct cost
        advisor.research_points -= cost
        advisor.points_spent = getattr(advisor, "points_spent", 0) + cost

        # Mark as unlocked
        advisor.game_modifiers.tech_unlocked.add(tech_id)

        # Apply permanent effects
        for mechanic, value in tech.get("effect", {}).items():
            advisor.game_modifiers.permanent[mechanic] = value

        # Record
        self.last_unlock_time = current_time
        log_entry = {
            "tech_id": tech_id,
            "name": name,
            "time": current_time,
            "doctrine": doctrine,
            "cost": cost,
        }
        self.research_log.append(log_entry)

        # Narrative
        doctrine_label = doctrine.replace("_", " ").title()
        if narrative_panel is not None:
            narrative_panel.add_message(
                f"Research breakthrough: {name}! (driven by {doctrine_label} doctrine)",
                "Achievement",
            )

        # EventBus
        if event_bus is not None:
            try:
                from events.bus import GameEvent, CATEGORY_MILESTONE
                event_bus.publish(GameEvent(
                    category=CATEGORY_MILESTONE,
                    summary=f"Tech unlocked: {name}",
                    detail=f"The colony's {doctrine_label} focus led to a breakthrough in {name}. "
                           f"Effects: {', '.join(f'{k}={v}' for k, v in tech.get('effect', {}).items())}",
                    metadata={"tech_id": tech_id, "doctrine": doctrine, "cost": cost},
                ))
            except Exception:
                pass

        # Observer analytics — record_observer_timeline_event lives in praxans_game
        # which cannot be imported in test contexts, so we check the advisor directly.
        try:
            timeline = getattr(advisor, "observer_timeline", None)
            if timeline is not None and isinstance(timeline, list):
                timeline.append({
                    "time": current_time,
                    "category": "milestone",
                    "summary": f"Tech unlocked: {name}",
                    "details": f"Doctrine: {doctrine_label}, Cost: {cost} RP",
                })
        except Exception:
            pass

        print(f"[TechResearch] Unlocked {name} (doctrine={doctrine}, cost={cost}, remaining={advisor.research_points})")

    def get_research_progress(self, advisor) -> dict[str, Any]:
        """Return a summary of research state for UI display."""
        if advisor is None:
            return {}

        tech_tree = getattr(advisor, "tech_tree", {})
        unlocked = getattr(advisor.game_modifiers, "tech_unlocked", set())
        points = getattr(advisor, "research_points", 0)

        total = len(tech_tree)
        done = len(unlocked)

        # Next candidate
        doctrine = "growth"
        next_tech = self._select_tech(doctrine, tech_tree, unlocked, 999999)
        next_name = tech_tree[next_tech]["name"] if next_tech and next_tech in tech_tree else None
        next_cost = tech_tree[next_tech].get("cost", 0) if next_tech and next_tech in tech_tree else 0

        return {
            "unlocked": done,
            "total": total,
            "points": points,
            "next_tech": next_name,
            "next_cost": next_cost,
            "recent": [e["name"] for e in self.research_log[-3:]],
        }
