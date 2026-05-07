# Praxans

Praxans is an autonomous Pygame civilization sandbox concept where small AI-driven creatures gather resources, build settlements, and react to changing biome, weather, and social conditions while the player watches.

The project is currently a documentation and metadata baseline. Runtime code, assets, dependency files, and executable game entrypoints have not been added to this repository yet.

## Project Status

- Status: prototype shell
- Runtime target: Python with Pygame
- Current repository contents: public project metadata and documentation
- Source of truth for MoltHub metadata: `.molthub/project.md`

## Intended Game Shape

Praxans is intended to be an observer-led simulation rather than a direct-control game. The player watches a small civilization emerge from local creature decisions, environmental pressure, resource availability, and social needs.

Planned systems include:

- autonomous creature behavior;
- resource gathering and local production;
- settlement construction;
- biome and weather pressure;
- social and group reactions;
- local LLM-assisted civilization behavior where explicitly configured by the owner.

## Current Setup

Clone the repository:

```bash
git clone https://github.com/Perseusxrltd/Praxans.git
cd Praxans
```

There are no runtime dependencies to install yet because no game runtime has been committed. When implementation begins, add the Python dependency file, setup instructions, and launch command in this README in the same change as the first runnable code.

## Usage

There is no runnable game entrypoint in the repository yet.

Before adding one, document:

- supported Python version;
- package manager and dependency file;
- launch command;
- required local model or LLM configuration, if any;
- offline fallback behavior when no local model is configured;
- save-file and generated-data locations.

Do not require cloud AI credentials for the base local simulation unless a future owner-approved milestone explicitly scopes that behavior.

## Repository Structure

Current structure:

```text
.
├── .gitattributes
├── .molthub/
│   ├── project.md
│   └── README.md
├── AGENTS.md
├── LICENSE
└── README.md
```

Expected future structure should stay simple and explicit. Suggested paths:

```text
src/                 # Game source once runtime code exists
assets/              # Art, audio, and generated-safe asset inputs
docs/                # Design, architecture, and playtest notes
tests/               # Automated checks once code exists
```

## MoltHub Metadata

MoltHub metadata lives in `.molthub/project.md`.

Do not add `molthub.yaml` unless a separate legacy-compatibility task explicitly requires it. `.molthub/project.md` is the canonical public metadata path for this project.

Keep private production state, internal task boards, live project memory, and owner-only planning out of `.molthub/project.md`; those belong in MoltHub Workbench.

## Contributing

This repository is not ready for broad contribution yet. Useful early work is documentation, architecture notes, and small runtime scaffolding that keeps the simulation local-first and easy to inspect.

Before changing runtime scope, future agents should:

1. Read this README.
2. Read `AGENTS.md`.
3. Read `.molthub/project.md`.
4. Avoid duplicate metadata systems.
5. Keep secrets and local model credentials out of the repository.

## License

MIT. See `LICENSE`.
