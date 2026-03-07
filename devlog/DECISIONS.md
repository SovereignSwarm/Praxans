# Architectural Decision Records

> **Purpose**: Documents every non-trivial design choice made during Thonglets/Praxans development.
> See `AGENT_GUIDE.md` for formatting rules and how to add new entries.

---

## Records

### ADR-001: Observer-Only Design

- **date**: 2025-11-01
- **status**: accepted
- **context**: The game needed a clear identity. Adding player control mechanics would create tension between autonomous AI behavior and player intent, making neither fully satisfying.
- **decision**: Make the simulation strictly observer-only. No live player control over the colony. Players watch, inspect, and analyze but never command.
- **alternatives**: Hybrid control (rejected — dilutes the AI-driven narrative). Full player control (rejected — different game entirely).
- **consequences**: All UI is read-only observer tools. The LLM advisor drives colony strategy autonomously. Feature requests for "player commands" are rejected by convention.

---

### ADR-002: Single-File Monolith Origin

- **date**: 2025-11-01
- **status**: superseded (by ADR-008)
- **context**: Rapid prototyping needed the fastest iteration cycle possible. A single `praxans_game.py` allowed all 20 classes to be co-located for quick cross-referencing and editing.
- **decision**: Keep the entire game in one file during the prototype phase.
- **alternatives**: Multi-file from the start (rejected — premature abstraction before the architecture stabilized).
- **consequences**: The file grew to ~4,356 lines. Worked well for prototyping but became unwieldy as the system count grew. Eventually superseded by → ADR-008.

---

### ADR-003: LLM Integration via Ollama

- **date**: 2025-11-01
- **status**: accepted
- **context**: The game's AI advisor and goal-generation systems need an LLM. Cloud APIs are expensive and add latency; a local model keeps the game self-contained.
- **decision**: Use Ollama for local LLM inference. Make it optional — the game must boot and run without it.
- **alternatives**: OpenAI API (rejected — cost, latency, internet dependency). No LLM at all (rejected — core differentiator of the game).
- **consequences**: Ollama import is guarded with `try/except ImportError`. The game runs in "reduced mode" without it. Model preference is `qwen3.5:9b` with fallback chain.

---

### ADR-004: Optional Dependencies Pattern

- **date**: 2025-11-01
- **status**: accepted
- **context**: Both `ollama` and `noise` (Perlin noise) are useful but not critical. Requiring them makes the install heavier and blocks CI environments.
- **decision**: Guard both imports with `try/except ImportError`. Provide math-based fallbacks for noise. Provide stub behavior when Ollama is absent.
- **alternatives**: Hard-require everything (rejected — breaks CI and casual testing).
- **consequences**: Every import site for `ollama` or `noise` must be guarded. The `noise` fallback is a deterministic math approximation. LLM features are simply disabled without Ollama.

---

### ADR-005: Procedural Asset Fallbacks

- **date**: 2025-11-01
- **status**: accepted
- **context**: The assets directory was empty during early development. The game needed to render terrain, entities, and buildings without external art.
- **decision**: Generate all visuals procedurally in code (colored rects, dithered patterns, particle effects). Fall back to these when PNG assets are missing.
- **alternatives**: Require an asset pack at launch (rejected — blocks development). Use placeholder rectangles only (rejected — too ugly).
- **consequences**: The graphics system has code-drawn fallbacks for every visual element. When the SNES PNG pack was added later (→ ADR-012), the fallbacks remained as a safety net.

---

### ADR-006: Civilization Advisor Architecture

- **date**: 2025-11-01
- **status**: superseded (by ADR-010)
- **context**: The LLM advisor needs to analyze colony state and issue directives. Initially, this ran synchronously on the main thread.
- **decision**: Run advisor queries on a timed interval (30s) with a structured prompt that includes full game state.
- **alternatives**: Per-frame LLM queries (rejected — too expensive). Event-driven queries (rejected — too complex initially).
- **consequences**: The advisor became the central strategic brain. Slow/failed LLM calls would freeze the render loop — a problem that was later fixed by → ADR-010.

---

### ADR-007: Structured Snapshot Persistence

- **date**: 2026-01-06
- **status**: accepted
- **context**: Players wanted to resume sessions. The game state is complex (lineage, faction, fog-of-war, camera, festival timing) and needs full fidelity.
- **decision**: Serialize full colony state to `logs/snapshot_*.json` at session end. Resume from snapshots via `--load-latest-snapshot` or `--snapshot-file`.
- **alternatives**: Save to SQLite (rejected — overkill for JSON-shaped data). Save only key metrics (rejected — can't truly resume).
- **consequences**: Snapshots grew to 70–150KB as state fidelity expanded. Archive JSONs (`logs/archive_*.json`) were added for lighter end-of-session summaries with scoring metadata.

---

### ADR-008: Multi-Package Architecture Split

- **date**: 2026-03-06
- **status**: accepted
- **context**: The single-file monolith (→ ADR-002) reached ~8,000+ lines. Adding diplomacy, ecology, quests, and a storyteller in one file was untenable. The `entities/praxan.py` extraction had already proven the pattern.
- **decision**: Split into packages: `systems/`, `ui/`, `llm/`, `graphics/`, `map/`, `events/`, `entities/`, `defs/core/`. Each package owns a clear domain.
- **alternatives**: Keep the monolith (rejected — unmaintainable). Split by feature flags (rejected — doesn't reduce file size).
- **consequences**: `praxans_game.py` remains the entry point and still holds top-level state (~350KB). `entities/praxan.py` uses `from praxans_game import *` (wildcard import, intentional tight coupling). New systems are always added as modules under `systems/`.

---

### ADR-009: RimWorld-Style DefDatabase

- **date**: 2026-03-06
- **status**: accepted
- **context**: Buildings, technologies, items, jobs, and moods were hardcoded in Python dicts across multiple files. Adding or modifying content required code changes.
- **decision**: Implement a `DefDatabase` that recursively loads all `defs/**/*.json` at startup. Access content via `DefDatabase.get_all("BuildingDef")` etc. `game_content.py` exposes a lazy proxy dict for backward compatibility.
- **alternatives**: YAML files (rejected — requires extra dependency). Hardcoded dicts (rejected — doesn't scale). SQLite (rejected — overkill for static content).
- **consequences**: All authored game content lives in `defs/core/*.json`. Adding a new building type means editing a JSON file, not Python code. `DefDatabase` is the single source of truth (→ convention in CLAUDE.md).

---

### ADR-010: Async LLM with 4 Channels

- **date**: 2026-03-06
- **status**: accepted
- **context**: Synchronous LLM calls (→ ADR-006) froze the render loop when Ollama was slow or failed. As the game added faction intent, historian narratives, and memory digests, multiple concurrent LLM workloads needed scheduling.
- **decision**: Implement `LLMScheduler` with 4 async channels: `CHANNEL_COUNCIL` (colony decisions), `CHANNEL_FACTION` (faction intent), `CHANNEL_HISTORIAN` (narrative memory), `CHANNEL_MEMORY` (state summarization). All work runs off the main thread. `OllamaClient` wraps Ollama, strips `<think>` tags, handles model fallback.
- **alternatives**: Single async queue (rejected — can't prioritize council over historian). Web workers (rejected — Python, not JS).
- **consequences**: Slow/failed LLM calls never freeze rendering. Each channel can be independently rate-limited. The scheduler is polled each frame via `scheduler.poll()`.

---

### ADR-011: Staggered Tick Engine

- **date**: 2026-03-06
- **status**: accepted
- **context**: With 50+ entities and multiple subsystems, running all updates every frame caused performance spikes. RimWorld's tick bucketing pattern was a known solution.
- **decision**: Implement `TickManager` with three tiers: Normal (every frame), Rare (every 250 ticks, ~4s), Long (every 2000 ticks, ~33s). Register entities with appropriate frequencies.
- **alternatives**: Fixed delta accumulation (rejected — doesn't reduce per-frame work). LOD-based updates (rejected — too complex for current scale).
- **consequences**: Infrequent updates (mood recalculation, faction pressure, ecology checks) run on Rare/Long ticks, smoothing the frame budget. New systems must choose their tick tier explicitly.

---

### ADR-012: SNES-Inspired PNG Asset Pack

- **date**: 2026-03-06
- **status**: accepted
- **context**: Procedural fallback graphics (→ ADR-005) worked but looked generic. The game needed a visual identity.
- **decision**: Ship an original SNES-inspired PNG asset pack for terrain, actors, buildings, resources, hazards, NPCs, overlays, and transitions. Include a generator script at `scripts/generate_snes_assets.py`. The graphics system prefers shipped PNGs and falls back to procedural only if an asset is missing.
- **alternatives**: Use Creative Commons tilesets (rejected — licensing complexity, inconsistent style). Commission pixel art (rejected — budget).
- **consequences**: The `graphics/sprites.py` module manages sprite loading and caching. All new visual elements should have a corresponding PNG in `assets/`.

---

### ADR-013: Living Atlas Observer UI

- **date**: 2026-03-06
- **status**: accepted
- **context**: The original UI was a minimal HUD with hardcoded panels. As the game grew, it needed a proper command center, modal workbooks, scrollable drawers, and end-of-run flows.
- **decision**: Rebuild the UI into a "Living Atlas" observer shell. Command center (start/resume/scenarios/archives/settings), clickable HUD, scrollable inspect drawer, modal workbooks (research, evolution, analytics, archive), and end-of-run summary with scoring.
- **alternatives**: Web-based UI (rejected — too much overhead for a Pygame game). Immediate-mode GUI library (rejected — limited styling).
- **consequences**: UI is split across `ui/shell.py`, `ui/hud.py`, `ui/inspect.py`, `ui/analytics.py`, `ui/panels.py`, `ui/theme.py`, etc. Every HUD control is both clickable and hotkey-driven. `ui/input_router.py` manages UI state and entity picking.

---

### ADR-014: Diplomacy System Replacing Hardcoded Rivalries

- **date**: 2026-03-06
- **status**: accepted
- **context**: Faction interactions were hardcoded as simple rivalry booleans. The game needed nuanced inter-faction relations that evolve dynamically.
- **decision**: Implement a full diplomacy system with standings (-100..+100), relation tiers (Allied/Friendly/Neutral/Tense/Hostile), treaties (Trade/NAP/Alliance), diplomatic incidents, and autonomous actions.
- **alternatives**: Keep simple rivalries (rejected — too shallow). Player-driven diplomacy (rejected — violates observer-only design → ADR-001).
- **consequences**: `systems/diplomacy.py` (26KB) manages all inter-faction relations. Factions can autonomously form alliances, declare hostility, and push migration goals.

---

### ADR-015: Wildcard Import for Praxan Entity

- **date**: 2025-11-01
- **status**: accepted
- **context**: `entities/praxan.py` needs access to nearly all top-level game state (constants, globals, world map, resource lists). Explicit imports would create a 50+ line import block that mirrors the entire top-level namespace.
- **decision**: Use `from praxans_game import *` in `entities/praxan.py`. This is intentional tight coupling — the entity class is inseparable from the game state by design.
- **alternatives**: Dependency injection (rejected — massive refactor for unclear benefit at current scale). Explicit imports (rejected — impractical given the breadth of access needed).
- **consequences**: Refactoring `praxans_game.py` top-level state must consider that `praxan.py` depends on everything. This is documented in `CLAUDE.md` as a key convention.
