import unittest

from society_dynamics import choose_migration_target, choose_schism_members, compute_faction_metrics


class SocietyDynamicsTests(unittest.TestCase):
    def test_compute_faction_metrics_derives_pressures_and_doctrine(self):
        members = [
            {
                "id": 1,
                "health": 80,
                "happiness": 68,
                "morale": 72,
                "curiosity": 0.85,
                "sociability": 0.45,
                "learning_affinity": 1.08,
                "immune_strength": 0.96,
                "fertility_drive": 1.02,
                "social_cohesion": 0.82,
                "adaptability": 1.11,
                "favorite_biome": "forest",
                "role": "explorer",
                "known_resources_count": 4,
            },
            {
                "id": 2,
                "health": 76,
                "happiness": 61,
                "morale": 66,
                "curiosity": 0.72,
                "sociability": 0.38,
                "learning_affinity": 1.03,
                "immune_strength": 0.92,
                "fertility_drive": 1.01,
                "social_cohesion": 0.9,
                "adaptability": 1.07,
                "favorite_biome": "desert",
                "role": "gatherer",
                "known_resources_count": 3,
            },
            {
                "id": 3,
                "health": 78,
                "happiness": 64,
                "morale": 69,
                "curiosity": 0.8,
                "sociability": 0.41,
                "learning_affinity": 1.02,
                "immune_strength": 0.95,
                "fertility_drive": 0.98,
                "social_cohesion": 0.88,
                "adaptability": 1.04,
                "favorite_biome": "swamp",
                "role": "explorer",
                "known_resources_count": 5,
            },
        ]

        metrics = compute_faction_metrics(members, avg_bond=38.0)

        self.assertIn(metrics["primary_doctrine"], {"security", "exploration"})
        self.assertGreater(metrics["schism_pressure"], 40.0)
        self.assertGreater(metrics["migration_pressure"], 45.0)

    def test_choose_schism_members_selects_dissenters(self):
        members = [
            {"id": 1, "leader_bond": 80, "happiness": 70, "curiosity": 0.2, "social_cohesion": 1.1, "favorite_biome": "plains", "role": "builder"},
            {"id": 2, "leader_bond": 18, "happiness": 35, "curiosity": 0.9, "social_cohesion": 0.82, "favorite_biome": "desert", "role": "explorer"},
            {"id": 3, "leader_bond": 20, "happiness": 39, "curiosity": 0.82, "social_cohesion": 0.84, "favorite_biome": "forest", "role": "explorer"},
            {"id": 4, "leader_bond": 78, "happiness": 72, "curiosity": 0.3, "social_cohesion": 1.05, "favorite_biome": "plains", "role": "gatherer"},
        ]

        split_ids = choose_schism_members(members, leader_id=1, preferred_biome="plains", minimum_size=2)

        self.assertEqual(split_ids, [2, 3])

    def test_choose_migration_target_prefers_known_frontier_resources(self):
        members = [
            {
                "known_resources": [(120.0, 120.0), (600.0, 420.0)],
            },
            {
                "known_resources": [(420.0, 200.0)],
            },
        ]

        target = choose_migration_target(
            centroid=(100.0, 100.0),
            member_snapshots=members,
            doctrine_key="exploration",
            world_width=800.0,
            world_height=600.0,
            migration_pressure=60.0,
        )

        self.assertEqual(target, (600.0, 420.0))


if __name__ == "__main__":
    unittest.main()
