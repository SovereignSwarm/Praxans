# Agent Notes For Praxans

Praxans is currently a documentation and metadata baseline for a future local Pygame civilization sandbox. Do not assume a runnable game exists until runtime files are present.

## Start Here

1. Read `README.md`.
2. Read `.molthub/project.md`.
3. Check the current file tree before adding new structure.
4. Keep changes small and documented.

## Metadata Rules

- `.molthub/project.md` is the canonical MoltHub metadata file.
- Do not create `molthub.yaml` unless a future task explicitly requires legacy compatibility.
- Do not create `.mothub/`.
- Do not put private task boards, owner-only memory, credentials, local model keys, or live production notes in public metadata.

## Runtime Rules

- Do not add cloud AI dependencies or external model calls without explicit owner scope.
- Prefer local-first simulation behavior.
- If adding Pygame runtime code, update `README.md` with the exact Python version, dependency install command, launch command, generated-file locations, and checks run.
- Keep generated caches, local saves, and secrets out of git.

## Handoff Expectations

When completing work, report:

- files changed;
- commands run;
- whether the game is runnable;
- any skipped checks;
- any MoltHub Project Memory update the owner should review.
