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
| `rituals.py` | **Rituals & Gatherings.** 6 data-driven faction rituals (Doctrine Renewal, Harvest Thanksgiving, Mourning Ceremony, Naming Day, Seasonal Rite, Victory Celebration) at shrines with moodlets, bond changes, episodic memories, cohesion boosts. Periodic and condition-triggered. Defs in `defs/core/rituals.json`. |
| `spatial.py` | Spatial indexing |
| `ecology.py` | **Regional fertility grid.** Per-512px-cell fertility (0-100) responds to harvesting pressure, season, weather, biome. Drives resource spawn multipliers, EventBus degradation/recovery events. Serialized in snapshots. |
| `reputation.py` | **Reputation & Social Hierarchy.** Per-Praxan reputation (0-100, default 50) rises from building, crafting masterworks, healing, teaching, combat victories, ritual leadership — falls from insults, mental breaks, fleeing combat. 5 tiers (Luminary/Respected/Established/Marginal/Outcast) with moodlets, episodic memories, EventBus events. Weights leader elections, modifies social target selection. Natural drift toward 50. Defs in `defs/core/reputation.json`. |
| `aspirations.py` | **Personal Aspirations & Life Goals.** Each adult Praxan receives a personality-driven aspiration (master crafter, social butterfly, colony leader, bold explorer, etc.). Progress tracked on rare-tick with milestone moodlets at 25/50/75%. Completion yields mood boost (+15), reputation gain, episodic memory. Elder transition = graceful expiry (no penalty). Death = cleanup. One aspiration at a time with 30s reassignment cooldown. Personality-weighted selection prevents identical assignments. Defs in `defs/core/aspirations.json`. |
| `warfare.py` | **Warfare & Raiding.** Inter-faction armed conflict driven by diplomacy standings. Hostile factions (standing < -40) can launch raids: pillage (steal resources), border skirmish (honor fight), sabotage (damage buildings), conquest assault (full-scale). Round-by-round combat with weapon/armor stats, morale checks, fortification bonuses. Consequences: loot transfer, building damage, moodlets (16 warfare-specific), reputation events (7 combat types), episodic memories, diplomacy shifts. Also triggered as storyteller incident. Defs in `defs/core/warfare.json`. |
| `event_cascades.py` | **Event Cascade System.** Cross-system reactive chain reactions. Subscribes to EventBus (death, disaster, warfare, birth) and triggers follow-up effects: mass death → collective trauma moodlets + mourning rituals; combat death → faction grief; epidemic → anxiety + cohesion drop; disaster → resource stress spike; severe disaster → survivor resilience; ecology crash → famine warning + migration pressure; warfare → diplomacy spiral; birth → communal joy + ritual signal. Queues pending effects (moodlets, memory, resilience) applied on rare-tick. Defs in `defs/core/cascades.json`. |
| `traditions.py` | **Cultural Heritage & Traditions.** Factions organically develop traditions from significant events (e.g. 3 wars in 5 min → Warrior Spirit). 10 TraditionDefs with formation thresholds, reinforcement, time-based decay, max 5 per faction, cultural exchange between allied factions, diplomacy modifiers for shared/conflicting traditions, strength-scaled passive bonuses. Subscribes to 9 EventBus categories. Defs in `defs/core/traditions.json`. |
| `migration.py` | **Individual Migration & Faction Defection.** Praxans evaluate satisfaction via push/pull factors (happiness, cohesion, reputation, disease, warfare, family, doctrine) and defect to more appealing factions. 5 MigrationDefs (discontent, war refugee, plague flight, family reunion, ideological exile). Consequences: membership transfer, moodlets (16 types), reputation shifts, cohesion changes, diplomacy penalties, episodic memories. Guards: leader immunity, min faction size, per-faction cooldowns. Defs in `defs/core/migration.json`. |
| `mentorship.py` | **Mentorship & Apprenticeship.** Mentor-apprentice pairs formed by personality-weighted matching within factions. 6 MentorshipDefs (gathering, building, medical, crafting, cooking, exploration). Proximity-based session XP (2.0-3.0× multiplier), bond growth, graduation at target level, breakage on death. Guards: no dual-role (can't be mentor AND apprentice), faction-only, max global cap, cooldowns. Defs in `defs/core/mentorship.json`. |
| `personality_evolution.py` | **Personality Evolution.** Personality traits (curiosity, sociability, diligence) shift gradually based on life experiences. 21 PersonalityShiftDefs map triggers (social interactions, skill-ups, building, crafting, mental breaks, death grief, rituals) to trait shifts. Life-stage scaling (youth 1.5×, elder 0.3×), natural drift toward 0.5, threshold crossings (0.25/0.50/0.75) record episodic memories + moodlets. Hybrid trigger: entity queue + EventBus + interaction hook. Defs in `defs/core/personality_shifts.json`. |
| `storyteller.py` | Event/crisis storytelling |
| `tech_research.py` | **Autonomous tech research.** Factions spend accumulated research points on techs guided by doctrine priority (growth→agriculture, security→medicine, harmony→social, etc.). Evaluates every 30s, respects prerequisites and cooldowns. Publishes EventBus milestones. Serialized in snapshots. |

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
| `moods.json` | `MoodDef` — AteRawFood, AteFineFood, Catharsis, FoughtOffInfection, + 7 social moodlets + 6 ritual moodlets + 6 reputation moodlets + 4 aspiration moodlets + 16 warfare moodlets + 9 cascade moodlets + 10 tradition moodlets + 16 migration moodlets (DefectorAnxiety, WarRefugee, FamilyReunion, etc.) |
| `reputation.json` | `ReputationEventDef` — 31 event types (built_structure, crafted_masterwork, combat_victory, defended_colony, defected_faction, welcomed_newcomer, etc.) + `ReputationTierDef` — 5 tiers (Luminary/Respected/Established/Marginal/Outcast) with moodlets |
| `warfare.json` | `RaidDef` — 4 raid types (pillage_raid, border_skirmish, sabotage_mission, conquest_assault) with doctrine weights, combat rounds, loot ratios, standing thresholds + `WarfareMoodDef` — 15 warfare-specific moodlets |
| `aspirations.json` | `AspirationDef` — 10 personality-weighted life goals (master_crafter, social_butterfly, colony_leader, bold_explorer, skilled_healer, master_builder, devoted_parent, luminary_path, knowledge_seeker, prosperous_provider) with progress checks, rewards, moodlets |
| `interactions.json` | `InteractionDef` — 8 social interaction types with preconditions, outcomes, drama weights, memory events |
| `diseases.json` | `DiseaseDef` — 5 named diseases with severity rates, incubation periods, transmission vectors, biome/season weights, capacity penalties, lethality |
| `rituals.json` | `RitualDef` — 6 faction ritual types with triggers (periodic/condition), effects, moodlets, gathering requirements |
| `cascades.json` | `CascadeDef` — 8 cross-system cascade rules (mass_death_trauma, combat_death_mourning, epidemic_anxiety, disaster_resource_stress, ecology_famine_warning, crisis_resilience, warfare_escalation, birth_celebration) with trigger filters, effect parameters, cooldowns, probabilities |
| `traditions.json` | `TraditionDef` — 10 cultural traditions (warrior_spirit, harvest_pride, healers_oath, builders_legacy, explorers_call, scholars_path, peacekeepers_way, survivors_grit, artisans_mark, ancestral_remembrance) with formation thresholds, reinforcement, decay, effects, conflicts, doctrine affinities |
| `migration.json` | `MigrationDef` — 5 individual migration types (discontent_defection, war_refugee, plague_flight, family_reunion, ideological_exile) with push/pull factors, thresholds, moodlets, reputation/cohesion/diplomacy consequences |
| `mentorship.json` | `MentorshipDef` — 6 apprenticeship programs (gathering, building, medical, crafting, cooking, exploration) with mentor min level, XP multiplier, max apprentices, personality weights |
| `personality_shifts.json` | `PersonalityShiftDef` — 21 experience-driven personality shifts mapping triggers (interactions, entity events, deaths, rituals) to trait changes with life-stage scaling |

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
