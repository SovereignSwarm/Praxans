# Logging System Documentation

## Log File Locations

All logs are saved in the **`logs/`** directory (relative to the game executable).

### Log Files Generated

1. **Session Log**: `logs/session_YYYYMMDD_HHMMSS.log`
   - Main log file containing all game events, errors, and debug information
   - Format: Timestamp - Level - Message
   - Includes all logging output from the game session

2. **Crash Logs**: `logs/crash_YYYYMMDD_HHMMSS_N.log`
   - Individual crash reports (one per crash)
   - Contains full traceback and error context
   - N = crash number for that session

3. **Session Reports**: `logs/report_YYYYMMDD_HHMMSS.json`
   - JSON file with session statistics
   - Includes: duration, events, errors, game state
   - Generated on normal exit

### Example File Structure

```
logs/
├── session_20250103_143022.log          # Main session log
├── crash_20250103_143022_1.log          # First crash in session
├── crash_20250103_143022_2.log          # Second crash in session
└── report_20250103_143022.json          # Session report
```

## Crash Safety Features

### Immediate Flushing
- All log entries are **immediately flushed** to disk after being written
- Uses `flush()` and `os.fsync()` to ensure data is written even on crash
- No buffering delays - logs are safe immediately

### Multiple Safety Layers

1. **Immediate Flush on Every Log Entry**
   - Every `log_event()` and `log_error()` call flushes immediately
   - No data loss from buffer delays

2. **Crash Logs**
   - Separate crash log files created for each exception
   - Contains full traceback and session context

3. **Exception Handlers**
   - `sys.excepthook`: Catches uncaught exceptions
   - `atexit`: Flushes logs on program exit
   - Try-finally blocks: Ensures cleanup in main loop

4. **Emergency Flush on Exit**
   - Registered with `atexit` to flush on any exit condition
   - Handles crashes, interrupts, and normal exits

## Viewing Logs

### During Development

Logs are printed to console in real-time, plus saved to files.

### After Crash

1. Navigate to `logs/` directory
2. Find session log: `session_YYYYMMDD_HHMMSS.log`
3. Check crash logs: `crash_YYYYMMDD_HHMMSS_N.log`
4. Review session report: `report_YYYYMMDD_HHMMSS.json`

### Log Format

```
2025-01-03 14:30:22,123 - INFO - Game session started: 20250103_143022
2025-01-03 14:30:22,124 - INFO - Log file location: D:\Documents\PerseusXR\Thonglets\logs\session_20250103_143022.log
2025-01-03 14:30:23,456 - INFO - [system] Game starting
2025-01-03 14:30:45,789 - ERROR - ERROR: Error updating thronglet 5: ...
```

## Key Log Events

The game logs:
- System events (startup, shutdown)
- Thronglet updates and errors
- Building construction
- Resource gathering
- LLM queries and responses
- Errors with full tracebacks
- Performance metrics
- Game state changes

## Accessing Logs Programmatically

You can access the logger from anywhere in the code:

```python
import logging
logger = logging.getLogger(__name__)
logger.info("Your message here")
```

The logger automatically writes to both console and file with immediate flushing.

## Troubleshooting

### No logs appearing?
- Check that `logs/` directory exists and is writable
- Check console output for log file location message at startup
- Verify file permissions

### Logs incomplete after crash?
- Check crash log files: `crash_*.log`
- Check if disk is full
- Verify OS hasn't delayed writes (unlikely with `os.fsync()`)

### Finding recent logs?
- Logs are timestamped: sort by modification date
- Session ID includes timestamp: `YYYYMMDD_HHMMSS`
- Most recent = highest timestamp in filename
