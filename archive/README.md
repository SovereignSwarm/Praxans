# Archive

This folder holds files that are no longer part of the active game/runtime flow but were kept for reference.

## Current Structure

- `legacy_docs/`
  Older diagnostics, fix reports, logging notes, and one-off analysis files that were cluttering the repo root.
- `legacy_launchers/`
  Redundant launcher wrappers that are no longer the recommended entrypoint.
- `legacy_tools/`
  Outdated helper scripts that bypass the current launcher/runtime setup.

## Active Launch Files

- Use `start_game.bat` for normal Windows launching.
- Use `start_game_with_logging.bat` only when debugging.
- Use `start_game.vbs` only if you want a double-click wrapper around `start_game.bat`.
