from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOGS_ROOT = ROOT / "logs"
DEFAULT_HEADLESS_SCENARIOS = (
    "standard",
    "fertile_floodplain",
    "harsh_winter_basin",
    "plague_start",
    "high_mutation",
    "volcanic_crucible",
)


@dataclass(frozen=True)
class RunSpec:
    name: str
    scenario: str
    seed: int
    max_frames: int
    log_dir: Path
    headless: bool
    snapshot_file: Path | None = None
    session_tag: str = ""
    with_llm: bool = False
    model: str = "qwen3.5:9b"
    telemetry_interval: float = 2.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-run Praxans simulations with detailed logging.")
    parser.add_argument(
        "--headless-scenarios",
        nargs="+",
        default=list(DEFAULT_HEADLESS_SCENARIOS),
        help="Scenario ids for fresh headless runs.",
    )
    parser.add_argument(
        "--headless-seeds",
        nargs="+",
        type=int,
        default=[11, 23],
        help="Seeds used for each headless scenario.",
    )
    parser.add_argument(
        "--headless-max-frames",
        type=int,
        default=1800,
        help="Frame budget for each fresh headless run.",
    )
    parser.add_argument(
        "--resume-runs",
        type=int,
        default=1,
        help="How many headless continuation runs to launch from each successful fresh snapshot.",
    )
    parser.add_argument(
        "--resume-max-frames",
        type=int,
        default=1200,
        help="Frame budget for each continuation run.",
    )
    parser.add_argument(
        "--visual-checks",
        type=int,
        default=2,
        help="How many successful headless runs to replay visually from their snapshots.",
    )
    parser.add_argument(
        "--visual-max-frames",
        type=int,
        default=240,
        help="Frame budget for each visual verification run.",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=2,
        help="Concurrent fresh headless subprocesses.",
    )
    parser.add_argument(
        "--telemetry-interval",
        type=float,
        default=2.0,
        help="Seconds between structured telemetry samples.",
    )
    parser.add_argument(
        "--output-root",
        default=str(LOGS_ROOT),
        help="Directory where batch folders will be created.",
    )
    parser.add_argument(
        "--model",
        default="qwen3.5:9b",
        help="Preferred local LLM model for game runs and optional batch review.",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Allow in-game LLM systems during runs.",
    )
    parser.add_argument(
        "--monitor-with-llm",
        action="store_true",
        help="Generate a post-run local-LLM review from the aggregated batch summary when possible.",
    )
    return parser.parse_args(argv)


def resolve_python_command() -> list[str]:
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return [str(venv_python)]
    if sys.executable:
        return [sys.executable]
    launcher = shutil.which("py")
    if launcher:
        return [launcher, "-3"]
    python_bin = shutil.which("python")
    if python_bin:
        return [python_bin]
    raise RuntimeError("No usable Python interpreter found for subprocess runs.")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_jsonl_tail(path: Path | None) -> tuple[int, dict[str, Any] | None]:
    if path is None or not path.exists():
        return 0, None

    count = 0
    last_sample: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            count += 1
            try:
                last_sample = json.loads(line)
            except json.JSONDecodeError:
                continue
    return count, last_sample


def _artifact_path(run_dir: Path, pattern: str) -> Path | None:
    matches = sorted(run_dir.glob(pattern))
    return matches[-1] if matches else None


def _timeout_seconds(max_frames: int, headless: bool) -> int:
    base = 180 if headless else 240
    return max(base, int((max_frames / 30.0) * 5.0) + 60)


def _completed_process(command: list[str], timeout: int, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def execute_run(spec: RunSpec, python_cmd: list[str]) -> dict[str, Any]:
    spec.log_dir.mkdir(parents=True, exist_ok=True)
    command = [
        *python_cmd,
        "praxans_game.py",
        "--scenario",
        spec.scenario,
        "--seed",
        str(spec.seed),
        "--max-frames",
        str(spec.max_frames),
        "--log-dir",
        str(spec.log_dir),
        "--log-level",
        "DEBUG",
        "--enable-probe-log",
        "--telemetry-interval",
        str(spec.telemetry_interval),
        "--model",
        spec.model,
        "--session-tag",
        spec.session_tag or spec.name,
    ]
    if spec.headless:
        command.append("--headless")
    if not spec.with_llm:
        command.append("--disable-llm")
    if spec.snapshot_file is not None:
        command.extend(["--snapshot-file", str(spec.snapshot_file)])

    env = os.environ.copy()
    env.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    env["PYTHONPATH"] = str(ROOT)

    started_at = time.time()
    completed = _completed_process(command, _timeout_seconds(spec.max_frames, spec.headless), env=env)
    finished_at = time.time()

    stdout_path = spec.log_dir / "launcher_stdout.log"
    stderr_path = spec.log_dir / "launcher_stderr.log"
    _write_text(stdout_path, completed.stdout)
    _write_text(stderr_path, completed.stderr)

    report_path = _artifact_path(spec.log_dir, "report_*.json")
    archive_path = _artifact_path(spec.log_dir, "archive_*.json")
    snapshot_path = _artifact_path(spec.log_dir, "snapshot_*.json")
    telemetry_path = _artifact_path(spec.log_dir, "telemetry_*.jsonl")
    session_log_path = _artifact_path(spec.log_dir, "session_*.log")
    thumb_path = _artifact_path(spec.log_dir, "thumb_*.png")

    report = _read_json(report_path)
    archive = _read_json(archive_path)
    telemetry_samples, last_telemetry = _read_jsonl_tail(telemetry_path)
    observer_report = dict(archive.get("observer_report", {}) or {})
    end_state = dict(archive.get("end_state", {}) or {})
    current_phase = dict(archive.get("current_phase", {}) or {})
    game_state = dict(report.get("game_state", {}) or {})

    findings = []
    if completed.returncode != 0:
        findings.append(f"process_exit_{completed.returncode}")
    if int(report.get("crash_count", 0) or 0) > 0:
        findings.append("crash_reported")
    if "FATAL ERROR" in completed.stdout:
        findings.append("fatal_stdout")
    if not report_path:
        findings.append("missing_report")
    if not archive_path:
        findings.append("missing_archive")
    if not snapshot_path:
        findings.append("missing_snapshot")
    if telemetry_samples == 0:
        findings.append("missing_telemetry")
    if int(observer_report.get("population", game_state.get("population", 0)) or 0) <= 0:
        findings.append("extinction")

    telemetry_settlement = dict(last_telemetry.get("settlement", {}) or {}) if isinstance(last_telemetry, dict) else {}
    return {
        "name": spec.name,
        "scenario": spec.scenario,
        "seed": spec.seed,
        "headless": spec.headless,
        "max_frames": spec.max_frames,
        "session_tag": spec.session_tag or spec.name,
        "snapshot_source": str(spec.snapshot_file) if spec.snapshot_file else None,
        "started_at": datetime.fromtimestamp(started_at).isoformat(),
        "finished_at": datetime.fromtimestamp(finished_at).isoformat(),
        "wall_clock_seconds": round(finished_at - started_at, 2),
        "returncode": completed.returncode,
        "success": completed.returncode == 0 and not findings,
        "findings": findings,
        "artifacts": {
            "run_dir": str(spec.log_dir.resolve()),
            "stdout_log": str(stdout_path.resolve()),
            "stderr_log": str(stderr_path.resolve()),
            "report": str(report_path.resolve()) if report_path else None,
            "archive": str(archive_path.resolve()) if archive_path else None,
            "snapshot": str(snapshot_path.resolve()) if snapshot_path else None,
            "telemetry": str(telemetry_path.resolve()) if telemetry_path else None,
            "session_log": str(session_log_path.resolve()) if session_log_path else None,
            "thumbnail": str(thumb_path.resolve()) if thumb_path else None,
        },
        "report": {
            "crash_count": int(report.get("crash_count", 0) or 0),
            "total_events": int(report.get("total_events", 0) or 0),
            "telemetry_samples": telemetry_samples,
        },
        "summary": {
            "population": int(observer_report.get("population", game_state.get("population", 0)) or 0),
            "max_population": int(observer_report.get("max_population", 0) or 0),
            "births_total": int(observer_report.get("births_total", 0) or 0),
            "deaths_total": int(observer_report.get("deaths_total", 0) or 0),
            "buildings": int(game_state.get("buildings", 0) or 0),
            "phase_id": str(current_phase.get("id", "")),
            "phase_label": str(current_phase.get("label", "")),
            "end_state_id": str(end_state.get("id", "")),
            "end_state_label": str(end_state.get("label", "")),
            "score": int(end_state.get("score", 0) or 0),
            "district_identity": str(telemetry_settlement.get("district_identity", "")),
            "prosperity_score": float(telemetry_settlement.get("prosperity_score", 0.0) or 0.0),
            "culture_score": float(telemetry_settlement.get("culture_score", 0.0) or 0.0),
        },
        "last_telemetry": last_telemetry,
    }


def create_batch_root(output_root: Path) -> Path:
    batch_root = output_root / f"simlab_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    batch_root.mkdir(parents=True, exist_ok=True)
    return batch_root


def build_fresh_specs(args: argparse.Namespace, batch_root: Path) -> list[RunSpec]:
    specs = []
    index = 1
    for scenario in args.headless_scenarios:
        for seed in args.headless_seeds:
            run_name = f"{index:02d}_{scenario}_seed{seed}_fresh"
            specs.append(
                RunSpec(
                    name=run_name,
                    scenario=scenario,
                    seed=seed,
                    max_frames=args.headless_max_frames,
                    log_dir=batch_root / run_name,
                    headless=True,
                    session_tag=f"simlab:fresh:{scenario}:seed{seed}",
                    with_llm=args.with_llm,
                    model=args.model,
                    telemetry_interval=args.telemetry_interval,
                )
            )
            index += 1
    return specs


def summarize_batch(results: list[dict[str, Any]]) -> dict[str, Any]:
    success_count = sum(1 for result in results if result.get("success"))
    crash_count = sum(int(result.get("report", {}).get("crash_count", 0) or 0) for result in results)
    extinctions = [result["name"] for result in results if "extinction" in result.get("findings", [])]
    highest_score = max((int(result.get("summary", {}).get("score", 0) or 0) for result in results), default=0)
    longest_run = max((float(result.get("wall_clock_seconds", 0.0) or 0.0) for result in results), default=0.0)
    return {
        "total_runs": len(results),
        "successful_runs": success_count,
        "failed_runs": len(results) - success_count,
        "crashes_reported": crash_count,
        "extinctions": extinctions,
        "highest_score": highest_score,
        "longest_wall_clock_seconds": longest_run,
    }


def render_markdown_report(batch_root: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        "# Simulation Lab Report",
        "",
        f"- Batch root: `{batch_root}`",
        f"- Total runs: {summary['total_runs']}",
        f"- Successful runs: {summary['successful_runs']}",
        f"- Failed runs: {summary['failed_runs']}",
        f"- Crashes reported: {summary['crashes_reported']}",
        f"- Highest score: {summary['highest_score']}",
        f"- Longest wall-clock run: {summary['longest_wall_clock_seconds']:.2f}s",
        "",
        "| Run | Mode | Scenario | Seed | Pop | Buildings | Phase | End State | Score | Findings |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- | ---: | --- |",
    ]
    for result in results:
        mode = "headless" if result.get("headless") else "visual"
        result_summary = dict(result.get("summary", {}) or {})
        findings = ", ".join(result.get("findings", [])) or "ok"
        lines.append(
            "| {name} | {mode} | {scenario} | {seed} | {population} | {buildings} | {phase} | {end_state} | {score} | {findings} |".format(
                name=result.get("name", ""),
                mode=mode,
                scenario=result.get("scenario", ""),
                seed=result.get("seed", 0),
                population=result_summary.get("population", 0),
                buildings=result_summary.get("buildings", 0),
                phase=result_summary.get("phase_id", "") or "n/a",
                end_state=result_summary.get("end_state_id", "") or "n/a",
                score=result_summary.get("score", 0),
                findings=findings,
            )
        )

    anomalous = [result for result in results if result.get("findings")]
    if anomalous:
        lines.extend(["", "## Anomalies", ""])
        for result in anomalous:
            lines.append(
                "- `{name}`: {findings} | artifacts `{run_dir}`".format(
                    name=result.get("name", ""),
                    findings=", ".join(result.get("findings", [])),
                    run_dir=result.get("artifacts", {}).get("run_dir", ""),
                )
            )
    return "\n".join(lines) + "\n"


def ollama_available() -> bool:
    binary = shutil.which("ollama")
    if not binary:
        return False

    probe = _completed_process([binary, "list"], 15)
    return probe.returncode == 0


def render_llm_prompt(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    compact_results = []
    for result in results:
        compact_results.append(
            {
                "name": result.get("name"),
                "scenario": result.get("scenario"),
                "seed": result.get("seed"),
                "mode": "headless" if result.get("headless") else "visual",
                "findings": result.get("findings", []),
                "summary": result.get("summary", {}),
            }
        )

    payload = {
        "summary": summary,
        "results": compact_results,
    }
    return (
        "You are reviewing a batch of Praxans simulation runs. "
        "Identify likely bugs, suspicious patterns, and the highest-value next debugging steps. "
        "Do not reveal chain-of-thought or internal reasoning. "
        "Respond with short sections titled Findings and Next Steps.\n\n"
        + json.dumps(payload, indent=2)
    )


def _sanitize_llm_review(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").strip()
    marker = "\n**Likely Bugs**"
    if marker in cleaned:
        cleaned = cleaned.split(marker, 1)[1]
        cleaned = "**Likely Bugs**" + cleaned
    elif "Findings" in cleaned:
        cleaned = cleaned[cleaned.index("Findings") :]
    elif cleaned.lower().startswith("thinking..."):
        parts = cleaned.split("\n\n")
        cleaned = parts[-1].strip()
    return cleaned.strip() + "\n"


def generate_llm_review(batch_root: Path, model: str, summary: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    review_path = batch_root / "llm_batch_review.md"
    if not ollama_available():
        return {
            "enabled": False,
            "reason": "ollama_unavailable",
            "review_file": None,
        }

    prompt = render_llm_prompt(summary, results)
    response = _completed_process(["ollama", "run", model, prompt], 180)
    if response.returncode != 0:
        _write_text(review_path, response.stderr or response.stdout)
        return {
            "enabled": False,
            "reason": f"ollama_failed_{response.returncode}",
            "review_file": str(review_path.resolve()),
        }

    _write_text(review_path, _sanitize_llm_review(response.stdout))
    return {
        "enabled": True,
        "reason": "ok",
        "review_file": str(review_path.resolve()),
    }


def run_fresh_headless_batch(specs: list[RunSpec], python_cmd: list[str], parallelism: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, parallelism)) as executor:
        future_map = {executor.submit(execute_run, spec, python_cmd): spec for spec in specs}
        for future in as_completed(future_map):
            results.append(future.result())
    results.sort(key=lambda result: result.get("name", ""))
    return results


def run_resume_and_visual_checks(
    fresh_results: list[dict[str, Any]],
    args: argparse.Namespace,
    batch_root: Path,
    python_cmd: list[str],
) -> list[dict[str, Any]]:
    follow_up_results: list[dict[str, Any]] = []
    visual_budget = max(0, args.visual_checks)
    visual_used = 0

    for fresh in fresh_results:
        snapshot_text = fresh.get("artifacts", {}).get("snapshot")
        snapshot_path = Path(snapshot_text) if snapshot_text else None
        if not fresh.get("success") or snapshot_path is None or not snapshot_path.exists():
            continue

        for resume_index in range(max(0, args.resume_runs)):
            resume_name = f"{fresh['name']}_resume{resume_index + 1}"
            resume_spec = RunSpec(
                name=resume_name,
                scenario=str(fresh.get("scenario")),
                seed=int(fresh.get("seed", 0)),
                max_frames=args.resume_max_frames,
                log_dir=batch_root / resume_name,
                headless=True,
                snapshot_file=snapshot_path,
                session_tag=f"simlab:resume:{fresh['scenario']}:seed{fresh['seed']}:r{resume_index + 1}",
                with_llm=args.with_llm,
                model=args.model,
                telemetry_interval=args.telemetry_interval,
            )
            follow_up_results.append(execute_run(resume_spec, python_cmd))

        if visual_used < visual_budget:
            visual_name = f"{fresh['name']}_visual"
            visual_spec = RunSpec(
                name=visual_name,
                scenario=str(fresh.get("scenario")),
                seed=int(fresh.get("seed", 0)),
                max_frames=args.visual_max_frames,
                log_dir=batch_root / visual_name,
                headless=False,
                snapshot_file=snapshot_path,
                session_tag=f"simlab:visual:{fresh['scenario']}:seed{fresh['seed']}",
                with_llm=args.with_llm,
                model=args.model,
                telemetry_interval=args.telemetry_interval,
            )
            follow_up_results.append(execute_run(visual_spec, python_cmd))
            visual_used += 1

    return follow_up_results


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_root = Path(args.output_root)
    python_cmd = resolve_python_command()
    batch_root = create_batch_root(output_root)

    fresh_specs = build_fresh_specs(args, batch_root)
    fresh_results = run_fresh_headless_batch(fresh_specs, python_cmd, args.parallelism)
    follow_up_results = run_resume_and_visual_checks(fresh_results, args, batch_root, python_cmd)
    all_results = fresh_results + follow_up_results

    batch_summary = {
        "batch_root": str(batch_root.resolve()),
        "generated_at": datetime.now().isoformat(),
        "python_command": python_cmd,
        "options": {
            "headless_scenarios": args.headless_scenarios,
            "headless_seeds": args.headless_seeds,
            "headless_max_frames": args.headless_max_frames,
            "resume_runs": args.resume_runs,
            "resume_max_frames": args.resume_max_frames,
            "visual_checks": args.visual_checks,
            "visual_max_frames": args.visual_max_frames,
            "parallelism": args.parallelism,
            "telemetry_interval": args.telemetry_interval,
            "with_llm": args.with_llm,
            "monitor_with_llm": args.monitor_with_llm,
            "model": args.model,
        },
        "summary": summarize_batch(all_results),
        "results": all_results,
    }

    summary_path = batch_root / "batch_summary.json"
    markdown_path = batch_root / "batch_report.md"
    summary_path.write_text(json.dumps(batch_summary, indent=2), encoding="utf-8")
    markdown_path.write_text(
        render_markdown_report(batch_root, batch_summary["summary"], all_results),
        encoding="utf-8",
    )

    llm_review = {
        "enabled": False,
        "reason": "not_requested",
        "review_file": None,
    }
    if args.monitor_with_llm:
        llm_review = generate_llm_review(batch_root, args.model, batch_summary["summary"], all_results)
        batch_summary["llm_review"] = llm_review
        summary_path.write_text(json.dumps(batch_summary, indent=2), encoding="utf-8")

    print(f"Simulation batch complete: {batch_root.resolve()}")
    print(f"Summary JSON: {summary_path.resolve()}")
    print(f"Report Markdown: {markdown_path.resolve()}")
    if llm_review.get("review_file"):
        print(f"LLM Review: {llm_review['review_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
