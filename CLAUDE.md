# Praxans — CLAUDE.md

## Project Overview

**Praxans** is an autonomous Pygame civilization sandbox. Small AI-driven creatures ("Praxans") gather resources, build settlements, and react to biome/weather/social conditions. The game is **observer-only** — no live player control over the colony.

LLM integration is via **Ollama** (preferred model: `qwen3.5:9b`). Both Ollama and the `noise` library are optional at import time; the game boots in reduced mode without them.

---

## Running the Game

```bash
# Activate venv first (always)
.venv\Scripts\activate

# Interactive
python praxans_game.py

# Headless smoke test (CI-safe)
python praxans_game.py --headless --disable-llm --max-frames 2 --seed 1

# Resume latest snapshot
python praxans_game.py --load-latest-snapshot

# Run a scenario
python praxans_game.py --scenario high_mutation
```

Windows launchers: `start_game.bat`, `start_game.ps1`, `start_game.vbs`, `start_game_with_logging.bat`

## Tests

```bash
python -m unittest discover -s tests
```

## Compile Check

```bash
python -m py_compile praxans_game.py runtime_config.py
```

---

## Architecture

### Entry Points
| File | Role |
|---|---|
| `praxans_game.py` | Main game loop, simulation tick, all top-level state |
| `runtime_config.py` | CLI arg parsing (`RuntimeConfig` frozen dataclass), `UserSettings` (loads from `settings.json`) |

### Packages

| Package | Purpose |
|---|---|
| `entities/` | `Praxan` entity class — **imports `from praxans_game import *`** (tight coupling by design) |
| `systems/` | Game subsystems (see below) |
| `llm/` | Ollama client, async scheduler, prompts, interpreters |
| `graphics/` | Scene/entity/effects/terrain renderers, palette, frame models, sprites |
| `map/` | World generation, biome/planet models |
| `ui/` | Shell (command center), HUD, inspect drawer, analytics, camera director |
| `events/` | Event bus, cascades, incidents |
| `defs/core/` | JSON content files loaded by `DefDatabase` |
| `tests/` | `unittest` test suite |

### Key Systems (`systems/`)

| File | Description |
|---|---|
| `def_database.py` | **RimWorld-style content registry.** Recursively loads all `defs/**/*.json` at startup. Access via `DefDatabase.get_all("BuildingDef")` etc. |
| `ticker.py` | **Staggered tick engine** (RimWorld-inspired). Normal tick every frame; Rare every 250 ticks (~4s); Long every 2000 ticks (~33s). Prevents performance spikes at scale. |
| `praxan_memory.py` | **Per-Praxan autobiographical memory.** Each Praxan carries a bounded (24-entry), personality-weighted episodic memory. Events (birth, grief, partnership, combat, masterwork, etc.) are auto-recorded with emotional weights influenced by curiosity/sociability/diligence. Surfaced in inspect drawer, LLM council views, and snapshots. Defs in `defs/core/memory_events.json`. |
| `policies.py` | Colony policy manager: food (lavish/simple/raw_only), medical (best/herbal/none), hostility (flee/fight/ignore). |
| `dev_mode.py` | F12 developer overlay — entity spawning, force kill/heal, incident triggers, speed override, god mode. |
| `advisor.py` | LLM-powered advisor |
| `society.py` | Society/faction mechanics, trade system |
| `diplomacy.py` | **Inter-faction diplomacy**: standings (-100..+100), relation tiers (Allied/Friendly/Neutral/Tense/Hostile), treaties (Trade/NAP/Alliance), diplomatic incidents, autonomous actions. Replaces hardcoded rivalries. |
| `social_interactions.py` | **InteractionDef execution engine.** 8 data-driven social interactions (chat, deep conversation, argument, share meal, teach, comfort, play, insult) with precondition checking, personality-weighted selection, outcome application (moodlets, bonds, opinions, social need, XP, memory), cooldowns, and EventBus publishing. Defs in `defs/core/interactions.json`. |
| `disease.py` | **Named disease/epidemic system.** 5 typed diseases (Gut Rot, Grey Lung, Swamp Fever, Blood Plague, Muscle Worm) with incubation→symptomatic→recovery stages, proximity-based transmission, capacity penalties, immunity buildup, quarantine at hospitals, epidemic detection. Replaces the old `diseased` boolean. Defs in `defs/core/diseases.json`. |
| `spatial.py` | Spatial indexing |
| `storyteller.py` | Event/crisis storytelling |

### LLM Subsystem (`llm/`)

Four async channels processed by `LLMScheduler`:
- `CHANNEL_COUNCIL` — colony-wide decisions
- `CHANNEL_FACTION` — faction intent
- `CHANNEL_HISTORIAN` — narrative memory
- `CHANNEL_MEMORY` — summarized state

`OllamaClient` wraps Ollama, strips `<think>` tags (Qwen), handles model fallback. All LLM work runs off the main thread so slow/failed calls never freeze rendering.

### Content Data (`defs/core/`)

| File | Def Types |
|---|---|
| `buildings.json` | `BuildingDef` |
| `technologies.json` | `TechDef` |
| `items.json` | `ArmorDef`, `WeaponDef` |
| `jobs.json` | `JobDef` — CookMeal, SmithArmor, CraftWeapon |
| `moods.json` | `MoodDef` — AteRawFood, AteFineFood, Catharsis, FoughtOffInfection, + 7 social moodlets (HadChat, HadDeepTalk, HadArgument, WasInsulted, WasComforted, SharedMeal, HadFun, etc.) |
| `interactions.json` | `InteractionDef` — 8 social interaction types with preconditions, outcomes, drama weights, memory events |
| `diseases.json` | `DiseaseDef` — 5 named diseases with severity rates, incubation periods, transmission vectors, biome/season weights, capacity penalties, lethality |

`game_content.py` exposes `BUILDING_DEFINITIONS` as a lazy proxy dict that always reads from `DefDatabase` — never hardcode building data, always go through `DefDatabase`.

### UI (`ui/`)

| File | Role |
|---|---|
| `shell.py` | Command center (start/resume/scenarios/archives/settings) |
| `hud.py` | Live run HUD |
| `inspect.py` | Scrollable entity inspect drawer |
| `analytics.py` | Modal analytics, end-of-run summary |
| `camera_director.py` | Camera bookmarks, auto-follow |
| `input_router.py` | `UIState`, `UIRectRegistry`, entity picking |
| `layout.py` | Layout computation |
| `history_graph.py` | Time-series population/wealth/mood graph *(new, untracked)* |
| `theme.py` | Panel drawing, UI theme |

### Persistence

- **Snapshots**: `logs/snapshot_*.json` — full colony state including lineage, faction, fog-of-war, camera. Resume with `--load-latest-snapshot` or `--snapshot-file`.
- **Archives**: `logs/archive_*.json` — end-of-session summaries with score metadata.
- **Reports/batch logs**: `logs/report_*.json`, `logs/batch_*.log`, `logs/crash_*.log`

---

## Current Git State

**Modified (not committed):**
- `entities/praxan.py`
- `game_content.py`
- `praxans_game.py`

**New/untracked (not yet staged):**
- `defs/core/items.json` — ArmorDef/WeaponDef content
- `defs/core/jobs.json` — JobDef content
- `defs/core/moods.json` — MoodDef content
- `systems/dev_mode.py` — F12 dev overlay
- `systems/policies.py` — Colony policy manager
- `systems/ticker.py` — Staggered tick engine
- `ui/history_graph.py` — Time-series graph
- `crash_output.txt` — Last crash output (do not commit)

---

## Dependencies

```
pygame>=2.6,<3.0
ollama>=0.6,<1.0      # optional
noise>=1.2.2,<2.0     # optional (falls back to math-based approximation)
```

Python 3.8+ (codebase uses cpython 3.13/3.14 based on `__pycache__`).

---

## Key Conventions

- **Observer-only**: Do not add player control mechanics. The simulation runs autonomously.
- **Optional imports**: Ollama and noise must stay optional. Guard with `try/except ImportError`.
- **Wildcard import**: `entities/praxan.py` uses `from praxans_game import *` intentionally — it needs access to all top-level game state. Do not refactor without considering this dependency.
- **DefDatabase is the source of truth**: All authored game content (buildings, tech, items, jobs, moods) lives in `defs/core/*.json`. Load via `DefDatabase`, never hardcode.
- **Async LLM**: Submit jobs via `LLMScheduler.submit()`, poll via `scheduler.poll()`. Never block the render loop on LLM calls.
- **Staggered ticking**: Register entities with `TickManager` using the appropriate tick frequency. Only use `needs_rare=True` or `needs_long=True` for infrequent updates.
- **Logs go to `logs/`**: Runtime logs, snapshots, archives, and crash output all land here. `crash_output.txt` in the repo root is a temp artifact.
- **No CLAUDE.md in commits** unless explicitly asked.

---

## Scenario Presets

`standard`, `fertile_floodplain`, `harsh_winter_basin`, `plague_start`, `scarce_stone`, `high_mutation`

Defined in `game_scenarios.py`. Smoke test any new scenario with `--headless --disable-llm --max-frames 2`.
