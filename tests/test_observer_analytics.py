import unittest
from types import SimpleNamespace

from observer_analytics import build_observer_report


class ObserverAnalyticsTests(unittest.TestCase):
    def test_build_observer_report_summarizes_lineages_mortality_and_factions(self):
        praxans = [
            SimpleNamespace(id=1, lineage_id=1, generation=0),
            SimpleNamespace(id=2, lineage_id=1, generation=1),
            SimpleNamespace(id=3, lineage_id=2, generation=2),
        ]
        advisor = SimpleNamespace(
            total_deaths=3,
            group_tasks=[SimpleNamespace(), SimpleNamespace()],
            events_history=[{"time": 11.0, "description": "Built workshop"}],
            session_stats={
                "max_population": 5,
                "births_total": 4,
                "avg_survival_time": 91.5,
                "deaths_by_cause": {"old_age": 2, "health_failure": 1},
                "factions_formed": 2,
                "factions_dissolved": 1,
                "peak_factions": 2,
                "faction_schisms": 1,
                "faction_successions": 2,
                "migration_events": 3,
                "current_evolution_summary": {
                    "lineage_counts": {1: 2, 2: 1},
                    "avg_traits": {
                        "learning_affinity": 1.12,
                        "immune_strength": 0.95,
                    },
                },
                "evolution_history": [{"elapsed_seconds": 20.0, "population": 3, "avg_generation": 1.0}],
                "timeline_events": [
                    {"time": 10.0, "category": "birth", "summary": "Lineage 1 expanded"},
                    {"time": 12.0, "category": "faction", "summary": "Faction 0 formed"},
                ],
                "faction_history": [{"time": 12.0, "action": "formed", "faction_id": 0, "members": 3}],
            },
        )
        faction_manager = SimpleNamespace(
            factions={
                0: SimpleNamespace(
                    member_ids=[1, 2, 3],
                    leader_id=2,
                    shared_goals=[{"type": "build_workshop"}],
                    primary_doctrine="industry",
                    cohesion=64.0,
                    stability=59.0,
                    schism_pressure=34.0,
                    migration_pressure=48.0,
                    rival_faction_ids=[1],
                    succession_count=2,
                    resource_stress=63.0,
                    food_security=42.0,
                    material_security=38.0,
                    ecology_fertility=46.0,
                ),
            }
        )

        report = build_observer_report(praxans, advisor, faction_manager)

        self.assertEqual(report["population"], 3)
        self.assertEqual(report["max_population"], 5)
        self.assertEqual(report["births_total"], 4)
        self.assertEqual(report["deaths_total"], 3)
        self.assertEqual(report["active_group_tasks"], 2)
        self.assertEqual(report["faction_schisms"], 1)
        self.assertEqual(report["faction_successions"], 2)
        self.assertEqual(report["migration_events"], 3)
        self.assertEqual(report["top_lineages"][0]["lineage_id"], 1)
        self.assertEqual(report["top_lineages"][0]["count"], 2)
        self.assertEqual(report["mortality"][0]["label"], "Old Age")
        self.assertEqual(report["active_factions"][0]["members"], 3)
        self.assertEqual(report["active_factions"][0]["leader_id"], 2)
        self.assertEqual(report["active_factions"][0]["doctrine"], "industry")
        self.assertEqual(report["active_factions"][0]["resource_stress"], 63.0)
        self.assertEqual(report["active_factions"][0]["food_security"], 42.0)
        self.assertEqual(report["active_factions"][0]["material_security"], 38.0)
        self.assertEqual(report["active_factions"][0]["ecology_fertility"], 46.0)
        self.assertEqual(report["timeline"][-1]["summary"], "Faction 0 formed")
        self.assertEqual(report["faction_history"][0]["action"], "formed")

    def test_build_observer_report_skips_non_numeric_avg_traits(self):
        advisor = SimpleNamespace(
            total_deaths=0,
            group_tasks=[],
            events_history=[],
            session_stats={
                "current_evolution_summary": {
                    "lineage_counts": {1: 1},
                    "avg_traits": {
                        "learning_affinity": "n/a",
                        "immune_strength": 0.95,
                    },
                },
            },
        )

        report = build_observer_report([SimpleNamespace(id=1, lineage_id=1, generation=0)], advisor, faction_manager=None)

        self.assertEqual(len(report["trait_outliers"]), 1)
        self.assertEqual(report["trait_outliers"][0]["trait_name"], "immune_strength")

    def test_build_observer_report_handles_non_numeric_timeline_time(self):
        praxans = [SimpleNamespace(id=9, lineage_id=9, generation=0)]
        advisor = SimpleNamespace(
            total_deaths=0,
            group_tasks=[],
            events_history=[],
            session_stats={
                "current_evolution_summary": {
                    "lineage_counts": {9: 1},
                    "avg_traits": {"metabolism_efficiency": 1.0},
                },
                "timeline_events": [
                    {"time": "unknown", "category": "faction", "summary": "Malformed timestamp"},
                    {"time": 2.0, "category": "faction", "summary": "Faction formed"},
                ],
            },
        )

        report = build_observer_report(praxans, advisor, faction_manager=None)

        self.assertEqual(len(report["timeline"]), 2)
        self.assertEqual(report["timeline"][0]["summary"], "Malformed timestamp")
        self.assertEqual(report["timeline"][0]["time"], 0.0)
        self.assertEqual(report["timeline"][1]["summary"], "Faction formed")
    def test_build_observer_report_handles_non_numeric_faction_metrics(self):
        praxans = [SimpleNamespace(id=1, lineage_id=1, generation=0)]
        advisor = SimpleNamespace(
            total_deaths=0,
            group_tasks=[],
            events_history=[],
            session_stats={
                "current_evolution_summary": {
                    "lineage_counts": {1: 1},
                    "avg_traits": {"metabolism_efficiency": 1.0},
                },
            },
        )
        faction_manager = SimpleNamespace(
            factions={
                0: SimpleNamespace(
                    member_ids=[1],
                    leader_id=1,
                    shared_goals=[],
                    primary_doctrine="growth",
                    cohesion="bad",
                    stability="59.5",
                    schism_pressure=None,
                    migration_pressure="unknown",
                    rival_faction_ids=[],
                    succession_count=0,
                    resource_stress="x",
                    food_security="n/a",
                    material_security=37.5,
                    ecology_fertility="fertile",
                ),
            }
        )

        report = build_observer_report(praxans, advisor, faction_manager)

        faction = report["active_factions"][0]
        self.assertEqual(faction["cohesion"], 0.0)
        self.assertEqual(faction["stability"], 59.5)
        self.assertEqual(faction["schism_pressure"], 0.0)
        self.assertEqual(faction["migration_pressure"], 0.0)
        self.assertEqual(faction["resource_stress"], 0.0)
        self.assertEqual(faction["food_security"], 52.0)
        self.assertEqual(faction["material_security"], 37.5)
        self.assertEqual(faction["ecology_fertility"], 70.0)
    def test_build_observer_report_falls_back_to_existing_events_when_timeline_is_missing(self):
        praxans = [SimpleNamespace(id=7, lineage_id=7, generation=0)]
        advisor = SimpleNamespace(
            total_deaths=0,
            group_tasks=[],
            events_history=[{"time": 4.0, "description": "Built house"}],
            session_stats={
                "current_evolution_summary": {
                    "lineage_counts": {7: 1},
                    "avg_traits": {"metabolism_efficiency": 1.0},
                },
                "lineage_events": [{"time": 3.0, "label": "Birth: #7 G0 L7"}],
            },
        )

        report = build_observer_report(praxans, advisor, faction_manager=None)

        self.assertEqual(len(report["timeline"]), 2)
        self.assertEqual(report["timeline"][0]["category"], "lineage")
        self.assertEqual(report["timeline"][1]["summary"], "Built house")


if __name__ == "__main__":
    unittest.main()

