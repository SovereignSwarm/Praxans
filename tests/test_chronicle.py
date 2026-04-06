"""Tests for the Legends & Chronicle system (systems/chronicle.py)."""

import unittest
import time

from systems.chronicle import (
    ChronicleManager,
    ChronicleEntry,
    get_era_def,
    get_all_era_defs,
    get_all_deed_defs,
    get_legend_tier,
    clear_cache,
    _EVAL_INTERVAL,
    _ERA_WINDOW,
    _MAX_CHRONICLE_ENTRIES,
    _ERA_MOODLET_INTERVAL,
    _LEGEND_MOODLET_INTERVAL,
)


# ---------------------------------------------------------------------------
# Stubs
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
        self.moodlets = []
        self.name = f"Praxan_{self.id}"
        self.life_stage = "adult"
        self.memory = StubMemory()
        self._pending_reputation_events = []

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

    def record(self, category=None, summary=None, emotional_weight=None,
               related_ids=None, metadata=None, **kwargs):
        self.entries.append({
            "category": category,
            "summary": summary,
            "emotional_weight": emotional_weight,
            "related_ids": related_ids or [],
            "metadata": metadata or {},
        })


class StubReputationManager:
    def __init__(self):
        self.events = []

    def record_event(self, praxan_id, event_type):
        self.events.append((praxan_id, event_type))


class StubEventBus:
    def __init__(self):
        self.events = []
        self._subs = {}

    def subscribe(self, category, handler):
        self._subs.setdefault(category, []).append(handler)

    def publish(self, event):
        self.events.append(event)
        cat = getattr(event, "category", "")
        for handler in self._subs.get(cat, []):
            handler(event)


class StubAdvisor:
    def __init__(self):
        self.observer_timeline = []


# GameEvent-like stub
class StubEvent:
    def __init__(self, category="warfare", summary="A battle occurred",
                 drama=5, timestamp=None, faction_id=None, praxan_id=None,
                 metadata=None):
        self.category = category
        self.summary = summary
        self.drama = drama
        self.timestamp = timestamp or time.time()
        self.faction_id = faction_id
        self.praxan_id = praxan_id
        self.metadata = metadata or {}


# ---------------------------------------------------------------------------
# Setup helper
# ---------------------------------------------------------------------------

def _load_defs():
    from systems.def_database import DefDatabase
    DefDatabase.clear()
    DefDatabase.initialize("defs")


# ---------------------------------------------------------------------------
# Tests — Def loading
# ---------------------------------------------------------------------------

class TestDefLoading(unittest.TestCase):
    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()

    def test_era_defs_loaded(self):
        defs = get_all_era_defs()
        self.assertGreaterEqual(len(defs), 8)

    def test_era_def_has_required_fields(self):
        edef = get_era_def("age_of_war")
        self.assertIsNotNone(edef)
        self.assertIn("dominant_categories", edef)
        self.assertIn("threshold", edef)
        self.assertIn("priority", edef)
        self.assertIn("moodlet", edef)

    def test_deed_defs_loaded(self):
        defs = get_all_deed_defs()
        self.assertGreaterEqual(len(defs), 10)

    def test_deed_def_has_required_fields(self):
        defs = get_all_deed_defs()
        for deed_id, ddef in defs.items():
            self.assertIn("required_count", ddef, f"{deed_id} missing required_count")
            self.assertIn("legend_points", ddef, f"{deed_id} missing legend_points")
            self.assertIn("event_category", ddef, f"{deed_id} missing event_category")

    def test_legend_tier_sorted_descending(self):
        # Highest tier first
        t20 = get_legend_tier(20)
        self.assertIsNotNone(t20)
        self.assertEqual(t20["id"], "legendary")

    def test_legend_tier_notable(self):
        t5 = get_legend_tier(5)
        self.assertIsNotNone(t5)
        self.assertEqual(t5["id"], "notable")

    def test_legend_tier_below_min_returns_none(self):
        self.assertIsNone(get_legend_tier(0))
        self.assertIsNone(get_legend_tier(4))

    def test_legend_tier_renowned(self):
        t12 = get_legend_tier(12)
        self.assertIsNotNone(t12)
        self.assertEqual(t12["id"], "renowned")

    def test_clear_cache_resets(self):
        defs = get_all_era_defs()
        self.assertTrue(len(defs) > 0)
        clear_cache()
        # After clear, internal cache is empty — but _load_defs re-populates
        # Just verify clear doesn't crash
        clear_cache()


# ---------------------------------------------------------------------------
# Tests — ChronicleEntry
# ---------------------------------------------------------------------------

class TestChronicleEntry(unittest.TestCase):
    def test_to_dict_round_trip(self):
        entry = ChronicleEntry(
            category="warfare",
            summary="A great battle",
            timestamp=1000.0,
            drama_weight=8,
            faction_id=1,
            praxan_id=42,
            era_id="age_of_war",
        )
        d = entry.to_dict()
        restored = ChronicleEntry.from_dict(d)
        self.assertEqual(restored.category, "warfare")
        self.assertEqual(restored.summary, "A great battle")
        self.assertEqual(restored.timestamp, 1000.0)
        self.assertEqual(restored.drama_weight, 8)
        self.assertEqual(restored.faction_id, 1)
        self.assertEqual(restored.praxan_id, 42)
        self.assertEqual(restored.era_id, "age_of_war")

    def test_optional_fields_default_none(self):
        entry = ChronicleEntry(category="birth", summary="Born", timestamp=0.0)
        d = entry.to_dict()
        self.assertNotIn("faction_id", d)
        self.assertNotIn("praxan_id", d)
        self.assertNotIn("era_id", d)


# ---------------------------------------------------------------------------
# Tests — Event recording
# ---------------------------------------------------------------------------

class TestEventRecording(unittest.TestCase):
    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()
        self.bus = StubEventBus()
        self.mgr = ChronicleManager()
        self.mgr.attach_event_bus(self.bus)

    def test_high_drama_event_recorded(self):
        """Events with drama >= 2 are chronicled."""
        evt = StubEvent(category="warfare", drama=5, timestamp=100.0)
        self.mgr._on_event(evt)
        self.assertEqual(len(self.mgr._entries), 1)
        self.assertEqual(self.mgr._entries[0].category, "warfare")

    def test_low_drama_event_ignored(self):
        """Events with drama < 2 are not chronicled."""
        evt = StubEvent(category="personal", drama=1, timestamp=100.0)
        self.mgr._on_event(evt)
        self.assertEqual(len(self.mgr._entries), 0)

    def test_praxan_deed_event_logged(self):
        """Events with praxan_id populate the deed event log."""
        evt = StubEvent(
            category="warfare", drama=5, timestamp=100.0,
            praxan_id=7,
            metadata={"type": "combat_victory"},
        )
        self.mgr._on_event(evt)
        log = self.mgr._deed_event_log.get(7, [])
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0][0], "combat_victory")

    def test_chronicle_capped_at_max(self):
        """Chronicle entries are bounded to _MAX_CHRONICLE_ENTRIES."""
        for i in range(_MAX_CHRONICLE_ENTRIES + 50):
            evt = StubEvent(category="warfare", drama=3, timestamp=float(i))
            self.mgr._on_event(evt)
        self.assertLessEqual(len(self.mgr._entries), _MAX_CHRONICLE_ENTRIES)

    def test_event_bus_subscription(self):
        """attach_event_bus subscribes to all categories."""
        from events.bus import ALL_CATEGORIES
        for cat in ALL_CATEGORIES:
            self.assertIn(cat, self.bus._subs)

    def test_deed_event_log_capped(self):
        """Per-praxan deed event log is bounded."""
        for i in range(50):
            evt = StubEvent(
                category="warfare", drama=3, timestamp=float(i),
                praxan_id=1, metadata={"type": "combat_victory"},
            )
            self.mgr._on_event(evt)
        log = self.mgr._deed_event_log.get(1, [])
        self.assertLessEqual(len(log), 30)


# ---------------------------------------------------------------------------
# Tests — Era evaluation
# ---------------------------------------------------------------------------

class TestEraEvaluation(unittest.TestCase):
    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()
        self.bus = StubEventBus()
        self.mgr = ChronicleManager()
        self.mgr.attach_event_bus(self.bus)

    def _flood_events(self, category, count=10, drama=5, base_time=1000.0):
        """Inject many events of a single category."""
        for i in range(count):
            evt = StubEvent(category=category, drama=drama, timestamp=base_time + i)
            self.mgr._on_event(evt)

    def test_default_era_is_founding(self):
        self.assertEqual(self.mgr.get_current_era(), "age_of_founding")

    def test_warfare_events_trigger_age_of_war(self):
        now = 2000.0
        self._flood_events("warfare", count=10, base_time=now - 100)
        self.mgr._last_eval_time = 0.0  # Force eval
        self.mgr.update([], current_time=now, event_bus=self.bus)
        self.assertEqual(self.mgr.get_current_era(), "age_of_war")

    def test_era_transition_publishes_event(self):
        now = 2000.0
        self._flood_events("warfare", count=10, base_time=now - 100)
        self.mgr._last_eval_time = 0.0
        self.bus.events.clear()
        self.mgr.update([], current_time=now, event_bus=self.bus)
        milestone_events = [e for e in self.bus.events if getattr(e, "category", "") == "milestone"]
        self.assertGreater(len(milestone_events), 0)

    def test_era_transition_recorded_in_history(self):
        now = 2000.0
        self._flood_events("warfare", count=10, base_time=now - 100)
        self.mgr._last_eval_time = 0.0
        self.mgr.update([], current_time=now, event_bus=self.bus)
        history = self.mgr.get_era_history()
        self.assertGreater(len(history), 0)

    def test_era_transition_logged_to_advisor(self):
        advisor = StubAdvisor()
        now = 2000.0
        self._flood_events("warfare", count=10, base_time=now - 100)
        self.mgr._last_eval_time = 0.0
        self.mgr.update([], current_time=now, event_bus=self.bus, advisor=advisor)
        self.assertGreater(len(advisor.observer_timeline), 0)

    def test_no_era_change_without_threshold(self):
        """Too few events don't trigger an era change."""
        now = 2000.0
        self._flood_events("warfare", count=1, drama=2, base_time=now - 50)
        self.mgr._last_eval_time = 0.0
        self.mgr.update([], current_time=now, event_bus=self.bus)
        self.assertEqual(self.mgr.get_current_era(), "age_of_founding")

    def test_era_label_human_readable(self):
        label = self.mgr.get_current_era_label()
        self.assertIn("Age of Founding", label)

    def test_disaster_events_trigger_plague_or_hardship(self):
        now = 2000.0
        self._flood_events("disaster", count=10, base_time=now - 100)
        self.mgr._last_eval_time = 0.0
        self.mgr.update([], current_time=now, event_bus=self.bus)
        era = self.mgr.get_current_era()
        self.assertIn(era, ("age_of_plague", "age_of_war", "age_of_schism"))

    def test_era_moodlets_applied(self):
        p = StubPraxan()
        now = 2000.0
        self._flood_events("warfare", count=10, base_time=now - 100)
        self.mgr._last_eval_time = 0.0
        self.mgr._last_era_moodlet_time = 0.0  # Force moodlet application
        self.mgr.update([p], current_time=now, event_bus=self.bus)
        moodlet_names = [m["name"] for m in p.moodlets]
        # age_of_war should give EraOfConflict
        self.assertTrue(any("Era" in name for name in moodlet_names),
                        f"Expected era moodlet, got {moodlet_names}")


# ---------------------------------------------------------------------------
# Tests — Legendary deeds
# ---------------------------------------------------------------------------

class TestLegendaryDeeds(unittest.TestCase):
    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()
        self.bus = StubEventBus()
        self.mgr = ChronicleManager()
        self.mgr.attach_event_bus(self.bus)

    def _inject_deed_events(self, praxan_id, event_type, count, base_time=1000.0):
        """Inject deed-relevant events for a praxan."""
        for i in range(count):
            evt = StubEvent(
                category="warfare" if "combat" in event_type or "raid" in event_type else "personal",
                drama=5,
                timestamp=base_time + i,
                praxan_id=praxan_id,
                metadata={"type": event_type},
            )
            self.mgr._on_event(evt)

    def test_war_hero_deed_completion(self):
        """3 combat victories should complete the war_hero deed."""
        p = StubPraxan()
        self._inject_deed_events(p.id, "combat_victory", 3)
        self.mgr._last_eval_time = 0.0
        self.mgr.update([p], current_time=2000.0)
        completed = self.mgr.get_completed_deeds(p.id)
        self.assertIn("war_hero", completed)

    def test_deed_awards_legend_points(self):
        p = StubPraxan()
        self._inject_deed_events(p.id, "combat_victory", 3)
        self.mgr._last_eval_time = 0.0
        self.mgr.update([p], current_time=2000.0)
        pts = self.mgr.get_legend_points(p.id)
        self.assertGreater(pts, 0)

    def test_deed_creates_episodic_memory(self):
        p = StubPraxan()
        self._inject_deed_events(p.id, "combat_victory", 3)
        self.mgr._last_eval_time = 0.0
        self.mgr.update([p], current_time=2000.0)
        cats = [e["category"] for e in p.memory.entries]
        self.assertIn("legendary_deed", cats)

    def test_deed_not_counted_twice(self):
        p = StubPraxan()
        self._inject_deed_events(p.id, "combat_victory", 6)
        self.mgr._last_eval_time = 0.0
        self.mgr.update([p], current_time=2000.0)
        pts1 = self.mgr.get_legend_points(p.id)
        # Evaluate again — should not re-award
        self.mgr._last_eval_time = 0.0
        self.mgr.update([p], current_time=3000.0)
        pts2 = self.mgr.get_legend_points(p.id)
        self.assertEqual(pts1, pts2)

    def test_insufficient_events_no_deed(self):
        p = StubPraxan()
        self._inject_deed_events(p.id, "combat_victory", 1)
        self.mgr._last_eval_time = 0.0
        self.mgr.update([p], current_time=2000.0)
        completed = self.mgr.get_completed_deeds(p.id)
        self.assertNotIn("war_hero", completed)

    def test_multiple_deeds_accumulate_points(self):
        p = StubPraxan()
        # War hero (3 combat victories) + great builder (5 buildings)
        self._inject_deed_events(p.id, "combat_victory", 3)
        for i in range(5):
            evt = StubEvent(
                category="building", drama=3, timestamp=1010.0 + i,
                praxan_id=p.id, metadata={"type": "building"},
            )
            self.mgr._on_event(evt)
        self.mgr._last_eval_time = 0.0
        self.mgr.update([p], current_time=2000.0)
        pts = self.mgr.get_legend_points(p.id)
        completed = self.mgr.get_completed_deeds(p.id)
        self.assertIn("war_hero", completed)
        self.assertIn("great_builder", completed)
        # war_hero=5 + great_builder=3 = 8
        self.assertEqual(pts, 8)


# ---------------------------------------------------------------------------
# Tests — Legend tiers
# ---------------------------------------------------------------------------

class TestLegendTiers(unittest.TestCase):
    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()
        self.bus = StubEventBus()
        self.mgr = ChronicleManager()
        self.mgr.attach_event_bus(self.bus)
        self.rep_mgr = StubReputationManager()

    def test_notable_tier_at_5_points(self):
        p = StubPraxan()
        self.mgr._legend_points[p.id] = 5
        self.mgr._last_eval_time = 0.0
        self.mgr.update(
            [p], reputation_manager=self.rep_mgr,
            event_bus=self.bus, current_time=2000.0,
        )
        tier = self.mgr.get_legend_tier(p.id)
        self.assertEqual(tier, "notable")

    def test_renowned_tier_at_12_points(self):
        p = StubPraxan()
        self.mgr._legend_points[p.id] = 12
        self.mgr._last_eval_time = 0.0
        self.mgr.update(
            [p], reputation_manager=self.rep_mgr,
            event_bus=self.bus, current_time=2000.0,
        )
        tier = self.mgr.get_legend_tier(p.id)
        self.assertEqual(tier, "renowned")

    def test_legendary_tier_at_20_points(self):
        p = StubPraxan()
        self.mgr._legend_points[p.id] = 20
        self.mgr._last_eval_time = 0.0
        self.mgr.update(
            [p], reputation_manager=self.rep_mgr,
            event_bus=self.bus, current_time=2000.0,
        )
        tier = self.mgr.get_legend_tier(p.id)
        self.assertEqual(tier, "legendary")

    def test_tier_transition_publishes_milestone(self):
        """Upgrading from notable→renowned fires a milestone event."""
        p = StubPraxan()
        self.mgr._legend_points[p.id] = 12
        self.mgr._legend_tiers[p.id] = "notable"  # Was notable, now has 12 pts → renowned
        self.mgr._last_eval_time = 0.0
        self.bus.events.clear()
        self.mgr.update(
            [p], reputation_manager=self.rep_mgr,
            event_bus=self.bus, current_time=2000.0,
        )
        milestone_events = [e for e in self.bus.events if getattr(e, "category", "") == "milestone"]
        self.assertGreater(len(milestone_events), 0)

    def test_tier_transition_awards_reputation(self):
        """Upgrading from notable→renowned awards became_legend reputation."""
        p = StubPraxan()
        self.mgr._legend_points[p.id] = 12
        self.mgr._legend_tiers[p.id] = "notable"
        self.mgr._last_eval_time = 0.0
        self.mgr.update(
            [p], reputation_manager=self.rep_mgr,
            event_bus=self.bus, current_time=2000.0,
        )
        self.assertTrue(any(e[1] == "became_legend" for e in self.rep_mgr.events))

    def test_tier_transition_creates_memory(self):
        """Upgrading from notable→renowned creates legend_status memory."""
        p = StubPraxan()
        self.mgr._legend_points[p.id] = 12
        self.mgr._legend_tiers[p.id] = "notable"
        self.mgr._last_eval_time = 0.0
        self.mgr.update(
            [p], reputation_manager=self.rep_mgr,
            event_bus=self.bus, current_time=2000.0,
        )
        cats = [e["category"] for e in p.memory.entries]
        self.assertIn("legend_status", cats)

    def test_first_tier_assignment_is_silent(self):
        """First tier assignment (None→notable) does not fire events."""
        p = StubPraxan()
        self.mgr._legend_points[p.id] = 5
        # No prior tier entry
        self.mgr._last_eval_time = 0.0
        self.rep_mgr.events.clear()
        self.mgr.update(
            [p], reputation_manager=self.rep_mgr,
            event_bus=self.bus, current_time=2000.0,
        )
        # Tier IS set
        self.assertEqual(self.mgr.get_legend_tier(p.id), "notable")
        # But no reputation event (first assignment is silent)
        self.assertFalse(any(e[1] == "became_legend" for e in self.rep_mgr.events))

    def test_tier_moodlets_applied(self):
        p = StubPraxan()
        self.mgr._legend_points[p.id] = 5
        self.mgr._legend_tiers[p.id] = "notable"
        self.mgr._last_eval_time = 0.0
        self.mgr._last_legend_moodlet_time = 0.0
        self.mgr.update(
            [p], reputation_manager=self.rep_mgr,
            event_bus=self.bus, current_time=2000.0,
        )
        moodlet_names = [m["name"] for m in p.moodlets]
        self.assertIn("NotableFigure", moodlet_names)

    def test_no_transition_when_same_tier(self):
        p = StubPraxan()
        self.mgr._legend_points[p.id] = 5
        self.mgr._legend_tiers[p.id] = "notable"  # Already at notable
        self.mgr._last_eval_time = 0.0
        self.rep_mgr.events.clear()
        self.mgr.update(
            [p], reputation_manager=self.rep_mgr,
            event_bus=self.bus, current_time=2000.0,
        )
        # No reputation event for staying at same tier
        self.assertEqual(len(self.rep_mgr.events), 0)

    def test_get_legend_tier_label(self):
        p = StubPraxan()
        self.mgr._legend_points[p.id] = 12
        label = self.mgr.get_legend_tier_label(p.id)
        self.assertEqual(label, "Renowned")

    def test_get_legend_tier_label_no_points(self):
        label = self.mgr.get_legend_tier_label(999)
        self.assertIsNone(label)


# ---------------------------------------------------------------------------
# Tests — Queries
# ---------------------------------------------------------------------------

class TestQueries(unittest.TestCase):
    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()
        self.mgr = ChronicleManager()

    def test_get_recent_entries(self):
        for i in range(20):
            self.mgr._entries.append(
                ChronicleEntry("warfare", f"Battle {i}", float(i), drama_weight=3)
            )
        recent = self.mgr.get_recent_entries(5)
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[-1].summary, "Battle 19")

    def test_get_high_drama_entries(self):
        self.mgr._entries.append(ChronicleEntry("warfare", "Small", 1.0, drama_weight=2))
        self.mgr._entries.append(ChronicleEntry("warfare", "Big", 2.0, drama_weight=10))
        self.mgr._entries.append(ChronicleEntry("warfare", "Medium", 3.0, drama_weight=5))
        top = self.mgr.get_high_drama_entries(2)
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0].summary, "Big")

    def test_get_all_legends(self):
        self.mgr._legend_points[1] = 5
        self.mgr._legend_points[2] = 12
        self.mgr._legend_points[3] = 0
        self.mgr._completed_deeds[1] = {"war_hero"}
        legends = self.mgr.get_all_legends()
        self.assertIn(1, legends)
        self.assertIn(2, legends)
        self.assertNotIn(3, legends)
        self.assertEqual(legends[1]["tier"], "notable")

    def test_get_completed_deeds_empty(self):
        self.assertEqual(self.mgr.get_completed_deeds(999), [])


# ---------------------------------------------------------------------------
# Tests — Death cleanup
# ---------------------------------------------------------------------------

class TestDeathCleanup(unittest.TestCase):
    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()
        self.mgr = ChronicleManager()

    def test_remove_praxan_clears_deed_log(self):
        self.mgr._deed_event_log[42] = [("combat_victory", 100.0)]
        self.mgr._legend_points[42] = 10
        self.mgr.remove_praxan(42)
        self.assertNotIn(42, self.mgr._deed_event_log)

    def test_remove_praxan_preserves_legend_data(self):
        self.mgr._legend_points[42] = 10
        self.mgr._legend_tiers[42] = "notable"
        self.mgr._completed_deeds[42] = {"war_hero"}
        self.mgr.remove_praxan(42)
        # Legend data should still exist
        self.assertEqual(self.mgr.get_legend_points(42), 10)
        self.assertEqual(self.mgr.get_legend_tier(42), "notable")
        self.assertIn("war_hero", self.mgr.get_completed_deeds(42))


# ---------------------------------------------------------------------------
# Tests — Serialization
# ---------------------------------------------------------------------------

class TestSerialization(unittest.TestCase):
    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()
        self.bus = StubEventBus()
        self.mgr = ChronicleManager()
        self.mgr.attach_event_bus(self.bus)

    def test_serialize_round_trip(self):
        now = 5000.0
        # Set up state
        self.mgr._current_era = "age_of_war"
        self.mgr._era_start_time = 4000.0
        self.mgr._era_history = [("age_of_founding", 0.0, 4000.0), ("age_of_war", 4000.0, None)]
        self.mgr._legend_points = {1: 10, 2: 5}
        self.mgr._legend_tiers = {1: "notable", 2: "notable"}
        self.mgr._completed_deeds = {1: {"war_hero", "great_builder"}}
        self.mgr._deed_event_log = {1: [("combat_victory", 4500.0), ("combat_victory", 4600.0)]}
        self.mgr._deed_counts = {1: {"war_hero": 3}}
        self.mgr._entries.append(ChronicleEntry("warfare", "Battle", 4500.0, 5))
        self.mgr._last_eval_time = 4900.0
        self.mgr._last_era_moodlet_time = 4800.0
        self.mgr._last_legend_moodlet_time = 4700.0

        data = self.mgr.serialize(current_time=now)

        # Restore into fresh manager
        mgr2 = ChronicleManager()
        restore_time = 6000.0
        mgr2.restore(data, current_time=restore_time)

        self.assertEqual(mgr2._current_era, "age_of_war")
        self.assertEqual(mgr2._legend_points, {1: 10, 2: 5})
        self.assertEqual(mgr2._legend_tiers, {1: "notable", 2: "notable"})
        self.assertIn("war_hero", mgr2._completed_deeds.get(1, set()))
        self.assertIn("great_builder", mgr2._completed_deeds.get(1, set()))
        self.assertEqual(len(mgr2._entries), 1)
        self.assertEqual(mgr2._entries[0].category, "warfare")

    def test_serialize_timestamps_relative(self):
        now = 1000.0
        self.mgr._last_eval_time = 950.0
        data = self.mgr.serialize(current_time=now)
        self.assertAlmostEqual(data["last_eval_seconds_ago"], 50.0, places=1)

    def test_restore_timestamps_absolute(self):
        now = 1000.0
        data = {
            "last_eval_seconds_ago": 50.0,
            "last_era_moodlet_seconds_ago": 100.0,
            "last_legend_moodlet_seconds_ago": 200.0,
        }
        self.mgr.restore(data, current_time=now)
        self.assertAlmostEqual(self.mgr._last_eval_time, 950.0, places=1)

    def test_restore_deed_event_log(self):
        data = {
            "deed_event_log": {
                "1": [
                    {"type": "combat_victory", "seconds_ago": 100.0},
                    {"type": "combat_victory", "seconds_ago": 200.0},
                ],
            },
        }
        self.mgr.restore(data, current_time=1000.0)
        log = self.mgr._deed_event_log.get(1, [])
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0][0], "combat_victory")
        self.assertAlmostEqual(log[0][1], 900.0, places=1)

    def test_serialize_era_history(self):
        now = 5000.0
        self.mgr._era_history = [("age_of_founding", 0.0, 3000.0)]
        data = self.mgr.serialize(current_time=now)
        self.assertEqual(len(data["era_history"]), 1)
        self.assertEqual(data["era_history"][0]["era_id"], "age_of_founding")
        self.assertAlmostEqual(data["era_history"][0]["start_seconds_ago"], 5000.0, places=1)

    def test_empty_serialize(self):
        data = self.mgr.serialize(current_time=1000.0)
        self.assertEqual(data["current_era"], "age_of_founding")
        self.assertEqual(data["entries"], [])


# ---------------------------------------------------------------------------
# Tests — Update throttling
# ---------------------------------------------------------------------------

class TestUpdateThrottling(unittest.TestCase):
    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()
        self.mgr = ChronicleManager()

    def test_update_skipped_within_interval(self):
        self.mgr._last_eval_time = 1000.0
        self.mgr._current_era = "age_of_founding"
        # Try to update within the 30s interval
        self.mgr.update([], current_time=1010.0)
        # Era should not change
        self.assertEqual(self.mgr.get_current_era(), "age_of_founding")

    def test_update_runs_after_interval(self):
        self.mgr._last_eval_time = 0.0
        self.mgr.update([], current_time=_EVAL_INTERVAL + 1)
        # Should have updated last_eval_time
        self.assertGreater(self.mgr._last_eval_time, 0.0)


# ---------------------------------------------------------------------------
# Tests — Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()
        self.bus = StubEventBus()
        self.mgr = ChronicleManager()
        self.mgr.attach_event_bus(self.bus)

    def test_update_with_dead_praxan_skipped(self):
        p = StubPraxan()
        p.alive = False
        self.mgr._last_eval_time = 0.0
        # Should not crash
        self.mgr.update([p], current_time=2000.0)

    def test_update_with_empty_praxans(self):
        self.mgr._last_eval_time = 0.0
        self.mgr.update([], current_time=2000.0)

    def test_attach_none_event_bus(self):
        mgr = ChronicleManager()
        mgr.attach_event_bus(None)  # Should not crash

    def test_praxan_without_memory(self):
        """Deed completion on a praxan without memory attribute."""
        p = StubPraxan()
        p.memory = None
        self.mgr._deed_event_log[p.id] = [("combat_victory", 1000.0)] * 5
        self.mgr._last_eval_time = 0.0
        # Should not crash
        self.mgr.update([p], current_time=2000.0)

    def test_legend_tier_label_for_dead_praxan(self):
        """Legend data persists after death."""
        self.mgr._legend_points[99] = 20
        label = self.mgr.get_legend_tier_label(99)
        self.assertEqual(label, "Legendary")


# ---------------------------------------------------------------------------
# Tests — Full integration scenario
# ---------------------------------------------------------------------------

class TestFullIntegration(unittest.TestCase):
    """End-to-end scenario: praxan earns deeds, reaches legend tier."""

    def setUp(self):
        StubPraxan._next_id = 0
        clear_cache()
        _load_defs()
        self.bus = StubEventBus()
        self.mgr = ChronicleManager()
        self.mgr.attach_event_bus(self.bus)
        self.rep_mgr = StubReputationManager()
        self.advisor = StubAdvisor()

    def test_praxan_becomes_notable_through_deeds(self):
        p = StubPraxan()

        # Earn war_hero: 3 combat victories = 5 legend points
        for i in range(3):
            evt = StubEvent(
                category="warfare", drama=5, timestamp=1000.0 + i,
                praxan_id=p.id, metadata={"type": "combat_victory"},
            )
            self.mgr._on_event(evt)

        # First update: evaluate deeds + tier (first tier assignment is silent)
        self.mgr._last_eval_time = 0.0
        self.mgr._last_legend_moodlet_time = 0.0
        self.mgr.update(
            [p],
            reputation_manager=self.rep_mgr,
            event_bus=self.bus,
            current_time=2000.0,
            advisor=self.advisor,
        )

        # War hero completed
        self.assertIn("war_hero", self.mgr.get_completed_deeds(p.id))
        self.assertEqual(self.mgr.get_legend_points(p.id), 5)
        self.assertEqual(self.mgr.get_legend_tier(p.id), "notable")

        # Moodlet applied (legend moodlets work even on first assignment)
        moodlet_names = [m["name"] for m in p.moodlets]
        self.assertIn("NotableFigure", moodlet_names)

        # Deed memory recorded
        cats = [e["category"] for e in p.memory.entries]
        self.assertIn("legendary_deed", cats)

    def test_praxan_upgrades_tier_fires_events(self):
        """Earning enough deeds to upgrade notable→renowned fires events."""
        p = StubPraxan()

        # Pre-seed: already notable with 5 points from war_hero
        self.mgr._legend_points[p.id] = 5
        self.mgr._legend_tiers[p.id] = "notable"
        self.mgr._completed_deeds[p.id] = {"war_hero"}

        # Earn great_builder: 5 building events = 3 more legend points → total 8
        # Plus great_healer: 4 healed_other = 4 more → total 12 → renowned
        for i in range(5):
            evt = StubEvent(
                category="building", drama=3, timestamp=3000.0 + i,
                praxan_id=p.id, metadata={"type": "building"},
            )
            self.mgr._on_event(evt)
        for i in range(4):
            evt = StubEvent(
                category="personal", drama=3, timestamp=3010.0 + i,
                praxan_id=p.id, metadata={"type": "healed_other"},
            )
            self.mgr._on_event(evt)

        self.mgr._last_eval_time = 0.0
        self.mgr._last_legend_moodlet_time = 0.0
        self.rep_mgr.events.clear()
        self.bus.events.clear()
        self.mgr.update(
            [p],
            reputation_manager=self.rep_mgr,
            event_bus=self.bus,
            current_time=4000.0,
            advisor=self.advisor,
        )

        # Tier upgraded to renowned (5 + 3 + 4 = 12)
        self.assertEqual(self.mgr.get_legend_tier(p.id), "renowned")

        # Reputation event fired
        self.assertTrue(any(e[1] == "became_legend" for e in self.rep_mgr.events))

        # Legend_status memory
        cats = [e["category"] for e in p.memory.entries]
        self.assertIn("legend_status", cats)

        # Advisor timeline updated
        self.assertGreater(len(self.advisor.observer_timeline), 0)


if __name__ == "__main__":
    unittest.main()
