"""Tests for the Named Disease / Epidemic System."""
import unittest
import time
import random

from systems.def_database import DefDatabase
from systems.disease import (
    DiseaseManager,
    DiseaseInstance,
    STAGE_INCUBATING,
    STAGE_SYMPTOMATIC,
    STAGE_RECOVERING,
    get_disease_def,
    get_all_disease_ids,
    clear_cache,
)


class _MockPraxan:
    """Minimal praxan mock for disease tests."""

    def __init__(self, pid=0, x=100.0, y=100.0):
        self.id = pid
        self.x = x
        self.y = y
        self.alive = True
        self.diseased = False
        self.disease_start_time = 0
        self.diseases = []
        self.disease_immunities = {}
        self.genetics = {"immune_strength": 1.0, "adaptability": 1.0}
        self.moodlets = []
        self.name = f"Test-{pid}"
        self.health = 100.0

        # Minimal episodic memory mock
        class _MemMock:
            def __init__(self):
                self.entries = []
            def record(self, category, summary, **kwargs):
                self.entries.append({"category": category, "summary": summary})
        self.episodic_memory = _MemMock()

    def add_moodlet(self, name, value, duration, start_time):
        self.moodlets.append({"name": name, "value": value, "duration": duration})


class _MockBuilding:
    def __init__(self, btype="house", x=100.0, y=100.0):
        self.building_type = btype
        self.x = x
        self.y = y
        self.occupants = []


class DiseaseDefDatabaseMixin:
    """Mixin to ensure DefDatabase is initialized for disease tests."""

    def setUp(self):
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        clear_cache()


class TestDiseaseDefLoading(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test that disease defs load from DefDatabase."""

    def test_all_disease_ids_loaded(self):
        ids = get_all_disease_ids()
        self.assertIn("gut_rot", ids)
        self.assertIn("grey_lung", ids)
        self.assertIn("swamp_fever", ids)
        self.assertIn("blood_plague", ids)
        self.assertIn("muscle_worm", ids)
        self.assertEqual(len(ids), 5)

    def test_disease_def_has_required_fields(self):
        ddef = get_disease_def("gut_rot")
        self.assertIsNotNone(ddef)
        self.assertIn("label", ddef)
        self.assertIn("severity_per_second", ddef)
        self.assertIn("incubation_seconds", ddef)
        self.assertIn("transmission_radius", ddef)
        self.assertIn("transmission_chance", ddef)
        self.assertIn("lethality", ddef)
        self.assertIn("immunity_gain_rate", ddef)
        self.assertIn("capacity_penalties", ddef)
        self.assertIn("mood_offset", ddef)

    def test_biome_and_season_weights(self):
        ddef = get_disease_def("swamp_fever")
        self.assertIsNotNone(ddef)
        self.assertEqual(ddef["biome_weights"]["swamp"], 4.0)
        self.assertEqual(ddef["biome_weights"]["tundra"], 0.0)
        self.assertEqual(ddef["season_weights"]["summer"], 2.0)

    def test_muscle_worm_non_contagious(self):
        ddef = get_disease_def("muscle_worm")
        self.assertIsNotNone(ddef)
        self.assertEqual(ddef["transmission_radius"], 0.0)
        self.assertEqual(ddef["transmission_chance"], 0.0)
        self.assertIn("non_contagious", ddef.get("tags", []))


class TestDiseaseInstance(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test DiseaseInstance creation and serialization."""

    def test_initial_state(self):
        inst = DiseaseInstance("gut_rot")
        self.assertEqual(inst.disease_id, "gut_rot")
        self.assertEqual(inst.stage, STAGE_INCUBATING)
        self.assertAlmostEqual(inst.severity, 0.0)
        self.assertAlmostEqual(inst.immunity, 0.0)
        self.assertFalse(inst.tended)
        self.assertFalse(inst.quarantined)

    def test_serialization_roundtrip(self):
        inst = DiseaseInstance("grey_lung")
        inst.stage = STAGE_SYMPTOMATIC
        inst.severity = 0.45
        inst.immunity = 0.3
        inst.tended = True
        inst.tend_quality = 0.5
        inst.quarantined = True

        data = inst.to_dict()
        restored = DiseaseInstance.from_dict(data)

        self.assertEqual(restored.disease_id, "grey_lung")
        self.assertEqual(restored.stage, STAGE_SYMPTOMATIC)
        self.assertAlmostEqual(restored.severity, 0.45, places=3)
        self.assertAlmostEqual(restored.immunity, 0.3, places=3)
        self.assertTrue(restored.tended)
        self.assertAlmostEqual(restored.tend_quality, 0.5, places=1)
        self.assertTrue(restored.quarantined)


class TestDiseaseManagerInfection(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test DiseaseManager infection mechanics."""

    def test_infect_adds_disease(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        result = mgr.infect(praxan, "gut_rot")
        self.assertTrue(result)
        self.assertEqual(len(praxan.diseases), 1)
        self.assertEqual(praxan.diseases[0].disease_id, "gut_rot")
        self.assertTrue(praxan.diseased)  # backward compat

    def test_double_infection_blocked(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        mgr.infect(praxan, "gut_rot")
        result = mgr.infect(praxan, "gut_rot")
        self.assertFalse(result)
        self.assertEqual(len(praxan.diseases), 1)

    def test_multiple_different_diseases(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        mgr.infect(praxan, "gut_rot")
        mgr.infect(praxan, "grey_lung")
        self.assertEqual(len(praxan.diseases), 2)

    def test_immunity_blocks_reinfection(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        praxan.disease_immunities["gut_rot"] = time.time() + 120
        result = mgr.infect(praxan, "gut_rot")
        self.assertFalse(result)
        self.assertEqual(len(praxan.diseases), 0)

    def test_infect_records_memory(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        mgr.infect(praxan, "gut_rot")
        memories = praxan.episodic_memory.entries
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]["category"], "disease_contracted")
        self.assertIn("Gut Rot", memories[0]["summary"])

    def test_infect_adds_moodlet_not_yet(self):
        """Moodlet should not be added during incubation — only when symptomatic."""
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        mgr.infect(praxan, "gut_rot")
        # During incubation, no mood change
        self.assertEqual(len(praxan.moodlets), 0)


class TestDiseaseProgression(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test disease progression through stages."""

    def test_incubation_to_symptomatic(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        mgr.infect(praxan, "gut_rot")
        # Set contracted_at in the past to exceed incubation
        praxan.diseases[0].contracted_at = time.time() - 20  # gut_rot incubation is 15s

        mgr.update([praxan], delta_time=1.0)

        self.assertEqual(praxan.diseases[0].stage, STAGE_SYMPTOMATIC)
        # Should have moodlet now
        self.assertTrue(any("Gut Rot" in m["name"] for m in praxan.moodlets))

    def test_severity_increases_during_symptomatic(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        mgr.infect(praxan, "gut_rot")
        d = praxan.diseases[0]
        d.stage = STAGE_SYMPTOMATIC
        d.contracted_at = time.time() - 20

        initial_sev = d.severity
        mgr.update([praxan], delta_time=5.0)
        self.assertGreater(d.severity, initial_sev)

    def test_immunity_builds_over_time(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        mgr.infect(praxan, "gut_rot")
        d = praxan.diseases[0]
        d.stage = STAGE_SYMPTOMATIC
        d.contracted_at = time.time() - 20

        initial_imm = d.immunity
        mgr.update([praxan], delta_time=5.0)
        self.assertGreater(d.immunity, initial_imm)

    def test_recovery_when_immunity_full(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        mgr.infect(praxan, "gut_rot")
        d = praxan.diseases[0]
        d.stage = STAGE_SYMPTOMATIC
        d.contracted_at = time.time() - 20
        d.immunity = 0.999  # Almost recovered

        # Large delta to push immunity past 1.0
        mgr.update([praxan], delta_time=10.0)

        # Disease should be removed
        self.assertEqual(len(praxan.diseases), 0)
        self.assertFalse(praxan.diseased)
        # Should have recovery moodlet
        self.assertTrue(any("Recovered" in m["name"] for m in praxan.moodlets))
        # Should have immunity
        self.assertIn("gut_rot", praxan.disease_immunities)

    def test_recovery_memory_recorded(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        mgr.infect(praxan, "gut_rot")
        d = praxan.diseases[0]
        d.stage = STAGE_SYMPTOMATIC
        d.contracted_at = time.time() - 20
        d.immunity = 0.999

        mgr.update([praxan], delta_time=10.0)

        recovery_memories = [m for m in praxan.episodic_memory.entries if m["category"] == "disease_recovered"]
        self.assertEqual(len(recovery_memories), 1)
        self.assertIn("Gut Rot", recovery_memories[0]["summary"])


class TestDiseaseTending(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test disease tending mechanics."""

    def test_tend_sets_flag(self):
        praxan = _MockPraxan(0)
        d = DiseaseInstance("gut_rot")
        d.stage = STAGE_SYMPTOMATIC
        praxan.diseases = [d]

        result = DiseaseManager.tend_disease(praxan, tender_skill_level=3)
        self.assertTrue(result)
        self.assertTrue(d.tended)
        self.assertAlmostEqual(d.tend_quality, 0.5)

    def test_tend_already_tended_does_nothing(self):
        praxan = _MockPraxan(0)
        d = DiseaseInstance("gut_rot")
        d.stage = STAGE_SYMPTOMATIC
        d.tended = True
        praxan.diseases = [d]

        result = DiseaseManager.tend_disease(praxan, tender_skill_level=6)
        self.assertFalse(result)  # Nothing new to tend

    def test_tending_slows_severity(self):
        mgr = DiseaseManager()
        # Untended praxan
        p1 = _MockPraxan(0)
        mgr.infect(p1, "gut_rot")
        p1.diseases[0].stage = STAGE_SYMPTOMATIC
        p1.diseases[0].contracted_at = time.time() - 20

        # Tended praxan
        p2 = _MockPraxan(1)
        mgr.infect(p2, "gut_rot")
        p2.diseases[0].stage = STAGE_SYMPTOMATIC
        p2.diseases[0].contracted_at = time.time() - 20
        p2.diseases[0].tended = True
        p2.diseases[0].tend_quality = 0.8

        mgr.update([p1], delta_time=5.0)
        sev_untended = p1.diseases[0].severity

        mgr.update([p2], delta_time=5.0)
        sev_tended = p2.diseases[0].severity

        self.assertLess(sev_tended, sev_untended)


class TestDiseaseCapacities(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test capacity penalty calculation."""

    def test_no_penalties_when_incubating(self):
        praxan = _MockPraxan(0)
        d = DiseaseInstance("gut_rot")
        d.stage = STAGE_INCUBATING
        praxan.diseases = [d]

        penalties = DiseaseManager.get_capacity_penalties(praxan)
        self.assertEqual(len(penalties), 0)

    def test_penalties_when_symptomatic(self):
        praxan = _MockPraxan(0)
        d = DiseaseInstance("gut_rot")
        d.stage = STAGE_SYMPTOMATIC
        d.severity = 0.5
        praxan.diseases = [d]

        penalties = DiseaseManager.get_capacity_penalties(praxan)
        self.assertIn("moving", penalties)
        self.assertLess(penalties["moving"], 1.0)

    def test_multiple_diseases_stack_penalties(self):
        praxan = _MockPraxan(0)
        d1 = DiseaseInstance("gut_rot")
        d1.stage = STAGE_SYMPTOMATIC
        d1.severity = 0.5
        d2 = DiseaseInstance("grey_lung")
        d2.stage = STAGE_SYMPTOMATIC
        d2.severity = 0.5
        praxan.diseases = [d1, d2]

        penalties = DiseaseManager.get_capacity_penalties(praxan)
        # Both diseases penalize moving; the min is taken
        self.assertIn("moving", penalties)


class TestDiseaseMoodOffset(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test mood offset from diseases."""

    def test_no_offset_during_incubation(self):
        praxan = _MockPraxan(0)
        d = DiseaseInstance("gut_rot")
        d.stage = STAGE_INCUBATING
        praxan.diseases = [d]

        offset = DiseaseManager.get_mood_offset(praxan)
        self.assertEqual(offset, 0.0)

    def test_negative_offset_when_symptomatic(self):
        praxan = _MockPraxan(0)
        d = DiseaseInstance("blood_plague")
        d.stage = STAGE_SYMPTOMATIC
        d.severity = 0.5
        praxan.diseases = [d]

        offset = DiseaseManager.get_mood_offset(praxan)
        self.assertLess(offset, 0)


class TestDiseaseTransmission(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test proximity-based disease transmission."""

    def test_non_contagious_does_not_spread(self):
        mgr = DiseaseManager()
        source = _MockPraxan(0, x=100, y=100)
        target = _MockPraxan(1, x=105, y=100)  # Very close

        mgr.infect(source, "muscle_worm")
        source.diseases[0].stage = STAGE_SYMPTOMATIC
        source.diseases[0].contracted_at = time.time() - 40

        # Run many updates — should never spread (tx_radius=0, tx_chance=0)
        for _ in range(20):
            mgr.update([source, target], delta_time=1.0)

        self.assertEqual(len(target.diseases), 0)

    def test_quarantine_prevents_transmission(self):
        mgr = DiseaseManager()
        source = _MockPraxan(0, x=100, y=100)
        target = _MockPraxan(1, x=110, y=100)
        hospital = _MockBuilding("hospital", x=100, y=100)

        mgr.infect(source, "grey_lung")
        source.diseases[0].stage = STAGE_SYMPTOMATIC
        source.diseases[0].contracted_at = time.time() - 30

        # Update with hospital nearby — source should be quarantined
        mgr.update([source, target], delta_time=1.0, buildings=[hospital])

        self.assertTrue(source.diseases[0].quarantined)


class TestDiseaseSummary(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test disease summary strings."""

    def test_healthy_summary(self):
        praxan = _MockPraxan(0)
        self.assertEqual(DiseaseManager.get_disease_summary(praxan), "Healthy")

    def test_infected_summary(self):
        praxan = _MockPraxan(0)
        d = DiseaseInstance("gut_rot")
        d.stage = STAGE_SYMPTOMATIC
        d.severity = 0.5
        d.immunity = 0.3
        praxan.diseases = [d]

        summary = DiseaseManager.get_disease_summary(praxan)
        self.assertIn("Gut Rot", summary)
        self.assertIn("Symptomatic", summary)


class TestDiseaseManagerSerialization(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test disease serialization for snapshots."""

    def test_serialize_empty(self):
        praxan = _MockPraxan(0)
        data = DiseaseManager.serialize_diseases(praxan)
        self.assertEqual(data, [])

    def test_serialize_and_deserialize(self):
        praxan = _MockPraxan(0)
        d = DiseaseInstance("grey_lung")
        d.stage = STAGE_SYMPTOMATIC
        d.severity = 0.4
        d.immunity = 0.2
        d.tended = True
        d.tend_quality = 0.5
        praxan.diseases = [d]

        data = DiseaseManager.serialize_diseases(praxan)
        self.assertEqual(len(data), 1)

        # Restore onto a new praxan
        new_praxan = _MockPraxan(1)
        DiseaseManager.deserialize_diseases(new_praxan, data)

        self.assertEqual(len(new_praxan.diseases), 1)
        restored = new_praxan.diseases[0]
        self.assertEqual(restored.disease_id, "grey_lung")
        self.assertEqual(restored.stage, STAGE_SYMPTOMATIC)
        self.assertTrue(new_praxan.diseased)  # backward compat

    def test_immunity_serialization(self):
        praxan = _MockPraxan(0)
        praxan.disease_immunities = {
            "gut_rot": time.time() + 60,
            "expired": time.time() - 10,  # Already expired
        }

        data = DiseaseManager.serialize_immunities(praxan)
        self.assertIn("gut_rot", data)
        self.assertGreater(data["gut_rot"], 0)
        self.assertNotIn("expired", data)

        new_praxan = _MockPraxan(1)
        DiseaseManager.deserialize_immunities(new_praxan, data)
        self.assertIn("gut_rot", new_praxan.disease_immunities)
        self.assertGreater(new_praxan.disease_immunities["gut_rot"], time.time())


class TestDiseaseContraction(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test ambient disease contraction."""

    def test_try_contract_swamp_fever_in_swamp(self):
        mgr = DiseaseManager()
        # High chance: swamp biome, summer, crowded, no hygiene
        contracted = False
        for _ in range(100):
            praxan = _MockPraxan(0)
            result = mgr.try_contract(
                praxan, biome="swamp", season="summer",
                population_density=3.0, hygiene_factor=0.5,
            )
            if result:
                contracted = True
                break
        self.assertTrue(contracted, "Expected at least one contraction in 100 tries in swamp")

    def test_try_contract_respects_immunity(self):
        mgr = DiseaseManager()
        praxan = _MockPraxan(0)
        # Immune to everything
        for did in get_all_disease_ids():
            praxan.disease_immunities[did] = time.time() + 999

        for _ in range(50):
            result = mgr.try_contract(
                praxan, biome="swamp", season="summer",
                population_density=5.0, hygiene_factor=0.3,
            )
            self.assertIsNone(result)


class TestEventBusPublishing(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Regression: EventBus.publish must receive a GameEvent, not (str, dict)."""

    class _RecordingBus:
        def __init__(self):
            self.published = []

        def publish(self, event):
            self.published.append(event)

    def test_infect_publishes_game_event(self):
        from events.bus import GameEvent
        bus = self._RecordingBus()
        mgr = DiseaseManager()
        p = _MockPraxan(1)
        result = mgr.infect(p, "gut_rot", event_bus=bus)
        self.assertTrue(result)
        self.assertEqual(len(bus.published), 1)
        self.assertIsInstance(bus.published[0], GameEvent)
        self.assertIn("gut_rot", str(bus.published[0].metadata))

    def test_epidemic_publishes_game_event(self):
        from events.bus import GameEvent
        bus = self._RecordingBus()
        mgr = DiseaseManager()
        mgr.epidemic_threshold = 2
        praxans = []
        for i in range(3):
            p = _MockPraxan(i, x=100 + i * 50, y=100)
            d = DiseaseInstance("gut_rot")
            d.stage = STAGE_SYMPTOMATIC
            d.contracted_at = time.time() - 20
            d.severity = 0.3
            p.diseases = [d]
            p.diseased = True
            praxans.append(p)
        mgr.update(praxans, delta_time=1.0, event_bus=bus)
        epidemic_events = [e for e in bus.published if isinstance(e, GameEvent) and "epidemic" in str(e.metadata)]
        self.assertGreater(len(epidemic_events), 0)


class TestEpidemicDetection(DiseaseDefDatabaseMixin, unittest.TestCase):
    """Test epidemic threshold detection."""

    def test_epidemic_fires_at_threshold(self):
        mgr = DiseaseManager()
        mgr.epidemic_threshold = 3

        praxans = []
        for i in range(4):
            p = _MockPraxan(i, x=100 + i * 100, y=100)
            d = DiseaseInstance("gut_rot")
            d.stage = STAGE_SYMPTOMATIC
            d.contracted_at = time.time() - 20
            d.severity = 0.3
            p.diseases = [d]
            p.diseased = True
            praxans.append(p)

        mgr.update(praxans, delta_time=1.0)
        self.assertIn("gut_rot", mgr.active_epidemics)
        self.assertGreaterEqual(mgr.active_epidemics["gut_rot"], 3)


if __name__ == "__main__":
    unittest.main()
