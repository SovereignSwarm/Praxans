import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HeadlessSmokeTests(unittest.TestCase):
    def test_game_exits_cleanly_in_headless_smoke_mode(self):
        env = os.environ.copy()
        env.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

        result = subprocess.run(
            [
                sys.executable,
                "praxans_game.py",
                "--headless",
                "--disable-llm",
                "--max-frames",
                "2",
                "--seed",
                "1",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertIn("SESSION ENDED", result.stdout, msg=result.stderr)
        self.assertNotIn("FATAL ERROR", result.stdout, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
