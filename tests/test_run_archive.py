import os
import unittest
from types import SimpleNamespace

from test_tempdir import workspace_tempdir

from run_archive import (
    build_archive_comparison,
    build_run_archive,
    build_run_summary,
    classify_end_state,
    classify_run_phase,
    find_recent_archives,
    write_run_archive,
)


class RunArchiveTests(unittest.TestCase):
    def _build_advisor(self):
        return SimpleNamespace(
            session_stats={
                "max_population": 9,
                "births_total": 5,
                "deaths_by_cause": {"health_failure": 1},
                "avg_survival_time": 88.0,
                "peak_factions": 2,
                "factions_formed": 2,
                "factions_dissolved": 1,
                "current_evolution_summary": {
                    "lineage_counts": {1: 4, 2: 2},
                    "avg_traits": {"adaptability": 1.08, "social_cohesion": 1.12},
                },
                "evolution_history": [{"elapsed_seconds": 30.0, "population": 6, "avg_generation": 1.5}],
                "timeline_events": [{"time": 100.0, "category": "birth", "summary": "Birth surge"}],
                "lineage_events": [{"time": 90.0, "label": "Lineage 1 dominates"}],
                "faction_history": [{"time": 95.0, "action": "formed", "faction_id": 0, "members": 4}],
            },
            total_deaths=1,
            group_tasks=[],
            current_settlement_state={
                "district_identity": "agrarian",
                "prosperity_score": 0.74,
                "culture_score": 0.58,
                "festival_readiness": 0.62,
            },
            council_state={
                "doctrine": {"focus": "growth", "stance": "measured"},
                "strategic_priorities": [{"key": "food_security", "weight": 0.9}],
                "event_framing": "A stable expansion wave.",
            },
            active_challenges=[],
        )

    def test_classify_run_phase_and_end_state(self):
        phase_id = classify_run_phase(elapsed_seconds=210.0, population=9, building_count=6, faction_count=2, crisis_count=0)
        self.assertEqual(phase_id, "societal_divergence")

        end_state_id = classify_end_state(
            population=11,
            settlement_state={"prosperity_score": 0.76, "culture_score": 0.55},
            observer_report={
                "mortality": [{"cause_id": "health_failure", "count": 1}],
                "deaths_total": 1,
                "births_total": 4,
                "peak_factions": 1,
            },
            current_phase="societal_divergence",
            extinction=False,
        )
        self.assertEqual(end_state_id, "thriving_civilization")

    def test_build_and_compare_archives(self):
        praxans = [
            SimpleNamespace(id=1, lineage_id=1, generation=2),
            SimpleNamespace(id=2, lineage_id=1, generation=1),
            SimpleNamespace(id=3, lineage_id=1, generation=2),
            SimpleNamespace(id=4, lineage_id=1, generation=3),
            SimpleNamespace(id=5, lineage_id=2, generation=1),
            SimpleNamespace(id=6, lineage_id=2, generation=2),
        ]
        buildings = [SimpleNamespace(building_type="house"), SimpleNamespace(building_type="farm")]
        advisor = self._build_advisor()
        faction_manager = SimpleNamespace(
            factions={
                0: SimpleNamespace(member_ids=[1, 2, 3, 4], leader_id=1, shared_goals=[{"goal": "Expand"}]),
                1: SimpleNamespace(member_ids=[5, 6], leader_id=5, shared_goals=[]),
            }
        )

        summary = build_run_summary(
            praxans=praxans,
            buildings=buildings,
            advisor=advisor,
            current_time=120.0,
            game_start_time=0.0,
            settlement_state=advisor.current_settlement_state,
            faction_manager=faction_manager,
            scenario_id="high_mutation",
            scenario_name="High Mutation",
            selected_model="qwen3.5:9b",
            seed=7,
            session_id="session_a",
            camera_bookmarks=[{"label": "Birth wave", "category": "birth", "x": 40.0, "y": 20.0, "time": 118.0}],
            scene_thumbnail_key="thumb_session_a.png",
        )
        self.assertEqual(summary["scenario"]["id"], "high_mutation")
        self.assertEqual(summary["council"]["doctrine"]["focus"], "growth")
        self.assertIn("key_moments", summary)
        self.assertIn("phase_history", summary)
        self.assertIn("population_curve", summary)
        self.assertEqual(summary["population_curve"][0]["elapsed_seconds"], 30.0)
        self.assertEqual(summary["population_curve"][0]["avg_generation"], 1.5)
        self.assertIn("death_cause_breakdown", summary)
        self.assertIn("lineage_highlights", summary)
        self.assertIn("faction_highlights", summary)
        self.assertEqual(summary["camera_bookmarks"][0]["label"], "Birth wave")
        self.assertEqual(summary["scene_thumbnail_key"], "thumb_session_a.png")
        self.assertIn("focus_moments", summary)

        archive = build_run_archive(
            praxans=praxans,
            buildings=buildings,
            advisor=advisor,
            current_time=120.0,
            game_start_time=0.0,
            settlement_state=advisor.current_settlement_state,
            faction_manager=faction_manager,
            scenario_id="high_mutation",
            scenario_name="High Mutation",
            selected_model="qwen3.5:9b",
            seed=7,
            session_id="session_a",
            camera_bookmarks=[{"label": "Birth wave", "category": "birth", "x": 40.0, "y": 20.0, "time": 118.0}],
            scene_thumbnail_key="thumb_session_a.png",
        )
        self.assertIn("timeline", archive)
        self.assertEqual(archive["session_id"], "session_a")
        self.assertEqual(archive["scene_thumbnail_key"], "thumb_session_a.png")

        with workspace_tempdir() as temp_dir:
            older_path = write_run_archive(temp_dir, "older", {**archive, "session_id": "older"})
            newer_path = write_run_archive(
                temp_dir,
                "newer",
                {
                    **archive,
                    "session_id": "newer",
                    "summary_card": {**archive["summary_card"], "score": archive["summary_card"]["score"] - 8},
                    "end_state": {**archive["end_state"], "score": archive["end_state"]["score"] - 8},
                },
            )
            with open(os.path.join(temp_dir, "archive_broken.json"), "w", encoding="utf-8") as broken_file:
                broken_file.write("{not-json")
            os.utime(older_path, (1000, 1000))
            os.utime(newer_path, (2000, 2000))

            recent_archives = find_recent_archives(temp_dir, limit=3)
            self.assertIn(newer_path, recent_archives)

            comparison = build_archive_comparison(summary, recent_archives)

        self.assertEqual(len(comparison), 2)
        self.assertIn("score_delta", comparison[0])



    def test_numeric_fields_with_malformed_values_do_not_crash(self):
        end_state = classify_end_state(
            population=2,
            settlement_state={"prosperity_score": "bad", "culture_score": "bad"},
            observer_report={
                "mortality": [{"cause_id": "health_failure", "count": "n/a"}],
                "deaths_total": "unknown",
                "births_total": "unknown",
                "peak_factions": "unknown",
                "factions_dissolved": "unknown",
            },
            current_phase="founding",
            extinction=False,
        )
        self.assertEqual(end_state, "brittle_survival")

        with workspace_tempdir() as temp_dir:
            bad_archive_path = os.path.join(temp_dir, "archive_bad.json")
            with open(bad_archive_path, "w", encoding="utf-8") as archive_file:
                archive_file.write(
                    '{"session_id":"bad","scenario":{"name":"Malformed"},"current_phase":{"label":"Unknown"},'
                    '"end_state":{"label":"Broken","score":"NaN"},"summary_card":{"score":"NaN","population_peak":"bad"}}'
                )

            comparison = build_archive_comparison(
                current_summary={"end_state": {"score": "broken"}},
                archive_paths=[bad_archive_path],
            )

        self.assertEqual(len(comparison), 1)
        self.assertEqual(comparison[0]["score"], 0)
        self.assertEqual(comparison[0]["population_peak"], 0)
        self.assertEqual(comparison[0]["score_delta"], 0)
if __name__ == "__main__":
    unittest.main()



