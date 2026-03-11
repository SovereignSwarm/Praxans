"""
Diplomacy System — Inter-faction relations, treaties, and diplomatic actions.

Each faction pair has a DiplomaticRelation tracking standing (-100 to +100),
active treaties, and incident history. Factions autonomously take diplomatic
actions based on doctrine, ideology alignment, proximity, and trade history.

Relation tiers:
    Allied    (standing > 60)   — shared goals, mutual defense, bonus trade
    Friendly  (standing > 20)   — open trade, no hostility
    Neutral   (-20..20)         — default, cautious
    Tense     (standing < -20)  — reduced trade, border friction
    Hostile   (standing < -60)  — no trade, active rivalry

Integration:
    - Called from FactionManager after faction refresh (every 10s)
    - Replaces hardcoded _update_rivalries with standing-based rivalry
    - Feeds TradeSystem: only Neutral+ factions can trade
    - Publishes GameEvents via EventBus for CATEGORY_DIPLOMACY
    - Serialized in run snapshots for save/load
"""
from __future__ import annotations

import time
import random
import logging
from collections import defaultdict

logger = logging.getLogger("Diplomacy")

# ---------------------------------------------------------------------------
# Relation tiers
# ---------------------------------------------------------------------------
TIER_ALLIED = "allied"
TIER_FRIENDLY = "friendly"
TIER_NEUTRAL = "neutral"
TIER_TENSE = "tense"
TIER_HOSTILE = "hostile"

TIER_THRESHOLDS = {
    TIER_ALLIED: 60,
    TIER_FRIENDLY: 20,
    TIER_NEUTRAL: -20,   # >= -20
    TIER_TENSE: -60,     # >= -60
    # Below -60 is hostile
}

def standing_to_tier(standing: float) -> str:
    if standing > 60:
        return TIER_ALLIED
    if standing > 20:
        return TIER_FRIENDLY
    if standing >= -20:
        return TIER_NEUTRAL
    if standing >= -60:
        return TIER_TENSE
    return TIER_HOSTILE

TIER_LABELS = {
    TIER_ALLIED: "Allied",
    TIER_FRIENDLY: "Friendly",
    TIER_NEUTRAL: "Neutral",
    TIER_TENSE: "Tense",
    TIER_HOSTILE: "Hostile",
}

# ---------------------------------------------------------------------------
# Treaty types
# ---------------------------------------------------------------------------
TREATY_TRADE = "trade_agreement"
TREATY_NAP = "non_aggression_pact"
TREATY_ALLIANCE = "alliance"

TREATY_LABELS = {
    TREATY_TRADE: "Trade Agreement",
    TREATY_NAP: "Non-Aggression Pact",
    TREATY_ALLIANCE: "Alliance",
}

# Standing requirements to propose each treaty type
TREATY_STANDING_REQ = {
    TREATY_TRADE: 0,
    TREATY_NAP: -10,
    TREATY_ALLIANCE: 40,
}

# Duration in seconds
TREATY_DURATION = {
    TREATY_TRADE: 120.0,
    TREATY_NAP: 90.0,
    TREATY_ALLIANCE: 180.0,
}

# Standing bonus per tick while treaty is active
TREATY_STANDING_BONUS = {
    TREATY_TRADE: 0.3,
    TREATY_NAP: 0.15,
    TREATY_ALLIANCE: 0.5,
}


# ---------------------------------------------------------------------------
# Diplomatic Incidents (random events that shift relations)
# ---------------------------------------------------------------------------
DIPLOMATIC_INCIDENTS = [
    {
        "id": "border_dispute",
        "label": "Border Dispute",
        "standing_delta": -12,
        "requires_proximity": True,
        "description": "Territorial friction sparks a diplomatic incident.",
    },
    {
        "id": "cultural_exchange",
        "label": "Cultural Exchange",
        "standing_delta": 10,
        "requires_proximity": True,
        "description": "Members from both factions share knowledge and customs.",
    },
    {
        "id": "resource_theft",
        "label": "Resource Theft",
        "standing_delta": -18,
        "requires_proximity": True,
        "description": "One faction accuses the other of stealing resources.",
    },
    {
        "id": "diplomatic_gift",
        "label": "Diplomatic Gift",
        "standing_delta": 14,
        "requires_proximity": False,
        "description": "A faction sends a gift to improve relations.",
    },
    {
        "id": "insult",
        "label": "Diplomatic Insult",
        "standing_delta": -8,
        "requires_proximity": False,
        "description": "A leader's remarks offend the other faction.",
    },
    {
        "id": "joint_feast",
        "label": "Joint Feast",
        "standing_delta": 16,
        "requires_proximity": True,
        "description": "Both factions celebrate together, strengthening bonds.",
    },
    {
        "id": "ideological_clash",
        "label": "Ideological Clash",
        "standing_delta": -10,
        "requires_proximity": False,
        "description": "Doctrinal differences cause a public disagreement.",
    },
]


# ---------------------------------------------------------------------------
# DiplomaticRelation
# ---------------------------------------------------------------------------
class DiplomaticRelation:
    """Tracks the diplomatic state between two factions."""

    __slots__ = (
        "faction_a_id", "faction_b_id", "standing", "treaties",
        "incident_log", "last_incident_time", "trade_count",
        "tier_changed_time",
    )

    def __init__(self, faction_a_id: int, faction_b_id: int, initial_standing: float = 0.0):
        self.faction_a_id = min(faction_a_id, faction_b_id)
        self.faction_b_id = max(faction_a_id, faction_b_id)
        self.standing = max(-100.0, min(100.0, initial_standing))
        self.treaties: list[dict] = []  # [{type, started_at, expires_at}]
        self.incident_log: list[dict] = []  # [{id, label, delta, time}] capped at 10
        self.last_incident_time = 0.0
        self.trade_count = 0  # trades completed between these factions
        self.tier_changed_time = 0.0

    @property
    def tier(self) -> str:
        return standing_to_tier(self.standing)

    @property
    def tier_label(self) -> str:
        return TIER_LABELS.get(self.tier, "Unknown")

    def shift_standing(self, delta: float, current_time: float = 0.0):
        """Shift standing by delta, clamped to [-100, 100]."""
        old_tier = self.tier
        self.standing = max(-100.0, min(100.0, self.standing + delta))
        new_tier = self.tier
        if old_tier != new_tier:
            self.tier_changed_time = current_time
        return old_tier != new_tier

    def add_treaty(self, treaty_type: str, current_time: float):
        """Add a treaty if not already active."""
        if self.has_treaty(treaty_type):
            return False
        if self.standing < TREATY_STANDING_REQ.get(treaty_type, 0):
            return False
        self.treaties.append({
            "type": treaty_type,
            "started_at": current_time,
            "expires_at": current_time + TREATY_DURATION.get(treaty_type, 120.0),
        })
        return True

    def has_treaty(self, treaty_type: str) -> bool:
        return any(t["type"] == treaty_type for t in self.treaties)

    def expire_treaties(self, current_time: float) -> list[str]:
        """Remove expired treaties, return list of expired treaty types."""
        expired = [t["type"] for t in self.treaties if current_time >= t["expires_at"]]
        self.treaties = [t for t in self.treaties if current_time < t["expires_at"]]
        return expired

    def record_incident(self, incident_id: str, label: str, delta: float, current_time: float):
        self.incident_log.append({
            "id": incident_id,
            "label": label,
            "delta": round(delta, 1),
            "time": round(current_time, 3),
        })
        if len(self.incident_log) > 10:
            del self.incident_log[:-10]
        self.last_incident_time = current_time

    def record_trade(self):
        """Record a successful trade between these factions."""
        self.trade_count += 1

    def can_trade(self) -> bool:
        """Whether these factions are allowed to trade."""
        return self.standing >= -20  # Neutral or better

    def serialize(self, current_time: float | None = None) -> dict:
        if current_time is None:
            current_time = time.time()
        active_treaties = []
        for t in self.treaties:
            remaining = t["expires_at"] - current_time
            if remaining > 0:
                active_treaties.append({
                    "type": t["type"],
                    "remaining_seconds": round(remaining, 3),
                })
        return {
            "faction_a_id": self.faction_a_id,
            "faction_b_id": self.faction_b_id,
            "standing": round(self.standing, 2),
            "tier": self.tier,
            "treaties": active_treaties,
            "incident_log": list(self.incident_log[-5:]),
            "trade_count": self.trade_count,
            "last_incident_elapsed": round(
                max(0.0, current_time - self.last_incident_time), 3
            ) if self.last_incident_time > 0 else 0.0,
        }


# ---------------------------------------------------------------------------
# DiplomacyManager
# ---------------------------------------------------------------------------
class DiplomacyManager:
    """Manages all inter-faction diplomatic relations."""

    UPDATE_INTERVAL = 10.0       # Seconds between diplomacy ticks
    INCIDENT_COOLDOWN = 25.0     # Min seconds between incidents for a pair
    INCIDENT_CHANCE = 0.12       # Chance per faction pair per tick
    STANDING_DECAY_RATE = 0.15   # Per tick, toward neutral
    PROXIMITY_THRESHOLD = 250    # Pixels — factions closer than this have proximity effects
    SCHISM_INITIAL_STANDING = -35.0  # Standing when a faction splits from another

    def __init__(self):
        self.relations: dict[tuple[int, int], DiplomaticRelation] = {}
        self.last_update_time = 0.0
        self.diplomatic_log: list[dict] = []  # Recent diplomatic events, capped
        self._max_log = 20

    def _key(self, fid_a: int, fid_b: int) -> tuple[int, int]:
        return (min(fid_a, fid_b), max(fid_a, fid_b))

    def get_relation(self, fid_a: int, fid_b: int) -> DiplomaticRelation:
        """Get or create the relation between two factions."""
        key = self._key(fid_a, fid_b)
        if key not in self.relations:
            self.relations[key] = DiplomaticRelation(key[0], key[1])
        return self.relations[key]

    def set_initial_standing(self, fid_a: int, fid_b: int, standing: float):
        """Set initial standing for a new faction pair (e.g. after schism)."""
        rel = self.get_relation(fid_a, fid_b)
        rel.standing = max(-100.0, min(100.0, standing))

    def register_schism(self, parent_faction_id: int, child_faction_id: int, current_time: float):
        """Register a schism: the new faction starts hostile to its parent."""
        rel = self.get_relation(parent_faction_id, child_faction_id)
        rel.standing = self.SCHISM_INITIAL_STANDING
        rel.tier_changed_time = current_time
        self._log_event(current_time, "schism_hostility",
                        f"F{child_faction_id} broke away from F{parent_faction_id}",
                        parent_faction_id, child_faction_id)

    def register_trade(self, fid_a: int, fid_b: int, current_time: float):
        """Record a successful trade — improves standing slightly."""
        rel = self.get_relation(fid_a, fid_b)
        rel.record_trade()
        rel.shift_standing(1.5, current_time)

    def update(self, faction_manager, praxans, current_time: float, event_bus=None, advisor=None):
        """Run a full diplomacy tick: decay, treaties, incidents, autonomous actions."""
        if current_time - self.last_update_time < self.UPDATE_INTERVAL:
            return
        self.last_update_time = current_time

        if faction_manager is None:
            return

        factions = faction_manager.factions
        faction_ids = list(factions.keys())

        if len(faction_ids) < 2:
            return

        # Clean up relations for dissolved factions
        self._cleanup_dissolved(faction_ids)

        # Precompute faction centroids
        centroids = {}
        for fid in faction_ids:
            centroids[fid] = factions[fid].get_centroid(praxans)

        # Process each pair
        for i, fid_a in enumerate(faction_ids):
            for fid_b in faction_ids[i + 1:]:
                rel = self.get_relation(fid_a, fid_b)

                # 1. Expire treaties
                expired = rel.expire_treaties(current_time)
                for treaty_type in expired:
                    self._log_event(current_time, "treaty_expired",
                                    f"{TREATY_LABELS.get(treaty_type, treaty_type)} between F{fid_a} and F{fid_b} expired",
                                    fid_a, fid_b)
                    if event_bus is not None:
                        self._publish_event(event_bus, current_time,
                                            f"{TREATY_LABELS.get(treaty_type, treaty_type)} expired",
                                            f"Agreement between F{fid_a} and F{fid_b} has lapsed.",
                                            fid_a)

                # 2. Apply treaty standing bonuses
                for treaty in rel.treaties:
                    bonus = TREATY_STANDING_BONUS.get(treaty["type"], 0.1)
                    rel.shift_standing(bonus, current_time)

                # 3. Ideology alignment modifier
                ideology_delta = self._compute_ideology_affinity(
                    factions[fid_a], factions[fid_b]
                )
                rel.shift_standing(ideology_delta * 0.3, current_time)

                # 4. Proximity friction/bonding
                dist = self._faction_distance(centroids.get(fid_a), centroids.get(fid_b))
                if dist is not None and dist < self.PROXIMITY_THRESHOLD:
                    # Close factions experience friction if tense, bonding if friendly
                    if rel.standing < -10:
                        rel.shift_standing(-0.3, current_time)  # friction
                    elif rel.standing > 10:
                        rel.shift_standing(0.2, current_time)  # bonding

                # 5. Standing decay toward neutral
                if abs(rel.standing) > 5:
                    decay = self.STANDING_DECAY_RATE if rel.standing > 0 else -self.STANDING_DECAY_RATE
                    rel.shift_standing(-decay, current_time)

                # 6. Random diplomatic incidents
                if (current_time - rel.last_incident_time > self.INCIDENT_COOLDOWN
                        and random.random() < self.INCIDENT_CHANCE):
                    self._trigger_incident(rel, fid_a, fid_b, dist, current_time,
                                           event_bus, advisor)

                # 7. Autonomous diplomatic actions (doctrine-driven)
                self._autonomous_action(rel, factions[fid_a], factions[fid_b],
                                        fid_a, fid_b, current_time, event_bus)

        # 8. Update faction rivalry lists based on standing
        self._sync_rivalries(faction_manager, faction_ids)

    def _cleanup_dissolved(self, active_faction_ids: list[int]):
        """Remove relations for factions that no longer exist."""
        active_set = set(active_faction_ids)
        to_remove = [
            key for key in self.relations
            if key[0] not in active_set or key[1] not in active_set
        ]
        for key in to_remove:
            del self.relations[key]

    def _compute_ideology_affinity(self, faction_a, faction_b) -> float:
        """Return a -1..1 score of how aligned two factions' ideologies are.

        Positive = similar ideology, negative = divergent.
        """
        axes = ("growth", "security", "industry", "exploration", "harmony")
        total_diff = 0.0
        for axis in axes:
            val_a = faction_a.ideology.get(axis, 0.0)
            val_b = faction_b.ideology.get(axis, 0.0)
            total_diff += abs(val_a - val_b)
        # Normalize: max total_diff is ~5.0 (each axis 0..1)
        # Map to -1..1: 0 diff = +1 affinity, 2.5 diff = 0, 5.0 diff = -1
        affinity = 1.0 - (total_diff / 2.5)
        return max(-1.0, min(1.0, affinity))

    def _faction_distance(self, centroid_a, centroid_b) -> float | None:
        if centroid_a is None or centroid_b is None:
            return None
        dx = centroid_a[0] - centroid_b[0]
        dy = centroid_a[1] - centroid_b[1]
        return (dx * dx + dy * dy) ** 0.5

    def _trigger_incident(self, rel, fid_a, fid_b, dist, current_time,
                          event_bus, advisor):
        """Trigger a random diplomatic incident between two factions."""
        is_proximate = dist is not None and dist < self.PROXIMITY_THRESHOLD

        candidates = [
            inc for inc in DIPLOMATIC_INCIDENTS
            if not inc["requires_proximity"] or is_proximate
        ]
        if not candidates:
            return

        # Weight selection: negative incidents more likely when tense,
        # positive incidents more likely when friendly
        weights = []
        for inc in candidates:
            w = 1.0
            if inc["standing_delta"] < 0 and rel.standing < 0:
                w = 1.5  # escalation bias
            elif inc["standing_delta"] > 0 and rel.standing > 0:
                w = 1.3  # reinforcement bias
            elif inc["standing_delta"] > 0 and rel.standing < -30:
                w = 0.5  # harder to improve very bad relations
            weights.append(w)

        incident = random.choices(candidates, weights=weights, k=1)[0]
        delta = incident["standing_delta"]
        tier_changed = rel.shift_standing(delta, current_time)
        rel.record_incident(incident["id"], incident["label"], delta, current_time)

        self._log_event(current_time, incident["id"],
                        f"{incident['label']} between F{fid_a} and F{fid_b} ({delta:+.0f})",
                        fid_a, fid_b)

        if event_bus is not None:
            self._publish_event(
                event_bus, current_time,
                f"{incident['label']}: F{fid_a} & F{fid_b}",
                f"{incident['description']} Standing: {rel.standing:.0f} ({rel.tier_label})",
                fid_a,
            )

        if tier_changed and advisor is not None:
            try:
                from praxans_game import record_observer_timeline_event
                record_observer_timeline_event(
                    advisor, current_time, "diplomacy",
                    f"F{fid_a}-F{fid_b} relations shifted to {rel.tier_label}",
                    f"Standing {rel.standing:.0f}. Triggered by: {incident['label']}.",
                )
            except ImportError:
                pass

    def _autonomous_action(self, rel, faction_a, faction_b, fid_a, fid_b,
                           current_time, event_bus):
        """Factions autonomously propose treaties based on doctrine and standing."""
        # Only act every ~30s per pair (use tier_changed_time as rough throttle)
        if current_time - rel.tier_changed_time < 30.0 and rel.treaties:
            return

        # Harmony-doctrine factions are more diplomatic
        a_diplomatic = faction_a.primary_doctrine in ("harmony", "growth")
        b_diplomatic = faction_b.primary_doctrine in ("harmony", "growth")

        # Try to propose alliance if standing high enough
        if rel.standing > 50 and (a_diplomatic or b_diplomatic):
            if not rel.has_treaty(TREATY_ALLIANCE):
                if rel.add_treaty(TREATY_ALLIANCE, current_time):
                    self._log_event(current_time, "alliance_formed",
                                    f"F{fid_a} and F{fid_b} formed an Alliance",
                                    fid_a, fid_b)
                    if event_bus is not None:
                        self._publish_event(event_bus, current_time,
                                            f"Alliance: F{fid_a} & F{fid_b}",
                                            "Two factions formalize their bond into a mutual defense pact.",
                                            fid_a)
                    return

        # Trade agreement if standing neutral+
        if rel.standing > 5 and not rel.has_treaty(TREATY_TRADE):
            # Industry/growth factions more likely to propose trade
            if faction_a.primary_doctrine in ("industry", "growth") or \
               faction_b.primary_doctrine in ("industry", "growth") or \
               random.random() < 0.3:
                if rel.add_treaty(TREATY_TRADE, current_time):
                    self._log_event(current_time, "trade_agreement",
                                    f"F{fid_a} and F{fid_b} signed a Trade Agreement",
                                    fid_a, fid_b)
                    if event_bus is not None:
                        self._publish_event(event_bus, current_time,
                                            f"Trade Agreement: F{fid_a} & F{fid_b}",
                                            "Resources will flow more freely between these factions.",
                                            fid_a)
                    return

        # NAP if tense but not hostile (de-escalation)
        if -40 < rel.standing < -5 and not rel.has_treaty(TREATY_NAP):
            if a_diplomatic or b_diplomatic:
                if rel.add_treaty(TREATY_NAP, current_time):
                    self._log_event(current_time, "nap_signed",
                                    f"F{fid_a} and F{fid_b} signed a Non-Aggression Pact",
                                    fid_a, fid_b)
                    if event_bus is not None:
                        self._publish_event(event_bus, current_time,
                                            f"NAP: F{fid_a} & F{fid_b}",
                                            "Both factions agree to a period of non-aggression.",
                                            fid_a)
                    return

    def _sync_rivalries(self, faction_manager, faction_ids):
        """Update faction.rival_faction_ids based on diplomatic standing."""
        factions = faction_manager.factions
        for fid in faction_ids:
            faction = factions[fid]
            rivals = []
            for other_fid in faction_ids:
                if other_fid == fid:
                    continue
                rel = self.get_relation(fid, other_fid)
                if rel.tier in (TIER_HOSTILE, TIER_TENSE):
                    rivals.append(other_fid)
            faction.rival_faction_ids = rivals

    def _publish_event(self, event_bus, current_time, summary, detail, faction_id):
        """Publish a diplomacy event to the event bus."""
        try:
            from events.bus import GameEvent, CATEGORY_DIPLOMACY
            event_bus.publish(GameEvent(
                category=CATEGORY_DIPLOMACY,
                summary=summary,
                detail=detail,
                faction_id=faction_id,
                timestamp=current_time,
            ))
        except ImportError:
            pass

    def _log_event(self, current_time, event_type, description, fid_a, fid_b):
        """Add to internal diplomatic log."""
        self.diplomatic_log.append({
            "time": round(current_time, 3),
            "type": event_type,
            "description": description,
            "factions": [fid_a, fid_b],
        })
        if len(self.diplomatic_log) > self._max_log:
            del self.diplomatic_log[:-self._max_log]

    # ---- Query methods for UI / LLM ----------------------------------------

    def get_faction_relations_summary(self, faction_id: int) -> list[dict]:
        """Get a summary of all relations for a faction (for inspect drawer)."""
        summaries = []
        for key, rel in self.relations.items():
            if faction_id not in key:
                continue
            other_id = key[1] if key[0] == faction_id else key[0]
            treaty_names = [TREATY_LABELS.get(t["type"], t["type"]) for t in rel.treaties]
            summaries.append({
                "faction_id": other_id,
                "standing": round(rel.standing, 1),
                "tier": rel.tier_label,
                "treaties": treaty_names,
                "trade_count": rel.trade_count,
            })
        summaries.sort(key=lambda s: -s["standing"])
        return summaries

    def get_all_relations_for_llm(self) -> list[str]:
        """Return human-readable summaries for the LLM advisor."""
        lines = []
        for key, rel in self.relations.items():
            treaty_str = ""
            if rel.treaties:
                names = [TREATY_LABELS.get(t["type"], t["type"]) for t in rel.treaties]
                treaty_str = f" [{', '.join(names)}]"
            lines.append(
                f"F{key[0]}-F{key[1]}: {rel.tier_label} ({rel.standing:+.0f}){treaty_str}"
            )
        return lines[:8]

    def get_recent_incidents(self, count: int = 5) -> list[dict]:
        """Return the most recent diplomatic incidents across all pairs."""
        all_incidents = []
        for rel in self.relations.values():
            for inc in rel.incident_log:
                inc_copy = dict(inc)
                inc_copy["factions"] = [rel.faction_a_id, rel.faction_b_id]
                all_incidents.append(inc_copy)
        all_incidents.sort(key=lambda x: x.get("time", 0))
        return all_incidents[-count:]

    # ---- Serialization ------------------------------------------------------

    def serialize(self, current_time: float | None = None) -> dict:
        if current_time is None:
            current_time = time.time()
        return {
            "relations": [rel.serialize(current_time) for rel in self.relations.values()],
            "diplomatic_log": list(self.diplomatic_log[-10:]),
        }

    def deserialize(self, data: dict):
        """Restore diplomacy state from snapshot."""
        if not data or not isinstance(data, dict):
            return
        now = time.time()
        self.relations.clear()
        relations_data = data.get("relations", [])
        if not isinstance(relations_data, list):
            relations_data = []

        for rel_data in relations_data:
            if not isinstance(rel_data, dict):
                continue
            try:
                fid_a = int(rel_data.get("faction_a_id", 0))
                fid_b = int(rel_data.get("faction_b_id", 0))
            except (TypeError, ValueError):
                continue
            try:
                standing = float(rel_data.get("standing", 0.0))
            except (TypeError, ValueError):
                standing = 0.0
            rel = DiplomaticRelation(fid_a, fid_b, standing)
            # Rebase treaty expiry timestamps to current wall clock.
            # Old snapshots stored absolute {expires_at}; new ones store {remaining_seconds}.
            rel.treaties = []
            treaties_data = rel_data.get("treaties", [])
            if not isinstance(treaties_data, list):
                treaties_data = []
            for t in treaties_data:
                if not isinstance(t, dict):
                    continue
                treaty_type = t.get("type")
                if not isinstance(treaty_type, str) or not treaty_type:
                    continue
                if "remaining_seconds" in t:
                    try:
                        remaining = float(t["remaining_seconds"])
                    except (TypeError, ValueError):
                        remaining = 0.0
                elif "expires_at" in t:
                    try:
                        remaining = float(t["expires_at"]) - now  # legacy format
                    except (TypeError, ValueError):
                        remaining = 0.0
                else:
                    remaining = 0.0
                if remaining > 0:
                    rel.treaties.append({
                        "type": treaty_type,
                        "started_at": now,
                        "expires_at": now + remaining,
                    })
            incidents_data = rel_data.get("incident_log", [])
            rel.incident_log = list(incidents_data) if isinstance(incidents_data, list) else []
            try:
                rel.trade_count = int(rel_data.get("trade_count", 0))
            except (TypeError, ValueError):
                rel.trade_count = 0
            # Rebase last_incident_time to prevent a burst of incidents immediately after load.
            try:
                last_incident_elapsed = float(rel_data.get("last_incident_elapsed", 0.0))
            except (TypeError, ValueError):
                last_incident_elapsed = 0.0
            if last_incident_elapsed > 0:
                rel.last_incident_time = now - last_incident_elapsed
            self.relations[self._key(fid_a, fid_b)] = rel
        log_data = data.get("diplomatic_log", [])
        self.diplomatic_log = list(log_data) if isinstance(log_data, list) else []
