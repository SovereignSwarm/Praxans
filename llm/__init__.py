"""LLM subsystem for Praxans — multi-channel civilization engine.

Provides scheduler, contracts, memory, state views, prompt templates,
and deterministic interpreters for five live LLM channels:
  council · faction_leaders · diplomat · historian · memory_summarizer
"""

from __future__ import annotations

# Channel constants
CHANNEL_COUNCIL = "council"
CHANNEL_FACTION = "faction_leaders"
CHANNEL_DIPLOMACY = "diplomat"
CHANNEL_HISTORIAN = "historian"
CHANNEL_MEMORY = "memory_summarizer"

ALL_CHANNELS = (CHANNEL_COUNCIL, CHANNEL_FACTION, CHANNEL_DIPLOMACY, CHANNEL_HISTORIAN, CHANNEL_MEMORY)

