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

    def test_build_write_and_load_snapshot_round_trip(self):
        thronglet = SimpleNamespace(
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
            occupants=[thronglet],
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
            session_stats={"max_population": 4},
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
            events_history=[{"time": 99.0, "description": "New thronglet born"}],
            last_model_used="qwen3.5:35b",
            group_tasks=[
                SimpleNamespace(
                    task_type="build",
                    description="Raise a workshop",
                    required_count=2,
                    target_location=(44.0, 55.0),
                    target_building_type="workshop",
                    assigned_thronglets=[7],
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
                    formed_time=84.0,
                )
            }
        )
        city_planner = SimpleNamespace(
            zones={(8, 9): "residential"},
            current_plan={"districts": [{"type": "residential", "priority": 1, "location": "north"}]},
            last_plan_update=80.0,
        )
        world_map = SimpleNamespace(
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
            [thronglet],
            [building],
            [resource],
            advisor,
            season,
            weather_system,
            current_time=100.0,
            game_start_time=40.0,
            selected_model="qwen3.5:35b",
            celebration_state=celebration_state,
            camera=camera,
            world_map=world_map,
            fog_of_war=fog_of_war,
            territory_manager=territory_manager,
            faction_manager=faction_manager,
            city_planner=city_planner,
            scenario_id="high_mutation",
        )

        self.assertEqual(snapshot["snapshot_version"], SNAPSHOT_VERSION)
        self.assertEqual(snapshot["selected_model"], "qwen3.5:35b")
        self.assertEqual(snapshot["scenario_id"], "high_mutation")
        self.assertEqual(snapshot["advisor"]["temporary_modifiers"]["workers_focus"]["remaining_seconds"], 40.0)
        self.assertEqual(snapshot["camera"]["zoom"], 1.75)
        self.assertEqual(snapshot["celebration"]["active_remaining"], 12.0)
        self.assertEqual(snapshot["advisor"]["active_challenges"][0]["remaining_seconds"], 40.0)
        self.assertEqual(snapshot["advisor"]["group_tasks"][0]["created_elapsed"], 8.0)
        self.assertEqual(snapshot["fog_of_war"]["tiles"][0]["x"], 1)
        self.assertEqual(snapshot["territory"]["tiles"][0]["claim_strength"], 66.5)
        self.assertEqual(snapshot["factions"][0]["leader_id"], 7)
        self.assertEqual(snapshot["city_planner"]["zones"][0]["zone_type"], "residential")
        self.assertEqual(snapshot["world"]["encounters"][0]["encounter_type"], "ruins")
        self.assertEqual(snapshot["world"]["npcs"][0]["last_interaction_elapsed"], 4.0)

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = write_run_snapshot(temp_dir, "test_session", snapshot)
            loaded = load_run_snapshot(snapshot_path)

        self.assertEqual(loaded["population"], 1)
        self.assertEqual(loaded["season"], "autumn")
        self.assertEqual(loaded["scenario_id"], "high_mutation")
        self.assertEqual(loaded["thronglets"][0]["id"], 7)
        self.assertEqual(loaded["buildings"][0]["built_by"], 7)
        self.assertEqual(loaded["buildings"][0]["occupant_ids"], [7])
        self.assertEqual(loaded["advisor"]["tech_unlocked"], ["agriculture_1"])
        self.assertEqual(loaded["thronglets"][0]["generation"], 2)
        self.assertEqual(loaded["thronglets"][0]["lineage_id"], 1)
        self.assertEqual(loaded["thronglets"][0]["genetics"]["learning_affinity"], 1.12)
        self.assertEqual(loaded["thronglets"][0]["skills"]["building"]["level"], 4)
        self.assertEqual(loaded["thronglets"][0]["known_resources"][0]["x"], 100.0)
        self.assertEqual(loaded["thronglets"][0]["disease_elapsed"], 10.0)
        self.assertEqual(loaded["thronglets"][0]["last_reproduction_elapsed"], 18.0)
        self.assertEqual(loaded["advisor"]["civilization_age"], 6)
        self.assertEqual(loaded["advisor"]["total_deaths"], 2)
        self.assertEqual(loaded["advisor"]["last_model_used"], "qwen3.5:35b")
        self.assertEqual(loaded["advisor"]["group_tasks"][0]["task_type"], "build")
        self.assertEqual(loaded["fog_of_war"]["visibility_radius"], 72)
        self.assertEqual(loaded["territory"]["tiles"][0]["center_type"], "building")
        self.assertEqual(loaded["factions"][0]["member_ids"], [7])
        self.assertEqual(loaded["city_planner"]["current_plan"]["districts"][0]["location"], "north")
        self.assertEqual(loaded["world"]["hazards"][0]["damage_rate"], 0.8)
        self.assertEqual(loaded["world"]["npcs"][0]["trade_rates"]["food_for_wood"], 2)


if __name__ == "__main__":
    unittest.main()
