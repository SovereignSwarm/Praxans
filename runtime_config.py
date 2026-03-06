from __future__ import annotations

import argparse
import builtins
import os
from dataclasses import dataclass
from typing import Optional, Sequence

from game_scenarios import DEFAULT_SCENARIO_ID, format_scenario_help, list_scenario_ids


_NOISY_CONSOLE_PREFIXES = (
    "[DEBUG]",
    "[STATUS",
    "[Thronglet ",
    "[Q-Learning]",
    "[Directive",
    "[JSON Directive]",
    "[Group Task]",
    "[Goal",
    "[Evolution]",
    "[Conditional]",
    "[Advisor Stats]",
)


@dataclass(frozen=True)
class RuntimeConfig:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    headless: bool = False
    max_frames: Optional[int] = None
    disable_llm: bool = False
    verbose_console: bool = False
    log_level: str = "INFO"
    log_dir: str = "logs"
    seed: Optional[int] = None
    enable_probe_log: bool = False
    model: str = "qwen3.5:35b"
    snapshot_file: Optional[str] = None
    load_latest_snapshot: bool = False
    scenario: str = DEFAULT_SCENARIO_ID


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def parse_runtime_config(argv: Optional[Sequence[str]] = None) -> RuntimeConfig:
    parser = argparse.ArgumentParser(description="Run the Thronglets simulation.")
    parser.add_argument("--width", type=_positive_int, default=1920, help="Window width in pixels.")
    parser.add_argument("--height", type=_positive_int, default=1080, help="Window height in pixels.")
    parser.add_argument("--fps", type=_positive_int, default=30, help="Target frames per second.")
    parser.add_argument("--headless", action="store_true", help="Use SDL's dummy video driver for non-interactive runs.")
    parser.add_argument("--max-frames", type=_positive_int, default=None, help="Exit automatically after this many frames.")
    parser.add_argument("--disable-llm", action="store_true", help="Disable all Ollama-powered behavior.")
    parser.add_argument("--verbose-console", action="store_true", help="Show verbose simulation traces in the console.")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Python logging level for session logs and console output.",
    )
    parser.add_argument("--log-dir", default="logs", help="Directory for runtime logs and reports.")
    parser.add_argument("--seed", type=int, default=None, help="Deterministic random seed for reproducible runs.")
    parser.add_argument(
        "--enable-probe-log",
        action="store_true",
        help="Enable the low-level debug probe log used for render diagnostics.",
    )
    parser.add_argument(
        "--model",
        default="qwen3.5:35b",
        help="Preferred Ollama model name.",
    )
    parser.add_argument(
        "--snapshot-file",
        default=None,
        help="Resume the simulation from a specific session snapshot JSON file.",
    )
    parser.add_argument(
        "--load-latest-snapshot",
        action="store_true",
        help="Resume from the newest snapshot found in the log directory.",
    )
    parser.add_argument(
        "--scenario",
        choices=list_scenario_ids(),
        default=DEFAULT_SCENARIO_ID,
        help=f"Observer scenario preset. Options: {format_scenario_help()}",
    )
    args = parser.parse_args(argv)
    return RuntimeConfig(
        width=args.width,
        height=args.height,
        fps=args.fps,
        headless=args.headless,
        max_frames=args.max_frames,
        disable_llm=args.disable_llm,
        verbose_console=args.verbose_console,
        log_level=args.log_level,
        log_dir=args.log_dir,
        seed=args.seed,
        enable_probe_log=args.enable_probe_log,
        model=args.model,
        snapshot_file=args.snapshot_file,
        load_latest_snapshot=args.load_latest_snapshot,
        scenario=args.scenario,
    )


def configure_environment(config: RuntimeConfig) -> None:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    if config.headless:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


def build_console_printer(config: RuntimeConfig):
    builtin_print = builtins.print

    def runtime_print(*args, **kwargs):
        message = " ".join(str(arg) for arg in args).strip()
        if config.verbose_console or not message.startswith(_NOISY_CONSOLE_PREFIXES):
            builtin_print(*args, **kwargs)

    return runtime_print
