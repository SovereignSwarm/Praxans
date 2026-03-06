"""Genetics and cultural profile façade — re-exports from the monolith.

This module establishes the target namespace for genetics code extraction.
New code should import from here rather than praxans_game directly.

Future work will move the implementations here and leave thin shims
in praxans_game.py for backward compatibility.
"""

from __future__ import annotations

# Re-export genetics functions from the monolith
from praxans_game import (  # noqa: F401
    GENETIC_TRAIT_SPECS,
    random_genetic_profile,
    inherit_genetic_profile,
    format_genetic_trait_delta,
    summarize_population_evolution,
    build_trait_display_lines,
    compute_cultural_profile,
    record_population_evolution_sample,
)
