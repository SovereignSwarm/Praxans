import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.simulation_lab import render_markdown_report, summarize_batch

_TEST_TMP_ROOT = Path('.tmp') / 'test-temp'
_TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


class SimulationLabTests(unittest.TestCase):
    def test_summarize_batch_counts_failures_and_extinctions(self):
        results = [
            {
                "name": "run_ok",
                "success": True,
                "findings": [],
                "report": {"crash_count": 0},
                "summary": {"score": 12},
                "wall_clock_seconds": 18.4,
            },
            {
                "name": "run_bad",
                "success": False,
                "findings": ["extinction", "missing_telemetry"],
                "report": {"crash_count": 1},
                "summary": {"score": 4},
                "wall_clock_seconds": 23.7,
            },
        ]

        summary = summarize_batch(results)

        self.assertEqual(summary["total_runs"], 2)
        self.assertEqual(summary["successful_runs"], 1)
        self.assertEqual(summary["failed_runs"], 1)
        self.assertEqual(summary["crashes_reported"], 1)
        self.assertEqual(summary["extinctions"], ["run_bad"])
        self.assertEqual(summary["highest_score"], 12)
        self.assertEqual(summary["longest_wall_clock_seconds"], 23.7)

    def test_render_markdown_report_lists_runs_and_anomalies(self):
        tmpdir = tempfile.mkdtemp(dir=_TEST_TMP_ROOT)
        try:
            report = render_markdown_report(
                Path(tmpdir),
                {
                    "total_runs": 1,
                    "successful_runs": 0,
                    "failed_runs": 1,
                    "crashes_reported": 1,
                    "highest_score": 7,
                    "longest_wall_clock_seconds": 11.2,
                },
                [
                    {
                        "name": "run_bad",
                        "headless": True,
                        "scenario": "standard",
                        "seed": 7,
                        "findings": ["missing_telemetry"],
                        "artifacts": {"run_dir": str(Path(tmpdir) / "run_bad")},
                        "summary": {
                            "population": 2,
                            "buildings": 1,
                            "phase_id": "founding",
                            "end_state_id": "brittle_survival",
                            "score": 7,
                        },
                    }
                ],
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self.assertIn("Simulation Lab Report", report)
        self.assertIn("run_bad", report)
        self.assertIn("missing_telemetry", report)
        self.assertIn("## Anomalies", report)


if __name__ == "__main__":
    unittest.main()
