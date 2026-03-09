import sys
import unittest


_saved_argv = sys.argv
sys.argv = sys.argv[:1]
import praxans_game  # noqa: F401
sys.argv = _saved_argv

from entities.praxan import Praxan


class PraxanGoalTests(unittest.TestCase):
    def test_migrate_goal_accepts_coordinate_target(self):
        praxan = Praxan(0, 0)
        praxan.needs['hunger'] = 100
        praxan.needs['energy'] = 100
        praxan.personal_goal = {
            "type": "migrate",
            "target": {"x": 120.0, "y": 0.0},
            "reason": "regression coverage",
        }

        result = praxan.decide_action(
            resources=[],
            buildings=[],
            delta_time=0.1,
            directives=[],
            is_night=False,
            other_praxans=[],
            group_tasks={},
            conditional_behaviors=[],
            territory_manager=None,
            city_planner=None,
            hazards=[],
            world_map=None,
            game_hour=12,
            rooms=[],
        )

        self.assertIsNone(result)
        self.assertEqual(praxan.current_action, "goal: migrating")
        self.assertIsNotNone(praxan.personal_goal)
        self.assertGreater(praxan.vx, 0.0)

    def test_legacy_moodlet_schema_is_normalized(self):
        praxan = Praxan(0, 0)
        praxan.moodlets = [
            {
                "id": "disaster_earthquake",
                "label": "Survived Earthquake",
                "offset": -6,
                "duration": 30.0,
                "applied_at": 100.0,
            }
        ]

        praxan.update_mood(current_time=110.0, delta_time=1.0)
        praxan.add_moodlet("Sick: Fever", -8, 120, 110.0)

        self.assertEqual(praxan.moodlets[0]["name"], "Survived Earthquake")
        self.assertEqual(praxan.moodlets[0]["start_time"], 100.0)
        self.assertIn("Sick: Fever", [m["name"] for m in praxan.moodlets])


if __name__ == "__main__":
    unittest.main()
