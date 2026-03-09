import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from game_scenarios import DEFAULT_SCENARIO_ID
from runtime_config import UserSettings, build_console_printer, parse_runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def test_parse_runtime_config_overrides_defaults(self):
        config = parse_runtime_config(
            [
                "--width",
                "1280",
                "--height",
                "720",
                "--fps",
                "60",
                "--headless",
                "--max-frames",
                "5",
                "--disable-llm",
                "--verbose-console",
                "--log-level",
                "DEBUG",
                "--log-dir",
                "tmp-logs",
                "--seed",
                "42",
                "--enable-probe-log",
                "--telemetry-interval",
                "1.5",
                "--model",
                "qwen3.5:9b",
                "--snapshot-file",
                "logs\\snapshot_test.json",
                "--scenario",
                "high_mutation",
                "--session-tag",
                "batch-audit",
            ]
        )

        self.assertEqual(config.width, 1280)
        self.assertEqual(config.height, 720)
        self.assertEqual(config.fps, 60)
        self.assertTrue(config.headless)
        self.assertEqual(config.max_frames, 5)
        self.assertTrue(config.disable_llm)
        self.assertTrue(config.verbose_console)
        self.assertEqual(config.log_level, "DEBUG")
        self.assertEqual(config.log_dir, "tmp-logs")
        self.assertEqual(config.seed, 42)
        self.assertTrue(config.enable_probe_log)
        self.assertEqual(config.telemetry_interval, 1.5)
        self.assertEqual(config.model, "qwen3.5:9b")
        self.assertEqual(config.snapshot_file, "logs\\snapshot_test.json")
        self.assertFalse(config.load_latest_snapshot)
        self.assertEqual(config.scenario, "high_mutation")
        self.assertEqual(config.session_tag, "batch-audit")

    def test_parse_runtime_config_uses_qwen35_default_model(self):
        config = parse_runtime_config([])
        self.assertEqual(config.model, "qwen3.5:9b")
        self.assertEqual(config.scenario, DEFAULT_SCENARIO_ID)
        self.assertEqual(config.telemetry_interval, 5.0)
        self.assertEqual(config.session_tag, "")

    def test_parse_runtime_config_supports_latest_snapshot_flag(self):
        config = parse_runtime_config(["--load-latest-snapshot"])
        self.assertTrue(config.load_latest_snapshot)
        self.assertIsNone(config.snapshot_file)

    def test_console_printer_suppresses_noisy_debug_lines_by_default(self):
        config = parse_runtime_config([])
        runtime_print = build_console_printer(config)
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            runtime_print("[DEBUG] hidden")
            runtime_print("visible line")

        self.assertEqual(buffer.getvalue().strip(), "visible line")

    def test_user_settings_load_ignores_unknown_keys(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "llm_host": "http://localhost:11434",
                    "llm_model": "llama3.1:8b",
                    "global_temperature_modifier": 0.2,
                    "unknown_flag": True,
                },
                handle,
            )

        output = io.StringIO()
        with redirect_stdout(output):
            settings = UserSettings.load(path)

        self.assertEqual(settings.llm_host, "http://localhost:11434")
        self.assertEqual(settings.llm_model, "llama3.1:8b")
        self.assertEqual(settings.global_temperature_modifier, 0.2)
        self.assertIn("Ignoring unknown setting key(s)", output.getvalue())


if __name__ == "__main__":
    unittest.main()
