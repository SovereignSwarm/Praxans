# Thronglets Logging Guide

## Overview

The Thronglets game has comprehensive logging that captures all output, errors, and crash information. All logs are saved in the `logs/` directory.

## Log Files

### 1. Session Log (`session_YYYYMMDD_HHMMSS.log`)
- **Location**: `logs/session_*.log`
- **Contents**: All game events, errors, and debug messages
- **Format**: Standard Python logging format with timestamps
- **When Created**: Every game session
- **Status**: Always created, even on crash

### 2. Crash Log (`crash_YYYYMMDD_HHMMSS_N.log`)
- **Location**: `logs/crash_*.log`
- **Contents**: 
  - Full error traceback
  - Recent log events (last 20)
  - All errors in the session
  - Session and batch log file locations
- **Format**: Human-readable text
- **When Created**: Only when a crash occurs
- **Status**: Created automatically on exception

### 3. Batch Log (`batch_YYYYMMDD_HHMMSS.log`)
- **Location**: `logs/batch_*.log`
- **Contents**: Complete console output (stdout and stderr) from batch file
- **Format**: Raw console output
- **When Created**: Only when run from batch file
- **Status**: Created by batch file script

### 4. Session Report (`report_YYYYMMDD_HHMMSS.json`)
- **Location**: `logs/report_*.json`
- **Contents**: JSON summary of session (duration, crashes, events, game state)
- **Format**: JSON
- **When Created**: Always at session end
- **Status**: Created automatically

## Running with Full Logging

### Option 1: Use `Thronglets.bat` (Recommended)
- Automatically captures all console output to `logs/batch_*.log`
- Shows output on screen AND saves to file
- Run by double-clicking `Thronglets.bat`

### Option 2: Use `start_game.bat`
- Enhanced launcher with error handling
- Also captures all output

### Option 3: Run directly from Python
```bash
python thronglets_game.py
```
- Still creates session logs and crash logs
- Does NOT create batch log (only batch files do this)

## After a Crash

When the game crashes, check these files in order:

1. **`logs/crash_YYYYMMDD_HHMMSS_N.log`** (N = crash number)
   - Most detailed crash information
   - Full traceback
   - Recent events
   - All errors in session

2. **`logs/batch_YYYYMMDD_HHMMSS.log`** (if run from batch file)
   - Complete console output
   - All print statements
   - All error messages

3. **`logs/session_YYYYMMDD_HHMMSS.log`**
   - Complete session log
   - All logged events with timestamps
   - Error entries

4. **`logs/report_YYYYMMDD_HHMMSS.json`**
   - Session summary
   - Crash count
   - Duration and statistics

## Log File Naming

All log files use timestamps:
- Format: `TYPE_YYYYMMDD_HHMMSS.log` or `.json`
- Example: `session_20251103_103244.log`
- Example: `crash_20251103_103244_1.log` (first crash in session)
- Example: `batch_20251103_103244.log`

## Console Messages

The game prints log file locations:
- On startup: Shows session log location
- On crash: Shows crash log location
- On exit: Shows all relevant log files

## Important Notes

- **All logs are automatically flushed** to disk immediately to prevent data loss on crash
- **Batch logs** only exist if you run from a `.bat` file
- **Crash logs** include references to batch logs if available
- **Session logs** are always created, even if the game crashes immediately

## Finding Log Files

1. Navigate to the game directory
2. Open the `logs/` folder
3. Sort by date modified to find latest files
4. Look for the session ID (YYYYMMDD_HHMMSS) to match related files

## Sharing Logs for Debugging

When reporting issues, please provide:
1. The crash log: `logs/crash_*.log`
2. The session log: `logs/session_*.log`  
3. The batch log (if available): `logs/batch_*.log`
4. The session report: `logs/report_*.json`

All these files together provide complete context about what happened.

