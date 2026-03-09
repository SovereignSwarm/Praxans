"""Named Disease / Epidemic System.

Replaces the single ``praxan.diseased`` boolean with typed diseases that have
transmission vectors, incubation phases, capacity penalties, immunity buildup,
and quarantine mechanics.

Disease definitions live in ``defs/core/diseases.json`` and are loaded via
``DefDatabase``.

Integration points:
    - ``DiseaseManager.update()`` called from main loop (rare-tick cadence)
    - ``DiseaseManager.try_contract()`` replaces ``praxan.contract_disease()``
    - ``DiseaseManager.get_capacity_penalties()`` feeds into praxan capacities
    - Snapshot: ``to_dict()`` / ``from_dict()`` per-praxan disease list
    - EventBus: publishes disease_contracted, disease_recovered, epidemic events
"""

from __future__ import annotations

import math
import random
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Disease instance (per-praxan, per-disease)
# ---------------------------------------------------------------------------

STAGE_INCUBATING = "incubating"
STAGE_SYMPTOMATIC = "symptomatic"
STAGE_RECOVERING = "recovering"


class DiseaseInstance:
    """A single active disease on one Praxan."""

    __slots__ = (
        "disease_id", "stage", "severity", "immunity",
        "tended", "tend_quality", "contracted_at", "quarantined",
    )

    def __init__(
        self,
        disease_id: str,
        contracted_at: Optional[float] = None,
    ) -> None:
        self.disease_id = disease_id
        self.stage = STAGE_INCUBATING
        self.severity: float = 0.0   # 0.0-1.0, 1.0 = lethal threshold
        self.immunity: float = 0.0   # 0.0-1.0, 1.0 = recovered
        self.tended: bool = False
        self.tend_quality: float = 0.0
        self.contracted_at: float = contracted_at or time.time()
        self.quarantined: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "disease_id": self.disease_id,
            "stage": self.stage,
            "severity": round(self.severity, 4),
            "immunity": round(self.immunity, 4),
            "tended": self.tended,
            "tend_quality": round(self.tend_quality, 2),
            "elapsed": round(max(0.0, time.time() - self.contracted_at), 2),
            "quarantined": self.quarantined,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DiseaseInstance":
        inst = cls(
            disease_id=data["disease_id"],
            contracted_at=time.time() - data.get("elapsed", 0.0),
        )
        inst.stage = data.get("stage", STAGE_INCUBATING)
        inst.severity = data.get("severity", 0.0)
        inst.immunity = data.get("immunity", 0.0)
        inst.tended = data.get("tended", False)
        inst.tend_quality = data.get("tend_quality", 0.0)
        inst.quarantined = data.get("quarantined", False)
        return inst


# ---------------------------------------------------------------------------
# DiseaseDef cache (loaded from DefDatabase lazily)
# ---------------------------------------------------------------------------

_disease_def_cache: dict[str, dict[str, Any]] = {}


def _load_disease_defs() -> None:
    """Populate cache from DefDatabase."""
    if _disease_def_cache:
        return
    try:
        from systems.def_database import DefDatabase
        defs = DefDatabase.get_all("DiseaseDef")  # returns {id: data_dict}
        for def_id, def_data in defs.items():
            _disease_def_cache[def_id] = def_data
    except Exception:
        pass


def get_disease_def(disease_id: str) -> Optional[dict[str, Any]]:
    """Return a DiseaseDef by id, or None."""
    _load_disease_defs()
    return _disease_def_cache.get(disease_id)


def get_all_disease_ids() -> list[str]:
    """Return all known disease IDs."""
    _load_disease_defs()
    return list(_disease_def_cache.keys())


def clear_cache() -> None:
    """Clear the disease def cache (for tests)."""
    _disease_def_cache.clear()


# ---------------------------------------------------------------------------
# DiseaseManager
# ---------------------------------------------------------------------------

class DiseaseManager:
    """Manages disease progression, transmission, and recovery for all Praxans.

    Called from the main loop at rare-tick cadence (~4s).
    """

    def __init__(self) -> None:
        self.active_epidemics: dict[str, int] = {}  # disease_id -> infected count
        self.epidemic_threshold = 3  # infections needed to declare epidemic
        self._last_epidemic_events: dict[str, float] = {}  # disease_id -> last event time

    # ---- main tick ---------------------------------------------------------

    def update(
        self,
        praxans: list,
        delta_time: float,
        buildings: list | None = None,
        world_map: object | None = None,
        event_bus: object | None = None,
        narrative_panel: object | None = None,
    ) -> None:
        """Progress diseases, check transmission, update epidemic tracking."""
        now = time.time()
        buildings = buildings or []

        # Build spatial lookup for transmission
        positions: dict[int, tuple[float, float]] = {}
        for p in praxans:
            if getattr(p, "alive", True):
                positions[p.id] = (p.x, p.y)

        # Hospital positions for quarantine detection
        hospital_positions: list[tuple[float, float]] = []
        for b in buildings:
            if getattr(b, "building_type", "") == "hospital":
                hospital_positions.append((b.x, b.y))

        # Track infection counts for epidemic detection
        infection_counts: dict[str, int] = {}

        for praxan in praxans:
            if not getattr(praxan, "alive", True):
                continue

            diseases = getattr(praxan, "diseases", [])
            if not diseases:
                continue

            to_remove: list[DiseaseInstance] = []

            for disease in diseases:
                ddef = get_disease_def(disease.disease_id)
                if not ddef:
                    to_remove.append(disease)
                    continue

                # Count for epidemic tracking
                infection_counts[disease.disease_id] = infection_counts.get(disease.disease_id, 0) + 1

                # --- Stage progression ---
                incubation_secs = ddef.get("incubation_seconds", 15.0)
                elapsed = now - disease.contracted_at

                if disease.stage == STAGE_INCUBATING:
                    if elapsed >= incubation_secs:
                        disease.stage = STAGE_SYMPTOMATIC
                        # Apply disease moodlet when symptoms appear
                        mood_offset = ddef.get("mood_offset", -10)
                        _add_disease_moodlet(praxan, ddef, now)
                    continue  # No severity/immunity progress during incubation

                # --- Severity progression (symptomatic stage) ---
                if disease.stage == STAGE_SYMPTOMATIC:
                    sev_rate = ddef.get("severity_per_second", 0.01)
                    # Tending slows severity growth
                    if disease.tended:
                        treatment_factor = ddef.get("treatment_speed_factor", 1.0)
                        sev_rate *= max(0.1, 1.0 - disease.tend_quality * 0.8 * treatment_factor)
                    disease.severity = min(1.0, disease.severity + sev_rate * delta_time)

                # --- Immunity buildup ---
                imm_rate = ddef.get("immunity_gain_rate", 0.01)
                immune_strength = getattr(praxan, "genetics", {}).get("immune_strength", 1.0)
                imm_rate *= max(0.5, immune_strength)
                # Tending boosts immunity gain
                if disease.tended:
                    treatment_factor = ddef.get("treatment_speed_factor", 1.0)
                    imm_rate *= (1.0 + disease.tend_quality * treatment_factor)
                disease.immunity = min(1.0, disease.immunity + imm_rate * delta_time)

                # --- Recovery check ---
                if disease.immunity >= 1.0:
                    disease.stage = STAGE_RECOVERING
                    to_remove.append(disease)
                    _on_recovery(praxan, ddef, event_bus, narrative_panel, now)
                    continue

                # --- Lethality check ---
                if disease.severity >= 1.0:
                    lethality = ddef.get("lethality", 0.3)
                    if random.random() < lethality:
                        setattr(praxan, "last_death_cause_hint", f"disease:{ddef.get('id', 'unknown')}")
                        praxan.alive = False
                        _on_disease_death(praxan, ddef, event_bus, narrative_panel, now)
                    else:
                        # Survived severity peak — accelerate immunity
                        disease.immunity = min(1.0, disease.immunity + 0.3)
                        disease.severity = 0.8  # Severity recedes slightly

                # --- Quarantine detection ---
                px, py = praxan.x, praxan.y
                near_hospital = any(
                    math.sqrt((hx - px) ** 2 + (hy - py) ** 2) < 60
                    for hx, hy in hospital_positions
                )
                disease.quarantined = near_hospital and disease.stage == STAGE_SYMPTOMATIC

                # --- Transmission ---
                if disease.stage == STAGE_SYMPTOMATIC and not disease.quarantined:
                    tx_radius = ddef.get("transmission_radius", 30.0)
                    tx_chance = ddef.get("transmission_chance", 0.005) * delta_time
                    if tx_radius > 0 and tx_chance > 0:
                        self._try_transmit(
                            praxan, disease.disease_id, tx_radius, tx_chance,
                            praxans, positions, now, event_bus, narrative_panel,
                        )

            # Remove recovered diseases
            for d in to_remove:
                if d in diseases:
                    diseases.remove(d)

        # --- Epidemic tracking ---
        self.active_epidemics = {}
        for did, count in infection_counts.items():
            if count >= self.epidemic_threshold:
                self.active_epidemics[did] = count
                last_event = self._last_epidemic_events.get(did, 0)
                if now - last_event > 60:  # Max one epidemic event per disease per 60s
                    self._last_epidemic_events[did] = now
                    _on_epidemic(did, count, event_bus, narrative_panel, now)

    # ---- contraction -------------------------------------------------------

    def try_contract(
        self,
        praxan: object,
        biome: str = "plains",
        season: str = "summer",
        population_density: float = 1.0,
        hygiene_factor: float = 1.0,
        event_bus: object | None = None,
        narrative_panel: object | None = None,
    ) -> Optional[str]:
        """Attempt to contract a random disease based on environment.

        Returns the disease_id if contracted, else None.
        """
        _load_disease_defs()
        if not _disease_def_cache:
            return None

        diseases = getattr(praxan, "diseases", [])
        # Praxan's existing disease ids
        existing_ids = {d.disease_id for d in diseases}
        # Immunity from past diseases
        past_immunities = getattr(praxan, "disease_immunities", {})

        immune_strength = getattr(praxan, "genetics", {}).get("immune_strength", 1.0)
        adaptability = getattr(praxan, "genetics", {}).get("adaptability", 1.0)

        for disease_id, ddef in _disease_def_cache.items():
            if disease_id in existing_ids:
                continue
            # Check past immunity (recently recovered)
            if past_immunities.get(disease_id, 0) > time.time():
                continue

            biome_weight = ddef.get("biome_weights", {}).get(biome, 1.0)
            season_weight = ddef.get("season_weights", {}).get(season, 1.0)

            # Base contraction chance (per rare tick, ~4s)
            base_chance = 0.002
            if "rare" in ddef.get("tags", []):
                base_chance *= 0.15
            if "common" in ddef.get("tags", []):
                base_chance *= 2.0

            # Crowding factor for airborne diseases
            crowding_mult = 1.0
            if "airborne" in ddef.get("tags", []) or "crowding" in ddef.get("tags", []):
                crowding_mult = min(3.0, population_density)

            chance = (
                base_chance
                * biome_weight
                * season_weight
                * crowding_mult
                * (2.0 - hygiene_factor)
                / max(0.5, immune_strength)
                / max(0.75, adaptability)
            )

            if random.random() < chance:
                self.infect(praxan, disease_id, event_bus, narrative_panel)
                return disease_id

        return None

    def infect(
        self,
        praxan: object,
        disease_id: str,
        event_bus: object | None = None,
        narrative_panel: object | None = None,
    ) -> bool:
        """Infect a praxan with a specific disease. Returns True if newly infected."""
        ddef = get_disease_def(disease_id)
        if not ddef:
            return False

        diseases = getattr(praxan, "diseases", None)
        if diseases is None:
            praxan.diseases = []
            diseases = praxan.diseases

        # Already has this disease?
        if any(d.disease_id == disease_id for d in diseases):
            return False

        # Past immunity?
        past_immunities = getattr(praxan, "disease_immunities", {})
        if past_immunities.get(disease_id, 0) > time.time():
            return False

        now = time.time()
        inst = DiseaseInstance(disease_id, contracted_at=now)
        diseases.append(inst)

        # Keep backward compat: set boolean flag
        praxan.diseased = True
        praxan.disease_start_time = now

        # Record memory
        mem = getattr(praxan, "episodic_memory", None)
        if mem:
            label = ddef.get("label", disease_id)
            name = getattr(praxan, "name", f"Praxan {getattr(praxan, 'id', '?')}")
            mem.record(
                "disease_contracted",
                f"{name} contracted {label}",
                metadata={"disease_id": disease_id},
            )

        # EventBus
        if event_bus:
            try:
                from events.bus import GameEvent, CATEGORY_PERSONAL
                _label = ddef.get("label", disease_id)
                _name = getattr(praxan, "name", f"Praxan {getattr(praxan, 'id', '?')}")
                event_bus.publish(GameEvent(
                    category=CATEGORY_PERSONAL,
                    summary=f"{_name} contracted {_label}",
                    praxan_id=getattr(praxan, "id", None),
                    metadata={"disease_id": disease_id, "type": "disease_contracted"},
                ))
            except Exception:
                pass

        return True

    # ---- capacity penalties ------------------------------------------------

    @staticmethod
    def get_capacity_penalties(praxan: object) -> dict[str, float]:
        """Return combined capacity multipliers from all active symptomatic diseases.

        Returns dict like {'moving': 0.6, 'consciousness': 0.85}.
        Values are multiplicative minimums across all diseases.
        """
        penalties: dict[str, float] = {}
        diseases = getattr(praxan, "diseases", [])
        for disease in diseases:
            if disease.stage != STAGE_SYMPTOMATIC:
                continue
            ddef = get_disease_def(disease.disease_id)
            if not ddef:
                continue
            caps = ddef.get("capacity_penalties", {})
            for cap, mult in caps.items():
                # Scale penalty by severity
                scaled = 1.0 - (1.0 - mult) * min(1.0, disease.severity * 2)
                if cap in penalties:
                    penalties[cap] = min(penalties[cap], scaled)
                else:
                    penalties[cap] = scaled
        return penalties

    @staticmethod
    def get_mood_offset(praxan: object) -> float:
        """Return total mood offset from all active symptomatic diseases."""
        total = 0.0
        diseases = getattr(praxan, "diseases", [])
        for disease in diseases:
            if disease.stage != STAGE_SYMPTOMATIC:
                continue
            ddef = get_disease_def(disease.disease_id)
            if not ddef:
                continue
            total += ddef.get("mood_offset", -10) * min(1.0, disease.severity * 2)
        return total

    @staticmethod
    def get_disease_summary(praxan: object) -> str:
        """Return a human-readable summary of active diseases."""
        diseases = getattr(praxan, "diseases", [])
        if not diseases:
            return "Healthy"
        parts = []
        for d in diseases:
            ddef = get_disease_def(d.disease_id)
            label = ddef.get("label", d.disease_id) if ddef else d.disease_id
            stage_label = d.stage.replace("_", " ").title()
            sev_pct = int(d.severity * 100)
            imm_pct = int(d.immunity * 100)
            tended = " [tended]" if d.tended else ""
            quarantine = " [quarantined]" if d.quarantined else ""
            parts.append(f"{label} ({stage_label}, sev:{sev_pct}%, imm:{imm_pct}%{tended}{quarantine})")
        return "; ".join(parts)

    # ---- tending -----------------------------------------------------------

    @staticmethod
    def tend_disease(praxan: object, tender_skill_level: int = 1) -> bool:
        """Tend a praxan's diseases (called when a medic treats them).

        Returns True if any disease was tended.
        """
        diseases = getattr(praxan, "diseases", [])
        tended_any = False
        for disease in diseases:
            if disease.stage == STAGE_SYMPTOMATIC and not disease.tended:
                disease.tended = True
                disease.tend_quality = min(1.0, tender_skill_level / 6.0)
                tended_any = True
        return tended_any

    # ---- serialization -----------------------------------------------------

    @staticmethod
    def serialize_diseases(praxan: object) -> list[dict]:
        """Serialize a praxan's active diseases for snapshot."""
        diseases = getattr(praxan, "diseases", [])
        return [d.to_dict() for d in diseases]

    @staticmethod
    def deserialize_diseases(praxan: object, data: list[dict]) -> None:
        """Restore diseases from snapshot data."""
        praxan.diseases = [DiseaseInstance.from_dict(d) for d in data]
        # Update backward compat flag
        praxan.diseased = len(praxan.diseases) > 0
        if praxan.diseases:
            praxan.disease_start_time = min(d.contracted_at for d in praxan.diseases)

    @staticmethod
    def serialize_immunities(praxan: object) -> dict[str, float]:
        """Serialize disease immunities (expiry timestamps)."""
        imm = getattr(praxan, "disease_immunities", {})
        now = time.time()
        return {did: round(exp - now, 2) for did, exp in imm.items() if exp > now}

    @staticmethod
    def deserialize_immunities(praxan: object, data: dict[str, float]) -> None:
        """Restore disease immunities from snapshot."""
        now = time.time()
        praxan.disease_immunities = {did: now + remaining for did, remaining in data.items() if remaining > 0}

    # ---- internal ----------------------------------------------------------

    def _try_transmit(
        self,
        source: object,
        disease_id: str,
        radius: float,
        chance: float,
        praxans: list,
        positions: dict[int, tuple[float, float]],
        now: float,
        event_bus: object | None,
        narrative_panel: object | None,
    ) -> None:
        """Try to spread a disease from source to nearby praxans."""
        sx, sy = source.x, source.y
        src_id = source.id

        for target in praxans:
            if not getattr(target, "alive", True):
                continue
            if target.id == src_id:
                continue

            tx, ty = positions.get(target.id, (0, 0))
            dist = math.sqrt((sx - tx) ** 2 + (sy - ty) ** 2)
            if dist > radius:
                continue

            # Distance-scaled chance
            dist_factor = 1.0 - (dist / radius)
            if random.random() < chance * dist_factor:
                self.infect(target, disease_id, event_bus, narrative_panel)


# ---------------------------------------------------------------------------
# Helper functions (module-level)
# ---------------------------------------------------------------------------

def _add_disease_moodlet(praxan: object, ddef: dict, now: float) -> None:
    """Add a moodlet for becoming symptomatic."""
    add_moodlet = getattr(praxan, "add_moodlet", None)
    if add_moodlet:
        label = ddef.get("label", "Disease")
        mood_val = ddef.get("mood_offset", -10)
        add_moodlet(f"Sick: {label}", mood_val, 120, now)


def _on_recovery(
    praxan: object,
    ddef: dict,
    event_bus: object | None,
    narrative_panel: object | None,
    now: float,
) -> None:
    """Handle disease recovery."""
    disease_id = ddef["id"]
    label = ddef.get("label", disease_id)
    name = getattr(praxan, "name", f"Praxan {getattr(praxan, 'id', '?')}")

    # Grant temporary immunity (120 seconds)
    immunities = getattr(praxan, "disease_immunities", None)
    if immunities is None:
        praxan.disease_immunities = {}
        immunities = praxan.disease_immunities
    immunities[disease_id] = now + 120.0

    # Recovery moodlet
    add_moodlet = getattr(praxan, "add_moodlet", None)
    if add_moodlet:
        add_moodlet(f"Recovered: {label}", 8, 180, now)

    # Memory
    mem = getattr(praxan, "episodic_memory", None)
    if mem:
        mem.record("disease_recovered", f"{name} recovered from {label}",
                    metadata={"disease_id": disease_id})

    # Update backward compat flag
    diseases = getattr(praxan, "diseases", [])
    remaining = [d for d in diseases if d.disease_id != disease_id]
    if not remaining:
        praxan.diseased = False
        praxan.disease_start_time = 0

    if event_bus:
        try:
            from events.bus import GameEvent, CATEGORY_PERSONAL
            event_bus.publish(GameEvent(
                category=CATEGORY_PERSONAL,
                summary=f"{name} recovered from {label}",
                praxan_id=getattr(praxan, "id", None),
                metadata={"disease_id": disease_id, "type": "disease_recovered"},
            ))
        except Exception:
            pass


def _on_disease_death(
    praxan: object,
    ddef: dict,
    event_bus: object | None,
    narrative_panel: object | None,
    now: float,
) -> None:
    """Handle death from disease."""
    disease_id = ddef["id"]
    label = ddef.get("label", disease_id)
    name = getattr(praxan, "name", f"Praxan {getattr(praxan, 'id', '?')}")

    # Memory (recorded even though they're dying — visible in death summary)
    mem = getattr(praxan, "episodic_memory", None)
    if mem:
        mem.record("near_death", f"{name} succumbed to {label}",
                    metadata={"disease_id": disease_id, "cause": "disease"})

    if narrative_panel:
        try:
            narrative_panel.add_message(f"{name} died of {label}.", "Death")
        except Exception:
            pass

    if event_bus:
        try:
            from events.bus import GameEvent, CATEGORY_DEATH
            event_bus.publish(GameEvent(
                category=CATEGORY_DEATH,
                summary=f"{name} died of {label}",
                praxan_id=getattr(praxan, "id", None),
                metadata={"disease_id": disease_id, "cause": "disease"},
            ))
        except Exception:
            pass


def _on_epidemic(
    disease_id: str,
    count: int,
    event_bus: object | None,
    narrative_panel: object | None,
    now: float,
) -> None:
    """Fire epidemic event."""
    ddef = get_disease_def(disease_id)
    label = ddef.get("label", disease_id) if ddef else disease_id

    if narrative_panel:
        try:
            narrative_panel.add_message(
                f"Epidemic! {label} has infected {count} praxans.", "Crisis"
            )
        except Exception:
            pass

    if event_bus:
        try:
            from events.bus import GameEvent, CATEGORY_DISASTER
            event_bus.publish(GameEvent(
                category=CATEGORY_DISASTER,
                summary=f"Epidemic! {label} has infected {count} praxans",
                metadata={"disease_id": disease_id, "infected_count": count, "type": "epidemic"},
            ))
        except Exception:
            pass
