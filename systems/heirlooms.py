"""Heirloom & Legacy Artifact System.

Named items that transcend individual Praxan lifetimes.  When a Praxan crafts
a Masterwork+ quality item, it may become a **named heirloom** — a weapon,
armor, tool, or symbolic relic with a procedurally-generated name, an ownership
history, and a growing **legend score** that tracks notable events in the
item's life.

Key mechanics:

- **Creation**: masterwork/legendary crafted items automatically become
  heirlooms.  Faction-founding events create Founder's Banners.  Leader
  deaths create Memorial Stones.
- **Naming**: procedural two-part names (adjective + noun) seeded from the
  creator's ID and the item's creation time.
- **Legend growth**: events involving the heirloom (battles, inheritance,
  owner becoming luminary, surviving disasters) add to its legend score.
  Higher legend = stronger stat bonuses.
- **Inheritance**: on owner death, the heirloom passes to the next bearer
  in priority order (partner → child → faction leader → faction vault).
- **Faction relics**: when legend exceeds a threshold, the heirloom becomes
  a faction relic granting cohesion bonuses to all faction members.
- **Looting**: warfare raids can steal heirlooms from defeated factions.
- **Moodlets**: receiving, losing, and bearing ancestral heirlooms all
  affect mood.  Faction relics grant a passive mood bonus.
- **Reputation**: creating an heirloom grants reputation.  Bearing a faction
  relic grants periodic reputation.
- **Memory**: key heirloom events are recorded in episodic memory.

Definitions live in ``defs/core/heirlooms.json`` and are loaded via
``DefDatabase``.

Integration:
    - ``HeirloomManager.update()`` called on rare-tick cadence (~every 30s)
    - Entity fields: ``praxan._pending_heirloom_events`` list
    - Snapshot: ``serialize()`` / ``restore()``
    - EventBus: subscribes to CATEGORY_DEATH, CATEGORY_WARFARE, CATEGORY_DISASTER
    - Publishes CATEGORY_CULTURAL_SHIFT on relic ascension
    - Reputation: queues ``created_heirloom``, ``holds_faction_relic``
    - Episodic memory: records creation, inheritance, loss, relic ascension
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from events.bus import (
    CATEGORY_CULTURAL_SHIFT,
    CATEGORY_DEATH,
    CATEGORY_DISASTER,
    CATEGORY_MILESTONE,
    CATEGORY_WARFARE,
    GameEvent,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Def cache (lazily loaded from DefDatabase)
# ---------------------------------------------------------------------------

_heirloom_type_cache: dict[str, dict[str, Any]] = {}
_heirloom_event_cache: dict[str, dict[str, Any]] = {}


def _load_defs() -> None:
    """Populate caches from DefDatabase."""
    global _heirloom_type_cache, _heirloom_event_cache
    if _heirloom_type_cache:
        return
    try:
        from systems.def_database import DefDatabase
        type_defs = DefDatabase.get_all("HeirloomTypeDef")
        if type_defs:
            for def_id, def_data in type_defs.items():
                _heirloom_type_cache[def_id] = def_data
        event_defs = DefDatabase.get_all("HeirloomEventDef")
        if event_defs:
            for def_id, def_data in event_defs.items():
                _heirloom_event_cache[def_id] = def_data
    except Exception:
        pass


def get_heirloom_type_def(type_id: str) -> Optional[dict[str, Any]]:
    _load_defs()
    return _heirloom_type_cache.get(type_id)


def get_all_heirloom_type_defs() -> dict[str, dict[str, Any]]:
    _load_defs()
    return dict(_heirloom_type_cache)


def get_heirloom_event_def(event_id: str) -> Optional[dict[str, Any]]:
    _load_defs()
    return _heirloom_event_cache.get(event_id)


def clear_cache() -> None:
    """Clear cached defs (for testing)."""
    global _heirloom_type_cache, _heirloom_event_cache
    _heirloom_type_cache = {}
    _heirloom_event_cache = {}


# ---------------------------------------------------------------------------
# Name generation
# ---------------------------------------------------------------------------

_HEIRLOOM_PREFIXES = [
    "Dawn", "Storm", "Iron", "Blood", "Ash", "Sun", "Moon", "Star",
    "Frost", "Thunder", "Shadow", "Stone", "Fire", "Wind", "Night",
    "Bone", "Silk", "Ember", "Tide", "Thorn",
]

_WEAPON_SUFFIXES = [
    "fang", "bite", "edge", "fury", "wrath", "song", "cry",
    "bane", "strike", "claw", "thorn", "heart", "keeper", "render",
]

_ARMOR_SUFFIXES = [
    "guard", "ward", "shell", "mantle", "aegis", "bastion",
    "shield", "wall", "shroud", "veil", "bulwark", "haven",
]

_TOOL_SUFFIXES = [
    "craft", "touch", "hand", "mark", "gift", "grace",
    "spark", "bloom", "weave", "forge", "mend", "shaper",
]

_RELIC_SUFFIXES = [
    "banner", "stone", "totem", "sigil", "crown", "flame",
    "oath", "memory", "light", "spirit", "glory", "legacy",
]

_MEMORIAL_SUFFIXES = [
    "memorial", "remembrance", "tribute", "monument", "pillar",
    "marker", "cairn", "shrine", "echo", "whisper",
]


def generate_heirloom_name(
    category: str, creator_id: int = 0, created_at: float = 0.0,
) -> str:
    """Generate a procedural two-part name for an heirloom."""
    seed = hash((creator_id, int(created_at * 1000))) & 0xFFFFFFFF
    rng = random.Random(seed)
    prefix = rng.choice(_HEIRLOOM_PREFIXES)
    if category == "weapon":
        suffix = rng.choice(_WEAPON_SUFFIXES)
    elif category == "armor":
        suffix = rng.choice(_ARMOR_SUFFIXES)
    elif category == "tool":
        suffix = rng.choice(_TOOL_SUFFIXES)
    elif category == "memorial":
        suffix = rng.choice(_MEMORIAL_SUFFIXES)
    else:
        suffix = rng.choice(_RELIC_SUFFIXES)
    return f"{prefix}{suffix}"


# ---------------------------------------------------------------------------
# Heirloom data model
# ---------------------------------------------------------------------------

_next_heirloom_id = 1


def _get_next_id() -> int:
    global _next_heirloom_id
    hid = _next_heirloom_id
    _next_heirloom_id += 1
    return hid


@dataclass
class Heirloom:
    """A single named artifact with history."""

    heirloom_id: int
    name: str
    type_id: str            # references HeirloomTypeDef.id
    category: str           # weapon / armor / tool / relic / memorial
    creator_id: Optional[int]   # Praxan who created it (None for banner/memorial)
    creator_name: str
    created_at: float       # game time of creation
    owner_id: Optional[int]     # current bearer (None = faction vault)
    faction_id: Optional[int]   # owning faction
    legend_score: float     # accumulated legend
    is_faction_relic: bool  # promoted to faction relic
    history: list[dict[str, Any]]  # list of event dicts
    base_item: Optional[dict[str, Any]] = None  # original equipment data

    # -- Derived stats --

    def stat_bonus(self) -> float:
        """Calculate bonus from legend (capped by type def)."""
        type_def = get_heirloom_type_def(self.type_id)
        if not type_def:
            return 0.0
        per_legend = type_def.get("stat_bonus_per_legend", 0.0)
        cap = type_def.get("max_stat_bonus", 0.3)
        return min(self.legend_score * per_legend, cap)

    def cohesion_bonus(self) -> float:
        """Return cohesion bonus if this is a faction relic."""
        if not self.is_faction_relic:
            return 0.0
        type_def = get_heirloom_type_def(self.type_id)
        if not type_def:
            return 0.0
        return type_def.get("cohesion_bonus", 0.0)

    def skill_xp_bonus(self) -> float:
        """Return skill XP bonus for tools."""
        type_def = get_heirloom_type_def(self.type_id)
        if not type_def:
            return 0.0
        return type_def.get("skill_xp_bonus", 0.0) * min(self.legend_score / 50.0, 1.0)

    def add_history_event(self, event_id: str, description: str,
                          timestamp: float, related_ids: list[int] | None = None) -> None:
        event_def = get_heirloom_event_def(event_id)
        legend_value = event_def.get("legend_value", 0) if event_def else 3
        self.legend_score += legend_value
        self.history.append({
            "event_id": event_id,
            "description": description,
            "timestamp": timestamp,
            "related_ids": list(related_ids or []),
            "legend_added": legend_value,
        })
        # Cap history length to prevent unbounded growth
        if len(self.history) > 50:
            self.history = self.history[-50:]

    def generation_count(self) -> int:
        """Count how many inheritance events have occurred."""
        return sum(1 for h in self.history if h.get("event_id") == "inherited")

    def to_dict(self) -> dict[str, Any]:
        return {
            "heirloom_id": self.heirloom_id,
            "name": self.name,
            "type_id": self.type_id,
            "category": self.category,
            "creator_id": self.creator_id,
            "creator_name": self.creator_name,
            "created_at": round(self.created_at, 3),
            "owner_id": self.owner_id,
            "faction_id": self.faction_id,
            "legend_score": round(self.legend_score, 2),
            "is_faction_relic": self.is_faction_relic,
            "history": list(self.history),
            "base_item": self.base_item,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Heirloom":
        return cls(
            heirloom_id=data.get("heirloom_id", 0),
            name=data.get("name", "Unknown"),
            type_id=data.get("type_id", ""),
            category=data.get("category", ""),
            creator_id=data.get("creator_id"),
            creator_name=data.get("creator_name", ""),
            created_at=data.get("created_at", 0.0),
            owner_id=data.get("owner_id"),
            faction_id=data.get("faction_id"),
            legend_score=data.get("legend_score", 0.0),
            is_faction_relic=data.get("is_faction_relic", False),
            history=list(data.get("history", [])),
            base_item=data.get("base_item"),
        )


# ---------------------------------------------------------------------------
# Mood def helpers
# ---------------------------------------------------------------------------

_mood_def_cache: dict[str, dict[str, Any]] = {}


def _get_mood_def(mood_id: str) -> dict[str, Any]:
    """Load a MoodDef from DefDatabase."""
    if mood_id in _mood_def_cache:
        return _mood_def_cache[mood_id]
    try:
        from systems.def_database import DefDatabase
        all_moods = DefDatabase.get_all("MoodDef")
        if all_moods:
            for mid, mdata in all_moods.items():
                _mood_def_cache[mid] = mdata
    except Exception:
        pass
    return _mood_def_cache.get(mood_id, {})


# ---------------------------------------------------------------------------
# HeirloomManager
# ---------------------------------------------------------------------------

EVAL_INTERVAL = 30.0  # seconds between evaluation cycles
MAX_HEIRLOOMS_PER_FACTION = 20  # cap to prevent unbounded growth


class HeirloomManager:
    """Manages the lifecycle of all heirlooms in the simulation."""

    def __init__(self) -> None:
        self._heirlooms: dict[int, Heirloom] = {}  # heirloom_id → Heirloom
        self._last_eval_time: float = 0.0
        self._event_bus = None
        self._pending_deaths: list[dict[str, Any]] = []
        self._pending_warfare: list[dict[str, Any]] = []
        self._pending_disasters: list[dict[str, Any]] = []

    # ---- EventBus integration -----------------------------------------------

    def attach_event_bus(self, event_bus) -> None:
        self._event_bus = event_bus
        event_bus.subscribe(CATEGORY_DEATH, self._on_death)
        event_bus.subscribe(CATEGORY_WARFARE, self._on_warfare)
        event_bus.subscribe(CATEGORY_DISASTER, self._on_disaster)

    def _on_death(self, event: GameEvent) -> None:
        # Merge GameEvent direct fields + metadata so _process_deaths can find praxan_id
        entry = dict(event.metadata or {})
        if event.praxan_id is not None and "praxan_id" not in entry:
            entry["praxan_id"] = event.praxan_id
        self._pending_deaths.append(entry)

    def _on_warfare(self, event: GameEvent) -> None:
        self._pending_warfare.append(dict(event.metadata or {}))

    def _on_disaster(self, event: GameEvent) -> None:
        self._pending_disasters.append(dict(event.metadata or {}))

    # ---- Public API ---------------------------------------------------------

    def create_heirloom(
        self,
        type_id: str,
        creator_id: Optional[int],
        creator_name: str,
        faction_id: Optional[int],
        current_time: float,
        base_item: Optional[dict[str, Any]] = None,
        owner_id: Optional[int] = None,
    ) -> Optional[Heirloom]:
        """Create a new heirloom and register it."""
        type_def = get_heirloom_type_def(type_id)
        if not type_def:
            return None

        # Faction cap check
        if faction_id is not None:
            faction_count = sum(
                1 for h in self._heirlooms.values()
                if h.faction_id == faction_id
            )
            if faction_count >= MAX_HEIRLOOMS_PER_FACTION:
                return None

        category = type_def.get("category", "relic")
        name = generate_heirloom_name(category, creator_id or 0, current_time)
        legend_base = type_def.get("legend_base", 10)

        heirloom = Heirloom(
            heirloom_id=_get_next_id(),
            name=name,
            type_id=type_id,
            category=category,
            creator_id=creator_id,
            creator_name=creator_name,
            created_at=current_time,
            owner_id=owner_id if owner_id is not None else creator_id,
            faction_id=faction_id,
            legend_score=legend_base,
            is_faction_relic=type_def.get("faction_relic_threshold", 100) == 0,
            history=[],
            base_item=base_item,
        )

        heirloom.add_history_event(
            "created",
            f"Forged by {creator_name}",
            current_time,
            [creator_id] if creator_id is not None else [],
        )

        self._heirlooms[heirloom.heirloom_id] = heirloom
        _logger.info("Heirloom created: %s (%s) by %s", name, type_id, creator_name)
        return heirloom

    def get_heirloom(self, heirloom_id: int) -> Optional[Heirloom]:
        return self._heirlooms.get(heirloom_id)

    def get_all_heirlooms(self) -> dict[int, Heirloom]:
        return dict(self._heirlooms)

    def get_heirlooms_by_owner(self, owner_id: int) -> list[Heirloom]:
        return [h for h in self._heirlooms.values() if h.owner_id == owner_id]

    def get_heirlooms_by_faction(self, faction_id: int) -> list[Heirloom]:
        return [h for h in self._heirlooms.values() if h.faction_id == faction_id]

    def get_faction_relics(self, faction_id: int) -> list[Heirloom]:
        return [
            h for h in self._heirlooms.values()
            if h.faction_id == faction_id and h.is_faction_relic
        ]

    def get_faction_cohesion_bonus(self, faction_id: int) -> float:
        """Total cohesion bonus from all faction relics."""
        return sum(h.cohesion_bonus() for h in self.get_faction_relics(faction_id))

    # ---- Main update --------------------------------------------------------

    def update(
        self,
        praxans: list,
        faction_manager=None,
        reputation_manager=None,
        current_time: float = 0.0,
        advisor=None,
        narrative_panel=None,
    ) -> None:
        """Periodic evaluation — process pending events and check relic ascension."""
        if current_time - self._last_eval_time < EVAL_INTERVAL:
            return
        self._last_eval_time = current_time

        praxan_map = {p.id: p for p in praxans if getattr(p, "alive", True)}

        # Process pending deaths — trigger inheritance
        self._process_deaths(praxan_map, faction_manager, current_time,
                             advisor, narrative_panel)

        # Process pending warfare — heirloom looting
        self._process_warfare(praxan_map, current_time, narrative_panel)

        # Process pending disasters — legend growth for survivors
        self._process_disasters(praxan_map, current_time)

        # Check for relic ascension
        self._check_relic_ascension(praxan_map, current_time,
                                    advisor, narrative_panel)

        # Apply periodic effects to heirloom bearers
        self._apply_bearer_effects(praxan_map, current_time)

    # ---- Event processing ---------------------------------------------------

    def _process_deaths(self, praxan_map, faction_manager, current_time,
                        advisor, narrative_panel) -> None:
        deaths = self._pending_deaths[:]
        self._pending_deaths.clear()

        for death_data in deaths:
            dead_id = death_data.get("praxan_id") or death_data.get("id")
            if dead_id is None:
                continue

            heirlooms = [h for h in self._heirlooms.values() if h.owner_id == dead_id]
            if not heirlooms:
                continue

            cause = death_data.get("cause", "unknown")
            dead_name = death_data.get("name", f"Praxan #{dead_id}")

            for heirloom in heirlooms:
                # Legend event for heroic death
                if cause in ("combat", "battle", "raid"):
                    heirloom.add_history_event(
                        "owner_died_heroically",
                        f"{dead_name} fell in battle bearing {heirloom.name}",
                        current_time, [dead_id],
                    )

                # Find heir
                heir_id = self._find_heir(
                    dead_id, heirloom, praxan_map, faction_manager,
                )

                if heir_id is not None:
                    heir = praxan_map.get(heir_id)
                    heir_name = getattr(heir, "name", f"#{heir_id}") if heir else f"#{heir_id}"
                    self._transfer_heirloom(
                        heirloom, heir_id, current_time,
                        f"Inherited by {heir_name} after {dead_name}'s death",
                        praxan_map, narrative_panel, is_inheritance=True,
                    )
                else:
                    # Goes to faction vault (no owner)
                    heirloom.owner_id = None
                    heirloom.add_history_event(
                        "inherited",
                        f"Placed in faction vault after {dead_name}'s death",
                        current_time, [dead_id],
                    )

    def _find_heir(self, dead_id, heirloom, praxan_map, faction_manager) -> Optional[int]:
        """Find the best heir for an heirloom following type priority.

        Real praxan relationships are stored as {other_id: rel_type_str}, e.g.
        {7: "partner", 3: "child"}.  We scan living praxans to find who was
        connected to the deceased.
        """
        type_def = get_heirloom_type_def(heirloom.type_id)
        if not type_def:
            return None

        priority = type_def.get("inheritance_priority", ["child", "partner", "faction_leader"])

        # Build a candidate dict from living praxans' relationship fields.
        # Relationship format: praxan.relationships[other_id] = rel_type_str
        #   rel == "partner"  → p is dead's partner
        #   rel == "parent"   → dead_id is p's parent, so p is a child of the dead
        #   rel == "child"    → dead_id is p's child (p is the parent — not an heir)
        relationships: dict[str, list] = {}
        for p in praxan_map.values():
            rels = getattr(p, "relationships", {})
            rel_with_dead = rels.get(dead_id)
            if rel_with_dead == "partner":
                relationships.setdefault("partner", []).append(p.id)
            elif rel_with_dead == "parent":
                # dead_id was p's parent → p is a child of the deceased
                relationships.setdefault("child", []).append(p.id)

        for heir_type in priority:
            if heir_type == "partner":
                partner_ids = relationships.get("partner", [])
                for pid in partner_ids:
                    if pid in praxan_map:
                        return pid
            elif heir_type == "child":
                child_ids = relationships.get("child", [])
                for cid in child_ids:
                    if cid in praxan_map:
                        return cid
            elif heir_type == "faction_leader":
                if faction_manager and heirloom.faction_id is not None:
                    factions = getattr(faction_manager, "factions", [])
                    for faction in factions:
                        if getattr(faction, "id", None) == heirloom.faction_id:
                            leader = getattr(faction, "leader", None)
                            if leader and leader.id in praxan_map and leader.id != dead_id:
                                return leader.id
        return None

    def _process_warfare(self, praxan_map, current_time, narrative_panel) -> None:
        warfare_events = self._pending_warfare[:]
        self._pending_warfare.clear()

        for war_data in warfare_events:
            outcome = war_data.get("outcome", "")
            if outcome != "attacker_victory":
                continue

            # Warfare events use "attacker_faction" / "defender_faction" (no _id suffix)
            defender_faction = war_data.get("defender_faction") or war_data.get("defender_faction_id")
            attacker_faction = war_data.get("attacker_faction") or war_data.get("attacker_faction_id")
            if defender_faction is None or attacker_faction is None:
                continue

            # Chance to loot an heirloom from the defender
            defender_heirlooms = [
                h for h in self._heirlooms.values()
                if h.faction_id == defender_faction and not h.is_faction_relic
            ]
            if not defender_heirlooms:
                continue

            # 30% chance to loot one heirloom per raid
            if random.random() > 0.30:
                continue

            looted = random.choice(defender_heirlooms)

            # Find an attacker to receive it
            attacker_combatants = war_data.get("attacker_combatants", [])
            recipient = None
            for cid in attacker_combatants:
                if cid in praxan_map:
                    recipient = cid
                    break

            looted.add_history_event(
                "looted",
                f"Seized by faction #{attacker_faction} in a raid",
                current_time,
            )
            old_faction = looted.faction_id
            looted.faction_id = attacker_faction
            looted.owner_id = recipient

            # Apply moodlets to old faction members
            for p in praxan_map.values():
                if getattr(p, "faction_id", None) == old_faction:
                    mood = _get_mood_def("HeirloomLooted")
                    if mood:
                        p.add_moodlet(
                            "HeirloomLooted",
                            mood.get("mood_offset", -12),
                            mood.get("duration", 360),
                            current_time,
                        )

            if recipient and recipient in praxan_map:
                heir = praxan_map[recipient]
                mood = _get_mood_def("ReceivedHeirloom")
                if mood:
                    heir.add_moodlet(
                        "ReceivedHeirloom",
                        mood.get("mood_offset", 10),
                        mood.get("duration", 300),
                        current_time,
                    )
                if hasattr(heir, "episodic_memory"):
                    heir.episodic_memory.record(
                        "heirloom_received",
                        f"Seized {looted.name} as war spoils",
                    )

            if narrative_panel:
                narrative_panel.add_message(
                    f"{looted.name} seized by raiders!", "Drama",
                )

    def _process_disasters(self, praxan_map, current_time) -> None:
        disasters = self._pending_disasters[:]
        self._pending_disasters.clear()

        for disaster_data in disasters:
            # Add legend to all heirlooms whose bearers survived
            for heirloom in self._heirlooms.values():
                if heirloom.owner_id and heirloom.owner_id in praxan_map:
                    heirloom.add_history_event(
                        "survived_disaster",
                        f"Survived {disaster_data.get('type', 'a disaster')} "
                        f"with bearer",
                        current_time,
                    )

    def _check_relic_ascension(self, praxan_map, current_time,
                               advisor, narrative_panel) -> None:
        """Check if any heirloom should be promoted to faction relic."""
        for heirloom in self._heirlooms.values():
            if heirloom.is_faction_relic:
                continue
            type_def = get_heirloom_type_def(heirloom.type_id)
            if not type_def:
                continue
            threshold = type_def.get("faction_relic_threshold", 100)
            if threshold <= 0:
                continue  # already a relic from creation
            if heirloom.legend_score >= threshold:
                heirloom.is_faction_relic = True
                heirloom.add_history_event(
                    "faction_relic_ascended",
                    f"{heirloom.name} declared a treasure of faction "
                    f"#{heirloom.faction_id}",
                    current_time,
                )

                # Notify owner
                if heirloom.owner_id and heirloom.owner_id in praxan_map:
                    owner = praxan_map[heirloom.owner_id]
                    mood = _get_mood_def("HeirloomBecameRelic")
                    if mood:
                        owner.add_moodlet(
                            "HeirloomBecameRelic",
                            mood.get("mood_offset", 8),
                            mood.get("duration", 300),
                            current_time,
                        )
                    if hasattr(owner, "episodic_memory"):
                        owner.episodic_memory.record(
                            "heirloom_became_relic",
                            f"{heirloom.name} declared a faction treasure",
                        )
                    if hasattr(owner, "_pending_reputation_events"):
                        owner._pending_reputation_events.append("created_heirloom")

                # EventBus
                if self._event_bus:
                    self._event_bus.publish(GameEvent(
                        category=CATEGORY_CULTURAL_SHIFT,
                        summary=f"{heirloom.name} has become a faction relic!",
                        metadata={
                            "type": "heirloom_relic_ascension",
                            "heirloom_name": heirloom.name,
                            "heirloom_id": heirloom.heirloom_id,
                            "faction_id": heirloom.faction_id,
                            "legend_score": heirloom.legend_score,
                        },
                    ))

                if narrative_panel:
                    narrative_panel.add_message(
                        f"{heirloom.name} has become a faction relic!",
                        "Achievement",
                    )

                # Observer timeline
                if advisor and hasattr(advisor, "observer_timeline"):
                    advisor.observer_timeline.append({
                        "time": current_time,
                        "type": "heirloom_relic",
                        "detail": f"{heirloom.name} declared faction relic "
                                  f"(legend: {heirloom.legend_score:.0f})",
                    })

    def _apply_bearer_effects(self, praxan_map, current_time) -> None:
        """Apply periodic moodlets and reputation to heirloom bearers."""
        for heirloom in self._heirlooms.values():
            if heirloom.owner_id is None:
                continue
            owner = praxan_map.get(heirloom.owner_id)
            if owner is None:
                continue

            # Ancestral heirloom mood (if inherited at least once)
            if heirloom.generation_count() >= 1:
                mood = _get_mood_def("AncestralHeirloom")
                if mood:
                    owner.add_moodlet(
                        "AncestralHeirloom",
                        mood.get("mood_offset", 5),
                        mood.get("duration", 600),
                        current_time,
                    )

            # Faction relic bearer reputation
            if heirloom.is_faction_relic:
                if hasattr(owner, "_pending_reputation_events"):
                    owner._pending_reputation_events.append("holds_faction_relic")

    def _transfer_heirloom(
        self, heirloom: Heirloom, new_owner_id: int,
        current_time: float, description: str,
        praxan_map: dict, narrative_panel=None,
        is_inheritance: bool = False,
    ) -> None:
        """Transfer an heirloom to a new owner with full effects."""
        old_owner_id = heirloom.owner_id
        heirloom.owner_id = new_owner_id

        heirloom.add_history_event(
            "inherited" if is_inheritance else "inherited",
            description,
            current_time,
            [new_owner_id, old_owner_id] if old_owner_id else [new_owner_id],
        )

        # Check generation milestone
        gen = heirloom.generation_count()
        if gen > 0 and gen % 3 == 0:
            heirloom.add_history_event(
                "generation_passed",
                f"{heirloom.name} has passed through {gen} generations",
                current_time,
            )

        new_owner = praxan_map.get(new_owner_id)
        if new_owner:
            # Moodlet
            memory_cat = "heirloom_inherited" if is_inheritance else "heirloom_received"
            mood_id = "ReceivedHeirloom"
            mood = _get_mood_def(mood_id)
            if mood:
                new_owner.add_moodlet(
                    mood_id,
                    mood.get("mood_offset", 10),
                    mood.get("duration", 300),
                    current_time,
                )

            # Episodic memory
            if hasattr(new_owner, "episodic_memory"):
                new_owner.episodic_memory.record(
                    memory_cat,
                    f"Received {heirloom.name}" +
                    (f" from an ancestor" if is_inheritance else ""),
                )

            # Update faction if needed
            new_faction = getattr(new_owner, "faction_id", None)
            if new_faction is not None:
                heirloom.faction_id = new_faction

        if narrative_panel and is_inheritance:
            heir_name = getattr(new_owner, "name", f"#{new_owner_id}") if new_owner else f"#{new_owner_id}"
            narrative_panel.add_message(
                f"{heir_name} inherits {heirloom.name}", "Event",
            )

    # ---- Battle legend hook (called from warfare) ---------------------------

    def record_battle_participation(self, praxan_ids: list[int],
                                    current_time: float,
                                    battle_type: str = "raid") -> None:
        """Add legend to heirlooms carried by battle participants."""
        for heirloom in self._heirlooms.values():
            if heirloom.owner_id in praxan_ids:
                heirloom.add_history_event(
                    "used_in_battle",
                    f"Carried into {battle_type}",
                    current_time,
                    [heirloom.owner_id],
                )

    def record_colony_defense(self, defender_ids: list[int],
                              current_time: float) -> None:
        """Add legend to heirlooms carried by successful defenders."""
        for heirloom in self._heirlooms.values():
            if heirloom.owner_id in defender_ids:
                heirloom.add_history_event(
                    "defended_colony",
                    f"Carried during colony defense",
                    current_time,
                    [heirloom.owner_id],
                )

    def record_owner_luminary(self, praxan_id: int, current_time: float) -> None:
        """Add legend when an heirloom bearer becomes a luminary."""
        for heirloom in self._heirlooms.values():
            if heirloom.owner_id == praxan_id:
                heirloom.add_history_event(
                    "owner_became_luminary",
                    f"Bearer rose to Luminary status",
                    current_time,
                    [praxan_id],
                )

    # ---- Serialization ------------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        return {
            "heirlooms": {
                str(hid): h.to_dict()
                for hid, h in self._heirlooms.items()
            },
            "last_eval_time": round(self._last_eval_time, 3),
            "next_heirloom_id": _next_heirloom_id,
        }

    def restore(self, data: dict[str, Any], current_time: float = 0.0) -> None:
        global _next_heirloom_id
        self._heirlooms.clear()
        self._pending_deaths.clear()
        self._pending_warfare.clear()
        self._pending_disasters.clear()

        heirloom_data = data.get("heirlooms", {})
        for hid_str, hdata in heirloom_data.items():
            heirloom = Heirloom.from_dict(hdata)
            self._heirlooms[heirloom.heirloom_id] = heirloom

        self._last_eval_time = current_time - max(
            0.0, EVAL_INTERVAL - data.get("last_eval_time", 0.0)
        )
        saved_next = data.get("next_heirloom_id", 0)
        if saved_next > _next_heirloom_id:
            _next_heirloom_id = saved_next

    # ---- Queries for UI / inspect -------------------------------------------

    def get_heirloom_summary(self, heirloom_id: int) -> Optional[str]:
        """One-line summary for inspect drawer."""
        h = self._heirlooms.get(heirloom_id)
        if not h:
            return None
        relic_tag = " [RELIC]" if h.is_faction_relic else ""
        return (
            f"{h.name}{relic_tag} — {h.category}, legend {h.legend_score:.0f}, "
            f"{h.generation_count()} generations, created by {h.creator_name}"
        )

    def get_most_legendary(self, n: int = 5) -> list[Heirloom]:
        """Return the n most legendary heirlooms across all factions."""
        return sorted(
            self._heirlooms.values(),
            key=lambda h: h.legend_score,
            reverse=True,
        )[:n]
