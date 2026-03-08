import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ui import analytics


class UIAnalyticsCacheTests(unittest.TestCase):
    def setUp(self):
        analytics._archive_cache.clear()

    def test_cache_is_scoped_by_limit(self):
        def fake_find_recent_archives(_log_dir, limit=18):
            return [f"archive_{i}.json" for i in range(limit)]

        def fake_load_run_archive(path):
            session_id = path.replace("archive_", "").replace(".json", "")
            return {
                "session_id": session_id,
                "scenario": {"name": "Scenario"},
                "end_state": {"label": "Stable", "score": 1},
                "summary_card": {"headline": "Run", "score": 1, "population_peak": 1},
                "key_moments": [],
            }

        with mock.patch("ui.analytics.find_recent_archives", side_effect=fake_find_recent_archives), mock.patch(
            "ui.analytics.load_run_archive", side_effect=fake_load_run_archive
        ):
            cards_limited = analytics.load_archive_cards("logs", limit=1)
            cards_expanded = analytics.load_archive_cards("logs", limit=3)

        self.assertEqual(len(cards_limited), 1)
        self.assertEqual(len(cards_expanded), 3)


if __name__ == "__main__":
    unittest.main()
