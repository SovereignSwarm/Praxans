# System Registry

> **Purpose**: Lookup table of every game system and subsystem. See `AGENT_GUIDE.md` for update rules.

---

## Entity Layer

### praxan_entity

- **name**: Praxan Entity
- **status**: active
- **package**: entities/
- **files**: `entities/praxan.py`
- **dependencies**: praxans_game (wildcard import → ADR-015)
- **dependents**: society, diplomacy, ecology, quests, storyteller, llm_advisor, spatial_index, ui_inspect
- **known_issues**: File is 146KB — tightly coupled to top-level game state via wildcard import
- **last_touched**: 2026-03-07

---

## Core Systems (`systems/`)

### def_database

- **name**: DefDatabase (Content Registry)
- **status**: active
- **package**: systems/
- **files**: `systems/def_database.py`, `defs/core/buildings.json`, `defs/core/technologies.json`, `defs/core/items.json`, `defs/core/jobs.json`, `defs/core/moods.json`
- **dependencies**: none (standalone loader)
- **dependents**: game_content, praxan_entity, ui_panels
- **known_issues**: none
- **last_touched**: 2026-03-06

### ticker

- **name**: Staggered Tick Engine
- **status**: active
- **package**: systems/
- **files**: `systems/ticker.py`
- **dependencies**: none
- **dependents**: praxan_entity, ecology, society, diplomacy
- **known_issues**: none
- **last_touched**: 2026-03-06

### policies

- **name**: Colony Policy Manager
- **status**: active
- **package**: systems/
- **files**: `systems/policies.py`
- **dependencies**: none
- **dependents**: praxan_entity, llm_advisor
- **known_issues**: none
- **last_touched**: 2026-03-06

### dev_mode

- **name**: F12 Developer Overlay
- **status**: active
- **package**: systems/
- **files**: `systems/dev_mode.py`
- **dependencies**: praxan_entity, event_bus
- **dependents**: none (dev-only)
- **known_issues**: none
- **last_touched**: 2026-03-06

### advisor

- **name**: LLM-Powered Advisor
- **status**: active
- **package**: systems/
- **files**: `systems/advisor.py`
- **dependencies**: llm_client, llm_scheduler, llm_prompts, llm_interpreters, llm_memory, def_database
- **dependents**: praxan_entity, ui_hud
- **known_issues**: File is 104KB — largest system module
- **last_touched**: 2026-03-07

### diplomacy

- **name**: Inter-Faction Diplomacy
- **status**: active
- **package**: systems/
- **files**: `systems/diplomacy.py`
- **dependencies**: society, event_bus
- **dependents**: praxan_entity, storyteller
- **known_issues**: none
- **last_touched**: 2026-03-07

### ecology

- **name**: Ecology System
- **status**: active
- **package**: systems/
- **files**: `systems/ecology.py`
- **dependencies**: spatial_index, map_generation
- **dependents**: storyteller
- **known_issues**: none
- **last_touched**: 2026-03-07

### quests

- **name**: Quest System
- **status**: active
- **package**: systems/
- **files**: `systems/quests.py`
- **dependencies**: praxan_entity, event_bus
- **dependents**: ui_hud
- **known_issues**: none
- **last_touched**: 2026-03-07

### storyteller

- **name**: Event/Crisis Storyteller
- **status**: active
- **package**: systems/
- **files**: `systems/storyteller.py`
- **dependencies**: event_bus, diplomacy, ecology, society
- **dependents**: ui_hud, llm_advisor
- **known_issues**: none
- **last_touched**: 2026-03-07

### society

- **name**: Society & Faction Mechanics
- **status**: active
- **package**: systems/
- **files**: `systems/society.py`
- **dependencies**: praxan_entity, event_bus
- **dependents**: diplomacy, storyteller, llm_advisor
- **known_issues**: none
- **last_touched**: 2026-03-07

### spatial_index

- **name**: Spatial Indexing
- **status**: active
- **package**: systems/
- **files**: `systems/spatial.py`
- **dependencies**: none
- **dependents**: ecology, praxan_entity, fog_of_war
- **known_issues**: none
- **last_touched**: 2026-03-07

### expose_data

- **name**: Data Exposure Layer
- **status**: active
- **package**: systems/
- **files**: `systems/expose_data.py`
- **dependencies**: praxan_entity, def_database
- **dependents**: llm_prompts
- **known_issues**: none
- **last_touched**: 2026-03-06

### mod_loader

- **name**: Mod Loader
- **status**: active
- **package**: systems/
- **files**: `systems/mod_loader.py`
- **dependencies**: def_database
- **dependents**: none
- **known_issues**: none
- **last_touched**: 2026-03-06

---

## LLM Subsystem (`llm/`)

### llm_client

- **name**: Ollama Client
- **status**: active
- **package**: llm/
- **files**: `llm/client.py`
- **dependencies**: ollama (optional external)
- **dependents**: llm_scheduler
- **known_issues**: none
- **last_touched**: 2026-03-06

### llm_scheduler

- **name**: LLM Async Scheduler (4 Channels)
- **status**: active
- **package**: llm/
- **files**: `llm/scheduler.py`
- **dependencies**: llm_client
- **dependents**: advisor
- **known_issues**: none
- **last_touched**: 2026-03-06

### llm_prompts

- **name**: LLM Prompt Templates
- **status**: active
- **package**: llm/
- **files**: `llm/prompts.py`
- **dependencies**: expose_data
- **dependents**: advisor, llm_contracts
- **known_issues**: none
- **last_touched**: 2026-03-06

### llm_interpreters

- **name**: LLM Response Interpreters
- **status**: active
- **package**: llm/
- **files**: `llm/interpreters.py`
- **dependencies**: none
- **dependents**: advisor
- **known_issues**: none
- **last_touched**: 2026-03-06

### llm_memory

- **name**: LLM Memory & Digest
- **status**: active
- **package**: llm/
- **files**: `llm/memory.py`
- **dependencies**: none
- **dependents**: advisor, llm_scheduler
- **known_issues**: none
- **last_touched**: 2026-03-06

### llm_contracts

- **name**: LLM Contracts & Schemas
- **status**: active
- **package**: llm/
- **files**: `llm/contracts.py`
- **dependencies**: none
- **dependents**: advisor, llm_prompts
- **known_issues**: none
- **last_touched**: 2026-03-06

### llm_state_views

- **name**: LLM State Views
- **status**: active
- **package**: llm/
- **files**: `llm/state_views.py`
- **dependencies**: praxan_entity, def_database
- **dependents**: llm_prompts
- **known_issues**: none
- **last_touched**: 2026-03-06

---

## Events (`events/`)

### event_bus

- **name**: Event Bus
- **status**: active
- **package**: events/
- **files**: `events/bus.py`
- **dependencies**: none
- **dependents**: cascades, incidents, storyteller, quests, diplomacy, society
- **known_issues**: none
- **last_touched**: 2026-03-06

### cascades

- **name**: Event Cascades
- **status**: active
- **package**: events/
- **files**: `events/cascades.py`
- **dependencies**: event_bus
- **dependents**: storyteller
- **known_issues**: none
- **last_touched**: 2026-03-06

### incidents

- **name**: Incidents
- **status**: active
- **package**: events/
- **files**: `events/incidents.py`
- **dependencies**: event_bus
- **dependents**: storyteller, dev_mode
- **known_issues**: none
- **last_touched**: 2026-03-06

---

## Graphics (`graphics/`)

### scene_renderer

- **name**: Scene Renderer
- **status**: active
- **package**: graphics/
- **files**: `graphics/scene_renderer.py`
- **dependencies**: terrain_renderer, entity_renderer, effects_renderer
- **dependents**: praxans_game (main loop)
- **known_issues**: none
- **last_touched**: 2026-03-07

### terrain_renderer

- **name**: Terrain Renderer
- **status**: active
- **package**: graphics/
- **files**: `graphics/terrain_renderer.py`
- **dependencies**: graphics_content, sprites
- **dependents**: scene_renderer
- **known_issues**: none
- **last_touched**: 2026-03-07

### entity_renderer

- **name**: Entity Renderer
- **status**: active
- **package**: graphics/
- **files**: `graphics/entity_renderer.py`
- **dependencies**: sprites, palette
- **dependents**: scene_renderer
- **known_issues**: none
- **last_touched**: 2026-03-07

### effects_renderer

- **name**: Effects Renderer
- **status**: active
- **package**: graphics/
- **files**: `graphics/effects_renderer.py`
- **dependencies**: palette
- **dependents**: scene_renderer
- **known_issues**: none
- **last_touched**: 2026-03-07

### sprites

- **name**: Sprite Manager
- **status**: active
- **package**: graphics/
- **files**: `graphics/sprites.py`
- **dependencies**: assets/ (PNG files)
- **dependents**: terrain_renderer, entity_renderer
- **known_issues**: none
- **last_touched**: 2026-03-06

### palette

- **name**: Color Palette
- **status**: active
- **package**: graphics/
- **files**: `graphics/palette.py`
- **dependencies**: none
- **dependents**: entity_renderer, effects_renderer, terrain_renderer
- **known_issues**: none
- **last_touched**: 2026-03-06

### graphics_content

- **name**: Graphics Content Definitions
- **status**: active
- **package**: graphics/
- **files**: `graphics/content.py`
- **dependencies**: def_database
- **dependents**: terrain_renderer
- **known_issues**: none
- **last_touched**: 2026-03-06

### frame_models

- **name**: Render Frame Models
- **status**: active
- **package**: graphics/
- **files**: `graphics/frame_models.py`
- **dependencies**: none
- **dependents**: scene_renderer
- **known_issues**: none
- **last_touched**: 2026-03-06

---

## Map (`map/`)

### map_generation

- **name**: World Map Generation
- **status**: active
- **package**: map/
- **files**: `map/generation.py`
- **dependencies**: noise (optional external), map_models
- **dependents**: praxans_game, ecology, terrain_renderer
- **known_issues**: none
- **last_touched**: 2026-03-07

### map_models

- **name**: Map & Biome Models
- **status**: active
- **package**: map/
- **files**: `map/models.py`
- **dependencies**: none
- **dependents**: map_generation, praxan_entity
- **known_issues**: none
- **last_touched**: 2026-03-06

### planet

- **name**: Planet Selection
- **status**: active
- **package**: map/
- **files**: `map/planet.py`
- **dependencies**: none
- **dependents**: map_generation, ui_planet_select
- **known_issues**: none
- **last_touched**: 2026-03-06

### poi

- **name**: Points of Interest
- **status**: active
- **package**: map/
- **files**: `map/poi.py`
- **dependencies**: map_models
- **dependents**: map_generation, praxan_entity
- **known_issues**: none
- **last_touched**: 2026-03-06

---

## UI (`ui/`)

### ui_shell

- **name**: Command Center Shell
- **status**: active
- **package**: ui/
- **files**: `ui/shell.py`
- **dependencies**: ui_theme, ui_input_router
- **dependents**: praxans_game
- **known_issues**: none
- **last_touched**: 2026-03-07

### ui_hud

- **name**: Live Run HUD
- **status**: active
- **package**: ui/
- **files**: `ui/hud.py`
- **dependencies**: ui_theme, ui_layout
- **dependents**: praxans_game
- **known_issues**: none
- **last_touched**: 2026-03-07

### ui_inspect

- **name**: Scrollable Entity Inspect Drawer
- **status**: active
- **package**: ui/
- **files**: `ui/inspect.py`
- **dependencies**: praxan_entity, ui_theme
- **dependents**: praxans_game
- **known_issues**: none
- **last_touched**: 2026-03-07

### ui_analytics

- **name**: Modal Analytics & End-of-Run Summary
- **status**: active
- **package**: ui/
- **files**: `ui/analytics.py`
- **dependencies**: observer_analytics, ui_theme
- **dependents**: praxans_game
- **known_issues**: none
- **last_touched**: 2026-03-06

### ui_panels

- **name**: UI Panels (Research, Evolution, etc.)
- **status**: active
- **package**: ui/
- **files**: `ui/panels.py`
- **dependencies**: ui_theme, def_database
- **dependents**: praxans_game
- **known_issues**: none
- **last_touched**: 2026-03-07

### ui_input_router

- **name**: UI State & Input Router
- **status**: active
- **package**: ui/
- **files**: `ui/input_router.py`
- **dependencies**: none
- **dependents**: ui_shell, ui_hud
- **known_issues**: none
- **last_touched**: 2026-03-06

### ui_camera_director

- **name**: Camera Bookmarks & Auto-Follow
- **status**: active
- **package**: ui/
- **files**: `ui/camera_director.py`
- **dependencies**: none
- **dependents**: praxans_game
- **known_issues**: none
- **last_touched**: 2026-03-06

### ui_theme

- **name**: UI Theme & Panel Rendering
- **status**: active
- **package**: ui/
- **files**: `ui/theme.py`
- **dependencies**: none
- **dependents**: ui_shell, ui_hud, ui_inspect, ui_analytics, ui_panels
- **known_issues**: none
- **last_touched**: 2026-03-06

### ui_history_graph

- **name**: Time-Series Population/Wealth/Mood Graph
- **status**: active
- **package**: ui/
- **files**: `ui/history_graph.py`
- **dependencies**: none
- **dependents**: ui_analytics
- **known_issues**: none
- **last_touched**: 2026-03-06

### ui_search_overlay

- **name**: Search Overlay
- **status**: active
- **package**: ui/
- **files**: `ui/search_overlay.py`
- **dependencies**: ui_theme
- **dependents**: praxans_game
- **known_issues**: none
- **last_touched**: 2026-03-06

### ui_planet_select

- **name**: Planet Selection Screen
- **status**: active
- **package**: ui/
- **files**: `ui/planet_select.py`
- **dependencies**: planet, ui_theme
- **dependents**: ui_shell
- **known_issues**: none
- **last_touched**: 2026-03-06

### ui_layout

- **name**: Layout Computation
- **status**: active
- **package**: ui/
- **files**: `ui/layout.py`
- **dependencies**: none
- **dependents**: ui_hud
- **known_issues**: none
- **last_touched**: 2026-03-06

### ui_models

- **name**: UI Data Models
- **status**: active
- **package**: ui/
- **files**: `ui/models.py`
- **dependencies**: none
- **dependents**: ui_panels, ui_inspect
- **known_issues**: none
- **last_touched**: 2026-03-06

---

## Root-Level Modules

### praxans_game

- **name**: Main Game Loop & Top-Level State
- **status**: active
- **package**: root
- **files**: `praxans_game.py`
- **dependencies**: all systems, all UI, all graphics, map, events, entities
- **dependents**: praxan_entity (wildcard import)
- **known_issues**: File is 350KB — monolithic entry point holding all top-level state
- **last_touched**: 2026-03-07

### runtime_config

- **name**: CLI Args & User Settings
- **status**: active
- **package**: root
- **files**: `runtime_config.py`
- **dependencies**: none
- **dependents**: praxans_game
- **known_issues**: none
- **last_touched**: 2026-03-06

### game_content

- **name**: Building Definitions Proxy
- **status**: active
- **package**: root
- **files**: `game_content.py`
- **dependencies**: def_database
- **dependents**: praxan_entity, advisor
- **known_issues**: none
- **last_touched**: 2026-03-06

### game_scenarios

- **name**: Scenario Presets
- **status**: active
- **package**: root
- **files**: `game_scenarios.py`
- **dependencies**: none
- **dependents**: praxans_game, ui_shell
- **known_issues**: none
- **last_touched**: 2026-03-06

### observer_analytics

- **name**: Observer Analytics Engine
- **status**: active
- **package**: root
- **files**: `observer_analytics.py`
- **dependencies**: praxan_entity
- **dependents**: ui_analytics
- **known_issues**: none
- **last_touched**: 2026-03-06

### society_dynamics

- **name**: Society Dynamics (Legacy)
- **status**: active
- **package**: root
- **files**: `society_dynamics.py`
- **dependencies**: praxan_entity
- **dependents**: society
- **known_issues**: May overlap with `systems/society.py`
- **last_touched**: 2026-03-06

### run_snapshot

- **name**: Snapshot Serializer
- **status**: active
- **package**: root
- **files**: `run_snapshot.py`
- **dependencies**: praxan_entity, all systems
- **dependents**: praxans_game
- **known_issues**: none
- **last_touched**: 2026-03-06

### run_archive

- **name**: Archive Summary Generator
- **status**: active
- **package**: root
- **files**: `run_archive.py`
- **dependencies**: observer_analytics
- **dependents**: praxans_game
- **known_issues**: none
- **last_touched**: 2026-03-06

### genetics

- **name**: Genetics System
- **status**: active
- **package**: root
- **files**: `genetics.py`
- **dependencies**: none
- **dependents**: praxan_entity
- **known_issues**: Small file (741B) — may be a stub
- **last_touched**: 2026-03-06

---

## Test Suite

### test_suite

- **name**: Automated Tests
- **status**: active
- **package**: tests/
- **files**: 20 test files covering: advisor contract, diplomacy, game content, game scenarios, graphics renderer, grief system, headless smoke, LLM contracts, LLM interpreters, LLM memory, LLM scheduler, map generation, observer analytics, quest system, run archive, run snapshot, runtime config, society dynamics, UI input router, UI render smoke
- **dependencies**: all systems under test
- **dependents**: none
- **known_issues**: none
- **last_touched**: 2026-03-07
