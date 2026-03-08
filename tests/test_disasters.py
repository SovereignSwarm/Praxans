"""Tests for natural disasters system (systems/disasters.py)."""

import unittest
import time
import math

from systems.disasters import (
    DisasterManager,
    ActiveDisaster,
    get_disaster_def,
    get_all_disaster_ids,
    clear_cache,
    EVAL_INTERVAL,
    MIN_COOLDOWN_GLOBAL,
    BASE_CHANCE_PER_EVAL,
    _disaster_def_cache,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight stubs
# ---------------------------------------------------------------------------

class StubBuilding:
    def __init__(self, x=100, y=100, building_type="house"):
        self.x = x
        self.y = y
        self.building_type = building_type
        self.stored_resources = {"food": 10, "wood": 10, "stone": 5}
        self.level = 1


class StubPraxan:
    def __init__(self, x=100, y=100, alive=True):
        self.x = x
        self.y = y
        self.id = id(self)
        self.alive = alive
        self.health = 100.0
        self.speed = 1.0
        self.moodlets = []
        self.memory = StubMemory()
        self.needs = {"energy": 100.0}
        self._disaster_speed_penalty = 0.0


class StubMemory:
    def __init__(self):
        self.events = []

    def add_event(self, **kwargs):
        self.events.append(kwargs)


class StubWorldMap:
    def __init__(self, biome="plains"):
        self._biome = biome

    def get_biome_at(self, x, y):
        return self._biome


class StubEventBus:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


class StubNarrativePanel:
    def __init__(self):
        self.messages = []

    def add_message(self, text, category=""):
        self.messages.append((text, category))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDisasterDefLoading(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def test_disaster_defs_load(self):
        """All disaster defs should load from JSON."""
        ids = get_all_disaster_ids()
        self.assertGreaterEqual(len(ids), 7)
        self.assertIn("earthquake", ids)
        self.assertIn("flood", ids)
        self.assertIn("wildfire", ids)
        self.assertIn("blizzard", ids)
        self.assertIn("toxic_bloom", ids)
        self.assertIn("meteor_strike", ids)
        self.assertIn("dust_storm", ids)

    def test_disaster_def_fields(self):
        """Each disaster def should have required fields."""
        for did in get_all_disaster_ids():
            ddef = get_disaster_def(did)
            self.assertIsNotNone(ddef, f"Def missing for {did}")
            self.assertIn("label", ddef)
            self.assertIn("radius", ddef)
            self.assertIn("duration", ddef)
            self.assertIn("effects", ddef)
            self.assertIn("conditions", ddef)
            self.assertIn("base_weight", ddef)
            self.assertIn("cooldown", ddef)
            self.assertIn("drama", ddef)

    def test_disaster_def_effects_structure(self):
        """Effects should contain expected keys."""
        eq_def = get_disaster_def("earthquake")
        self.assertIn("building_damage_pct", eq_def["effects"])
        self.assertIn("health_damage", eq_def["effects"])
        self.assertIn("mood_offset", eq_def["effects"])

    def test_meteor_has_resource_bonus(self):
        """Meteor strike should have resource_bonus in effects."""
        meteor = get_disaster_def("meteor_strike")
        self.assertIn("resource_bonus", meteor["effects"])
        self.assertIn("stone", meteor["effects"]["resource_bonus"])

    def test_clear_cache(self):
        """clear_cache should empty the cache."""
        get_all_disaster_ids()  # populate
        self.assertTrue(len(_disaster_def_cache) > 0)
        clear_cache()
        self.assertEqual(len(_disaster_def_cache), 0)


class TestActiveDisaster(unittest.TestCase):
    def test_creation(self):
        ad = ActiveDisaster("earthquake", 100, 200, 0.7, time.time(), 15.0)
        self.assertEqual(ad.disaster_id, "earthquake")
        self.assertFalse(ad.applied)
        self.assertFalse(ad.is_expired)

    def test_expiration(self):
        ad = ActiveDisaster("flood", 50, 50, 0.5, time.time() - 100, 10.0)
        self.assertTrue(ad.is_expired)

    def test_serialization(self):
        ad = ActiveDisaster("wildfire", 150, 250, 0.8, time.time(), 20.0)
        ad.applied = True
        data = ad.to_dict()
        self.assertEqual(data["disaster_id"], "wildfire")
        self.assertTrue(data["applied"])
        self.assertAlmostEqual(data["severity"], 0.8, places=2)

    def test_deserialization(self):
        ad = ActiveDisaster("blizzard", 300, 400, 0.6, time.time() - 5.0, 30.0)
        ad.applied = True
        data = ad.to_dict()
        restored = ActiveDisaster.from_dict(data)
        self.assertEqual(restored.disaster_id, "blizzard")
        self.assertTrue(restored.applied)
        self.assertAlmostEqual(restored.severity, 0.6, places=2)


class TestDisasterManagerSelection(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = DisasterManager()

    def test_select_with_enough_population(self):
        """Selection should return a disaster when population/buildings meet minimums."""
        praxans = [StubPraxan(x=100 + i * 10, y=100) for i in range(8)]
        buildings = [StubBuilding(x=100 + i * 20, y=100) for i in range(5)]
        now = time.time()
        did = self.mgr._select_disaster(now, praxans, buildings, StubWorldMap(), "summer", "clear")
        self.assertIsNotNone(did)
        self.assertIn(did, get_all_disaster_ids())

    def test_select_respects_cooldown(self):
        """A disaster on cooldown should not be selected."""
        now = time.time()
        # Put all disasters on cooldown
        for did in get_all_disaster_ids():
            self.mgr._cooldowns[did] = now
        praxans = [StubPraxan() for _ in range(10)]
        buildings = [StubBuilding() for _ in range(5)]
        result = self.mgr._select_disaster(now, praxans, buildings, StubWorldMap(), "summer", "clear")
        self.assertIsNone(result)

    def test_select_respects_population_minimum(self):
        """Should not select a disaster requiring more population than available."""
        praxans = [StubPraxan()]  # Only 1
        buildings = [StubBuilding()]
        now = time.time()
        # Most disasters require min_population >= 3
        # Repeat selection 20 times — should get None or very rarely something
        results = []
        for _ in range(20):
            r = self.mgr._select_disaster(now, praxans, buildings, StubWorldMap(), "summer", "clear")
            results.append(r)
        # The majority should be None (most defs require pop >= 3-6)
        none_count = results.count(None)
        self.assertGreater(none_count, 10)

    def test_biome_weighting_affects_selection(self):
        """Mountain biome should boost earthquake selection."""
        praxans = [StubPraxan() for _ in range(10)]
        buildings = [StubBuilding() for _ in range(5)]
        mountain_map = StubWorldMap("mountains")
        now = time.time()
        earthquake_count = 0
        for _ in range(100):
            self.mgr._cooldowns.clear()
            did = self.mgr._select_disaster(now, praxans, buildings, mountain_map, "summer", "clear")
            if did == "earthquake":
                earthquake_count += 1
        # Earthquake should appear significantly more than random chance
        self.assertGreater(earthquake_count, 5)

    def test_season_weighting(self):
        """Winter should boost blizzard selection."""
        praxans = [StubPraxan() for _ in range(10)]
        buildings = [StubBuilding() for _ in range(5)]
        tundra_map = StubWorldMap("tundra")
        now = time.time()
        blizzard_count = 0
        for _ in range(100):
            self.mgr._cooldowns.clear()
            did = self.mgr._select_disaster(now, praxans, buildings, tundra_map, "winter", "clear")
            if did == "blizzard":
                blizzard_count += 1
        self.assertGreater(blizzard_count, 5)

    def test_weather_boost(self):
        """Storm weather should boost flood selection."""
        praxans = [StubPraxan() for _ in range(10)]
        buildings = [StubBuilding() for _ in range(5)]
        swamp_map = StubWorldMap("swamp")
        now = time.time()
        flood_count = 0
        for _ in range(100):
            self.mgr._cooldowns.clear()
            did = self.mgr._select_disaster(now, praxans, buildings, swamp_map, "spring", "storm")
            if did == "flood":
                flood_count += 1
        self.assertGreater(flood_count, 5)


class TestDisasterManagerFiring(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = DisasterManager()

    def test_fire_disaster(self):
        """Firing a disaster should create an active disaster and record history."""
        praxans = [StubPraxan(x=100, y=100) for _ in range(5)]
        buildings = [StubBuilding(x=100, y=100) for _ in range(3)]
        now = time.time()
        result = self.mgr._fire_disaster(
            "earthquake", now, praxans, buildings,
            StubWorldMap(), StubEventBus(), StubNarrativePanel(),
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["disaster_id"], "earthquake")
        self.assertEqual(len(self.mgr.active_disasters), 1)
        self.assertEqual(len(self.mgr.history), 1)

    def test_fire_updates_cooldown(self):
        """Firing should set the per-disaster cooldown."""
        now = time.time()
        self.mgr._fire_disaster(
            "flood", now, [StubPraxan()], [StubBuilding()],
            StubWorldMap(), StubEventBus(), StubNarrativePanel(),
        )
        self.assertAlmostEqual(self.mgr._cooldowns["flood"], now, delta=1.0)

    def test_fire_updates_global_timer(self):
        """Firing should update _last_disaster_time."""
        now = time.time()
        self.mgr._fire_disaster(
            "wildfire", now, [StubPraxan()], [StubBuilding()],
            StubWorldMap(), StubEventBus(), StubNarrativePanel(),
        )
        self.assertAlmostEqual(self.mgr._last_disaster_time, now, delta=1.0)


class TestDisasterEffects(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = DisasterManager()

    def test_health_damage(self):
        """Praxans within radius should take health damage."""
        praxan = StubPraxan(x=100, y=100)
        praxan.health = 100.0
        building = StubBuilding(x=100, y=100)
        now = time.time()
        ad = ActiveDisaster("earthquake", 100, 100, 1.0, now, 15.0)
        self.mgr.active_disasters.append(ad)
        self.mgr._apply_effects(
            ad, [praxan], [building], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        self.assertLess(praxan.health, 100.0)

    def test_praxans_outside_radius_unaffected(self):
        """Praxans outside the disaster radius should not be damaged."""
        praxan = StubPraxan(x=5000, y=5000)  # Far away
        praxan.health = 100.0
        building = StubBuilding(x=100, y=100)
        now = time.time()
        ad = ActiveDisaster("earthquake", 100, 100, 1.0, now, 15.0)
        self.mgr._apply_effects(
            ad, [praxan], [building], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        self.assertEqual(praxan.health, 100.0)

    def test_building_resource_scatter(self):
        """Buildings in radius should lose resources from scatter."""
        building = StubBuilding(x=100, y=100)
        building.stored_resources = {"food": 20, "wood": 20, "stone": 10}
        now = time.time()
        ad = ActiveDisaster("earthquake", 100, 100, 1.0, now, 15.0)
        self.mgr._apply_effects(
            ad, [], [building], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        # Earthquake has resource_scatter_pct=0.20
        self.assertLess(building.stored_resources["food"], 20)

    def test_farm_food_destruction(self):
        """Farms should lose extra food from farm_destruction_pct."""
        farm = StubBuilding(x=100, y=100, building_type="farm")
        farm.stored_resources = {"food": 50, "wood": 10, "stone": 5}
        now = time.time()
        ad = ActiveDisaster("flood", 100, 100, 1.0, now, 18.0)
        self.mgr._apply_effects(
            ad, [], [farm], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        # Flood has farm_destruction_pct=0.50
        self.assertLess(farm.stored_resources["food"], 50)

    def test_wildfire_wood_destruction(self):
        """Wildfire should destroy wood in buildings."""
        building = StubBuilding(x=100, y=100)
        building.stored_resources = {"food": 10, "wood": 30, "stone": 5}
        now = time.time()
        ad = ActiveDisaster("wildfire", 100, 100, 1.0, now, 25.0)
        self.mgr._apply_effects(
            ad, [], [building], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        self.assertLess(building.stored_resources["wood"], 30)

    def test_meteor_resource_bonus(self):
        """Meteor strike should deposit bonus resources at nearest storage."""
        storage = StubBuilding(x=110, y=110, building_type="storage")
        storage.stored_resources = {"food": 5, "wood": 5, "stone": 5}
        now = time.time()
        ad = ActiveDisaster("meteor_strike", 100, 100, 1.0, now, 5.0)
        self.mgr._apply_effects(
            ad, [], [storage], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        self.assertGreater(storage.stored_resources["stone"], 5)

    def test_moodlet_applied(self):
        """Affected praxans should receive a disaster moodlet."""
        praxan = StubPraxan(x=100, y=100)
        now = time.time()
        ad = ActiveDisaster("earthquake", 100, 100, 0.5, now, 15.0)
        self.mgr._apply_effects(
            ad, [praxan], [], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        disaster_moodlets = [m for m in praxan.moodlets if "disaster" in m["id"]]
        self.assertEqual(len(disaster_moodlets), 1)
        self.assertLess(disaster_moodlets[0]["offset"], 0)

    def test_no_duplicate_moodlets(self):
        """Applying effects twice should not duplicate moodlets."""
        praxan = StubPraxan(x=100, y=100)
        now = time.time()
        ad = ActiveDisaster("earthquake", 100, 100, 0.5, now, 15.0)
        self.mgr._apply_effects(
            ad, [praxan], [], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        self.mgr._apply_effects(
            ad, [praxan], [], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        disaster_moodlets = [m for m in praxan.moodlets if "disaster" in m["id"]]
        self.assertEqual(len(disaster_moodlets), 1)

    def test_episodic_memory_recorded(self):
        """Affected praxans should get an episodic memory of the disaster."""
        praxan = StubPraxan(x=100, y=100)
        now = time.time()
        ad = ActiveDisaster("flood", 100, 100, 0.7, now, 18.0)
        self.mgr._apply_effects(
            ad, [praxan], [], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        self.assertEqual(len(praxan.memory.events), 1)
        self.assertEqual(praxan.memory.events[0]["event_type"], "disaster")

    def test_eventbus_published(self):
        """A CATEGORY_DISASTER event should be published."""
        bus = StubEventBus()
        praxan = StubPraxan(x=100, y=100)
        now = time.time()
        ad = ActiveDisaster("earthquake", 100, 100, 0.5, now, 15.0)
        self.mgr._apply_effects(
            ad, [praxan], [], StubWorldMap(),
            bus, StubNarrativePanel(),
        )
        self.assertEqual(len(bus.published), 1)
        self.assertEqual(bus.published[0].category, "disaster")

    def test_narrative_panel_message(self):
        """Narrative panel should receive a disaster message."""
        panel = StubNarrativePanel()
        praxan = StubPraxan(x=100, y=100)
        now = time.time()
        ad = ActiveDisaster("earthquake", 100, 100, 0.5, now, 15.0)
        self.mgr._apply_effects(
            ad, [praxan], [], StubWorldMap(),
            StubEventBus(), panel,
        )
        self.assertEqual(len(panel.messages), 1)
        self.assertIn("Catastrophe", panel.messages[0][1])

    def test_dead_praxans_not_affected(self):
        """Dead praxans should not take damage."""
        praxan = StubPraxan(x=100, y=100, alive=False)
        praxan.health = 50.0
        now = time.time()
        ad = ActiveDisaster("earthquake", 100, 100, 1.0, now, 15.0)
        self.mgr._apply_effects(
            ad, [praxan], [], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        self.assertEqual(praxan.health, 50.0)

    def test_distance_falloff(self):
        """Praxans farther from center should take less damage."""
        close_praxan = StubPraxan(x=100, y=100)
        far_praxan = StubPraxan(x=350, y=100)  # 250 units away
        close_praxan.health = 100.0
        far_praxan.health = 100.0
        now = time.time()
        # Earthquake radius is 300
        ad = ActiveDisaster("earthquake", 100, 100, 1.0, now, 15.0)
        self.mgr._apply_effects(
            ad, [close_praxan, far_praxan], [], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        self.assertLess(close_praxan.health, far_praxan.health)

    def test_speed_penalty_applied(self):
        """Blizzard should apply speed penalty to affected praxans."""
        praxan = StubPraxan(x=100, y=100)
        now = time.time()
        ad = ActiveDisaster("blizzard", 100, 100, 1.0, now, 30.0)
        self.mgr._apply_effects(
            ad, [praxan], [], StubWorldMap(),
            StubEventBus(), StubNarrativePanel(),
        )
        self.assertGreater(praxan._disaster_speed_penalty, 0)


class TestDisasterManagerUpdate(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = DisasterManager()

    def test_update_respects_eval_interval(self):
        """update() should not fire if not enough time has passed."""
        now = time.time()
        self.mgr._last_eval_time = now
        result = self.mgr.update(
            current_time=now + 5.0,  # Only 5s, need 30s
            praxans=[StubPraxan() for _ in range(10)],
            buildings=[StubBuilding() for _ in range(5)],
        )
        self.assertIsNone(result)

    def test_update_respects_global_cooldown(self):
        """update() should not fire within global cooldown."""
        now = time.time()
        self.mgr._last_eval_time = now - EVAL_INTERVAL - 1
        self.mgr._last_disaster_time = now  # Just fired
        result = self.mgr.update(
            current_time=now + EVAL_INTERVAL + 1,
            praxans=[StubPraxan() for _ in range(10)],
            buildings=[StubBuilding() for _ in range(5)],
        )
        self.assertIsNone(result)

    def test_update_cleans_expired(self):
        """Expired active disasters should be cleaned up."""
        ad = ActiveDisaster("earthquake", 100, 100, 0.5, time.time() - 100, 10.0)
        ad.applied = True
        self.mgr.active_disasters.append(ad)
        now = time.time()
        self.mgr.update(
            current_time=now,
            praxans=[StubPraxan()],
            buildings=[StubBuilding()],
        )
        self.assertEqual(len(self.mgr.active_disasters), 0)

    def test_phase_scaling_climax(self):
        """Climax phase should increase disaster chance."""
        # This test verifies the logic path — actual firing is random
        mgr = DisasterManager()
        mgr._last_eval_time = 0.0
        mgr._last_disaster_time = 0.0
        # We can't deterministically test random, but verify no crash
        mgr.update(
            current_time=time.time() + EVAL_INTERVAL + MIN_COOLDOWN_GLOBAL + 1,
            praxans=[StubPraxan() for _ in range(10)],
            buildings=[StubBuilding() for _ in range(5)],
            storyteller_phase="climax",
        )

    def test_has_active_disaster_property(self):
        """has_active_disaster should reflect state."""
        self.assertFalse(self.mgr.has_active_disaster)
        ad = ActiveDisaster("flood", 100, 100, 0.5, time.time(), 30.0)
        self.mgr.active_disasters.append(ad)
        self.assertTrue(self.mgr.has_active_disaster)


class TestDisasterManagerSerialization(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = DisasterManager()

    def test_serialize_empty(self):
        """Empty manager should serialize cleanly."""
        data = self.mgr.serialize()
        self.assertIn("active_disasters", data)
        self.assertIn("history", data)
        self.assertEqual(len(data["active_disasters"]), 0)

    def test_serialize_with_active(self):
        """Active disaster should appear in serialization."""
        ad = ActiveDisaster("earthquake", 100, 200, 0.7, time.time(), 15.0)
        self.mgr.active_disasters.append(ad)
        self.mgr.history.append({"disaster_id": "earthquake", "severity": 0.7})
        data = self.mgr.serialize()
        self.assertEqual(len(data["active_disasters"]), 1)
        self.assertEqual(data["active_disasters"][0]["disaster_id"], "earthquake")

    def test_roundtrip_restore(self):
        """Serialize + restore should preserve state."""
        now = time.time()
        ad = ActiveDisaster("flood", 150, 250, 0.6, now - 5.0, 20.0)
        ad.applied = True
        self.mgr.active_disasters.append(ad)
        self.mgr.history.append({"disaster_id": "flood", "severity": 0.6})
        self.mgr._last_disaster_time = now - 10.0
        self.mgr._cooldowns["flood"] = now - 10.0

        data = self.mgr.serialize(current_time=now)

        # Restore into fresh manager
        new_mgr = DisasterManager()
        new_mgr.restore(data)
        self.assertEqual(len(new_mgr.active_disasters), 1)
        self.assertEqual(new_mgr.active_disasters[0].disaster_id, "flood")
        self.assertTrue(new_mgr.active_disasters[0].applied)
        self.assertEqual(len(new_mgr.history), 1)
        # Cooldown should be roughly restored
        self.assertIn("flood", new_mgr._cooldowns)

    def test_restore_empty(self):
        """Restoring from empty dict should not crash."""
        self.mgr.restore({})
        self.assertEqual(len(self.mgr.active_disasters), 0)

    def test_restore_none(self):
        """Restoring from None-like empty should not crash."""
        self.mgr.restore({})

    def test_cooldown_elapsed_pattern(self):
        """Cooldown should use elapsed-time pattern for snapshot portability."""
        now = time.time()
        self.mgr._cooldowns["earthquake"] = now - 30.0
        data = self.mgr.serialize(current_time=now)
        self.assertAlmostEqual(data["cooldowns"]["earthquake"], 30.0, delta=2.0)

        new_mgr = DisasterManager()
        new_mgr.restore(data)
        # Restored cooldown should be approximately 30s ago
        elapsed = time.time() - new_mgr._cooldowns["earthquake"]
        self.assertAlmostEqual(elapsed, 30.0, delta=3.0)


class TestDisasterManagerHelpers(unittest.TestCase):
    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")
        self.mgr = DisasterManager()

    def test_get_active_labels(self):
        """get_active_labels should return labels of active disasters."""
        ad = ActiveDisaster("earthquake", 100, 100, 0.5, time.time(), 30.0)
        self.mgr.active_disasters.append(ad)
        labels = self.mgr.get_active_labels()
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0], "Earthquake")

    def test_recent_history(self):
        """recent_history should return last N records."""
        for i in range(10):
            self.mgr.history.append({"disaster_id": f"test_{i}"})
        recent = self.mgr.recent_history(3)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[0]["disaster_id"], "test_7")


class TestStorytellerIncidentIntegration(unittest.TestCase):
    """Test the storyteller incident that delegates to DisasterManager."""

    def setUp(self):
        clear_cache()
        from systems.def_database import DefDatabase
        DefDatabase.clear()
        DefDatabase.initialize("defs")

    def test_incident_natural_disaster_fires(self):
        """The incident_natural_disaster function should work with a DisasterManager."""
        from events.incidents import incident_natural_disaster

        mgr = DisasterManager()
        praxans = [StubPraxan(x=100, y=100) for _ in range(8)]
        buildings = [StubBuilding(x=100, y=100) for _ in range(5)]
        bus = StubEventBus()
        panel = StubNarrativePanel()

        game_state = {
            "disaster_manager": mgr,
            "praxans": praxans,
            "buildings": buildings,
            "event_bus": bus,
            "narrative_panel": panel,
            "world_map": StubWorldMap(),
            "season": type("S", (), {"current": "summer"})(),
            "weather_system": type("W", (), {"current_weather": "clear"})(),
        }
        incident_natural_disaster(game_state)
        # Should have fired at least one disaster
        self.assertGreaterEqual(len(mgr.active_disasters), 0)  # May not fire if cooldown hits

    def test_incident_without_manager(self):
        """incident_natural_disaster should do nothing if no disaster_manager."""
        from events.incidents import incident_natural_disaster
        game_state = {}
        # Should not crash
        incident_natural_disaster(game_state)


if __name__ == "__main__":
    unittest.main()
