# Thronglets Launcher Guide

## Recommended entrypoints

- `start_game.bat`
  Uses the project's `.venv` first, falls back to `py -3` or `python`, and writes a batch log in `logs/`.
- `start_game_with_logging.bat`
  Same launcher, but passes `--verbose-console --log-level DEBUG` for deeper troubleshooting.
- `start_game.ps1`
  PowerShell launcher with argument passthrough and `Tee-Object` log capture.
- `start_game.vbs`
  Thin wrapper around `start_game.bat` for double-click launching.

## Useful CLI flags

These can be passed to `start_game.ps1`, `start_game.bat`, or directly to `thronglets_game.py`.

- `--disable-llm`
  Skip all Ollama-powered behavior.
- `--model qwen3.5:35b`
  Prefer a specific Ollama model. The game now defaults to `qwen3.5:35b`.
- `--headless --max-frames 2`
  Run a quick smoke test without opening a real window.
- `--verbose-console`
  Re-enable noisy simulation traces.
- `--seed 1`
  Use a deterministic random seed for repeatable smoke runs.

## Examples

```powershell
.\start_game.ps1 --disable-llm
```

```powershell
.\start_game.ps1 --headless --disable-llm --max-frames 2 --seed 1
```

```powershell
.\start_game.ps1 --model qwen3.5:35b
```
