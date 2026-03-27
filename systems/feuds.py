"""Feuds & Grudges System — persistent interpersonal conflict between Praxans.

Unlike diplomacy (faction-to-faction standing), feuds track grudges between
individual Praxans.  Grudges accumulate from insults, arguments, heirloom
theft, betrayal (defection), kin-slaying, and leadership disputes.  Each
grudge-pair has a total weight that determines the feud **stage** — from
simmering resentment through open hostility, vendetta, and blood feud.

Each stage applies escalating effects: moodlets, opinion drift, social
avoidance, insult-chance boosts, cohesion/diplomacy penalties, and at the
extreme, physical confrontation.  Grudges decay over time (personality-
weighted), and feuds can resolve when weight falls below the minimum threshold.

Definitions live in ``defs/core/feuds.json`` (defTypes ``GrudgeDef`` and
``FeudStageDef``) and are loaded via ``DefDatabase``.

Integration:
    - ``FeudsManager.update()`` called on rare-tick cadence
    - ``FeudsManager.record_grudge(holder_id, target_id, grudge_id)``
      called by other systems (social interactions, warfare, migration)
    - EventBus subscription for auto-recording from PERSONAL / WARFARE /
      MIGRATION events
    - Snapshot: ``serialize()`` / ``restore()``
"""

from __future__ import annotations

import random
import time
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Def caches (lazily loaded from DefDatabase)
# ---------------------------------------------------------------------------

_grudge_def_cache: dict[str, dict[str, Any]] = {}
_stage_def_cache: list[dict[str, Any]] = []


def _load_defs() -> None:
    """Populate caches from DefDatabase."""
    global _grudge_def_cache, _stage_def_cache
    if _grudge_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        grudge_defs = DefDatabase.get_all("GrudgeDef")
        if grudge_defs:
            if isinstance(grudge_defs, dict):
                _grudge_def_cache.update(grudge_defs)
            elif isinstance(grudge_defs, list):
                for d in grudge_defs:
                    if isinstance(d, dict) and "id" in d:
                        _grudge_def_cache[d["id"]] = d
        stage_defs = DefDatabase.get_all("FeudStageDef")
        if stage_defs:
            stages = stage_defs.values() if isinstance(stage_defs, dict) else stage_defs
            _stage_def_cache = sorted(
                stages,
                key=lambda s: s.get("severity", 0),
                reverse=True,
            )
    except Exception:
        pass


def get_grudge_def(grudge_id: str) -> Optional[dict[str, Any]]:
    _load_defs()
    return _grudge_def_cache.get(grudge_id)


def get_all_grudge_defs() -> dict[str, dict[str, Any]]:
    _load_defs()
    return dict(_grudge_def_cache)


def get_stage_for_weight(total_weight: float) -> Optional[dict[str, Any]]:
    """Return the FeudStageDef matching *total_weight*, or None if below min."""
    _load_defs()
    for stage in _stage_def_cache:  # sorted descending by severity
        if total_weight >= stage.get("min_grudge_weight", 999):
            return stage
    return None


def clear_cache() -> None:
    global _grudge_def_cache, _stage_def_cache
    _grudge_def_cache = {}
    _stage_def_cache = []


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVAL_INTERVAL: float = 15.0      # seconds between feud evaluations
DECAY_INTERVAL: float = 30.0     # seconds between grudge decay passes
MAX_FEUDS_PER_PRAXAN: int = 5    # cap to prevent runaway grudge accumulation


# ---------------------------------------------------------------------------
# Feud pair key helper
# ---------------------------------------------------------------------------

def _pair_key(a_id: int, b_id: int) -> tuple[int, int]:
    """Canonical ordered pair key so (a,b) == (b,a) for feud lookups."""
    return (min(a_id, b_id), max(a_id, b_id))


# ---------------------------------------------------------------------------
# FeudsManager
# ---------------------------------------------------------------------------

class FeudsManager:
    """Manages grudges and feuds between individual Praxans.

    Typical lifecycle::

        mgr = FeudsManager()
        mgr.attach_event_bus(event_bus)
        # Other systems queue grudge events:
        mgr.record_grudge(holder_id, target_id, "insult_grudge")
        # On rare tick:
        mgr.update(praxans, faction_manager, diplomacy_manager, event_bus, current_time)
    """

    def __init__(self) -> None:
        # {(holder_id, target_id): [{grudge_id, weight, timestamp}, ...]}
        # Note: directed — holder bears grudge against target
        self._grudges: dict[tuple[int, int], list[dict[str, Any]]] = {}
        # {pair_key: stage_id} for detecting stage transitions
        self._stages: dict[tuple[int, int], str] = {}
        self._last_eval_time: float = 0.0
        self._last_decay_time: float = 0.0
        self._event_bus: Any = None

    # ---- EventBus auto-subscription ---------------------------------------

    def attach_event_bus(self, event_bus: Any) -> None:
        """Subscribe to EventBus categories to auto-record grudges."""
        self._event_bus = event_bus
        if event_bus is None:
            return
        try:
            from events.bus import CATEGORY_PERSONAL, CATEGORY_WARFARE, CATEGORY_MIGRATION
            event_bus.subscribe(CATEGORY_PERSONAL, self._on_personal_event)
            event_bus.subscribe(CATEGORY_WARFARE, self._on_warfare_event)
            event_bus.subscribe(CATEGORY_MIGRATION, self._on_migration_event)
        except Exception:
            pass

    def _on_personal_event(self, event: Any) -> None:
        """React to social interaction events (insults, arguments)."""
        data = getattr(event, "data", None) or getattr(event, "metadata", {}) or {}
        interaction = data.get("interaction")
        initiator = data.get("initiator")
        target = data.get("target")
        if initiator is None or target is None:
            return
        if interaction == "insult":
            self.record_grudge(target, initiator, "insult_grudge")
        elif interaction == "argument":
            self.record_grudge(initiator, target, "argument_grudge")
            self.record_grudge(target, initiator, "argument_grudge")

    def _on_warfare_event(self, event: Any) -> None:
        """React to warfare events (kin killed, heirloom looted)."""
        data = getattr(event, "data", None) or getattr(event, "metadata", {}) or {}
        sub_type = data.get("sub_type", "")
        # Kin slayer grudge: family member of the deceased vs the killer
        if sub_type == "combat_kill":
            killer_id = data.get("killer_id")
            victim_id = data.get("victim_id")
            kin_ids = data.get("victim_kin_ids", [])
            if killer_id is not None:
                for kin_id in kin_ids:
                    if isinstance(kin_id, int) and kin_id != killer_id:
                        self.record_grudge(kin_id, killer_id, "kin_slayer_grudge")
        # Heirloom theft grudge
        if sub_type == "heirloom_looted":
            owner_id = data.get("owner_id")
            looter_id = data.get("looter_id")
            if owner_id is not None and looter_id is not None:
                self.record_grudge(owner_id, looter_id, "heirloom_theft_grudge")

    def _on_migration_event(self, event: Any) -> None:
        """React to migration/defection — betrayal grudge for friends/family."""
        data = getattr(event, "data", None) or getattr(event, "metadata", {}) or {}
        sub_type = data.get("sub_type", "")
        if sub_type in ("defected", "defection"):
            defector_id = data.get("praxan_id") or data.get("defector_id")
            affected_ids = data.get("affected_friend_ids", []) + data.get("affected_family_ids", [])
            if defector_id is not None:
                for pid in affected_ids:
                    if isinstance(pid, int) and pid != defector_id:
                        self.record_grudge(pid, defector_id, "betrayal_grudge")

    # ---- public API -------------------------------------------------------

    def record_grudge(
        self,
        holder_id: int,
        target_id: int,
        grudge_id: str,
        multiplier: float = 1.0,
    ) -> float:
        """Record a grudge from *holder* against *target*.

        Returns the weight added (after personality scaling). Returns 0 if
        the grudge def is unknown or the cap is reached.
        """
        if holder_id == target_id:
            return 0.0

        gdef = get_grudge_def(grudge_id)
        if gdef is None:
            return 0.0

        # Cap check
        directed_key = (holder_id, target_id)
        existing = self._grudges.get(directed_key, [])
        if len(existing) >= 20:  # hard cap per directed pair
            return 0.0

        # Personality-weighted base weight
        base_weight = gdef.get("weight", 10) * multiplier
        weight = base_weight  # personality scaling applied in update() via holder's traits

        entry = {
            "grudge_id": grudge_id,
            "weight": weight,
            "timestamp": time.time(),
        }

        if directed_key not in self._grudges:
            self._grudges[directed_key] = []
        self._grudges[directed_key].append(entry)

        return weight

    def get_total_weight(self, holder_id: int, target_id: int) -> float:
        """Return the total grudge weight holder bears against target."""
        entries = self._grudges.get((holder_id, target_id), [])
        return sum(e.get("weight", 0) for e in entries)

    def get_feud_stage(self, holder_id: int, target_id: int) -> Optional[dict[str, Any]]:
        """Return the current FeudStageDef for this directed grudge pair, or None."""
        weight = self.get_total_weight(holder_id, target_id)
        return get_stage_for_weight(weight)

    def get_feud_stage_id(self, holder_id: int, target_id: int) -> Optional[str]:
        """Return the stage id or None."""
        stage = self.get_feud_stage(holder_id, target_id)
        return stage.get("id") if stage else None

    def get_all_feuds_for(self, praxan_id: int) -> list[dict[str, Any]]:
        """Return all active feuds involving *praxan_id* as holder.

        Each entry: {target_id, total_weight, stage_id, stage_label}.
        """
        result = []
        for (h_id, t_id), entries in self._grudges.items():
            if h_id != praxan_id:
                continue
            total = sum(e.get("weight", 0) for e in entries)
            if total <= 0:
                continue
            stage = get_stage_for_weight(total)
            result.append({
                "target_id": t_id,
                "total_weight": round(total, 1),
                "stage_id": stage.get("id") if stage else None,
                "stage_label": stage.get("label") if stage else None,
                "grudge_count": len(entries),
            })
        return result

    def has_feud_with(self, holder_id: int, target_id: int) -> bool:
        """Return True if holder has an active feud (any stage) against target."""
        return self.get_feud_stage(holder_id, target_id) is not None

    def should_avoid_socially(self, praxan_id: int, other_id: int) -> bool:
        """Return True if praxan should avoid social interaction with other.

        Checks both directions — either party having social_avoidance blocks.
        """
        for h, t in [(praxan_id, other_id), (other_id, praxan_id)]:
            stage = self.get_feud_stage(h, t)
            if stage and stage.get("effects", {}).get("social_avoidance"):
                return True
        return False

    def get_insult_chance_boost(self, holder_id: int, target_id: int) -> float:
        """Return the insult_chance from the feud stage (0.0 if none)."""
        stage = self.get_feud_stage(holder_id, target_id)
        if stage:
            return stage.get("effects", {}).get("insult_chance", 0.0)
        return 0.0

    def remove_praxan(self, praxan_id: int) -> None:
        """Clean up all grudges involving a dead praxan."""
        keys_to_remove = [
            k for k in self._grudges
            if k[0] == praxan_id or k[1] == praxan_id
        ]
        for k in keys_to_remove:
            del self._grudges[k]
        # Clean stage cache
        pair_keys_to_remove = [
            k for k in self._stages
            if k[0] == praxan_id or k[1] == praxan_id
        ]
        for k in pair_keys_to_remove:
            del self._stages[k]

    # ---- rare-tick update --------------------------------------------------

    def update(
        self,
        praxans: list,
        faction_manager: Any = None,
        diplomacy_manager: Any = None,
        event_bus: Any = None,
        current_time: float | None = None,
    ) -> None:
        """Evaluate feud stages, apply effects, decay grudges.

        Called on rare-tick cadence (~every 4 seconds).
        """
        now = current_time or time.time()

        # Build alive lookup
        alive_map: dict[int, Any] = {}
        for p in praxans:
            if getattr(p, "alive", True):
                alive_map[p.id] = p

        # Clean up dead praxans
        dead_ids = set()
        for (h_id, t_id) in list(self._grudges.keys()):
            if h_id not in alive_map:
                dead_ids.add(h_id)
            if t_id not in alive_map:
                dead_ids.add(t_id)
        for did in dead_ids:
            self.remove_praxan(did)

        # Eval pass — stage transitions, moodlets, opinion drift, effects
        do_eval = (now - self._last_eval_time) >= EVAL_INTERVAL
        if not do_eval:
            return
        self._last_eval_time = now

        # Process all directed grudge pairs (evaluate BEFORE decay)
        for (h_id, t_id), entries in list(self._grudges.items()):
            if not entries:
                continue
            holder = alive_map.get(h_id)
            target = alive_map.get(t_id)
            if holder is None or target is None:
                continue

            total = sum(e.get("weight", 0) for e in entries)
            stage = get_stage_for_weight(total)
            pair = _pair_key(h_id, t_id)

            if stage is None:
                # Below minimum — feud resolved
                old_stage = self._stages.pop(pair, None)
                if old_stage:
                    self._on_feud_resolved(holder, target, old_stage, event_bus, now)
                continue

            stage_id = stage.get("id", "simmering")
            old_stage_id = self._stages.get(pair)

            # Detect stage transitions
            if old_stage_id != stage_id:
                self._stages[pair] = stage_id
                self._on_stage_change(holder, target, old_stage_id, stage_id, stage, event_bus, now)

            # Apply recurring effects
            self._apply_effects(holder, target, stage, faction_manager, diplomacy_manager, now)

        # Decay pass (after eval so current weights get full effect first)
        do_decay = (now - self._last_decay_time) >= DECAY_INTERVAL
        if do_decay:
            self._last_decay_time = now
            self._apply_decay(alive_map)

    def _apply_decay(self, alive_map: dict[int, Any]) -> None:
        """Decay all grudge weights based on grudge def decay_rate and holder personality."""
        keys_to_clean = []
        for (h_id, t_id), entries in self._grudges.items():
            holder = alive_map.get(h_id)
            remaining = []
            for entry in entries:
                gdef = get_grudge_def(entry.get("grudge_id", ""))
                decay_rate = gdef.get("decay_rate", 0.3) if gdef else 0.3

                # Personality modulates decay: high sociability = faster decay (forgiving)
                # high diligence = slower decay (holds grudges longer)
                if holder is not None:
                    personality = getattr(holder, "personality", {})
                    sociability = personality.get("sociability", 0.5)
                    diligence = personality.get("diligence", 0.5)
                    # More sociable → decay faster (1.0 + 0.5 at max sociability)
                    # More diligent → decay slower (1.0 - 0.3 at max diligence)
                    decay_mult = 1.0 + (sociability - 0.5) * 1.0 - (diligence - 0.5) * 0.6
                    decay_rate *= max(0.1, decay_mult)

                entry["weight"] = max(0.0, entry["weight"] - decay_rate)
                if entry["weight"] > 0.5:  # prune near-zero
                    remaining.append(entry)

            if remaining:
                self._grudges[(h_id, t_id)] = remaining
            else:
                keys_to_clean.append((h_id, t_id))

        for k in keys_to_clean:
            del self._grudges[k]

    def _apply_effects(
        self,
        holder: Any,
        target: Any,
        stage: dict[str, Any],
        faction_manager: Any,
        diplomacy_manager: Any,
        current_time: float,
    ) -> None:
        """Apply recurring feud stage effects."""
        effects = stage.get("effects", {})
        moodlet_id = stage.get("moodlet_id")
        moodlet_offset = stage.get("moodlet_offset", 0)
        moodlet_duration = stage.get("moodlet_duration", 120)

        # Moodlet on holder
        if moodlet_id and hasattr(holder, "add_moodlet"):
            holder.add_moodlet(moodlet_id, moodlet_offset, moodlet_duration, current_time)

        # Opinion drift (push opinion toward negative)
        opinion_drift = effects.get("opinion_drift", 0)
        if opinion_drift and hasattr(holder, "opinions"):
            current_opinion = holder.opinions.get(target.id, 0)
            holder.opinions[target.id] = max(-100, current_opinion + opinion_drift)

        # Cohesion penalty (same-faction feuds weaken cohesion)
        cohesion_penalty = effects.get("cohesion_penalty", 0)
        if cohesion_penalty and faction_manager is not None:
            h_fid = getattr(holder, "faction_id", None)
            t_fid = getattr(target, "faction_id", None)
            if h_fid is not None and h_fid == t_fid:
                factions = getattr(faction_manager, "factions", {})
                faction = factions.get(h_fid)
                if faction is not None:
                    old_c = getattr(faction, "cohesion", 50)
                    faction.cohesion = max(0, old_c + cohesion_penalty)

        # Diplomacy penalty (cross-faction feuds harm diplomatic standing)
        diplo_penalty = effects.get("diplomacy_penalty", 0)
        if diplo_penalty and diplomacy_manager is not None:
            h_fid = getattr(holder, "faction_id", None)
            t_fid = getattr(target, "faction_id", None)
            if h_fid is not None and t_fid is not None and h_fid != t_fid:
                try:
                    diplomacy_manager.adjust_standing(h_fid, t_fid, diplo_penalty)
                except Exception:
                    pass

        # Violence chance (blood feud) — queue confrontation
        violence_chance = effects.get("violence_chance", 0)
        if violence_chance and random.random() < violence_chance:
            self._trigger_confrontation(holder, target, current_time)

    def _trigger_confrontation(self, holder: Any, target: Any, current_time: float) -> None:
        """Physical confrontation between feuding praxans.

        Both take damage; loser gets reputation penalty.
        """
        h_hp = getattr(holder, "health", 100)
        t_hp = getattr(target, "health", 100)

        # Simple combat roll based on health + bravery
        h_power = h_hp * 0.5 + getattr(holder, "personality", {}).get("bravery", 0.5) * 30 + random.random() * 20
        t_power = t_hp * 0.5 + getattr(target, "personality", {}).get("bravery", 0.5) * 30 + random.random() * 20

        damage_to_loser = random.randint(15, 30)
        damage_to_winner = random.randint(5, 15)

        if h_power >= t_power:
            winner, loser = holder, target
        else:
            winner, loser = target, holder

        # Apply damage
        if hasattr(loser, "health"):
            loser.health = max(1, loser.health - damage_to_loser)
        if hasattr(winner, "health"):
            winner.health = max(1, winner.health - damage_to_winner)

        # Reputation consequences
        if hasattr(winner, "_pending_reputation_events"):
            winner._pending_reputation_events.append("feud_confrontation_won")
        if hasattr(loser, "_pending_reputation_events"):
            loser._pending_reputation_events.append("feud_confrontation_lost")

        # Episodic memory
        w_name = getattr(winner, "name", f"Praxan {winner.id}")
        l_name = getattr(loser, "name", f"Praxan {loser.id}")
        for p, desc in [(winner, f"{w_name} fought {l_name} in a blood feud and won"),
                        (loser, f"{l_name} fought {w_name} in a blood feud and lost")]:
            if hasattr(p, "episodic_memory") and p.episodic_memory is not None:
                p.episodic_memory.record(
                    "feud_confrontation",
                    desc,
                    related_ids=[winner.id if p is loser else loser.id],
                    metadata={"result": "won" if p is winner else "lost"},
                )

        # Moodlets
        if hasattr(winner, "add_moodlet"):
            winner.add_moodlet("FeudConfrontationWon", 3, 180, current_time)
        if hasattr(loser, "add_moodlet"):
            loser.add_moodlet("FeudConfrontationLost", -8, 180, current_time)

    def _on_stage_change(
        self,
        holder: Any,
        target: Any,
        old_stage_id: Optional[str],
        new_stage_id: str,
        stage_def: dict[str, Any],
        event_bus: Any,
        current_time: float,
    ) -> None:
        """Handle a feud stage escalation or de-escalation."""
        h_name = getattr(holder, "name", f"Praxan {holder.id}")
        t_name = getattr(target, "name", f"Praxan {target.id}")
        label = stage_def.get("label", new_stage_id)
        severity = stage_def.get("severity", 1)

        is_escalation = old_stage_id is None or severity > _stage_severity(old_stage_id)

        # Episodic memory
        if hasattr(holder, "episodic_memory") and holder.episodic_memory is not None:
            if is_escalation:
                holder.episodic_memory.record(
                    "feud_escalated",
                    f"{h_name}'s feud with {t_name} escalated to {label}",
                    related_ids=[target.id],
                    metadata={"stage": new_stage_id},
                )
            else:
                holder.episodic_memory.record(
                    "feud_deescalated",
                    f"{h_name}'s feud with {t_name} cooled to {label}",
                    related_ids=[target.id],
                    metadata={"stage": new_stage_id},
                )

        # EventBus
        if event_bus is not None:
            try:
                from events.bus import GameEvent, CATEGORY_PERSONAL
                direction = "escalated to" if is_escalation else "cooled to"
                drama = min(3 + severity * 2, 10)
                event_bus.publish(GameEvent(
                    category=CATEGORY_PERSONAL,
                    summary=f"{h_name}'s feud with {t_name} {direction} {label}",
                    detail=f"Total grudge weight: {self.get_total_weight(holder.id, target.id):.0f}",
                    praxan_id=holder.id,
                    faction_id=getattr(holder, "faction_id", None),
                    metadata={
                        "type": "feud_stage_change",
                        "holder_id": holder.id,
                        "target_id": target.id,
                        "stage": new_stage_id,
                        "escalation": is_escalation,
                    },
                ))
            except Exception:
                pass

        # Ally recruitment at hostile+ stages
        if is_escalation and stage_def.get("effects", {}).get("ally_recruitment"):
            self._try_recruit_allies(holder, target, new_stage_id, current_time)

    def _on_feud_resolved(
        self,
        holder: Any,
        target: Any,
        old_stage_id: str,
        event_bus: Any,
        current_time: float,
    ) -> None:
        """Handle feud resolution (weight dropped below minimum)."""
        h_name = getattr(holder, "name", f"Praxan {holder.id}")
        t_name = getattr(target, "name", f"Praxan {target.id}")

        if hasattr(holder, "episodic_memory") and holder.episodic_memory is not None:
            holder.episodic_memory.record(
                "feud_resolved",
                f"{h_name}'s feud with {t_name} has ended",
                related_ids=[target.id],
                metadata={"old_stage": old_stage_id},
            )

        # Small mood boost for resolution
        if hasattr(holder, "add_moodlet"):
            holder.add_moodlet("FeudResolved", 4, 180, current_time)

        if event_bus is not None:
            try:
                from events.bus import GameEvent, CATEGORY_PERSONAL
                event_bus.publish(GameEvent(
                    category=CATEGORY_PERSONAL,
                    summary=f"{h_name}'s feud with {t_name} has ended",
                    praxan_id=holder.id,
                    metadata={"type": "feud_resolved", "holder_id": holder.id, "target_id": target.id},
                ))
            except Exception:
                pass

    def _try_recruit_allies(
        self,
        holder: Any,
        target: Any,
        stage_id: str,
        current_time: float,
    ) -> None:
        """At hostile+ stages, holder's friends develop a rival_grudge toward target."""
        if not hasattr(holder, "relationships"):
            return
        friends = []
        rels = getattr(holder, "relationships", {})
        for rel_id, rel_types in rels.items():
            if isinstance(rel_types, list):
                if "friend" in rel_types:
                    friends.append(rel_id)
            elif isinstance(rel_types, str):
                if rel_types == "friend":
                    friends.append(rel_id)

        # Each friend has a chance to pick up a rival grudge
        for friend_id in friends:
            if isinstance(friend_id, int) and random.random() < 0.3:
                self.record_grudge(friend_id, target.id, "rival_grudge", multiplier=0.5)

    # ---- query helpers ----------------------------------------------------

    def get_active_feud_count(self) -> int:
        """Return number of active directed grudge pairs."""
        return len(self._grudges)

    def get_feuding_pairs(self) -> list[tuple[int, int, str]]:
        """Return list of (holder_id, target_id, stage_id) for all active feuds."""
        result = []
        for (h_id, t_id), entries in self._grudges.items():
            total = sum(e.get("weight", 0) for e in entries)
            stage = get_stage_for_weight(total)
            if stage:
                result.append((h_id, t_id, stage.get("id", "simmering")))
        return result

    def get_faction_feuds(self, faction_id: int, praxans: list) -> list[dict[str, Any]]:
        """Return all feuds involving members of a faction."""
        member_ids = {p.id for p in praxans
                      if getattr(p, "alive", True) and getattr(p, "faction_id", None) == faction_id}
        result = []
        for (h_id, t_id), entries in self._grudges.items():
            if h_id in member_ids or t_id in member_ids:
                total = sum(e.get("weight", 0) for e in entries)
                stage = get_stage_for_weight(total)
                if stage:
                    result.append({
                        "holder_id": h_id,
                        "target_id": t_id,
                        "total_weight": round(total, 1),
                        "stage_id": stage.get("id"),
                        "is_internal": h_id in member_ids and t_id in member_ids,
                    })
        return result

    # ---- serialization ----------------------------------------------------

    def serialize(self, current_time: float | None = None) -> dict[str, Any]:
        """Serialize for snapshot."""
        now = current_time or time.time()
        grudge_data = {}
        for (h_id, t_id), entries in self._grudges.items():
            key = f"{h_id}:{t_id}"
            grudge_data[key] = [
                {
                    "grudge_id": e.get("grudge_id", ""),
                    "weight": round(e.get("weight", 0), 2),
                    "age_seconds": round(now - e.get("timestamp", now), 1),
                }
                for e in entries
                if e.get("weight", 0) > 0.5
            ]
        return {
            "grudges": grudge_data,
            "stages": {f"{k[0]}:{k[1]}": v for k, v in self._stages.items()},
        }

    def restore(self, data: dict[str, Any], current_time: float | None = None) -> None:
        """Restore from snapshot data."""
        now = current_time or time.time()
        self._grudges.clear()
        self._stages.clear()

        grudge_data = data.get("grudges", {})
        for key, entries in grudge_data.items():
            try:
                h_str, t_str = key.split(":")
                h_id, t_id = int(h_str), int(t_str)
            except (ValueError, TypeError):
                continue
            restored = []
            for e in entries:
                age = e.get("age_seconds", 0)
                restored.append({
                    "grudge_id": e.get("grudge_id", ""),
                    "weight": max(0.0, float(e.get("weight", 0))),
                    "timestamp": now - max(0.0, float(age)),
                })
            if restored:
                self._grudges[(h_id, t_id)] = restored

        stage_data = data.get("stages", {})
        for key, stage_id in stage_data.items():
            try:
                a_str, b_str = key.split(":")
                a_id, b_id = int(a_str), int(b_str)
                self._stages[(a_id, b_id)] = str(stage_id)
            except (ValueError, TypeError):
                continue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STAGE_SEVERITY = {
    "simmering": 1,
    "hostile": 2,
    "vendetta": 3,
    "blood_feud": 4,
}


def _stage_severity(stage_id: str) -> int:
    return _STAGE_SEVERITY.get(stage_id, 0)
