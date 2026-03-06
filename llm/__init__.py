"""LLM subsystem for Thronglets — multi-channel civilization engine.

Provides scheduler, contracts, memory, state views, prompt templates,
and deterministic interpreters for four live LLM channels:
  council · faction_leaders · historian · memory_summarizer
"""

from __future__ import annotations

# Channel constants
CHANNEL_COUNCIL = "council"
CHANNEL_FACTION = "faction_leaders"
CHANNEL_HISTORIAN = "historian"
CHANNEL_MEMORY = "memory_summarizer"

ALL_CHANNELS = (CHANNEL_COUNCIL, CHANNEL_FACTION, CHANNEL_HISTORIAN, CHANNEL_MEMORY)
