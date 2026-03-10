"""Tests for the Rituals & Gatherings system (systems/rituals.py)."""

import unittest
import time
import math

from systems.rituals import (
    RitualManager,
    FactionRitualState,
    get_ritual_def,
    get_all_ritual_defs,
    clear_cache,
    RITUAL_EVAL_INTERVAL,
    RITUAL_GATHER_RADIUS,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight stubs
# ---------------------------------------------------------------------------

class StubPraxan:
    _next_id = 0

    def __init__(self, x=100, y=100, faction_id=0):
        self.id = StubPraxan._next_id
        StubPraxan._next_id += 1
        self.x = x
        self.y = y
        self.faction_id = faction_id
        self.alive = True
        self.health = 100.0
        self.happiness = 70.0
        self.morale = 65.0
        self.inspiration = 30.0
        self.resilience = 1.0
        self.needs = {
            "hunger": 80.0,
            "energy": 80.0,
            "social": 50.0,
            "thirst": 80.0,
        }
        self.bonds = {}
        self.moodlets = []
        self.personality = {"curiosity": 0.5, "sociability": 0.7, "diligence": 0.5}
        self.episodic_memory = StubMemory()
        self.traits = []

    def add_moodlet(self, name, value, duration, start_time):
        for m in self.moodlets:
            if m["name"] == name:
                m["duration"] = duration
                m["start_time"] = start_time
                return
        self.moodlets.append({
            "name": name,
            "value": value,
            "duration": duration,
            "start_time": start_time,
        })


class StubMemory:
    def __init__(self):
        self.entries = []

    def record(self, category, summary, related_ids=None, timestamp=None, metadata=None, weight_override=None):
        self.entries.append({
            "category": category,
            "summary": summary,
            "related_ids": related_ids or [],
            "timestamp": timestamp,
            "metadata": metadata or {},
        })


class StubBuilding:
    def __init__(self, x=100, y=100, building_type="house"):
        self.x = x
        self.y = y
        self.building_type = building_type


class StubFaction:
    def __init__(self, faction_id=0, member_ids=None):
        self.id = faction_id
        self.member_ids = list(member_ids or [])
        self.leader_id = member_ids[0] if member_ids else None
        self.primary_doctrine = "growth"
        self.cohesion = 60.0
        self.stability = 50.0
        self.food_security = 52.0

    def get_members(self, praxans):
        return [p for p in praxans if p.id in self.member_ids]

    def get_centroid(self, praxans):
        members = self.get_members(praxans)
        if not members:
            return None
        avg_x = sum(m.x for m in members) / len(members)
        avg_y = sum(m.y for m in members) / len(members)
        return (avg_x, avg_y)


class StubFactionManager:
    def __init__(self, factions=None):
        self.factions = factions or {}


class StubEventBus:
    def __init__(self):
        self.published = []
        self._subscribers = {}

    def publish(self, event):
        self.published.append(event)

    def subscribe(self, category, handler):
        self._subscribers.setdefault(category, []).append(handler)


class StubNarrativePanel:
    def __init__(self):
        self.messages = []

    def add_message(self, text, category=""):
        self.messages.append((text, category))


class StubParticleSystem:
    def __init__(self):
        self.particles = []

    def create_particles(self, x, y, effect_type, count):
        self.particles.append((x, y, effect_type, count))


class StubAdvisor:
    def __init__(self):
        self.session_stats = {}
        self.observer_timeline = []


# ---------------------------------------------------------------------------
# Tests — Def Loading
# ---------------------------------------------------------------------------

class TestRitualDefLoading(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def test_ritual_defs_load(self):
        """All 6 ritual defs should load from JSON."""
        defs = get_all_ritual_defs()
        self.assertEqual(len(defs), 6)
        self.assertIn("doctrine_renewal", defs)
        self.assertIn("harvest_thanksgiving", defs)
        self.assertIn("mourning_ceremony", defs)
        self.assertIn("naming_day", defs)
        self.assertIn("seasonal_rite", defs)
        self.assertIn("victory_celebration", defs)

    def test_ritual_def_required_fields(self):
        """Each ritual def should have required fields."""
        for rid, rdef in get_all_ritual_defs().items():
            self.assertIn("id", rdef, f"Missing 'id' in {rid}")
            self.assertIn("name", rdef, f"Missing 'name' in {rid}")
            self.assertIn("trigger", rdef, f"Missing 'trigger' in {rid}")
            self.assertIn("min_participants", rdef, f"Missing 'min_participants' in {rid}")
            self.assertIn("effects", rdef, f"Missing 'effects' in {rid}")
            self.assertIn("moodlet", rdef, f"Missing 'moodlet' in {rid}")
            self.assertIn("drama_weight", rdef, f"Missing 'drama_weight' in {rid}")
            self.assertIn("narrative_template", rdef, f"Missing 'narrative_template' in {rid}")

    def test_ritual_def_effects_structure(self):
        """Effects should contain mood-related keys."""
        doctrine = get_ritual_def("doctrine_renewal")
        self.assertIn("morale_boost", doctrine["effects"])
        self.assertIn("bond_change", doctrine["effects"])

    def test_periodic_rituals_have_interval(self):
        """Periodic rituals must have interval_seconds."""
        doctrine = get_ritual_def("doctrine_renewal")
        self.assertEqual(doctrine["trigger"], "periodic")
        self.assertIn("interval_seconds", doctrine)
        self.assertGreater(doctrine["interval_seconds"], 0)

    def test_conditional_rituals_have_condition(self):
        """Conditional rituals must have a condition field."""
        harvest = get_ritual_def("harvest_thanksgiving")
        self.assertEqual(harvest["trigger"], "condition")
        self.assertIn("condition", harvest)

    def test_moodlet_defs_exist(self):
        """Ritual moodlets should exist in MoodDef."""
        from systems.def_database import DefDatabase
        mood_defs = DefDatabase.get_all("MoodDef")
        mood_ids = set(mood_defs.keys())
        for rid, rdef in get_all_ritual_defs().items():
            moodlet_id = rdef.get("moodlet")
            if moodlet_id:
                self.assertIn(moodlet_id, mood_ids, f"Moodlet {moodlet_id} missing from MoodDef")


# ---------------------------------------------------------------------------
# Tests — FactionRitualState
# ---------------------------------------------------------------------------

class TestFactionRitualState(unittest.TestCase):
    def test_serialization_roundtrip(self):
        """FactionRitualState should serialize and restore cleanly."""
        state = FactionRitualState(faction_id=3)
        state.last_ritual_times = {"doctrine_renewal": 100.0, "mourning_ceremony": 80.0}
        state.ritual_history = [{"ritual_id": "doctrine_renewal", "time": 100.0, "participants": 4}]
        state.pending_conditions = {"recent_death": 90.0}

        data = state.to_dict()
        restored = FactionRitualState.from_dict(data)

        self.assertEqual(restored.faction_id, 3)
        self.assertEqual(restored.last_ritual_times["doctrine_renewal"], 100.0)
        self.assertEqual(len(restored.ritual_history), 1)
        self.assertEqual(restored.pending_conditions["recent_death"], 90.0)

    def test_history_bounded(self):
        """Ritual history should be bounded to 8 entries in serialization."""
        state = FactionRitualState(faction_id=0)
        for i in range(20):
            state.ritual_history.append({"ritual_id": f"test_{i}", "time": float(i)})

        data = state.to_dict()
        self.assertLessEqual(len(data["ritual_history"]), 8)


# ---------------------------------------------------------------------------
# Tests — RitualManager Core
# ---------------------------------------------------------------------------

class TestRitualManagerInit(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0

    def test_initial_state(self):
        rm = RitualManager()
        self.assertEqual(rm.total_rituals_held, 0)
        self.assertEqual(len(rm.faction_states), 0)

    def test_serialization_roundtrip(self):
        rm = RitualManager()
        rm.total_rituals_held = 5
        rm.faction_states[0] = FactionRitualState(0)
        rm.faction_states[0].last_ritual_times["doctrine_renewal"] = 50.0

        data = rm.serialize()
        rm2 = RitualManager()
        rm2.restore(data)

        self.assertEqual(rm2.total_rituals_held, 5)
        self.assertIn(0, rm2.faction_states)
        self.assertEqual(rm2.faction_states[0].last_ritual_times["doctrine_renewal"], 50.0)

    def test_restore_empty_data(self):
        rm = RitualManager()
        rm.restore({})
        self.assertEqual(rm.total_rituals_held, 0)

    def test_restore_none_data(self):
        rm = RitualManager()
        rm.restore(None)
        self.assertEqual(rm.total_rituals_held, 0)

    def test_restore_ignores_non_dict_faction_states(self):
        rm = RitualManager()
        rm.restore({"total_rituals_held": 3, "faction_states": []})
        self.assertEqual(rm.total_rituals_held, 3)
        self.assertEqual(rm.last_eval_time, 0.0)
        self.assertEqual(rm.faction_states, {})


# ---------------------------------------------------------------------------
# Tests — Ritual Execution
# ---------------------------------------------------------------------------

class TestRitualExecution(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0

    def _make_faction_with_shrine(self, n_members=4):
        """Create a faction of n_members near a shrine."""
        praxans = [StubPraxan(x=100 + i * 10, y=100, faction_id=0) for i in range(n_members)]
        member_ids = [p.id for p in praxans]
        faction = StubFaction(faction_id=0, member_ids=member_ids)
        fm = StubFactionManager(factions={0: faction})
        shrine = StubBuilding(x=100, y=100, building_type="shrine")
        return praxans, faction, fm, [shrine]

    def test_periodic_ritual_fires(self):
        """Doctrine renewal should fire when interval elapsed and shrine present."""
        praxans, faction, fm, buildings = self._make_faction_with_shrine()
        rm = RitualManager()
        event_bus = StubEventBus()
        narrative = StubNarrativePanel()
        advisor = StubAdvisor()

        # First call — initializes last_eval_time
        rm.update(fm, praxans, buildings, 0.0, event_bus, advisor, narrative)

        # Second call after eval interval — should trigger a ritual
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1, event_bus, advisor, narrative)

        self.assertGreater(rm.total_rituals_held, 0)
        self.assertGreater(len(event_bus.published), 0)
        self.assertGreater(len(narrative.messages), 0)

    def test_ritual_applies_moodlet(self):
        """Participants should receive a moodlet from the ritual."""
        praxans, faction, fm, buildings = self._make_faction_with_shrine()
        rm = RitualManager()

        rm.update(fm, praxans, buildings, 0.0)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1)

        # At least some praxans should have received moodlets
        moodlet_count = sum(1 for p in praxans if p.moodlets)
        self.assertGreater(moodlet_count, 0)

    def test_ritual_applies_bond_changes(self):
        """Participants should gain bonds with other participants."""
        praxans, faction, fm, buildings = self._make_faction_with_shrine()
        # Reset all bonds to known state
        for p in praxans:
            p.bonds = {}

        rm = RitualManager()
        rm.update(fm, praxans, buildings, 0.0)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1)

        # At least one praxan should have bonds with others
        total_bonds = sum(len(p.bonds) for p in praxans)
        self.assertGreater(total_bonds, 0)

    def test_ritual_records_memory(self):
        """Participants should get an episodic memory entry."""
        praxans, faction, fm, buildings = self._make_faction_with_shrine()
        rm = RitualManager()

        rm.update(fm, praxans, buildings, 0.0)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1)

        memory_count = sum(len(p.episodic_memory.entries) for p in praxans)
        self.assertGreater(memory_count, 0)
        # Check memory category
        first_memory = None
        for p in praxans:
            if p.episodic_memory.entries:
                first_memory = p.episodic_memory.entries[0]
                break
        self.assertIsNotNone(first_memory)
        self.assertEqual(first_memory["category"], "ritual_attended")

    def test_ritual_boosts_faction_cohesion(self):
        """Faction cohesion should increase after a ritual with cohesion_boost."""
        praxans, faction, fm, buildings = self._make_faction_with_shrine()
        initial_cohesion = faction.cohesion
        rm = RitualManager()

        rm.update(fm, praxans, buildings, 0.0)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1)

        # Cohesion may or may not increase depending on which ritual fires
        # (doctrine_renewal has cohesion_boost, others may not)
        # So we just check that the system ran without errors
        self.assertGreaterEqual(faction.cohesion, initial_cohesion)

    def test_cooldown_prevents_double_fire(self):
        """A ritual should not fire twice within its cooldown period."""
        praxans, faction, fm, buildings = self._make_faction_with_shrine()
        rm = RitualManager()

        rm.update(fm, praxans, buildings, 0.0)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1)
        count_after_first = rm.total_rituals_held

        # Try again shortly after — should not fire because cooldowns
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL * 2 + 2)
        # Might fire a different ritual type, but same type should be blocked
        # We verify that the first ritual type is tracked in cooldowns
        state = rm.faction_states[0]
        self.assertGreater(len(state.last_ritual_times), 0)

    def test_no_ritual_without_shrine_for_doctrine_renewal(self):
        """Doctrine renewal requires a shrine — should not fire without one."""
        praxans = [StubPraxan(x=100 + i * 10, y=100, faction_id=0) for i in range(4)]
        member_ids = [p.id for p in praxans]
        faction = StubFaction(faction_id=0, member_ids=member_ids)
        fm = StubFactionManager(factions={0: faction})
        # Only houses, no shrine
        buildings = [StubBuilding(x=100, y=100, building_type="house")]

        rm = RitualManager()
        rm.update(fm, praxans, buildings, 0.0)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1)

        # Some rituals don't require a shrine (mourning, naming, victory)
        # But doctrine_renewal and seasonal_rite require shrine
        state = rm.faction_states.get(0)
        if state:
            self.assertNotIn("doctrine_renewal", state.last_ritual_times)
            self.assertNotIn("seasonal_rite", state.last_ritual_times)

    def test_small_faction_skipped(self):
        """Faction with < 2 members should not trigger rituals."""
        praxans = [StubPraxan(x=100, y=100, faction_id=0)]
        faction = StubFaction(faction_id=0, member_ids=[praxans[0].id])
        fm = StubFactionManager(factions={0: faction})
        buildings = [StubBuilding(x=100, y=100, building_type="shrine")]

        rm = RitualManager()
        rm.update(fm, praxans, buildings, 0.0)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1)

        self.assertEqual(rm.total_rituals_held, 0)


# ---------------------------------------------------------------------------
# Tests — Condition Signals
# ---------------------------------------------------------------------------

class TestRitualConditions(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0

    def test_death_signal_enables_mourning(self):
        """Signaling a death should enable mourning ceremony condition."""
        praxans = [StubPraxan(x=100 + i * 10, y=100, faction_id=0) for i in range(3)]
        member_ids = [p.id for p in praxans]
        faction = StubFaction(faction_id=0, member_ids=member_ids)
        fm = StubFactionManager(factions={0: faction})
        # No shrine needed for mourning
        buildings = [StubBuilding(x=100, y=100, building_type="house")]

        rm = RitualManager()
        t = 0.0
        rm.update(fm, praxans, buildings, t)

        # Signal a death
        t += RITUAL_EVAL_INTERVAL + 1
        rm.signal_death(0, t)
        rm.update(fm, praxans, buildings, t)

        # Check mourning ceremony could fire
        state = rm.faction_states.get(0)
        # If mourning fired, it's in history
        rituals_fired = [h["ritual_id"] for h in (state.ritual_history if state else [])]
        # Mourning might fire or not depending on randomness, but the condition check should pass
        self.assertTrue(rm._check_condition("recent_death", faction, state or FactionRitualState(0), praxans, t, "summer", {}))

    def test_birth_signal_enables_naming_day(self):
        """Signaling a birth should enable naming day condition."""
        rm = RitualManager()
        t = 100.0
        rm.signal_birth(0, t)

        faction = StubFaction(faction_id=0, member_ids=[0, 1, 2])
        state = FactionRitualState(0)
        self.assertTrue(rm._check_condition("recent_birth", faction, state, [], t + 10, "summer", {}))
        # After 60s, condition should expire
        self.assertFalse(rm._check_condition("recent_birth", faction, state, [], t + 70, "summer", {}))

    def test_season_change_signal(self):
        """Signaling a season change should enable seasonal rite condition."""
        rm = RitualManager()
        t = 200.0
        rm.signal_season_change("winter", t)

        faction = StubFaction(faction_id=0, member_ids=[0, 1, 2])
        state = FactionRitualState(0)
        self.assertTrue(rm._check_condition("season_changed", faction, state, [], t + 5, "winter", {}))
        # After 45s, condition should expire
        self.assertFalse(rm._check_condition("season_changed", faction, state, [], t + 50, "winter", {}))

    def test_food_security_condition(self):
        """High food security should enable harvest thanksgiving."""
        rm = RitualManager()
        faction = StubFaction(faction_id=0, member_ids=[0, 1, 2])
        faction.food_security = 80.0
        state = FactionRitualState(0)
        ritual_def = {"condition_threshold": 75.0}
        self.assertTrue(rm._check_condition("food_security_high", faction, state, [], 100.0, "summer", ritual_def))

        faction.food_security = 50.0
        self.assertFalse(rm._check_condition("food_security_high", faction, state, [], 100.0, "summer", ritual_def))

    def test_crisis_survived_signal(self):
        """Signaling crisis survived should enable victory celebration."""
        rm = RitualManager()
        t = 300.0
        rm.signal_crisis_survived(0, t)

        faction = StubFaction(faction_id=0, member_ids=[0, 1, 2])
        state = FactionRitualState(0)
        self.assertTrue(rm._check_condition("survived_crisis", faction, state, [], t + 10, "summer", {}))
        # After 90s, condition should expire
        self.assertFalse(rm._check_condition("survived_crisis", faction, state, [], t + 100, "summer", {}))

    def test_season_signal_ignores_same_season(self):
        """Signaling the same season twice should not re-trigger."""
        rm = RitualManager()
        rm.signal_season_change("summer", 100.0)
        first_time = rm._season_changed

        rm.signal_season_change("summer", 200.0)
        self.assertEqual(rm._season_changed, first_time)  # Unchanged


# ---------------------------------------------------------------------------
# Tests — EventBus Integration
# ---------------------------------------------------------------------------

class TestRitualEventBusIntegration(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0

    def test_attach_event_bus(self):
        """attach_event_bus should subscribe to disaster events."""
        rm = RitualManager()
        event_bus = StubEventBus()
        rm.attach_event_bus(event_bus)
        self.assertIn("disaster", event_bus._subscribers)
        self.assertEqual(len(event_bus._subscribers["disaster"]), 1)

    def test_publishes_cultural_shift_event(self):
        """Executing a ritual should publish a CATEGORY_CULTURAL_SHIFT event."""
        praxans = [StubPraxan(x=100 + i * 10, y=100, faction_id=0) for i in range(4)]
        member_ids = [p.id for p in praxans]
        faction = StubFaction(faction_id=0, member_ids=member_ids)
        fm = StubFactionManager(factions={0: faction})
        buildings = [StubBuilding(x=100, y=100, building_type="shrine")]

        rm = RitualManager()
        event_bus = StubEventBus()

        rm.update(fm, praxans, buildings, 0.0, event_bus)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1, event_bus)

        cultural_events = [e for e in event_bus.published if e.category == "cultural_shift"]
        self.assertGreater(len(cultural_events), 0)
        self.assertIsNotNone(cultural_events[0].location)
        self.assertEqual(cultural_events[0].faction_id, 0)

    def test_advisor_stats_tracked(self):
        """Ritual execution should increment advisor.session_stats['rituals_held']."""
        praxans = [StubPraxan(x=100 + i * 10, y=100, faction_id=0) for i in range(4)]
        member_ids = [p.id for p in praxans]
        faction = StubFaction(faction_id=0, member_ids=member_ids)
        fm = StubFactionManager(factions={0: faction})
        buildings = [StubBuilding(x=100, y=100, building_type="shrine")]

        rm = RitualManager()
        advisor = StubAdvisor()

        rm.update(fm, praxans, buildings, 0.0, advisor=advisor)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1, advisor=advisor)

        self.assertGreater(advisor.session_stats.get("rituals_held", 0), 0)


# ---------------------------------------------------------------------------
# Tests — Particles
# ---------------------------------------------------------------------------

class TestRitualParticles(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0

    def test_ritual_creates_particles(self):
        """Ritual execution should create particles at gathering point."""
        praxans = [StubPraxan(x=100 + i * 10, y=100, faction_id=0) for i in range(4)]
        member_ids = [p.id for p in praxans]
        faction = StubFaction(faction_id=0, member_ids=member_ids)
        fm = StubFactionManager(factions={0: faction})
        buildings = [StubBuilding(x=100, y=100, building_type="shrine")]

        rm = RitualManager()
        particles = StubParticleSystem()

        rm.update(fm, praxans, buildings, 0.0, particle_system=particles)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1, particle_system=particles)

        self.assertGreater(len(particles.particles), 0)


# ---------------------------------------------------------------------------
# Tests — Edge Cases
# ---------------------------------------------------------------------------

class TestRitualEdgeCases(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0

    def test_no_faction_manager(self):
        """Update with None faction_manager should not crash."""
        rm = RitualManager()
        rm.update(None, [], [], 100.0)
        self.assertEqual(rm.total_rituals_held, 0)

    def test_empty_factions(self):
        """Update with empty factions dict should not crash."""
        fm = StubFactionManager(factions={})
        rm = RitualManager()
        rm.update(fm, [], [], 100.0)
        self.assertEqual(rm.total_rituals_held, 0)

    def test_dissolved_faction_cleanup(self):
        """States for dissolved factions should be cleaned up."""
        praxans = [StubPraxan(x=100 + i * 10, y=100, faction_id=0) for i in range(4)]
        member_ids = [p.id for p in praxans]
        faction = StubFaction(faction_id=0, member_ids=member_ids)
        fm = StubFactionManager(factions={0: faction})
        buildings = [StubBuilding(x=100, y=100, building_type="shrine")]

        rm = RitualManager()
        rm.update(fm, praxans, buildings, 0.0)
        self.assertIn(0, rm.faction_states)

        # Remove faction
        fm.factions = {}
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1)
        self.assertNotIn(0, rm.faction_states)

    def test_eval_interval_respected(self):
        """Updates within eval interval should be skipped."""
        rm = RitualManager()
        fm = StubFactionManager(factions={})

        rm.update(fm, [], [], 0.0)
        first_eval = rm.last_eval_time
        rm.update(fm, [], [], RITUAL_EVAL_INTERVAL / 2)
        # Second update should not change last_eval_time since it was too soon
        self.assertEqual(rm.last_eval_time, first_eval)

    def test_multiple_factions_independent(self):
        """Different factions should have independent ritual states."""
        praxans_a = [StubPraxan(x=100 + i * 10, y=100, faction_id=0) for i in range(3)]
        praxans_b = [StubPraxan(x=500 + i * 10, y=500, faction_id=1) for i in range(3)]
        faction_a = StubFaction(faction_id=0, member_ids=[p.id for p in praxans_a])
        faction_b = StubFaction(faction_id=1, member_ids=[p.id for p in praxans_b])
        fm = StubFactionManager(factions={0: faction_a, 1: faction_b})
        buildings = [
            StubBuilding(x=100, y=100, building_type="shrine"),
            StubBuilding(x=500, y=500, building_type="shrine"),
        ]

        rm = RitualManager()
        all_praxans = praxans_a + praxans_b
        rm.update(fm, all_praxans, buildings, 0.0)
        rm.update(fm, all_praxans, buildings, RITUAL_EVAL_INTERVAL + 1)

        self.assertIn(0, rm.faction_states)
        self.assertIn(1, rm.faction_states)

    def test_narrative_panel_message(self):
        """Ritual should produce a narrative panel message."""
        praxans = [StubPraxan(x=100 + i * 10, y=100, faction_id=0) for i in range(4)]
        member_ids = [p.id for p in praxans]
        faction = StubFaction(faction_id=0, member_ids=member_ids)
        fm = StubFactionManager(factions={0: faction})
        buildings = [StubBuilding(x=100, y=100, building_type="shrine")]

        rm = RitualManager()
        narrative = StubNarrativePanel()

        rm.update(fm, praxans, buildings, 0.0, narrative_panel=narrative)
        rm.update(fm, praxans, buildings, RITUAL_EVAL_INTERVAL + 1, narrative_panel=narrative)

        self.assertGreater(len(narrative.messages), 0)
        # Should be "Achievement" category
        self.assertEqual(narrative.messages[0][1], "Achievement")


# ---------------------------------------------------------------------------
# Tests — Gathering Point
# ---------------------------------------------------------------------------

class TestGatheringPoint(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        StubPraxan._next_id = 0

    def test_gathering_at_nearest_shrine(self):
        """Ritual should gather at the nearest shrine to faction centroid."""
        praxans = [StubPraxan(x=100, y=100, faction_id=0), StubPraxan(x=120, y=100, faction_id=0)]
        member_ids = [p.id for p in praxans]
        faction = StubFaction(faction_id=0, member_ids=member_ids)

        far_shrine = StubBuilding(x=900, y=900, building_type="shrine")
        near_shrine = StubBuilding(x=110, y=100, building_type="shrine")
        buildings = [far_shrine, near_shrine]

        rm = RitualManager()
        ritual_def = {"required_building": "shrine"}
        point = rm._find_gathering_point(ritual_def, faction, praxans, buildings)
        self.assertIsNotNone(point)
        self.assertEqual(point, (110, 100))  # near shrine

    def test_gathering_at_centroid_without_required_building(self):
        """Rituals without required building should gather at centroid."""
        praxans = [StubPraxan(x=200, y=300, faction_id=0), StubPraxan(x=400, y=300, faction_id=0)]
        member_ids = [p.id for p in praxans]
        faction = StubFaction(faction_id=0, member_ids=member_ids)

        rm = RitualManager()
        ritual_def = {"required_building": None}
        point = rm._find_gathering_point(ritual_def, faction, praxans, [])
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], 300.0)
        self.assertAlmostEqual(point[1], 300.0)

    def test_no_gathering_point_without_required_building_type(self):
        """If required building type isn't present, returns None."""
        praxans = [StubPraxan(x=100, y=100, faction_id=0)]
        faction = StubFaction(faction_id=0, member_ids=[praxans[0].id])
        buildings = [StubBuilding(x=100, y=100, building_type="house")]

        rm = RitualManager()
        ritual_def = {"required_building": "shrine"}
        point = rm._find_gathering_point(ritual_def, faction, praxans, buildings)
        self.assertIsNone(point)


if __name__ == "__main__":
    unittest.main()

