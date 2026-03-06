# Thronglets

Thronglets is an autonomous Pygame civilization sandbox where small AI-driven creatures gather resources, build settlements, and react to changing biome, weather, and social conditions while you watch in observer mode.

## What changed in this upgrade

- Restored a broken main loop and render pipeline so the game compiles and launches again.
- Added a real runtime CLI for headless smoke tests, deterministic seeds, logging control, and LLM opt-out.
- Reduced default console spam and bounded session log growth with rotating log files.
- Made Ollama and Perlin noise optional at import time so the project can still boot in reduced mode.
- Modernized the Windows launchers to prefer the repo's virtualenv and capture logs consistently.
- Added automated smoke tests.
- Retuned the live simulation with richer settlement mood systems, district identity, celebration surges, and upgraded HUD feedback.
- Switched the Ollama default model preference to `qwen3.5:35b`.
- Centralized buildings, tech, abilities, and goal types into a shared content layer.
- Added structured end-of-session state snapshots to `logs/snapshot_*.json` and resume support from those snapshots.
- Moved advisor and goal-generation Ollama work off the main loop so the game keeps rendering while Qwen is busy or unavailable.
- Removed live player steering from the runtime flow so the simulation stays observer-first.
- Added heritable thronglet traits, lineage tracking, mutation drift, and a dedicated evolution observer panel.
- Expanded snapshot fidelity so resumed runs keep lineage state, observer camera state, and festival timing.
- Expanded snapshot fidelity again so resumed runs now keep fog-of-war discovery, territory claim memory, faction/group coordination, and world encounters/hazards/NPC state.
- Added observer scenario presets so autonomous runs can start from distinct ecological and evolutionary conditions without introducing player control.
- Added observer analytics tooling with a structured timeline, mortality summaries, lineage dominance tracking, and faction churn visibility.
- Added run archive summaries so completed observer sessions now emit `logs/archive_*.json` alongside snapshots for comparison and scoring.
- Added deeper faction society mechanics with doctrine drift, leadership succession, schism pressure, and migration-frontier behavior.

## Requirements

- Python 3.8+
- Optional: Ollama plus at least one local model if you want advisor and goal-generation features
- Recommended Ollama model: `qwen3.5:35b`

Install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Running the game

Interactive run:

```bash
python thronglets_game.py
```

Observer controls:

- Mouse drag or minimap click to inspect the world
- Mouse hover/click to inspect entities
- `F` to toggle auto-follow
- `1` / `2` / `5` to change sim speed
- `R` to inspect research/evolution modifiers
- `S` to open the evolution observer panel with lineage events and trait drift
- `T` to open the observer analytics panel with timeline, mortality, and faction summaries
- `A` to open the run archive review panel with phase, end-state, and recent-run comparisons
- Active faction migration pressure now appears in-world as frontier route lines pointing toward migration targets

Explicitly target the preferred Qwen model:

```bash
python thronglets_game.py --model qwen3.5:35b
```

Disable LLM features:

```bash
python thronglets_game.py --disable-llm
```

Headless smoke run:

```bash
python thronglets_game.py --headless --disable-llm --max-frames 2 --seed 1
```

Run a preset observer scenario:

```bash
python thronglets_game.py --scenario high_mutation
```

Scenario smoke run:

```bash
python thronglets_game.py --headless --disable-llm --scenario plague_start --max-frames 2 --seed 1
```

Resume the newest snapshot:

```bash
python thronglets_game.py --load-latest-snapshot
```

Resume a specific snapshot:

```bash
python thronglets_game.py --snapshot-file logs\snapshot_20260306_180259.json
```

Windows launchers:

- `start_game.bat`
- `start_game_with_logging.bat`
- `start_game.ps1`
- `start_game.vbs`

## Useful CLI flags

- `--headless`
  Uses SDL's dummy video driver for non-interactive runs.
- `--max-frames N`
  Exits automatically after `N` frames.
- `--disable-llm`
  Skips all Ollama requests.
- `--model MODEL_NAME`
  Sets the preferred Ollama model. Default: `qwen3.5:35b`.
- `--verbose-console`
  Re-enables noisy simulation traces that are suppressed by default.
- `--log-level {DEBUG,INFO,WARNING,ERROR}`
  Controls Python logger output.
- `--seed N`
  Makes smoke runs reproducible.
- `--load-latest-snapshot`
  Boots from the newest `logs/snapshot_*.json`.
- `--snapshot-file PATH`
  Boots from a specific snapshot JSON file.
- `--scenario PRESET`
  Starts the autonomous observer run with a named preset such as `standard`, `high_mutation`, `plague_start`, or `harsh_winter_basin`.

## Scenario presets

- `standard`
  Balanced baseline observer run.
- `fertile_floodplain`
  Faster early growth, more food, gentler mutation pressure.
- `harsh_winter_basin`
  Cold start with tighter food pressure and harsher weather cadence.
- `plague_start`
  Larger colony beginning under disease pressure.
- `scarce_stone`
  Construction bottlenecked by mineral scarcity.
- `high_mutation`
  Elevated mutation drift and a larger starting cluster for faster divergence.

## Verification

Compile check:

```bash
python -m py_compile thronglets_game.py runtime_config.py
```

Test suite:

```bash
python -m unittest discover -s tests
```

## Notes

- If Ollama is unavailable, the simulation still runs; LLM-driven behaviors simply stay disabled.
- If Ollama is available, the game now prefers `qwen3.5:35b` and falls back through a curated local-model list.
- Advisor and personal-goal requests now run asynchronously, so slow or failed local-model calls should not freeze the render loop.
- The game is observer-only by design; there is no live player command channel into the colony AI.
- If `noise` is unavailable, city zoning falls back to a deterministic math-based noise approximation.
- Runtime logs and reports are written to `logs/`.
- End-of-session structured state snapshots are written to `logs/snapshot_*.json`, and those files can be used to resume a colony run.
- End-of-session run archive summaries are written to `logs/archive_*.json` with phase, end-state, and observer score metadata.
- Snapshots now retain the active scenario ID so resumed runs preserve the same observer conditions and mutation profile.
- The observer analytics view highlights lineage dominance, death causes, faction formation/dissolution, and recent colony milestones so long autonomous runs are easier to read.
- Factions can now accumulate succession pressure, split into schisms, and push migration goals without any player intervention.
