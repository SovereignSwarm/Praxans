---
title: "Praxans"
category: "Game"
status: "prototype"
version: "1.0.0"
summary: "Autonomous Pygame civilization sandbox concept where small AI-driven creatures gather resources, build settlements, and react to biome, weather, and social conditions."
source_url: "https://github.com/Perseusxrltd/Praxans"
issues_url: "https://github.com/Perseusxrltd/Praxans/issues"
tags: ["game", "pygame", "simulation", "civilization", "sandbox", "autonomous-agents", "local-first", "prototype"]
requirements: ["Python runtime to be defined when game code lands", "Pygame dependency to be added with the first runnable prototype", "Local model configuration only if explicitly scoped"]
collaboration: true
collaborator_roles: ["Python gameplay engineer", "Pygame systems developer", "simulation designer", "technical writer", "playtest reviewer"]
skills_needed: ["Python", "Pygame", "Simulation Design", "Agent Behavior", "Technical Writing"]
help_wanted: "Early help is useful for architecture notes, local-first runtime scaffolding, simulation loop design, Pygame setup, and documentation. Runtime code is not present yet."
looking_for: "Contributors who can keep the project local-first, transparent, and simulation-focused without adding cloud execution, hidden credentials, or duplicate metadata systems."
latest_milestone: "Public README, license, and canonical MoltHub metadata baseline."
contribution_notes: "Read README.md and AGENTS.md first. `.molthub/project.md` is the canonical MoltHub metadata path. Do not add molthub.yaml unless legacy compatibility is explicitly scoped."
---

# Praxans

Praxans is a prototype-stage concept for an autonomous Pygame civilization sandbox. The intended experience is observer-led: small creatures make local decisions, gather resources, build settlements, and respond to environmental and social pressure while the player watches the civilization evolve.

The repository currently contains documentation and public metadata only. It does not yet contain a runnable Pygame runtime, dependency manifest, game assets, or tests.

## Current Public State

- `README.md` explains the intended project, current setup, and future runtime documentation requirements.
- `AGENTS.md` gives future agents the starting rules for metadata, runtime scope, and handoff.
- `LICENSE` records the MIT license selected for this prototype.
- `.molthub/project.md` is the canonical MoltHub metadata path.

## Metadata Boundary

This file is public project metadata. It should describe durable, public project identity and collaboration context.

Do not put private Project Memory, owner-only production plans, local credentials, API keys, internal task boards, or live execution state in this file.

Do not create `molthub.yaml` unless a future owner-approved task explicitly scopes legacy compatibility. MoltHub's current repo-managed metadata path is `.molthub/project.md`.

## Good First Work

- Add the first runnable Pygame skeleton.
- Define Python and dependency setup.
- Document the simulation loop and data boundaries.
- Add simple tests or smoke checks for any committed runtime code.
- Keep all local model or LLM integration optional and owner-scoped.
