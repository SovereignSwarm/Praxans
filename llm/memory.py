"""Rolling memory layers for civilization, factions, and map state.

Each layer maintains a bounded list of digest entries that summarize
recent history.  The memory_summarizer channel periodically compresses
these into shorter digests so prompts stay within budget.

Memory is serializable for snapshot save/restore.
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any


def _bounded_append(target: list, entry: Any, limit: int) -> None:
    target.append(entry)
    if len(target) > limit:
        del target[:-limit]


# ---------------------------------------------------------------------------
# Civilization Memory
# ---------------------------------------------------------------------------

class CivilizationMemory:
    """Doctrine changes, crises, major builds, population milestones."""

    MAX_ENTRIES = 20
    MAX_DIGESTS = 6

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.digests: list[str] = []

    def record(self, category: str, summary: str, time_stamp: float = 0.0) -> None:
        _bounded_append(
            self.entries,
            {"time": time_stamp or time.time(), "category": category, "summary": summary},
            self.MAX_ENTRIES,
        )

    def set_digest(self, digest_text: str) -> None:
        if digest_text:
            _bounded_append(self.digests, digest_text, self.MAX_DIGESTS)

    def recent_text(self, count: int = 8) -> str:
        lines = [e["summary"] for e in self.entries[-count:]]
        return "\n".join(lines) if lines else "(no recent events)"

    def digest_text(self) -> str:
        return "\n".join(self.digests) if self.digests else "(no digest yet)"

    def to_dict(self) -> dict[str, Any]:
        return {"entries": list(self.entries), "digests": list(self.digests)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CivilizationMemory:
        mem = cls()
        mem.entries = list(data.get("entries") or [])[-cls.MAX_ENTRIES:]
        mem.digests = list(data.get("digests") or [])[-cls.MAX_DIGESTS:]
        return mem


# ---------------------------------------------------------------------------
# Faction Memory
# ---------------------------------------------------------------------------

class FactionMemory:
    """Per-faction memory: leaders, schisms, rivalries, migrations, doctrine drift."""

    MAX_ENTRIES_PER_FACTION = 12
    MAX_DIGESTS_PER_FACTION = 4

    def __init__(self) -> None:
        # keyed by faction_id (int)
        self._entries: dict[int, list[dict[str, Any]]] = {}
        self._digests: dict[int, list[str]] = {}

    def record(self, faction_id: int, category: str, summary: str, time_stamp: float = 0.0) -> None:
        bucket = self._entries.setdefault(faction_id, [])
        _bounded_append(
            bucket,
            {"time": time_stamp or time.time(), "category": category, "summary": summary},
            self.MAX_ENTRIES_PER_FACTION,
        )

    def set_digest(self, faction_id: int, digest_text: str) -> None:
        if digest_text:
            bucket = self._digests.setdefault(faction_id, [])
            _bounded_append(bucket, digest_text, self.MAX_DIGESTS_PER_FACTION)

    def recent_text(self, faction_id: int, count: int = 6) -> str:
        bucket = self._entries.get(faction_id, [])
        lines = [e["summary"] for e in bucket[-count:]]
        return "\n".join(lines) if lines else "(no faction events)"

    def digest_text(self, faction_id: int) -> str:
        bucket = self._digests.get(faction_id, [])
        return "\n".join(bucket) if bucket else ""

    def all_faction_ids(self) -> list[int]:
        return sorted(set(self._entries.keys()) | set(self._digests.keys()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": {str(k): list(v) for k, v in self._entries.items()},
            "digests": {str(k): list(v) for k, v in self._digests.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FactionMemory:
        mem = cls()
        for k, v in (data.get("entries") or {}).items():
            try:
                fid = int(k)
            except (TypeError, ValueError):
                continue
            mem._entries[fid] = list(v)[-cls.MAX_ENTRIES_PER_FACTION:]
        for k, v in (data.get("digests") or {}).items():
            try:
                fid = int(k)
            except (TypeError, ValueError):
                continue
            mem._digests[fid] = list(v)[-cls.MAX_DIGESTS_PER_FACTION:]
        return mem


# ---------------------------------------------------------------------------
# Map Memory
# ---------------------------------------------------------------------------

class MapMemory:
    """Discovered landmarks, dangerous corridors, settlement networks, border tension."""

    MAX_ENTRIES = 16
    MAX_DIGESTS = 4

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.digests: list[str] = []

    def record(self, category: str, summary: str, time_stamp: float = 0.0) -> None:
        _bounded_append(
            self.entries,
            {"time": time_stamp or time.time(), "category": category, "summary": summary},
            self.MAX_ENTRIES,
        )

    def set_digest(self, digest_text: str) -> None:
        if digest_text:
            _bounded_append(self.digests, digest_text, self.MAX_DIGESTS)

    def recent_text(self, count: int = 6) -> str:
        lines = [e["summary"] for e in self.entries[-count:]]
        return "\n".join(lines) if lines else "(no map events)"

    def digest_text(self) -> str:
        return "\n".join(self.digests) if self.digests else "(no map digest)"

    def to_dict(self) -> dict[str, Any]:
        return {"entries": list(self.entries), "digests": list(self.digests)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MapMemory:
        mem = cls()
        mem.entries = list(data.get("entries") or [])[-cls.MAX_ENTRIES:]
        mem.digests = list(data.get("digests") or [])[-cls.MAX_DIGESTS:]
        return mem


# ---------------------------------------------------------------------------
# Aggregate Memory Container
# ---------------------------------------------------------------------------

class LLMMemory:
    """Top-level container holding all three memory layers."""

    def __init__(self) -> None:
        self.civilization = CivilizationMemory()
        self.factions = FactionMemory()
        self.map = MapMemory()

    def to_dict(self) -> dict[str, Any]:
        return {
            "civilization": self.civilization.to_dict(),
            "factions": self.factions.to_dict(),
            "map": self.map.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMMemory:
        mem = cls()
        if data:
            mem.civilization = CivilizationMemory.from_dict(data.get("civilization") or {})
            mem.factions = FactionMemory.from_dict(data.get("factions") or {})
            mem.map = MapMemory.from_dict(data.get("map") or {})
        return mem

    # Convenience aliases used by snapshot / restore code
    def serialize(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def deserialize(cls, data: dict[str, Any]) -> LLMMemory:
        return cls.from_dict(data)
