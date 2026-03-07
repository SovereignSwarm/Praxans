"""Per-Praxan Autobiographical / Episodic Memory System.

Every Praxan carries a bounded rolling list of personally significant events.
Memories are personality-weighted: a curious Praxan values discovery memories
more; a social Praxan weighs friendships and losses more heavily.

The system is data-driven — event type definitions live in
``defs/core/memory_events.json`` and are loaded via ``DefDatabase``.

Typical integration points:
    - ``Praxan.__init__``: create ``EpisodicMemory``
    - ``apply_grief``, ``trigger_mental_break``, ``set_relationship``, etc.:
      call ``memory.record(...)``
    - ``ui/inspect.py``: call ``recent_text()`` / ``life_story_summary()``
    - ``llm/state_views.py``: call ``most_significant(3)``
    - Snapshot save/load: ``to_dict()`` / ``from_dict()``
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_MEMORIES = 24  # Rolling cap — roughly one per in-game "chapter"

# Personality amplification factor (0-1 personality value ×  this)
PERSONALITY_AMP = 0.5  # e.g. curiosity=1.0 → +50% weight on discovery memories


# ---------------------------------------------------------------------------
# MemoryEntry
# ---------------------------------------------------------------------------

@dataclass
class MemoryEntry:
    """A single autobiographical memory."""

    category: str        # e.g. "birth", "grief", "masterwork"
    summary: str         # Human-readable one-liner
    emotional_weight: float  # 0-10+, higher = more significant
    timestamp: float = field(default_factory=time.time)
    related_ids: list[int] = field(default_factory=list)  # Praxan IDs involved
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "summary": self.summary,
            "emotional_weight": round(self.emotional_weight, 2),
            "timestamp": self.timestamp,
            "related_ids": list(self.related_ids),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryEntry":
        return cls(
            category=data.get("category", "unknown"),
            summary=data.get("summary", ""),
            emotional_weight=data.get("emotional_weight", 1.0),
            timestamp=data.get("timestamp", 0.0),
            related_ids=list(data.get("related_ids", [])),
            metadata=dict(data.get("metadata", {})),
        )


# ---------------------------------------------------------------------------
# MemoryEventDef cache (loaded from DefDatabase lazily)
# ---------------------------------------------------------------------------

_event_def_cache: dict[str, dict[str, Any]] = {}


def _get_event_def(category: str) -> dict[str, Any]:
    """Look up a MemoryEventDef from the DefDatabase (cached)."""
    if category in _event_def_cache:
        return _event_def_cache[category]

    # Try DefDatabase
    try:
        from systems.def_database import DefDatabase
        defs = DefDatabase.get_all("MemoryEventDef")
        for d in defs:
            _event_def_cache[d["id"]] = d
        if category in _event_def_cache:
            return _event_def_cache[category]
    except Exception:
        pass

    # Fallback defaults
    return {"id": category, "base_weight": 3, "personality_factor": None, "label": category.replace("_", " ").title()}


def _calculate_weight(category: str, personality: dict[str, float]) -> float:
    """Calculate emotional weight from base + personality amplification."""
    event_def = _get_event_def(category)
    base = event_def.get("base_weight", 3)
    factor_key = event_def.get("personality_factor")
    if factor_key and factor_key in personality:
        base += personality[factor_key] * PERSONALITY_AMP * base
    return round(base, 2)


def get_event_label(category: str) -> str:
    """Return human-readable label for a memory category."""
    event_def = _get_event_def(category)
    return event_def.get("label", category.replace("_", " ").title())


# ---------------------------------------------------------------------------
# EpisodicMemory
# ---------------------------------------------------------------------------

class EpisodicMemory:
    """Bounded, personality-weighted autobiographical memory for one Praxan.

    Parameters
    ----------
    personality : dict
        The owning Praxan's personality dict (curiosity, sociability, diligence).
    max_entries : int
        Rolling cap on stored memories (default 24).
    """

    def __init__(
        self,
        personality: Optional[dict[str, float]] = None,
        max_entries: int = MAX_MEMORIES,
    ) -> None:
        self.personality: dict[str, float] = personality or {}
        self.max_entries = max_entries
        self.entries: list[MemoryEntry] = []

    # ---- recording --------------------------------------------------------

    def record(
        self,
        category: str,
        summary: str,
        related_ids: Optional[list[int]] = None,
        timestamp: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
        weight_override: Optional[float] = None,
    ) -> MemoryEntry:
        """Record a new memory. Returns the created entry."""
        weight = weight_override if weight_override is not None else _calculate_weight(category, self.personality)
        entry = MemoryEntry(
            category=category,
            summary=summary,
            emotional_weight=weight,
            timestamp=timestamp if timestamp is not None else time.time(),
            related_ids=list(related_ids or []),
            metadata=dict(metadata or {}),
        )
        self.entries.append(entry)

        # Enforce cap — evict the least significant memory (not the most recent)
        if len(self.entries) > self.max_entries:
            min_idx = 0
            min_weight = self.entries[0].emotional_weight
            for i, e in enumerate(self.entries[1:], 1):
                if e.emotional_weight < min_weight:
                    min_weight = e.emotional_weight
                    min_idx = i
            del self.entries[min_idx]

        return entry

    # ---- querying ---------------------------------------------------------

    def most_significant(self, n: int = 3) -> list[MemoryEntry]:
        """Return the N most emotionally significant memories."""
        sorted_entries = sorted(self.entries, key=lambda e: e.emotional_weight, reverse=True)
        return sorted_entries[:n]

    def recent(self, n: int = 6) -> list[MemoryEntry]:
        """Return the N most recent memories."""
        return list(self.entries[-n:])

    def by_category(self, category: str) -> list[MemoryEntry]:
        """Return all memories of a given category."""
        return [e for e in self.entries if e.category == category]

    def recent_text(self, n: int = 6) -> str:
        """Human-readable recent history (newest first)."""
        recent = list(reversed(self.entries[-n:]))
        if not recent:
            return "(no memories yet)"
        lines = []
        for entry in recent:
            label = get_event_label(entry.category)
            lines.append(f"- {label}: {entry.summary}")
        return "\n".join(lines)

    def most_significant_text(self, n: int = 3) -> str:
        """Human-readable most significant memories."""
        significant = self.most_significant(n)
        if not significant:
            return "(no memories yet)"
        lines = []
        for entry in significant:
            label = get_event_label(entry.category)
            lines.append(f"- {label}: {entry.summary}")
        return "\n".join(lines)

    def life_story_summary(self) -> str:
        """Auto-generate a one-sentence life story from top memories."""
        if not self.entries:
            return "Has no notable memories yet."

        top = self.most_significant(4)
        fragments = []
        for entry in top:
            label = get_event_label(entry.category).lower()
            fragments.append(label)

        if len(fragments) == 1:
            return f"A life marked by: {fragments[0]}."
        elif len(fragments) == 2:
            return f"A life shaped by {fragments[0]} and {fragments[1]}."
        else:
            return f"A life shaped by {', '.join(fragments[:-1])}, and {fragments[-1]}."

    @property
    def memory_count(self) -> int:
        return len(self.entries)

    # ---- mood integration -------------------------------------------------

    def recent_trauma_score(self, lookback: float = 300.0) -> float:
        """Sum emotional weight of negative memories in the last `lookback` seconds.

        Used by happiness calculation to apply nostalgia/trauma mood modifiers.
        """
        now = time.time()
        trauma_categories = {"grief", "mental_break", "combat_wound", "near_death"}
        score = 0.0
        for entry in self.entries:
            if entry.category in trauma_categories and (now - entry.timestamp) < lookback:
                score += entry.emotional_weight
        return score

    def recent_joy_score(self, lookback: float = 300.0) -> float:
        """Sum emotional weight of positive memories in the last `lookback` seconds."""
        now = time.time()
        joy_categories = {"partnership", "friendship", "masterwork", "discovery", "parenthood"}
        score = 0.0
        for entry in self.entries:
            if entry.category in joy_categories and (now - entry.timestamp) < lookback:
                score += entry.emotional_weight
        return score

    # ---- serialization ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "max_entries": self.max_entries,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], personality: Optional[dict[str, float]] = None) -> "EpisodicMemory":
        if data is None:
            return cls(personality=personality)
        mem = cls(
            personality=personality,
            max_entries=data.get("max_entries", MAX_MEMORIES),
        )
        for entry_data in data.get("entries", []):
            mem.entries.append(MemoryEntry.from_dict(entry_data))
        return mem
