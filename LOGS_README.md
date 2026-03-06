# Game Session Logs

When you run the game, comprehensive logging is automatically enabled to help diagnose crashes and track game behavior.

## Log Files Location

All logs are saved in the `logs/` directory which is automatically created on first run.

## Log File Types

1. **Session Logs** (`session_YYYYMMDD_HHMMSS.log`)
   - Full game session log with all events
   - Timestamped entries for every action
   - Use for detailed debugging

2. **Crash Logs** (`crash_YYYYMMDD_HHMMSS_N.log`)
   - Created when an error occurs during gameplay
   - Contains full stack traces
   - Multiple crashes = multiple files

3. **Session Reports** (`report_YYYYMMDD_HHMMSS.json`)
   - Generated after each game session
   - Summary statistics
   - Crash count and duration
   - Game state snapshot

## What Gets Logged

- All errors and crashes with full stack traces
- Game events (building construction, reproduction, deaths)
- State transitions for debugging action loops
- System messages
- Session statistics

## Reading the Logs

If your game crashes after a few minutes:
1. Check `logs/` directory for crash logs
2. Open the most recent crash log file
3. Look for error messages and stack traces
4. Share the log file for debugging

The session report JSON files are human-readable and show a summary of what happened during the game session.

## Example Session Report

```json
{
  "session_id": "20241201_143022",
  "start_time": "2024-12-01T14:30:22",
  "end_time": "2024-12-01T14:35:45",
  "duration_seconds": 323.5,
  "duration_formatted": "0:05:23",
  "crash_count": 1,
  "total_events": 152,
  "game_state": {
    "population": 8,
    "buildings": 6,
    "duration": 323.5
  },
  "errors": [...]
}
```

