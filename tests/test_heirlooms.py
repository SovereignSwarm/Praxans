"""Tests for the Heirloom & Legacy Artifact System (systems/heirlooms.py).

Covers:
- HeirloomTypeDef / HeirloomEventDef loading from DefDatabase
- Heirloom creation (named weapons, armor, tools, banners, memorials)
- Procedural name generation
- Legend score accumulation from events
- Stat bonus calculation (capped by type def)
- Cohesion bonus for faction relics
- Inheritance on death (partner → child → faction leader → vault)
- Faction relic ascension at legend threshold
- Heirloom looting during warfare
- Bearer moodlets (ancestral, relic)
- Serialization / restoration
- EventBus integration (death, warfare, disaster)
- Faction cap enforcement
- Edge cases (no heir, dead owner, empty factions)
"""

import time
import unittest
from unittest.mock import MagicMock

from events.bus import (
    CATEGORY_CULTURAL_SHIFT,
    CATEGORY_DEATH,
    CATEGORY_DISASTER,
    CATEGORY_WARFARE,
    EventBus,
    GameEvent,
)
from systems.def_database import DefDatabase
from systems.heirlooms import (
    HeirloomManager,
    Heirloom,
    clear_cache,
    generate_heirloom_name,
    get_all_heirloom_type_defs,
    get_heirloom_type_def,
    get_heirloom_event_def,
    EVAL_INTERVAL,
    MAX_HEIRLOOMS_PER_FACTION,
    _get_next_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockPraxan:
    def __init__(self, pid=0, x=0.0, y=0.0, faction_id=0, alive=True):
        self.id = pid
        self.x = x
        self.y = y
        self.alive = alive
        self.name = f"Praxan_{pid}"
        self.faction_id = faction_id
        self.personality = {"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5}
        self.traits = []
        self.bonds = {}
        self.opinions = {}
        self.relationships = {}
        self.moodlets = []
        self.equipment = {"weapon": None, "armor": None}
        self._pending_reputation_events = []
        self._pending_heirloom_events = []
        self.episodic_memory = MagicMock()

    def add_moodlet(self, name, value, duration, current_time):
        self.moodlets.append({
            "name": name, "value": value,
            "duration": duration, "start_time": current_time,
        })


class MockFaction:
    def __init__(self, fid=0, leader_id=None):
        self.id = fid
        self.leader = None
        if leader_id is not None:
            self.leader = MagicMock()
            self.leader.id = leader_id


class MockFactionManager:
    def __init__(self, factions=None):
        self.factions = factions or []


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestDefLoading(unittest.TestCase):
    """HeirloomTypeDef and HeirloomEventDef load from DefDatabase."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_type_defs_loaded(self):
        defs = get_all_heirloom_type_defs()
        self.assertGreaterEqual(len(defs), 5)
        self.assertIn("named_weapon", defs)
        self.assertIn("named_armor", defs)
        self.assertIn("founders_banner", defs)
        self.assertIn("masterwork_tool", defs)
        self.assertIn("memorial_stone", defs)

    def test_type_def_fields(self):
        weapon = get_heirloom_type_def("named_weapon")
        self.assertIsNotNone(weapon)
        self.assertEqual(weapon["category"], "weapon")
        self.assertEqual(weapon["min_quality"], "Masterwork")
        self.assertGreater(weapon["legend_base"], 0)
        self.assertIn("inheritance_priority", weapon)

    def test_event_defs_loaded(self):
        ev = get_heirloom_event_def("created")
        self.assertIsNotNone(ev)
        self.assertGreater(ev["legend_value"], 0)

    def test_all_event_defs_have_legend_value(self):
        for eid in ("created", "inherited", "used_in_battle",
                     "owner_died_heroically", "looted", "faction_relic_ascended"):
            ev = get_heirloom_event_def(eid)
            self.assertIsNotNone(ev, f"Missing HeirloomEventDef: {eid}")
            self.assertIn("legend_value", ev)


class TestNameGeneration(unittest.TestCase):
    """Procedural heirloom name generation."""

    def test_deterministic(self):
        name1 = generate_heirloom_name("weapon", creator_id=42, created_at=100.0)
        name2 = generate_heirloom_name("weapon", creator_id=42, created_at=100.0)
        self.assertEqual(name1, name2)

    def test_different_seeds(self):
        name1 = generate_heirloom_name("weapon", creator_id=1, created_at=100.0)
        name2 = generate_heirloom_name("weapon", creator_id=2, created_at=100.0)
        # Different seeds should usually produce different names (not guaranteed but very likely)
        # Just check they're valid strings
        self.assertTrue(len(name1) > 3)
        self.assertTrue(len(name2) > 3)

    def test_categories_generate_valid_names(self):
        for cat in ("weapon", "armor", "tool", "relic", "memorial"):
            name = generate_heirloom_name(cat, creator_id=7, created_at=50.0)
            self.assertIsInstance(name, str)
            self.assertGreater(len(name), 3)


class TestHeirloomDataModel(unittest.TestCase):
    """Heirloom dataclass methods."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_stat_bonus_scales_with_legend(self):
        h = Heirloom(
            heirloom_id=1, name="Test", type_id="named_weapon",
            category="weapon", creator_id=1, creator_name="Tester",
            created_at=0.0, owner_id=1, faction_id=0,
            legend_score=50.0, is_faction_relic=False, history=[],
        )
        bonus = h.stat_bonus()
        self.assertGreater(bonus, 0.0)

    def test_stat_bonus_capped(self):
        h = Heirloom(
            heirloom_id=1, name="Test", type_id="named_weapon",
            category="weapon", creator_id=1, creator_name="Tester",
            created_at=0.0, owner_id=1, faction_id=0,
            legend_score=99999.0, is_faction_relic=False, history=[],
        )
        weapon_def = get_heirloom_type_def("named_weapon")
        max_bonus = weapon_def["max_stat_bonus"]
        self.assertAlmostEqual(h.stat_bonus(), max_bonus)

    def test_cohesion_bonus_only_for_relics(self):
        h = Heirloom(
            heirloom_id=1, name="Test", type_id="founders_banner",
            category="relic", creator_id=1, creator_name="Tester",
            created_at=0.0, owner_id=1, faction_id=0,
            legend_score=50.0, is_faction_relic=False, history=[],
        )
        self.assertEqual(h.cohesion_bonus(), 0.0)
        h.is_faction_relic = True
        self.assertGreater(h.cohesion_bonus(), 0.0)

    def test_add_history_event_increases_legend(self):
        h = Heirloom(
            heirloom_id=1, name="Test", type_id="named_weapon",
            category="weapon", creator_id=1, creator_name="Tester",
            created_at=0.0, owner_id=1, faction_id=0,
            legend_score=10.0, is_faction_relic=False, history=[],
        )
        old_legend = h.legend_score
        h.add_history_event("used_in_battle", "Carried into battle", 100.0)
        self.assertGreater(h.legend_score, old_legend)
        self.assertEqual(len(h.history), 1)

    def test_history_capped_at_50(self):
        h = Heirloom(
            heirloom_id=1, name="Test", type_id="named_weapon",
            category="weapon", creator_id=1, creator_name="Tester",
            created_at=0.0, owner_id=1, faction_id=0,
            legend_score=10.0, is_faction_relic=False, history=[],
        )
        for i in range(60):
            h.add_history_event("used_in_battle", f"Battle {i}", float(i))
        self.assertLessEqual(len(h.history), 50)

    def test_generation_count(self):
        h = Heirloom(
            heirloom_id=1, name="Test", type_id="named_weapon",
            category="weapon", creator_id=1, creator_name="Tester",
            created_at=0.0, owner_id=1, faction_id=0,
            legend_score=10.0, is_faction_relic=False, history=[],
        )
        self.assertEqual(h.generation_count(), 0)
        h.add_history_event("inherited", "Passed down", 100.0)
        h.add_history_event("inherited", "Passed down again", 200.0)
        self.assertEqual(h.generation_count(), 2)

    def test_serialization_roundtrip(self):
        h = Heirloom(
            heirloom_id=42, name="Stormfang", type_id="named_weapon",
            category="weapon", creator_id=7, creator_name="Kara",
            created_at=100.0, owner_id=7, faction_id=1,
            legend_score=35.5, is_faction_relic=False,
            history=[{"event_id": "created", "description": "test",
                       "timestamp": 100.0, "related_ids": [7],
                       "legend_added": 5}],
            base_item={"id": "sword", "quality": "Masterwork"},
        )
        data = h.to_dict()
        restored = Heirloom.from_dict(data)
        self.assertEqual(restored.heirloom_id, 42)
        self.assertEqual(restored.name, "Stormfang")
        self.assertEqual(restored.type_id, "named_weapon")
        self.assertAlmostEqual(restored.legend_score, 35.5, places=1)
        self.assertEqual(len(restored.history), 1)
        self.assertEqual(restored.base_item["quality"], "Masterwork")


class TestHeirloomCreation(unittest.TestCase):
    """HeirloomManager.create_heirloom."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()
        self.mgr = HeirloomManager()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_create_named_weapon(self):
        h = self.mgr.create_heirloom(
            type_id="named_weapon", creator_id=1, creator_name="Kara",
            faction_id=0, current_time=100.0,
            base_item={"id": "sword", "damage": 15, "quality": "Masterwork"},
        )
        self.assertIsNotNone(h)
        self.assertEqual(h.category, "weapon")
        self.assertEqual(h.creator_name, "Kara")
        self.assertEqual(h.owner_id, 1)
        self.assertGreater(h.legend_score, 0)
        self.assertEqual(len(h.history), 1)  # "created" event

    def test_create_founders_banner_is_auto_relic(self):
        h = self.mgr.create_heirloom(
            type_id="founders_banner", creator_id=None, creator_name="The Colony",
            faction_id=0, current_time=100.0,
        )
        self.assertIsNotNone(h)
        self.assertTrue(h.is_faction_relic)
        self.assertEqual(h.category, "relic")

    def test_create_memorial_stone(self):
        h = self.mgr.create_heirloom(
            type_id="memorial_stone", creator_id=None, creator_name="In Memory of Riko",
            faction_id=0, current_time=100.0,
        )
        self.assertIsNotNone(h)
        self.assertTrue(h.is_faction_relic)

    def test_faction_cap_enforced(self):
        for i in range(MAX_HEIRLOOMS_PER_FACTION):
            h = self.mgr.create_heirloom(
                type_id="named_weapon", creator_id=i, creator_name=f"P{i}",
                faction_id=0, current_time=100.0,
            )
            self.assertIsNotNone(h, f"Failed to create heirloom {i}")
        # This should fail — faction cap reached
        h = self.mgr.create_heirloom(
            type_id="named_weapon", creator_id=999, creator_name="Overflow",
            faction_id=0, current_time=100.0,
        )
        self.assertIsNone(h)

    def test_create_with_invalid_type_returns_none(self):
        h = self.mgr.create_heirloom(
            type_id="nonexistent_type", creator_id=1, creator_name="Test",
            faction_id=0, current_time=100.0,
        )
        self.assertIsNone(h)

    def test_different_factions_have_separate_caps(self):
        for i in range(MAX_HEIRLOOMS_PER_FACTION):
            self.mgr.create_heirloom(
                type_id="named_weapon", creator_id=i, creator_name=f"P{i}",
                faction_id=0, current_time=100.0,
            )
        # Different faction should still work
        h = self.mgr.create_heirloom(
            type_id="named_weapon", creator_id=100, creator_name="Other",
            faction_id=1, current_time=100.0,
        )
        self.assertIsNotNone(h)


class TestQueries(unittest.TestCase):
    """Query methods on HeirloomManager."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()
        self.mgr = HeirloomManager()
        self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        self.mgr.create_heirloom("named_armor", 2, "Miko", 0, 101.0)
        self.mgr.create_heirloom("founders_banner", None, "Colony", 1, 102.0)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_get_by_owner(self):
        heirlooms = self.mgr.get_heirlooms_by_owner(1)
        self.assertEqual(len(heirlooms), 1)
        self.assertEqual(heirlooms[0].creator_name, "Kara")

    def test_get_by_faction(self):
        heirlooms = self.mgr.get_heirlooms_by_faction(0)
        self.assertEqual(len(heirlooms), 2)

    def test_get_faction_relics(self):
        relics = self.mgr.get_faction_relics(1)
        self.assertEqual(len(relics), 1)  # founder's banner

    def test_get_most_legendary(self):
        top = self.mgr.get_most_legendary(2)
        self.assertEqual(len(top), 2)
        # Should be sorted by legend descending
        self.assertGreaterEqual(top[0].legend_score, top[1].legend_score)

    def test_get_heirloom_summary(self):
        all_h = self.mgr.get_all_heirlooms()
        hid = list(all_h.keys())[0]
        summary = self.mgr.get_heirloom_summary(hid)
        self.assertIsInstance(summary, str)
        self.assertIn("legend", summary)

    def test_faction_cohesion_bonus(self):
        bonus = self.mgr.get_faction_cohesion_bonus(1)
        self.assertGreater(bonus, 0.0)  # founder's banner is a relic


class TestInheritance(unittest.TestCase):
    """Heirloom inheritance on death."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()
        self.mgr = HeirloomManager()
        self.bus = EventBus()
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_inherits_to_partner(self):
        """Heirloom passes to living partner on death."""
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        hid = h.heirloom_id

        # Set up praxans with partner relationship.
        # Real praxan format: {other_id: rel_type_str}
        p1 = MockPraxan(pid=1, faction_id=0)
        p2 = MockPraxan(pid=2, faction_id=0)
        p2.relationships = {1: "partner"}  # p2's partner is praxan #1

        # Publish death event
        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Kara died",
            metadata={"praxan_id": 1, "name": "Kara", "cause": "old_age"},
        ))

        # Run update to process
        self.mgr.update(
            praxans=[p2], faction_manager=MockFactionManager(),
            current_time=100.0 + EVAL_INTERVAL + 1,
        )

        self.assertEqual(h.owner_id, 2)

    def test_inherits_to_child_if_no_partner(self):
        """Heirloom passes to living child if no partner."""
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)

        child = MockPraxan(pid=3, faction_id=0)
        # Real praxan format: {other_id: rel_type_str}.
        # child.relationships[1] = "parent" means "praxan #1 is my parent" — so child is a child of #1.
        child.relationships = {1: "parent"}

        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Kara died",
            metadata={"praxan_id": 1, "name": "Kara", "cause": "old_age"},
        ))

        self.mgr.update(
            praxans=[child], faction_manager=MockFactionManager(),
            current_time=100.0 + EVAL_INTERVAL + 1,
        )

        self.assertEqual(h.owner_id, 3)

    def test_inherits_to_faction_leader_as_fallback(self):
        """Heirloom passes to faction leader if no family."""
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)

        leader = MockPraxan(pid=5, faction_id=0)
        faction = MockFaction(fid=0, leader_id=5)
        fm = MockFactionManager([faction])

        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Kara died",
            metadata={"praxan_id": 1, "name": "Kara", "cause": "old_age"},
        ))

        self.mgr.update(
            praxans=[leader], faction_manager=fm,
            current_time=100.0 + EVAL_INTERVAL + 1,
        )

        self.assertEqual(h.owner_id, 5)

    def test_goes_to_vault_if_no_heir(self):
        """Heirloom goes to faction vault (owner_id=None) if no one qualifies."""
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)

        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Kara died",
            metadata={"praxan_id": 1, "name": "Kara", "cause": "old_age"},
        ))

        # No alive praxans to inherit
        self.mgr.update(
            praxans=[], faction_manager=MockFactionManager(),
            current_time=100.0 + EVAL_INTERVAL + 1,
        )

        self.assertIsNone(h.owner_id)

    def test_heroic_death_adds_legend(self):
        """Combat death adds extra legend via owner_died_heroically event."""
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        initial_legend = h.legend_score

        self.bus.publish(GameEvent(
            category=CATEGORY_DEATH,
            summary="Kara died in combat",
            metadata={"praxan_id": 1, "name": "Kara", "cause": "combat"},
        ))

        self.mgr.update(
            praxans=[], faction_manager=MockFactionManager(),
            current_time=100.0 + EVAL_INTERVAL + 1,
        )

        # Legend should have grown from heroic death + inheritance event
        self.assertGreater(h.legend_score, initial_legend)


class TestRelicAscension(unittest.TestCase):
    """Faction relic ascension when legend exceeds threshold."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()
        self.mgr = HeirloomManager()
        self.bus = EventBus()
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_relic_ascension_at_threshold(self):
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        # named_weapon threshold is 80
        h.legend_score = 79.0
        self.assertFalse(h.is_faction_relic)

        owner = MockPraxan(pid=1, faction_id=0)

        # First update — below threshold
        self.mgr.update(
            praxans=[owner], current_time=100.0 + EVAL_INTERVAL + 1,
        )
        self.assertFalse(h.is_faction_relic)

        # Push over threshold
        h.legend_score = 81.0
        self.mgr.update(
            praxans=[owner], current_time=100.0 + 2 * EVAL_INTERVAL + 2,
        )
        self.assertTrue(h.is_faction_relic)
        # Owner should have gotten moodlet
        mood_names = [m["name"] for m in owner.moodlets]
        self.assertIn("HeirloomBecameRelic", mood_names)

    def test_relic_ascension_publishes_event(self):
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        h.legend_score = 81.0

        events_received = []
        self.bus.subscribe(CATEGORY_CULTURAL_SHIFT, lambda e: events_received.append(e))

        owner = MockPraxan(pid=1, faction_id=0)
        self.mgr.update(
            praxans=[owner], current_time=100.0 + EVAL_INTERVAL + 1,
        )

        self.assertEqual(len(events_received), 1)
        self.assertEqual(events_received[0].metadata["type"], "heirloom_relic_ascension")


class TestBattleLegend(unittest.TestCase):
    """Battle participation and colony defense legend hooks."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()
        self.mgr = HeirloomManager()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_battle_participation_adds_legend(self):
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        initial = h.legend_score
        self.mgr.record_battle_participation([1], 200.0, "raid")
        self.assertGreater(h.legend_score, initial)

    def test_colony_defense_adds_legend(self):
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        initial = h.legend_score
        self.mgr.record_colony_defense([1], 200.0)
        self.assertGreater(h.legend_score, initial)

    def test_luminary_adds_legend(self):
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        initial = h.legend_score
        self.mgr.record_owner_luminary(1, 200.0)
        self.assertGreater(h.legend_score, initial)

    def test_non_participants_unaffected(self):
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        initial = h.legend_score
        self.mgr.record_battle_participation([99], 200.0, "raid")  # owner not participant
        self.assertEqual(h.legend_score, initial)


class TestWarfareLooting(unittest.TestCase):
    """Heirloom theft during warfare raids."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()
        self.mgr = HeirloomManager()
        self.bus = EventBus()
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_loot_possible_on_attacker_victory(self):
        """Non-relic heirlooms can be looted on attacker victory (30% chance)."""
        import random
        random.seed(42)  # seed for reproducibility

        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        attacker = MockPraxan(pid=10, faction_id=1)

        # Try multiple times to hit the 30% chance
        looted = False
        for attempt in range(20):
            h.faction_id = 0
            h.owner_id = 1
            self.bus.publish(GameEvent(
                category=CATEGORY_WARFARE,
                summary="Raid resolved",
                metadata={
                    "outcome": "attacker_victory",
                    "defender_faction_id": 0,
                    "attacker_faction_id": 1,
                    "attacker_combatants": [10],
                },
            ))
            self.mgr.update(
                praxans=[attacker],
                current_time=100.0 + (attempt + 1) * (EVAL_INTERVAL + 1),
            )
            if h.faction_id == 1:
                looted = True
                break

        self.assertTrue(looted, "Heirloom should be lootable (tried 20 times with 30% chance)")

    def test_faction_relics_not_looted(self):
        """Faction relics are protected from looting."""
        h = self.mgr.create_heirloom("founders_banner", None, "Colony", 0, 100.0)
        self.assertTrue(h.is_faction_relic)

        attacker = MockPraxan(pid=10, faction_id=1)

        for attempt in range(10):
            self.bus.publish(GameEvent(
                category=CATEGORY_WARFARE,
                summary="Raid resolved",
                metadata={
                    "outcome": "attacker_victory",
                    "defender_faction_id": 0,
                    "attacker_faction_id": 1,
                    "attacker_combatants": [10],
                },
            ))
            self.mgr.update(
                praxans=[attacker],
                current_time=100.0 + (attempt + 1) * (EVAL_INTERVAL + 1),
            )

        # Banner should stay with original faction
        self.assertEqual(h.faction_id, 0)

    def test_defender_victory_no_loot(self):
        """No looting on defender victory."""
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)

        self.bus.publish(GameEvent(
            category=CATEGORY_WARFARE,
            summary="Raid resolved",
            metadata={
                "outcome": "defender_victory",
                "defender_faction_id": 0,
                "attacker_faction_id": 1,
            },
        ))

        self.mgr.update(
            praxans=[], current_time=100.0 + EVAL_INTERVAL + 1,
        )

        self.assertEqual(h.faction_id, 0)


class TestBearerEffects(unittest.TestCase):
    """Periodic moodlets for heirloom bearers."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()
        self.mgr = HeirloomManager()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_ancestral_moodlet_after_inheritance(self):
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        # Simulate inheritance
        h.history.append({
            "event_id": "inherited", "description": "test",
            "timestamp": 150.0, "related_ids": [2], "legend_added": 3,
        })
        h.owner_id = 2

        owner = MockPraxan(pid=2, faction_id=0)
        self.mgr.update(
            praxans=[owner], current_time=100.0 + EVAL_INTERVAL + 1,
        )

        mood_names = [m["name"] for m in owner.moodlets]
        self.assertIn("AncestralHeirloom", mood_names)

    def test_relic_bearer_gets_reputation(self):
        h = self.mgr.create_heirloom("founders_banner", None, "Colony", 0, 100.0)
        h.owner_id = 3

        owner = MockPraxan(pid=3, faction_id=0)
        self.mgr.update(
            praxans=[owner], current_time=100.0 + EVAL_INTERVAL + 1,
        )

        self.assertIn("holds_faction_relic", owner._pending_reputation_events)


class TestDisasterLegend(unittest.TestCase):
    """Disasters add legend to heirlooms of surviving bearers."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()
        self.mgr = HeirloomManager()
        self.bus = EventBus()
        self.mgr.attach_event_bus(self.bus)

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_disaster_adds_legend_to_surviving_bearers(self):
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        initial = h.legend_score

        owner = MockPraxan(pid=1, faction_id=0)
        self.bus.publish(GameEvent(
            category=CATEGORY_DISASTER,
            summary="Storm struck",
            metadata={"type": "storm"},
        ))

        self.mgr.update(
            praxans=[owner], current_time=100.0 + EVAL_INTERVAL + 1,
        )
        self.assertGreater(h.legend_score, initial)


class TestSerialization(unittest.TestCase):
    """Manager serialize/restore roundtrip."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()
        self.mgr = HeirloomManager()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_serialize_restore_roundtrip(self):
        self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        self.mgr.create_heirloom("founders_banner", None, "Colony", 1, 101.0)

        data = self.mgr.serialize()
        self.assertIn("heirlooms", data)
        self.assertEqual(len(data["heirlooms"]), 2)

        # Restore into a fresh manager
        mgr2 = HeirloomManager()
        mgr2.restore(data, current_time=200.0)

        self.assertEqual(len(mgr2.get_all_heirlooms()), 2)
        relics = mgr2.get_faction_relics(1)
        self.assertEqual(len(relics), 1)

    def test_empty_restore(self):
        mgr2 = HeirloomManager()
        mgr2.restore({}, current_time=0.0)
        self.assertEqual(len(mgr2.get_all_heirlooms()), 0)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and guard conditions."""

    def setUp(self):
        clear_cache()
        DefDatabase.clear()
        DefDatabase.initialize()
        self.mgr = HeirloomManager()

    def tearDown(self):
        clear_cache()
        DefDatabase.clear()

    def test_update_before_interval_is_noop(self):
        """Update called before EVAL_INTERVAL is a no-op."""
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        self.mgr.update(praxans=[], current_time=100.0)
        # Should not crash, just skip

    def test_dead_owner_heirloom_not_affected_by_bearer_effects(self):
        """Bearer effects only apply to alive owners."""
        h = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0)
        h.owner_id = 99  # non-existent

        p = MockPraxan(pid=2, faction_id=0)
        self.mgr.update(
            praxans=[p], current_time=100.0 + EVAL_INTERVAL + 1,
        )
        # p should have no heirloom moodlets
        self.assertEqual(len(p.moodlets), 0)

    def test_multiple_heirlooms_per_owner(self):
        """One praxan can hold multiple heirlooms."""
        h1 = self.mgr.create_heirloom("named_weapon", 1, "Kara", 0, 100.0,
                                       owner_id=1)
        h2 = self.mgr.create_heirloom("named_armor", 1, "Kara", 0, 101.0,
                                       owner_id=1)
        owned = self.mgr.get_heirlooms_by_owner(1)
        self.assertEqual(len(owned), 2)


if __name__ == "__main__":
    unittest.main()
