# Changelog

> **Purpose**: Version-level changes grouped by development phase.
> See `AGENT_GUIDE.md` for update rules.

---

## [Current — Polish & Live Systems] — 2026-03-07 to present

### Added
- Dynamic point-lighting for night cycle (→ effects_renderer)
- LLM settings overlay for configuring Ollama connection (→ ui_shell, runtime_config)
- Fog of war refactored to RimWorld-style Line of Sight (→ spatial_index)
- Momentum-based camera panning with zoom-to-cursor (→ praxans_game)
- Production logging system (`devlog/`) with 5 structured files (→ ADR: future)

### Changed
- Camera zoom system rewritten for fluid, continuous control
- Removed dead atmospheric overlay code from graphics pipeline

### Fixed
- Consolidated bug fixes from full game review and refactor session
- Fixed broken references after DefDatabase migration and tick method changes

---

## [Architecture Refactor] — 2026-03-06

### Added
- `systems/` package: `def_database.py`, `ticker.py`, `policies.py`, `dev_mode.py`, `advisor.py`, `diplomacy.py`, `ecology.py`, `quests.py`, `storyteller.py`, `society.py`, `spatial.py`, `expose_data.py`, `mod_loader.py` (→ ADR-008)
- `llm/` package: `client.py`, `scheduler.py`, `prompts.py`, `interpreters.py`, `memory.py`, `contracts.py`, `state_views.py` (→ ADR-010)
- `graphics/` package: `scene_renderer.py`, `terrain_renderer.py`, `entity_renderer.py`, `effects_renderer.py`, `sprites.py`, `palette.py`, `content.py`, `frame_models.py` (→ ADR-012)
- `map/` package: `generation.py`, `models.py`, `planet.py`, `poi.py`
- `events/` package: `bus.py`, `cascades.py`, `incidents.py`
- `ui/` package: `shell.py`, `hud.py`, `inspect.py`, `analytics.py`, `panels.py`, `input_router.py`, `camera_director.py`, `layout.py`, `history_graph.py`, `theme.py`, `search_overlay.py`, `planet_select.py`, `models.py` (→ ADR-013)
- `defs/core/` JSON content: `buildings.json`, `technologies.json`, `items.json`, `jobs.json`, `moods.json` (→ ADR-009)
- DefDatabase — RimWorld-style content registry (→ ADR-009)
- Staggered tick engine — Normal/Rare/Long tiers (→ ADR-011)
- Colony policy manager (food/medical/hostility) (→ policies)
- F12 developer overlay (→ dev_mode)
- Inter-faction diplomacy with standings, treaties, and autonomous actions (→ ADR-014)
- Ecology system with biome-aware environmental dynamics (→ ecology)
- Quest system with structured objectives (→ quests)
- Event/crisis storyteller engine (→ storyteller)
- Event bus + cascades + incidents framework (→ event_bus, cascades, incidents)
- Spatial indexing for efficient proximity queries (→ spatial_index)
- Living Atlas observer UI shell with command center (→ ADR-013)
- Search overlay for entity discovery (→ ui_search_overlay)
- Planet selection screen (→ ui_planet_select)
- Time-series history graph (→ ui_history_graph)
- SNES-inspired PNG asset pack (→ ADR-012)
- Async LLM scheduler with 4 channels (→ ADR-010)
- LLM memory and digest system (→ llm_memory)
- Mod loader for external content packs (→ mod_loader)
- Observer analytics with lineage dominance and death summaries (→ observer_analytics)
- Run archive summaries with scoring metadata (→ run_archive)
- 20 automated test files (→ test_suite)

### Changed
- Extracted `entities/praxan.py` from monolith (→ ADR-015)
- Main game loop refactored to delegate to system packages
- Camera system moved to use continuous key panning with delta_time
- Ollama default model changed to `qwen3.5:9b`
- LLM advisor and goal-generation moved off main thread (→ ADR-010)
- Simulation set to observer-only — removed live player steering
- Graphics pipeline now prefers PNG asset pack, falls back to procedural
- Snapshot fidelity expanded: lineage, fog-of-war, territory claims, faction state, camera, festival timing, scenario ID

### Fixed
- Restored broken main loop and render pipeline
- Added real runtime CLI for headless smoke tests
- Reduced default console spam, bounded log growth with rotating files
- Made Ollama and noise optional at import time (→ ADR-004)
- Modernized Windows launchers to use repo venv

### Removed
- Live player control mechanics (→ ADR-001)
- Legacy launcher wrappers (moved to `archive/legacy_launchers`)
- Legacy diagnostic docs (moved to `archive/legacy_docs/`)

---

## [Feature Expansion] — 2026-01-06 to 2026-02-28

### Added
- Heritable praxan traits, lineage tracking, and mutation drift
- Evolution observer panel
- Faction society mechanics with doctrine drift, leadership succession, schism pressure, and migration
- Observer scenario presets: `standard`, `fertile_floodplain`, `harsh_winter_basin`, `plague_start`, `scarce_stone`, `high_mutation`
- Observer analytics timeline, mortality summaries, and faction churn
- Run archive summaries (`logs/archive_*.json`)
- Structured end-of-session state snapshots (`logs/snapshot_*.json`) with resume support (→ ADR-007)

### Changed
- Expanded snapshot fidelity multiple times (lineage, camera, festivals, fog-of-war, territories, factions, encounters, hazards, NPCs)
- Retuned live simulation: richer mood systems, district identity, celebration surges, upgraded HUD feedback

### Fixed
- Biome resource bonuses now applied to spawning (food, wood, stone)
- `gather_rate` modifier now functional
- `health_regen` confirmed working

---

## [Stabilization] — 2025-12-01 to 2026-01-05

### Added
- Deep analysis report for rendering pipeline diagnosis
- Diagnostic logging at critical init points (camera, chunks, assets)
- Implementation verification report

### Fixed
- Camera initialization/position validation
- Chunk surface generation fallbacks
- Silent exception handling in rendering pipeline
- Asset manager error handling

---

## [Prototype] — 2025-11-01 to 2025-11-30

### Added
- Initial `praxans_game.py` monolith: 4,356 lines, 20 classes (→ ADR-002)
- Praxan AI entity with needs (hunger, energy, thirst), health, skills, social bonds, disease, reproduction
- 6 building types: house, farm, storage, workshop, shrine, well
- Resource system: food, wood, stone with respawn
- Civilization advisor with LLM integration via Ollama (→ ADR-003, ADR-006)
- Chunk-based world generation with 8 biomes
- Fog of war with tile-level visibility
- Particle system with 8 effect types
- Tooltip system, selection manager, info panel
- Day/night cycle, 4 seasons, weather events
- Encounters (ruins, mineral veins, oases, sacred groves)
- Terrain hazards (quicksand, avalanches, floods, predators)
- NPC system (traders, rival tribes, wildlife)
- Camera system with pan/zoom
- 24-color pixel art palette with procedural dithering
- System connections analysis document
- Windows launchers (batch, PowerShell, VBS)
- Observer-only design principle established (→ ADR-001)
