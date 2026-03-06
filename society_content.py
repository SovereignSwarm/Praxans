from __future__ import annotations


FACTION_IDEOLOGY_AXES = ("growth", "security", "industry", "exploration", "harmony")

FACTION_DYNAMICS = {
    "schism_pressure_threshold": 58.0,
    "migration_pressure_threshold": 46.0,
    "minimum_schism_size": 2,
    "schism_cooldown_seconds": 40.0,
    "migration_cooldown_seconds": 26.0,
    "succession_grace_seconds": 18.0,
}

FACTION_DOCTRINE_PROFILES = {
    "growth": {
        "label": "Growth Kinship",
        "focus": "population_growth",
        "preferred_buildings": ["house", "farm", "well"],
        "crisis_response": "stabilize_needs",
        "summary": "Expands population and keeps the settlement fed.",
    },
    "security": {
        "label": "Warden Compact",
        "focus": "survivability",
        "preferred_buildings": ["well", "house", "storage"],
        "crisis_response": "fortify_health",
        "summary": "Prioritizes resilience, recovery, and defensive cohesion.",
    },
    "industry": {
        "label": "Forge Collective",
        "focus": "production",
        "preferred_buildings": ["workshop", "storage", "farm"],
        "crisis_response": "stabilize_logistics",
        "summary": "Turns labor and storage into a stronger production base.",
    },
    "exploration": {
        "label": "Frontier Chorus",
        "focus": "territory",
        "preferred_buildings": ["workshop", "well", "house"],
        "crisis_response": "seek_resources",
        "summary": "Pushes outward for new resources and territorial momentum.",
    },
    "harmony": {
        "label": "Sanctuary Accord",
        "focus": "culture",
        "preferred_buildings": ["shrine", "house", "well"],
        "crisis_response": "restore_morale",
        "summary": "Stabilizes happiness, bonds, and cultural continuity.",
    },
}

AUTONOMOUS_DOCTRINE_GOALS = {
    "growth": "build houses and farms for the next population wave",
    "security": "secure water, shelter, and health reserves",
    "industry": "raise storage and workshop capacity",
    "exploration": "survey the frontier and claim new resource ground",
    "harmony": "restore morale and social cohesion around the shrine",
}

RUN_PHASE_DEFINITIONS = {
    "founding": {"label": "Founding", "summary": "The colony is establishing shelter, water, and food basics."},
    "expansion": {"label": "Expansion", "summary": "Population, districts, and infrastructure are scaling outward."},
    "societal_divergence": {"label": "Societal Divergence", "summary": "Lineages and factions are diverging into distinct identities."},
    "crisis_endgame": {"label": "Crisis / End-State", "summary": "The run is being defined by collapse pressure or late-stage stabilization."},
}

END_STATE_DEFINITIONS = {
    "thriving_civilization": {
        "label": "Thriving Civilization",
        "summary": "The colony sustained growth, cohesion, and prosperity.",
    },
    "brittle_survival": {
        "label": "Brittle Survival",
        "summary": "The colony endured, but only under continued fragility.",
    },
    "ideological_fracture": {
        "label": "Ideological Fracture",
        "summary": "Factional pressure overwhelmed shared identity.",
    },
    "ecological_collapse": {
        "label": "Ecological Collapse",
        "summary": "Food, resources, or hygiene pressure destabilized the colony.",
    },
    "plague_collapse": {
        "label": "Plague Collapse",
        "summary": "Disease pressure became the defining failure mode.",
    },
    "lineage_extinction": {
        "label": "Lineage Extinction",
        "summary": "The colony failed to preserve a viable population line.",
    },
}
