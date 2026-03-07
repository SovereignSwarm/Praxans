import os
import tempfile
import unittest
from types import SimpleNamespace

from run_snapshot import (
    SNAPSHOT_VERSION,
    build_run_snapshot,
    find_latest_snapshot,
    load_run_snapshot,
    resolve_snapshot_path,
    write_run_snapshot,
)


class RunSnapshotTests(unittest.TestCase):
    def test_find_latest_snapshot_returns_newest_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            older = os.path.join(temp_dir, "snapshot_old.json")
            newer = os.path.join(temp_dir, "snapshot_new.json")
            with open(older, "w", encoding="utf-8") as file_handle:
                file_handle.write("{}")
            with open(newer, "w", encoding="utf-8") as file_handle:
                file_handle.write("{}")

            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))

            self.assertEqual(find_latest_snapshot(temp_dir), newer)

    def test_resolve_snapshot_path_uses_log_dir_for_relative_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = os.path.join(temp_dir, "snapshot_case.json")
            with open(snapshot_path, "w", encoding="utf-8") as file_handle:
                file_handle.write("{}")

            resolved = resolve_snapshot_path(temp_dir, snapshot_file="snapshot_case.json")
            self.assertEqual(resolved, os.path.abspath(snapshot_path))

    def test_load_run_snapshot_rejects_newer_snapshot_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = os.path.join(temp_dir, "snapshot_future.json")
            with open(snapshot_path, "w", encoding="utf-8") as file_handle:
                file_handle.write('{"snapshot_version": 999}')

            with self.assertRaises(ValueError):
                load_run_snapshot(snapshot_path)

    def test_build_write_and_load_snapshot_round_trip(self):
        praxan = SimpleNamespace(
            id=7,
            role="builder",
            x=12.5,
            y=13.5,
            health=88.0,
            happiness=76.0,
            morale=81.0,
            inspiration=18.0,
            favorite_biome="forest",
            age=44.0,
            diseased=True,
            disease_start_time=90.0,
            resilience=1.05,
            settlement_prosperity=0.72,
            inventory={"food": 2, "wood": 3, "stone": 1},
            needs={"hunger": 90.0, "energy": 80.0, "thirst": 70.0},
            state="idle",
            current_action="build house",
            personal_goal={"type": "build_house", "target": "center", "reason": "need shelter"},
            goal_progress=0.4,
            personality={"curiosity": 0.65, "sociability": 0.4, "diligence": 0.9},
            genetics={
                "metabolism_efficiency": 1.08,
                "learning_affinity": 1.12,
                "immune_strength": 0.96,
                "fertility_drive": 1.03,
            },
            generation=2,
            parent_ids=[1, 4],
            lineage_id=1,
            mutation_count=3,
            birth_origin="offspring",
            skills={
                "gathering": {"level": 2, "xp": 15.0},
                "building": {"level": 4, "xp": 50.0},
                "exploring": {"level": 1, "xp": 0.0},
            },
            bonds={4: 72.5, 9: 25.0},
            faction_id=2,
            known_resources=[(100.0, 120.0), (140.0, 180.0)],
            last_reproduction_time=82.0,
            goal_assigned_time=91.5,
        )
        building = SimpleNamespace(
            building_type="house",
            x=40.0,
            y=50.0,
            level=2,
            built_by=7,
            aura_strength=0.6,
            stored_resources={"food": 1, "wood": 0, "stone": 0},
            occupants=[praxan],
        )
        resource = SimpleNamespace(
            resource_type="food",
            x=60.0,
            y=70.0,
            collected=True,
            collect_time=95.0,
        )
        advisor = SimpleNamespace(
            research_points=25,
            points_spent=10,
            stability_counter=2,
            current_focus="resources",
            directives=[{"priority": 5, "action": "gather food", "reasoning": "low reserves"}],
            json_directives={"individual": {}, "communal": "gather food", "conditions": {}},
            council_state={"doctrine": {"focus": "growth", "stance": "measured"}},
            advisory_history=[{"time": 97.0, "doctrine": {"focus": "growth"}}],
            session_stats={"max_population": 4, "current_run_summary": {"end_state": {"label": "Thriving Civilization"}}},
            current_settlement_state={"district_identity": "homestead"},
            query_count=3,
            intervention_stats={"total_queries": 5, "interventions": 2, "no_changes": 3, "crisis_interventions": 1},
            active_challenges=[
                {"type": "bounty", "start_time": 90.0, "duration": 50.0, "reward": 25, "target": 10, "collected": 3}
            ],
            civilization_age=6,
            total_deaths=2,
            achievements=["weathered_winter"],
            history=[{"summary": "hold steady"}],
            events_history=[{"time": 99.0, "description": "New praxan born"}],
            last_model_used="qwen3.5:9b",
            group_tasks=[
                SimpleNamespace(
                    task_type="build",
                    description="Raise a workshop",
                    required_count=2,
                    target_location=(44.0, 55.0),
                    target_building_type="workshop",
                    assigned_praxans=[7],
                    active=True,
                    faction_id=0,
                    created_time=92.0,
                )
            ],
            game_modifiers=SimpleNamespace(
                tech_unlocked={"agriculture_1"},
                permanent={"farm_production_rate": 1.2},
                temporary={"workers_focus": (1.5, 140.0)},
            ),
        )
        season = SimpleNamespace(current="autumn")
        weather_system = SimpleNamespace(current_weather="rain", next_event_time=130.0)
        celebration_state = {"active_until": 112.0, "cooldown_until": 165.0, "center": (42.0, 51.0)}
        camera = SimpleNamespace(x=320.0, y=240.0, zoom=1.75, follow_mode=True)
        fog_of_war = SimpleNamespace(fog_grid={(1, 2): 255, (3, 4): 200}, visibility_radius=72)
        territory_manager = SimpleNamespace(
            territory_grid={
                (10, 11): {"claim_strength": 66.5, "claimed_time": 87.0, "center_type": "building"},
            }
        )
        faction_manager = SimpleNamespace(
            factions={
                0: SimpleNamespace(
                    member_ids=[7],
                    leader_id=7,
                    shared_goals=[{"type": "build_workshop"}],
                    ideology={"growth": 0.8, "security": 0.3},
                    cohesion=0.71,
                    stability=0.66,
                    schism_pressure=48.0,
                    migration_pressure=63.0,
                    primary_doctrine="growth",
                    preferred_biome="forest",
                    migration_target=(180.0, 210.0),
                    succession_count=2,
                    last_succession_time=95.0,
                    last_schism_time=92.0,
                    last_migration_time=98.0,
                    rival_faction_ids=[2],
                    formed_time=84.0,
                )
            }
        )
        run_summary = {
            "current_phase": {"id": "expansion", "label": "Expansion"},
            "end_state": {"id": "brittle_survival", "label": "Brittle Survival", "score": 61},
        }
        city_planner = SimpleNamespace(
            zones={(8, 9): "residential"},
            current_plan={"districts": [{"type": "residential", "priority": 1, "location": "north"}]},
            last_plan_update=80.0,
        )
        world_map = SimpleNamespace(
            generation_version=2,
            world_seed=12345,
            world_profile=SimpleNamespace(to_payload=lambda: {"chunk_cols": 16, "chunk_rows": 12, "region_cols": 8, "region_rows": 6}),
            discovered_chunks={(0, 0), (1, 1)},
            regions=[{"region_id": "r0_0", "biome": "plains", "world_rect": [0, 0, 1024, 1024]}],
            route_network=[{"route_id": "route_a", "start_region_id": "r0_0", "end_region_id": "r1_0", "points": [{"x": 32.0, "y": 32.0}, {"x": 128.0, "y": 32.0}], "risk": 0.2}],
            landmarks=[{"landmark_id": "landmark_0", "region_id": "r0_0", "name": "Amber Fields", "category": "granary", "x": 64.0, "y": 64.0}],
            settlements=[{"settlement_id": "set_0", "region_id": "r0_0", "x": 80.0, "y": 88.0, "settlement_type": "capital", "population": 7, "prosperity": 0.8, "water_access": 0.7, "route_access": 0.65, "polity_id": 0}],
            polities=[{"polity_id": 0, "name": "Frontier Polity 1", "home_region_id": "r0_0", "doctrine_bias": "growth", "frontier_pressure": 42.0, "settlement_ids": ["set_0"], "claimed_region_ids": ["r0_0"], "trade_route_ids": ["route_a"], "capital_settlement_id": "set_0", "accent_color": [200, 160, 120]}],
            water_network=[{"points": [{"x": 16.0, "y": 12.0}, {"x": 200.0, "y": 18.0}]}],
            encounters=[
                SimpleNamespace(x=77.0, y=88.0, encounter_type="ruins", discovered=True, explored=False, reward_given=False)
            ],
            hazards=[
                SimpleNamespace(x=90.0, y=120.0, hazard_type="predator_lair", radius=95.0, active=True, damage_rate=0.8)
            ],
            npcs=[
                SimpleNamespace(
                    x=140.0,
                    y=150.0,
                    npc_type="trader",
                    visible=True,
                    inventory={"food": 5, "wood": 2, "stone": 1},
                    trade_rates={"food_for_wood": 2},
                    hostile=False,
                    reputation=12,
                    last_interaction=96.0,
                )
            ],
        )

        snapshot = build_run_snapshot(
            [praxan],
            [building],
            [resource],
            advisor,
            season,
            weather_system,
            current_time=100.0,
            game_start_time=40.0,
            selected_model="qwen3.5:9b",
            celebration_state=celebration_state,
            camera=camera,
            world_map=world_map,
            fog_of_war=fog_of_war,
            territory_manager=territory_manager,
            faction_manager=faction_manager,
            city_planner=city_planner,
            scenario_id="high_mutation",
            run_summary=run_summary,
            camera_bookmarks=[{"label": "Founding", "category": "scenario", "x": 42.0, "y": 51.0, "time": 100.0}],
            scene_thumbnail_key="thumb_test_session.png",
            focus_moments=[{"label": "Founding", "category": "scenario", "time": 100.0}],
        )

        self.assertEqual(snapshot["snapshot_version"], SNAPSHOT_VERSION)
        self.assertEqual(snapshot["selected_model"], "qwen3.5:9b")
        self.assertEqual(snapshot["scenario_id"], "high_mutation")
        self.assertEqual(snapshot["run_summary"]["end_state"]["score"], 61)
        self.assertEqual(snapshot["graphics"]["scene_thumbnail_key"], "thumb_test_session.png")
        self.assertEqual(snapshot["graphics"]["camera_bookmarks"][0]["label"], "Founding")
        self.assertEqual(snapshot["advisor"]["temporary_modifiers"]["workers_focus"]["remaining_seconds"], 40.0)
        self.assertEqual(snapshot["camera"]["zoom"], 1.75)
        self.assertEqual(snapshot["celebration"]["active_remaining"], 12.0)
        self.assertEqual(snapshot["advisor"]["active_challenges"][0]["remaining_seconds"], 40.0)
        self.assertEqual(snapshot["advisor"]["group_tasks"][0]["created_elapsed"], 8.0)
        self.assertEqual(snapshot["fog_of_war"]["tiles"][0]["x"], 1)
        self.assertEqual(snapshot["territory"]["tiles"][0]["claim_strength"], 66.5)
        self.assertEqual(snapshot["factions"][0]["leader_id"], 7)
        self.assertEqual(snapshot["factions"][0]["primary_doctrine"], "growth")
        self.assertEqual(snapshot["factions"][0]["migration_target"]["x"], 180.0)
        self.assertEqual(snapshot["factions"][0]["succession_count"], 2)
        self.assertEqual(snapshot["factions"][0]["rival_faction_ids"], [2])
        self.assertEqual(snapshot["city_planner"]["zones"][0]["zone_type"], "residential")
        self.assertEqual(snapshot["world"]["world_seed"], 12345)
        self.assertEqual(snapshot["world"]["world_profile"]["chunk_cols"], 16)
        self.assertEqual(snapshot["world"]["regions"][0]["region_id"], "r0_0")
        self.assertEqual(snapshot["world"]["routes"][0]["route_id"], "route_a")
        self.assertEqual(snapshot["world"]["polities"][0]["home_region_id"], "r0_0")
        self.assertEqual(snapshot["world"]["encounters"][0]["encounter_type"], "ruins")
        self.assertEqual(snapshot["world"]["npcs"][0]["last_interaction_elapsed"], 4.0)
        self.assertEqual(snapshot["advisor"]["council_state"]["doctrine"]["focus"], "growth")
        self.assertEqual(snapshot["advisor"]["advisory_history"][0]["doctrine"]["focus"], "growth")

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = write_run_snapshot(temp_dir, "test_session", snapshot)
            loaded = load_run_snapshot(snapshot_path)

        self.assertEqual(loaded["population"], 1)
        self.assertEqual(loaded["season"], "autumn")
        self.assertEqual(loaded["scenario_id"], "high_mutation")
        self.assertEqual(loaded["run_summary"]["current_phase"]["label"], "Expansion")
        self.assertEqual(loaded["graphics"]["scene_thumbnail_key"], "thumb_test_session.png")
        self.assertEqual(loaded["praxans"][0]["id"], 7)
        self.assertEqual(loaded["buildings"][0]["built_by"], 7)
        self.assertEqual(loaded["buildings"][0]["occupant_ids"], [7])
        self.assertEqual(loaded["advisor"]["tech_unlocked"], ["agriculture_1"])
        self.assertEqual(loaded["praxans"][0]["generation"], 2)
        self.assertEqual(loaded["praxans"][0]["lineage_id"], 1)
        self.assertEqual(loaded["praxans"][0]["genetics"]["learning_affinity"], 1.12)
        self.assertEqual(loaded["praxans"][0]["skills"]["building"]["level"], 4)
        self.assertEqual(loaded["praxans"][0]["known_resources"][0]["x"], 100.0)
        self.assertEqual(loaded["praxans"][0]["disease_elapsed"], 10.0)
        self.assertEqual(loaded["praxans"][0]["last_reproduction_elapsed"], 18.0)
        self.assertEqual(loaded["advisor"]["civilization_age"], 6)
        self.assertEqual(loaded["advisor"]["total_deaths"], 2)
        self.assertEqual(loaded["advisor"]["last_model_used"], "qwen3.5:9b")
        self.assertEqual(loaded["advisor"]["council_state"]["doctrine"]["focus"], "growth")
        self.assertEqual(loaded["advisor"]["advisory_history"][0]["doctrine"]["focus"], "growth")
        self.assertEqual(loaded["advisor"]["group_tasks"][0]["task_type"], "build")
        self.assertEqual(loaded["fog_of_war"]["visibility_radius"], 72)
        self.assertEqual(loaded["territory"]["tiles"][0]["center_type"], "building")
        self.assertEqual(loaded["factions"][0]["member_ids"], [7])
        self.assertEqual(loaded["factions"][0]["cohesion"], 0.71)
        self.assertEqual(loaded["factions"][0]["migration_pressure"], 63.0)
        self.assertEqual(loaded["factions"][0]["preferred_biome"], "forest")
        self.assertEqual(loaded["city_planner"]["current_plan"]["districts"][0]["location"], "north")
        self.assertEqual(loaded["world"]["generation_version"], 2)
        self.assertEqual(loaded["world"]["discovered_chunks"][0]["chunk_x"], 0)
        self.assertEqual(loaded["world"]["hazards"][0]["damage_rate"], 0.8)
        self.assertEqual(loaded["world"]["npcs"][0]["trade_rates"]["food_for_wood"], 2)


    def test_opinions_survive_snapshot_round_trip(self):
        """opinions dict must be serialized so interaction preconditions work after reload."""
        praxan = SimpleNamespace(
            id=1,
            role="gatherer",
            x=100.0, y=100.0,
            health=100.0, happiness=50.0, morale=50.0, inspiration=0.0,
            favorite_biome="plains", age=120.0,
            diseased=False, resilience=1.0, settlement_prosperity=0.5,
            inventory={"food": 0, "wood": 0, "stone": 0},
            needs={"hunger": 80.0, "energy": 80.0, "thirst": 80.0},
            state="idle", current_action="wander",
            personal_goal=None, goal_progress=0.0,
            personality={"curiosity": 0.5, "sociability": 0.5, "diligence": 0.5},
            genetics={},
            generation=1, parent_ids=[], lineage_id=1, mutation_count=0,
            birth_origin="founder",
            skills={},
            bonds={2: 40.0},
            opinions={2: -45.0, 3: 30.0},  # rival (negative) and friend (positive)
            relationships={}, traits=[], name="Test", faction_id=None,
            known_resources=[],
            last_reproduction_time=0.0, goal_assigned_time=0.0,
            episodic_memory=None,
        )
        advisor = SimpleNamespace(
            research_points=0, points_spent=0, stability_counter=0,
            current_focus="resources",
            directives=[], json_directives={"individual": {}, "communal": "", "conditions": {}},
            council_state={}, advisory_history=[], session_stats={},
            current_settlement_state={}, query_count=0,
            intervention_stats={"total_queries": 0, "interventions": 0, "no_changes": 0, "crisis_interventions": 0},
            active_challenges=[], civilization_age=1, total_deaths=0,
            achievements=[], history=[], events_history=[], last_model_used="",
            group_tasks=[],
            game_modifiers=SimpleNamespace(tech_unlocked=set(), permanent={}, temporary={}),
        )
        season = SimpleNamespace(current="summer")
        weather_system = SimpleNamespace(current_weather="clear", next_event_time=999.0)

        snapshot = build_run_snapshot(
            [praxan], [], [], advisor, season, weather_system,
            current_time=200.0, game_start_time=100.0,
        )

        praxan_snap = snapshot["praxans"][0]
        self.assertIn("opinions", praxan_snap, "opinions must be serialized in snapshot")
        self.assertAlmostEqual(praxan_snap["opinions"]["2"], -45.0)
        self.assertAlmostEqual(praxan_snap["opinions"]["3"], 30.0)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_run_snapshot(temp_dir, "opinions_test", snapshot)
            loaded = load_run_snapshot(path)

        loaded_opinions = loaded["praxans"][0]["opinions"]
        self.assertAlmostEqual(loaded_opinions["2"], -45.0)
        self.assertAlmostEqual(loaded_opinions["3"], 30.0)


if __name__ == "__main__":
    unittest.main()
