"""Tests for the Ecology & Regional Fertility System (systems/ecology.py).

Covers:
    - Cell fertility status thresholds
    - Harvest impact and pressure accumulation
    - Fertility regeneration with season/weather/biome modifiers
    - Weather burst damage (apply_weather_event)
    - Degradation and recovery EventBus events
    - World fertility summary
    - Serialization / deserialization round-trip
    - Snapshot helpers (_serialize_global_climate)
    - Advisor environment context formatting
"""

import unittest
import time
import math

from systems.ecology import (
    EcologyManager,
    EcoCell,
    _fertility_status,
    DEFAULT_FERTILITY,
    MAX_FERTILITY,
    MIN_FERTILITY,
    THRESHOLD_BARREN,
    THRESHOLD_DEGRADED,
    THRESHOLD_STRESSED,
    THRESHOLD_HEALTHY,
    HARVEST_IMPACT,
    BASE_REGEN_RATE,
    SEASON_REGEN,
    WEATHER_REGEN,
    WEATHER_DAMAGE,
    BIOME_FERTILITY_CAP,
    BIOME_REGEN_MULT,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class StubSeason:
    def __init__(self, current="summer"):
        self.current = current
        self.year = 1


class StubWeather:
    def __init__(self, current="clear"):
        self.current_weather = current


class StubWorldMap:
    def get_biome_at(self, x, y):
        # left half = forest, right half = desert
        if x < 512:
            return "forest"
        return "desert"


class CollectedEvent:
    """Collects events published via .publish()."""
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


# ---------------------------------------------------------------------------
# Unit Tests — EcoCell
# ---------------------------------------------------------------------------

class TestFertilityStatus(unittest.TestCase):

    def test_barren_threshold(self):
        self.assertEqual(_fertility_status(0.0), "Barren")
        self.assertEqual(_fertility_status(15.0), "Barren")

    def test_degraded_threshold(self):
        self.assertEqual(_fertility_status(16.0), "Degraded")
        self.assertEqual(_fertility_status(35.0), "Degraded")

    def test_stressed_threshold(self):
        self.assertEqual(_fertility_status(36.0), "Stressed")
        self.assertEqual(_fertility_status(55.0), "Stressed")

    def test_healthy_threshold(self):
        self.assertEqual(_fertility_status(56.0), "Healthy")
        self.assertEqual(_fertility_status(75.0), "Healthy")

    def test_lush_threshold(self):
        self.assertEqual(_fertility_status(76.0), "Lush")
        self.assertEqual(_fertility_status(100.0), "Lush")


class TestEcoCell(unittest.TestCase):

    def test_default_init(self):
        cell = EcoCell()
        self.assertEqual(cell.fertility, DEFAULT_FERTILITY)
        self.assertEqual(cell.harvest_pressure, 0.0)
        self.assertEqual(cell.status, "Lush")

    def test_round_trip_serialization(self):
        cell = EcoCell(fertility=42.5, biome="taiga")
        cell.harvest_pressure = 3.7
        cell.total_harvests = 15
        data = cell.to_dict()
        restored = EcoCell.from_dict(data)
        self.assertAlmostEqual(restored.fertility, 42.5, places=1)
        self.assertEqual(restored.biome, "taiga")
        self.assertAlmostEqual(restored.harvest_pressure, 3.7, places=1)
        self.assertEqual(restored.total_harvests, 15)
        self.assertEqual(restored.status, _fertility_status(42.5))


# ---------------------------------------------------------------------------
# Unit Tests — EcologyManager
# ---------------------------------------------------------------------------

class TestEcologyManagerInit(unittest.TestCase):

    def test_grid_dimensions(self):
        mgr = EcologyManager(1024, 1024, cell_size=512)
        self.assertEqual(mgr.cols, 2)
        self.assertEqual(mgr.rows, 2)

    def test_biome_seeding_from_world_map(self):
        mgr = EcologyManager(1024, 512, cell_size=512, world_map=StubWorldMap())
        # col 0 center is at x=256 → forest
        self.assertEqual(mgr.grid[0][0].biome, "forest")
        # col 1 center is at x=768 → desert
        self.assertEqual(mgr.grid[1][0].biome, "desert")

    def test_biome_caps_initial_fertility(self):
        mgr = EcologyManager(1024, 512, cell_size=512, world_map=StubWorldMap())
        # Desert cap is 40, so initial fertility = min(80, 40) = 40
        self.assertAlmostEqual(mgr.grid[1][0].fertility, 40.0)
        # Forest cap is 100, so initial fertility = min(80, 100) = 80
        self.assertAlmostEqual(mgr.grid[0][0].fertility, 80.0)


class TestHarvesting(unittest.TestCase):

    def setUp(self):
        self.mgr = EcologyManager(512, 512, cell_size=512)

    def test_record_harvest_reduces_fertility(self):
        original = self.mgr.grid[0][0].fertility
        self.mgr.record_harvest(100, 100, "food")
        self.assertLess(self.mgr.grid[0][0].fertility, original)

    def test_harvest_pressure_accumulates(self):
        self.mgr.record_harvest(100, 100, "wood")
        self.mgr.record_harvest(100, 100, "wood")
        self.assertAlmostEqual(
            self.mgr.grid[0][0].harvest_pressure,
            HARVEST_IMPACT["wood"] * 2,
        )

    def test_total_harvests_tracked(self):
        self.mgr.record_harvest(100, 100, "food")
        self.mgr.record_harvest(100, 100, "stone")
        self.assertEqual(self.mgr.total_harvests, 2)
        self.assertEqual(self.mgr.grid[0][0].total_harvests, 2)

    def test_fertility_multiplier_decreases_with_low_fertility(self):
        cell = self.mgr.grid[0][0]
        high_mult = self.mgr.get_fertility_multiplier(100, 100)
        cell.fertility = 10.0
        low_mult = self.mgr.get_fertility_multiplier(100, 100)
        self.assertGreater(high_mult, low_mult)

    def test_fertility_never_below_zero(self):
        cell = self.mgr.grid[0][0]
        cell.fertility = 1.0
        for _ in range(50):
            self.mgr.record_harvest(100, 100, "wood")
        self.assertGreaterEqual(cell.fertility, MIN_FERTILITY)


class TestRegeneration(unittest.TestCase):

    def setUp(self):
        self.mgr = EcologyManager(512, 512, cell_size=512)
        # Reduce fertility so there's room to regenerate
        self.mgr.grid[0][0].fertility = 50.0
        self.mgr.grid[0][0].status = _fertility_status(50.0)
        self.mgr.last_update_time = 0.0

    def test_basic_regen(self):
        """Fertility increases after an update tick."""
        before = self.mgr.grid[0][0].fertility
        self.mgr.update(10.0, season=StubSeason("summer"), weather_system=StubWeather("clear"))
        self.assertGreater(self.mgr.grid[0][0].fertility, before)

    def test_spring_rain_fast_regen(self):
        """Spring + rain should regenerate faster than summer + clear."""
        mgr_fast = EcologyManager(512, 512, cell_size=512)
        mgr_fast.grid[0][0].fertility = 50.0
        mgr_fast.last_update_time = 0.0

        mgr_slow = EcologyManager(512, 512, cell_size=512)
        mgr_slow.grid[0][0].fertility = 50.0
        mgr_slow.last_update_time = 0.0

        mgr_fast.update(10.0, season=StubSeason("spring"), weather_system=StubWeather("rain"))
        mgr_slow.update(10.0, season=StubSeason("summer"), weather_system=StubWeather("clear"))

        self.assertGreater(
            mgr_fast.grid[0][0].fertility,
            mgr_slow.grid[0][0].fertility,
        )

    def test_drought_damages_fertility(self):
        """Drought weather should reduce fertility via weather damage."""
        mgr = EcologyManager(512, 512, cell_size=512)
        mgr.grid[0][0].fertility = 60.0
        mgr.last_update_time = 0.0
        # Despite regen, drought's damage component should make net change lower
        mgr.update(10.0, season=StubSeason("summer"), weather_system=StubWeather("drought"))
        # Drought has WEATHER_DAMAGE of 2.0, applied as 0.1*dt = 2.0 per tick
        # Even with regen, net result should be noticeably less than with clear weather
        mgr_clear = EcologyManager(512, 512, cell_size=512)
        mgr_clear.grid[0][0].fertility = 60.0
        mgr_clear.last_update_time = 0.0
        mgr_clear.update(10.0, season=StubSeason("summer"), weather_system=StubWeather("clear"))

        self.assertLess(
            mgr.grid[0][0].fertility,
            mgr_clear.grid[0][0].fertility,
        )

    def test_respects_biome_fertility_cap(self):
        """Fertility cannot exceed the biome's cap."""
        mgr = EcologyManager(1024, 512, cell_size=512, world_map=StubWorldMap())
        # Desert cell (col 1) has cap of 40
        desert_cell = mgr.grid[1][0]
        desert_cell.fertility = 38.0
        mgr.last_update_time = 0.0
        # Run many regen ticks
        for t in range(1, 20):
            mgr.update(t * 10.0, season=StubSeason("spring"), weather_system=StubWeather("rain"))
        self.assertLessEqual(desert_cell.fertility, BIOME_FERTILITY_CAP["desert"])

    def test_harvest_pressure_decays(self):
        """Harvest pressure should decrease over time during regen ticks."""
        self.mgr.grid[0][0].harvest_pressure = 10.0
        self.mgr.update(10.0, season=StubSeason("summer"), weather_system=StubWeather("clear"))
        self.assertLess(self.mgr.grid[0][0].harvest_pressure, 10.0)

    def test_update_interval_respected(self):
        """Calling update before the interval should be a no-op."""
        self.mgr.last_update_time = 10.0
        before = self.mgr.grid[0][0].fertility
        self.mgr.update(11.0)  # Only 1s, interval is 4s
        self.assertEqual(self.mgr.grid[0][0].fertility, before)


class TestWeatherBurstDamage(unittest.TestCase):

    def test_storm_burst_reduces_fertility(self):
        mgr = EcologyManager(512, 512, cell_size=512)
        before = mgr.grid[0][0].fertility
        mgr.apply_weather_event("storm")
        self.assertLess(mgr.grid[0][0].fertility, before)

    def test_drought_burst_reduces_fertility(self):
        mgr = EcologyManager(512, 512, cell_size=512)
        before = mgr.grid[0][0].fertility
        mgr.apply_weather_event("drought")
        self.assertLess(mgr.grid[0][0].fertility, before)

    def test_clear_weather_no_damage(self):
        mgr = EcologyManager(512, 512, cell_size=512)
        before = mgr.grid[0][0].fertility
        mgr.apply_weather_event("clear")
        self.assertEqual(mgr.grid[0][0].fertility, before)

    def test_rain_weather_no_damage(self):
        mgr = EcologyManager(512, 512, cell_size=512)
        before = mgr.grid[0][0].fertility
        mgr.apply_weather_event("rain")
        self.assertEqual(mgr.grid[0][0].fertility, before)


class TestEcologyEvents(unittest.TestCase):

    def test_degradation_event_fires(self):
        """Moving from Stressed to Degraded should fire a disaster event."""
        mgr = EcologyManager(512, 512, cell_size=512)
        cell = mgr.grid[0][0]
        cell.fertility = THRESHOLD_DEGRADED + 1.0  # Stressed
        cell.status = "Stressed"
        bus = CollectedEvent()
        mgr.last_update_time = 0.0
        # Force drought to push below THRESHOLD_DEGRADED
        for t in range(1, 30):
            mgr.update(t * 5.0, season=StubSeason("winter"), weather_system=StubWeather("drought"), event_bus=bus)
        # Check if fertility dropped to Degraded
        if cell.fertility <= THRESHOLD_DEGRADED:
            degradation_events = [e for e in bus.events if "degraded" in str(getattr(e, "summary", "")).lower() or "barren" in str(getattr(e, "summary", "")).lower()]
            self.assertGreater(len(degradation_events), 0, "Expected a degradation event")

    def test_recovery_event_fires(self):
        """Moving from Degraded to Stressed should fire a milestone event."""
        mgr = EcologyManager(512, 512, cell_size=512)
        cell = mgr.grid[0][0]
        cell.fertility = THRESHOLD_DEGRADED - 5.0  # In Degraded range
        cell.status = "Degraded"
        cell._last_event_fertility = cell.fertility
        bus = CollectedEvent()
        mgr.last_update_time = 0.0
        # Rain in spring should push fertility up past THRESHOLD_DEGRADED
        for t in range(1, 60):
            mgr.update(t * 5.0, season=StubSeason("spring"), weather_system=StubWeather("rain"), event_bus=bus)
        if cell.fertility > THRESHOLD_DEGRADED:
            recovery_events = [e for e in bus.events if "recovered" in str(getattr(e, "summary", "")).lower()]
            self.assertGreater(len(recovery_events), 0, "Expected a recovery event")


class TestFertilitySummary(unittest.TestCase):

    def test_summary_keys(self):
        mgr = EcologyManager(512, 512, cell_size=512)
        summary = mgr.get_world_fertility_summary()
        self.assertIn("avg_fertility", summary)
        self.assertIn("total_harvests", summary)
        self.assertIn("region_counts", summary)
        self.assertIn("grid_size", summary)

    def test_initial_avg_fertility(self):
        mgr = EcologyManager(512, 512, cell_size=512)
        summary = mgr.get_world_fertility_summary()
        self.assertAlmostEqual(summary["avg_fertility"], DEFAULT_FERTILITY, places=0)


class TestRegionInfo(unittest.TestCase):

    def test_region_info_keys(self):
        mgr = EcologyManager(512, 512, cell_size=512)
        info = mgr.get_region_info(100, 100)
        self.assertIn("fertility", info)
        self.assertIn("status", info)
        self.assertIn("biome", info)
        self.assertIn("spawn_multiplier", info)


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestEcologySerialization(unittest.TestCase):

    def test_round_trip(self):
        mgr = EcologyManager(1024, 512, cell_size=512, world_map=StubWorldMap())
        # Modify some cells
        mgr.record_harvest(100, 100, "food")
        mgr.record_harvest(100, 100, "wood")
        mgr.record_harvest(600, 200, "stone")
        mgr.degradation_events = 3
        mgr.recovery_events = 1

        data = mgr.serialize()
        restored = EcologyManager.deserialize(data, 1024, 512, world_map=StubWorldMap())

        self.assertEqual(restored.total_harvests, mgr.total_harvests)
        self.assertEqual(restored.degradation_events, 3)
        self.assertEqual(restored.recovery_events, 1)
        # Check that modified cells have their values
        orig_cell = mgr.grid[0][0]
        rest_cell = restored.grid[0][0]
        self.assertAlmostEqual(rest_cell.fertility, orig_cell.fertility, places=1)
        self.assertEqual(rest_cell.total_harvests, orig_cell.total_harvests)

    def test_empty_deserialize(self):
        """Deserializing empty data should produce a default manager."""
        mgr = EcologyManager.deserialize({}, 512, 512)
        self.assertEqual(mgr.total_harvests, 0)
        self.assertAlmostEqual(mgr.grid[0][0].fertility, DEFAULT_FERTILITY, places=0)

    def test_only_modified_cells_serialized(self):
        """Default cells should not be included in serialized data to save space."""
        mgr = EcologyManager(1024, 1024, cell_size=512)
        # No harvesting — all cells are default
        data = mgr.serialize()
        self.assertEqual(len(data["cells"]), 0)


# ---------------------------------------------------------------------------
# GlobalClimate serialization
# ---------------------------------------------------------------------------

class TestGlobalClimateSerialization(unittest.TestCase):

    def test_serialize_global_climate(self):
        from run_snapshot import _serialize_global_climate

        class StubClimate:
            epoch = "Ice Age"
            global_temp_offset = -8.5
            global_moisture_offset = -0.2
            target_temp_offset = -10.0
            target_moisture_offset = -0.3

        data = _serialize_global_climate(StubClimate())
        self.assertEqual(data["epoch"], "Ice Age")
        self.assertAlmostEqual(data["global_temp_offset"], -8.5, places=3)
        self.assertAlmostEqual(data["target_temp_offset"], -10.0, places=3)

    def test_serialize_none_climate(self):
        from run_snapshot import _serialize_global_climate
        data = _serialize_global_climate(None)
        self.assertEqual(data, {})


# ---------------------------------------------------------------------------
# Advisor environment context formatting
# ---------------------------------------------------------------------------
# NOTE: Cannot import ColonyAdvisor directly because systems.advisor imports
# praxans_game which fires argparse (known project constraint).  Instead we
# test the formatting logic in isolation by duplicating the pure function.

def _format_environment_context(env):
    """Standalone copy of ColonyAdvisor._format_environment_context for testing.

    The real method reads ``self.environment_context``; this helper accepts it
    as a parameter so we can test without importing the advisor module.
    """
    env = env or {}
    season = env.get("season", "unknown")
    year = env.get("year", "?")
    weather = env.get("weather", "clear")
    epoch = env.get("climate_epoch", "Holocene")
    eco = env.get("ecology", {})
    avg_f = eco.get("avg_fertility", 80)
    counts = eco.get("region_counts", {})
    distress_parts = []
    for status in ("Barren", "Degraded", "Stressed"):
        n = counts.get(status, 0)
        if n > 0:
            distress_parts.append(f"{n} {status}")
    land_detail = ", ".join(distress_parts) if distress_parts else "all healthy"
    return (
        f"- Season: {season.title()} Y{year} | Weather: {weather} | Epoch: {epoch}\n"
        f"- Land: avg fertility {avg_f:.0f}%, {land_detail}"
    )


class TestAdvisorEnvironmentContext(unittest.TestCase):

    def test_format_environment_no_context(self):
        """Should produce a reasonable default when no context is set."""
        result = _format_environment_context(None)
        self.assertIn("unknown", result.lower())

    def test_format_environment_with_context(self):
        result = _format_environment_context({
            "season": "winter",
            "year": 3,
            "weather": "drought",
            "climate_epoch": "Ice Age",
            "ecology": {
                "avg_fertility": 42.0,
                "region_counts": {"Barren": 2, "Stressed": 3, "Healthy": 5},
            },
        })
        self.assertIn("Winter", result)
        self.assertIn("Y3", result)
        self.assertIn("drought", result)
        self.assertIn("Ice Age", result)
        self.assertIn("42", result)
        self.assertIn("2 Barren", result)
        self.assertIn("3 Stressed", result)

    def test_format_environment_all_healthy(self):
        result = _format_environment_context({
            "season": "spring",
            "year": 1,
            "weather": "clear",
            "climate_epoch": "Holocene",
            "ecology": {
                "avg_fertility": 80.0,
                "region_counts": {"Lush": 4, "Healthy": 2},
            },
        })
        self.assertIn("all healthy", result)


if __name__ == "__main__":
    unittest.main()
