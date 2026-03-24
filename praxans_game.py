from __future__ import annotations
"""
Praxans - A Black Mirror-style Lemmings simulation game
Cute pixelated creatures make AI-powered decisions using a local LLM
"""

import atexit
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import random
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field, replace
from datetime import datetime

from llm.contracts import council_payload_defaults as advisory_payload_defaults, parse_council_payload as parse_advisory_payload
from llm.client import OllamaClient, sanitize_llm_response as _llm_sanitize
from llm.scheduler import LLMScheduler
from llm.memory import LLMMemory
from llm.state_views import build_council_view, build_faction_view, build_historian_view, build_memory_view
from llm.prompts import build_council_prompt, build_faction_prompt, build_historian_prompt, build_memory_prompt
from llm.interpreters import apply_council_payload, apply_faction_intent, apply_historian, apply_memory_summary
from llm import CHANNEL_COUNCIL, CHANNEL_FACTION, CHANNEL_HISTORIAN, CHANNEL_MEMORY, CHANNEL_MUSE
from game_scenarios import DEFAULT_SCENARIO_ID, get_scenario_profile
from graphics import GraphicsConfig, SceneRenderer, build_render_frame
from graphics.content import ROOM_WALL_BUILDING_TYPES, SNAP_ZOOM_LEVELS, building_occupied_tiles, building_origin_to_anchor
from map import WORLD_GENERATION_VERSION, build_frontier_world, build_world_profile
from observer_analytics import build_observer_report
from run_archive import build_archive_comparison, build_run_archive, build_run_summary, find_recent_archives, write_run_archive
from society_content import AUTONOMOUS_DOCTRINE_GOALS, FACTION_DOCTRINE_PROFILES, FACTION_DYNAMICS, FACTION_IDEOLOGY_AXES, RUN_PHASE_DEFINITIONS
from society_dynamics import choose_migration_target, choose_schism_members, compute_faction_metrics
from ui.analytics import draw_end_summary, draw_modal_layer
from ui.camera_director import CameraDirector
from ui.hud import draw_run_hud, next_overlay
from ui.input_router import UIState, UIRectRegistry, handle_escape, pick_world_entity
from ui.inspect import build_inspect_view_model, draw_inspect_drawer
from ui.layout import compute_run_layout
from ui.models import RunHudModel, build_field_notes
from ui.shell import run_command_center
from ui.theme import build_ui_theme, draw_panel
from game_content import (
    BUILDING_DEFINITIONS,
    clone_abilities,
    clone_legacy_bonuses,
    clone_tech_tree,
    format_building_prompt_lines,
    format_goal_type_lines,
    get_building_cost,
    JOB_DEFS,
    QUALITY_LEVELS,
    QUALITY_MULTIPLIERS
)
from run_snapshot import (
    build_run_snapshot,
    load_run_snapshot,
    resolve_snapshot_path,
    write_run_snapshot,
)
from runtime_config import build_console_printer, configure_environment, parse_runtime_config

RUNTIME_CONFIG = parse_runtime_config(sys.argv[1:])
configure_environment(RUNTIME_CONFIG)

import pygame

try:
    import ollama
except ImportError:
    ollama = None

try:
    import noise
except ImportError:
    noise = None

# Initialize Pygame
pygame.init()

print = build_console_printer(RUNTIME_CONFIG)
LLM_ENABLED = not RUNTIME_CONFIG.disable_llm and ollama is not None

# Constants
WINDOW_WIDTH = RUNTIME_CONFIG.width
WINDOW_HEIGHT = RUNTIME_CONFIG.height
FPS = RUNTIME_CONFIG.fps
PRAXAN_SPEED = 1.5  # Doubled for larger scale
RESOURCE_COLLISION_DIST = 24  # Adjusted for larger sprites

# Time speed control
TIME_SPEED_OPTIONS = [1.0, 2.0, 5.0]  # 1x, 2x, 5x

# Visual scale constants
PRAXAN_RADIUS = 16  # Visually larger relative to grid
BUILDING_SIZE = 32  # Half scale of new 64 tile size, but larger overall
RESOURCE_RADIUS_FOOD = 8  # Larger, more visible resources
RESOURCE_RADIUS_WOOD = 10  # Larger, more visible resources
# Map system constants
CHUNK_SIZE = 1024  # Size of a terrain chunk in pixels
INITIAL_CHUNKS_X = 2  # 2x2 initial grid for 2048x2048 world
INITIAL_CHUNKS_Y = 2

# RimWorld-inspired Time System
TICKS_PER_HOUR = 2500
TICKS_PER_DAY = 60000
game_ticks = 0
CHUNK_SIZE = 512  # Pixels per chunk (512x512) -> This will now be 8x8 tiles instead of 16x16
TILE_SIZE = 64  # Size of each tile (doubled for higher detail)
INITIAL_CHUNKS_X = 64  # Massive planetary scale world width in chunks
INITIAL_CHUNKS_Y = 64  # Massive planetary scale world height in chunks
NOISE_SCALE = 0.1  # For Perlin noise generation

# Territory system constants
TERRITORY_CLAIM_RATE = 2.0  # Claim strength increase per second
TERRITORY_DECAY_RATE = 0.1  # Decay rate for unclaimed tiles
TERRITORY_CLAIM_RADIUS = 80  # Doubled for new scale
BUILDING_CLAIM_RADIUS = 120  # Doubled for new scale

# Civilization Advisor Configuration — multi-channel cadences
COUNCIL_REVIEW_INTERVAL = 12.0
FACTION_REVIEW_INTERVAL = 18.0
HISTORIAN_REVIEW_INTERVAL = 20.0
MEMORY_SUMMARY_INTERVAL = 90.0
DIPLOMACY_REVIEW_INTERVAL = 25.0
# Legacy alias kept for any remaining references
CIVILIZATION_ADVISOR_INTERVAL = COUNCIL_REVIEW_INTERVAL

# Day/Night Cycle Configuration
DAY_LENGTH = 60.0  # seconds (full cycle = day + night)
NIGHT_START = DAY_LENGTH / 2  # night starts halfway through day

# Reproduction Configuration
REPRODUCTION_COOLDOWN = 45.0  # 45 seconds between reproductions (faster for growth)
REPRODUCTION_PROXIMITY = 60  # Doubled for larger sprites
REPRODUCTION_NEEDS_THRESHOLD = 60  # both hunger and energy must be above this (easier to reproduce)
MAX_POPULATION = 25  # soft cap to maintain performance
INITIAL_POPULATION = 2  # start with 2 praxans

# Resource Configuration
RESOURCE_RESPAWN_TIME = 30.0  # Food respawns every 30 seconds
RESOURCE_GATHER_TIME_FOOD = 3.0  # Time to gather food (seconds)
RESOURCE_GATHER_TIME_WOOD = 5.0  # Time to chop down tree (seconds)
RESOURCE_GATHER_TIME_STONE = 8.0  # Time to mine stone (seconds)
WOOD_MAX_ON_MAP = 1000  # Maximum wood resources at once (massive map)
# FOOD_MAX_ON_MAP removed - food uses respawn timer system instead

# Health & Lifespan
PRAXAN_MAX_AGE = 420.0  # 7 minutes (increased for better survival)
HEALTH_DECAY_BASE = 0.01
DISEASE_CHANCE_BASE = 0.001

# Life Stages (age thresholds in seconds)
LIFE_STAGE_INFANT = 30.0    # 0-30s: dependent on parents, can't work
LIFE_STAGE_YOUTH = 90.0     # 30-90s: can do basic work, can't reproduce, fast learner
LIFE_STAGE_ADULT = 330.0    # 90-330s: full capabilities
# 330-420s = Elder: reduced speed, wisdom bonus to faction

# Relationship types (stored in praxan.relationships dict)
REL_PARTNER = 'partner'
REL_PARENT = 'parent'
REL_CHILD = 'child'
REL_FRIEND = 'friend'
REL_RIVAL = 'rival'

# Partnership threshold (bond strength needed to form partnership on reproduction)
PARTNERSHIP_BOND_THRESHOLD = 50.0

# Name generation syllables (alien-sounding but pronounceable)
NAME_SYLLABLES = [
    "ka", "ra", "mi", "no", "zu", "ta", "shi", "ko", "na", "ri",
    "mu", "wa", "to", "se", "yu", "ha", "ke", "ro", "sa", "chi",
    "ni", "fu", "ma", "ki", "te", "yo", "so", "ne", "hi", "ku",
]

def generate_praxan_name(seed_id=None):
    """Generate a pronounceable name from syllables. Deterministic if seed_id given."""
    rng = random.Random(seed_id) if seed_id is not None else random
    length = rng.choice([2, 2, 2, 3])  # Mostly 2-syllable names
    return ''.join(rng.choice(NAME_SYLLABLES) for _ in range(length)).capitalize()

# Skills
SKILL_XP_GATHERING = 10  # XP per resource
SKILL_XP_BUILDING = 25   # XP per building
SKILL_LEVEL_THRESHOLD = 100  # XP to level up

# Skill system
SKILL_BONUS_PER_LEVEL = 0.10  # 10% improvement per level
MAX_SKILL_LEVEL = 6  # Cap at level 6 for 50% bonus

# Population management
OVERPOPULATION_THRESHOLD = 0.9  # 90% of max
OVERPOPULATION_MAX_PENALTY = 1.0  # 100% penalty at cap

# Role bonuses
GATHERER_SPEED_BONUS = 1.5
BUILDER_COST_REDUCTION = 0.8
EXPLORER_LUCK_CHANCE = 0.10

# Challenge scaling
DIFFICULTY_BASE = 1.0
DIFFICULTY_SCALING_FACTOR = 20.0  # Points needed per difficulty level

# Social
BOND_INCREASE_RATE = 0.5  # Per second working together
BOND_DECAY_RATE = 0.1     # Per second apart

# Resource Sharing
RESOURCE_SHARING_RADIUS = 100  # Doubled for new scale - praxans within this distance can share resources for building

# Behavior Tree Constants
BT_NODE_SELECTOR = 'selector'
BT_NODE_SEQUENCE = 'sequence'
BT_NODE_CONDITION = 'condition'
BT_NODE_ACTION = 'action'

# Q-Learning Constants
Q_LEARNING_ALPHA = 0.1  # Learning rate
Q_LEARNING_GAMMA = 0.9  # Discount factor
Q_LEARNING_EPSILON = 0.3  # Exploration rate (30% chance to use Q-learning)
Q_TABLE_MAX_SIZE = 1000  # Maximum Q-table entries

# Advanced Resources
STONE_MAX_ON_MAP = 500
RESOURCE_RADIUS_STONE = 10  # Larger, more visible resources

# Water & Hygiene
WATER_NEED_DECAY = 0.04

# Praxan State Machine Constants
STATE_IDLE = 'idle'
STATE_SEEK_NEED = 'seek_need'
STATE_EXECUTE_DIRECTIVE = 'execute_directive'
STATE_SOCIALIZE = 'socialize'
STATE_REST = 'rest'
STATE_EXPLORE = 'explore'
STATE_CLAIM_TILE = 'claim_tile'
STATE_HAUL = 'haul'
STATE_GATHER = 'gather'
STATE_BUILD = 'build'
STATE_CRAFT = 'craft'

# Mental Break States
STATE_BINGE = 'binge'
STATE_SAD_WANDER = 'sad_wander'
STATE_TANTRUM = 'tantrum'
STATE_INSULTING = 'insulting'
STATE_CATATONIC = 'catatonic'
STATE_GIVE_UP = 'give_up'
STATE_DOWNED = 'downed'

# Food Spoilage
FOOD_SPOIL_TIME = 120.0  # 2 minutes

# Seasons
SEASON_LENGTH = 90.0  # 90 seconds per season

# AI / simulation tuning
PREFERRED_OLLAMA_MODEL = (RUNTIME_CONFIG.model or "qwen3.5:9b").strip()
ROLE_SKILL_MAP = {
    "gatherer": "gathering",
    "builder": "building",
    "explorer": "exploring",
}
WORK_TYPES = ['Gathering', 'Building', 'Exploring', 'Hauling', 'Researching', 'Medical', 'Crafting', 'Cooking']
ACTIVE_SCENARIO_PROFILE = get_scenario_profile(DEFAULT_SCENARIO_ID)
ACTIVE_SCENARIO_ID = ACTIVE_SCENARIO_PROFILE["id"]
ACTIVE_MUTATION_SCALE = float(ACTIVE_SCENARIO_PROFILE.get("mutation_scale", 1.0))
GENETIC_TRAIT_SPECS = {
    "metabolism_efficiency": {"label": "Metabolism", "min": 0.82, "max": 1.18},
    "learning_affinity": {"label": "Learning", "min": 0.85, "max": 1.2},
    "immune_strength": {"label": "Immunity", "min": 0.8, "max": 1.25},
    "fertility_drive": {"label": "Fertility", "min": 0.85, "max": 1.15},
    "social_cohesion": {"label": "Cohesion", "min": 0.8, "max": 1.25},
    "adaptability": {"label": "Adaptation", "min": 0.82, "max": 1.2},
}

TRAIT_DEFINITIONS = {
    'Volatile': {'mood_offset': -5, 'mental_break_threshold': 15},
    'Iron-Willed': {'mood_offset': 0, 'mental_break_threshold': -15},
    'Fast Walker': {'speed_mult': 1.25},
    'Slowpoke': {'speed_mult': 0.75},
    'Gourmand': {'hunger_rate': 1.5, 'mood_offset': -5},
    'Ascetic': {'hunger_rate': 0.8, 'mood_offset': 5},
    'Lazy': {'speed_mult': 0.9, 'hunger_rate': 0.8},
    'Industrious': {'speed_mult': 1.15, 'hunger_rate': 1.2},
    'Optimist': {'mood_offset': 10},
    'Pessimist': {'mood_offset': -10},
}
BIOME_TYPES = ["forest", "plains", "mountains", "desert", "snow", "swamp", "taiga", "tundra"]
SETTLEMENT_AURA_RADIUS = 220
SETTLEMENT_CLUSTER_RADIUS = 280
FAVORITE_BIOME_SPEED_BONUS = 0.08
MORALE_SPEED_BONUS = 0.06
INSPIRATION_SKILL_BONUS = 0.15
OLLAMA_DETECTION_TIMEOUT_SECONDS = 2.5
OLLAMA_REQUEST_TIMEOUT_SECONDS = 25.0
OLLAMA_KEEP_ALIVE = "15m"
LLM_BACKOFF_SECONDS = 45.0

# Configuration
VERBOSE_LOGGING = RUNTIME_CONFIG.verbose_console
SHOW_ENTITY_TAGS = False  # Show entity name tags above entities
DEBUG_SHOW_INVENTORY_TEXT = False  # Set to True to show debug inventory overlays (F0W0S0 format)
# ===================================================================
# COHESIVE COLOR PALETTE (24 colors for consistent pixel art style)
# ===================================================================

# Terrain greens
GRASS_DARK = (58, 125, 68)     # #3A7D44 - Dark grass
GRASS_MID = (95, 160, 82)      # #5FA052 - Medium grass
GRASS_LIGHT = (139, 200, 130)  # #8BC882 - Light grass accents

# Terrain browns/dirt
DIRT_DARK = (107, 68, 35)      # #6B4423 - Dark dirt
DIRT_MID = (139, 90, 60)       # #8B5A3C - Medium soil
DIRT_LIGHT = (170, 120, 80)    # #AA7850 - Light soil

# Terrain grays (rock/stone)
ROCK_DARK = (90, 107, 115)     # #5A6B73 - Dark rock
ROCK_MID = (122, 139, 150)     # #7A8B93 - Medium stone
ROCK_LIGHT = (160, 170, 180)   # #A0AAB4 - Light stone

# Water/ice
WATER_DEEP = (30, 80, 120)     # Deep water
WATER_SHALLOW = (80, 140, 180) # Shallow water
ICE_BLUE = (180, 220, 230)     # Ice

# Biome-specific
DESERT_SAND = (210, 180, 140)  # #D2B48C - Desert
SNOW_WHITE = (240, 248, 255)   # #F0F8FF - Snow
SWAMP_DARK = (50, 100, 60)     # Swamp green
TAIGA_GREEN = (60, 120, 80)    # Taiga forest

# Base colors (kept for compatibility)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (200, 72, 72)            # #C84848 - Softer red
YELLOW = (255, 220, 80)        # Softer yellow
GREEN = GRASS_MID              # Primary green
BLUE = (60, 120, 180)          # #3C78B4 - Soft blue
BROWN = DIRT_MID               # Primary brown
GRAY = ROCK_MID                # Primary gray

# UI accents
GOLD = (212, 175, 55)          # #D4AF37 - Gold accents
CYAN = (78, 205, 196)          # #4ECDC4 - Cyan accents
RED_ACCENT = (200, 72, 72)     # #C84848 - Red for warnings

# Role-based colors (improved for visibility)
GATHERER_COLOR = GRASS_LIGHT   # Light green
BUILDER_COLOR = DIRT_MID       # Brown
EXPLORER_COLOR = (255, 180, 80) # Orange

# Night colors (darker versions)
GREEN_NIGHT = (30, 70, 40)
RED_NIGHT = (100, 35, 35)

# Setup display - will be initialized in main()
screen = None
clock = None

# Time speed control
current_time_speed = 0  # Index into TIME_SPEED_OPTIONS (default 1x)

# Fonts for text display
font = pygame.font.Font(None, 32)  # Increased for larger window
font_large = pygame.font.Font(None, 48)  # Increased for larger window
font_small = pygame.font.Font(None, 24)  # Increased for larger window

# ===================================================================
# LLM Subsystem — delegates to llm/ package
# ===================================================================

# Global client instance (created lazily or at startup in main())
_ollama_client: OllamaClient | None = None


def _get_llm_client() -> OllamaClient:
    """Return the global OllamaClient, creating it if needed."""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient(
            preferred_model=PREFERRED_OLLAMA_MODEL,
            detect_timeout=OLLAMA_DETECTION_TIMEOUT_SECONDS,
            request_timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS,
            keep_alive=OLLAMA_KEEP_ALIVE,
            seed=getattr(RUNTIME_CONFIG, "seed", None),
        )
    return _ollama_client


# Legacy compatibility stubs — used by a handful of call sites that
# haven't been migrated yet.  New code should use the scheduler.

def get_fastest_available_model():
    """Legacy stub — delegates to OllamaClient.detect_model()."""
    if not LLM_ENABLED:
        return None
    return _get_llm_client().detect_model()


def sanitize_llm_response(response_text):
    """Legacy stub — delegates to llm.client.sanitize_llm_response."""
    return _llm_sanitize(response_text)


def generate_ollama_text(prompt, purpose="general"):
    """Legacy stub — blocking generate via OllamaClient."""
    if not LLM_ENABLED:
        raise RuntimeError("LLM disabled or Ollama unavailable")
    return _get_llm_client().generate(prompt, channel=purpose)


def start_async_llm_job(prompt, purpose, metadata=None):
    """Legacy stub — wraps generate_ollama_text in a thread."""
    job = {
        "purpose": purpose,
        "metadata": metadata or {},
        "queued_at": time.time(),
        "response_text": None,
        "model_used": None,
        "error": None,
        "done": threading.Event(),
    }

    def _runner():
        try:
            text, model = generate_ollama_text(prompt, purpose=purpose)
            job["response_text"] = text
            job["model_used"] = model
        except Exception as exc:
            job["error"] = exc
        finally:
            job["done"].set()

    job["thread"] = threading.Thread(target=_runner, daemon=True, name=f"ollama-{purpose}")
    job["thread"].start()
    return job



def sample_procedural_noise(x, y, scale, octaves=1, persistence=0.5, lacunarity=2.0):
    """Sample Perlin noise when available, otherwise fall back to a deterministic approximation."""
    if noise is not None:
        return noise.pnoise2(
            x * scale,
            y * scale,
            octaves=octaves,
            persistence=persistence,
            lacunarity=lacunarity,
        )

    base = math.sin((x * scale) * 0.73) * math.cos((y * scale) * 1.19)
    detail = math.sin((x * scale) * lacunarity + 0.37) * math.cos((y * scale) * lacunarity + 1.11)
    combined = base + (detail * persistence)
    return max(-1.0, min(1.0, combined / (1.0 + persistence)))


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def distance_between(x1, y1, x2, y2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def blend_color(color_a, color_b, factor):
    factor = clamp(factor, 0.0, 1.0)
    return tuple(int(color_a[i] + (color_b[i] - color_a[i]) * factor) for i in range(3))


def set_active_scenario(scenario_id):
    global ACTIVE_SCENARIO_PROFILE, ACTIVE_SCENARIO_ID, ACTIVE_MUTATION_SCALE

    profile = get_scenario_profile(scenario_id)
    ACTIVE_SCENARIO_PROFILE = profile
    ACTIVE_SCENARIO_ID = profile["id"]
    ACTIVE_MUTATION_SCALE = max(0.5, min(3.0, float(profile.get("mutation_scale", 1.0))))
    return profile


def spawn_resource_cluster(resources, center_x, center_y, count, resource_type, world_width, world_height, min_distance, max_distance):
    for _ in range(max(0, int(count))):
        angle = random.uniform(0, 2 * math.pi)
        distance = random.uniform(min_distance, max_distance)
        x = center_x + distance * math.cos(angle)
        y = center_y + distance * math.sin(angle)
        x = max(50, min(world_width - 50, x))
        y = max(50, min(world_height - 50, y))
        resources.append(Resource(x, y, resource_type))


def apply_scenario_startup_conditions(scenario_profile, praxans, advisor, season, weather_system, current_time):
    favorite_biomes = [biome for biome in scenario_profile.get("favorite_biomes", []) if biome in BIOME_TYPES] or BIOME_TYPES
    morale_bonus = float(scenario_profile.get("morale_bonus", 0.0))
    inspiration_bonus = float(scenario_profile.get("inspiration_bonus", 0.0))
    health_bonus = float(scenario_profile.get("health_bonus", 0.0))
    disease_health_penalty = float(scenario_profile.get("disease_health_penalty", 0.0))

    for praxan in praxans:
        praxan.favorite_biome = random.choice(favorite_biomes)
        praxan.morale = clamp(praxan.morale + morale_bonus, 0.0, 100.0)
        praxan.inspiration = clamp(praxan.inspiration + inspiration_bonus, 0.0, 100.0)
        praxan.health = clamp(praxan.health + health_bonus, 10.0, 100.0)

    diseased_count = min(len(praxans), max(0, int(scenario_profile.get("starting_diseased", 0))))
    if diseased_count > 0:
        try:
            from systems.disease import DiseaseManager, get_all_disease_ids
            mgr = DiseaseManager()
            disease_ids = get_all_disease_ids()
            for praxan in random.sample(praxans, diseased_count):
                did = random.choice(disease_ids) if disease_ids else None
                if did:
                    mgr.infect(praxan, did)
                else:
                    praxan.diseased = True
                    praxan.disease_start_time = current_time - random.uniform(5.0, 15.0)
                praxan.health = clamp(praxan.health - disease_health_penalty, 10.0, 100.0)
                praxan.add_moodlet("Sickly Start", -12.0, 600, current_time)
        except Exception:
            for praxan in random.sample(praxans, diseased_count):
                praxan.diseased = True
                praxan.disease_start_time = current_time - random.uniform(5.0, 15.0)
                praxan.health = clamp(praxan.health - disease_health_penalty, 10.0, 100.0)
                praxan.add_moodlet("Sickly Start", -12.0, 600, current_time)

    advisor.research_points += max(0, int(scenario_profile.get("starting_research", 0)))
    advisor.last_pop_count = len(praxans)
    advisor.session_stats["scenario_id"] = scenario_profile["id"]
    advisor.session_stats["scenario_name"] = scenario_profile["name"]
    advisor.session_stats["mutation_scale"] = ACTIVE_MUTATION_SCALE

    for challenge_template in scenario_profile.get("initial_challenges", []):
        if not isinstance(challenge_template, dict):
            continue
        challenge = dict(challenge_template)
        challenge["start_time"] = current_time
        challenge["duration"] = float(challenge_template.get("duration", 45.0))
        challenge["active"] = bool(challenge_template.get("active", True))
        advisor.active_challenges.append(challenge)

    if scenario_profile.get("season") in ("spring", "summer", "autumn", "winter"):
        season.current = scenario_profile["season"]
    weather_system.current_weather = scenario_profile.get("weather", weather_system.current_weather)
    delay_min, delay_max = scenario_profile.get("weather_delay_range", (45.0, 90.0))
    weather_system.next_event_time = current_time + random.uniform(float(delay_min), float(delay_max))


def get_role_skill_key(role):
    return ROLE_SKILL_MAP.get(role)


def random_genetic_profile():
    profile = {}
    for trait_name, trait_spec in GENETIC_TRAIT_SPECS.items():
        profile[trait_name] = round(random.uniform(trait_spec["min"], trait_spec["max"]), 3)
    return profile


def inherit_genetic_profile(parent1, parent2):
    inherited_profile = {}
    mutation_count = 0
    mutation_span = 0.05 * ACTIVE_MUTATION_SCALE
    for trait_name, trait_spec in GENETIC_TRAIT_SPECS.items():
        parent_a = getattr(parent1, "genetics", {}).get(trait_name, 1.0)
        parent_b = getattr(parent2, "genetics", {}).get(trait_name, 1.0)
        parent_avg = (parent_a + parent_b) / 2.0
        mutated_value = clamp(parent_avg + random.uniform(-mutation_span, mutation_span), trait_spec["min"], trait_spec["max"])
        if abs(mutated_value - parent_avg) >= (mutation_span * 0.5):
            mutation_count += 1
        inherited_profile[trait_name] = round(mutated_value, 3)
    return inherited_profile, mutation_count


def format_genetic_trait_delta(value):
    delta_pct = (value - 1.0) * 100.0
    return f"{delta_pct:+.0f}%"


def summarize_population_evolution(praxans):
    if not praxans:
        return {
            "population": 0,
            "avg_generation": 0.0,
            "max_generation": 0,
            "founder_lines": 0,
            "dominant_lineage": None,
            "dominant_lineage_size": 0,
            "dominant_biome": "plains",
            "total_mutations": 0,
            "avg_traits": {trait_name: 1.0 for trait_name in GENETIC_TRAIT_SPECS},
            "trait_drift": "metabolism_efficiency",
            "lineage_counts": {},
        }

    lineage_counts = {}
    biome_counts = {}
    avg_traits = {trait_name: 0.0 for trait_name in GENETIC_TRAIT_SPECS}
    generation_values = []
    total_mutations = 0

    for praxan in praxans:
        lineage_id = getattr(praxan, "lineage_id", praxan.id)
        lineage_counts[lineage_id] = lineage_counts.get(lineage_id, 0) + 1
        biome_name = getattr(praxan, "favorite_biome", "plains")
        biome_counts[biome_name] = biome_counts.get(biome_name, 0) + 1
        generation_values.append(getattr(praxan, "generation", 0))
        total_mutations += int(getattr(praxan, "mutation_count", 0))
        for trait_name in GENETIC_TRAIT_SPECS:
            avg_traits[trait_name] += getattr(praxan, "genetics", {}).get(trait_name, 1.0)

    population = len(praxans)
    for trait_name in avg_traits:
        avg_traits[trait_name] = round(avg_traits[trait_name] / population, 3)

    dominant_lineage, dominant_lineage_size = max(lineage_counts.items(), key=lambda item: item[1])
    dominant_biome = max(biome_counts.items(), key=lambda item: item[1])[0]
    trait_drift = max(avg_traits.items(), key=lambda item: abs(item[1] - 1.0))[0]

    return {
        "population": population,
        "avg_generation": round(sum(generation_values) / population, 2),
        "max_generation": max(generation_values),
        "founder_lines": len(lineage_counts),
        "dominant_lineage": dominant_lineage,
        "dominant_lineage_size": dominant_lineage_size,
        "dominant_biome": dominant_biome,
        "total_mutations": total_mutations,
        "avg_traits": avg_traits,
        "trait_drift": trait_drift,
        "lineage_counts": lineage_counts,
    }


# ---- Emergent Culture from Genetics ----------------------------------------

_TRAIT_CULTURE_MAP = {
    "adaptability":        "Explorer",       # curious, frontier-seeking
    "learning_affinity":   "Scholar",        # knowledge-driven
    "immune_strength":     "Stoic",          # hardy, endurance-oriented
    "fertility_drive":     "Expansionist",   # growth-focused, prolific
    "social_cohesion":     "Communal",       # cooperation-oriented
    "metabolism_efficiency": "Resilient",    # resource-efficient, survivors
}


def compute_cultural_profile(avg_traits: dict[str, float]) -> dict[str, Any]:
    """Derive a cultural identity from population-level genetic averages.

    Returns:
        {
            "dominant_culture": "Explorer" | "Scholar" | ...
            "dominant_trait": "adaptability" | ...
            "drift_magnitude": float   (how far the dominant trait is from baseline)
            "profile_summary": "Explorer culture (high adaptability +12%)"
            "secondary_culture": "Scholar" | None
        }
    """
    if not avg_traits:
        return {
            "dominant_culture": "Balanced",
            "dominant_trait": "",
            "drift_magnitude": 0.0,
            "profile_summary": "Balanced culture (no dominant traits)",
            "secondary_culture": None,
        }

    # Sort traits by absolute deviation from baseline
    sorted_traits = sorted(
        avg_traits.items(),
        key=lambda item: abs(item[1] - 1.0),
        reverse=True,
    )

    top_trait, top_val = sorted_traits[0]
    drift_pct = round((top_val - 1.0) * 100, 1)
    dominant = _TRAIT_CULTURE_MAP.get(top_trait, "Balanced")

    secondary = None
    if len(sorted_traits) > 1:
        sec_trait, sec_val = sorted_traits[1]
        if abs(sec_val - 1.0) > 0.03:
            secondary = _TRAIT_CULTURE_MAP.get(sec_trait)

    sign = "+" if drift_pct >= 0 else ""
    summary = f"{dominant} culture (high {top_trait.replace('_', ' ')} {sign}{drift_pct}%)"

    return {
        "dominant_culture": dominant,
        "dominant_trait": top_trait,
        "drift_magnitude": abs(top_val - 1.0),
        "profile_summary": summary,
        "secondary_culture": secondary,
    }


def append_bounded_history(target_list, entry, limit):
    target_list.append(entry)
    if len(target_list) > limit:
        del target_list[:-limit]


def record_observer_timeline_event(advisor, current_time, category, summary, details=None):
    if advisor is None:
        return

    summary_text = str(summary).strip()
    if not summary_text:
        return

    append_bounded_history(
        advisor.events_history,
        {
            "time": current_time,
            "description": summary_text,
        },
        24,
    )
    timeline_event = {
        "time": current_time,
        "category": str(category or "simulation"),
        "summary": summary_text,
    }
    if details:
        timeline_event["details"] = str(details).strip()
    append_bounded_history(advisor.session_stats.setdefault("timeline_events", []), timeline_event, 32)


def build_trait_display_lines(genetics):
    lines = []
    for trait_name, trait_spec in GENETIC_TRAIT_SPECS.items():
        trait_value = getattr(genetics, "get", lambda *_: 1.0)(trait_name, 1.0) if genetics is not None else 1.0
        lines.append(f"  {trait_spec['label']}: {format_genetic_trait_delta(trait_value)}")
    return lines


def refresh_run_summary_cache(
    advisor,
    praxans,
    buildings,
    current_time,
    game_start_time,
    faction_manager=None,
    scenario_id=None,
    scenario_name=None,
    selected_model=None,
    seed=None,
    session_id=None,
    extinction=False,
    force=False,
):
    if advisor is None:
        return {}

    last_refresh = float(getattr(advisor, "last_run_summary_refresh", 0.0) or 0.0)
    if not force and current_time - last_refresh < 8.0:
        return advisor.session_stats.get("current_run_summary", {})

    summary = build_run_summary(
        praxans=praxans,
        buildings=buildings,
        advisor=advisor,
        current_time=current_time,
        game_start_time=game_start_time,
        settlement_state=getattr(advisor, "current_settlement_state", {}),
        faction_manager=faction_manager,
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        selected_model=selected_model,
        seed=seed,
        session_id=session_id,
        extinction=extinction,
    )
    advisor.session_stats["current_run_summary"] = summary
    advisor.last_run_summary_refresh = current_time
    return summary


def record_population_evolution_sample(advisor, praxans, current_time, game_start_time, force=False):
    if advisor is None:
        return summarize_population_evolution(praxans)

    last_sample_time = getattr(advisor, "last_evolution_sample_time", 0.0)
    if not force and current_time - last_sample_time < 20.0:
        return advisor.session_stats.get("current_evolution_summary", summarize_population_evolution(praxans))

    summary = summarize_population_evolution(praxans)
    sample = {
        "elapsed_seconds": round(max(0.0, current_time - game_start_time), 2),
        "population": summary["population"],
        "avg_generation": summary["avg_generation"],
        "max_generation": summary["max_generation"],
        "founder_lines": summary["founder_lines"],
        "dominant_lineage": summary["dominant_lineage"],
        "trait_drift": summary["trait_drift"],
        "avg_traits": dict(summary["avg_traits"]),
    }
    history = advisor.session_stats.setdefault("evolution_history", [])
    append_bounded_history(history, sample, 18)
    advisor.session_stats["current_evolution_summary"] = summary
    advisor.session_stats["highest_generation"] = max(
        summary["max_generation"],
        advisor.session_stats.get("highest_generation", 0),
    )
    advisor.session_stats["peak_founder_lines"] = max(
        summary["founder_lines"],
        advisor.session_stats.get("peak_founder_lines", 0),
    )
    advisor.last_evolution_sample_time = current_time
    return summary


def compute_colony_anchor(praxans, buildings):
    living_praxans = [praxan for praxan in praxans if getattr(praxan, "alive", True)]
    if buildings:
        anchors = [(float(building.x), float(building.y)) for building in buildings if hasattr(building, "x") and hasattr(building, "y")]
        if living_praxans:
            anchors.extend((float(praxan.x), float(praxan.y)) for praxan in living_praxans[:8])
        if anchors:
            return (
                sum(anchor[0] for anchor in anchors) / len(anchors),
                sum(anchor[1] for anchor in anchors) / len(anchors),
            )

    if not living_praxans:
        return None

    def _cluster_cost(candidate):
        return sum(math.sqrt((candidate.x - other.x) ** 2 + (candidate.y - other.y) ** 2) for other in living_praxans)

    anchor_praxan = min(living_praxans, key=_cluster_cost)
    return float(anchor_praxan.x), float(anchor_praxan.y)


def estimate_bootstrap_materials(anchor_x, anchor_y, praxans, buildings, resources):
    available_wood = 0.0
    available_stone = 0.0

    for praxan in praxans:
        if not getattr(praxan, "alive", True):
            continue
        if math.sqrt((praxan.x - anchor_x) ** 2 + (praxan.y - anchor_y) ** 2) > 260:
            continue
        available_wood += float(praxan.inventory.get("wood", 0) or 0)
        available_stone += float(praxan.inventory.get("stone", 0) or 0)

    for building in buildings:
        stored_resources = getattr(building, "stored_resources", None)
        if not stored_resources:
            continue
        if math.sqrt((building.x - anchor_x) ** 2 + (building.y - anchor_y) ** 2) > 220:
            continue
        available_wood += float(stored_resources.get("wood", 0) or 0)
        available_stone += float(stored_resources.get("stone", 0) or 0)

    for resource in resources:
        if getattr(resource, "collected", False):
            continue
        if getattr(resource, "resource_type", "") not in ("wood", "stone"):
            continue
        if math.sqrt((resource.x - anchor_x) ** 2 + (resource.y - anchor_y) ** 2) > 240:
            continue
        if resource.resource_type == "wood":
            available_wood += 1.0
        else:
            available_stone += 1.0

    return available_wood, available_stone


def consume_bootstrap_materials(anchor_x, anchor_y, required_wood, required_stone, praxans, buildings, resources, current_time):
    wood_needed = float(required_wood)
    stone_needed = float(required_stone)

    for praxan in praxans:
        if wood_needed <= 0 and stone_needed <= 0:
            return True
        if not getattr(praxan, "alive", True):
            continue
        if math.sqrt((praxan.x - anchor_x) ** 2 + (praxan.y - anchor_y) ** 2) > 260:
            continue
        if wood_needed > 0:
            available = float(praxan.inventory.get("wood", 0) or 0)
            take = min(wood_needed, available)
            praxan.inventory["wood"] = max(0, available - take)
            wood_needed -= take
        if stone_needed > 0:
            available = float(praxan.inventory.get("stone", 0) or 0)
            take = min(stone_needed, available)
            praxan.inventory["stone"] = max(0, available - take)
            stone_needed -= take

    for building in buildings:
        if wood_needed <= 0 and stone_needed <= 0:
            return True
        stored_resources = getattr(building, "stored_resources", None)
        if not stored_resources:
            continue
        if math.sqrt((building.x - anchor_x) ** 2 + (building.y - anchor_y) ** 2) > 220:
            continue
        if wood_needed > 0:
            available = float(stored_resources.get("wood", 0) or 0)
            take = min(wood_needed, available)
            stored_resources["wood"] = max(0.0, available - take)
            wood_needed -= take
        if stone_needed > 0:
            available = float(stored_resources.get("stone", 0) or 0)
            take = min(stone_needed, available)
            stored_resources["stone"] = max(0.0, available - take)
            stone_needed -= take

    for resource in resources:
        if wood_needed <= 0 and stone_needed <= 0:
            return True
        if getattr(resource, "collected", False):
            continue
        if math.sqrt((resource.x - anchor_x) ** 2 + (resource.y - anchor_y) ** 2) > 240:
            continue
        if resource.resource_type == "wood" and wood_needed > 0:
            resource.collected = True
            resource.collect_time = current_time
            wood_needed -= 1.0
        elif resource.resource_type == "stone" and stone_needed > 0:
            resource.collected = True
            resource.collect_time = current_time
            stone_needed -= 1.0

    return wood_needed <= 0 and stone_needed <= 0


def attempt_bootstrap_construction(
    *,
    praxans,
    buildings,
    resources,
    advisor,
    city_planner,
    world_map,
    particle_system,
    narrative_panel,
    current_time,
    reputation_manager=None,
):
    if advisor is None or city_planner is None or not praxans:
        return None

    last_bootstrap_time = float(getattr(advisor, "last_bootstrap_build_time", 0.0) or 0.0)
    if current_time - last_bootstrap_time < 12.0:
        return None

    living_praxans = [praxan for praxan in praxans if getattr(praxan, "alive", True)]
    if not living_praxans:
        return None

    anchor = compute_colony_anchor(living_praxans, buildings)
    if anchor is None:
        return None
    anchor_x, anchor_y = anchor

    counts = {}
    for building in buildings:
        building_type = getattr(building, "building_type", "house")
        counts[building_type] = counts.get(building_type, 0) + 1

    desired_build_order = []
    if counts.get("house", 0) == 0:
        desired_build_order.append("house")
    if counts.get("storage", 0) == 0 and len(living_praxans) >= 2:
        desired_build_order.append("storage")
    if counts.get("farm", 0) == 0 and len(living_praxans) >= 2:
        desired_build_order.append("farm")
    if counts.get("well", 0) == 0 and len(living_praxans) >= 3:
        desired_build_order.append("well")

    if not desired_build_order:
        return None

    available_wood, available_stone = estimate_bootstrap_materials(anchor_x, anchor_y, living_praxans, buildings, resources)
    for building_type in desired_build_order:
        required_wood, required_stone = get_building_cost(building_type)
        if available_wood < required_wood or available_stone < required_stone:
            continue

        build_x, build_y, _ = city_planner.find_best_location(building_type, buildings, getattr(world_map, "hazards", []), anchor)
        if not consume_bootstrap_materials(anchor_x, anchor_y, required_wood, required_stone, living_praxans, buildings, resources, current_time):
            continue

        new_building = Building(build_x, build_y, building_type)
        new_building.built_at = current_time
        builder = min(living_praxans, key=lambda praxan: math.sqrt((praxan.x - build_x) ** 2 + (praxan.y - build_y) ** 2))
        new_building.built_by = getattr(builder, "id", None)
        if world_map is not None and hasattr(world_map, "get_biome_at"):
            try:
                new_building.origin_biome = world_map.get_biome_at(build_x, build_y)
            except Exception:
                new_building.origin_biome = None
        if not new_building.material_style:
            new_building.material_style = new_building._derive_material_style(new_building.origin_biome)

        buildings.append(new_building)
        particle_system.create_particles(build_x, build_y, 'build', 12)
        try:
            builder.gain_skill_xp('building', SKILL_XP_BUILDING)
        except Exception:
            pass
        advisor.session_stats['buildings_built'][building_type] = advisor.session_stats['buildings_built'].get(building_type, 0) + 1
        advisor.last_bootstrap_build_time = current_time
        narrative_panel.add_message(f"Bootstrap crew raised a {building_type}.", 'Achievement')
        record_observer_timeline_event(
            advisor,
            current_time,
            "build",
            f"Built {building_type}",
            f"Bootstrap construction completed near colony center by #{getattr(builder, 'id', 'unknown')}.",
        )
        # Reputation boost for the builder
        if reputation_manager is not None:
            reputation_manager.record_event(getattr(builder, 'id', -1), "built_structure")
        # Queue personality shift for the builder
        pending = getattr(builder, '_pending_personality_shifts', None)
        if pending is not None:
            pending.append("entity:built_structure")
        return new_building

    return None


def build_runtime_telemetry_sample(
    *,
    current_time,
    game_start_time,
    frame_count,
    praxans,
    buildings,
    resources,
    advisor,
    settlement_state,
    season,
    weather_system,
    faction_manager,
    runtime_config,
    selected_model,
    time_speed_value,
):
    elapsed_seconds = max(0.0, float(current_time) - float(game_start_time))
    active_resources = {
        "food": 0,
        "wood": 0,
        "stone": 0,
        "water": 0,
    }
    for resource in resources:
        if getattr(resource, "collected", False):
            continue
        resource_type = str(getattr(resource, "resource_type", "food") or "food")
        active_resources[resource_type] = active_resources.get(resource_type, 0) + 1

    building_counts = {}
    for building in buildings:
        building_type = str(getattr(building, "building_type", "house") or "house")
        building_counts[building_type] = building_counts.get(building_type, 0) + 1
    dominant_buildings = [
        {"type": building_type, "count": count}
        for building_type, count in sorted(building_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
    ]

    population = max(0, len(praxans))
    avg_health = round(sum(float(getattr(praxan, "health", 0.0) or 0.0) for praxan in praxans) / population, 2) if population else 0.0
    avg_happiness = round(sum(float(getattr(praxan, "happiness", 0.0) or 0.0) for praxan in praxans) / population, 2) if population else 0.0
    avg_morale = round(sum(float(getattr(praxan, "morale", 0.0) or 0.0) for praxan in praxans) / population, 2) if population else 0.0
    avg_inspiration = round(sum(float(getattr(praxan, "inspiration", 0.0) or 0.0) for praxan in praxans) / population, 2) if population else 0.0
    diseased_count = sum(1 for praxan in praxans if bool(getattr(praxan, "diseased", False)))
    mutated_count = sum(1 for praxan in praxans if int(getattr(praxan, "mutation_count", 0) or 0) > 0)
    max_generation = max((int(getattr(praxan, "generation", 0) or 0) for praxan in praxans), default=0)

    faction_count = len(getattr(faction_manager, "factions", {}) or {}) if faction_manager is not None else 0
    current_summary = dict(getattr(advisor, "session_stats", {}).get("current_run_summary", {}) or {})
    current_phase = dict(current_summary.get("current_phase", {}) or {})
    end_state = dict(current_summary.get("end_state", {}) or {})

    llm_pending = False
    if hasattr(advisor, "has_pending_llm_jobs"):
        try:
            llm_pending = bool(advisor.has_pending_llm_jobs())
        except Exception:
            llm_pending = False

    return {
        "timestamp": round(float(current_time), 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "frame_count": int(frame_count),
        "scenario_id": str(getattr(advisor, "session_stats", {}).get("scenario_id", runtime_config.scenario)),
        "session_tag": str(getattr(runtime_config, "session_tag", "") or ""),
        "population": population,
        "buildings_total": len(buildings),
        "resources_active": active_resources,
        "dominant_buildings": dominant_buildings,
        "praxans": {
            "avg_health": avg_health,
            "avg_happiness": avg_happiness,
            "avg_morale": avg_morale,
            "avg_inspiration": avg_inspiration,
            "diseased": diseased_count,
            "mutated": mutated_count,
            "max_generation": max_generation,
        },
        "settlement": {
            "district_identity": str(settlement_state.get("district_identity", "homestead")),
            "prosperity_score": round(float(settlement_state.get("prosperity_score", 0.0) or 0.0), 3),
            "culture_score": round(float(settlement_state.get("culture_score", 0.0) or 0.0), 3),
            "security_score": round(float(settlement_state.get("security_score", 0.0) or 0.0), 3),
            "stored_food": int(settlement_state.get("stored_food", 0) or 0),
            "stored_wood": int(settlement_state.get("stored_wood", 0) or 0),
            "stored_stone": int(settlement_state.get("stored_stone", 0) or 0),
        },
        "factions": {
            "active": faction_count,
            "peak": int(getattr(advisor, "session_stats", {}).get("peak_factions", faction_count) or faction_count),
            "group_tasks_active": len(getattr(advisor, "group_tasks", []) or []),
            "active_challenges": len(getattr(advisor, "active_challenges", []) or []),
        },
        "advisor": {
            "births_total": int(getattr(advisor, "session_stats", {}).get("births_total", 0) or 0),
            "deaths_total": int(getattr(advisor, "total_deaths", 0) or 0),
            "research_points": int(getattr(advisor, "research_points", 0) or 0),
            "last_model_used": str(getattr(advisor, "last_model_used", "") or ""),
            "phase_id": str(current_phase.get("id", "")),
            "end_state_id": str(end_state.get("id", "")),
            "score": int(end_state.get("score", 0) or 0),
        },
        "environment": {
            "season": str(getattr(season, "current", "")),
            "weather": str(getattr(weather_system, "current_weather", "")),
            "time_speed": round(float(time_speed_value or 0.0), 3),
        },
        "llm": {
            "enabled": bool(LLM_ENABLED and not runtime_config.disable_llm),
            "selected_model": str(selected_model or ""),
            "pending_jobs": llm_pending,
        },
    }


def compute_settlement_snapshot(praxans, buildings, world_map=None, season=None, weather_system=None):
    counts = {btype: 0 for btype in ["house", "storage", "farm", "workshop", "shrine", "well"]}
    stored_food = 0
    stored_wood = 0
    stored_stone = 0
    total_inventory_food = sum(t.inventory.get("food", 0) for t in praxans)

    for building in buildings:
        counts[building.building_type] = counts.get(building.building_type, 0) + 1
        stored_food += building.stored_resources.get("food", 0)
        stored_wood += building.stored_resources.get("wood", 0)
        stored_stone += building.stored_resources.get("stone", 0)

    population = max(1, len(praxans))
    avg_health = sum(t.health for t in praxans) / population if praxans else 100
    avg_happiness = sum(t.happiness for t in praxans) / population if praxans else 80
    avg_morale = sum(getattr(t, "morale", 65) for t in praxans) / population if praxans else 65

    shelter_ratio = clamp(counts.get("house", 0) / max(1.0, population / 2.0), 0.0, 1.0)
    water_ratio = clamp(counts.get("well", 0) / max(1.0, population / 5.0), 0.0, 1.0)
    spirit_ratio = clamp(counts.get("shrine", 0) / max(1.0, population / 6.0), 0.0, 1.0)
    industry_ratio = clamp((counts.get("storage", 0) + counts.get("workshop", 0)) / max(1.0, population / 4.0), 0.0, 1.0)
    food_security = clamp((stored_food + total_inventory_food + counts.get("farm", 0) * 2) / (population * 3.0), 0.0, 1.35)

    season_modifier = {
        "spring": 0.08,
        "summer": 0.02,
        "autumn": 0.05,
        "winter": -0.06,
    }.get(season.current if season else "summer", 0.0)
    weather_modifier = {
        "clear": 0.0,
        "rain": 0.06,
        "storm": -0.08,
        "drought": -0.12,
        "aurora": 0.10,
    }.get(weather_system.current_weather if weather_system else "clear", 0.0)

    prosperity_score = clamp(
        0.18
        + (avg_health / 100.0) * 0.22
        + (avg_happiness / 100.0) * 0.18
        + (avg_morale / 100.0) * 0.12
        + shelter_ratio * 0.10
        + water_ratio * 0.08
        + spirit_ratio * 0.06
        + industry_ratio * 0.07
        + food_security * 0.10
        + season_modifier
        + weather_modifier,
        0.0,
        1.4,
    )
    culture_score = clamp((spirit_ratio * 0.4) + (industry_ratio * 0.2) + (avg_happiness / 100.0) * 0.4, 0.0, 1.0)
    district_scores = {
        "homestead": counts.get("house", 0) + shelter_ratio * 2.0,
        "agrarian": counts.get("farm", 0) + food_security * 1.8,
        "industrial": counts.get("workshop", 0) + counts.get("storage", 0) + industry_ratio * 1.6,
        "spiritual": counts.get("shrine", 0) + spirit_ratio * 2.2,
        "hydration": counts.get("well", 0) + water_ratio * 2.0,
    }
    district_identity = max(district_scores.items(), key=lambda item: item[1])[0]
    festival_readiness = clamp(
        (prosperity_score * 0.55)
        + (culture_score * 0.3)
        + (avg_morale / 100.0) * 0.15,
        0.0,
        1.0,
    )

    dominant_biome = "plains"
    if world_map and praxans:
        biome_counts = {}
        for praxan in praxans:
            biome = world_map.get_biome_at(praxan.x, praxan.y)
            biome_counts[biome] = biome_counts.get(biome, 0) + 1
        dominant_biome = max(biome_counts.items(), key=lambda item: item[1])[0]

    for building in buildings:
        nearby_types = {building.building_type}
        nearby_population = 0
        for other in buildings:
            if other is building:
                continue
            if distance_between(building.x, building.y, other.x, other.y) <= SETTLEMENT_CLUSTER_RADIUS:
                nearby_types.add(other.building_type)

        if praxans:
            nearby_population = sum(
                1 for praxan in praxans if distance_between(building.x, building.y, praxan.x, praxan.y) <= SETTLEMENT_AURA_RADIUS
            )

        storage_bonus = min(0.35, sum(building.stored_resources.values()) / 30.0)
        synergy_score = (len(nearby_types) - 1) * 0.22 + min(0.25, nearby_population * 0.04) + storage_bonus
        building.level = 1 + int(synergy_score >= 0.42) + int(synergy_score >= 0.88)
        building.aura_strength = clamp((prosperity_score * 0.45) + synergy_score * 0.55, 0.0, 1.0)

    landmark_level = max((getattr(building, "level", 1) for building in buildings), default=1)

    return {
        "population": population,
        "counts": counts,
        "stored_food": stored_food,
        "stored_wood": stored_wood,
        "stored_stone": stored_stone,
        "avg_health": avg_health,
        "avg_happiness": avg_happiness,
        "avg_morale": avg_morale,
        "prosperity_score": prosperity_score,
        "culture_score": culture_score,
        "district_identity": district_identity,
        "festival_readiness": festival_readiness,
        "landmark_level": landmark_level,
        "dominant_biome": dominant_biome,
        "weather": weather_system.current_weather if weather_system else "clear",
        "season": season.current if season else "summer",
        "festival_active": False,
        "festival_timer": 0.0,
    }



def update_settlement_celebration(
    celebration_state,
    settlement_state,
    praxans,
    buildings,
    particle_system,
    narrative_panel,
    current_time,
    delta_time,
):
    """Trigger and sustain celebratory surges when the settlement is thriving."""
    if not settlement_state:
        return

    active_until = celebration_state.get("active_until", 0.0)
    center = celebration_state.get("center")
    festival_active = active_until > current_time
    counts = settlement_state.get("counts", {})
    readiness = settlement_state.get("festival_readiness", 0.0)
    has_cultural_anchor = counts.get("shrine", 0) > 0 or counts.get("workshop", 0) > 0

    if not festival_active and current_time >= celebration_state.get("cooldown_until", 0.0):
        if len(praxans) >= 4 and has_cultural_anchor and readiness >= 0.78:
            anchor = next(
                (
                    building
                    for building in buildings
                    if building.building_type in ("shrine", "workshop", "house")
                ),
                buildings[0] if buildings else None,
            )
            if anchor:
                center = (anchor.x, anchor.y)
            elif praxans:
                center = (
                    sum(praxan.x for praxan in praxans) / len(praxans),
                    sum(praxan.y for praxan in praxans) / len(praxans),
                )
            else:
                center = None

            celebration_state["center"] = center
            celebration_state["active_until"] = current_time + 18.0
            celebration_state["cooldown_until"] = current_time + 95.0
            celebration_state["last_particle_time"] = 0.0
            active_until = celebration_state["active_until"]
            festival_active = True
            narrative_panel.add_message("SETTLEMENT FESTIVAL: Prosperity ripples through the colony.", "Achievement")
            if center:
                particle_system.create_particles(center[0], center[1], "confetti", 24)

    if festival_active:
        if center and current_time - celebration_state.get("last_particle_time", 0.0) >= 0.8:
            celebration_state["last_particle_time"] = current_time
            particle_system.create_particles(
                center[0] + random.uniform(-20, 20),
                center[1] + random.uniform(-20, 20),
                "confetti",
                8,
            )

        for praxan in praxans:
            bonus_scale = 1.0
            if center and distance_between(praxan.x, praxan.y, center[0], center[1]) <= 220:
                bonus_scale = 1.35
            praxan.morale = clamp(praxan.morale + 0.9 * delta_time * bonus_scale, 0.0, 100.0)
            praxan.add_moodlet("Festival Joy", 15.0 * bonus_scale, 5.0, current_time)
            praxan.inspiration = clamp(praxan.inspiration + 0.65 * delta_time * bonus_scale, 0.0, 100.0)

    settlement_state["festival_active"] = festival_active
    settlement_state["festival_timer"] = max(0.0, active_until - current_time) if festival_active else 0.0


class AssetManager:
    """Manages loading and caching of game assets (tilesets, sprites, etc.)"""
    def __init__(self):
        self.tilesets = {}
        self.sprites = {}
        self.cache = {}
        self.assets_path = os.path.join(os.path.dirname(__file__), 'assets')
    
    def load_tile(self, biome_type, tile_name):
        """Load a specific tile for a biome type"""
        cache_key = f"{biome_type}_{tile_name}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        # Try to load from file
        tile_path = os.path.join(self.assets_path, 'tilesets', f"{biome_type}_{tile_name}.png")
        if os.path.exists(tile_path):
            try:
                tile_surface = pygame.image.load(tile_path).convert_alpha()
                tile_surface = pygame.transform.scale(tile_surface, (TILE_SIZE, TILE_SIZE))
                self.cache[cache_key] = tile_surface
                return tile_surface
            except Exception as e:
                print(f"Failed to load tile {tile_path}: {e}")
        
        # Fallback: generate procedural tile
        return self.generate_tile(biome_type, tile_name)
    
    def generate_tile(self, biome_type, tile_name):
        """Generate a procedural tile as fallback with dithering and texture"""
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface = surface.convert_alpha()  # Enable alpha for better rendering
        
        # Use new cohesive color palette
        biome_colors = {
            'forest': GRASS_DARK,
            'plains': GRASS_MID,
            'mountains': ROCK_MID,
            'desert': DESERT_SAND,
            'snow': SNOW_WHITE,
            'swamp': SWAMP_DARK,
            'taiga': TAIGA_GREEN,
            'tundra': ICE_BLUE
        }
        
        base_color = biome_colors.get(biome_type, GRAY)
        surface.fill(base_color)
        
        # Add texture with dithering pattern for pixel art feel
        if biome_type in ['forest', 'plains', 'taiga']:
            # Grass textures with dithering
            variant = random.choice([GRASS_DARK, GRASS_MID, GRASS_LIGHT])
            for i in range(0, TILE_SIZE, 4):
                for j in range(0, TILE_SIZE, 4):
                    if random.random() < 0.3:
                        pygame.draw.rect(surface, variant, (i, j, 2, 2))
        elif biome_type in ['mountains']:
            # Rocky texture
            variant = random.choice([ROCK_DARK, ROCK_MID, ROCK_LIGHT])
            for _ in range(8):
                x = random.randint(0, TILE_SIZE - 3)
                y = random.randint(0, TILE_SIZE - 3)
                pygame.draw.rect(surface, variant, (x, y, 3, 3))
        elif biome_type == 'desert':
            # Sandy texture
            for _ in range(6):
                x = random.randint(0, TILE_SIZE - 1)
                y = random.randint(0, TILE_SIZE - 1)
                pygame.draw.rect(surface, DIRT_LIGHT, (x, y, 1, 1))
        elif biome_type == 'swamp':
            # Muddy texture with water spots
            for _ in range(5):
                x = random.randint(0, TILE_SIZE - 2)
                y = random.randint(0, TILE_SIZE - 2)
                pygame.draw.rect(surface, WATER_DEEP, (x, y, 2, 2))
        elif biome_type == 'snow':
            # Snow texture with slight variations
            for _ in range(4):
                x = random.randint(0, TILE_SIZE - 1)
                y = random.randint(0, TILE_SIZE - 1)
                pygame.draw.rect(surface, (250, 250, 255), (x, y, 1, 1))
        
        cache_key = f"{biome_type}_{tile_name}"
        self.cache[cache_key] = surface
        return surface


class NarrativePanel:
    """Manages scrolling narrative log for LLM advisor storytelling"""
    def __init__(self):
        self.messages = []
        self.max_messages = 5
    
    def add_message(self, message, category='Strategy'):
        """Add a narrative message"""
        self.messages.append({
            'text': message,
            'category': category,
            'time': time.time(),
            'alpha': 0  # Start invisible for fade-in
        })
        # Keep only recent messages
        if len(self.messages) > self.max_messages:
            self.messages.pop(0)
    
    def update(self):
        """Update alpha fade-in for messages"""
        for msg in self.messages:
            age = time.time() - msg['time']
            # Fade in over 1 second
            if age < 1.0:
                msg['alpha'] = min(255, int(255 * age))
    
    def draw(self, surface, x, y, width, height):
        """Draw the narrative panel"""
        # Semi-transparent background
        panel = pygame.Surface((width, height))
        panel.set_alpha(200)
        panel.fill((20, 20, 40))
        surface.blit(panel, (x, y))
        
        # Category color mapping
        category_colors = {
            'Strategy': (150, 150, 255),
            'Discovery': (150, 255, 150),
            'Crisis': (255, 150, 150),
            'Achievement': (255, 255, 150)
        }
        
        # Draw messages
        y_offset = 10
        for msg in self.messages:
            # Draw category icon/color
            category_color = category_colors.get(msg['category'], WHITE)
            category_text = font_small.render(f"[{msg['category'][:1]}]", True, category_color)
            surface.blit(category_text, (x + 10, y + y_offset))
            
            # Draw message text with alpha
            message_text = font_small.render(msg['text'][:60], True, WHITE)
            # Note: pygame doesn't support alpha in fonts easily, so we'll just draw normally
            surface.blit(message_text, (x + 40, y + y_offset))
            
            y_offset += 30


class TooltipSystem:
    """Manages hover detection and tooltip rendering"""
    def __init__(self):
        self.hovered_entity = None
        self.hovered_type = None
    
    def detect_hover(self, mouse_world_x, mouse_world_y, camera, praxans, buildings, resources, encounters, hazards, npcs, world_map):
        """Detect which entity the mouse is hovering over"""
        self.hovered_entity = None
        self.hovered_type = None
        
        # Check entities in priority order
        # Check praxans
        for praxan in praxans:
            distance = math.sqrt((mouse_world_x - praxan.x)**2 + (mouse_world_y - praxan.y)**2)
            threshold = PRAXAN_RADIUS * camera.zoom
            if distance < threshold:
                self.hovered_entity = praxan
                self.hovered_type = 'praxan'
                return
        
        # Check buildings
        for building in buildings:
            distance = math.sqrt((mouse_world_x - building.x)**2 + (mouse_world_y - building.y)**2)
            threshold = BUILDING_SIZE * camera.zoom
            if distance < threshold:
                self.hovered_entity = building
                self.hovered_type = 'building'
                return
        
        # Check resources
        for resource in resources:
            if not resource.collected:
                distance = math.sqrt((mouse_world_x - resource.x)**2 + (mouse_world_y - resource.y)**2)
                if resource.resource_type == 'food':
                    threshold = RESOURCE_RADIUS_FOOD * camera.zoom
                elif resource.resource_type == 'stone':
                    threshold = RESOURCE_RADIUS_STONE * camera.zoom
                else:
                    threshold = RESOURCE_RADIUS_WOOD * camera.zoom
                if distance < threshold:
                    self.hovered_entity = resource
                    self.hovered_type = 'resource'
                    return
        
        # Check encounters
        for encounter in encounters:
            if encounter.discovered:
                distance = math.sqrt((mouse_world_x - encounter.x)**2 + (mouse_world_y - encounter.y)**2)
                threshold = 30 * camera.zoom
                if distance < threshold:
                    self.hovered_entity = encounter
                    self.hovered_type = 'encounter'
                    return
        
        # Check hazards
        for hazard in hazards:
            if hazard.active:
                distance = math.sqrt((mouse_world_x - hazard.x)**2 + (mouse_world_y - hazard.y)**2)
                if distance < hazard.radius:
                    self.hovered_entity = hazard
                    self.hovered_type = 'hazard'
                    return
        
        # Check NPCs
        for npc in npcs:
            if npc.visible:
                distance = math.sqrt((mouse_world_x - npc.x)**2 + (mouse_world_y - npc.y)**2)
                threshold = 25 * camera.zoom
                if distance < threshold:
                    self.hovered_entity = npc
                    self.hovered_type = 'npc'
                    return
    
    def draw_tooltip(self, surface, mouse_screen_x, mouse_screen_y, faction_manager=None):
        """Draw tooltip for hovered entity with enhanced information"""
        if not self.hovered_entity:
            return
        
        # Build tooltip text based on entity type
        lines = []
        line_colors = []  # Track colors for each line
        
        if self.hovered_type == 'praxan':
            praxan = self.hovered_entity
            lines.append(f"Praxan #{praxan.id}")
            line_colors.append(WHITE)
            
            if praxan.role:
                lines.append(f"Role: {praxan.role.title()}")
                line_colors.append((200, 200, 255))
            
            # Health with color coding
            health_val = int(praxan.health)
            health_color = (100, 255, 100) if health_val > 70 else (255, 200, 100) if health_val > 40 else (255, 100, 100)
            lines.append(f"Health: {health_val}/100")
            line_colors.append(health_color)
            
            # Needs with color coding
            hunger_val = int(praxan.needs['hunger'])
            hunger_color = (100, 255, 100) if hunger_val > 50 else (255, 100, 100)
            lines.append(f"Hunger: {hunger_val}/100")
            line_colors.append(hunger_color)
            
            energy_val = int(praxan.needs['energy'])
            energy_color = (100, 255, 100) if energy_val > 50 else (255, 100, 100)
            lines.append(f"Energy: {energy_val}/100")
            line_colors.append(energy_color)
            
            # Happiness
            if hasattr(praxan, 'happiness'):
                happiness_val = int(praxan.happiness)
                happiness_color = (100, 255, 100) if happiness_val > 70 else (255, 200, 100) if happiness_val > 40 else (255, 100, 100)
                lines.append(f"Happiness: {happiness_val}/100")
                line_colors.append(happiness_color)

            lines.append(f"Generation: {getattr(praxan, 'generation', 0)}  Lineage: L{getattr(praxan, 'lineage_id', praxan.id)}")
            line_colors.append((255, 220, 150))
            if getattr(praxan, "parent_ids", None):
                parent_text = ",".join(str(parent_id) for parent_id in praxan.parent_ids[:2])
                lines.append(f"Parents: {parent_text}")
                line_colors.append((180, 180, 205))
            
            # Faction membership
            if hasattr(praxan, 'faction_id') and praxan.faction_id is not None:
                lines.append(f"Faction: {praxan.faction_id}")
                line_colors.append((200, 100, 255))
                if faction_manager and hasattr(faction_manager, 'factions'):
                    faction = faction_manager.get_faction(praxan.faction_id)
                    if faction:
                        lines.append(
                            f"Doctrine: {faction.primary_doctrine.title()}  Cohesion: {int(faction.cohesion)}  Schism: {int(faction.schism_pressure)}"
                        )
                        line_colors.append((220, 190, 255))
            elif faction_manager and hasattr(faction_manager, 'factions'):
                # Check if praxan is in any faction
                for fid, faction in faction_manager.factions.items():
                    if praxan.id in faction.member_ids:
                        lines.append(f"Faction: {fid}")
                        line_colors.append((200, 100, 255))
                        lines.append(
                            f"Doctrine: {faction.primary_doctrine.title()}  Cohesion: {int(faction.cohesion)}  Schism: {int(faction.schism_pressure)}"
                        )
                        line_colors.append((220, 190, 255))
                        break
            
            # Skills and bonuses
            skill_key = get_role_skill_key(praxan.role)
            if skill_key and skill_key in praxan.skills:
                skill_level = praxan.skills[skill_key]['level']
                lines.append(f"Skill Level: {skill_level}")
                line_colors.append((255, 215, 0))
                if praxan.role == 'gatherer':
                    bonus = (skill_level - 1) * 10
                    lines.append(f"Gather Bonus: +{bonus}%")
                    line_colors.append((100, 255, 100))
                elif praxan.role == 'builder':
                    bonus = (skill_level - 1) * 10
                    lines.append(f"Build Efficiency: +{bonus}%")
                    line_colors.append((100, 255, 100))
                elif praxan.role == 'explorer':
                    bonus = (skill_level - 1) * 15
                    lines.append(f"Visibility: +{bonus}%")
                    line_colors.append((100, 255, 100))
            
            # Q-learning stats
            if hasattr(praxan, 'q_table'):
                q_entries = len(praxan.q_table)
                if q_entries > 0:
                    lines.append(f"Learned Actions: {q_entries}")
                    line_colors.append((150, 200, 255))
            
            # State
            if hasattr(praxan, 'current_state'):
                state_name = praxan.current_state.replace('STATE_', '').replace('_', ' ').title()
                lines.append(f"State: {state_name}")
                line_colors.append((200, 200, 200))
            
            # Current action
            if hasattr(praxan, 'current_action') and praxan.current_action:
                lines.append(f"Task: {praxan.current_action}")
                line_colors.append((255, 255, 200))
            trait_drift_name = max(
                GENETIC_TRAIT_SPECS,
                key=lambda trait_name: abs(getattr(praxan, "genetics", {}).get(trait_name, 1.0) - 1.0),
            )
            trait_label = GENETIC_TRAIT_SPECS[trait_drift_name]["label"]
            trait_delta = format_genetic_trait_delta(getattr(praxan, "genetics", {}).get(trait_drift_name, 1.0))
            lines.append(f"{trait_label}: {trait_delta}")
            line_colors.append((150, 220, 255))
        elif self.hovered_type == 'building':
            building = self.hovered_entity
            lines.append(f"{building.building_type.title()}")
            line_colors.append(WHITE)
            if building.building_type == 'house':
                if building.occupants:
                    lines.append(f"Occupants: {len(building.occupants)}/2")
                    line_colors.append((200, 200, 255))
                lines.append(f"Built by: Praxan #{building.built_by}" if hasattr(building, 'built_by') and building.built_by is not None else "Built by: Unknown")
                line_colors.append((150, 150, 150))
            if building.stored_resources:
                stored = building.stored_resources
                if sum(stored.values()) > 0:
                    stored_str = ", ".join([f"{k}:{int(v)}" for k, v in stored.items() if v > 0])
                    if stored_str:
                        lines.append(f"Stored: {stored_str}")
                        line_colors.append((255, 255, 100))
        elif self.hovered_type == 'resource':
            resource = self.hovered_entity
            lines.append(f"{resource.resource_type.title()} Resource")
            line_colors.append(WHITE)
            if resource.collected:
                if hasattr(resource, 'collect_time'):
                    respawn_time = RESOURCE_RESPAWN_TIME - (time.time() - resource.collect_time)
                    if respawn_time > 0:
                        lines.append(f"Respawns in: {int(respawn_time)}s")
                        line_colors.append((255, 200, 100))
                    else:
                        lines.append("Respawned")
                        line_colors.append((100, 255, 100))
                else:
                    lines.append("Respawning...")
                    line_colors.append((255, 200, 100))
            else:
                lines.append("Available")
                line_colors.append((100, 255, 100))
        elif self.hovered_type == 'encounter':
            encounter = self.hovered_entity
            encounter_names = {
                'ruins': 'Ancient Ruins',
                'mineral_vein': 'Mineral Vein',
                'oasis': 'Oasis',
                'sacred_grove': 'Sacred Grove'
            }
            lines.append(encounter_names.get(encounter.encounter_type, 'Unknown'))
            line_colors.append(WHITE)
            lines.append("Discovered" if hasattr(encounter, 'discovered') and encounter.discovered else "Unexplored")
            line_colors.append((100, 255, 100) if hasattr(encounter, 'discovered') and encounter.discovered else (255, 200, 100))
        elif self.hovered_type == 'hazard':
            hazard = self.hovered_entity
            hazard_names = {
                'quicksand': 'Quicksand',
                'avalanche_zone': 'Avalanche Zone',
                'flood_zone': 'Flood Zone',
                'predator_lair': 'Predator Lair'
            }
            lines.append(hazard_names.get(hazard.hazard_type, 'Hazard'))
            line_colors.append((255, 100, 100))
            lines.append(f"Radius: {hazard.radius}m")
            line_colors.append((255, 150, 150))
            if hasattr(hazard, 'active') and hazard.active:
                lines.append("ACTIVE")
                line_colors.append((255, 50, 50))
        elif self.hovered_type == 'npc':
            npc = self.hovered_entity
            npc_names = {
                'trader': 'Trader',
                'rival_tribe': 'Rival Tribe',
                'wildlife_herd': 'Wildlife Herd'
            }
            lines.append(npc_names.get(npc.npc_type, 'NPC'))
            line_colors.append(WHITE)
            if hasattr(npc, 'hostile') and npc.hostile:
                lines.append("HOSTILE!")
                line_colors.append((255, 50, 50))
        
        # Calculate tooltip size (increased max width)
        max_width = 0
        for line in lines:
            width = font_small.size(line)[0]
            max_width = max(max_width, width)
        
        tooltip_width = min(max_width + 20, 350)  # Cap at 350px
        tooltip_height = len(lines) * 25 + 10
        
        # Position tooltip near mouse (offset to avoid cursor)
        tooltip_x = mouse_screen_x + 20
        tooltip_y = mouse_screen_y - tooltip_height
        
        # Keep on screen
        if tooltip_x + tooltip_width > WINDOW_WIDTH:
            tooltip_x = mouse_screen_x - tooltip_width - 10
        if tooltip_y < 0:
            tooltip_y = mouse_screen_y + 20
        
        # Draw tooltip background
        tooltip_surface = pygame.Surface((tooltip_width, tooltip_height))
        tooltip_surface.set_alpha(240)
        tooltip_surface.fill((20, 20, 30))
        surface.blit(tooltip_surface, (int(tooltip_x), int(tooltip_y)))
        pygame.draw.rect(surface, (100, 150, 200), (int(tooltip_x), int(tooltip_y), tooltip_width, tooltip_height), 2)
        
        # Draw tooltip text with color coding
        y_offset = 5
        for i, line in enumerate(lines):
            color = line_colors[i] if i < len(line_colors) else WHITE
            text = font_small.render(line, True, color)
            surface.blit(text, (int(tooltip_x + 10), int(tooltip_y + y_offset)))
            y_offset += 25


class SelectionManager:
    """Manages entity selection and highlighting"""
    def __init__(self):
        self.selected_entity = None
        self.selected_type = None
    
    def select(self, entity, entity_type):
        """Select an entity"""
        self.selected_entity = entity
        self.selected_type = entity_type
    
    def deselect(self):
        """Deselect current entity"""
        self.selected_entity = None
        self.selected_type = None
    
    def is_selected(self, entity):
        """Check if entity is selected"""
        return self.selected_entity == entity
    
    def draw_highlight(self, surface, entity, entity_type):
        """Draw highlight effect for selected entity"""
        if not self.is_selected(entity):
            return
        
        # Use world coordinates for the entity (already transformed to screen)
        if entity_type == 'praxan':
            # Yellow glow
            glow_surface = pygame.Surface((PRAXAN_RADIUS * 2 + 8, PRAXAN_RADIUS * 2 + 8), pygame.SRCALPHA)
            pygame.draw.circle(glow_surface, (*YELLOW, 150), (PRAXAN_RADIUS + 4, PRAXAN_RADIUS + 4), PRAXAN_RADIUS + 4)
            surface.blit(glow_surface, (int(entity.x - PRAXAN_RADIUS - 4), int(entity.y - PRAXAN_RADIUS - 4)))
        elif entity_type == 'building':
            # Cyan outline
            size = BUILDING_SIZE
            rect = pygame.Rect(int(entity.x - size//2 - 3), int(entity.y - size//2 - 3), size + 6, size + 6)
            pygame.draw.rect(surface, CYAN, rect, 3)
        elif entity_type == 'resource':
            # White glow
            if entity.resource_type == 'food':
                radius = RESOURCE_RADIUS_FOOD
            elif entity.resource_type == 'stone':
                radius = RESOURCE_RADIUS_STONE
            else:
                radius = RESOURCE_RADIUS_WOOD
            glow_surface = pygame.Surface((radius * 2 + 6, radius * 2 + 6), pygame.SRCALPHA)
            pygame.draw.circle(glow_surface, (*WHITE, 150), (radius + 3, radius + 3), radius + 3)
            surface.blit(glow_surface, (int(entity.x - radius - 3), int(entity.y - radius - 3)))
        elif entity_type in ['encounter', 'hazard', 'npc']:
            # White outline
            if entity_type == 'encounter':
                size = 20
            elif entity_type == 'hazard':
                size = entity.radius
            else:
                size = 25
            pygame.draw.circle(surface, WHITE, (int(entity.x), int(entity.y)), size, 2)


class WorkPriorityPanel:
    """RimWorld-style manual priority grid for praxans."""
    def __init__(self, ui_theme):
        self.theme = ui_theme
        self.rect = pygame.Rect(100, 100, 800, 500)
        self.scroll_y = 0
        self.row_height = 40
        self.col_width = 100
        self.headers = ["Pawn", "Gathering", "Building", "Exploring", "Hauling", "Researching"]

    def draw(self, surface, praxans, ui_registry):
        if not praxans: return
        
        # Draw background panel
        draw_panel(surface, self.rect, self.theme, fill=(25, 30, 32), alpha=245, radius=self.theme.radius_large)
        
        # Draw Headers
        header_y = self.rect.y + 15
        for i, header in enumerate(self.headers):
            text = self.theme.fonts.label.render(header, True, self.theme.palette.parchment)
            x = self.rect.x + 20 + i * self.col_width
            surface.blit(text, (x, header_y))
        
        # Draw Pawn Rows
        content_rect = self.rect.inflate(-40, -80)
        content_rect.y += 40
        
        y = content_rect.y
        for praxan in praxans:
            if y + self.row_height > self.rect.bottom - 20: break
            
            # Pawn Name/ID
            name_text = self.theme.fonts.caption.render(f"P#{praxan.id}", True, WHITE)
            surface.blit(name_text, (self.rect.x + 20, y + 10))
            
            # Priority Boxes
            for i, work_type in enumerate(WORK_TYPES):
                box_x = self.rect.x + 20 + (i + 1) * self.col_width
                box_rect = pygame.Rect(box_x, y + 5, 30, 30)
                
                priority = praxan.work_priorities.get(work_type, 3)
                priority_text = self.theme.fonts.label.render(str(priority), True, GOLD if priority < 3 else (200, 200, 200))
                
                # Register hit area
                ui_registry.register(f"cycle_priority:{praxan.id}:{work_type}", box_rect, action="cycle_priority", payload={"pawn_id": praxan.id, "work_type": work_type}, layer=10)
                
                # Draw box
                pygame.draw.rect(surface, (40, 45, 47), box_rect, border_radius=4)
                pygame.draw.rect(surface, self.theme.palette.slate, box_rect, 1, border_radius=4)
                
                # Center text in box
                tw, th = priority_text.get_size()
                surface.blit(priority_text, (box_rect.x + (30-tw)//2, box_rect.y + (30-th)//2))
                
            y += self.row_height

















class SchedulePanel:
    """RimWorld-style daily schedule grid for praxans."""
    def __init__(self, ui_theme):
        self.theme = ui_theme
        self.rect = pygame.Rect(50, 100, 1260, 500)
        self.row_height = 40
        self.col_width = 45 # for 24 hours
        self.categories = ["Anything", "Work", "Sleep"]
        self.colors = {
            "Anything": (100, 100, 100),
            "Work": (120, 60, 120),
            "Sleep": (60, 60, 180)
        }
        self.selected_category = "Anything"

    def draw(self, surface, praxans, registry, game_hour):
        # Draw panel background
        draw_panel(surface, self.rect, self.theme, fill=(25, 30, 35), alpha=245, radius=10)
        
        # Draw title
        title = self.theme.fonts.heading.render("DAILY SCHEDULE", True, self.theme.palette.parchment)
        surface.blit(title, (self.rect.x + 20, self.rect.y + 15))
        
        # Draw Current Time helper
        time_text = self.theme.fonts.label.render(f"Current Hour: {game_hour}:00", True, self.theme.palette.frost)
        surface.blit(time_text, (self.rect.centerx - time_text.get_width()//2, self.rect.y + 15))
        
        # Draw category selector (paint tool)
        cx = self.rect.x + 20
        cy = self.rect.y + 55
        for cat in self.categories:
            cat_rect = pygame.Rect(cx, cy, 100, 30)
            active = (self.selected_category == cat)
            draw_panel(surface, cat_rect, self.theme, fill=self.colors[cat] if active else (40, 45, 50), alpha=255)
            registry.register(f"select_schedule_cat:{cat}", cat_rect, action="select_schedule_cat", payload=cat, layer=10)
            txt = self.theme.fonts.caption.render(cat, True, (255, 255, 255))
            surface.blit(txt, (cat_rect.centerx - txt.get_width()//2, cat_rect.centery - txt.get_height()//2))
            cx += 110

        # Draw Hours Header
        hx = self.rect.x + 150
        hy = self.rect.y + 95
        for h in range(24):
            # Highlight current hour
            is_now = (h == game_hour)
            color = self.theme.palette.frost if is_now else self.theme.palette.muted_text
            h_text = self.theme.fonts.caption.render(str(h), True, color)
            surface.blit(h_text, (hx + (self.col_width // 2) - h_text.get_width()//2, hy))
            hx += self.col_width

        # Draw rows
        ry = self.rect.y + 120
        for p in praxans[:10]: # Limit for UI visibility
            # Pawn name
            p_rect = pygame.Rect(self.rect.x + 20, ry, 120, self.row_height - 5)
            draw_panel(surface, p_rect, self.theme, fill=(45, 50, 55), alpha=230)
            p_name = self.theme.fonts.caption.render(f"P#{p.id}", True, self.theme.palette.parchment)
            surface.blit(p_name, (p_rect.x + 10, p_rect.y + 10))
            
            # 24 hour slots
            sx = self.rect.x + 150
            for h in range(24):
                slot_rect = pygame.Rect(sx, ry, self.col_width - 2, self.row_height - 5)
                cat = p.schedule[h]
                pygame.draw.rect(surface, self.colors.get(cat, (100,100,100)), slot_rect)
                if h == game_hour:
                    pygame.draw.rect(surface, (255, 255, 255), slot_rect, 2) # Highlight current
                
                registry.register(f"set_schedule:{p.id}:{h}", slot_rect, action="cycle_schedule", payload=(p.id, h), layer=10)
                sx += self.col_width
            
            ry += self.row_height

@dataclass
class RoomStats:
    id: int
    size: int = 0
    beauty: float = 0.0
    is_outdoors: bool = True
    tiles: set[tuple[int, int]] = field(default_factory=set)

    @property
    def impressiveness(self):
        """Room impressiveness score (0-100) combining beauty, space, and enclosure."""
        if self.is_outdoors:
            return 0.0
        size_score = min(30, self.size * 1.5)  # Caps at 20 tiles
        beauty_score = max(0, min(40, self.beauty * 2.0))
        enclosure_bonus = 20  # Bonus for being a proper enclosed room
        return min(100, size_score + beauty_score + enclosure_bonus)

def detect_room(start_x, start_y, world_width, world_height, buildings):
    """Flood-fill to detect a room from a starting tile coordinates."""
    # Convert pixels to tile coordinates
    tx, ty = int(start_x // TILE_SIZE), int(start_y // TILE_SIZE)
    
    # Track wall positions (tiles occupied by buildings that block passage)
    wall_tiles = set()
    for b in buildings:
        if b.building_type in ROOM_WALL_BUILDING_TYPES:
            wall_tiles.update(building_occupied_tiles(b.x, b.y, b.building_type, TILE_SIZE))

    if (tx, ty) in wall_tiles:
        return None # Can't start inside a wall

    # Flood fill
    q = [(tx, ty)]
    room_tiles = {(tx, ty)}
    is_outdoors = False
    
    max_room_tiles = 400 # Safety limit for "indoors"
    
    # Grid dimensions in tiles
    w_tiles = world_width // TILE_SIZE
    h_tiles = world_height // TILE_SIZE

    while q:
        cx, cy = q.pop(0)
        
        # Check if we hit map edge
        if cx <= 0 or cy <= 0 or cx >= w_tiles - 1 or cy >= h_tiles - 1:
            is_outdoors = True
            # We don't break immediately if we want to find the full "outdoor" area, 
            # but for performance we limit it.
            if len(room_tiles) > max_room_tiles: break
            
        for dx, dy in [(0,1), (0,-1), (1,0), (-1,0)]:
            nx, ny = cx + dx, cy + dy
            if (nx, ny) not in room_tiles and (nx, ny) not in wall_tiles:
                if 0 <= nx < w_tiles and 0 <= ny < h_tiles:
                    room_tiles.add((nx, ny))
                    q.append((nx, ny))
                    if len(room_tiles) > max_room_tiles:
                        is_outdoors = True
                        q = [] # Stop fill
                        break
    
    # Calculate beauty
    beauty = 0.0
    for b in buildings:
        occupied_tiles = set(building_occupied_tiles(b.x, b.y, b.building_type, TILE_SIZE))
        if occupied_tiles & room_tiles:
            beauty += BUILDING_DEFINITIONS.get(b.building_type, {}).get('beauty', 0)
            
    return RoomStats(
        id=random.randint(1000, 9999), 
        size=len(room_tiles), 
        beauty=beauty, 
        is_outdoors=is_outdoors, 
        tiles=room_tiles
    )

def update_rooms(rooms, buildings, world_width, world_height):
    """Update the global list of rooms based on building positions."""
    rooms.clear()
    visited_tiles = set()
    
    # Grid dimensions in tiles
    w_tiles = world_width // TILE_SIZE
    h_tiles = world_height // TILE_SIZE
    wall_tiles = set()
    for building in buildings:
        if building.building_type in ROOM_WALL_BUILDING_TYPES:
            wall_tiles.update(building_occupied_tiles(building.x, building.y, building.building_type, TILE_SIZE))

    for b in buildings:
        # Check adjacent tiles of wall-buildings for potential rooms
        if b.building_type in ROOM_WALL_BUILDING_TYPES:
            for wall_tx, wall_ty in building_occupied_tiles(b.x, b.y, b.building_type, TILE_SIZE):
                for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    nx_tile = wall_tx + dx
                    ny_tile = wall_ty + dy
                    nx = nx_tile * TILE_SIZE
                    ny = ny_tile * TILE_SIZE
                    if nx < 0 or ny < 0 or nx >= world_width or ny >= world_height:
                        continue

                    tile_coords = (nx_tile, ny_tile)
                    if tile_coords in visited_tiles or tile_coords in wall_tiles:
                        continue

                    room = detect_room(nx, ny, world_width, world_height, buildings)
                    if room:
                        rooms.append(room)
                        visited_tiles.update(room.tiles)

class ParticleSystem:
    """Manages particle effects for visual feedback"""
    def __init__(self):
        self.particles = []
    
    def create_particles(self, x, y, particle_type='sparkle', count=5):
        """Create a burst of particles at a location"""
        for _ in range(count):
            if particle_type == 'sparkle':
                # Yellow sparkles for food collection - using palette
                self.particles.append({
                    'x': x, 'y': y,
                    'vx': random.uniform(-2, 2),
                    'vy': random.uniform(-3, -1),
                    'life': 20, 'max_life': 20,
                    'color': YELLOW
                })
            elif particle_type == 'dust':
                # Brown dust for wood gathering - using palette
                self.particles.append({
                    'x': x, 'y': y,
                    'vx': random.uniform(-2, 2),
                    'vy': random.uniform(-2, 0),
                    'life': 15, 'max_life': 15,
                    'color': DIRT_MID
                })
            elif particle_type == 'build':
                # Orange sparks for building - using palette
                self.particles.append({
                    'x': x, 'y': y,
                    'vx': random.uniform(-3, 3),
                    'vy': random.uniform(-3, 0),
                    'life': 25, 'max_life': 25,
                    'color': GOLD
                })
            elif particle_type == 'heart':
                # Floating hearts for reproduction - using palette
                self.particles.append({
                    'x': x, 'y': y,
                    'vx': random.uniform(-1, 1),
                    'vy': random.uniform(-3, -1),
                    'life': 40, 'max_life': 40,
                    'color': RED
                })
            elif particle_type == 'death':
                # Dark particles for death - using palette
                self.particles.append({
                    'x': x, 'y': y,
                    'vx': random.uniform(-2, 2),
                    'vy': random.uniform(-2, 0),
                    'life': 30, 'max_life': 30,
                    'color': ROCK_DARK
                })
            elif particle_type == 'knowledge':
                # Light blue particles for knowledge sharing - using palette
                self.particles.append({
                    'x': x, 'y': y,
                    'vx': random.uniform(-1, 1),
                    'vy': random.uniform(-2, 0),
                    'life': 20, 'max_life': 20,
                    'color': CYAN
                })
            elif particle_type == 'confetti':
                self.particles.append({
                    'x': x, 'y': y,
                    'vx': random.uniform(-2.5, 2.5),
                    'vy': random.uniform(-3.0, -0.5),
                    'life': 26, 'max_life': 26,
                    'color': random.choice([GOLD, CYAN, RED, GRASS_LIGHT, EXPLORER_COLOR]),
                    'shape': 'square',
                })
    
    def update(self):
        """Update all particles"""
        for particle in self.particles[:]:  # Copy list for safe iteration
            particle['x'] += particle['vx']
            particle['y'] += particle['vy']
            particle['life'] -= 1
            
            if particle['life'] <= 0:
                self.particles.remove(particle)
    
    def draw(self, surface):
        """Draw all particles"""
        for particle in self.particles:
            alpha = int(255 * (particle['life'] / particle['max_life']))
            color = particle['color']
            size = int(3 * (particle['life'] / particle['max_life']) + 1)
            particle_surface = pygame.Surface((size * 4, size * 4), pygame.SRCALPHA)
            if particle.get('shape') == 'square':
                pygame.draw.rect(
                    particle_surface,
                    (*color, alpha),
                    (size, size, size * 2, size * 2),
                )
            else:
                pygame.draw.circle(
                    particle_surface,
                    (*color, alpha),
                    (size * 2, size * 2),
                    max(1, size),
                )
            surface.blit(particle_surface, (int(particle['x'] - size * 2), int(particle['y'] - size * 2)))


class GroupTask:
    """Represents a communal task that requires coordination between multiple praxans"""
    def __init__(self, task_type, description, required_count=1, target_location=None, target_building_type=None):
        self.task_type = task_type  # 'build', 'gather', 'explore', etc.
        self.description = description
        self.required_count = required_count
        self.assigned_praxans = []  # List of praxan IDs
        self.target_location = target_location  # (x, y) for coordinated gathering/building
        self.target_building_type = target_building_type  # For building tasks
        self.created_time = time.time()
        self.active = True
        self.faction_id = None  # Optional: faction this task belongs to
    
    def is_complete(self):
        """Check if task has required number of praxans assigned"""
        return len(self.assigned_praxans) >= self.required_count
    
    def add_praxan(self, praxan_id):
        """Assign a praxan to this task"""
        if praxan_id not in self.assigned_praxans:
            self.assigned_praxans.append(praxan_id)
    
    def remove_praxan(self, praxan_id):
        """Remove a praxan from this task"""
        if praxan_id in self.assigned_praxans:
            self.assigned_praxans.remove(praxan_id)










class GameModifiers:
    """Tracks and applies dynamic game modifications"""
    def __init__(self):
        self.permanent = {}  # Permanent modifiers from tech
        self.temporary = {}  # Temporary from abilities: {name: (multiplier, end_time)}
        self.tech_unlocked = set()
        
    def get_modifier(self, mechanic_name):
        """Get combined modifier (permanent * temporary)"""
        perm = self.permanent.get(mechanic_name, 1.0)
        temp = 1.0
        if mechanic_name in self.temporary:
            entry = self.temporary[mechanic_name]
            # Check if it's a tuple (multiplier, end_time) or just a count integer
            if isinstance(entry, tuple):
                mult, end_time = entry
                if time.time() < end_time:
                    temp = mult
                else:
                    del self.temporary[mechanic_name]
        return perm * temp


class BehaviorTreeNode:
    """Base node for behavior tree"""
    def __init__(self, node_type, name, children=None, condition_func=None, action_func=None):
        self.node_type = node_type
        self.name = name
        self.children = children or []
        self.condition_func = condition_func
        self.action_func = action_func
        self.last_result = None  # Cache last result
    
    def tick(self, praxan, context):
        """Execute this node and return result (SUCCESS, FAILURE, RUNNING)"""
        if self.node_type == BT_NODE_SELECTOR:
            # Selector: Returns SUCCESS if any child succeeds, FAILURE if all fail
            for child in self.children:
                result = child.tick(praxan, context)
                if result == 'SUCCESS':
                    return 'SUCCESS'
            return 'FAILURE'
        
        elif self.node_type == BT_NODE_SEQUENCE:
            # Sequence: Returns FAILURE if any child fails, SUCCESS if all succeed
            for child in self.children:
                result = child.tick(praxan, context)
                if result == 'FAILURE':
                    return 'FAILURE'
                if result == 'RUNNING':
                    return 'RUNNING'
            return 'SUCCESS'
        
        elif self.node_type == BT_NODE_CONDITION:
            # Condition: Returns SUCCESS if condition is true
            if self.condition_func:
                if self.condition_func(praxan, context):
                    return 'SUCCESS'
            return 'FAILURE'
        
        elif self.node_type == BT_NODE_ACTION:
            # Action: Executes action and returns result
            if self.action_func:
                return self.action_func(praxan, context)
            return 'FAILURE'
        
        return 'FAILURE'


class BehaviorTree:
    """Behavior tree for praxan decision making - hybrid with FSM"""
    def __init__(self, praxan):
        self.praxan = praxan
        self.root = None
        self.last_successful_path = []  # Cache last successful path
        self.max_depth = 5
        self._build_tree()
    
    def _build_tree(self):
        """Build the behavior tree structure"""
        # 1. Survival Check (Absolute Priority)
        survival_check = BehaviorTreeNode(
            BT_NODE_CONDITION,
            'survival_check',
            condition_func=lambda t, ctx: (
                t.needs['hunger'] < 30 or 
                t.needs['energy'] < 30 or 
                t.needs['thirst'] < 40
            )
        )
        survival_action = BehaviorTreeNode(
            BT_NODE_ACTION,
            'seek_need',
            action_func=lambda t, ctx: self._transition_to_state(t, 'STATE_SEEK_NEED')
        )
        survival_node = BehaviorTreeNode(
            BT_NODE_SEQUENCE,
            'survival_priority',
            children=[survival_check, survival_action]
        )
        
        # 1.5 Schedule-based Rest (High Priority during Sleep hours)
        is_sleep_hour = BehaviorTreeNode(
            BT_NODE_CONDITION,
            'is_sleep_hour',
            condition_func=lambda t, ctx: (
                t.schedule[ctx.get('game_hour', 0)] == "Sleep" and 
                t.needs['energy'] < 90
            )
        )
        sleep_action = BehaviorTreeNode(
            BT_NODE_ACTION,
            'go_to_sleep',
            action_func=lambda t, ctx: self._transition_to_state(t, 'STATE_REST')
        )
        schedule_rest_node = BehaviorTreeNode(
            BT_NODE_SEQUENCE,
            'scheduled_rest',
            children=[is_sleep_hour, sleep_action]
        )
        
        # 2. Manual Directive Override (Player Command)
        has_directives = BehaviorTreeNode(
            BT_NODE_CONDITION,
            'has_directives',
            condition_func=lambda t, ctx: (
                ctx.get('directives') and 
                len(ctx['directives']) > 0
            )
        )
        directive_action = BehaviorTreeNode(
            BT_NODE_ACTION,
            'execute_directive',
            action_func=lambda t, ctx: self._transition_to_state(t, 'STATE_EXECUTE_DIRECTIVE')
        )
        directive_node = BehaviorTreeNode(
            BT_NODE_SEQUENCE,
            'manual_directive',
            children=[has_directives, directive_action]
        )
        
        # 3. Work Priority Node (RimWorld-style)
        def work_decision(t, ctx):
            # Sort WORK_TYPES by priority (1: High, 4: Low, 0: Disabled)
            if not hasattr(t, 'work_priorities'):
                return 'FAILURE'
                
            prioritized_work = sorted(
                [w for w in t.work_priorities if t.work_priorities[w] > 0],
                key=lambda w: t.work_priorities[w]
            )
            
            for work in prioritized_work:
                if work == 'Medical':
                    # Find someone needing medical attention
                    praxans = ctx.get('other_praxans', [])
                    for patient in praxans:
                        # Cannot tend dead people or healthy people
                        if getattr(patient, 'health', 0) <= 0 or not hasattr(patient, 'hediffs'):
                            continue
                        
                        # Find untended hediffs that need tending (wounds/bleeding/infection)
                        needs_tending = any(h.get('tended') is False for h in patient.hediffs if h['type'] in ['wound', 'bleeding', 'infection'])
                        
                        if needs_tending:
                            # 1. Provide target interaction logic
                            dist = math.sqrt((t.x - patient.x)**2 + (t.y - patient.y)**2)
                            if dist < 30:
                                # Close enough to tend
                                patient.tend_wound(t)
                                t.action_duration = 3.0 # Tending takes time
                                t.current_action = "tending"
                                return 'SUCCESS' # Just do the action
                            else:
                                # Too far, move towards patient
                                dx = patient.x - t.x
                                dy = patient.y - t.y
                                length = math.sqrt(dx**2 + dy**2)
                                if length > 0:
                                    t.x += (dx/length) * t.speed * 0.5 # Slower when moving with purpose
                                    t.y += (dy/length) * t.speed * 0.5
                                t.current_action = "seeking_patient"
                                return 'SUCCESS'
                elif work in ('Crafting', 'Cooking'):
                    buildings = ctx.get('buildings', [])
                    for b in buildings:
                        if not hasattr(b, 'bills') or not b.bills:
                            continue
                        
                        # Get the first bill
                        bill_id = b.bills[0]
                        if bill_id not in JOB_DEFS:
                            continue
                            
                        job_def = JOB_DEFS[bill_id]
                        if job_def.get('work_type') != work:
                            continue
                            
                        # Does building match station requirement?
                        if job_def.get('station') != b.building_type:
                            continue
                            
                        # Check ingredients in the building's stored_resources
                        can_craft = True
                        for ing in job_def.get('ingredients', []):
                            available = b.stored_resources.get(ing['type'], 0)
                            if available < ing['amount']:
                                can_craft = False
                                break
                        
                        if can_craft:
                            dist = math.sqrt((t.x - b.x)**2 + (t.y - b.y)**2)
                            if dist < 40:
                                t.current_action = f"crafting_{bill_id}"
                                t.action_duration = job_def.get('base_work', 400) / 100.0  # Scale down to seconds
                                # The actual production needs to happen at the END of the duration or inside praxan state machine
                                # For BT, we trigger the state transition
                                t.target_building = b
                                t.current_bill = bill_id
                                return self._transition_to_state(t, 'STATE_CRAFT')
                            else:
                                dx = b.x - t.x
                                dy = b.y - t.y
                                length = math.sqrt(dx**2 + dy**2)
                                if length > 0:
                                    t.x += (dx/length) * t.speed
                                    t.y += (dy/length) * t.speed
                                t.current_action = "going_to_craft"
                                return 'SUCCESS'
                elif work == 'Gathering':
                    if ctx.get('resources') and any(not r.collected for r in ctx['resources']):
                        return self._transition_to_state(t, 'STATE_GATHER')
                elif work == 'Building':
                    if ctx.get('buildings'): # Simple check for now
                        return self._transition_to_state(t, 'STATE_BUILD')
                elif work == 'Hauling':
                    if ctx.get('resources') and any(not r.collected for r in ctx['resources']):
                        return self._transition_to_state(t, 'STATE_HAUL')
                elif work == 'Exploring':
                    return self._transition_to_state(t, 'STATE_EXPLORE')
            return 'FAILURE'

        work_node = BehaviorTreeNode(
            BT_NODE_ACTION,
            'work_priority_logic',
            action_func=work_decision
        )
        
        # 4. Socialization & Leisure
        can_socialize = BehaviorTreeNode(
            BT_NODE_CONDITION,
            'can_socialize',
            condition_func=lambda t, ctx: (
                t.personality.get('sociability', 0) > 0.7 and 
                len(t.bonds) < 3 and
                t.needs['hunger'] > 70 and 
                t.needs['energy'] > 50
            )
        )
        socialize_action = BehaviorTreeNode(
            BT_NODE_ACTION,
            'socialize',
            action_func=lambda t, ctx: self._transition_to_state(t, 'STATE_SOCIALIZE')
        )
        socialize_node = BehaviorTreeNode(
            BT_NODE_SEQUENCE,
            'socialization',
            children=[can_socialize, socialize_action]
        )
        
        # 5. Idle
        idle_action = BehaviorTreeNode(
            BT_NODE_ACTION,
            'idle',
            action_func=lambda t, ctx: self._transition_to_state(t, 'STATE_IDLE')
        )
        
        # Root selector
        self.root = BehaviorTreeNode(
            BT_NODE_SELECTOR,
            'root',
            children=[survival_node, schedule_rest_node, directive_node, work_node, socialize_node, idle_action]
        )
    
    def _transition_to_state(self, praxan, state_name):
        """Helper to transition FSM state"""
        # Map string to actual state constants
        state_map = {
            'STATE_SEEK_NEED': STATE_SEEK_NEED,
            'STATE_EXECUTE_DIRECTIVE': STATE_EXECUTE_DIRECTIVE,
            'STATE_SOCIALIZE': STATE_SOCIALIZE,
            'STATE_IDLE': STATE_IDLE,
            'STATE_REST': STATE_REST,
            'STATE_HAUL': STATE_HAUL,
            'STATE_GATHER': STATE_GATHER,
            'STATE_BUILD': STATE_BUILD,
            'STATE_CRAFT': STATE_CRAFT,
            'STATE_EXPLORE': STATE_EXPLORE
        }
        if state_name in state_map:
            praxan.transition_to_state(state_map[state_name])
        return 'SUCCESS'
    
    def tick(self, context):
        """Execute behavior tree with given context"""
        if not self.root:
            return 'FAILURE'
        
        try:
            result = self.root.tick(self.praxan, context)
            
            # Cache successful path for performance
            if result == 'SUCCESS' and len(self.last_successful_path) < self.max_depth:
                # Track which nodes succeeded (simplified)
                pass
            
            return result
        except Exception as e:
            # Graceful degradation on error
            if VERBOSE_LOGGING:
                print(f"[BehaviorTree] Error in tick: {e}")
            return 'FAILURE'




class Encounter:
    """Special discovery events on the map"""
    def __init__(self, x, y, encounter_type):
        self.x = x
        self.y = y
        self.encounter_type = encounter_type  # 'ruins', 'mineral_vein', 'oasis', 'sacred_grove'
        self.explored = False
        self.discovered = False
        self.reward_given = False
        
    def draw(self, surface):
        """Draw the encounter marker"""
        if self.discovered and not self.explored:
            # Draw icon based on type
            icon_size = 20
            if self.encounter_type == 'ruins':
                color = (139, 69, 19)  # Brown
                pygame.draw.rect(surface, color, (self.x - icon_size//2, self.y - icon_size//2, icon_size, icon_size))
                pygame.draw.lines(surface, (100, 50, 0), False, 
                    [(self.x - icon_size//2, self.y + icon_size//2), 
                     (self.x - icon_size//3, self.y - icon_size//3), 
                     (self.x + icon_size//3, self.y - icon_size//3), 
                     (self.x + icon_size//2, self.y + icon_size//2)], 2)
            elif self.encounter_type == 'mineral_vein':
                color = (192, 192, 192)  # Silver
                pygame.draw.circle(surface, color, (int(self.x), int(self.y)), icon_size // 2)
                pygame.draw.lines(surface, (255, 255, 255), False, 
                    [(self.x - 5, self.y), (self.x, self.y - 5), 
                     (self.x + 5, self.y), (self.x, self.y + 5)], 2)
            elif self.encounter_type == 'oasis':
                color = (173, 216, 230)  # Light blue
                pygame.draw.circle(surface, color, (int(self.x), int(self.y)), icon_size // 2)
                pygame.draw.circle(surface, (135, 206, 250), (int(self.x), int(self.y)), icon_size // 3)
            elif self.encounter_type == 'sacred_grove':
                color = (34, 139, 34)  # Green
                pygame.draw.circle(surface, color, (int(self.x), int(self.y)), icon_size // 2)
                pygame.draw.lines(surface, (0, 255, 0), False, 
                    [(self.x, self.y - icon_size//3), 
                     (self.x - 3, self.y + icon_size//4), 
                     (self.x + 3, self.y + icon_size//4)], 2)
            
            # Pulsing effect
            pulse = int(3 * math.sin(time.time() * 3))
            pygame.draw.circle(surface, color, (int(self.x), int(self.y)), icon_size // 2 + pulse, 1)


class TerrainHazard:
    """Environmental hazards that affect praxans"""
    def __init__(self, x, y, hazard_type, radius=100, duration=None):
        self.x = x
        self.y = y
        self.hazard_type = hazard_type  # 'quicksand', 'avalanche_zone', 'flood_zone', 'predator_lair', 'wildfire', 'flash_flood'
        self.radius = radius
        self.duration = duration
        self.spawn_time = time.time()
        self.active = True
        self.damage_rate = 0.5  # Health loss per second
        
    def check_affect(self, praxan):
        """Check if praxan is in range and apply effects"""
        if not self.active:
            return
            
        if self.duration and (time.time() - self.spawn_time) > self.duration:
            self.active = False
            return
        
        distance = math.sqrt((self.x - praxan.x)**2 + (self.y - praxan.y)**2)
        if distance < self.radius:
            # Apply hazard effects
            if self.hazard_type == 'quicksand':
                # Slow movement
                praxan.needs['energy'] = max(0, praxan.needs['energy'] - 0.3)
            elif self.hazard_type == 'avalanche_zone':
                # Chance to take damage
                if random.random() < 0.1:
                    praxan.take_damage(20, 'burn')
            elif self.hazard_type == 'flood_zone':
                # Increase disease risk
                praxan.contract_disease(DISEASE_CHANCE_BASE * 10)
            elif self.hazard_type == 'predator_lair':
                # Chance of attack
                if random.random() < 0.15:
                    praxan.take_damage(30, 'crush')
            elif self.hazard_type == 'wildfire':
                if random.random() < 0.1:
                    praxan.take_damage(20, 'burn')
            elif self.hazard_type == 'flash_flood':
                praxan.needs['energy'] = max(0, praxan.needs['energy'] - 1.0)
                if random.random() < 0.05:
                    praxan.take_damage(10, 'crush')
    
    def draw(self, surface):
        """Draw hazard marker"""
        if self.active:
            # Pulsing warning circle
            pulse = int(5 + 3 * math.sin(time.time() * 4))
            
            hazard_colors = {
                'quicksand': (139, 90, 43),
                'avalanche_zone': (255, 255, 255),
                'flood_zone': (64, 164, 223),
                'predator_lair': (255, 0, 0),
                'wildfire': (255, 100, 0),
                'flash_flood': (40, 100, 200)
            }
            color = hazard_colors.get(self.hazard_type, (255, 0, 255))
            
            pygame.draw.circle(surface, color, (int(self.x), int(self.y)), self.radius, 2)
            pygame.draw.circle(surface, (*color, 50), (int(self.x), int(self.y)), self.radius + pulse, 1)


class NPC:
    """Non-player characters for interaction"""
    def __init__(self, x, y, npc_type):
        self.x = x
        self.y = y
        self.npc_type = npc_type  # 'trader', 'rival_tribe', 'wildlife_herd'
        self.visible = True
        self.last_interaction = 0
        if npc_type == 'trader':
            self.inventory = {'food': random.randint(10, 30), 'wood': random.randint(5, 20), 'stone': random.randint(3, 10)}
            self.trade_rates = {'food_for_wood': 2, 'wood_for_stone': 2}
        else:
            self.inventory = {'food': random.randint(10, 30), 'wood': random.randint(5, 20), 'stone': random.randint(3, 10)}
        self.hostile = npc_type == 'rival_tribe'
        self.reputation = 0  # -100 to 100 for rival tribes
        
    def draw(self, surface):
        """Draw the NPC"""
        if self.visible:
            icon_size = 25
            npc_colors = {
                'trader': (255, 215, 0),  # Gold
                'rival_tribe': (139, 0, 0),  # Dark red
                'wildlife_herd': (205, 133, 63)  # Brown
            }
            color = npc_colors.get(self.npc_type, (128, 128, 128))
            
            # Draw NPC icon
            if self.npc_type == 'trader':
                # Draw caravan wagon
                pygame.draw.rect(surface, color, (self.x - icon_size//2, self.y - icon_size//3, icon_size, icon_size//2))
                pygame.draw.circle(surface, BLACK, (self.x - icon_size//4, self.y + icon_size//6), 4)
                pygame.draw.circle(surface, BLACK, (self.x + icon_size//4, self.y + icon_size//6), 4)
            elif self.npc_type == 'rival_tribe':
                # Draw threatening symbol
                pygame.draw.circle(surface, color, (int(self.x), int(self.y)), icon_size // 2)
                pygame.draw.lines(surface, (255, 255, 255), False, 
                    [(self.x, self.y - 8), (self.x - 5, self.y + 5), (self.x, self.y), (self.x + 5, self.y + 5)], 2)
            else:  # wildlife_herd
                # Draw multiple small circles for herd
                for i in range(3):
                    offset_x = random.randint(-5, 5)
                    offset_y = random.randint(-5, 5)
                    pygame.draw.circle(surface, color, (int(self.x + offset_x), int(self.y + offset_y)), icon_size // 3)
            
            # Pulsing ring for traders and rivals
            if self.npc_type in ['trader', 'rival_tribe']:
                pulse = int(2 * math.sin(time.time() * 2))
                pygame.draw.circle(surface, color, (int(self.x), int(self.y)), icon_size // 2 + pulse, 1)


class StockpileZone:
    """A zone designated for resource storage with filters and priority."""
    def __init__(self, x, y, width, height, zone_id):
        self.rect = pygame.Rect(x, y, width, height)
        self.id = zone_id
        self.allowed_resources = {'food', 'wood', 'stone'}
        self.priority = 1  # 1 (Low) to 4 (Critical)
        self.stored_resources = {'food': 0, 'wood': 0, 'stone': 0}

    def is_valid_for(self, resource_type):
        return resource_type in self.allowed_resources

    def get_center(self):
        return self.rect.centerx, self.rect.centery

    def draw(self, surface):
        # Draw translucent blue overlay for the stockpile
        overlay = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        color = (*BLUE, 60) # Soft blue with transparency
        pygame.draw.rect(overlay, color, (0, 0, self.rect.width, self.rect.height))
        surface.blit(overlay, (self.rect.x, self.rect.y))
        # Border
        pygame.draw.rect(surface, (*BLUE, 150), self.rect, 2)
        # Label
        label = font_small.render(f"Stockpile #{self.id}", True, WHITE)
        surface.blit(label, (self.rect.x + 5, self.rect.y + 5))


class Resource:
    """A collectible resource"""
    def __init__(self, x, y, resource_type='food'):
        self.x = x
        self.y = y
        self.resource_type = resource_type  # 'food' or 'wood'
        self.collected = False
        self.collect_time = 0  # Timestamp when collected (for respawning)
    
    def update(self, delta_time):
        """Update resource state (respawn logic for food)"""
        if self.collected and self.resource_type == 'food':
            current_time = time.time()
            if current_time - self.collect_time >= RESOURCE_RESPAWN_TIME:
                self.collected = False
                self.collect_time = 0
    
    def draw(self, surface, praxans=None):
        """Draw stylized resources with silhouette and shimmer."""
        if not self.collected:
            if self.resource_type == 'food':
                color = RED
                base_radius = RESOURCE_RADIUS_FOOD
            elif self.resource_type == 'stone':
                color = GRAY
                base_radius = RESOURCE_RADIUS_STONE
            else:
                color = BROWN
                base_radius = RESOURCE_RADIUS_WOOD
            
            # Check if any praxan is nearby for glow effect
            nearby = False
            if praxans:
                for praxan in praxans:
                    distance = math.sqrt((self.x - praxan.x)**2 + (self.y - praxan.y)**2)
                    if distance < 60:  # Glow if within 60 pixels (scaled)
                        nearby = True
                        break
            
            # Draw glow effect if nearby with proper alpha
            if nearby:
                glow_radius = base_radius + 8
                glow_color = tuple(min(255, c + 100) for c in color)  # Brighter color
                # Create glow surface with alpha
                glow_surface = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(glow_surface, (*glow_color, 80), (glow_radius, glow_radius), glow_radius)
                surface.blit(glow_surface, (int(self.x - glow_radius), int(self.y - glow_radius)))

            shimmer = math.sin(time.time() * 4 + self.x * 0.05 + self.y * 0.03)
            highlight_color = blend_color(color, WHITE, 0.25 + 0.15 * max(0, shimmer))

            if self.resource_type == 'food':
                berry_offsets = [(-4, 1), (0, -2), (4, 1)]
                for off_x, off_y in berry_offsets:
                    pygame.draw.circle(surface, BLACK, (int(self.x + off_x), int(self.y + off_y)), base_radius + 2)
                    pygame.draw.circle(surface, color, (int(self.x + off_x), int(self.y + off_y)), base_radius + 1)
                pygame.draw.line(surface, GRASS_DARK, (int(self.x), int(self.y - 7)), (int(self.x), int(self.y - 2)), 2)
                pygame.draw.circle(surface, highlight_color, (int(self.x), int(self.y - 1)), max(2, base_radius - 1))
            elif self.resource_type == 'wood':
                trunk = pygame.Rect(int(self.x - 3), int(self.y - 5), 6, 10)
                foliage_center = (int(self.x), int(self.y - 6))
                pygame.draw.rect(surface, BLACK, (trunk.x - 1, trunk.y - 1, trunk.width + 2, trunk.height + 2))
                pygame.draw.rect(surface, DIRT_MID, trunk)
                pygame.draw.circle(surface, BLACK, foliage_center, base_radius + 5)
                pygame.draw.circle(surface, GRASS_DARK, foliage_center, base_radius + 4)
                pygame.draw.circle(surface, GRASS_LIGHT, (foliage_center[0] - 2, foliage_center[1] - 2), max(3, base_radius + 1))
            else:
                rock_points = [
                    (int(self.x - 6), int(self.y + 3)),
                    (int(self.x - 2), int(self.y - 6)),
                    (int(self.x + 5), int(self.y - 3)),
                    (int(self.x + 6), int(self.y + 4)),
                    (int(self.x), int(self.y + 7)),
                ]
                pygame.draw.polygon(surface, BLACK, rock_points)
                inner_points = [(x - 1 if x > self.x else x + 1 if x < self.x else x, y) for x, y in rock_points]
                pygame.draw.polygon(surface, color, inner_points)
                pygame.draw.line(surface, highlight_color, (int(self.x - 2), int(self.y - 2)), (int(self.x + 2), int(self.y + 2)), 2)
    
    def check_collision(self, praxan):
        """Check if praxan is within collection distance"""
        if self.collected:
            return False
        distance = math.sqrt((self.x - praxan.x)**2 + (self.y - praxan.y)**2)
        return distance < RESOURCE_COLLISION_DIST





def save_legacy_data(stats, unlocks):
    """Save meta progression data"""
    legacy_file = 'legacy_data.json'
    try:
        # Load existing data if present
        existing_data = load_legacy_data()
        data = {
            'total_runs': existing_data.get('total_runs', 0) + 1,
            'best_population': max(existing_data.get('best_population', 0), stats.get('max_population', 0)),
            'total_days_survived': existing_data.get('total_days_survived', 0) + stats.get('days_survived', 0),
            'unlocked_bonuses': list(set(existing_data.get('unlocked_bonuses', []) + unlocks))
        }
        with open(legacy_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"[Legacy] Saved data: {data}")
    except Exception as e:
        print(f"[Legacy] Error saving: {e}")

def load_legacy_data():
    """Load meta progression data"""
    legacy_file = 'legacy_data.json'
    if os.path.exists(legacy_file):
        try:
            with open(legacy_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Legacy] Error loading: {e}")
            return {'total_runs': 0, 'best_population': 0, 'total_days_survived': 0, 'unlocked_bonuses': []}
    return {'total_runs': 0, 'best_population': 0, 'total_days_survived': 0, 'unlocked_bonuses': []}


class Camera:
    """Advanced Director system for fluid, momentum-based world viewing."""
    def __init__(self, world_width, world_height):
        # Actual state (current frame)
        self.x = 0.0
        self.y = 0.0
        self.zoom = 1.0
        
        # Target state (where we are gliding to)
        self.target_x = 0.0
        self.target_y = 0.0
        self.target_zoom = 1.0
        
        # Momentum
        self.vel_x = 0.0
        self.vel_y = 0.0
        self.friction = 0.88
        
        # Constraints
        self.min_zoom = 0.1
        self.max_zoom = 12.0
        self.world_width = world_width
        self.world_height = world_height
        
        # Lerp settings
        self.lerp_speed_pos = 12.0  # Positional glide speed
        self.lerp_speed_zoom = 10.0 # Zoom glide speed
        
        self.panning = False
        self.follow_mode = False
        
    def world_to_screen(self, world_x, world_y):
        return (world_x - self.x) * self.zoom, (world_y - self.y) * self.zoom
    
    def screen_to_world(self, screen_x, screen_y):
        return (screen_x / self.zoom) + self.x, (screen_y / self.zoom) + self.y
    
    def update(self, delta_time, screen_w, screen_h):
        """Update camera state using lerp and momentum."""
        if self.panning:
            # While dragging, momentum is reset
            self.vel_x = 0
            self.vel_y = 0
        else:
            # Apply momentum
            self.target_x += self.vel_x * delta_time
            self.target_y += self.vel_y * delta_time
            self.vel_x *= self.friction
            self.vel_y *= self.friction

        # Glide actual values toward targets
        self.x += (self.target_x - self.x) * min(1.0, self.lerp_speed_pos * delta_time)
        self.y += (self.target_y - self.y) * min(1.0, self.lerp_speed_pos * delta_time)
        self.zoom += (self.target_zoom - self.zoom) * min(1.0, self.lerp_speed_zoom * delta_time)
        
        self.clamp_camera(screen_w, screen_h)

    def adjust_zoom(self, factor, mouse_pos=None, screen_w=None, screen_h=None):
        """Scale target zoom. If mouse_pos is provided, zoom toward it (Rimworld-style)."""
        old_zoom = self.target_zoom
        self.target_zoom = max(self.min_zoom, min(self.max_zoom, self.target_zoom * factor))
        
        if mouse_pos and screen_w and screen_h:
            # Calculate world point under mouse before zoom
            mx, my = mouse_pos
            world_m_x = (mx / old_zoom) + self.target_x
            world_m_y = (my / old_zoom) + self.target_y
            
            # Adjust target_x/y so that the same world point stays under the mouse at new zoom
            self.target_x = world_m_x - (mx / self.target_zoom)
            self.target_y = world_m_y - (my / self.target_zoom)
            
        self.clamp_camera(screen_w, screen_h)

    def start_pan(self, screen_pos):
        self.follow_mode = False
        self.panning = True
        self.last_mouse_pos = screen_pos

    def update_pan(self, screen_pos):
        if self.panning:
            dx = (screen_pos[0] - self.last_mouse_pos[0]) / self.zoom
            dy = (screen_pos[1] - self.last_mouse_pos[1]) / self.zoom
            
            # Apply direct displacement to targets
            self.target_x -= dx
            self.target_y -= dy
            
            # Capture velocity for momentum release
            self.vel_x = -dx * 20.0
            self.vel_y = -dy * 20.0
            
            self.last_mouse_pos = screen_pos

    def stop_pan(self):
        self.panning = False

    def clamp_camera(self, screen_w, screen_h):
        """Keep camera within world bounds accounting for window size and zoom."""
        sw = screen_w or 1920
        sh = screen_h or 1080
        
        # Max bounds for target
        max_x = max(0, self.world_width - (sw / self.target_zoom))
        max_y = max(0, self.world_height - (sh / self.target_zoom))
        self.target_x = max(0, min(self.target_x, max_x))
        self.target_y = max(0, min(self.target_y, max_y))
        
        # Max bounds for actual
        max_ax = max(0, self.world_width - (sw / self.zoom))
        max_ay = max(0, self.world_height - (sh / self.zoom))
        self.x = max(0, min(self.x, max_ax))
        self.y = max(0, min(self.y, max_ay))

    def update_follow(self, entities, delta_time, screen_w, screen_h):
        if not self.follow_mode or not entities:
            return
        
        mean_x = sum(e.x for e in entities) / len(entities)
        mean_y = sum(e.y for e in entities) / len(entities)
        
        self.target_x = mean_x - screen_w / (2 * self.target_zoom)
        self.target_y = mean_y - screen_h / (2 * self.target_zoom)
        self.clamp_camera(screen_w, screen_h)

    def handle_keys(self, keys, delta_time):
        """Standard keyboard panning."""
        if self.follow_mode: return
        
        speed = 400.0 / self.zoom # Pixels per second at 1.0 zoom
        move_x = 0
        move_y = 0
        if keys[pygame.K_w] or keys[pygame.K_UP]: move_y -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]: move_y += 1
        if keys[pygame.K_a] or keys[pygame.K_LEFT]: move_x -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]: move_x += 1
        
        if move_x or move_y:
            self.target_x += move_x * speed * delta_time
            self.target_y += move_y * speed * delta_time
            self.follow_mode = False


class MapChunk:
    """A chunk of the world map"""
    def __init__(self, chunk_x, chunk_y, asset_manager=None, lazy_render=True, chunk_state=None, botany_manager=None, zoology_manager=None):
        self.chunk_x = chunk_x
        self.chunk_y = chunk_y
        self.world_x = chunk_x * CHUNK_SIZE
        self.world_y = chunk_y * CHUNK_SIZE
        self.tiles = {}  # {tile_pos: biome_type}
        self.biome_mix = {}
        self.region_id = None
        self.water_tiles = set()
        self.river_tiles = set()
        self.resources = []
        self.buildings = []
        self.explored = False
        if chunk_state is not None:
            self.world_x = int(getattr(chunk_state, "world_x", self.world_x))
            self.world_y = int(getattr(chunk_state, "world_y", self.world_y))
            self.tiles = dict(getattr(chunk_state, "tiles", {}))
            self.biome_mix = dict(getattr(chunk_state, "biome_mix", {}))
            self.region_id = getattr(chunk_state, "region_id", None)
            self.water_tiles = set(getattr(chunk_state, "water_tiles", ()))
            self.river_tiles = set(getattr(chunk_state, "river_tiles", ()))
            
            # Generate static flora for this chunk based on climate
            self._generate_static_flora(botany_manager)
        else:
            self.generate_biomes()
        self.surface = None  # Cached pre-rendered surface
        self.asset_manager = asset_manager
        self.surface_rendered = False
        
        # Lazy rendering: only render surface when first needed (much faster startup)
        if not lazy_render and asset_manager:
            self.render_surface()
    
    def _generate_static_flora(self, botany_manager):
        """Generate Rimworld-style dense trees and rocks directly within the chunk's tiles."""
        if botany_manager:
            botany_manager.spawn_initial_flora(self, TILE_SIZE)
            return
            
        seed_val = int(self.world_x * 73856093 + self.world_y * 19349663)
        rng = random.Random(seed_val)
        
        # Determine base density based on dominant biomes in the chunk
        densities = {
            'forest': {'wood': 0.65, 'stone': 0.05, 'food': 0.15},
            'taiga': {'wood': 0.50, 'stone': 0.10, 'food': 0.05},
            'swamp': {'wood': 0.35, 'stone': 0.02, 'food': 0.10},
            'plains': {'wood': 0.10, 'stone': 0.05, 'food': 0.08},
            'mountains': {'wood': 0.02, 'stone': 0.45, 'food': 0.01},
            'tundra': {'wood': 0.05, 'stone': 0.15, 'food': 0.02},
            'desert': {'wood': 0.01, 'stone': 0.10, 'food': 0.01},
            'snow': {'wood': 0.01, 'stone': 0.15, 'food': 0.00},
        }

        # Each tile is TILE_SIZE. We can try placing 1-3 resources per tile in heavily wooded areas
        for (tx, ty), biome in self.tiles.items():
            if (tx, ty) in self.water_tiles or (tx, ty) in self.river_tiles:
                continue
                
            rates = densities.get(biome, densities['plains'])
            
            # Trees (Wood)
            if rng.random() < rates['wood']:
                count = rng.randint(1, 3) if rates['wood'] > 0.4 else 1
                for _ in range(count):
                    px = self.world_x + (tx * TILE_SIZE) + rng.uniform(4, TILE_SIZE - 4)
                    py = self.world_y + (ty * TILE_SIZE) + rng.uniform(4, TILE_SIZE - 4)
                    res = Resource(px, py, 'wood')
                    self.resources.append(res)
                    
            # Rocks (Stone)
            elif rng.random() < rates['stone']:
                count = rng.randint(1, 4) if rates['stone'] > 0.3 else 1
                for _ in range(count):
                    px = self.world_x + (tx * TILE_SIZE) + rng.uniform(4, TILE_SIZE - 4)
                    py = self.world_y + (ty * TILE_SIZE) + rng.uniform(4, TILE_SIZE - 4)
                    res = Resource(px, py, 'stone')
                    self.resources.append(res)
                    
            # Forage (Food)
            elif rng.random() < rates['food']:
                px = self.world_x + (tx * TILE_SIZE) + rng.uniform(4, TILE_SIZE - 4)
                py = self.world_y + (ty * TILE_SIZE) + rng.uniform(4, TILE_SIZE - 4)
                res = Resource(px, py, 'food')
                self.resources.append(res)
    
    def render_surface(self):
        """Pre-render the chunk to a surface for faster drawing"""
        # Skip if already rendered
        if self.surface_rendered and self.surface is not None:
            return
        
        # Always create surface, even if asset_manager is None
        self.surface = pygame.Surface((CHUNK_SIZE, CHUNK_SIZE))
        self.surface_rendered = True
        
        if self.asset_manager is None:
            # Fallback: fill with biome color based on center tile
            center_tile = self.tiles.get((8, 8), 'plains')
            biome_colors = {
                'forest': GRASS_DARK,
                'plains': GRASS_MID,
                'mountains': ROCK_MID,
                'desert': DESERT_SAND,
                'snow': SNOW_WHITE,
                'swamp': SWAMP_DARK,
                'taiga': TAIGA_GREEN,
                'tundra': ICE_BLUE
            }
            color = biome_colors.get(center_tile, GRAY)
            self.surface.fill(color)
            return
        
        # Normal rendering with asset manager
        for tile_pos, biome_type in self.tiles.items():
            tile_x, tile_y = tile_pos
            local_x = tile_x * TILE_SIZE
            local_y = tile_y * TILE_SIZE
            
            # Load or generate tile
            try:
                tile_surface = self.asset_manager.load_tile(biome_type, 'grass')
                if tile_surface:
                    self.surface.blit(tile_surface, (local_x, local_y))
                else:
                    # Fallback if load_tile returns None
                    biome_colors = {
                        'forest': GRASS_DARK,
                        'plains': GRASS_MID,
                        'mountains': ROCK_MID,
                        'desert': DESERT_SAND,
                        'snow': SNOW_WHITE,
                        'swamp': SWAMP_DARK,
                        'taiga': TAIGA_GREEN,
                        'tundra': ICE_BLUE
                    }
                    color = biome_colors.get(biome_type, GRAY)
                    pygame.draw.rect(self.surface, color, (local_x, local_y, TILE_SIZE, TILE_SIZE))
            except Exception as e:
                # Fallback on error
                biome_colors = {
                    'forest': GRASS_DARK,
                    'plains': GRASS_MID,
                    'mountains': ROCK_MID,
                    'desert': DESERT_SAND,
                    'snow': SNOW_WHITE,
                    'swamp': SWAMP_DARK,
                    'taiga': TAIGA_GREEN,
                    'tundra': ICE_BLUE
                }
                color = biome_colors.get(biome_type, GRAY)
                pygame.draw.rect(self.surface, color, (local_x, local_y, TILE_SIZE, TILE_SIZE))
    
    def generate_biomes(self):
        """Generate biomes for this chunk using simple noise"""
        tiles_x = CHUNK_SIZE // TILE_SIZE
        tiles_y = CHUNK_SIZE // TILE_SIZE
        
        for tx in range(tiles_x):
            for ty in range(tiles_y):
                # Simple Perlin-like noise using multiple octaves
                world_x = self.world_x + (tx * TILE_SIZE)
                world_y = self.world_y + (ty * TILE_SIZE)
                
                # Generate elevation, temperature, moisture
                elevation = self.simple_noise(world_x, world_y, 0.02, 0)
                temperature = self.simple_noise(world_x, world_y, 0.01, 1000)
                moisture = self.simple_noise(world_x, world_y, 0.015, 2000)
                
                # Determine biome from these values
                biome_type = self.get_biome_from_climate(elevation, temperature, moisture)
                self.tiles[(tx, ty)] = biome_type
    
    def simple_noise(self, x, y, scale, offset):
        """Simple noise function for biome generation"""
        # Use sinusoidal approximation for smooth noise
        fx = x * scale
        fy = y * scale + offset
        return math.sin(fx) * math.cos(fy)
    
    def get_biome_from_climate(self, elevation, temperature, moisture):
        """Determine biome from climate parameters"""
        # Normalize values to 0-1 range
        elevation_n = (elevation + 1) / 2
        temp_n = (temperature + 1) / 2
        moisture_n = (moisture + 1) / 2
        
        # Determine biome based on thresholds
        if elevation_n > 0.7:
            return 'mountains'
        elif elevation_n < 0.3:
            if moisture_n > 0.6:
                return 'swamp'
            elif temp_n < 0.3:
                return 'tundra'
            elif temp_n > 0.7 and moisture_n < 0.3:
                return 'desert'
            else:
                return 'plains'
        else:
            if temp_n < 0.3:
                if moisture_n > 0.5:
                    return 'taiga'
                else:
                    return 'tundra'
            elif temp_n > 0.7:
                if moisture_n < 0.3:
                    return 'desert'
                elif moisture_n > 0.6:
                    return 'forest'
                else:
                    return 'plains'
            else:
                if moisture_n > 0.5:
                    return 'forest'
                else:
                    return 'plains'


class WorldMap:
    """Manages the world map with chunks"""
    def __init__(self, asset_manager=None, scenario_profile=None, seed=None, snapshot_world=None, planet_tile=None, botany_manager=None, zoology_manager=None):
        self.chunks = {}  # {(chunk_x, chunk_y): MapChunk}
        self.asset_manager = asset_manager
        self.botany_manager = botany_manager
        self.zoology_manager = zoology_manager
        self.encounters = []  # List of special encounters
        self.hazards = []  # List of terrain hazards
        self.npcs = []  # List of NPCs
        self.discovered_chunks = set()
        self.modified_chunks = {}
        self.scenario_profile = dict(scenario_profile or {})

        snapshot_world = dict(snapshot_world or {})
        profile_source = dict(self.scenario_profile)
        if isinstance(snapshot_world.get("world_profile"), dict):
            profile_source["worldgen"] = dict(snapshot_world.get("world_profile", {}))
            
        # [Phase 3] If a Planet Tile was provided, force the local profile to inherit its climate
        self.planet_tile = planet_tile
        if self.planet_tile:
            print(f"[Planet Local Gen] Inheriting traits from planet tile: Biome {planet_tile.biome}, Temp {planet_tile.temperature:.2f}")
            if "worldgen" not in profile_source:
                profile_source["worldgen"] = {}
            profile_source["worldgen"]["climate_bias"] = planet_tile.biome
            profile_source["worldgen"]["temperature_bias"] = planet_tile.temperature
            profile_source["worldgen"]["moisture_bias"] = planet_tile.moisture
            
            # Restrict local map size to feel more like a "landing zone"
            profile_source["worldgen"]["chunk_cols"] = 16
            profile_source["worldgen"]["chunk_rows"] = 16
            
            # If the planet is ocean, we spawn an island map
            if not planet_tile.is_land:
                profile_source["worldgen"]["water_abundance"] = 0.9
                
        # [Phase 4: LLM Generation] If an AI world seed was provided, let it override the basic planet parameters
        ai_seed = snapshot_world.get("ai_world_seed")
        if ai_seed:
            print(f"[Planet Local Gen] Overriding local traits with AI Dream: {ai_seed.get('planet_name')} - {ai_seed.get('lore')}")
            if "worldgen" not in profile_source:
                profile_source["worldgen"] = {}
            profile_source["worldgen"]["climate_bias"] = ai_seed.get("climate_bias", "plains")
            profile_source["worldgen"]["temperature_bias"] = ai_seed.get("temperature_bias", 0.5)
            profile_source["worldgen"]["moisture_bias"] = ai_seed.get("moisture_bias", 0.5)
            profile_source["worldgen"]["ruggedness"] = ai_seed.get("ruggedness", 0.5)
            profile_source["worldgen"]["water_abundance"] = ai_seed.get("water_abundance", 0.5)
            profile_source["worldgen"]["hazard_density"] = ai_seed.get("hazard_density", 0.5)
            profile_source["worldgen"]["mutation_pressure"] = ai_seed.get("mutation_pressure", 0.5)
            # Store the lore and botany ideas to pass to other managers later if needed
            self.ai_botany_ideas = ai_seed.get("botany_ideas", [])
            if self.botany_manager:
                self.botany_manager.ai_botany_ideas = self.ai_botany_ideas
            self.planet_name = ai_seed.get("planet_name", "Unknown")
            self.planet_lore = ai_seed.get("lore", "")

        self.world_profile = build_world_profile(profile_source, chunk_size=CHUNK_SIZE, tile_size=TILE_SIZE)
        self.chunk_cols = int(self.world_profile.chunk_cols)
        self.chunk_rows = int(self.world_profile.chunk_rows)
        self.world_width = int(self.world_profile.world_width)
        self.world_height = int(self.world_profile.world_height)
        self.region_cols = int(self.world_profile.region_cols)
        self.region_rows = int(self.world_profile.region_rows)
        self.generation_version = int(snapshot_world.get("generation_version", WORLD_GENERATION_VERSION))
        self.world_seed = int(
            snapshot_world.get("world_seed")
            if snapshot_world.get("world_seed") is not None
            else (seed if seed is not None else random.randint(1, 2**31 - 1))
        )
        self.frontier_world = build_frontier_world(self.world_seed, self.world_profile)
        self.region_objects = dict(self.frontier_world["regions"])
        self.route_objects = list(self.frontier_world["routes"])
        self.landmark_objects = list(self.frontier_world["landmarks"])
        self.settlement_objects = list(self.frontier_world["settlements"])
        self.polity_objects = list(self.frontier_world["polities"])
        render_layers = dict(self.frontier_world["render_layers"])
        self.region_overlay = list(render_layers.get("region_overlay", []))
        self.route_network = list(render_layers.get("route_network", []))
        self.landmark_markers = list(render_layers.get("landmark_markers", []))
        self.polity_overlay = list(render_layers.get("polity_overlay", []))
        self.water_network = list(render_layers.get("water_network", []))
        self.regions = list(self.region_overlay)
        self.routes = list(self.route_network)
        self.landmarks = list(self.landmark_markers)
        self.settlements = [settlement.to_payload() for settlement in self.settlement_objects]
        self.polities = list(self.polity_overlay)
        self.river_paths = list(self.frontier_world.get("river_paths", []))
        self.generate_initial_chunks()
        self.generate_geography_entities()
        if snapshot_world:
            self.apply_snapshot_world_state(snapshot_world)
    
    def generate_initial_chunks(self):
        """Generate initial set of chunks"""
        # Use lazy rendering for faster startup - surfaces will be created on first use
        for (cx, cy), chunk_state in self.frontier_world["chunks"].items():
            self.chunks[(cx, cy)] = MapChunk(cx, cy, self.asset_manager, lazy_render=True, chunk_state=chunk_state, botany_manager=self.botany_manager, zoology_manager=self.zoology_manager)

    def generate_geography_entities(self):
        """Generate encounters, hazards, and NPCs from the frontier geography instead of scatter noise."""
        self.encounters = []
        self.hazards = []
        self.npcs = []

        encounter_types = {
            "granary": "ruins",
            "citadel": "mineral_vein",
            "crossing": "oasis",
        }
        for landmark in self.landmark_objects:
            encounter = Encounter(float(landmark.x), float(landmark.y), encounter_types.get(landmark.category, "ruins"))
            encounter.discovered = False
            self.encounters.append(encounter)

        candidate_regions = sorted(
            self.region_objects.values(),
            key=lambda region: (region.frontier_score * 0.6) + (region.defensibility * 0.25) + (0.15 if region.coastal else 0.0),
            reverse=True,
        )
        hazard_budget = max(8, int(len(candidate_regions) * self.world_profile.hazard_density * 0.24))
        for region in candidate_regions[:hazard_budget]:
            x = region.world_rect[0] + (region.world_rect[2] / 2.0)
            y = region.world_rect[1] + (region.world_rect[3] / 2.0)
            hazard_type = {
                "mountains": "avalanche_zone",
                "desert": "quicksand",
                "swamp": "flood_zone",
            }.get(region.biome, "predator_lair")
            radius = 90 + int(region.frontier_score * 120)
            hazard = TerrainHazard(x, y, hazard_type, radius=radius)
            hazard.damage_rate = 0.4 + (region.frontier_score * 0.8)
            self.hazards.append(hazard)

        for route in self.route_objects:
            if len(route.points) < 2:
                continue
            midpoint = route.points[len(route.points) // 2]
            npc_type = "trader" if route.route_type == "trade" else "wildlife_herd"
            npc = NPC(midpoint[0], midpoint[1], npc_type)
            npc.route_id = route.route_id
            self.npcs.append(npc)
        for polity in self.polity_objects:
            home_region = self.region_objects.get(polity.home_region_id)
            if home_region is None:
                continue
            x, y = self.get_region_center(home_region.region_id)
            rival = NPC(x + 44, y + 28, "rival_tribe")
            rival.route_id = f"frontier_{polity.polity_id}"
            rival.reputation = -8
            self.npcs.append(rival)
    
    def get_chunk_at_world_pos(self, world_x, world_y):
        """Get chunk containing a world position"""
        chunk_x = int(world_x // CHUNK_SIZE)
        chunk_y = int(world_y // CHUNK_SIZE)
        return self.chunks.get((chunk_x, chunk_y))

    def get_region_at_world_pos(self, world_x, world_y):
        region_col = min(self.region_cols - 1, max(0, int(world_x // max(1, self.world_profile.region_width))))
        region_row = min(self.region_rows - 1, max(0, int(world_y // max(1, self.world_profile.region_height))))
        return self.region_objects.get(f"r{region_col}_{region_row}")

    def get_region_center(self, region_id):
        region = self.region_objects.get(region_id)
        if region is None:
            return (self.world_width / 2.0, self.world_height / 2.0)
        return (
            region.world_rect[0] + (region.world_rect[2] / 2.0),
            region.world_rect[1] + (region.world_rect[3] / 2.0),
        )

    def get_spawn_point(self, safe_biomes):
        safe_biomes = set(safe_biomes or [])
        settlements = sorted(self.settlement_objects, key=lambda settlement: settlement.prosperity, reverse=True)
        for settlement in settlements:
            region = self.region_objects.get(settlement.region_id)
            if region and (not safe_biomes or region.biome in safe_biomes):
                return (float(settlement.x), float(settlement.y))
        regions = sorted(self.region_objects.values(), key=lambda region: (region.fertility + region.route_score), reverse=True)
        for region in regions:
            if not safe_biomes or region.biome in safe_biomes:
                return self.get_region_center(region.region_id)
        return (self.world_width / 2.0, self.world_height / 2.0)

    def get_route_target_for_migration(self, centroid, doctrine_key, migration_pressure):
        if centroid is None or migration_pressure < 30.0:
            return None
        current_region = self.get_region_at_world_pos(centroid[0], centroid[1])
        current_region_id = getattr(current_region, "region_id", None)
        doctrine_weights = {
            "growth": lambda region: (region.fertility * 0.6) + (region.water_score * 0.2) + (region.route_score * 0.2),
            "security": lambda region: (region.defensibility * 0.6) + ((1.0 - region.frontier_score) * 0.25) + (region.route_score * 0.15),
            "industry": lambda region: (region.route_score * 0.55) + (region.defensibility * 0.25) + ((1.0 - region.moisture) * 0.2),
            "exploration": lambda region: (region.frontier_score * 0.5) + (region.route_score * 0.2) + (0.15 if region.coastal else 0.0) + (0.15 if region.river else 0.0),
            "harmony": lambda region: (region.water_score * 0.4) + (region.fertility * 0.3) + ((1.0 - region.frontier_score) * 0.3),
        }
        scorer = doctrine_weights.get(str(doctrine_key or "exploration"), doctrine_weights["exploration"])
        candidates = []
        for route in self.route_network:
            route_regions = {route.get("start_region_id"), route.get("end_region_id")}
            if current_region_id and current_region_id not in route_regions:
                continue
            target_region_id = route.get("end_region_id")
            if current_region_id and target_region_id == current_region_id:
                target_region_id = route.get("start_region_id")
            region = self.region_objects.get(target_region_id)
            if region is None:
                continue
            target_x, target_y = self.get_region_center(region.region_id)
            distance = math.hypot(target_x - centroid[0], target_y - centroid[1])
            score = scorer(region) * 100.0
            score += min(40.0, distance / 70.0)
            score -= float(route.get("risk", 0.0) or 0.0) * 22.0
            candidates.append((score, (target_x, target_y)))
        if not candidates:
            for settlement in self.settlement_objects:
                region = self.region_objects.get(settlement.region_id)
                if region is None:
                    continue
                distance = math.hypot(settlement.x - centroid[0], settlement.y - centroid[1])
                score = scorer(region) * 100.0
                score += min(32.0, distance / 80.0)
                candidates.append((score, (float(settlement.x), float(settlement.y))))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        best_x, best_y = candidates[0][1]
        return (
            clamp(best_x, 40.0, max(40.0, self.world_width - 40.0)),
            clamp(best_y, 40.0, max(40.0, self.world_height - 40.0)),
        )

    def apply_snapshot_world_state(self, world_data):
        if not isinstance(world_data, dict):
            return
        self.generation_version = int(world_data.get("generation_version", self.generation_version))
        discovered_chunks = set()
        for entry in world_data.get("discovered_chunks", []):
            if isinstance(entry, dict):
                chunk_x = entry.get("chunk_x")
                chunk_y = entry.get("chunk_y")
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                chunk_x, chunk_y = entry
            else:
                continue
            try:
                discovered_chunks.add((int(chunk_x), int(chunk_y)))
            except (TypeError, ValueError):
                continue
        if discovered_chunks:
            self.discovered_chunks = discovered_chunks
            for chunk_key in discovered_chunks:
                chunk = self.chunks.get(chunk_key)
                if chunk is not None:
                    chunk.explored = True

        if isinstance(world_data.get("polities"), list):
            updated_polities = []
            for index, polity in enumerate(world_data.get("polities", [])):
                if isinstance(polity, dict):
                    updated_polities.append(polity)
            if updated_polities:
                self.polity_overlay = list(updated_polities)
                self.polities = updated_polities
        else:
            self.polities = list(self.polity_overlay)

        if isinstance(world_data.get("settlements"), list):
            self.settlements = [settlement for settlement in world_data.get("settlements", []) if isinstance(settlement, dict)]
        else:
            self.settlements = [settlement.to_payload() for settlement in self.settlement_objects]

        if isinstance(world_data.get("routes"), list):
            self.route_network = [route for route in world_data.get("routes", []) if isinstance(route, dict)]
            self.routes = list(self.route_network)
        if isinstance(world_data.get("landmarks"), list):
            self.landmark_markers = [landmark for landmark in world_data.get("landmarks", []) if isinstance(landmark, dict)]
            self.landmarks = list(self.landmark_markers)
        if isinstance(world_data.get("regions"), list):
            self.region_overlay = [region for region in world_data.get("regions", []) if isinstance(region, dict)]
            self.regions = list(self.region_overlay)
        if isinstance(world_data.get("water_network"), list):
            self.water_network = [segment for segment in world_data.get("water_network", []) if isinstance(segment, dict)]
    def get_biome_at(self, world_x, world_y):
        """Get biome type at world coordinates"""
        chunk = self.get_chunk_at_world_pos(world_x, world_y)
        if not chunk:
            return 'plains'
        
        # Find tile within chunk
        local_x = world_x - chunk.world_x
        local_y = world_y - chunk.world_y
        tile_x = int(local_x // TILE_SIZE)
        tile_y = int(local_y // TILE_SIZE)
        
        return chunk.tiles.get((tile_x, tile_y), 'plains')
    
    def get_biome_properties(self, biome_type):
        """Get properties for a biome type"""
        biome_props = {
            'forest': {
                'movement_speed': 0.9,  # Slower in dense forest
                'food_bonus': 1.2,  # More foraging
                'wood_bonus': 1.5,
                'stone_bonus': 0.3,
                'comfort_bonus': 1.1,  # Good shelter
                'disease_risk': 0.8  # Lower disease risk
            },
            'plains': {
                'movement_speed': 1.0,
                'food_bonus': 1.0,
                'wood_bonus': 0.5,
                'stone_bonus': 0.5,
                'comfort_bonus': 1.0,
                'disease_risk': 1.0
            },
            'mountains': {
                'movement_speed': 0.7,  # Much slower
                'food_bonus': 0.5,
                'wood_bonus': 0.3,
                'stone_bonus': 1.8,
                'comfort_bonus': 0.8,  # Hard to live in
                'disease_risk': 1.2  # Higher altitude sickness
            },
            'desert': {
                'movement_speed': 1.1,  # Open terrain
                'food_bonus': 0.3,  # Very scarce
                'wood_bonus': 0.1,
                'stone_bonus': 0.8,
                'comfort_bonus': 0.6,  # Very uncomfortable
                'disease_risk': 1.3  # Dehydration risk
            },
            'snow': {
                'movement_speed': 0.6,  # Very slow
                'food_bonus': 0.2,
                'wood_bonus': 0.4,
                'stone_bonus': 0.4,
                'comfort_bonus': 0.5,  # Very cold
                'disease_risk': 1.5  # Frostbite
            },
            'swamp': {
                'movement_speed': 0.5,  # Very difficult terrain
                'food_bonus': 1.1,
                'wood_bonus': 0.6,
                'stone_bonus': 0.2,
                'comfort_bonus': 0.4,
                'disease_risk': 2.0  # High disease risk
            },
            'taiga': {
                'movement_speed': 0.8,
                'food_bonus': 0.7,
                'wood_bonus': 1.3,
                'stone_bonus': 0.3,
                'comfort_bonus': 0.8,
                'disease_risk': 1.0
            },
            'tundra': {
                'movement_speed': 0.7,
                'food_bonus': 0.4,
                'wood_bonus': 0.2,
                'stone_bonus': 0.2,
                'comfort_bonus': 0.5,
                'disease_risk': 1.3
            }
        }
        return biome_props.get(biome_type, biome_props['plains'])


class Building:
    """A structure built by praxans"""
    def __init__(self, x, y, building_type):
        self.x = x
        self.y = y
        self.building_type = building_type  # 'house', 'storage', 'farm', 'workshop', 'shrine', 'well'
        self.built_at = time.time()
        self.built_by = None  # Will store praxan ID who built it
        self.occupants = []  # Praxans currently using this building
        self.last_production_time = time.time()  # For farms
        self.stored_resources = {'food': 0, 'wood': 0, 'stone': 0}  # For storage/farms
        self.level = 1
        self.aura_strength = 0.0
        self.bills = []  # List of string bill IDs (e.g. 'CraftWeapon')
        self.origin_biome = None
        self.material_style = None
        self.wear = 0.04
        self.construction_progress = 0.18

    def _derive_material_style(self, biome_type):
        biome = str(biome_type or "plains").lower()
        if biome in ("forest", "taiga"):
            return "timber"
        if biome in ("desert",):
            return "adobe"
        if biome in ("mountains",):
            return "slate"
        if biome in ("swamp",):
            return "reed"
        if biome in ("snow", "tundra"):
            return "frost"
        return "plaster"
    
    def tick_rare(self, delta_time, game_state):
        """Update building state (production, etc.) periodically"""
        modifiers = game_state.get('advisor').game_modifiers if game_state.get('advisor') else None
        weather_effects = game_state.get('weather_effects')
        world_map = game_state.get('world_map')
        weather_system = game_state.get('weather_system')
        settlement_state = game_state.get('settlement_state', {})
        current_time = time.time()
        biome_type = None
        if world_map is not None and hasattr(world_map, 'get_biome_at'):
            try:
                biome_type = world_map.get_biome_at(self.x, self.y)
            except Exception:
                biome_type = None
        if biome_type:
            self.origin_biome = biome_type
        elif self.origin_biome is None:
            self.origin_biome = "plains"
        if not self.material_style:
            self.material_style = self._derive_material_style(self.origin_biome)

        occupancy_factor = min(3, len(self.occupants))
        build_rate = (delta_time / 18.0) * (1.0 + occupancy_factor * 0.18 + max(0, self.level - 1) * 0.08)
        self.construction_progress = clamp(self.construction_progress + build_rate, 0.0, 1.0)

        weather_name = str(getattr(weather_system, "current_weather", "clear") or "clear").lower()
        exposure_by_type = {
            'farm': 1.45,
            'watchtower': 1.5,
            'well': 1.2,
            'market': 1.25,
            'house': 1.0,
            'storage': 0.95,
            'workshop': 0.9,
            'shrine': 0.85,
            'hospital': 0.8,
            'school': 0.82,
        }
        weather_wear = {
            'clear': 1.0,
            'rain': 1.2,
            'storm': 1.55,
            'snow': 1.25,
            'heatwave': 1.3,
            'drought': 1.15,
            'aurora': 0.9,
        }.get(weather_name, 1.0)
        prosperity = float(settlement_state.get('prosperity_score', 0.5) or 0.5)
        maintenance_rate = delta_time * (0.0010 + prosperity * 0.0012 + occupancy_factor * 0.0004)
        wear_rate = delta_time * 0.0021 * exposure_by_type.get(self.building_type, 1.0) * weather_wear
        if self.construction_progress < 1.0:
            wear_rate *= 0.45
        self.wear = clamp(self.wear + wear_rate - maintenance_rate, 0.0, 1.0)

        # Farms produce food over time
        if self.building_type == 'farm':
            mod = modifiers.get_modifier('farm_production_rate') if modifiers else 1.0
            mod *= 1.0 + (self.level - 1) * 0.18

            # Apply weather drought effect (reduces production rate)
            if weather_effects and 'food' in weather_effects:
                # drought effect is -0.5, so multiply production time by (1 + abs(effect))
                # -0.5 makes production 1.5x slower
                mod *= (1.0 + abs(weather_effects['food']))

            production_time = 10.0 / mod
            if current_time - self.last_production_time >= production_time:
                # Calculate how many cycles passed
                cycles = int((current_time - self.last_production_time) / production_time)
                if cycles > 0:
                    self.stored_resources['food'] += cycles
                    # Consume wood for production
                    wood_needed = 0.1 * cycles
                    if self.stored_resources['wood'] >= wood_needed:
                        self.stored_resources['wood'] -= wood_needed
                    else:
                        self.stored_resources['wood'] = 0.0
                    self.last_production_time = current_time

        # Auto-populate bills when resources are available and queue is empty
        self._auto_populate_bills()
    
    def _auto_populate_bills(self):
        """Automatically queue crafting bills when the building has enough
        stored resources and its bill queue is empty.  This keeps workshops
        and farms productive without manual player intervention (observer-only
        game).  At most one bill is queued per rare-tick to avoid draining
        resources instantly."""
        if self.bills:
            return  # already has pending work

        for job_id, job_def in JOB_DEFS.items():
            if job_def.get('station') != self.building_type:
                continue
            # Check if building has enough ingredients
            can_do = True
            for ing in job_def.get('ingredients', []):
                if self.stored_resources.get(ing['type'], 0) < ing['amount']:
                    can_do = False
                    break
            if can_do:
                self.bills.append(job_id)
                return  # one bill per tick

    def can_enter(self, praxan, modifiers=None):
        """Check if praxan can use this building"""
        if self.building_type == 'house':
            capacity = int((2 + max(0, self.level - 1)) * (modifiers.get_modifier('house_capacity') if modifiers else 1.0))
            return len(self.occupants) < capacity
        return True  # Other buildings have no capacity limit
    
    def enter(self, praxan, modifiers=None):
        """Praxan enters building"""
        if praxan not in self.occupants and self.can_enter(praxan, modifiers):
            self.occupants.append(praxan)
            return True
        return False
    
    def leave(self, praxan):
        """Praxan leaves building"""
        if praxan in self.occupants:
            self.occupants.remove(praxan)
    
    def draw(self, surface):
        """Draw the building based on type with polished pixel art graphics"""
        size = BUILDING_SIZE
        rect = pygame.Rect(int(self.x - size//2), int(self.y - size//2), size, size)
        glow_colors = {
            'house': DIRT_LIGHT,
            'storage': ROCK_LIGHT,
            'farm': GRASS_LIGHT,
            'workshop': EXPLORER_COLOR,
            'shrine': GOLD,
            'well': CYAN,
            'hospital': (255, 200, 200),
            'school': (150, 200, 255),
            'watchtower': DIRT_LIGHT,
            'market': GOLD,
        }
        aura_strength = getattr(self, 'aura_strength', 0.0)
        if aura_strength > 0.08:
            glow_radius = size + int(10 * aura_strength)
            glow_surface = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
            glow_color = glow_colors.get(self.building_type, WHITE)
            pygame.draw.circle(
                glow_surface,
                (*glow_color, int(20 + aura_strength * 60)),
                (glow_radius, glow_radius),
                glow_radius // 2,
            )
            surface.blit(glow_surface, (int(self.x - glow_radius), int(self.y - glow_radius)))
        
        # Different colors and symbols for each building type
        if self.building_type == 'house':
            # Brown house with roof and details - using palette colors
            # Shadow with alpha
            shadow_surface = pygame.Surface((size + 4, size + 4), pygame.SRCALPHA)
            shadow_rect = pygame.Rect(2, 2, size, size)
            pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_rect)
            surface.blit(shadow_surface, (int(self.x - size//2 - 2), int(self.y - size//2 - 2)))
            
            # Main body
            pygame.draw.rect(surface, BLACK, (rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4))  # Frame
            pygame.draw.rect(surface, DIRT_DARK, rect)
            # Roof with better shading
            roof_height = int(size * 0.35)
            roof_points = [
                (self.x - size//2, self.y - size//2),
                (self.x, self.y - size//2 - roof_height),
                (self.x + size//2, self.y - size//2)
            ]
            pygame.draw.polygon(surface, DIRT_MID, roof_points)
            pygame.draw.polygon(surface, BLACK, roof_points, 2)
            
            # Window with glow
            window_size = max(5, int(size * 0.3))
            window_rect = pygame.Rect(int(self.x - window_size//2), int(self.y - window_size//2), window_size, window_size)
            pygame.draw.rect(surface, WATER_SHALLOW, window_rect)
            pygame.draw.rect(surface, BLACK, window_rect, 2)
            
            # Door
            door_width = int(size * 0.4)
            door_height = int(size * 0.6)
            door_rect = pygame.Rect(int(self.x - door_width//2), int(self.y + size//2 - door_height), door_width, door_height)
            pygame.draw.rect(surface, BLACK, door_rect)
            
            # Show occupancy with better visibility
            if self.occupants:
                for i, occupant in enumerate(self.occupants):
                    pygame.draw.circle(surface, BLACK, (int(self.x), int(self.y + size//2 + 8 + i * 4)), 4)  # Outline
                    pygame.draw.circle(surface, YELLOW, (int(self.x), int(self.y + size//2 + 8 + i * 4)), 3)
        elif self.building_type == 'storage':
            # Gray storage with 3D effect - using palette colors
            shadow_surface = pygame.Surface((size + 4, size + 4), pygame.SRCALPHA)
            shadow_rect = pygame.Rect(2, 2, size, size)
            pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_rect)
            surface.blit(shadow_surface, (int(self.x - size//2 - 2), int(self.y - size//2 - 2)))
            
            # Main body
            pygame.draw.rect(surface, BLACK, (rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4))  # Frame
            pygame.draw.rect(surface, ROCK_MID, rect)
            pygame.draw.rect(surface, ROCK_DARK, rect, 2)
            
            # Inner detail
            inner_padding = int(size * 0.3)
            inner_rect = pygame.Rect(int(self.x - size//2 + inner_padding), int(self.y - size//2 + inner_padding), size - inner_padding*2, size - inner_padding*2)
            pygame.draw.rect(surface, ROCK_LIGHT, inner_rect)
            pygame.draw.rect(surface, BLACK, inner_rect, 1)
            
            # Show stored resources (debug only)
            if DEBUG_SHOW_INVENTORY_TEXT:
                total_stored = self.stored_resources['food'] + self.stored_resources['wood'] + self.stored_resources['stone']
                if total_stored > 0:
                    storage_text = font_small.render(f"F{int(self.stored_resources['food'])}W{int(self.stored_resources['wood'])}S{int(self.stored_resources['stone'])}", True, WHITE)
                    surface.blit(storage_text, (int(self.x - 12), int(self.y - 8)))
        elif self.building_type == 'farm':
            # Green farm with crop rows - using palette colors
            shadow_surface = pygame.Surface((size + 4, size + 4), pygame.SRCALPHA)
            shadow_rect = pygame.Rect(2, 2, size, size)
            pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_rect)
            surface.blit(shadow_surface, (int(self.x - size//2 - 2), int(self.y - size//2 - 2)))
            
            # Base
            pygame.draw.rect(surface, BLACK, (rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4))  # Frame
            pygame.draw.rect(surface, GRASS_DARK, rect)
            pygame.draw.rect(surface, BLACK, rect, 2)
            
            # Crop rows
            for i in range(3):
                pygame.draw.line(surface, BLACK, 
                               (int(self.x - size//3 + i * size//3), int(self.y - size//2)),
                               (int(self.x - size//3 + i * size//3), int(self.y + size//2)), 3)
                # Individual plants
                plant_size = max(2, int(size * 0.18))
                pygame.draw.circle(surface, BLACK, 
                                 (int(self.x - size//3 + i * size//3), int(self.y - 2)), plant_size + 1)  # Outline
                pygame.draw.circle(surface, GRASS_LIGHT, 
                                 (int(self.x - size//3 + i * size//3), int(self.y - 2)), plant_size)
                pygame.draw.circle(surface, GRASS_DARK, 
                                 (int(self.x - size//3 + i * size//3), int(self.y + size//4)), plant_size-1)
            
            # Show production
            if self.stored_resources['food'] > 0:
                farm_text = font_small.render(str(int(self.stored_resources['food'])), True, WHITE)
                surface.blit(farm_text, (int(self.x - 5), int(self.y - 8)))
        elif self.building_type == 'workshop':
            # Orange workshop with tools - using palette colors
            shadow_surface = pygame.Surface((size + 4, size + 4), pygame.SRCALPHA)
            shadow_rect = pygame.Rect(2, 2, size, size)
            pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_rect)
            surface.blit(shadow_surface, (int(self.x - size//2 - 2), int(self.y - size//2 - 2)))
            
            pygame.draw.rect(surface, BLACK, (rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4))  # Frame
            pygame.draw.rect(surface, EXPLORER_COLOR, rect)
            pygame.draw.rect(surface, BLACK, rect, 2)
            
            # Draw tools (hammer icon) - improved
            pygame.draw.line(surface, BLACK, (int(self.x - size//3), int(self.y - size//3)), (int(self.x + size//3), int(self.y + size//3)), 3)
            pygame.draw.circle(surface, BLACK, (int(self.x - size//3), int(self.y - size//3)), 4)
        elif self.building_type == 'shrine':
            # Purple shrine with spire - using palette colors
            shadow_surface = pygame.Surface((size + 4, size + 4), pygame.SRCALPHA)
            shadow_rect = pygame.Rect(2, 2, size, size)
            pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_rect)
            surface.blit(shadow_surface, (int(self.x - size//2 - 2), int(self.y - size//2 - 2)))
            
            pygame.draw.rect(surface, BLACK, (rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4))  # Frame
            pygame.draw.rect(surface, GOLD, rect)  # Shrine color changed to gold
            pygame.draw.rect(surface, BLACK, rect, 2)
            
            # Spire
            spire_points = [(self.x, self.y - size//2), (self.x - size//3, self.y - size//2 - size//3), (self.x + size//3, self.y - size//2 - size//3)]
            pygame.draw.polygon(surface, BLACK, spire_points)
        elif self.building_type == 'well':
            # Cyan well with water - using palette colors
            shadow_surface = pygame.Surface((size + 4, size + 4), pygame.SRCALPHA)
            shadow_rect = pygame.Rect(2, 2, size, size)
            pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_rect)
            surface.blit(shadow_surface, (int(self.x - size//2 - 2), int(self.y - size//2 - 2)))
            
            pygame.draw.rect(surface, BLACK, (rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4))  # Frame
            pygame.draw.rect(surface, BLUE, rect)
            pygame.draw.rect(surface, BLACK, rect, 2)
            
            # Water inside - using palette
            water_rect = pygame.Rect(int(self.x - size//3), int(self.y - size//6), int(size*2/3), int(size*2/3))
            pygame.draw.rect(surface, WATER_SHALLOW, water_rect)
        elif self.building_type == 'hospital':
            # White hospital with red cross
            shadow_surface = pygame.Surface((size + 4, size + 4), pygame.SRCALPHA)
            shadow_rect = pygame.Rect(2, 2, size, size)
            pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_rect)
            surface.blit(shadow_surface, (int(self.x - size//2 - 2), int(self.y - size//2 - 2)))
            
            pygame.draw.rect(surface, BLACK, (rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4))  # Frame
            pygame.draw.rect(surface, WHITE, rect)
            pygame.draw.rect(surface, BLACK, rect, 2)
            
            # Red cross
            cross_thickness = max(2, int(size * 0.15))
            cross_length = int(size * 0.6)
            pygame.draw.rect(surface, (200, 40, 40), (self.x - cross_thickness//2, self.y - cross_length//2, cross_thickness, cross_length))
            pygame.draw.rect(surface, (200, 40, 40), (self.x - cross_length//2, self.y - cross_thickness//2, cross_length, cross_thickness))
            
        elif self.building_type == 'school':
            # Blue academy
            shadow_surface = pygame.Surface((size + 4, size + 4), pygame.SRCALPHA)
            shadow_rect = pygame.Rect(2, 2, size, size)
            pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_rect)
            surface.blit(shadow_surface, (int(self.x - size//2 - 2), int(self.y - size//2 - 2)))
            
            pygame.draw.rect(surface, BLACK, (rect.x - 2, rect.y - 2, rect.width + 4, rect.height + 4))  # Frame
            pygame.draw.rect(surface, (80, 130, 200), rect)
            pygame.draw.rect(surface, BLACK, rect, 2)
            
            # Open book symbol
            pygame.draw.line(surface, WHITE, (self.x - 4, self.y - 3), (self.x, self.y), 2)
            pygame.draw.line(surface, WHITE, (self.x, self.y), (self.x + 4, self.y - 3), 2)
            pygame.draw.line(surface, WHITE, (self.x, self.y), (self.x, self.y + 4), 2)
            
        elif self.building_type == 'watchtower':
            # Tall wooden tower
            shadow_surface = pygame.Surface((size + 4, size + 10), pygame.SRCALPHA)
            pygame.draw.rect(shadow_surface, (0, 0, 0, 100), (2, 2, size-4, size+6))
            surface.blit(shadow_surface, (int(self.x - size//2 - 2), int(self.y - size//2 - 6)))
            
            tower_rect = pygame.Rect(self.x - size//3, self.y - size//2 - 8, size*2//3, size + 8)
            pygame.draw.rect(surface, BLACK, (tower_rect.x - 2, tower_rect.y - 2, tower_rect.width + 4, tower_rect.height + 4))
            pygame.draw.rect(surface, DIRT_MID, tower_rect)
            pygame.draw.rect(surface, BLACK, tower_rect, 2)
            
            # Platform on top
            pygame.draw.rect(surface, ROCK_DARK, (self.x - size//2, self.y - size//2 - 8, size, 4))
            
        elif self.building_type == 'market':
            # Wide market with tents
            shadow_surface = pygame.Surface((size + 10, size), pygame.SRCALPHA)
            pygame.draw.rect(shadow_surface, (0, 0, 0, 100), (2, 2, size+6, size-4))
            surface.blit(shadow_surface, (int(self.x - size//2 - 5), int(self.y - size//2 + 2)))
            
            market_rect = pygame.Rect(self.x - size//2 - 4, self.y - size//2 + 4, size + 8, size - 4)
            pygame.draw.rect(surface, BLACK, (market_rect.x - 2, market_rect.y - 2, market_rect.width + 4, market_rect.height + 4))
            pygame.draw.rect(surface, (230, 180, 80), market_rect)
            pygame.draw.rect(surface, BLACK, market_rect, 2)
            
            # Tent stripes
            pygame.draw.line(surface, (200, 60, 60), (market_rect.x + 4, market_rect.y), (market_rect.x + 4, market_rect.y + market_rect.height), 3)
            pygame.draw.line(surface, (200, 60, 60), (market_rect.x + market_rect.width - 4, market_rect.y), (market_rect.x + market_rect.width - 4, market_rect.y + market_rect.height), 3)

        if self.level > 1:
            banner_y = int(self.y - size // 2 - 8)
            for tier in range(self.level - 1):
                banner_x = int(self.x - 5 + tier * 6)
                pygame.draw.circle(surface, BLACK, (banner_x, banner_y), 4)
                pygame.draw.circle(surface, GOLD, (banner_x, banner_y), 3)


class ObserverOverlay:
    """Read-only observer HUD for the autonomous simulation."""

    def draw(self, surface, advisor, camera):
        panel_w = min(980, WINDOW_WIDTH - 40)
        panel_h = 78
        panel_x = WINDOW_WIDTH // 2 - panel_w // 2
        panel_y = 10

        panel = pygame.Surface((panel_w, panel_h))
        panel.set_alpha(220)
        panel.fill((18, 22, 34))
        surface.blit(panel, (panel_x, panel_y))
        pygame.draw.rect(surface, (120, 150, 200), (panel_x, panel_y, panel_w, panel_h), 2)

        scenario_name = advisor.session_stats.get("scenario_name", ACTIVE_SCENARIO_PROFILE.get("name", "Standard Basin"))
        title = font_small.render(f"AUTONOMOUS OBSERVER | {scenario_name[:24].upper()}", True, (200, 220, 255))
        surface.blit(title, (panel_x + 14, panel_y + 8))

        current_summary = dict(advisor.session_stats.get("current_run_summary", {}) or {})
        phase_label = current_summary.get("current_phase", {}).get("label", "Founding")
        observer_score = int(current_summary.get("end_state", {}).get("score", 0) or 0)
        doctrine = dict(advisor.session_stats.get("current_doctrine", {}) or {})
        llm_status = advisor.get_llm_status_label("offline")
        follow_state = "ON" if camera.follow_mode else "OFF"
        # Show multi-channel status when scheduler is active
        channel_info = ""
        if getattr(advisor, "llm_scheduler", None):
            stats = advisor.llm_scheduler.get_stats()
            total = sum(stats.get(ch, {}).get("completed", 0) for ch in stats if isinstance(stats.get(ch), dict))
            if total > 0:
                channel_info = f"  |  LLM calls: {total}"
        status = font_small.render(
            f"Advisor: {llm_status}  |  Phase: {phase_label}  |  Score: {observer_score}  |  Follow: {follow_state}{channel_info}",
            True,
            (160, 220, 170),
        )
        surface.blit(status, (panel_x + 14, panel_y + 28))

        doctrine_text = (
            f"Doctrine: {str(doctrine.get('focus', 'survival')).replace('_', ' ').title()} / "
            f"{str(doctrine.get('stance', 'measured')).title()}"
        )
        surface.blit(font_small.render(doctrine_text[:42], True, (230, 210, 165)), (panel_x + 14, panel_y + 48))

        controls = font_small.render(
            "Mouse inspect/pan  |  1/2/5 speed  |  F follow  |  R research  |  S evolution  |  T analytics  |  A archive  |  +/- zoom",
            True,
            (180, 180, 205),
        )
        surface.blit(controls, (panel_x + 310, panel_y + 48))


class GameLogger:
    """Handles comprehensive logging and session reports"""
    def __init__(self, log_dir=None, log_level=None, session_tag=None):
        self.session_start_time = datetime.now()
        self.session_id = f"{self.session_start_time.strftime('%Y%m%d_%H%M%S_%f')}_{os.getpid()}"
        self.log_dir = log_dir or RUNTIME_CONFIG.log_dir
        self.session_tag = str(session_tag or getattr(RUNTIME_CONFIG, "session_tag", "") or "")
        self.crash_count = 0
        self.error_log = []
        self.game_events = []
        self.log_level_name = (log_level or RUNTIME_CONFIG.log_level).upper()
        self.log_level = getattr(logging, self.log_level_name, logging.INFO)
        self.telemetry_count = 0
        self.last_telemetry_sample = None
        
        # Create logs directory if it doesn't exist
        os.makedirs(self.log_dir, exist_ok=True)
        
        # Setup logging configuration with immediate flushing for crash safety
        log_file = os.path.join(self.log_dir, f"session_{self.session_id}.log")
        
        # Create file handler with rotation to prevent runaway log growth
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=2_000_000,
            backupCount=3,
            encoding='utf-8',
        )
        file_handler.setLevel(self.log_level)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        
        # Route normal runtime logs to stdout so PowerShell launchers do not
        # surface them as native-command errors when verbose logging is enabled.
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG if self.log_level == logging.DEBUG else logging.WARNING)
        console_handler.setFormatter(formatter)
        
        # Setup root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)
        root_logger.handlers.clear()  # Clear any existing handlers
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

        for logger_name in ("httpcore", "httpx", "urllib3", "asyncio"):
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        
        # Force immediate flush after each log
        file_handler.stream.flush()
        
        self.logger = logging.getLogger(__name__)
        self.log_file = log_file  # Store for reference
        self.file_handler = file_handler  # Keep reference for flushing
        self.telemetry_file = os.path.join(self.log_dir, f"telemetry_{self.session_id}.jsonl")
        self.telemetry_handle = open(self.telemetry_file, 'a', encoding='utf-8')
        
        # Log session start
        self.logger.info(f"Game session started: {self.session_id}")
        self.logger.info(f"Log file location: {os.path.abspath(log_file)}")
        if self.session_tag:
            self.logger.info(f"Session tag: {self.session_tag}")
        self.flush_logs()  # Ensure it's written
    
    def flush_logs(self):
        """Force flush all log handlers to ensure data is written"""
        if hasattr(self, 'file_handler'):
            self.file_handler.flush()
        if hasattr(self, 'telemetry_handle') and self.telemetry_handle:
            self.telemetry_handle.flush()
        for handler in logging.getLogger().handlers:
            if hasattr(handler, 'flush'):
                handler.flush()
    
    def log_event(self, event_type, message, data=None):
        """Log a game event with immediate flush"""
        event = {
            'timestamp': time.time(),
            'type': event_type,
            'message': message,
            'data': data
        }
        self.game_events.append(event)
        self.logger.info(f"[{event_type}] {message}")
        self.flush_logs()  # Immediate flush for crash safety
    
    def log_error(self, error_message, exc_info=None):
        """Log an error with full traceback and immediate flush"""
        self.crash_count += 1
        error_entry = {
            'timestamp': datetime.now().isoformat(),
            'error': error_message,
            'traceback': traceback.format_exc() if exc_info else None
        }
        self.error_log.append(error_entry)
        self.logger.error(f"ERROR: {error_message}", exc_info=exc_info)
        self.flush_logs()  # Immediate flush for crashes
        
        # Also write critical errors to a separate crash log with full context
        if exc_info:
            crash_file = os.path.join(self.log_dir, f"crash_{self.session_id}_{self.crash_count}.log")
            try:
                with open(crash_file, 'w', encoding='utf-8') as f:
                    f.write(f"{'='*80}\n")
                    f.write(f"CRASH #{self.crash_count} at {datetime.now().isoformat()}\n")
                    f.write(f"{'='*80}\n\n")
                    f.write(f"Session ID: {self.session_id}\n")
                    f.write(f"Session Log: {os.path.abspath(self.log_file) if hasattr(self, 'log_file') else 'N/A'}\n")
                    f.write(f"Batch Log: Check logs\\batch_*.log for complete console output\n\n")
                    f.write(f"{'='*80}\n")
                    f.write(f"ERROR: {error_message}\n")
                    f.write(f"{'='*80}\n\n")
                    f.write("FULL TRACEBACK:\n")
                    f.write(traceback.format_exc())
                    f.write(f"\n\n{'='*80}\n")
                    f.write("RECENT LOG EVENTS (last 20):\n")
                    f.write(f"{'='*80}\n")
                    for event in self.game_events[-20:]:
                        f.write(f"[{event['type']}] {event['message']}\n")
                    f.write(f"\n{'='*80}\n")
                    f.write("ALL ERRORS IN THIS SESSION:\n")
                    f.write(f"{'='*80}\n")
                    for i, err in enumerate(self.error_log, 1):
                        f.write(f"\nError #{i}:\n")
                        f.write(f"  Time: {err.get('timestamp', 'Unknown')}\n")
                        f.write(f"  Message: {err.get('error', 'Unknown')}\n")
                        if err.get('traceback'):
                            f.write(f"  Traceback: {err['traceback']}\n")
                    f.flush()  # Ensure crash log is written
                    os.fsync(f.fileno())  # Force OS to write to disk
                self.logger.info(f"Crash log saved to: {os.path.abspath(crash_file)}")
                self.flush_logs()
                # Also print location to console
                print(f"\n{'='*80}")
                print(f"CRASH LOG SAVED: {os.path.abspath(crash_file)}")
                print(f"SESSION LOG: {os.path.abspath(self.log_file) if hasattr(self, 'log_file') else 'N/A'}")
                print(f"BATCH LOG: Check logs\\batch_*.log for complete console output")
                print(f"{'='*80}\n")
            except Exception as e:
                # Even if crash log fails, at least try to log it
                print(f"CRITICAL: Failed to write crash log: {e}")
                traceback.print_exc()

    def log_telemetry(self, sample):
        """Append a structured telemetry sample to the session telemetry log."""
        if not isinstance(sample, dict):
            return
        try:
            self.telemetry_handle.write(json.dumps(sample, sort_keys=True) + "\n")
            self.telemetry_handle.flush()
            self.telemetry_count += 1
            self.last_telemetry_sample = dict(sample)
            population = sample.get("population", 0)
            buildings = sample.get("buildings_total", 0)
            elapsed = sample.get("elapsed_seconds", 0.0)
            phase_id = dict(sample.get("advisor", {}) or {}).get("phase_id", "")
            self.logger.debug(
                "[telemetry] t=%.1fs pop=%s buildings=%s phase=%s",
                float(elapsed),
                population,
                buildings,
                phase_id or "unknown",
            )
        except Exception:
            self.logger.exception("Failed to write telemetry sample")
    
    def generate_session_report(self, game_state=None):
        """Generate comprehensive session report"""
        session_end_time = datetime.now()
        duration = session_end_time - self.session_start_time
        
        report = {
            'session_id': self.session_id,
            'start_time': self.session_start_time.isoformat(),
            'end_time': session_end_time.isoformat(),
            'duration_seconds': duration.total_seconds(),
            'duration_formatted': str(duration),
            'session_tag': self.session_tag,
            'crash_count': self.crash_count,
            'total_events': len(self.game_events),
            'telemetry_file': os.path.abspath(self.telemetry_file),
            'telemetry_samples': self.telemetry_count,
            'last_telemetry': self.last_telemetry_sample,
            'game_state': game_state,
            'errors': self.error_log
        }
        
        # Save report to JSON
        report_file = os.path.join(self.log_dir, f"report_{self.session_id}.json")
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        
        self.logger.info(f"Session report saved to {report_file}")
        return report_file
    
    def save_quick_report(self):
        """Quick summary report for the console"""
        duration = datetime.now() - self.session_start_time
        print("\n" + "="*80)
        print("SESSION REPORT")
        print("="*80)
        print(f"Duration: {str(duration)} ({duration.total_seconds():.1f}s)")
        print(f"Total Events: {len(self.game_events)}")
        print(f"Errors/Crashes: {self.crash_count}")
        if self.error_log:
            print("\nErrors encountered:")
            for i, error in enumerate(self.error_log, 1):
                print(f"  {i}. {error.get('error', 'Unknown error')}")
        print("="*80)


def center_camera_on_colony(camera, praxans, buildings):
    anchors = [(praxan.x, praxan.y) for praxan in praxans]
    anchors.extend((building.x, building.y) for building in buildings)
    if not anchors:
        return

    center_x = sum(anchor[0] for anchor in anchors) / len(anchors)
    center_y = sum(anchor[1] for anchor in anchors) / len(anchors)
    camera.x = max(0, min(center_x - WINDOW_WIDTH / 2, camera.world_width - WINDOW_WIDTH))
    camera.y = max(0, min(center_y - WINDOW_HEIGHT / 2, camera.world_height - WINDOW_HEIGHT))


def restore_session_from_snapshot(
    snapshot,
    world_width,
    world_height,
    advisor,
    season,
    weather_system,
    world_map=None,
    fog_of_war=None,
    territory_manager=None,
    faction_manager=None,
    city_planner=None,
    praxan_class=None,
):
    """Restore the core colony state from a saved session snapshot."""
    now = time.time()
    saved_at = float(snapshot.get("saved_at", now) or now)
    elapsed_seconds = max(0.0, float(snapshot.get("elapsed_seconds", 0.0)))

    def _parse_optional_int(value, default=None):
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _parse_coordinate_entry(entry):
        if isinstance(entry, dict):
            try:
                return (float(entry.get("x", 0.0)), float(entry.get("y", 0.0)))
            except (TypeError, ValueError):
                return None
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            try:
                return (float(entry[0]), float(entry[1]))
            except (TypeError, ValueError):
                return None
        return None

    def _rebase_timestamp(saved_timestamp):
        if saved_timestamp in (None, 0, 0.0):
            return 0.0
        try:
            saved_timestamp = float(saved_timestamp)
        except (TypeError, ValueError):
            return 0.0
        if saved_timestamp <= 0.0:
            return 0.0
        paused_seconds = max(0.0, saved_at - saved_timestamp)
        return now - paused_seconds

    restored_praxans = []
    max_praxan_id = -1
    for praxan_data in snapshot.get("praxans", []):
        x = clamp(float(praxan_data.get("x", world_width / 2)), 50.0, world_width - 50.0)
        y = clamp(float(praxan_data.get("y", world_height / 2)), 50.0, world_height - 50.0)
        praxan = praxan_class(x, y)

        saved_id = int(praxan_data.get("id", praxan.id))
        praxan.id = saved_id
        max_praxan_id = max(max_praxan_id, saved_id)

        praxan.role = praxan_data.get("role")
        praxan.health = clamp(float(praxan_data.get("health", 100.0)), 0.0, 100.0)
        # Restore the personality baseline (base_mood), NOT the moodlet-affected happiness.
        # Old snapshots only have "happiness" (moodlet-inflated/deflated), which was incorrectly
        # baked into base_mood, causing spurious mental breaks post-load for grieving/sick praxans.
        # New snapshots include "base_mood" as a separate field; fall back to "happiness" for compat.
        _saved_base_mood = praxan_data.get("base_mood")
        if _saved_base_mood is not None:
            praxan.base_mood = clamp(float(_saved_base_mood), 0.0, 100.0)
        else:
            praxan.base_mood = clamp(float(praxan_data.get("happiness", praxan.base_mood)), 0.0, 100.0)
        praxan.morale = clamp(float(praxan_data.get("morale", praxan.morale)), 0.0, 100.0)
        praxan.inspiration = clamp(float(praxan_data.get("inspiration", praxan.inspiration)), 0.0, 100.0)
        praxan.favorite_biome = praxan_data.get("favorite_biome") if praxan_data.get("favorite_biome") in BIOME_TYPES else praxan.favorite_biome
        praxan.diseased = bool(praxan_data.get("diseased", False))
        praxan.resilience = float(praxan_data.get("resilience", praxan.resilience))
        praxan.settlement_prosperity = float(praxan_data.get("settlement_prosperity", praxan.settlement_prosperity))
        praxan.generation = max(0, int(praxan_data.get("generation", getattr(praxan, "generation", 0))))
        praxan.parent_ids = [
            parsed_parent_id
            for parsed_parent_id in (_parse_optional_int(parent_id) for parent_id in praxan_data.get("parent_ids", []))
            if parsed_parent_id is not None
        ]
        praxan.lineage_id = _parse_optional_int(praxan_data.get("lineage_id"), saved_id) or saved_id
        praxan.mutation_count = max(0, int(praxan_data.get("mutation_count", 0)))
        praxan.birth_origin = str(praxan_data.get("birth_origin", getattr(praxan, "birth_origin", "founder")))

        personality_data = praxan_data.get("personality", {})
        if isinstance(personality_data, dict):
            for trait_name in praxan.personality:
                trait_value = personality_data.get(trait_name, praxan.personality[trait_name])
                try:
                    praxan.personality[trait_name] = clamp(float(trait_value), 0.0, 1.0)
                except (TypeError, ValueError):
                    continue

        genetics_data = praxan_data.get("genetics", {})
        if isinstance(genetics_data, dict):
            for trait_name, trait_spec in GENETIC_TRAIT_SPECS.items():
                trait_value = genetics_data.get(trait_name, praxan.genetics.get(trait_name, 1.0))
                try:
                    praxan.genetics[trait_name] = clamp(float(trait_value), trait_spec["min"], trait_spec["max"])
                except (TypeError, ValueError):
                    continue

        skills_data = praxan_data.get("skills", {})
        if isinstance(skills_data, dict):
            for skill_name, skill_state in skills_data.items():
                if skill_name not in praxan.skills or not isinstance(skill_state, dict):
                    continue
                praxan.skills[skill_name]["level"] = max(
                    1,
                    min(MAX_SKILL_LEVEL, int(skill_state.get("level", praxan.skills[skill_name]["level"]))),
                )
                praxan.skills[skill_name]["xp"] = max(
                    0.0,
                    float(skill_state.get("xp", praxan.skills[skill_name]["xp"])),
                )

        bonds_data = praxan_data.get("bonds", {})
        praxan.bonds = {}
        if isinstance(bonds_data, dict):
            for other_id, bond_strength in bonds_data.items():
                parsed_other_id = _parse_optional_int(other_id)
                if parsed_other_id is None:
                    continue
                try:
                    praxan.bonds[parsed_other_id] = max(0.0, float(bond_strength))
                except (TypeError, ValueError):
                    continue

        # Restore opinions (interaction preconditions depend on these)
        opinions_data = praxan_data.get("opinions", {})
        praxan.opinions = {}
        if isinstance(opinions_data, dict):
            for other_id, opinion_score in opinions_data.items():
                parsed_other_id = _parse_optional_int(other_id)
                if parsed_other_id is None:
                    continue
                try:
                    praxan.opinions[parsed_other_id] = max(-100.0, min(100.0, float(opinion_score)))
                except (TypeError, ValueError):
                    continue

        # Restore typed relationships
        relationships_data = praxan_data.get("relationships", {})
        praxan.relationships = {}
        if isinstance(relationships_data, dict):
            for other_id, rel_type in relationships_data.items():
                parsed_other_id = _parse_optional_int(other_id)
                if parsed_other_id is not None and isinstance(rel_type, str):
                    praxan.relationships[parsed_other_id] = rel_type

        # Restore name (or regenerate deterministically)
        saved_name = praxan_data.get("name")
        if saved_name and isinstance(saved_name, str):
            praxan.name = saved_name

        # Restore Deep Traits — must override the random sample from __init__
        saved_traits = praxan_data.get("traits")
        if isinstance(saved_traits, list):
            valid_traits = [t for t in saved_traits if isinstance(t, str) and t in TRAIT_DEFINITIONS]
            if valid_traits:
                praxan.traits = valid_traits

        # Restore equipment (dicts with def data + quality, or None)
        saved_equipment = praxan_data.get("equipment", {})
        if isinstance(saved_equipment, dict):
            for slot in ('armor', 'weapon'):
                val = saved_equipment.get(slot)
                if isinstance(val, dict):
                    praxan.equipment[slot] = val
                else:
                    praxan.equipment[slot] = None

        praxan.faction_id = _parse_optional_int(praxan_data.get("faction_id"))
        praxan.known_resources = []
        for resource_entry in praxan_data.get("known_resources", []):
            parsed_resource = _parse_coordinate_entry(resource_entry)
            if not parsed_resource:
                continue
            resource_x = clamp(parsed_resource[0], 0.0, world_width)
            resource_y = clamp(parsed_resource[1], 0.0, world_height)
            praxan.known_resources.append((resource_x, resource_y))

        inventory = praxan_data.get("inventory", {})
        for resource_name in praxan.inventory:
            praxan.inventory[resource_name] = max(0, int(inventory.get(resource_name, 0)))

        needs = praxan_data.get("needs", {})
        for need_name in praxan.needs:
            praxan.needs[need_name] = clamp(float(needs.get(need_name, praxan.needs[need_name])), 0.0, 100.0)

        praxan.state = praxan_data.get("state") or STATE_IDLE
        praxan.current_action = praxan_data.get("current_action") or "wander"
        praxan.personal_goal = praxan_data.get("personal_goal")
        praxan.goal_progress = clamp(float(praxan_data.get("goal_progress", 0.0)), 0.0, 1.0)

        # Restore aspiration / life goals state
        saved_aspiration = praxan_data.get("aspiration")
        if isinstance(saved_aspiration, dict) and saved_aspiration.get("id"):
            praxan.aspiration = saved_aspiration
        else:
            praxan.aspiration = None
        praxan._completed_aspirations = list(praxan_data.get("completed_aspirations", []))

        # Mentorship state (relationship managed by MentorshipManager.restore_praxan_mentorships)
        saved_mentorship = praxan_data.get("mentorship")
        praxan.mentorship = saved_mentorship if isinstance(saved_mentorship, dict) else None

        age_seconds = max(0.0, float(praxan_data.get("age_seconds", elapsed_seconds)))
        praxan.birth_time = now - age_seconds
        praxan.age = age_seconds
        disease_elapsed = max(0.0, float(praxan_data.get("disease_elapsed", 0.0)))
        praxan.disease_start_time = now - disease_elapsed if praxan.diseased and disease_elapsed > 0 else 0.0

        # Restore typed diseases
        typed_disease_data = praxan_data.get("typed_diseases", [])
        immunity_data = praxan_data.get("disease_immunities", {})
        if typed_disease_data or immunity_data:
            try:
                from systems.disease import DiseaseManager
                if typed_disease_data:
                    DiseaseManager.deserialize_diseases(praxan, typed_disease_data)
                if immunity_data:
                    DiseaseManager.deserialize_immunities(praxan, immunity_data)
            except Exception:
                pass
        reproduction_elapsed = max(0.0, float(praxan_data.get("last_reproduction_elapsed", 0.0)))
        praxan.last_reproduction_time = now - reproduction_elapsed if reproduction_elapsed > 0 else 0.0
        goal_assigned_elapsed = max(0.0, float(praxan_data.get("goal_assigned_elapsed", 0.0)))
        praxan.goal_assigned_time = now - goal_assigned_elapsed if goal_assigned_elapsed > 0 else 0.0
        praxan.alive = praxan.health > 0
        restored_praxans.append(praxan)

    if max_praxan_id >= 0:
        praxan_class._next_id = max_praxan_id + 1

    praxan_lookup = {praxan.id: praxan for praxan in restored_praxans}
    restored_buildings = []
    building_occupancy_refs = []
    for building_data in snapshot.get("buildings", []):
        building_type = building_data.get("type")
        if building_type not in BUILDING_DEFINITIONS:
            continue

        x = clamp(float(building_data.get("x", world_width / 2)), 50.0, world_width - 50.0)
        y = clamp(float(building_data.get("y", world_height / 2)), 50.0, world_height - 50.0)
        building = Building(x, y, building_type)
        built_elapsed = max(0.0, float(building_data.get("built_elapsed", 120.0)))
        building.built_at = now - built_elapsed if built_elapsed > 0 else now
        building.level = max(1, int(building_data.get("level", 1)))
        building.built_by = building_data.get("built_by")
        building.aura_strength = clamp(float(building_data.get("aura_strength", 0.0)), 0.0, 1.0)
        building.origin_biome = str(building_data.get("origin_biome")) if building_data.get("origin_biome") else None
        material_style = building_data.get("material_style")
        building.material_style = str(material_style) if material_style else None
        building.wear = clamp(float(building_data.get("wear", 0.08)), 0.0, 1.0)
        building.construction_progress = clamp(float(building_data.get("construction_progress", 1.0)), 0.0, 1.0)

        stored_resources = building_data.get("stored_resources", {})
        for resource_name in building.stored_resources:
            building.stored_resources[resource_name] = max(0.0, float(stored_resources.get(resource_name, 0.0)))

        # Restore pending crafting bills
        saved_bills = building_data.get("bills", [])
        if isinstance(saved_bills, list):
            building.bills = [b for b in saved_bills if isinstance(b, str) and b in JOB_DEFS]

        restored_buildings.append(building)
        building_occupancy_refs.append((building, building_data.get("occupant_ids", [])))

    for building, occupant_ids in building_occupancy_refs:
        building.occupants = [
            praxan_lookup[occupant_id]
            for occupant_id in (_parse_optional_int(saved_id) for saved_id in occupant_ids)
            if occupant_id in praxan_lookup
        ]

    restored_resources = []
    for resource_data in snapshot.get("resources", []):
        resource_type = resource_data.get("type", "food")
        if resource_type not in ("food", "wood", "stone"):
            continue

        x = clamp(float(resource_data.get("x", world_width / 2)), 50.0, world_width - 50.0)
        y = clamp(float(resource_data.get("y", world_height / 2)), 50.0, world_height - 50.0)
        resource = Resource(x, y, resource_type)
        resource.collected = bool(resource_data.get("collected", False))
        if resource.collected and resource.resource_type == "food":
            remaining_seconds = clamp(float(resource_data.get("respawn_remaining", 0.0)), 0.0, RESOURCE_RESPAWN_TIME)
            resource.collect_time = now - max(0.0, RESOURCE_RESPAWN_TIME - remaining_seconds)
        elif resource.collected:
            resource.collect_time = now
        restored_resources.append(resource)

    advisor_data = snapshot.get("advisor", {})
    advisor.research_points = int(advisor_data.get("research_points", advisor.research_points))
    advisor.points_spent = int(advisor_data.get("points_spent", advisor.points_spent))
    advisor.stability_counter = int(advisor_data.get("stability_counter", advisor.stability_counter))
    advisor.query_count = int(advisor_data.get("query_count", advisor.query_count))
    advisor.current_focus = advisor_data.get("current_focus", advisor.current_focus)
    advisor.directives = list(advisor_data.get("directives", []))
    advisor.json_directives = dict(advisor_data.get("json_directives", advisor.json_directives))
    advisor.council_state = dict(advisor_data.get("council_state", advisor.council_state))
    advisor.advisory_history = list(advisor_data.get("advisory_history", advisor.advisory_history))
    advisor.session_stats.update(dict(advisor_data.get("session_stats", {})))
    advisor.session_stats.setdefault("buildings_built", {})
    advisor.session_stats.setdefault("deaths_by_cause", {})
    advisor.session_stats.setdefault("avg_survival_time", 0)
    advisor.session_stats.setdefault("successful_strategies", [])
    advisor.session_stats.setdefault("births_total", 0)
    advisor.session_stats.setdefault("highest_generation", 0)
    advisor.session_stats.setdefault("peak_founder_lines", 0)
    advisor.session_stats.setdefault("peak_factions", 0)
    advisor.session_stats.setdefault("factions_formed", 0)
    advisor.session_stats.setdefault("factions_dissolved", 0)
    advisor.session_stats.setdefault("faction_schisms", 0)
    advisor.session_stats.setdefault("faction_successions", 0)
    advisor.session_stats.setdefault("migration_events", 0)
    advisor.session_stats.setdefault("lineage_events", [])
    advisor.session_stats.setdefault("evolution_history", [])
    advisor.session_stats.setdefault("current_evolution_summary", {})
    advisor.session_stats.setdefault("timeline_events", [])
    advisor.session_stats.setdefault("faction_history", [])
    advisor.session_stats.setdefault("current_run_summary", {})
    for lineage_event in advisor.session_stats.get("lineage_events", []):
        if isinstance(lineage_event, dict) and "time" in lineage_event:
            lineage_event["time"] = _rebase_timestamp(lineage_event.get("time"))
    for timeline_event in advisor.session_stats.get("timeline_events", []):
        if isinstance(timeline_event, dict) and "time" in timeline_event:
            timeline_event["time"] = _rebase_timestamp(timeline_event.get("time"))
    for faction_event in advisor.session_stats.get("faction_history", []):
        if isinstance(faction_event, dict) and "time" in faction_event:
            faction_event["time"] = _rebase_timestamp(faction_event.get("time"))
    for advisory_event in advisor.advisory_history:
        if isinstance(advisory_event, dict) and "time" in advisory_event:
            advisory_event["time"] = _rebase_timestamp(advisory_event.get("time"))
    advisor.current_settlement_state = dict(advisor_data.get("settlement_state", advisor.current_settlement_state))
    advisor.intervention_stats.update(dict(advisor_data.get("intervention_stats", {})))
    advisor.active_challenges = []
    for challenge_data in advisor_data.get("active_challenges", []):
        if not isinstance(challenge_data, dict):
            continue
        remaining_seconds = max(0.0, float(challenge_data.get("remaining_seconds", 0.0)))
        if remaining_seconds <= 0.0:
            continue
        restored_challenge = dict(challenge_data)
        restored_challenge.pop("remaining_seconds", None)
        restored_challenge["start_time"] = now
        restored_challenge["duration"] = remaining_seconds
        advisor.active_challenges.append(restored_challenge)
    advisor.civilization_age = int(advisor_data.get("civilization_age", advisor.civilization_age))
    advisor.total_deaths = int(advisor_data.get("total_deaths", advisor.total_deaths))
    advisor.achievements = list(advisor_data.get("achievements", advisor.achievements))
    advisor.history = list(advisor_data.get("history", advisor.history))
    advisor.events_history = list(advisor_data.get("events_history", advisor.events_history))
    for event in advisor.events_history:
        if isinstance(event, dict) and "time" in event:
            event["time"] = _rebase_timestamp(event.get("time"))
    advisor.last_model_used = advisor_data.get("last_model_used", advisor.last_model_used)
    advisor.group_tasks = []
    for task_data in advisor_data.get("group_tasks", []):
        if not isinstance(task_data, dict):
            continue
        restored_task = GroupTask(
            task_data.get("task_type", "gather"),
            task_data.get("description", ""),
            required_count=max(1, int(task_data.get("required_count", 1))),
            target_location=_parse_coordinate_entry(task_data.get("target_location")),
            target_building_type=task_data.get("target_building_type"),
        )
        restored_task.assigned_praxans = [
            parsed_id
            for parsed_id in (_parse_optional_int(praxan_id) for praxan_id in task_data.get("assigned_praxans", []))
            if parsed_id is not None and parsed_id in praxan_lookup
        ]
        restored_task.active = bool(task_data.get("active", True))
        restored_task.faction_id = _parse_optional_int(task_data.get("faction_id"))
        created_elapsed = max(0.0, float(task_data.get("created_elapsed", 0.0)))
        restored_task.created_time = now - created_elapsed if created_elapsed > 0 else now
        advisor.group_tasks.append(restored_task)
    advisor.last_query_time = now
    advisor.last_goal_assignment = now
    advisor.last_pop_count = len(restored_praxans)
    advisor.last_llm_error = None

    # Restore LLM V2 memory from snapshot
    llm_memory_data = advisor_data.get("llm_memory", {})
    if isinstance(llm_memory_data, dict) and llm_memory_data:
        try:
            advisor.llm_memory = LLMMemory.deserialize(llm_memory_data)
            print(f"[Restore] LLM memory restored: {len(advisor.llm_memory.civilization.entries)} civ entries")
        except Exception as exc:
            print(f"[Restore] LLM memory restore failed (using fresh): {exc}")
            advisor.llm_memory = LLMMemory()

    restored_techs = advisor_data.get("tech_unlocked", [])
    advisor.game_modifiers.tech_unlocked = {tech_id for tech_id in restored_techs if tech_id in advisor.tech_tree}
    advisor.game_modifiers.permanent = dict(advisor_data.get("permanent_modifiers", advisor.game_modifiers.permanent))
    advisor.game_modifiers.temporary = {}
    for modifier_name, modifier_data in advisor_data.get("temporary_modifiers", {}).items():
        if not isinstance(modifier_data, dict):
            continue
        advisor.game_modifiers.temporary[modifier_name] = (
            float(modifier_data.get("value", 1.0)),
            now + max(0.0, float(modifier_data.get("remaining_seconds", 0.0))),
        )

    if snapshot.get("season") in ("spring", "summer", "autumn", "winter"):
        season.current = snapshot["season"]

    weather_system.current_weather = snapshot.get("weather", weather_system.current_weather)
    weather_system.next_event_time = now + max(5.0, float(snapshot.get("weather_next_event_in", 30.0)))
    active_ends_in = float(snapshot.get("weather_active_event_ends_in", 0.0))
    if weather_system.current_weather != "clear" and active_ends_in > 0.0:
        weather_system.active_event_end = now + active_ends_in
    else:
        weather_system.active_event_end = 0.0

    if fog_of_war is not None:
        fog_data = snapshot.get("fog_of_war", {})
        fog_of_war.fog_grid = {}
        if isinstance(fog_data, dict):
            fog_of_war.visibility_radius = max(16, int(fog_data.get("visibility_radius", fog_of_war.visibility_radius)))
            for tile_data in fog_data.get("tiles", []):
                if not isinstance(tile_data, dict):
                    continue
                tile_x = _parse_optional_int(tile_data.get("x"))
                tile_y = _parse_optional_int(tile_data.get("y"))
                visibility = _parse_optional_int(tile_data.get("visibility"), 255)
                if tile_x is None or tile_y is None or visibility is None:
                    continue
                fog_of_war.fog_grid[(tile_x, tile_y)] = max(0, min(255, visibility))

    if territory_manager is not None:
        territory_manager.territory_grid = {}
        territory_data = snapshot.get("territory", {})
        if isinstance(territory_data, dict):
            for tile_data in territory_data.get("tiles", []):
                if not isinstance(tile_data, dict):
                    continue
                tile_x = _parse_optional_int(tile_data.get("x"))
                tile_y = _parse_optional_int(tile_data.get("y"))
                if tile_x is None or tile_y is None:
                    continue
                claim_strength = clamp(float(tile_data.get("claim_strength", 0.0)), 0.0, 100.0)
                claimed_elapsed = max(0.0, float(tile_data.get("claimed_elapsed", 0.0)))
                center_type = tile_data.get("center_type", "exploration")
                territory_manager.territory_grid[(tile_x, tile_y)] = {
                    "claim_strength": claim_strength,
                    "claimed_time": now - claimed_elapsed if claimed_elapsed > 0 else now,
                    "center_type": center_type if center_type in ("building", "exploration") else "exploration",
                }
        territory_manager.voronoi_cache = {}
        territory_manager.voronoi_seeds = []
        territory_manager.last_voronoi_calculation = now
        territory_manager.last_population_count = len(restored_praxans) + len(restored_buildings)
        territory_manager.voronoi_cache_valid = False

    if city_planner is not None:
        city_planner_data = snapshot.get("city_planner", {})
        city_planner.zones = {}
        city_planner.current_plan = None
        city_planner.last_plan_update = 0
        if isinstance(city_planner_data, dict):
            for zone_data in city_planner_data.get("zones", []):
                if not isinstance(zone_data, dict):
                    continue
                zone_x = _parse_optional_int(zone_data.get("x"))
                zone_y = _parse_optional_int(zone_data.get("y"))
                zone_type = zone_data.get("zone_type", "mixed")
                if zone_x is None or zone_y is None:
                    continue
                city_planner.zones[(zone_x, zone_y)] = zone_type
            city_planner.current_plan = city_planner_data.get("current_plan")
            last_plan_elapsed = max(0.0, float(city_planner_data.get("last_plan_elapsed", 0.0)))
            city_planner.last_plan_update = now - last_plan_elapsed if last_plan_elapsed > 0 else 0

    if faction_manager is not None:
        faction_manager.factions = {}
        faction_manager.last_update = now
        max_faction_id = -1
        for praxan in restored_praxans:
            praxan.faction_id = None
        for faction_data in snapshot.get("factions", []):
            if not isinstance(faction_data, dict):
                continue
            member_ids = [
                member_id
                for member_id in (_parse_optional_int(raw_id) for raw_id in faction_data.get("member_ids", []))
                if member_id is not None and member_id in praxan_lookup
            ]
            if not member_ids:
                continue
            restored_faction = Faction(member_ids)
            saved_faction_id = _parse_optional_int(faction_data.get("id"), restored_faction.id)
            restored_faction.id = saved_faction_id
            restored_faction.leader_id = _parse_optional_int(faction_data.get("leader_id"))
            if restored_faction.leader_id not in member_ids:
                restored_faction.leader_id = member_ids[0]
            restored_faction.shared_goals = list(faction_data.get("shared_goals", []))
            restored_faction.ideology = dict(faction_data.get("ideology", restored_faction.ideology))
            restored_faction.cohesion = clamp(float(faction_data.get("cohesion", restored_faction.cohesion)), 0.0, 100.0)
            restored_faction.stability = clamp(float(faction_data.get("stability", restored_faction.stability)), 0.0, 100.0)
            restored_faction.schism_pressure = clamp(float(faction_data.get("schism_pressure", 0.0)), 0.0, 100.0)
            restored_faction.migration_pressure = clamp(float(faction_data.get("migration_pressure", 0.0)), 0.0, 100.0)
            restored_faction.primary_doctrine = str(faction_data.get("primary_doctrine", restored_faction.primary_doctrine))
            restored_faction.doctrine_profile = dict(
                FACTION_DOCTRINE_PROFILES.get(restored_faction.primary_doctrine, FACTION_DOCTRINE_PROFILES["growth"])
            )
            restored_faction.preferred_biome = str(faction_data.get("preferred_biome", restored_faction.preferred_biome))
            restored_target = _parse_coordinate_entry(faction_data.get("migration_target"))
            restored_faction.migration_target = restored_target if restored_target else None
            restored_faction.succession_count = max(0, int(faction_data.get("succession_count", 0) or 0))
            restored_faction.rival_faction_ids = [
                rival_id
                for rival_id in (_parse_optional_int(raw_id) for raw_id in faction_data.get("rival_faction_ids", []))
                if rival_id is not None
            ]
            last_succession_elapsed = max(0.0, float(faction_data.get("last_succession_elapsed", 0.0)))
            restored_faction.last_succession_time = now - last_succession_elapsed if last_succession_elapsed > 0 else 0.0
            last_schism_elapsed = max(0.0, float(faction_data.get("last_schism_elapsed", 0.0)))
            restored_faction.last_schism_time = now - last_schism_elapsed if last_schism_elapsed > 0 else 0.0
            last_migration_elapsed = max(0.0, float(faction_data.get("last_migration_elapsed", 0.0)))
            restored_faction.last_migration_time = now - last_migration_elapsed if last_migration_elapsed > 0 else 0.0
            last_resource_crisis_elapsed = max(0.0, float(faction_data.get("last_resource_crisis_elapsed", 0.0)))
            restored_faction.last_resource_crisis_time = now - last_resource_crisis_elapsed if last_resource_crisis_elapsed > 0 else 0.0
            formed_elapsed = max(0.0, float(faction_data.get("formed_elapsed", 0.0)))
            restored_faction.formed_time = now - formed_elapsed if formed_elapsed > 0 else now
            faction_manager.factions[saved_faction_id] = restored_faction
            max_faction_id = max(max_faction_id, saved_faction_id)
            for member_id in member_ids:
                praxan_lookup[member_id].faction_id = saved_faction_id
        if max_faction_id >= 0:
            Faction._next_id = max(Faction._next_id, max_faction_id + 1)
        for restored_faction in faction_manager.factions.values():
            restored_faction.refresh_identity(restored_praxans)
        faction_manager._update_rivalries()

    if world_map is not None:
        world_data = snapshot.get("world", {})
        if isinstance(world_data, dict):
            if hasattr(world_map, "apply_snapshot_world_state"):
                world_map.apply_snapshot_world_state(world_data)
            restored_encounters = []
            for encounter_data in world_data.get("encounters", []):
                if not isinstance(encounter_data, dict):
                    continue
                encounter_x = clamp(float(encounter_data.get("x", world_width / 2)), 0.0, world_width)
                encounter_y = clamp(float(encounter_data.get("y", world_height / 2)), 0.0, world_height)
                encounter_type = encounter_data.get("encounter_type", "ruins")
                restored_encounter = Encounter(encounter_x, encounter_y, encounter_type)
                restored_encounter.discovered = bool(encounter_data.get("discovered", False))
                restored_encounter.explored = bool(encounter_data.get("explored", False))
                restored_encounter.reward_given = bool(encounter_data.get("reward_given", False))
                restored_encounters.append(restored_encounter)
            if "encounters" in world_data:
                world_map.encounters = restored_encounters

            restored_hazards = []
            for hazard_data in world_data.get("hazards", []):
                if not isinstance(hazard_data, dict):
                    continue
                hazard_x = clamp(float(hazard_data.get("x", world_width / 2)), 0.0, world_width)
                hazard_y = clamp(float(hazard_data.get("y", world_height / 2)), 0.0, world_height)
                hazard_type = hazard_data.get("hazard_type", "predator_lair")
                restored_hazard = TerrainHazard(
                    hazard_x,
                    hazard_y,
                    hazard_type,
                    radius=max(10.0, float(hazard_data.get("radius", 100.0))),
                )
                restored_hazard.active = bool(hazard_data.get("active", True))
                restored_hazard.damage_rate = max(0.0, float(hazard_data.get("damage_rate", restored_hazard.damage_rate)))
                restored_hazards.append(restored_hazard)
            if "hazards" in world_data:
                world_map.hazards = restored_hazards

            restored_npcs = []
            for npc_data in world_data.get("npcs", []):
                if not isinstance(npc_data, dict):
                    continue
                npc_x = clamp(float(npc_data.get("x", world_width / 2)), 0.0, world_width)
                npc_y = clamp(float(npc_data.get("y", world_height / 2)), 0.0, world_height)
                npc_type = npc_data.get("npc_type", "trader")
                restored_npc = NPC(npc_x, npc_y, npc_type)
                restored_npc.visible = bool(npc_data.get("visible", True))
                restored_npc.inventory = dict(npc_data.get("inventory", restored_npc.inventory))
                restored_npc.trade_rates = dict(npc_data.get("trade_rates", getattr(restored_npc, "trade_rates", {})))
                restored_npc.hostile = bool(npc_data.get("hostile", restored_npc.hostile))
                restored_npc.reputation = int(npc_data.get("reputation", restored_npc.reputation))
                interaction_elapsed = max(0.0, float(npc_data.get("last_interaction_elapsed", 0.0)))
                restored_npc.last_interaction = now - interaction_elapsed if interaction_elapsed > 0 else 0
                restored_npcs.append(restored_npc)
            if "npcs" in world_data:
                world_map.npcs = restored_npcs

    celebration_center = None
    if restored_buildings:
        anchor = next(
            (building for building in restored_buildings if building.building_type in ("shrine", "workshop", "house")),
            restored_buildings[0],
        )
        celebration_center = (anchor.x, anchor.y)
    elif restored_praxans:
        celebration_center = (
            sum(praxan.x for praxan in restored_praxans) / len(restored_praxans),
            sum(praxan.y for praxan in restored_praxans) / len(restored_praxans),
        )

    settlement_state = compute_settlement_snapshot(restored_praxans, restored_buildings, None, season, weather_system)
    settlement_state.update(dict(advisor.current_settlement_state or {}))
    celebration_data = snapshot.get("celebration", {})
    if isinstance(celebration_data, dict):
        restored_center = _parse_coordinate_entry(celebration_data.get("center"))
        if restored_center:
            celebration_center = (
                clamp(restored_center[0], 0.0, world_width),
                clamp(restored_center[1], 0.0, world_height),
            )
        active_remaining = max(
            0.0,
            float(
                celebration_data.get(
                    "active_remaining",
                    settlement_state.get("festival_timer", 0.0) if settlement_state.get("festival_active") else 0.0,
                )
            ),
        )
        cooldown_remaining = max(
            0.0,
            float(celebration_data.get("cooldown_remaining", settlement_state.get("festival_timer", 0.0))),
        )
    else:
        active_remaining = max(
            0.0,
            float(settlement_state.get("festival_timer", 0.0) if settlement_state.get("festival_active") else 0.0),
        )
        cooldown_remaining = max(0.0, float(settlement_state.get("festival_timer", 0.0)))

    celebration_state = {
        "active_until": now + active_remaining if active_remaining > 0 else 0.0,
        "cooldown_until": now + cooldown_remaining,
        "last_particle_time": 0.0,
        "center": celebration_center,
    }

    snapshot_camera = snapshot.get("camera", {})
    camera_state = None
    if isinstance(snapshot_camera, dict):
        try:
            camera_state = {
                "x": float(snapshot_camera.get("x", 0.0)),
                "y": float(snapshot_camera.get("y", 0.0)),
                "zoom": float(snapshot_camera.get("zoom", 1.0)),
                "follow_mode": bool(snapshot_camera.get("follow_mode", True)),
            }
        except (TypeError, ValueError):
            camera_state = None

    return {
        "elapsed_seconds": elapsed_seconds,
        "selected_model": snapshot.get("selected_model"),
        "scenario_id": snapshot.get("scenario_id", DEFAULT_SCENARIO_ID) or DEFAULT_SCENARIO_ID,
        "run_summary": dict(snapshot.get("run_summary", {}) or {}),
        "praxans": restored_praxans,
        "buildings": restored_buildings,
        "resources": restored_resources,
        "settlement_state": settlement_state,
        "celebration_state": celebration_state,
        "camera_state": camera_state,
    }


def main(runtime_config=RUNTIME_CONFIG):
    """Main entry point"""
    global current_time_speed, screen, clock, WINDOW_WIDTH, WINDOW_HEIGHT, FPS
    global font, font_large, font_small, VERBOSE_LOGGING

    if not pygame.get_init():
        pygame.init()

    WINDOW_WIDTH = runtime_config.width
    WINDOW_HEIGHT = runtime_config.height
    FPS = runtime_config.fps
    VERBOSE_LOGGING = runtime_config.verbose_console
    font = pygame.font.Font(None, 32)
    font_large = pygame.font.Font(None, 48)
    font_small = pygame.font.Font(None, 24)

    if runtime_config.seed is not None:
        random.seed(runtime_config.seed)
    selected_scenario_id = runtime_config.scenario
    scenario_profile = set_active_scenario(selected_scenario_id)

    # Initialize the Content Authoring Pipeline
    from systems.def_database import DefDatabase
    DefDatabase.initialize("defs")

    # Initialize Mod Support (Pillar 7)
    from systems.mod_loader import ModLoader
    mod_loader = ModLoader("mods")
    mod_loader.discover()
    mod_loader.load_all(DefDatabase)
    
    # Initialize Staggered Ticking Engine
    from systems.ticker import TickManager
    tick_manager = TickManager()

    # Initialize Policy Manager (Pillar 2)
    from systems.policies import PolicyManager
    policy_manager = PolicyManager()

    # Initialize Dev Mode (Pillar 10)
    from systems.dev_mode import DevMode
    dev_mode = DevMode()

    # Initialize History Tracker (Pillar 4)
    from ui.history_graph import HistoryTracker, HistoryGraphRenderer
    history_tracker = HistoryTracker()
    history_renderer = HistoryGraphRenderer()

    # Initialize Quest System (Pillar 8)
    from systems.quests import QuestManager
    quest_manager = QuestManager()
    quest_manager.build_default_quests()
    quest_manager.start_quest("first_settlement")
    quest_manager.start_quest("feed_colony")
    quest_manager.start_quest("growing_community")

    # Initialize Search Overlay (Pillar 12)
    from ui.search_overlay import SearchOverlay
    search_overlay = SearchOverlay()

    # #region agent log
    log_path = os.path.join(runtime_config.log_dir, "probe_debug.log")
    def debug_log(location, message, data=None, hypothesis_id=None):
        if not runtime_config.enable_probe_log:
            return
        try:
            # Ensure directory exists
            log_dir = os.path.dirname(log_path)
            if not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            with open(log_path, 'a', encoding='utf-8') as f:
                log_entry = {
                    "timestamp": time.time() * 1000,
                    "location": location,
                    "message": message,
                    "data": data or {},
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": hypothesis_id
                }
                f.write(json.dumps(log_entry) + "\n")
                f.flush()  # Force write
        except Exception as e:
            # Print to console as fallback
            print(f"[DEBUG_LOG_ERROR] {location}: {message} - {e}")
    debug_log("main:entry", "Main function entered", {"screen_is_none": screen is None}, "H1")
    print("[DEBUG] Main function entered - logging initialized")
    # #endregion
    
    # Initialize display window first

    from systems.spatial import FogOfWar, TerritoryManager, CityPlanner
    from systems.society import Faction, FactionManager, TradeSystem
    from systems.diplomacy import DiplomacyManager
    from systems.disasters import DisasterManager
    from systems.advisor import CivilizationAdvisor
    from entities.praxan import Praxan
    if screen is None:
        try:
            try:
                os.environ.setdefault('SDL_VIDEO_WINDOW_POS', '100,100')
            except Exception:
                pass
            flags = 0 if runtime_config.headless else pygame.SCALED | pygame.RESIZABLE
            # #region agent log
            debug_log("main:screen_init_start", "Starting screen initialization", {"width": WINDOW_WIDTH, "height": WINDOW_HEIGHT}, "H3")
            # #endregion
            screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), flags)
            # #region agent log
            debug_log("main:screen_created", "Screen created", {"screen_is_none": screen is None, "screen_type": str(type(screen))}, "H3")
            # #endregion
            
            # Set window caption and icon
            pygame.display.set_caption("Praxans")
            try:
                icon_path = os.path.join(os.path.dirname(__file__), "assets", "ui", "icon_32.png")
                if os.path.exists(icon_path):
                    pygame.display.set_icon(pygame.image.load(icon_path))
            except Exception as e:
                print(f"Warning: Could not load window icon: {e}")
                
            clock = pygame.time.Clock()
            
            # Verify screen was created successfully
            print(f"[DEBUG] Screen created: {screen}")
            print(f"[DEBUG] Screen size: {screen.get_size()}")
            print(f"[DEBUG] Screen flags: {screen.get_flags()}")
            
            # #region agent log
            try:
                screen_size = screen.get_size() if screen else None
                debug_log("main:screen_verified", "Screen verified", {"size": screen_size}, "H3")
            except Exception as e:
                debug_log("main:screen_verify_failed", "Screen verification failed", {"error": str(e)}, "H3")
            # #endregion
            
            # Ensure the window shows immediately
            # #region agent log
            debug_log("main:flip_before_init", "About to flip display (initialization)", {}, "H4")
            # #endregion
            pygame.display.flip()
            # #region agent log
            debug_log("main:flip_after_init", "Display flipped (initialization)", {}, "H4")
            # #endregion
            print("Display window created")
            
            # On Windows, bring window to foreground and ensure it's visible
            if not runtime_config.headless:
                try:
                    import ctypes
                    if os.name == 'nt':  # Windows
                        wm_info = pygame.display.get_wm_info()
                        if 'window' in wm_info:
                            hwnd = wm_info['window']
                            # Show window normally (not minimized)
                            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                            # Bring to foreground
                            ctypes.windll.user32.SetForegroundWindow(hwnd)
                            # Force window update
                            ctypes.windll.user32.UpdateWindow(hwnd)
                            print("Window brought to foreground")
                except Exception as win_err:
                    print(f"Note: Could not bring window to foreground: {win_err}")
                    # Non-critical, continue if this fails
            
            # Additional flip to ensure window is visible
            # #region agent log
            debug_log("main:flip_before_init2", "About to flip display (second initialization)", {}, "H4")
            # #endregion
            pygame.display.flip()
            # #region agent log
            debug_log("main:flip_after_init2", "Display flipped (second initialization)", {}, "H4")
            # #endregion
        except Exception as e:
            # #region agent log
            debug_log("main:screen_init_error", "Screen initialization failed", {"error": str(e), "error_type": type(e).__name__}, "H3")
            # #endregion
            print(f"ERROR: Failed to create display window: {e}")
            traceback.print_exc()
            if not runtime_config.headless:
                input("Press Enter to exit...")
            return

    shell_choice = {
        "action": "start",
        "scenario_id": selected_scenario_id,
        "snapshot_path": resolve_snapshot_path(
            runtime_config.log_dir,
            snapshot_file=runtime_config.snapshot_file,
            load_latest=runtime_config.load_latest_snapshot,
        ),
    }
    if not runtime_config.headless and not runtime_config.snapshot_file and not runtime_config.load_latest_snapshot:
        screen, shell_choice = run_command_center(screen, clock, runtime_config, selected_scenario_id)
        if shell_choice.get("action") == "quit":
            try:
                pygame.quit()
            except Exception:
                pass
            return
            
        # [Phase 3] After command center, show Planet Select
        if shell_choice.get("action") == "start" and not shell_choice.get("snapshot_path"):
            from ui.planet_select import PlanetSelectUI
            planet_ui = PlanetSelectUI(screen, runtime_config, runtime_config.seed or 42)
            planet_choice = planet_ui.run()
            if planet_choice.get("action") == "quit":
                try:
                    pygame.quit()
                except Exception:
                    pass
                return
            # Pass the selected planet tile data into the shell_choice payload
            shell_choice["planet_tile"] = planet_choice.get("planet_tile")

    selected_scenario_id = str(shell_choice.get("scenario_id") or selected_scenario_id)
    scenario_profile = set_active_scenario(selected_scenario_id)

    # Refresh LLM client in case settings were modified in the command center
    if LLM_ENABLED:
        client_instance = _get_llm_client()
        if client_instance:
            try:
                client_instance.refresh_client()
            except Exception as e:
                print(f"[LLM] Warning: Failed to refresh client with new settings: {e}")

    # Initialize logging and crash tracking
    game_logger = GameLogger(
        log_dir=runtime_config.log_dir,
        log_level=runtime_config.log_level,
        session_tag=runtime_config.session_tag,
    )
    snapshot_resume_path = shell_choice.get("snapshot_path")
    snapshot_payload = None
    if snapshot_resume_path:
        try:
            snapshot_payload = load_run_snapshot(snapshot_resume_path)
            snapshot_scenario_id = str(snapshot_payload.get("scenario_id") or "").strip().lower()
            if snapshot_scenario_id and snapshot_scenario_id != scenario_profile["id"]:
                scenario_profile = set_active_scenario(snapshot_scenario_id)
                selected_scenario_id = snapshot_scenario_id
        except Exception as snapshot_error:
            print(f"[Snapshot] Failed to preload snapshot metadata: {snapshot_error}")
            snapshot_payload = None
    
    # Initialize LLM model selection (detect fastest available model)
    # Make this non-blocking to prevent hanging - use threading with timeout
    selected_model = None
    if LLM_ENABLED:
        print("Detecting fastest available LLM model...")
        import threading

        model_detection_done = threading.Event()

        def detect_model():
            nonlocal selected_model
            try:
                selected_model = get_fastest_available_model()
            except Exception as e:
                print(f"[LLM] Model detection error: {e}")
                selected_model = None
            finally:
                model_detection_done.set()

        # Start detection in background thread
        detection_thread = threading.Thread(target=detect_model, daemon=True)
        detection_thread.start()

        # Wait briefly for detection, then continue in safe mode.
        if model_detection_done.wait(timeout=OLLAMA_DETECTION_TIMEOUT_SECONDS):
            if selected_model:
                print(f"[LLM] Using model: {selected_model}")
            else:
                print("[LLM] WARNING: No LLM models available - AI features will be disabled")
                print(f"[LLM] Install a model with: ollama pull {PREFERRED_OLLAMA_MODEL}")
        else:
            print("[LLM] Model detection taking too long, continuing in guarded mode.")
            print("[LLM] Runtime requests will fail fast instead of blocking the game.")
            selected_model = None
    elif runtime_config.disable_llm:
        print("[LLM] Disabled via CLI")
    else:
        print("[LLM] Ollama package not installed - AI features will be disabled")
    
    # Register cleanup handlers to ensure logs are saved on crash/exit
    def emergency_flush():
        """Emergency flush logs on unexpected exit"""
        try:
            # game_logger is captured from the outer scope; it is not in this function's locals().
            game_logger.flush_logs()
            game_logger.logger.debug("Emergency exit flush completed")
            game_logger.flush_logs()
        except NameError:
            # Defensive fallback if registration happens before logger initialization.
            pass
        except Exception:
            pass  # Don't fail on exit
    
    atexit.register(emergency_flush)
    
    # Set up global exception handler to catch unhandled crashes
    def exception_handler(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions"""
        if exc_type == KeyboardInterrupt:
            game_logger.log_event("system", "Game interrupted by user")
            game_logger.flush_logs()
            return
        
        error_msg = f"Uncaught exception: {exc_type.__name__}: {exc_value}"
        game_logger.log_error(error_msg, exc_info=True)
        game_logger.flush_logs()
        
        # Also print to console
        print(f"\n{'='*80}")
        print("UNCAUGHT EXCEPTION - Check logs/ directory for details")
        print(f"{'='*80}")
        traceback.print_exception(exc_type, exc_value, exc_traceback)
    
    sys.excepthook = exception_handler
    
    game_logger.log_event("system", "Game starting")
    print(f"\n[LOGGING] Log files will be saved to: {os.path.abspath(game_logger.log_dir)}")
    print(f"[LOGGING] Session log: {os.path.abspath(game_logger.log_file)}\n")
    print(f"[LOGGING] Session telemetry: {os.path.abspath(game_logger.telemetry_file)}")
    print(f"[Scenario] {scenario_profile['name']} ({scenario_profile['id']})")
    
    print("Starting Praxans...")
    
    # Helper: draw a non-blocking loading message and pump events
    def _draw_loading(message):
        # Temporarily disable loading overlay to avoid stuck screen
        # Use console output only
        try:
            print(message)
            pygame.event.pump()
        except Exception:
            pass

    # Initialize world map and camera systems
    _draw_loading("Loading Praxans... Assets")
    asset_manager = AssetManager()
    print("Asset manager created")
    print(f"[DEBUG] Asset manager type: {type(asset_manager)}")
    _draw_loading("Loading Praxans... World")
    
    # [Phase 3] Check if a specific planet tile was selected to anchor the local map's climate
    planet_tile = None
    if locals().get("shell_choice") and "planet_tile" in shell_choice:
        planet_tile = shell_choice["planet_tile"]

    from systems.botany import BotanyManager
    from systems.zoology import ZoologyManager
    botany_manager = BotanyManager(rng_seed=runtime_config.seed)
    zoology_manager = ZoologyManager(rng_seed=runtime_config.seed)

    world_map = WorldMap(
        asset_manager,
        scenario_profile=scenario_profile,
        seed=runtime_config.seed,
        snapshot_world=(snapshot_payload or {}).get("world"),
        planet_tile=planet_tile,
        botany_manager=botany_manager,
        zoology_manager=zoology_manager,
    )
    print(f"World map created with {len(world_map.chunks)} chunks")
    
    # Chunks use lazy rendering now - surfaces will be created when first rendered
    print(f"[DEBUG] Chunks created: {len(world_map.chunks)} (surfaces will be created on first render)")
    world_width = int(getattr(world_map, "world_width", INITIAL_CHUNKS_X * CHUNK_SIZE))
    world_height = int(getattr(world_map, "world_height", INITIAL_CHUNKS_Y * CHUNK_SIZE))
    _draw_loading("Loading Praxans... Camera")
    camera = Camera(world_width, world_height)
    # Center camera on world initially to ensure chunks are visible
    camera.x = max(0, (world_width - WINDOW_WIDTH) / 2)
    camera.y = max(0, (world_height - WINDOW_HEIGHT) / 2)
    print(f"Camera initialized at ({camera.x:.1f}, {camera.y:.1f})")
    
    # Initialize praxans - CLUSTERED SPAWN
    praxans = []
    # Find safe spawn location (plains or forest biome preferred)
    safe_biomes = list(scenario_profile.get("spawn_biomes", ['plains', 'forest']))
    spawn_center_x, spawn_center_y = world_map.get_spawn_point(safe_biomes)
    
    print(f"Spawn center: ({spawn_center_x}, {spawn_center_y}) - Biome: {world_map.get_biome_at(spawn_center_x, spawn_center_y)}")
    
    # Center camera on spawn point and zoom in
    camera.x = max(0, min(spawn_center_x - WINDOW_WIDTH / 2, world_width - WINDOW_WIDTH))
    camera.y = max(0, min(spawn_center_y - WINDOW_HEIGHT / 2, world_height - WINDOW_HEIGHT))
    camera.zoom = 1.5
    camera.target_zoom = 1.5
    
    # Validate camera position and zoom
    if not (0 <= camera.x <= world_width) or not (0 <= camera.y <= world_height):
        print(f"[WARNING] Invalid camera position ({camera.x}, {camera.y}), resetting to center")
        camera.x = max(0, min(world_width / 2 - WINDOW_WIDTH / 2, world_width - WINDOW_WIDTH))
        camera.y = max(0, min(world_height / 2 - WINDOW_HEIGHT / 2, world_height - WINDOW_HEIGHT))
    
    if camera.zoom <= 0 or camera.zoom > camera.max_zoom:
        print(f"[WARNING] Invalid zoom {camera.zoom}, resetting to 1.5")
        camera.zoom = 1.5
        camera.target_zoom = 1.5

    # Ensure zoom is within bounds
    # (Previously set_zoom(camera.zoom))
    camera.target_zoom = camera.zoom
    camera.follow_mode = True
    
    print(f"Camera positioned at ({camera.x:.0f}, {camera.y:.0f}) with zoom {camera.zoom}")
    print(f"[DEBUG] Camera world size: {camera.world_width}x{camera.world_height}")
    print(f"[DEBUG] Window size: {WINDOW_WIDTH}x{WINDOW_HEIGHT}")
    
    _draw_loading("Loading Praxans... Spawning")
    # Spawn all praxans clustered around center
    initial_population = max(1, int(scenario_profile.get("initial_population", INITIAL_POPULATION)))
    for _ in range(initial_population):
        angle = random.uniform(0, 2 * math.pi)
        distance = random.uniform(10, 30)  # 10-30 pixels from center
        x = spawn_center_x + distance * math.cos(angle)
        y = spawn_center_y + distance * math.sin(angle)
        # Ensure within bounds
        x = max(50, min(world_width - 50, x))
        y = max(50, min(world_height - 50, y))
        founder = Praxan(x, y)
        founder.age = LIFE_STAGE_YOUTH  # Start founders as adults; age=0 triggers infant logic
        founder.birth_time = founder.birth_time - LIFE_STAGE_YOUTH  # Keep birth_time consistent so update_age_and_health() doesn't reset age to ~0
        praxans.append(founder)

    _draw_loading("Loading Praxans... Resources")
    # Initialize resources
    resources = []
    
    # First, spawn guaranteed resources near spawn center for early game
    starting_resources = dict(scenario_profile.get("starting_resources", {"food": 5, "wood": 3, "stone": 1}))
    spawn_resource_cluster(
        resources,
        spawn_center_x,
        spawn_center_y,
        starting_resources.get("food", 5),
        "food",
        world_width,
        world_height,
        40,
        80,
    )
    
    _draw_loading("Loading Praxans... Resources")
    spawn_resource_cluster(
        resources,
        spawn_center_x,
        spawn_center_y,
        starting_resources.get("wood", 3),
        "wood",
        world_width,
        world_height,
        40,
        80,
    )
    
    _draw_loading("Loading Praxans... Resources")
    spawn_resource_cluster(
        resources,
        spawn_center_x,
        spawn_center_y,
        starting_resources.get("stone", 1),
        "stone",
        world_width,
        world_height,
        50,
        100,
    )
    
    # Then spawn rest of resources across the map ASYNCHRONOUSLY over frames
    pending_resource_spawns = dict(scenario_profile.get("queued_resources", {'food': 45, 'wood': 32, 'stone': 14}))
    
    # Initialize buildings list
    buildings = []
    
    # Initialize civilization advisor
    advisor = CivilizationAdvisor()
    
    # Load legacy data and apply bonuses
    legacy_data = load_legacy_data()
    print(f"[Legacy] Loaded: Runs={legacy_data.get('total_runs', 0)}, Best Pop={legacy_data.get('best_population', 0)}")
    unlocked_bonuses = legacy_data.get('unlocked_bonuses', [])
    print(f"[Legacy] Unlocked bonuses: {unlocked_bonuses}")
    
    # Apply legacy bonuses to session stats (for future use)
    if 'head_start' in unlocked_bonuses:
        advisor.legacy_bonuses['head_start']['unlocked'] = True
    if 'wise_elders' in unlocked_bonuses:
        advisor.legacy_bonuses['wise_elders']['unlocked'] = True
    if 'prepared' in unlocked_bonuses:
        advisor.legacy_bonuses['prepared']['unlocked'] = True
    if 'architect' in unlocked_bonuses:
        advisor.legacy_bonuses['architect']['unlocked'] = True
    
    # Initialize particle system
    particle_system = ParticleSystem()
    
    # Initialize narrative panel
    narrative_panel = NarrativePanel()
    
    # Initialize event bus and narrative cascades
    from events.bus import EventBus
    from events.cascades import TitleCardQueue, CameraFocusQueue, attach_default_cascades
    event_bus = EventBus(max_log=100)
    title_cards = TitleCardQueue(max_display_time=4.0)
    camera_focus_queue = CameraFocusQueue()
    attach_default_cascades(event_bus, title_cards, camera_focus_queue, narrative_panel)
    
    # Initialize trade system
    trade_system = TradeSystem()
    
    # Initialize tooltip system
    tooltip_system = TooltipSystem()
    
    # Initialize selection manager
    selection_manager = SelectionManager()
    

    
    # Initialize read-only observer HUD
    observer_overlay = ObserverOverlay()
    
    # Initialize fog of war system
    fog_of_war = FogOfWar(world_width, world_height)
    
    # Initialize territory manager
    territory_manager = TerritoryManager(world_width, world_height)
    
    # Initialize faction manager and diplomacy
    faction_manager = FactionManager()
    diplomacy_manager = DiplomacyManager()
    
    # Initialize city planner
    city_planner = CityPlanner(territory_manager, world_map)
    
    # Initialize Storyteller pacing engine
    from systems.storyteller import Storyteller
    from events.incidents import register_all_incidents, INCIDENT_GOOD, INCIDENT_NEUTRAL, INCIDENT_BAD
    storyteller = Storyteller()
    register_all_incidents(storyteller)

    # Initialize autonomous tech research
    from systems.tech_research import TechResearchManager
    tech_research_manager = TechResearchManager()

    # Initialize natural disaster system
    disaster_manager = DisasterManager()

    # Initialize ecology system
    from systems.ecology import EcologyManager
    ecology_manager = EcologyManager(world_width, world_height, world_map=world_map)

    # Initialize disease system
    from systems.disease import DiseaseManager
    disease_manager = DiseaseManager()

    # Initialize ritual system
    from systems.rituals import RitualManager
    ritual_manager = RitualManager()
    ritual_manager.attach_event_bus(event_bus)

    # Initialize reputation & social hierarchy system
    from systems.reputation import ReputationManager
    reputation_manager = ReputationManager()
    reputation_manager.attach_event_bus(event_bus)

    # Initialize aspiration / life goals system
    from systems.aspirations import AspirationManager
    aspiration_manager = AspirationManager()
    aspiration_manager.attach_event_bus(event_bus)

    # Initialize warfare & raiding system
    from systems.warfare import WarfareManager
    warfare_manager = WarfareManager()
    warfare_manager.attach_event_bus(event_bus)

    # Initialize event cascade system (cross-system reactive chain reactions)
    from systems.event_cascades import EventCascadeManager
    cascade_manager = EventCascadeManager()
    cascade_manager.set_systems(
        disease_manager=disease_manager,
        ritual_manager=ritual_manager,
        diplomacy_manager=diplomacy_manager,
        faction_manager=faction_manager,
    )
    cascade_manager.attach_event_bus(event_bus)

    # Initialize cultural heritage & traditions system
    from systems.traditions import TraditionManager
    tradition_manager = TraditionManager()
    tradition_manager.set_systems(diplomacy_manager=diplomacy_manager)
    tradition_manager.attach_event_bus(event_bus)

    # Initialize individual migration & faction defection system
    from systems.migration import MigrationManager
    migration_manager = MigrationManager()
    migration_manager.set_systems(diplomacy_manager=diplomacy_manager)
    migration_manager.attach_event_bus(event_bus)

    # Initialize mentorship & apprenticeship system
    from systems.mentorship import MentorshipManager
    mentorship_manager = MentorshipManager()
    mentorship_manager.attach_event_bus(event_bus)

    # Initialize personality evolution system
    from systems.personality_evolution import PersonalityEvolutionManager
    personality_evolution_manager = PersonalityEvolutionManager()
    personality_evolution_manager.attach_event_bus(event_bus)

    # Initialize heirloom & legacy artifact system
    from systems.heirlooms import HeirloomManager
    heirloom_manager = HeirloomManager()
    heirloom_manager.attach_event_bus(event_bus)

    # Initialize season and weather systems
    from systems.climate import Season, WeatherSystem, TemperatureGrid, GlobalClimate
    global_climate = GlobalClimate()
    season = Season()
    weather_system = WeatherSystem()
    temperature_grid = TemperatureGrid(world_width, world_height)
    apply_scenario_startup_conditions(scenario_profile, praxans, advisor, season, weather_system, time.time())
    settlement_state = compute_settlement_snapshot(praxans, buildings, world_map, season, weather_system)
    celebration_state = {
        "active_until": 0.0,
        "cooldown_until": 0.0,
        "last_particle_time": 0.0,
        "center": None,
    }
    advisor.current_settlement_state = settlement_state
    narrative_panel.add_message(f"Scenario: {scenario_profile['name']}", "Strategy")
    record_observer_timeline_event(
        advisor,
        time.time(),
        "scenario",
        f"Scenario active: {scenario_profile['name']}",
        scenario_profile.get("description"),
    )
    record_population_evolution_sample(advisor, praxans, time.time(), time.time(), force=True)
    refresh_run_summary_cache(
        advisor,
        praxans,
        buildings,
        time.time(),
        time.time(),
        faction_manager=faction_manager,
        scenario_id=scenario_profile["id"],
        scenario_name=scenario_profile["name"],
        selected_model=selected_model,
        seed=runtime_config.seed,
        session_id=game_logger.session_id,
        force=True,
    )
    rooms = []
    last_room_update = 0
    restored_elapsed_seconds = 0.0
    if snapshot_resume_path:
        try:
            if snapshot_payload is None:
                snapshot_payload = load_run_snapshot(snapshot_resume_path)
            restored_state = restore_session_from_snapshot(
                snapshot_payload,
                world_width,
                world_height,
                advisor,
                season,
                weather_system,
                world_map=world_map,
                fog_of_war=fog_of_war,
                territory_manager=territory_manager,
                faction_manager=faction_manager,
                city_planner=city_planner,
                praxan_class=Praxan,
            )
            praxans = restored_state["praxans"]
            buildings = restored_state["buildings"]
            resources = restored_state["resources"]
            settlement_state = compute_settlement_snapshot(praxans, buildings, world_map, season, weather_system)
            settlement_state.update(restored_state["settlement_state"])
            celebration_state = restored_state["celebration_state"]
            advisor.current_settlement_state = settlement_state
            if restored_state.get("run_summary"):
                advisor.session_stats["current_run_summary"] = dict(restored_state["run_summary"])
            restored_elapsed_seconds = restored_state["elapsed_seconds"]
            scenario_profile = set_active_scenario(restored_state.get("scenario_id", scenario_profile["id"]))
            advisor.session_stats["scenario_id"] = scenario_profile["id"]
            advisor.session_stats["scenario_name"] = scenario_profile["name"]
            advisor.session_stats["mutation_scale"] = ACTIVE_MUTATION_SCALE
            # Restore quest state so resumed sessions don't re-award rewards
            quest_manager.from_dict(snapshot_payload.get("quests", {}))
            # Restore diplomacy state
            diplomacy_manager.deserialize(snapshot_payload.get("diplomacy", {}))
            # Restore tech research state
            tech_research_data = snapshot_payload.get("tech_research", {})
            if tech_research_data:
                tech_research_manager.restore(tech_research_data)
            # Restore disaster state
            disaster_data = snapshot_payload.get("disasters", {})
            if disaster_data:
                disaster_manager.restore(disaster_data)
            # Restore ritual state
            ritual_data = snapshot_payload.get("rituals", {})
            if ritual_data:
                ritual_manager.restore(ritual_data)
            # Restore reputation & social hierarchy state
            reputation_data = snapshot_payload.get("reputation", {})
            if reputation_data:
                reputation_manager.restore(reputation_data)
            # Restore aspiration / life goals state
            aspirations_data = snapshot_payload.get("aspirations", {})
            if aspirations_data:
                aspiration_manager.restore(aspirations_data, now=now)
                aspiration_manager.restore_praxan_aspirations(praxans)
            # Restore warfare & raiding state
            warfare_data = snapshot_payload.get("warfare", {})
            if warfare_data:
                warfare_manager.restore(warfare_data, current_time=now)
            # Restore event cascade state
            cascade_data = snapshot_payload.get("cascades", {})
            if cascade_data:
                cascade_manager.restore(cascade_data)
            # Restore cultural heritage & traditions state
            traditions_data = snapshot_payload.get("traditions", {})
            if traditions_data:
                tradition_manager.restore(traditions_data, current_time=now)
            # Restore individual migration & defection state
            migration_data = snapshot_payload.get("migration", {})
            if migration_data:
                migration_manager.restore(migration_data, current_time=now)
            # Restore mentorship & apprenticeship state
            mentorship_data = snapshot_payload.get("mentorship", {})
            if mentorship_data:
                mentorship_manager.restore(mentorship_data, current_time=now)
                mentorship_manager.restore_praxan_mentorships(praxans)
            # Restore personality evolution state
            pe_data = snapshot_payload.get("personality_evolution", {})
            if pe_data:
                personality_evolution_manager.restore(pe_data, current_time=now)
            # Restore heirloom & legacy artifact state
            heirloom_data = snapshot_payload.get("heirlooms", {})
            if heirloom_data:
                heirloom_manager.restore(heirloom_data, current_time=now)
            # Restore ecology state (fertility grid, harvest pressure, degradation/recovery events)
            ecology_data = snapshot_payload.get("ecology", {})
            if ecology_data:
                from systems.ecology import EcologyManager as _EcoMgr
                ecology_manager = _EcoMgr.deserialize(
                    ecology_data, world_width, world_height, world_map=world_map,
                )
            # Restore global climate epoch drift (temp/moisture offsets, epoch label)
            gc_data = snapshot_payload.get("global_climate", {})
            if gc_data:
                global_climate.epoch = str(gc_data.get("epoch", global_climate.epoch))
                global_climate.global_temp_offset = float(gc_data.get("global_temp_offset", 0.0))
                global_climate.global_moisture_offset = float(gc_data.get("global_moisture_offset", 0.0))
                global_climate.target_temp_offset = float(gc_data.get("target_temp_offset", 0.0))
                global_climate.target_moisture_offset = float(gc_data.get("target_moisture_offset", 0.0))
            pending_resource_spawns = {}
            if restored_state.get("selected_model") and not selected_model:
                selected_model = restored_state["selected_model"]
            if restored_state.get("camera_state"):
                restored_camera = restored_state["camera_state"]
                restored_zoom = max(camera.min_zoom, min(camera.max_zoom, float(restored_camera.get("zoom", camera.zoom))))
                camera.zoom = restored_zoom
                camera.target_zoom = restored_zoom
                camera.x = restored_camera.get("x", camera.x)
                camera.y = restored_camera.get("y", camera.y)
                camera.follow_mode = bool(restored_camera.get("follow_mode", True))
                camera.clamp_camera(WINDOW_WIDTH, WINDOW_HEIGHT)
            else:
                center_camera_on_colony(camera, praxans, buildings)
                camera.follow_mode = True
            fog_of_war.update(praxans, buildings, world_map)
            territory_manager.update(praxans, buildings)
            record_population_evolution_sample(advisor, praxans, time.time(), time.time() - restored_elapsed_seconds, force=True)
            refresh_run_summary_cache(
                advisor,
                praxans,
                buildings,
                time.time(),
                time.time() - restored_elapsed_seconds,
                faction_manager=faction_manager,
                scenario_id=scenario_profile["id"],
                scenario_name=scenario_profile["name"],
                selected_model=selected_model,
                seed=runtime_config.seed,
                session_id=game_logger.session_id,
                force=True,
            )
            narrative_panel.add_message(
                f"RESUMED: {os.path.basename(snapshot_resume_path)} [{scenario_profile['name']}]",
                "Achievement",
            )
            record_observer_timeline_event(
                advisor,
                time.time(),
                "resume",
                f"Resumed snapshot [{scenario_profile['name']}]",
                os.path.basename(snapshot_resume_path),
            )
            print(f"[Snapshot] Restored session from {snapshot_resume_path}")
        except Exception as restore_error:
            print(f"[Snapshot] Failed to restore {snapshot_resume_path}: {restore_error}")
            traceback.print_exc()

    # Track mouse position for tooltips
    mouse_screen_pos = (0, 0)
    
    # Game state tracking
    running = True
    game_over = False
    final_stats = None
    ui_theme = build_ui_theme(WINDOW_WIDTH, WINDOW_HEIGHT)
    ui_registry = UIRectRegistry()
    ui_state = UIState(
        active_screen="run",
        selected_scenario_id=scenario_profile["id"],
        camera_mode="follow" if camera.follow_mode else "free",
        map_overlay="biome",
    )
    work_panel = WorkPriorityPanel(ui_theme)
    schedule_panel = SchedulePanel(ui_theme)
    camera_director = CameraDirector()
    graphics_config = GraphicsConfig(target_fps=FPS)
    scene_renderer = SceneRenderer(graphics_config, asset_root=os.path.join(os.path.dirname(__file__), "assets"))
    post_run_action = None

    def _toggle_modal(modal_name):
        ui_state.active_modal = None if ui_state.active_modal == modal_name else modal_name
        if ui_state.active_modal != "archive":
            ui_state.archive_scroll = 0
        if ui_state.active_modal != "analytics":
            ui_state.analytics_section = "population"

    def _handle_ui_action(action_name, payload=None):
        nonlocal running, post_run_action, selected_model
        global current_time_speed
        ui_state.show_quit_prompt = False
        if action_name == "toggle_follow":
            camera.follow_mode = not camera.follow_mode
            ui_state.camera_mode = "follow" if camera.follow_mode else "free"
            return
        if action_name == "speed_1":
            current_time_speed = 0
            return
        if action_name == "speed_2":
            current_time_speed = 1
            return
        if action_name == "speed_5":
            current_time_speed = 2
            return
        if action_name == "toggle_modal_research":
            _toggle_modal("research")
            return
        if action_name == "toggle_modal_evolution":
            _toggle_modal("evolution")
            return
        if action_name == "toggle_modal_analytics":
            _toggle_modal("analytics")
            return
        if action_name == "toggle_modal_archive":
            _toggle_modal("archive")
            return
        if action_name == "close_modal":
            ui_state.active_modal = None
            return
        if action_name == "inspect_tab":
            ui_state.inspect_tab = str(payload or "overview")
            ui_state.inspect_scroll = 0
            return
        if action_name == "analytics_tab":
            ui_state.analytics_section = str(payload or "population")
            return
        if action_name == "cycle_overlay":
            ui_state.map_overlay = next_overlay(ui_state.map_overlay)
            return
        if action_name == "focus_latest_event":
            cue_label = camera_director.queue_latest_focus(time.time())
            if cue_label:
                ui_state.camera_mode = "event"
                ui_state.camera_cue = cue_label
                camera.follow_mode = False
            return
        if action_name == "archive_select":
            session_id = str(payload or "")
            if not session_id:
                return
            if ui_state.selected_run is None or ui_state.selected_run == session_id:
                ui_state.selected_run = session_id
            elif ui_state.compare_run == session_id:
                ui_state.compare_run = None
            elif ui_state.compare_run is None:
                ui_state.compare_run = session_id
            else:
                ui_state.selected_run = session_id
                ui_state.compare_run = None
            return
        if action_name == "end_archive":
            ui_state.active_modal = "archive"
            ui_state.end_summary_open = False
            return
        if action_name == "end_compare":
            ui_state.active_modal = "archive"
            ui_state.end_summary_open = False
            return

        if action_name == "work":
            ui_state.show_work_priority = not ui_state.show_work_priority
            if ui_state.show_work_priority:
                ui_state.show_schedule = False
            return
        
        if action_name == "schedule":
            ui_state.show_schedule = not ui_state.show_schedule
            if ui_state.show_schedule:
                ui_state.show_work_priority = False
            return
        
        if action_name == "architect":
            # Toggle architect mode; default to orders if opening
            if ui_state.architect_mode:
                ui_state.architect_mode = None
            else:
                ui_state.architect_mode = "orders"
            return

        if action_name.startswith("architect_sub:"):
            ui_state.architect_mode = action_name.split(":")[1]
            return

        if action_name == "cycle_priority":
            p_id, w_type = payload if isinstance(payload, (list, tuple)) else (payload.get("pawn_id"), payload.get("work_type"))
            target = next((p for p in praxans if p.id == p_id), None)
            if target:
                prio = target.work_priorities.get(w_type, 3)
                target.work_priorities[w_type] = (prio + 1) % 5
            return

        if action_name == "select_schedule_cat":
            schedule_panel.selected_category = payload
            return

        if action_name == "cycle_schedule":
            p_id, hour = payload
            target = next((p for p in praxans if p.id == p_id), None)
            if target:
                target.schedule[hour] = schedule_panel.selected_category
            return
        if action_name == "end_resume":
            post_run_action = "resume_latest"
            running = False
            return
        if action_name == "end_new_run":
            post_run_action = "new_run"
            running = False
            return
        if action_name == "architect":
            ui_state.architect_mode = "orders" if ui_state.architect_mode is None else None
            return
        if action_name.startswith("architect_sub:"):
            ui_state.architect_mode = action_name.split(":")[1]
            return
        if action_name == "work":
            _toggle_modal("analytics") # Placeholder or new modal
            ui_state.analytics_section = "culture" # Use as placeholder for work
            return
        if action_name == "jump_to_pawn":
            p_id = payload
            target = next((p for p in praxans if p.id == p_id), None)
            if target:
                camera.target_x = target.x - WINDOW_WIDTH / (2 * camera.zoom)
                camera.target_y = target.y - WINDOW_HEIGHT / (2 * camera.zoom)
                camera.follow_mode = True
                selection_manager.select(target, "praxan")
            return
        if action_name == "force_rest":
            p_id = payload
            target = next((p for p in praxans if p.id == p_id), None)
            if target:
                target.state = STATE_REST if 'STATE_REST' in dir() else 'STATE_REST'
                target.current_action = "Forced rest"
                target.vx, target.vy = 0, 0
            return
        if action_name == "force_haul":
            p_id = payload
            target = next((p for p in praxans if p.id == p_id), None)
            if target:
                target.work_priorities['Hauling'] = 1  # Highest priority
                target.current_action = "Prioritized hauling"
            return
        if action_name == "deconstruct_building":
            if payload and hasattr(payload, 'x'):
                try:
                    buildings.remove(payload)
                    narrative_panel.add_message(f"Deconstructed {getattr(payload, 'building_type', 'building')}", 'Achievement')
                except ValueError:
                    pass
            return
        if action_name == "context_action":
            # Handle context specific orders
            ui_state.context_menu_pos = None
            ui_state.context_menu_items = []
            return
    
    game_start_time = time.time() - restored_elapsed_seconds
    last_status_time = game_start_time
    render_diag_until = game_start_time  # Disable diag overlay
    record_population_evolution_sample(advisor, praxans, time.time(), game_start_time, force=True)
    refresh_run_summary_cache(
        advisor,
        praxans,
        buildings,
        time.time(),
        game_start_time,
        faction_manager=faction_manager,
        scenario_id=scenario_profile["id"],
        scenario_name=scenario_profile["name"],
        selected_model=selected_model,
        seed=runtime_config.seed,
        session_id=game_logger.session_id,
        force=True,
    )
    print("Praxans game started! Observer mode is active - the colony evolves without player commands.")
    print(f"[DEBUG] Entering main game loop...")
    
    # #region agent log
    debug_log("main:before_loop", "About to enter main game loop", {"running": running, "screen_is_none": screen is None}, "H1")
    # #endregion
    
    # Main game loop - wrapped in try-finally for crash safety
    next_runtime_config = None
    try:
        frame_count = 0
        last_telemetry_time = 0.0
        debug_watermark_error_logged = False
        storyteller_overlay_error_logged = False
        # #region agent log
        debug_log("main:loop_start", "Main loop started", {"frame_count": frame_count, "running": running}, "H1")
        # #endregion
        while running:
            delta_time = clock.tick(FPS) / 1000.0 * TIME_SPEED_OPTIONS[current_time_speed]
            frame_count += 1
            
            # Update game time
            global game_ticks
            game_ticks += int(60 * delta_time) # Assume 60 ticks per real second at 1x speed
            game_hour = (game_ticks // TICKS_PER_HOUR) % 24
            # #region agent log
            if frame_count == 1:
                debug_log("main:first_frame", "First frame started", {"frame_count": frame_count}, "H2")
            if frame_count <= 5:
                debug_log("main:frame", f"Frame {frame_count}", {"frame_count": frame_count, "running": running}, "H1")
            # #endregion
            if frame_count == 1:
                print(f"[DEBUG] First frame started")
            if frame_count % 300 == 0:  # Print every 10 seconds at 30 FPS
                print(f"[DEBUG] Frame {frame_count}, running={running}")
            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE and not runtime_config.headless:
                    WINDOW_WIDTH, WINDOW_HEIGHT = max(1366, event.w), max(768, event.h)
                    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SCALED | pygame.RESIZABLE)
                    ui_theme = build_ui_theme(WINDOW_WIDTH, WINDOW_HEIGHT)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if handle_escape(ui_state, selection_manager):
                            running = False
                    elif event.key == pygame.K_o and game_over:
                        ui_state.end_summary_open = not ui_state.end_summary_open
                    elif event.key == pygame.K_RETURN and ui_state.show_quit_prompt:
                        running = False
                    elif event.key == pygame.K_1:
                        _handle_ui_action("speed_1")
                    elif event.key == pygame.K_2:
                        _handle_ui_action("speed_2")
                    elif event.key == pygame.K_5:
                        _handle_ui_action("speed_5")
                    elif event.key == pygame.K_f:
                        _handle_ui_action("toggle_follow")
                    elif event.key == pygame.K_MINUS or event.key == pygame.K_KP_MINUS:
                        camera.adjust_zoom(0.9, screen_w=WINDOW_WIDTH, screen_h=WINDOW_HEIGHT)
                    elif event.key == pygame.K_EQUALS or event.key == pygame.K_KP_PLUS:
                        camera.adjust_zoom(1.1, screen_w=WINDOW_WIDTH, screen_h=WINDOW_HEIGHT)
                    elif event.key == pygame.K_r:
                        _handle_ui_action("toggle_modal_research")
                    elif event.key == pygame.K_s:
                        _handle_ui_action("toggle_modal_evolution")
                    elif event.key == pygame.K_t:
                        _handle_ui_action("toggle_modal_analytics")
                    elif event.key == pygame.K_a:
                        _handle_ui_action("toggle_modal_archive")
                    elif event.key == pygame.K_SPACE:
                        _handle_ui_action("focus_latest_event")
                    elif event.key == pygame.K_F12:
                        dev_mode.toggle()
                    elif event.key == pygame.K_h:
                        history_renderer.toggle()
                    elif event.key == pygame.K_SLASH:
                        search_overlay.toggle()
                    elif search_overlay.active:
                        search_overlay.handle_key(event, game_state if 'game_state' in dir() else {}, camera, window_size=(WINDOW_WIDTH, WINDOW_HEIGHT))
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    run_layout = compute_run_layout(WINDOW_WIDTH, WINDOW_HEIGHT)
                    ui_hit = ui_registry.hit_test(event.pos)
                    
                    # Clear context menu unless we clicked inside it
                    if ui_hit is None or not ui_hit.id.startswith("context_item:"):
                        ui_state.context_menu_pos = None
                        ui_state.context_menu_items = []

                    if event.button == 1:  # Left mouse
                        if ui_hit is not None:
                            if ui_hit.action == "minimap_jump":
                                map_x = run_layout.minimap.x + 10
                                map_y = run_layout.minimap.y + 34
                                map_w = run_layout.minimap.w - 20
                                map_h = run_layout.minimap.h - 66
                                if map_x <= event.pos[0] <= map_x + map_w and map_y <= event.pos[1] <= map_y + map_h:
                                    click_x_on_map = event.pos[0] - map_x
                                    click_y_on_map = event.pos[1] - map_y
                                    minimap_scale_x = map_w / max(1, camera.world_width)
                                    minimap_scale_y = map_h / max(1, camera.world_height)
                                    world_click_x = click_x_on_map / minimap_scale_x
                                    world_click_y = click_y_on_map / minimap_scale_y
                                    camera.target_x = max(0, min(world_click_x - WINDOW_WIDTH / (2 * max(0.01, camera.target_zoom)), camera.world_width - WINDOW_WIDTH / max(0.01, camera.target_zoom)))
                                    camera.target_y = max(0, min(world_click_y - WINDOW_HEIGHT / (2 * max(0.01, camera.target_zoom)), camera.world_height - WINDOW_HEIGHT / max(0.01, camera.target_zoom)))
                                    camera.clamp_camera(WINDOW_WIDTH, WINDOW_HEIGHT)
                            else:
                                _handle_ui_action(ui_hit.action or ui_hit.id, ui_hit.payload)
                        else:
                            keys = pygame.key.get_pressed()
                            shift_pressed = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
                            entity, entity_type = pick_world_entity(
                                event.pos,
                                camera,
                                praxans,
                                buildings,
                                resources,
                                world_map.encounters,
                                world_map.hazards,
                                world_map.npcs,
                                praxan_radius=PRAXAN_RADIUS,
                                building_size=BUILDING_SIZE,
                                resource_radii={
                                    "food": RESOURCE_RADIUS_FOOD,
                                    "stone": RESOURCE_RADIUS_STONE,
                                    "wood": RESOURCE_RADIUS_WOOD,
                                },
                            )
                            if entity is not None and not shift_pressed:
                                selection_manager.select(entity, entity_type)
                                ui_state.inspect_target = {"entity": entity, "type": entity_type}
                                ui_state.inspect_tab = "overview"
                                ui_state.inspect_scroll = 0
                            else:
                                camera.start_pan(event.pos)
                    elif event.button == 3:  # Right mouse
                        if ui_hit is None:
                            # Open context menu at world position
                            ui_state.context_menu_pos = event.pos
                            world_x, world_y = camera.screen_to_world(event.pos[0], event.pos[1])
                            
                            # Simple logic for now: if pawn selected, give orders
                            selected = selection_manager.selected_entity
                            if selected and selection_manager.selected_type == "praxan":
                                ui_state.context_menu_items = [
                                    {"id": "move", "label": f"Move P#{selected.id} here", "pos": (world_x, world_y)},
                                    {"id": "work", "label": "Prioritize Work", "pos": (world_x, world_y)},
                                ]
                            else:
                                ui_state.context_menu_items = [
                                    {"id": "cancel", "label": "Cancel orders"},
                                ]
                    elif event.button == 2:  # Middle mouse button - always pan
                        camera.start_pan(event.pos)
                    elif event.button == 4:  # Scroll up
                        scroll_target = ui_registry.scroll_target(mouse_screen_pos)
                        if scroll_target and scroll_target.id == "inspect_drawer":
                            ui_state.inspect_scroll = max(0, ui_state.inspect_scroll - 28)
                        elif scroll_target and scroll_target.id == "modal_frame" and ui_state.active_modal == "archive":
                            ui_state.archive_scroll = max(0, ui_state.archive_scroll - 32)
                        else:
                            camera.adjust_zoom(1.1, mouse_pos=event.pos, screen_w=WINDOW_WIDTH, screen_h=WINDOW_HEIGHT)
                    elif event.button == 5:  # Scroll down
                        scroll_target = ui_registry.scroll_target(mouse_screen_pos)
                        if scroll_target and scroll_target.id == "inspect_drawer":
                            ui_state.inspect_scroll += 28
                        elif scroll_target and scroll_target.id == "modal_frame" and ui_state.active_modal == "archive":
                            ui_state.archive_scroll += 32
                        else:
                            camera.adjust_zoom(0.9, mouse_pos=event.pos, screen_w=WINDOW_WIDTH, screen_h=WINDOW_HEIGHT)
                elif event.type == pygame.MOUSEMOTION:
                    camera.update_pan(event.pos)
                    # Track mouse position for tooltips
                    mouse_screen_pos = event.pos
                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1 or event.button == 2:
                        camera.stop_pan()
            
            # CRITICAL: On first frame, render immediately BEFORE any heavy operations
            # This prevents black screen from blocking operations
            if frame_count == 1:
                # #region agent log
                debug_log("main:first_frame_render_start", "Starting first frame render", {"frame_count": frame_count}, "H2")
                # #endregion
                try:
                    # Fill screen immediately
                    # #region agent log
                    debug_log("main:screen_fill_before", "About to fill screen", {"screen_is_none": screen is None}, "H5")
                    # #endregion
                    screen.fill((50, 50, 50))  # Dark background
                    # #region agent log
                    debug_log("main:screen_fill_after", "Screen filled", {}, "H5")
                    # #endregion
                    
                    # Draw test pattern to verify rendering
                    pygame.draw.rect(screen, (255, 0, 0), (0, 0, 50, 50))  # Red square top-left
                    pygame.draw.rect(screen, (0, 255, 0), (WINDOW_WIDTH-50, 0, 50, 50))  # Green square top-right
                    pygame.draw.rect(screen, (0, 0, 255), (0, WINDOW_HEIGHT-50, 50, 50))  # Blue square bottom-left
                    pygame.draw.rect(screen, (255, 255, 0), (WINDOW_WIDTH-50, WINDOW_HEIGHT-50, 50, 50))  # Yellow square bottom-right
                    
                    # Draw loading text
                    loading_font = pygame.font.Font(None, 48)
                    loading_text = loading_font.render("Loading...", True, (200, 200, 200))
                    screen.blit(loading_text, (WINDOW_WIDTH // 2 - loading_text.get_width() // 2, 
                                              WINDOW_HEIGHT // 2 - loading_text.get_height() // 2))
                    
                    # FLIP IMMEDIATELY - show something on screen right away
                    # #region agent log
                    debug_log("main:flip_before_first", "About to flip display (first frame)", {}, "H4")
                    # #endregion
                    pygame.display.flip()
                    # #region agent log
                    debug_log("main:flip_after_first", "Display flipped (first frame)", {}, "H4")
                    # #endregion
                    print("[DEBUG] First frame - rendered and flipped immediately")
                    
                    # Do a minimal render pass - just draw one visible chunk to show progress
                    try:
                        # Find first visible chunk and render it
                        for chunk_key, chunk in world_map.chunks.items():
                            screen_x1, screen_y1 = camera.world_to_screen(chunk.world_x, chunk.world_y)
                            screen_x2, screen_y2 = camera.world_to_screen(chunk.world_x + CHUNK_SIZE, chunk.world_y + CHUNK_SIZE)
                            if screen_x2 > 0 and screen_x1 < WINDOW_WIDTH and screen_y2 > 0 and screen_y1 < WINDOW_HEIGHT:
                                # Render this chunk
                                if chunk.surface is None:
                                    chunk.render_surface()
                                zoomed_chunk_w = int(CHUNK_SIZE * camera.zoom)
                                zoomed_chunk_h = int(CHUNK_SIZE * camera.zoom)
                                if zoomed_chunk_w > 0 and zoomed_chunk_h > 0 and chunk.surface:
                                    scaled_chunk = pygame.transform.scale(chunk.surface, (zoomed_chunk_w, zoomed_chunk_h))
                                    screen.blit(scaled_chunk, (int(screen_x1), int(screen_y1)))
                                break  # Just render one chunk for first frame
                        
                        # Flip again to show chunk
                        # #region agent log
                        debug_log("main:flip_before_chunk", "About to flip display (chunk render)", {}, "H4")
                        # #endregion
                        pygame.display.flip()
                        # #region agent log
                        debug_log("main:flip_after_chunk", "Display flipped (chunk render)", {}, "H4")
                        # #endregion
                        print("[DEBUG] First frame - rendered first chunk")
                    except Exception as e:
                        # #region agent log
                        debug_log("main:chunk_render_error", "Chunk render failed", {"error": str(e)}, "H2")
                        # #endregion
                        print(f"[DEBUG] First chunk render failed (non-critical): {e}")
                        
                except Exception as e:
                    # #region agent log
                    debug_log("main:first_frame_render_error", "First frame render failed", {"error": str(e), "error_type": type(e).__name__}, "H2")
                    # #endregion
                    print(f"[CRITICAL] Failed first frame render: {e}")
                    traceback.print_exc()
            
            # Calculate delta time for smooth updates
            current_time = time.time()
            delta_time = (1.0 / FPS) * TIME_SPEED_OPTIONS[current_time_speed]
            
            # Process pending resource spawns in small batches each frame
            try:
                if 'pending_resource_spawns' in locals() and pending_resource_spawns:
                    batch_limit = 8  # max spawns per frame
                    spawned_this_frame = 0
                    for res_type in ['food', 'wood', 'stone']:
                        while pending_resource_spawns.get(res_type, 0) > 0 and spawned_this_frame < batch_limit:
                            x = random.randint(100, world_width - 100)
                            y = random.randint(100, world_height - 100)
                            biome_type = world_map.get_biome_at(x, y)
                            biome_props = world_map.get_biome_properties(biome_type)
                            chance = biome_props.get(f'{res_type}_bonus', 1.0) * 0.5
                            if random.random() < chance:
                                resources.append(Resource(x, y, res_type))
                            pending_resource_spawns[res_type] -= 1
                            spawned_this_frame += 1
                    # Clean empty entries
                    for k in list(pending_resource_spawns.keys()):
                        if pending_resource_spawns[k] <= 0:
                            pending_resource_spawns.pop(k, None)
            except Exception as e:
                print(f"[Init] Pending resource spawn error: {e}")
            
            # DRAW to ensure screen updates - ALWAYS fill screen every frame
            # #region agent log
            if frame_count <= 5:
                debug_log("main:screen_fill_frame", f"Filling screen (frame {frame_count})", {"frame_count": frame_count}, "H5")
            # #endregion
            try:
                screen.fill((50, 50, 50))  # Dark background for unexplored areas
                # #region agent log
                if frame_count <= 5:
                    debug_log("main:screen_fill_success", f"Screen filled successfully (frame {frame_count})", {"frame_count": frame_count}, "H5")
                # #endregion
            except Exception as e:
                # #region agent log
                debug_log("main:screen_fill_error", "Screen fill failed", {"error": str(e), "frame_count": frame_count}, "H5")
                # #endregion
                print(f"[CRITICAL] Failed to fill screen: {e}")
                traceback.print_exc()
                game_logger.log_error(f"Screen fill error: {e}", exc_info=True)

            # Note: Full rendering (chunks, entities, UI) happens in the main rendering pass below
            # This ensures proper rendering order and avoids double-rendering
            
            # Smooth camera panning with held keys
            keys = pygame.key.get_pressed()
            camera.handle_keys(keys, delta_time)
            
            # Update camera and follow
            camera.update(delta_time, WINDOW_WIDTH, WINDOW_HEIGHT)
            camera.update_follow(praxans, delta_time, WINDOW_WIDTH, WINDOW_HEIGHT)
            
            # Skip heavy updates on first frame to ensure immediate rendering
            if frame_count > 1:
                # Update fog of war
                try:
                    fog_of_war.update(praxans, buildings, world_map)
                except Exception as e:
                    print(f"[ERROR] Fog of war update failed: {e}")
                    game_logger.log_error(f"Fog of war update error: {e}")
                
                # Update territory manager (can be expensive - skip first frame)
                try:
                    territory_manager.update(praxans, buildings)
                except Exception as e:
                    print(f"[ERROR] Territory manager update failed: {e}")
                    game_logger.log_error(f"Territory manager update error: {e}")
                
                # Update city planner
                try:
                    city_planner.update(praxans, buildings, advisor, current_time)
                except Exception as e:
                    print(f"[ERROR] City planner update failed: {e}")
                    game_logger.log_error(f"City planner update error: {e}")
            else:
                print("[DEBUG] Skipping heavy updates on first frame for faster initial render")
            
            # Update praxans
            num_active_resources = sum(1 for r in resources if not r.collected)
            num_buildings = len(buildings)
            
            # Calculate population pressure
            population_ratio = len(praxans) / MAX_POPULATION
            overpopulation_penalty = 0
            if population_ratio >= OVERPOPULATION_THRESHOLD:
                overpopulation_penalty = (population_ratio - OVERPOPULATION_THRESHOLD) * 10  # 0-100% penalty
                # Apply to needs decay
                for praxan in praxans:
                    praxan.needs_decay_multiplier = 1.0 + overpopulation_penalty
            
            # Calculate day/night cycle
            day_cycle = (current_time - game_start_time) % DAY_LENGTH
            is_night = day_cycle >= NIGHT_START
            time_of_day = "NIGHT" if is_night else "DAY"
            
            # Periodic status updates every 10 seconds
            if current_time - last_status_time >= 10:
                elapsed = int(current_time - game_start_time)
                total_food_inv = sum(t.inventory['food'] for t in praxans)
                total_wood_inv = sum(t.inventory['wood'] for t in praxans)
                print(f"\n[STATUS {elapsed}s] {num_active_resources} resources left, Total inventory: {total_food_inv} food, {total_wood_inv} wood, Buildings: {num_buildings}")
                for idx, t in enumerate(praxans):
                    print(f"   Praxan {idx}: pos=({int(t.x)}, {int(t.y)}), inv={t.inventory}")
                print()
                last_status_time = current_time

            advisor.poll_async_jobs(
                praxans,
                resources,
                buildings,
                narrative_panel=narrative_panel,
                faction_manager=faction_manager,
            )
            # V2 multi-channel poll / queue --------------------------------
            advisor.poll_llm_channels(
                praxans,
                resources,
                buildings,
                narrative_panel=narrative_panel,
                faction_manager=faction_manager,
            )
            if advisor.last_model_used:
                selected_model = advisor.last_model_used
            record_population_evolution_sample(advisor, praxans, current_time, game_start_time, force=False)
            
            # Record history samples for the History Graph (Pillar 4)
            history_tracker.update(current_time, praxans, buildings, storyteller)
            
            # Award research points (time-based and milestones)
            days_survived = int((current_time - game_start_time) / DAY_LENGTH)
            if days_survived > advisor.civilization_age:
                advisor.research_points += 25
                advisor.civilization_age = days_survived
                narrative_panel.add_message(f"Day {days_survived} survived! +25 research points", 'Achievement')
            
            # Population milestones (every 5 praxans)
            pop_milestone = (len(praxans) // 5) * 5
            if pop_milestone > 0 and not hasattr(advisor, 'last_pop_milestone'):
                advisor.last_pop_milestone = 0
            if pop_milestone > getattr(advisor, 'last_pop_milestone', 0):
                advisor.research_points += 10
                advisor.last_pop_milestone = pop_milestone
                if pop_milestone % 10 == 0:  # Only message every 10
                    narrative_panel.add_message(f"Population milestone: {pop_milestone}! +10 research points", 'Achievement')
            
            # Track max population in session stats
            advisor.session_stats['max_population'] = max(
                advisor.session_stats.get('max_population', 0),
                len(praxans)
            )
            
            # Building milestones (one-time per building)
            for building in buildings:
                if not hasattr(building, 'awarded_points'):
                    advisor.research_points += 10
                    building.awarded_points = True
            
            # Civilization advisor query with smart intervals and intervention assessment
            # Generate state summary
            state_summary = advisor._generate_state_summary(praxans, resources, buildings, territory_manager, world_map)

            # V2 multi-channel scheduling — runs all 4 channels at different cadences
            advisor.queue_channel_reviews(
                current_time,
                praxans,
                resources,
                buildings,
                state_summary,
                faction_manager=faction_manager,
            )
            
            # Legacy single-channel advisor (runs in parallel with V2 for backward compat)
            # Calculate dynamic interval
            if advisor.stability_counter > 3:
                current_interval = CIVILIZATION_ADVISOR_INTERVAL * 2  # 60 seconds when stable
            elif state_summary['crisis_flags']:
                current_interval = CIVILIZATION_ADVISOR_INTERVAL * 0.5  # 15 seconds in crisis
            else:
                current_interval = CIVILIZATION_ADVISOR_INTERVAL  # 30 seconds normal
            
            # Prevent immediate query on first frame - ensure at least 10 seconds have passed since initialization
            # This prevents blocking the first frames with a long LLM query
            time_since_last = current_time - advisor.last_query_time
            min_delay_before_first_query = 10.0  # Wait 10 seconds before first query to let game load
            if (
                not advisor.has_pending_llm_jobs()
                and time_since_last >= current_interval
                and time_since_last >= min_delay_before_first_query
            ):
                # Check if intervention needed
                should_intervene, reason, flags = advisor._should_intervene(state_summary, current_time)

                if should_intervene:
                    advisor.queue_strategy_query(
                        praxans,
                        resources,
                        buildings,
                        state_summary=state_summary,
                        intervention_reason=reason,
                        faction_manager=faction_manager,
                    )
                else:
                    print(f"[Advisor] Skipping query - civilization {reason}")
                    advisor.stability_counter += 1
                    advisor.intervention_stats['total_queries'] += 1
                    advisor.intervention_stats['no_changes'] += 1
                    advisor.last_query_time = current_time
            
            # Update resources (respawn logic)
            for resource in resources:
                resource.update(delta_time)
            
            # Update particle system
            particle_system.update()
            
            # Update narrative panel
            narrative_panel.update()
            
            # Update tooltip system - detect hover
            mouse_world_x, mouse_world_y = camera.screen_to_world(mouse_screen_pos[0], mouse_screen_pos[1])
            tooltip_system.detect_hover(mouse_world_x, mouse_world_y, camera, praxans, buildings, resources, 
                                         world_map.encounters, world_map.hazards, world_map.npcs, world_map)
            
            # Update season and weather
            prev_season = season.current
            season.update(current_time - game_start_time)
            if season.current != prev_season:
                ritual_manager.signal_season_change(season.current, current_time)
            
            # Update Storyteller Engine (Pacing & Events)
            # Create a weak game state dict for incidents
            game_state = {
                'praxans': praxans,
                'buildings': buildings,
                'resources': resources,
                'narrative_panel': narrative_panel,
                'event_bus': event_bus,
                'world_width': camera.world_width,
                'world_height': camera.world_height,
                'praxan_class': Praxan,
                'resource_class': Resource,
                'disaster_manager': disaster_manager,
                'warfare_manager': warfare_manager,
                'diplomacy_manager': diplomacy_manager,
                'faction_manager': faction_manager,
                'season': season,
                'weather_system': weather_system,
                'world_map': world_map,
            }
            storyteller.update(current_time, game_state)

            # Autonomous tech research — factions spend accumulated RP based on doctrine
            tech_research_manager.update(
                current_time,
                advisor,
                factions=list(faction_manager.factions.values()),
                event_bus=event_bus,
                narrative_panel=narrative_panel,
            )

            # Natural disaster evaluation — area-of-effect environmental events
            disaster_manager.update(
                current_time=current_time,
                praxans=praxans,
                buildings=buildings,
                world_map=world_map,
                season_name=season.current,
                weather_name=weather_system.current_weather,
                event_bus=event_bus,
                narrative_panel=narrative_panel,
                storyteller_phase=storyteller.current_phase,
                colony_wealth=storyteller.colony_wealth,
            )

            # Faction rituals & gatherings — periodic ceremonies at shrines
            ritual_manager.update(
                faction_manager=faction_manager,
                praxans=praxans,
                buildings=buildings,
                current_time=current_time,
                event_bus=event_bus,
                advisor=advisor,
                narrative_panel=narrative_panel,
                particle_system=particle_system,
                season=season.current,
            )

            # Reputation & social hierarchy — evaluate tiers, apply moodlets, drift
            reputation_manager.update(
                praxans=praxans,
                faction_manager=faction_manager,
                event_bus=event_bus,
                current_time=current_time,
            )

            # Aspirations / life goals — assign, track progress, complete/fail
            aspiration_manager.update(
                praxans=praxans,
                faction_manager=faction_manager,
                reputation_manager=reputation_manager,
                event_bus=event_bus,
                current_time=current_time,
            )

            # Warfare & raiding — evaluate hostile factions, resolve combat
            warfare_manager.update(
                praxans=praxans,
                buildings=buildings,
                faction_manager=faction_manager,
                diplomacy_manager=diplomacy_manager,
                reputation_manager=reputation_manager,
                current_time=current_time,
                advisor=advisor,
            )

            # Cultural heritage & traditions — formation, decay, exchange, moodlets
            tradition_manager.update(
                faction_manager=faction_manager,
                diplomacy_manager=diplomacy_manager,
                praxans=praxans,
                current_time=current_time,
                event_bus=event_bus,
                advisor=advisor,
                narrative_panel=narrative_panel,
            )
            # Apply tradition moodlets to faction members
            for _fid, _faction in faction_manager.factions.items():
                _trad_moodlets = tradition_manager.get_tradition_moodlets(_fid)
                for _tm in _trad_moodlets:
                    for _p in praxans:
                        if getattr(_p, 'alive', True) and getattr(_p, 'faction_id', None) == _fid:
                            try:
                                _p.add_moodlet(_tm["id"], _tm["mood_offset"], _tm["duration"], current_time)
                            except Exception:
                                pass

            # Individual migration & faction defection — push/pull evaluation
            try:
                _disease_mgr = disease_manager if "disease_manager" in local_names else None
                migration_manager.update(
                    faction_manager=faction_manager,
                    diplomacy_manager=diplomacy_manager,
                    praxans=praxans,
                    current_time=current_time,
                    event_bus=event_bus,
                    advisor=advisor,
                    narrative_panel=narrative_panel,
                    reputation_manager=reputation_manager,
                    disease_manager=_disease_mgr,
                )
            except Exception:
                pass

            # Mentorship & apprenticeship — sessions, graduations, new pairs
            try:
                mentorship_manager.update(
                    praxans=praxans,
                    faction_manager=faction_manager,
                    reputation_manager=reputation_manager,
                    event_bus=event_bus,
                    current_time=current_time,
                    advisor=advisor,
                    narrative_panel=narrative_panel,
                )
                # Set proximity XP multipliers on apprentice praxans
                _alive_map = {p.id: p for p in praxans if getattr(p, 'alive', True)}
                for _app_id, _mstate in mentorship_manager.get_all_active().items():
                    _app = _alive_map.get(_app_id)
                    if _app is None:
                        continue
                    _skill = _mstate.get("skill", "")
                    if mentorship_manager.is_near_mentor(_app_id, _alive_map):
                        _mult = mentorship_manager.get_xp_multiplier(_app_id, _skill)
                    else:
                        _mult = 1.0
                    if not hasattr(_app, '_mentorship_xp_mult'):
                        _app._mentorship_xp_mult = {}
                    _app._mentorship_xp_mult[_skill] = _mult
            except Exception:
                pass

            # Personality evolution — drain queued shifts, apply drift, detect thresholds
            try:
                personality_evolution_manager.update(
                    praxans=praxans,
                    current_time=current_time,
                )
            except Exception:
                pass

            # Heirloom & legacy artifacts — inheritance, relic ascension, bearer effects
            try:
                heirloom_manager.update(
                    praxans=praxans,
                    faction_manager=faction_manager,
                    reputation_manager=reputation_manager,
                    current_time=current_time,
                    advisor=advisor,
                    narrative_panel=narrative_panel,
                )
                # Drain pending heirloom creation events from praxans
                for _p in praxans:
                    if not getattr(_p, 'alive', True):
                        continue
                    _hevents = getattr(_p, '_pending_heirloom_events', [])
                    while _hevents:
                        _he = _hevents.pop(0)
                        if _he.get('action') == 'create':
                            _h = heirloom_manager.create_heirloom(
                                type_id=_he.get('type_id', 'masterwork_tool'),
                                creator_id=_p.id,
                                creator_name=getattr(_p, 'name', f'#{_p.id}'),
                                faction_id=getattr(_p, 'faction_id', None),
                                current_time=current_time,
                                base_item=_he.get('base_item'),
                                owner_id=_p.id,
                            )
                            if _h:
                                from systems.heirlooms import _get_mood_def
                                _mood = _get_mood_def("CreatedHeirloom")
                                if _mood:
                                    _p.add_moodlet("CreatedHeirloom", _mood.get("mood_offset", 12), _mood.get("duration", 360), current_time)
                                if hasattr(_p, 'episodic_memory'):
                                    _p.episodic_memory.record("heirloom_created", f"{_p.name} forged {_h.name}")
                                if hasattr(_p, '_pending_reputation_events'):
                                    _p._pending_reputation_events.append("created_heirloom")
                                narrative_panel.add_message(f"{_p.name} forged {_h.name}!", 'Achievement')
            except Exception:
                pass

            advisor.challenge_difficulty = advisor.calculate_difficulty(praxans, buildings, resources)
            # NOTE: season.update() already called above (line ~5857) with elapsed time.
            # Do NOT call season.update(current_time) again — that passes wall-clock time
            # which maps to absurd year numbers.  Only update climate/temperature/weather here.
            global_climate.update(current_time)
            temperature_grid.update(current_time, world_map, season, weather_system, buildings, global_climate)
            weather_event = weather_system.update(current_time, season.current, advisor.challenge_difficulty)
            if weather_event and weather_event['type'] != 'clear':
                narrative_panel.add_message(f"Weather Alert: {weather_event['type']}!", 'Crisis')
                # Apply burst ecology damage on weather event start (storm/drought scorches the land)
                ecology_manager.apply_weather_event(weather_event['type'], event_bus=event_bus)
                if weather_event['type'] in ('storm', 'drought'):
                    impact = 25.0 if weather_event['type'] == 'storm' else 15.0
                    affected_count = 0
                    for _t in praxans:
                        if random.random() < 0.4:
                            _t.take_damage(impact, 'crush')
                            _t.needs['energy'] = max(0.0, _t.needs['energy'] - impact)
                            affected_count += 1
                            
                    # Spawn dynamic hazards (Phase 4 Phenomena)
                    if random.random() < 0.4:
                        if praxans:
                            # Spawn near colony but slightly offset
                            center_praxan = random.choice(praxans)
                            hx = center_praxan.x + random.uniform(-600, 600)
                            hy = center_praxan.y + random.uniform(-600, 600)
                        else:
                            hx = random.uniform(100, camera.world_width - 100)
                            hy = random.uniform(100, camera.world_height - 100)
                            
                        hazard_type = 'wildfire' if weather_event['type'] == 'drought' or random.random() < 0.5 else 'flash_flood'
                        radius = random.uniform(150, 400)
                        duration = weather_event.get('duration', 30.0) * random.uniform(0.8, 1.5)
                        
                        world_map.hazards.append(TerrainHazard(hx, hy, hazard_type, radius=radius, duration=duration))
                        narrative_panel.add_message(f"A massive {hazard_type.replace('_', ' ')} erupted!", 'Crisis')
                        
                        # Destroy flora in the hazard zone immediately
                        if world_map.botany_manager:
                            for p in world_map.botany_manager.plants:
                                if not p.is_dead and math.hypot(p.x - hx, p.y - hy) < radius:
                                    p.die()
                                    
                    record_observer_timeline_event(
                        advisor,
                        current_time,
                        "disaster",
                        f"A severe {weather_event['type']} struck the settlement",
                        f"{affected_count} praxans suffered immediate health and energy damage from the catastrophe."
                    )

            # Ecology regeneration tick — fertility recovers based on season, weather, biome.
            # This drives the resource scarcity feedback loop: overharvested land recovers
            # slowly, drought scorches fertility, spring rain accelerates regrowth.
            # EventBus events fire on degradation (Barren/Degraded) and recovery.
            ecology_manager.update(current_time, season=season, weather_system=weather_system, event_bus=event_bus)

            # Sync environment context to advisor so LLM prompts include season/weather/ecology
            advisor.environment_context = {
                "season": season.current,
                "year": season.year,
                "weather": weather_system.current_weather,
                "climate_epoch": getattr(global_climate, "epoch", "Holocene"),
                "ecology": ecology_manager.get_world_fertility_summary(),
            }

            # Get weather effects for building and praxan updates
            weather_effects = weather_system.get_effects()
            
            # Update buildings (production, etc.) will be handled by TickManager now
            # Only weather effects logic remains here if needed (it's pulled in by TickManager though)

            settlement_state = compute_settlement_snapshot(praxans, buildings, world_map, season, weather_system)
            update_settlement_celebration(
                celebration_state,
                settlement_state,
                praxans,
                buildings,
                particle_system,
                narrative_panel,
                current_time,
                delta_time,
            )
            bootstrap_building = attempt_bootstrap_construction(
                praxans=praxans,
                buildings=buildings,
                resources=resources,
                advisor=advisor,
                city_planner=city_planner,
                world_map=world_map,
                particle_system=particle_system,
                narrative_panel=narrative_panel,
                current_time=current_time,
                reputation_manager=reputation_manager,
            )
            if bootstrap_building is not None:
                settlement_state = compute_settlement_snapshot(praxans, buildings, world_map, season, weather_system)
            advisor.current_settlement_state = settlement_state
            refresh_run_summary_cache(
                advisor,
                praxans,
                buildings,
                current_time,
                game_start_time,
                faction_manager=faction_manager,
                scenario_id=scenario_profile["id"],
                scenario_name=scenario_profile["name"],
                selected_model=advisor.last_model_used or selected_model,
                seed=runtime_config.seed,
                session_id=game_logger.session_id,
                extinction=game_over,
                force=False,
            )
            if runtime_config.telemetry_interval > 0.0 and (
                frame_count == 1 or current_time - last_telemetry_time >= runtime_config.telemetry_interval
            ):
                telemetry_sample = build_runtime_telemetry_sample(
                    current_time=current_time,
                    game_start_time=game_start_time,
                    frame_count=frame_count,
                    praxans=praxans,
                    buildings=buildings,
                    resources=resources,
                    advisor=advisor,
                    settlement_state=settlement_state,
                    season=season,
                    weather_system=weather_system,
                    faction_manager=faction_manager,
                    runtime_config=runtime_config,
                    selected_model=advisor.last_model_used or selected_model,
                    time_speed_value=TIME_SPEED_OPTIONS[current_time_speed],
                )
                game_logger.log_telemetry(telemetry_sample)
                last_telemetry_time = current_time
            
            # Weather effects are now handled inside Praxan.tick_normal via TickManager
            
            # Maintain resource counts by respawning resources if needed
            num_food_active = sum(1 for r in resources if r.resource_type == 'food' and not r.collected)
            num_wood_active = sum(1 for r in resources if r.resource_type == 'wood' and not r.collected)
            num_stone_active = sum(1 for r in resources if r.resource_type == 'stone' and not r.collected)
            
            # Apply seasonal modifiers
            season_modifiers = season.get_resource_modifier()
            
            if num_wood_active < WOOD_MAX_ON_MAP * season_modifiers['wood']:
                # Spawn a new wood resource with biome bonus + ecology fertility
                x = random.randint(100, camera.world_width - 100)
                y = random.randint(100, camera.world_height - 100)
                fertility_mult = ecology_manager.get_fertility_multiplier(x, y)

                if world_map:
                    biome_type = world_map.get_biome_at(x, y)
                    biome_props = world_map.get_biome_properties(biome_type)
                    wood_bonus = biome_props.get('wood_bonus', 1.0)
                    if random.random() < wood_bonus * 0.5 * fertility_mult:
                        resources.append(Resource(x, y, 'wood'))
                else:
                    if random.random() < fertility_mult:
                        resources.append(Resource(x, y, 'wood'))

            if num_stone_active < STONE_MAX_ON_MAP:
                # Spawn a new stone resource with biome bonus + ecology fertility
                x = random.randint(100, camera.world_width - 100)
                y = random.randint(100, camera.world_height - 100)
                fertility_mult = ecology_manager.get_fertility_multiplier(x, y)

                if world_map:
                    biome_type = world_map.get_biome_at(x, y)
                    biome_props = world_map.get_biome_properties(biome_type)
                    stone_bonus = biome_props.get('stone_bonus', 1.0)
                    if random.random() < stone_bonus * 0.5 * fertility_mult:
                        resources.append(Resource(x, y, 'stone'))
                else:
                    if random.random() < fertility_mult:
                        resources.append(Resource(x, y, 'stone'))
            
            # First pass: Sync entities and run staggered ticking
            game_state = {
                'praxans': praxans,
                'buildings': buildings,
                'resources': resources,
                'advisor': advisor,
                'narrative_panel': narrative_panel,
                'weather_effects': weather_effects,
                'temperature_grid': temperature_grid,
                'world_map': world_map,
                'rooms': rooms,
                'season': season,
                'settlement_state': settlement_state,
                'policy_manager': policy_manager,
                'storyteller': getattr(advisor, 'storyteller', None),
                'ecology_manager': ecology_manager,
            }
            tick_manager.sync_entities(praxans, buildings)
            tick_manager.tick(delta_time, game_state)
            # Update Quest System (Pillar 8) — must run after full game_state is built
            quest_manager.update(game_state)
            
            # Update biological systems (Phase 2 and 3)
            if world_map.botany_manager:
                world_map.botany_manager.update(current_time, temperature_grid, ecology_manager)
            if world_map.zoology_manager:
                dead_animals = world_map.zoology_manager.update(current_time, temperature_grid, world_map, world_map.botany_manager)
                if dead_animals:
                    # NOTE: do NOT use `import random` here — it shadows the
                    # module-level import and makes `random` an unresolved local
                    # throughout all of main() in Python 3.13+.  math and random
                    # are already imported at the top of the file.
                    for da in dead_animals:
                        amount = da.def_data.get('food_value', 5)
                        for _ in range(amount):
                            angle = random.uniform(0, math.pi * 2)
                            dist = random.uniform(2, 15)
                            rx = max(20, min(camera.world_width - 20, da.x + math.cos(angle) * dist))
                            ry = max(20, min(camera.world_height - 20, da.y + math.sin(angle) * dist))
                            resources.append(Resource(rx, ry, 'food'))

            # Remove monolithic O(N) updates and extract dead praxans for cleanup
            praxans_to_remove = []
            for idx, praxan in enumerate(praxans):
                if not praxan.alive:
                    if not getattr(praxan, 'death_processed', False):
                        praxan.death_processed = True
                        # Create death particle effect
                        particle_system.create_particles(praxan.x, praxan.y, 'death', 10)
                        praxans_to_remove.append(idx)
                        dead_name = getattr(praxan, 'name', f'#{praxan.id}')
                        narrative_panel.add_message(f"{dead_name} has passed away...", 'Crisis')
                        advisor.total_deaths = getattr(advisor, 'total_deaths', 0) + 1

                        # Apply grief moodlets to all surviving praxans with relationships
                        for survivor in praxans:
                            if survivor.alive and survivor.id != praxan.id:
                                survivor.apply_grief(praxan.id, current_time)
                        
                        # Track death cause
                        if praxan.age >= PRAXAN_MAX_AGE:
                            cause = 'old_age'
                        elif getattr(praxan, 'last_death_cause_hint', ''):
                            cause = str(getattr(praxan, 'last_death_cause_hint'))
                        elif praxan.health <= 0:
                            cause = 'health_failure'
                        else:
                            cause = 'unknown'
                            
                        advisor.session_stats['deaths_by_cause'][cause] = advisor.session_stats['deaths_by_cause'].get(cause, 0) + 1
                        previous_average = advisor.session_stats.get('avg_survival_time', 0.0)
                        death_count = max(1, advisor.total_deaths)
                        advisor.session_stats['avg_survival_time'] = (
                            ((previous_average * max(0, death_count - 1)) + praxan.age) / death_count
                        )
                        
                        append_bounded_history(
                            advisor.session_stats.setdefault('lineage_events', []),
                            {
                                "time": current_time,
                                "label": (
                                    f"Death: #{praxan.id} G{getattr(praxan, 'generation', 0)} "
                                    f"L{getattr(praxan, 'lineage_id', praxan.id)} ({cause})"
                                ),
                            },
                            16,
                        )
                        
                        record_observer_timeline_event(
                            advisor,
                            current_time,
                            "death",
                            f"{dead_name} (L{getattr(praxan, 'lineage_id', praxan.id)}) has died",
                            f"Cause: {cause.replace('_', ' ')}. Stage: {getattr(praxan, 'life_stage', 'unknown')}.",
                        )
                        # Signal death to ritual system for mourning ceremonies
                        if getattr(praxan, 'faction_id', None) is not None:
                            ritual_manager.signal_death(praxan.faction_id, current_time)
                        # Remove dead praxan from personality evolution zone tracking
                        personality_evolution_manager.cleanup_praxan(praxan.id)
            
            # Update factions outside the loop for efficiency
            faction_manager.update_factions(praxans, advisor,
                                            diplomacy_manager=diplomacy_manager,
                                            event_bus=event_bus,
                                            ecology_manager=ecology_manager,
                                            reputation_manager=reputation_manager)
            trade_system.update(
                faction_manager,
                praxans,
                current_time,
                diplomacy_manager=diplomacy_manager,
                advisor=advisor,
            )
            faction_manager.apply_autonomous_pressure(
                praxans,
                advisor,
                world_map,
                world_width,
                world_height,
                current_time,
            )

            # Periodically update room detection (every 5 seconds)
            if current_time - last_room_update > 5.0:
                update_rooms(rooms, buildings, world_width, world_height)
                last_room_update = current_time
            
            # Remove dead praxans (in reverse order to maintain indices)
            for idx in reversed(praxans_to_remove):
                praxans.pop(idx)
                print(f"A praxan has died. Population: {len(praxans)}")
            
            # Check for extinction
            if len(praxans) == 0 and not game_over:
                game_over = True
                ui_state.end_summary_open = True
                ui_state.active_modal = None
                extinction_summary = refresh_run_summary_cache(
                    advisor,
                    praxans,
                    buildings,
                    current_time,
                    game_start_time,
                    faction_manager=faction_manager,
                    scenario_id=scenario_profile["id"],
                    scenario_name=scenario_profile["name"],
                    selected_model=advisor.last_model_used or selected_model,
                    seed=runtime_config.seed,
                    session_id=game_logger.session_id,
                    extinction=True,
                    force=True,
                )
                final_stats = {
                    'phase': extinction_summary.get('current_phase', {}).get('label', 'Crisis / End-State'),
                    'end_state': extinction_summary.get('end_state', {}).get('label', 'Lineage Extinction'),
                    'observer_score': int(extinction_summary.get('end_state', {}).get('score', 0) or 0),
                    'days_survived': advisor.civilization_age,
                    'max_population': advisor.session_stats.get('max_population', INITIAL_POPULATION),
                    'total_deaths': advisor.total_deaths,
                    'buildings_built': sum(advisor.session_stats.get('buildings_built', {}).values()),
                    'research_points': advisor.research_points,
                    'techs_unlocked': len(advisor.game_modifiers.tech_unlocked),
                }
                narrative_panel.add_message("EXTINCTION: The civilization has fallen...", 'Crisis')
                
                # Calculate unlocks based on performance
                new_unlocks = []
                if final_stats['days_survived'] >= 10:
                    new_unlocks.append('head_start')
                if final_stats['max_population'] >= 15:
                    new_unlocks.append('wise_elders')
                if final_stats['buildings_built'] >= 8:
                    new_unlocks.append('architect')
                if final_stats['research_points'] >= 200:
                    new_unlocks.append('prepared')
                
                # Save legacy data
                save_legacy_data(final_stats, new_unlocks)
                if new_unlocks:
                    narrative_panel.add_message(f"Unlocked bonuses: {', '.join(new_unlocks)}", 'Achievement')
            
            # Get conditional behaviors for this frame
            conditional_behaviors = advisor.get_conditional_behaviors(praxans, buildings, resources)
            
            # Process group tasks: assign praxans to group tasks
            for group_task in advisor.group_tasks:
                if not group_task.is_complete():
                    # Find suitable praxans for this task
                    available_praxans = [t for t in praxans if 
                                           t.id not in group_task.assigned_praxans and
                                           t.needs['hunger'] > 50 and t.needs['energy'] > 50]
                    
                    # Assign based on role match
                    for praxan in available_praxans:
                        if len(group_task.assigned_praxans) >= group_task.required_count:
                            break
                        if group_task.task_type == 'build' and praxan.role == 'builder':
                            group_task.add_praxan(praxan.id)
                        elif group_task.task_type == 'gather' and praxan.role == 'gatherer':
                            group_task.add_praxan(praxan.id)
                        elif group_task.task_type == 'explore' and praxan.role == 'explorer':
                            group_task.add_praxan(praxan.id)
                        elif not praxan.role:  # No role yet, assign anyway
                            group_task.add_praxan(praxan.id)
            
            for idx, praxan in enumerate(praxans):
                # Safety check - skip invalid praxans
                if praxan is None or not hasattr(praxan, 'id'):
                    continue
                try:
                    # Get individual directive for this praxan
                    individual_directive = advisor.get_individual_directive(praxan.id)
                    
                    # Check if praxan is assigned to a group task
                    group_task = None
                    for task in advisor.group_tasks:
                        if praxan.id in task.assigned_praxans:
                            group_task = task
                            break
                    
                    # Combine legacy directives with individual and conditional behaviors
                    combined_directives = advisor.directives.copy()
                    
                    # Add conditional behaviors as directives
                    for behavior in conditional_behaviors:
                        if isinstance(behavior, dict):
                            combined_directives.append(behavior)
                    
                    if individual_directive:
                        # Convert individual directive to directive format for compatibility
                        combined_directives.append({
                            'priority': 8,  # High priority for individual directives
                            'action': individual_directive,
                            'reasoning': 'Individual directive'
                        })
                    
                    # If in a group task, add group task directive
                    if group_task:
                        combined_directives.append({
                            'priority': 7,
                            'action': group_task.description,
                            'reasoning': f'Group task: {group_task.task_type}'
                        })
                    
                    # Autonomous decision-making (no per-praxan LLM)
                    # Pass is_night to influence energy decay, and praxans list for mate-seeking
                    # Create a safe copy of praxans list to avoid iteration issues
                    try:
                        # Filter out None or invalid praxans for safety
                        safe_praxans = [t for t in praxans if t is not None and hasattr(t, 'id') and hasattr(t, 'inventory')]
                        building_type = praxan.decide_action(resources, buildings, delta_time, combined_directives, is_night, safe_praxans, advisor.group_tasks, conditional_behaviors, territory_manager, city_planner, world_map.hazards if world_map else [], world_map, game_hour=game_hour, rooms=rooms)
                    except Exception as e:
                        game_logger.log_error(f"Error in praxan {praxan.id if hasattr(praxan, 'id') else 'unknown'} decide_action: {str(e)}", exc_info=True)
                        building_type = None  # Skip this praxan for this frame
                    
                    # Handle building from directive
                    if building_type:
                        if praxan.next_build_location:
                            build_x = float(praxan.next_build_location[0])
                            build_y = float(praxan.next_build_location[1])
                        else:
                            build_origin_x = round(praxan.x / TILE_SIZE) * TILE_SIZE
                            build_origin_y = round(praxan.y / TILE_SIZE) * TILE_SIZE
                            build_x, build_y = building_origin_to_anchor(build_origin_x, build_origin_y, building_type, TILE_SIZE)
                        praxan.next_build_location = None  # Clear for next build
                        
                        new_building = Building(build_x, build_y, building_type)
                        new_building.built_at = current_time
                        new_building.built_by = praxan.id
                        if world_map is not None and hasattr(world_map, 'get_biome_at'):
                            try:
                                new_building.origin_biome = world_map.get_biome_at(build_x, build_y)
                            except Exception:
                                new_building.origin_biome = None
                        if not new_building.material_style:
                            new_building.material_style = new_building._derive_material_style(new_building.origin_biome)
                        buildings.append(new_building)
                        # Create particle effect
                        particle_system.create_particles(build_x, build_y, 'build', 12)
                        # Gain building skill XP
                        praxan.gain_skill_xp('building', SKILL_XP_BUILDING)
                        # Record success for Q-learning
                        praxan.record_success('build_' + building_type)
                        record_observer_timeline_event(
                            advisor,
                            current_time,
                            "build",
                            f"Built {building_type}",
                            f"Builder #{praxan.id} completed new infrastructure.",
                        )
                        # Track building statistics
                        advisor.session_stats['buildings_built'][building_type] = advisor.session_stats['buildings_built'].get(building_type, 0) + 1
                    
                    # Check collision with resources - now requires gathering time
                    for resource in resources:
                        if resource.check_collision(praxan):
                            # Determine required gathering time based on resource type
                            if resource.resource_type == 'food':
                                required_time = RESOURCE_GATHER_TIME_FOOD
                            elif resource.resource_type == 'wood':
                                required_time = RESOURCE_GATHER_TIME_WOOD
                            elif resource.resource_type == 'stone':
                                required_time = RESOURCE_GATHER_TIME_STONE
                            else:
                                required_time = 3.0  # Default
                            
                            # Apply gather_rate modifier and skill bonus to reduce time
                            gather_rate = advisor.game_modifiers.get_modifier('gather_rate') if advisor.game_modifiers else 1.0
                            skill_bonus = praxan.get_gathering_bonus() if praxan.role == 'gatherer' else 1.0
                            required_time = required_time / (gather_rate * skill_bonus)
                            
                            # Start gathering if not already gathering this resource
                            if praxan.gathering_resource != resource:
                                praxan.gathering_resource = resource
                                praxan.gathering_start_time = current_time
                                praxan.current_action = f"gathering {resource.resource_type}"
                                praxan.vx = 0  # Stop moving while gathering
                                praxan.vy = 0
                            
                            # Check if gathering is complete
                            elapsed_time = current_time - praxan.gathering_start_time
                            if elapsed_time >= required_time:
                                resource.collected = True
                                resource.collect_time = current_time
                                
                                # Get workshop bonus, skill bonus, and role bonus for gathering
                                workshop_bonus = praxan.get_workshop_bonus(buildings, advisor.game_modifiers)
                                skill_bonus = praxan.get_gathering_bonus() if praxan.role == 'gatherer' else 1.0
                                role_bonus = GATHERER_SPEED_BONUS if praxan.role == 'gatherer' else 1.0
                                efficiency = 1.0 - (overpopulation_penalty * 0.01)  # Max -10% at full penalty
                                resources_gained = workshop_bonus * skill_bonus * role_bonus * efficiency
                                
                                if resource.resource_type == 'food':
                                    praxan.inventory['food'] += int(resources_gained)
                                    # Handle fractional gathering (store in float)
                                    if not hasattr(praxan, 'fractional_inventory'):
                                        praxan.fractional_inventory = {'food': 0.0, 'wood': 0.0, 'stone': 0.0}
                                    praxan.fractional_inventory['food'] += (resources_gained - int(resources_gained))
                                    if praxan.fractional_inventory['food'] >= 1.0:
                                        praxan.inventory['food'] += 1
                                        praxan.fractional_inventory['food'] -= 1.0
                                    
                                    praxan.needs['hunger'] = min(100, praxan.needs['hunger'] + 20)  # Eating restores hunger
                                    # Create particle effect
                                    particle_system.create_particles(resource.x, resource.y, 'sparkle', 8)
                                    # Record success for Q-learning
                                    praxan.record_success('gather_food')
                                elif resource.resource_type == 'wood':
                                    praxan.inventory['wood'] += int(resources_gained)
                                    if not hasattr(praxan, 'fractional_inventory'):
                                        praxan.fractional_inventory = {'food': 0.0, 'wood': 0.0, 'stone': 0.0}
                                    praxan.fractional_inventory['wood'] += (resources_gained - int(resources_gained))
                                    if praxan.fractional_inventory['wood'] >= 1.0:
                                        praxan.inventory['wood'] += 1
                                        praxan.fractional_inventory['wood'] -= 1.0
                                    
                                    # Create particle effect
                                    particle_system.create_particles(resource.x, resource.y, 'dust', 6)
                                    # Record success for Q-learning
                                    praxan.record_success('gather_wood')
                                elif resource.resource_type == 'stone':
                                    praxan.inventory['stone'] += int(resources_gained)
                                    if not hasattr(praxan, 'fractional_inventory'):
                                        praxan.fractional_inventory = {'food': 0.0, 'wood': 0.0, 'stone': 0.0}
                                    praxan.fractional_inventory['stone'] += (resources_gained - int(resources_gained))
                                    if praxan.fractional_inventory['stone'] >= 1.0:
                                        praxan.inventory['stone'] += 1
                                        praxan.fractional_inventory['stone'] -= 1.0
                                    
                                    # Create particle effect
                                    particle_system.create_particles(resource.x, resource.y, 'dust', 6)
                                    # Record success for Q-learning
                                    praxan.record_success('gather_stone')
                                
                                if VERBOSE_LOGGING:
                                    print(f"[Praxan {idx}] *** Gathered {resource.resource_type}! Inventory now: {praxan.inventory}")
                                
                                # Gain skill XP for gathering
                                praxan.gain_skill_xp('gathering', SKILL_XP_GATHERING)

                                # Record ecological impact of harvesting
                                ecology_manager.record_harvest(resource.x, resource.y, resource.resource_type)

                                # Track bounty challenge progress
                                for challenge in advisor.active_challenges:
                                    if challenge['type'] == 'bounty':
                                        challenge['collected'] = challenge.get('collected', 0) + 1
                                
                                # Clear gathering state
                                praxan.gathering_resource = None
                                praxan.gathering_start_time = 0
                            # Continue gathering in next frame
                            break
                    else:
                        # Not near any resource, clear gathering state if was gathering
                        if praxan.gathering_resource:
                            praxan.gathering_resource = None
                            praxan.gathering_start_time = 0
                    
                    # Check building interaction
                    for building in buildings:
                        distance = math.sqrt((building.x - praxan.x)**2 + (building.y - praxan.y)**2)
                        if distance < 15:  # Within interaction range (adjusted for smaller sprites)
                            if building.building_type == 'house' and building.enter(praxan, advisor.game_modifiers):
                                # Restoring energy in house
                                praxan.needs['energy'] = min(100, praxan.needs['energy'] + 0.5)
                                praxan.current_action = "resting"
                            elif building.building_type == 'farm' and building.stored_resources['food'] > 0:
                                # Collect food from farm
                                building.stored_resources['food'] -= 1
                                praxan.inventory['food'] += 1
                                praxan.needs['hunger'] = min(100, praxan.needs['hunger'] + 30)
                                if VERBOSE_LOGGING:
                                    print(f"[Praxan {idx}] *** Collected food from farm! Hunger: {praxan.needs['hunger']}")
                            elif building.building_type == 'storage':
                                # Deposit resources in storage
                                total_deposited = 0
                                if praxan.inventory['food'] > 0:
                                    building.stored_resources['food'] += praxan.inventory['food']
                                    total_deposited += praxan.inventory['food']
                                    praxan.inventory['food'] = 0
                                if praxan.inventory['wood'] > 0:
                                    building.stored_resources['wood'] += praxan.inventory['wood']
                                    total_deposited += praxan.inventory['wood']
                                    praxan.inventory['wood'] = 0
                                if praxan.inventory['stone'] > 0:
                                    building.stored_resources['stone'] = building.stored_resources.get('stone', 0) + praxan.inventory['stone']
                                    total_deposited += praxan.inventory['stone']
                                    praxan.inventory['stone'] = 0
                                if total_deposited > 0 and VERBOSE_LOGGING:
                                    print(f"[Praxan {idx}] *** Deposited {total_deposited} resources in storage!")
                            elif building.building_type == 'well':
                                # Drink from well to restore thirst (if not disabled by challenge)
                                if not getattr(building, 'challenge_disabled', False):
                                    praxan.needs['thirst'] = min(100, praxan.needs['thirst'] + 0.5)
                        else:
                            # Too far away, leave building if inside
                            building.leave(praxan)
                    
                    # Update position
                    try:
                        safe_praxans_for_update = [t for t in praxans if t is not None and hasattr(t, 'id') and hasattr(t, 'inventory')]
                        praxan.update_position(advisor.game_modifiers, world_map, world_width, world_height, buildings, safe_praxans_for_update)
                    except Exception as e:
                        game_logger.log_error(f"Error updating position for praxan {praxan.id if hasattr(praxan, 'id') else 'unknown'}: {str(e)}", exc_info=True)
                except Exception as e:
                    # Catch any other unexpected errors in praxan update loop
                    game_logger.log_error(f"Unexpected error processing praxan {praxan.id if hasattr(praxan, 'id') else 'unknown'}: {str(e)}", exc_info=True)
                    continue
            
            # Check for encounter discovery and exploration
            for encounter in world_map.encounters:
                if not encounter.discovered:
                    # Check if any praxan is nearby
                    for praxan in praxans:
                        distance = math.sqrt((encounter.x - praxan.x)**2 + (encounter.y - praxan.y)**2)
                        if distance < 50:  # Adjusted for smaller sprites
                            encounter.discovered = True
                            encounter_names = {
                                'ruins': 'Ancient Ruins',
                                'mineral_vein': 'Mineral Vein',
                                'oasis': 'Oasis',
                                'sacred_grove': 'Sacred Grove'
                            }
                            narrative_panel.add_message(f"DISCOVERED: {encounter_names.get(encounter.encounter_type, 'Mysterious Site')}!", 'Achievement')
                            break
                
                # Check for encounter exploration (after discovery, reward only once)
                if encounter.discovered and not encounter.explored and not encounter.reward_given:
                    for praxan in praxans:
                        distance = math.sqrt((encounter.x - praxan.x)**2 + (encounter.y - praxan.y)**2)
                        if distance < 40:  # Within exploration range
                            # Start or continue exploration
                            if praxan.exploring_encounter == encounter:
                                # Continue exploring
                                if current_time - praxan.exploration_start_time >= praxan.exploration_duration:
                                    # Exploration complete! Give rewards
                                    encounter.explored = True
                                    encounter.reward_given = True
                                    praxan.exploring_encounter = None
                                    
                                    # Give rewards based on encounter type
                                    if encounter.encounter_type == 'ruins':
                                        # Random reward type
                                        reward_type = random.choice(['resources', 'tech', 'research'])
                                        if reward_type == 'resources':
                                            # Spawn resources nearby
                                            for _ in range(random.randint(2, 5)):
                                                res_type = random.choice(['food', 'wood', 'stone'])
                                                off_x = encounter.x + random.randint(-60, 60)
                                                off_y = encounter.y + random.randint(-60, 60)
                                                resources.append(Resource(off_x, off_y, res_type))
                                            narrative_panel.add_message("EXPLORED: Ancient Ruins! Found resources", 'Achievement')
                                        elif reward_type == 'tech':
                                            advisor.research_points += 75
                                            narrative_panel.add_message("EXPLORED: Ancient Ruins! Gained ancient knowledge", 'Achievement')
                                        else:
                                            advisor.research_points += 50
                                            narrative_panel.add_message("EXPLORED: Ancient Ruins! +50 research", 'Achievement')
                                    elif encounter.encounter_type == 'mineral_vein':
                                        # Scale stone bonus with difficulty
                                        stone_bonus = int(5 + advisor.challenge_difficulty * 2)
                                        advisor.research_points += 20
                                        # Add stone directly to nearest storage
                                        for building in buildings:
                                            if building.building_type == 'storage':
                                                building.stored_resources['stone'] += stone_bonus
                                                break
                                        narrative_panel.add_message(f"EXPLORED: Mineral Vein! +{stone_bonus} stone +20 research", 'Achievement')
                                    elif encounter.encounter_type == 'oasis':
                                        # Heal all praxans and restore thirst
                                        for t in praxans:
                                            t.heal_damage(30)
                                            t.needs['thirst'] = 100
                                            # Temporary disease immunity
                                            t.disease_immunity_until = current_time + 60
                                        narrative_panel.add_message("EXPLORED: Oasis! All praxans healed and hydrated", 'Achievement')
                                    elif encounter.encounter_type == 'sacred_grove':
                                        # Increase happiness for all and strengthen bonds
                                        for t in praxans:
                                            t.happiness = min(100, t.happiness + 20)
                                            # Strengthen all bonds
                                            for other in praxans:
                                                if other.id != t.id:
                                                    key = tuple(sorted([t.id, other.id]))
                                                    t.bonds[key] = min(100, t.bonds.get(key, 0) + 20)
                                        advisor.research_points += 30
                                        narrative_panel.add_message("EXPLORED: Sacred Grove! +20 happiness +30 research", 'Achievement')
                            else:
                                # Start new exploration
                                praxan.exploring_encounter = encounter
                                praxan.exploration_start_time = current_time
                        else:
                            # Too far away, cancel exploration if we're exploring this encounter
                            if praxan.exploring_encounter == encounter:
                                praxan.exploring_encounter = None
            
            # Check for disease outbreaks and recovery (typed disease system)
            population_density = len(praxans) / (WINDOW_WIDTH * WINDOW_HEIGHT / 10000)
            num_wells = sum(1 for b in buildings if b.building_type == 'well')
            hygiene_factor = max(0.5, num_wells / max(1, len(praxans) / 5))

            # Ambient contraction check (rare tick cadence)
            for praxan in praxans:
                if not praxan.alive:
                    continue
                biome = "plains"
                if world_map:
                    biome = world_map.get_biome_at(praxan.x, praxan.y)
                current_season = season.current if season else "summer"
                disease_manager.try_contract(
                    praxan,
                    biome=biome,
                    season=current_season,
                    population_density=population_density,
                    hygiene_factor=hygiene_factor,
                    event_bus=event_bus,
                    narrative_panel=narrative_panel,
                )

            # Progress all active diseases (transmission, immunity, recovery)
            disease_manager.update(
                praxans,
                delta_time,
                buildings=buildings,
                world_map=world_map,
                event_bus=event_bus,
                narrative_panel=narrative_panel,
            )

            # Apply pending cascade effects (moodlets, memory, resilience from cross-system reactions)
            cascade_manager.apply_pending_effects(praxans, current_time)

            # Check for NPC interactions
            for npc in world_map.npcs:
                if npc.visible:
                    for praxan in praxans:
                        distance = math.sqrt((npc.x - praxan.x)**2 + (npc.y - praxan.y)**2)
                        if distance < 30:  # Within interaction range (adjusted for smaller sprites)
                            # Start or continue interaction
                            if praxan.interacting_npc == npc:
                                # Continue interacting
                                if current_time - praxan.interaction_start_time >= praxan.interaction_duration:
                                    # Interaction complete! Process based on NPC type
                                    praxan.interacting_npc = None
                                    
                                    if npc.npc_type == 'trader':
                                        # Multiple trade options
                                        trades_available = []
                                        if praxan.inventory['food'] >= 2 and npc.inventory.get('wood', 0) >= 1:
                                            trades_available.append(('food_for_wood', 'food', 2, 'wood', 1))
                                        if praxan.inventory['wood'] >= 2 and npc.inventory.get('stone', 0) >= 1:
                                            trades_available.append(('wood_for_stone', 'wood', 2, 'stone', 1))
                                        if praxan.inventory['wood'] >= 1 and npc.inventory.get('food', 0) >= 2:
                                            trades_available.append(('wood_for_food', 'wood', 1, 'food', 2))
                                        
                                        if trades_available:
                                            trade = random.choice(trades_available)
                                            trade_name, give_res, give_amt, get_res, get_amt = trade
                                            praxan.inventory[give_res] -= give_amt
                                            npc.inventory[give_res] = npc.inventory.get(give_res, 0) + give_amt
                                            praxan.inventory[get_res] += get_amt
                                            npc.inventory[get_res] = npc.inventory.get(get_res, 0) - get_amt
                                            narrative_panel.add_message(f"Trade: {give_amt} {give_res} -> {get_amt} {get_res}", 'Achievement')
                                    elif npc.npc_type == 'rival_tribe':
                                        # Hostile encounter
                                        if random.random() < 0.5:  # 50% chance of negative encounter
                                            praxan.take_damage(15, 'cut')
                                            narrative_panel.add_message("Praxan encountered hostile tribe! -15 health", 'Crisis')
                                    elif npc.npc_type == 'wildlife_herd':
                                        # Friendly encounter, chance to gain food
                                        if random.random() < 0.3:  # 30% chance
                                            praxan.inventory['food'] += 1
                                            narrative_panel.add_message("Wildlife shared food! +1 food", 'Achievement')
                            else:
                                # Start new interaction
                                praxan.interacting_npc = npc
                                praxan.interaction_start_time = current_time
                        else:
                            # Too far away, cancel interaction
                            if praxan.interacting_npc == npc:
                                praxan.interacting_npc = None
            
            # Process active challenges
            for challenge in advisor.active_challenges[:]:
                elapsed = current_time - challenge['start_time']
                if elapsed >= challenge['duration']:
                    # Challenge completed
                    if challenge['type'] == 'bounty':
                        if challenge.get('collected', 0) >= challenge.get('target', 10):
                            advisor.research_points += challenge['reward']
                            narrative_panel.add_message(f"CHALLENGE COMPLETE: Bounty! +{challenge['reward']} research points", 'Achievement')
                        else:
                            narrative_panel.add_message("CHALLENGE FAILED: Bounty incomplete", 'Crisis')
                    else:
                        advisor.research_points += challenge['reward']
                        narrative_panel.add_message(f"CHALLENGE COMPLETE: {challenge['type']}! +{challenge['reward']} research points", 'Achievement')
                    advisor.active_challenges.remove(challenge)
                else:
                    # Apply challenge effects
                    if challenge['type'] == 'drought':
                        # Disable wells
                        for building in buildings:
                            if building.building_type == 'well':
                                # Mark as disabled (we'll check this in interaction)
                                building.challenge_disabled = True
                    elif challenge['type'] == 'plague':
                        # Increase disease chance
                        for praxan in praxans:
                            disease_chance = DISEASE_CHANCE_BASE * 5
                            praxan.contract_disease(disease_chance)
            
            # Reset well disabled status if no drought challenge
            drought_active = any(c['type'] == 'drought' for c in advisor.active_challenges)
            if not drought_active:
                for building in buildings:
                    if building.building_type == 'well':
                        building.challenge_disabled = False
            
            # Track bounty challenge progress
            for challenge in advisor.active_challenges:
                if challenge['type'] == 'bounty':
                    # Will be tracked when resources are collected
                    pass
            
            # Apply terrain hazards with difficulty scaling
            active_hazards = []
            for hazard in world_map.hazards:
                if hazard.active:
                    active_hazards.append(hazard)
                    for praxan in praxans:
                        # Scale damage by difficulty for hazards that deal damage
                        old_health = praxan.health
                        hazard.check_affect(praxan)
                        # Check if health changed, apply difficulty scaling
                        if praxan.health < old_health and advisor.challenge_difficulty > 1.0:
                            damage_scale = advisor.challenge_difficulty
                            additional_damage = (old_health - praxan.health) * (damage_scale - 1.0)
                            praxan.take_damage(additional_damage, 'difficulty')
            world_map.hazards = active_hazards
            
            # Check for reproduction opportunities
            if len(praxans) < MAX_POPULATION:
                for i in range(len(praxans)):
                    for j in range(i + 1, len(praxans)):
                        praxan1 = praxans[i]
                        praxan2 = praxans[j]
                        
                        # Check if both can reproduce
                        if not praxan1.can_reproduce() or not praxan2.can_reproduce():
                            continue
                        
                        # Check proximity
                        distance = math.sqrt((praxan1.x - praxan2.x)**2 + (praxan1.y - praxan2.y)**2)
                        if distance > REPRODUCTION_PROXIMITY:
                            continue
                        
                        # Reproduction successful!
                        # Create offspring near the parents
                        mid_x = (praxan1.x + praxan2.x) / 2
                        mid_y = (praxan1.y + praxan2.y) / 2
                        offset_x = random.uniform(-20, 20)
                        offset_y = random.uniform(-20, 20)
                        child = Praxan.create_offspring(
                            praxan1,
                            praxan2,
                            max(20, min(world_width - 20, mid_x + offset_x)),
                            max(20, min(world_height - 20, mid_y + offset_y)),
                        )
                        praxans.append(child)
                        
                        # Share knowledge between parents
                        praxan1.share_knowledge(praxan2)
                        praxan2.share_knowledge(praxan1)
                        # Create knowledge particle effect
                        if random.random() < 0.3:  # 30% chance per reproduction
                            particle_system.create_particles(mid_x, mid_y, 'knowledge', 5)
                        
                        # Update cooldowns
                        praxan1.last_reproduction_time = current_time
                        praxan2.last_reproduction_time = current_time
                        
                        # Visual feedback
                        praxan1.reproduction_message = "♥"
                        praxan1.reproduction_message_time = current_time
                        praxan2.reproduction_message = "♥"
                        praxan2.reproduction_message_time = current_time
                        
                        # Create particle effects (hearts)
                        particle_system.create_particles(praxan1.x, praxan1.y, 'heart', 15)
                        particle_system.create_particles(praxan2.x, praxan2.y, 'heart', 15)
                        
                        # Add narrative message with names
                        child_name = getattr(child, 'name', f'#{child.id}')
                        p1_name = getattr(praxan1, 'name', f'#{praxan1.id}')
                        p2_name = getattr(praxan2, 'name', f'#{praxan2.id}')
                        narrative_panel.add_message(
                            f"{child_name} born to {p1_name} & {p2_name} (Gen {child.generation}). Pop: {len(praxans)}",
                            'Achievement',
                        )

                        record_observer_timeline_event(
                            advisor,
                            current_time,
                            "birth",
                            f"Birth: {child_name} joins lineage {child.lineage_id}",
                            f"Parents: {p1_name} & {p2_name}. Population now {len(praxans)}.",
                        )
                        advisor.session_stats['births_total'] = advisor.session_stats.get('births_total', 0) + 1
                        # Signal birth to ritual system for naming day
                        parent_faction = getattr(praxan1, 'faction_id', None)
                        if parent_faction is not None:
                            ritual_manager.signal_birth(parent_faction, current_time)
                        append_bounded_history(
                            advisor.session_stats.setdefault('lineage_events', []),
                            {
                                "time": current_time,
                                "label": (
                                    f"Birth: #{child.id} G{child.generation} L{child.lineage_id} "
                                    f"from {praxan1.id}/{praxan2.id} mut {child.mutation_count}"
                                ),
                            },
                            16,
                        )
                        record_population_evolution_sample(advisor, praxans, current_time, game_start_time, force=True)
                        
                        print(f"New praxan born! Population: {len(praxans)}")
                        break
                    else:
                        continue
                        break
                
                record_population_evolution_sample(advisor, praxans, current_time, game_start_time, force=False)

                ghost_markers = [
                    {
                        "x": float(site[0]),
                        "y": float(site[1]),
                        "building_type": str(site[2]),
                        "doctrine": str(
                            ((getattr(advisor, "council_state", {}) or {}).get("doctrine", {}) or {}).get("focus", "growth")
                        ),
                    }
                    for site in list(getattr(city_planner, "proposed_sites", []) or [])
                    if isinstance(site, (list, tuple)) and len(site) >= 3
                ]

                render_frame = build_render_frame(
                    world_map=world_map,
                    camera=camera,
                    fog_of_war=fog_of_war,
                    territory_manager=territory_manager,
                    city_planner=city_planner,
                    faction_manager=faction_manager,
                    season=season,
                    weather_system=weather_system,
                    settlement_state=settlement_state,
                    current_time=current_time,
                    game_start_time=game_start_time,
                    frame_count=frame_count,
                    window_size=(WINDOW_WIDTH, WINDOW_HEIGHT),
                    chunk_size=CHUNK_SIZE,
                    tile_size=TILE_SIZE,
                    world_size=(world_width, world_height),
                    buildings=buildings,
                    resources=resources,
                    praxans=praxans,
                    encounters=world_map.encounters,
                    hazards=world_map.hazards,
                    npcs=world_map.npcs,
                    selected_entity=selection_manager.selected_entity,
                    particle_system=particle_system,
                    effect_cues=camera_director.to_payload(),
                    active_overlay=ui_state.map_overlay,
                    camera_bookmarks=camera_director.to_payload(),
                    ghost_markers=ghost_markers,
                )
                scene_renderer.render(screen, render_frame)
            
            current_summary = dict(advisor.session_stats.get("current_run_summary", {}) or {})
            evolution_summary = advisor.session_stats.get("current_evolution_summary") or summarize_population_evolution(praxans)
            llm_status = advisor.get_llm_status_label(
                selected_model
                or ("Disabled" if runtime_config.disable_llm or not LLM_ENABLED else PREFERRED_OLLAMA_MODEL)
            )
            scenario_name = advisor.session_stats.get("scenario_name", scenario_profile["name"])
            doctrine = dict((getattr(advisor, "council_state", {}) or {}).get("doctrine", {}) or {})
            doctrine_label = str(doctrine.get("focus") or doctrine.get("stance") or "Autonomous").replace("_", " ").title()
            phase_label = current_summary.get("current_phase", {}).get("label", "Founding")
            observer_score = int(current_summary.get("end_state", {}).get("score", 0) or 0)
            if praxans:
                colony_center = (
                    sum(praxan.x for praxan in praxans) / len(praxans),
                    sum(praxan.y for praxan in praxans) / len(praxans),
                )
            else:
                colony_center = None
            camera_director.sync_from_summary(current_summary, current_time, colony_center)
            cue_label = camera_director.apply(
                camera,
                current_time,
                (WINDOW_WIDTH, WINDOW_HEIGHT),
                manual_override=bool(getattr(camera, "panning", False)),
            )
            if cue_label:
                ui_state.camera_mode = "event"
                ui_state.camera_cue = cue_label
            else:
                ui_state.camera_cue = None
                ui_state.camera_mode = "follow" if camera.follow_mode else "free"

            active_challenges = list(getattr(advisor, "active_challenges", []) or [])
            if active_challenges:
                crisis_label = str(active_challenges[0].get("type", "Crisis")).replace("_", " ").title()
            elif population_ratio >= 1.0:
                crisis_label = "Capacity Reached"
            elif population_ratio >= OVERPOPULATION_THRESHOLD:
                crisis_label = "Overcapacity"
            else:
                crisis_label = "Stable"

            ui_registry.reset()
            run_layout = compute_run_layout(WINDOW_WIDTH, WINDOW_HEIGHT)
            # Build ecology summary for HUD environment ribbon
            _eco_summary = ecology_manager.get_world_fertility_summary()
            _eco_counts = _eco_summary.get("region_counts", {})
            _eco_parts = []
            for _eco_status in ("Barren", "Degraded", "Stressed"):
                _eco_n = _eco_counts.get(_eco_status, 0)
                if _eco_n > 0:
                    _eco_parts.append(f"{_eco_n} {_eco_status}")
            _ecology_label = ", ".join(_eco_parts) if _eco_parts else f"Avg {_eco_summary.get('avg_fertility', 80):.0f}%"

            hud_model = RunHudModel(
                scenario_name=scenario_name,
                phase_label=phase_label,
                doctrine_label=doctrine_label,
                llm_status=llm_status,
                speed_label=f"{TIME_SPEED_OPTIONS[current_time_speed]:.1f}x",
                follow_label="Follow" if camera.follow_mode else "Free",
                camera_mode_label=ui_state.camera_mode.title(),
                crisis_label=crisis_label,
                overlay_label=ui_state.map_overlay.title(),
                observer_score=observer_score,
                cue_label=ui_state.camera_cue or "",
                season_label=f"{season.current.title()} Y{season.year}",
                weather_label=weather_system.current_weather.title(),
                ecology_label=_ecology_label,
                climate_epoch=getattr(global_climate, 'epoch', ''),
            )
            field_notes = build_field_notes(advisor.session_stats.get("timeline_events", []), current_time, limit=6)
            minimap_context = {
                "world_map": world_map,
                "camera": camera,
                "city_planner": city_planner,
                "faction_manager": faction_manager,
                "praxans": praxans,
                "buildings": buildings,
                "fog_of_war": fog_of_war,
                "camera_bookmarks": camera_director.to_payload(),
                "biome_colors": {
                    "forest": GRASS_DARK,
                    "plains": GRASS_MID,
                    "mountains": ROCK_MID,
                    "desert": DESERT_SAND,
                    "snow": SNOW_WHITE,
                    "swamp": SWAMP_DARK,
                    "taiga": TAIGA_GREEN,
                    "tundra": ICE_BLUE,
                },
                "chunk_size": CHUNK_SIZE,
                "tile_size": TILE_SIZE,
                "window_size": (WINDOW_WIDTH, WINDOW_HEIGHT),
            }
            draw_run_hud(
                screen,
                ui_theme,
                run_layout,
                ui_registry,
                hud_model,
                field_notes,
                ui_state,
                current_time_speed,
                minimap_context,
                advisor=advisor,
            )

            if ui_state.show_work_priority:
                work_panel.draw(screen, praxans, ui_registry)
            
            if ui_state.show_schedule:
                schedule_panel.draw(screen, praxans, ui_registry, game_hour)
            inspect_model = build_inspect_view_model(
                selection_manager.selected_entity,
                selection_manager.selected_type,
                advisor,
                current_time,
                settlement_state,
                faction_manager=faction_manager,
                active_tab=ui_state.inspect_tab,
                praxans=praxans,
                diplomacy_manager=diplomacy_manager,
            )
            draw_inspect_drawer(
                screen,
                ui_theme,
                run_layout,
                ui_registry,
                inspect_model,
                scroll_offset=ui_state.inspect_scroll,
            )
            if not ui_state.end_summary_open:
                draw_modal_layer(
                    screen,
                    ui_theme,
                    run_layout,
                    ui_registry,
                    ui_state,
                    advisor=advisor,
                    current_summary=current_summary,
                    current_time=current_time,
                    log_dir=game_logger.log_dir,
                    evolution_summary=evolution_summary,
                )
            if ui_state.show_quit_prompt:
                quit_prompt_rect = pygame.Rect(run_layout.top_ribbon.centerx - 150, run_layout.top_ribbon.bottom + 12, 300, 54)
                ui_registry.register("quit_prompt", quit_prompt_rect, layer=25)
                draw_panel(screen, quit_prompt_rect, ui_theme, fill=(40, 28, 24), alpha=240, radius=ui_theme.radius_large)
                prompt_text = ui_theme.fonts.caption.render("Press Esc again or Enter to quit the run", True, ui_theme.palette.parchment)
                screen.blit(prompt_text, (quit_prompt_rect.x + 22, quit_prompt_rect.y + 18))

            # Draw tooltip (pass faction_manager for enhanced info)
            tooltip_system.draw_tooltip(screen, mouse_screen_pos[0], mouse_screen_pos[1], faction_manager)

            # Draw search overlay (toggled via /)
            search_overlay.draw(screen, ui_theme.fonts.label, camera, theme=ui_theme)
            search_overlay.draw_world_highlights(screen, camera)

            # Draw colony history graph overlay (toggled via H)
            history_renderer.draw(screen, history_tracker, ui_theme.fonts.caption, theme=ui_theme)
            
            # Quick on-screen debug watermark for the first 3 seconds after start
            if current_time - game_start_time < 3.0:
                try:
                    debug_text = font_small.render("DEBUG: RENDER OK", True, (255, 255, 0))
                    screen.blit(debug_text, (10, 5))
                except Exception as overlay_error:
                    if not debug_watermark_error_logged:
                        game_logger.logger.warning(
                            "Debug watermark render failed (suppressed after first warning): %s",
                            overlay_error,
                            exc_info=True,
                        )
                        debug_watermark_error_logged = True
                    
            # Storyteller Debug Overlay
            if not getattr(runtime_config, 'headless', False):
                try:
                    y_offset = 120
                    st_text1 = font_small.render(f"Storyteller Phase: {storyteller.current_phase.upper()}", True, (255, 200, 100))
                    st_text2 = font_small.render(f"Colony Wealth: {storyteller.colony_wealth:.0f}", True, (200, 255, 100))
                    st_text3 = font_small.render(f"Threat Points: {storyteller.accumulated_points:.1f} / {storyteller.threat_points:.1f}/sec", True, (255, 100, 100))
                    screen.blit(st_text1, (10, y_offset))
                    screen.blit(st_text2, (10, y_offset + 20))
                    screen.blit(st_text3, (10, y_offset + 40))
                except Exception as overlay_error:
                    if not storyteller_overlay_error_logged:
                        game_logger.logger.warning(
                            "Storyteller overlay render failed (suppressed after first warning): %s",
                            overlay_error,
                            exc_info=True,
                        )
                        storyteller_overlay_error_logged = True
            
            # Screen tint for critical overpopulation
            if population_ratio >= 1.0:
                tint = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
                tint.set_alpha(30)
                tint.fill((255, 100, 100))
                screen.blit(tint, (0, 0))
            
            if game_over and ui_state.end_summary_open:
                draw_end_summary(
                    screen,
                    ui_theme,
                    run_layout,
                    ui_registry,
                    current_summary,
                    snapshot_resume_path or "pending",
                )
            
            # Always flip display and tick clock
            # CRITICAL: This must happen every frame to show the rendered content
            # #region agent log
            if frame_count <= 5:
                debug_log("main:flip_before_final", f"About to flip display (final, frame {frame_count})", {"frame_count": frame_count}, "H4")
            # #endregion
            try:
                pygame.display.flip()
                # #region agent log
                if frame_count <= 5:
                    debug_log("main:flip_after_final", f"Display flipped (final, frame {frame_count})", {"frame_count": frame_count}, "H4")
                # #endregion
            except Exception as e:
                # #region agent log
                debug_log("main:flip_error", "Display flip failed", {"error": str(e), "frame_count": frame_count}, "H4")
                # #endregion
                print(f"[CRITICAL] Failed to flip display: {e}")
                traceback.print_exc()
                game_logger.log_error(f"Display flip error: {e}", exc_info=True)
                # Try to show error on screen if possible
                try:
                    error_text = font.render(f"DISPLAY ERROR: {str(e)[:40]}", True, (255, 0, 0))
                    screen.blit(error_text, (10, 10))
                    pygame.display.flip()
                except Exception:
                    game_logger.logger.exception(
                        "Failed to render emergency on-screen display error banner after flip failure"
                    )
            
            # Tick clock to maintain FPS
            clock.tick(FPS)
            # #region agent log
            if frame_count <= 5:
                debug_log("main:frame_complete", f"Frame {frame_count} complete", {"frame_count": frame_count, "running": running}, "H1")
            # #endregion

            if runtime_config.max_frames and frame_count >= runtime_config.max_frames:
                running = False
            
    except Exception as e:
        # #region agent log
        debug_log("main:loop_exception", "Exception in main loop", {"error": str(e), "error_type": type(e).__name__, "frame_count": frame_count}, "H7")
        # #endregion
        # Catch any exception in main loop
        game_logger.log_error(f"Fatal error in main game loop: {str(e)}", exc_info=True)
        game_logger.flush_logs()
        print(f"\nFATAL ERROR: {str(e)}")
        traceback.print_exc()
    
    finally:
        # Always generate session report and flush logs
        thumbnail_path = None
        try:
            if "scene_renderer" in locals() and getattr(scene_renderer, "last_thumbnail", None) is not None:
                thumbnail_path = os.path.join(game_logger.log_dir, f"thumb_{game_logger.session_id}.png")
                pygame.image.save(scene_renderer.last_thumbnail, thumbnail_path)
        except Exception:
            thumbnail_path = None
        try:
            pygame.quit()  # Ensure pygame is cleaned up
        except Exception:
            pass
        
        try:
            game_logger.save_quick_report()
            snapshot_file = None
            archive_file = None
            next_runtime_config = None
            run_summary = None
            archive_payload = None
            local_names = locals()
            required_snapshot_names = ("praxans", "buildings", "resources", "advisor", "season", "weather_system", "game_start_time")
            if all(name in local_names for name in required_snapshot_names):
                camera_bookmarks = camera_director.to_payload() if "camera_director" in local_names else []
                scene_thumbnail_key = os.path.basename(thumbnail_path) if thumbnail_path else None
                run_summary = build_run_summary(
                    praxans=praxans,
                    buildings=buildings,
                    advisor=advisor,
                    current_time=time.time(),
                    game_start_time=game_start_time,
                    settlement_state=getattr(advisor, "current_settlement_state", {}),
                    faction_manager=faction_manager if "faction_manager" in local_names else None,
                    scenario_id=scenario_profile["id"] if "scenario_profile" in local_names else ACTIVE_SCENARIO_ID,
                    scenario_name=scenario_profile["name"] if "scenario_profile" in local_names else ACTIVE_SCENARIO_PROFILE.get("name"),
                    selected_model=advisor.last_model_used or selected_model,
                    seed=runtime_config.seed,
                    session_id=game_logger.session_id,
                    extinction=bool(game_over),
                    camera_bookmarks=camera_bookmarks,
                    scene_thumbnail_key=scene_thumbnail_key,
                )
                advisor.session_stats["current_run_summary"] = run_summary
                archive_payload = build_run_archive(
                    praxans=praxans,
                    buildings=buildings,
                    advisor=advisor,
                    current_time=time.time(),
                    game_start_time=game_start_time,
                    settlement_state=getattr(advisor, "current_settlement_state", {}),
                    faction_manager=faction_manager if "faction_manager" in local_names else None,
                    scenario_id=scenario_profile["id"] if "scenario_profile" in local_names else ACTIVE_SCENARIO_ID,
                    scenario_name=scenario_profile["name"] if "scenario_profile" in local_names else ACTIVE_SCENARIO_PROFILE.get("name"),
                    selected_model=advisor.last_model_used or selected_model,
                    seed=runtime_config.seed,
                    session_id=game_logger.session_id,
                    extinction=bool(game_over),
                    camera_bookmarks=camera_bookmarks,
                    scene_thumbnail_key=scene_thumbnail_key,
                )
                archive_file = write_run_archive(game_logger.log_dir, game_logger.session_id, archive_payload)
                snapshot = build_run_snapshot(
                    praxans,
                    buildings,
                    resources,
                    advisor,
                    season,
                    weather_system,
                    time.time(),
                    game_start_time,
                    selected_model=advisor.last_model_used or selected_model,
                    resource_respawn_time=RESOURCE_RESPAWN_TIME,
                    celebration_state=celebration_state if "celebration_state" in local_names else None,
                    camera=camera if "camera" in local_names else None,
                    world_map=world_map if "world_map" in local_names else None,
                    fog_of_war=fog_of_war if "fog_of_war" in local_names else None,
                    territory_manager=territory_manager if "territory_manager" in local_names else None,
                    faction_manager=faction_manager if "faction_manager" in local_names else None,
                    city_planner=city_planner if "city_planner" in local_names else None,
                    scenario_id=scenario_profile["id"] if "scenario_profile" in local_names else ACTIVE_SCENARIO_ID,
                    run_summary=run_summary,
                    camera_bookmarks=camera_bookmarks,
                    scene_thumbnail_key=scene_thumbnail_key,
                    focus_moments=archive_payload.get("focus_moments", []),
                    quest_manager=quest_manager if "quest_manager" in local_names else None,
                    diplomacy_manager=diplomacy_manager if "diplomacy_manager" in local_names else None,
                    tech_research_manager=tech_research_manager if "tech_research_manager" in local_names else None,
                    disaster_manager=disaster_manager if "disaster_manager" in local_names else None,
                    ritual_manager=ritual_manager if "ritual_manager" in local_names else None,
                    reputation_manager=reputation_manager if "reputation_manager" in local_names else None,
                    aspiration_manager=aspiration_manager if "aspiration_manager" in local_names else None,
                    ecology_manager=ecology_manager if "ecology_manager" in local_names else None,
                    global_climate=global_climate if "global_climate" in local_names else None,
                    warfare_manager=warfare_manager if "warfare_manager" in local_names else None,
                    cascade_manager=cascade_manager if "cascade_manager" in local_names else None,
                    tradition_manager=tradition_manager if "tradition_manager" in local_names else None,
                    migration_manager=migration_manager if "migration_manager" in local_names else None,
                    mentorship_manager=mentorship_manager if "mentorship_manager" in local_names else None,
                    personality_evolution_manager=personality_evolution_manager if "personality_evolution_manager" in local_names else None,
                    heirloom_manager=heirloom_manager if "heirloom_manager" in local_names else None,
                )
                snapshot_file = write_run_snapshot(game_logger.log_dir, game_logger.session_id, snapshot)
            game_state = {
                'population': len(praxans),
                'buildings': len(buildings),
                'duration': time.time() - game_start_time,
                'scenario_id': scenario_profile["id"] if "scenario_profile" in local_names else runtime_config.scenario,
                'scenario_name': scenario_profile["name"] if "scenario_profile" in local_names else ACTIVE_SCENARIO_PROFILE.get("name"),
                'seed': runtime_config.seed,
                'session_tag': runtime_config.session_tag,
                'headless': runtime_config.headless,
                'selected_model': advisor.last_model_used or selected_model,
                'snapshot_file': os.path.abspath(snapshot_file) if snapshot_file else None,
                'archive_file': os.path.abspath(archive_file) if archive_file else None,
                'thumbnail_file': os.path.abspath(thumbnail_path) if thumbnail_path else None,
                'log_file': os.path.abspath(game_logger.log_file),
                'telemetry_file': os.path.abspath(game_logger.telemetry_file),
                'telemetry_samples': game_logger.telemetry_count,
                'run_summary': run_summary,
                'observer_report': (archive_payload or {}).get("observer_report"),
                'focus_moments': (archive_payload or {}).get("focus_moments", []),
                'game_over': bool(game_over),
                'crash_count': game_logger.crash_count,
            }
            game_logger.generate_session_report(game_state)
            game_logger.flush_logs()
            
            report_file = os.path.join(game_logger.log_dir, f"report_{game_logger.session_id}.json")
            print(f"\n{'='*80}")
            print("SESSION ENDED")
            print(f"{'='*80}")
            print(f"Log directory: {os.path.abspath(game_logger.log_dir)}")
            print(f"Session Log: {os.path.abspath(game_logger.log_file)}")
            print(f"Session Report: {os.path.abspath(report_file)}")
            print(f"Session Telemetry: {os.path.abspath(game_logger.telemetry_file)}")
            if snapshot_file:
                print(f"Session Snapshot: {os.path.abspath(snapshot_file)}")
            if archive_file:
                print(f"Run Archive: {os.path.abspath(archive_file)}")
            if game_logger.crash_count > 0:
                print(f"\nWARNING: {game_logger.crash_count} crash(es) occurred during this session")
                print(f"Check logs/ directory for:")
                print(f"  - crash_*.log files (detailed crash reports)")
                print(f"  - batch_*.log files (complete console output if run from batch file)")
            print(f"\nNote: If run from batch file, check logs\\batch_*.log for complete output")
            print(f"{'='*80}")
            print("Game ended. Thanks for playing!")
            if post_run_action == "resume_latest":
                next_runtime_config = replace(
                    runtime_config,
                    snapshot_file=None,
                    load_latest_snapshot=True,
                    scenario=scenario_profile["id"] if "scenario_profile" in local_names else runtime_config.scenario,
                )
            elif post_run_action == "new_run":
                next_runtime_config = replace(
                    runtime_config,
                    snapshot_file=None,
                    load_latest_snapshot=False,
                    scenario=scenario_profile["id"] if "scenario_profile" in local_names else runtime_config.scenario,
                )
        except Exception as e:
            print(f"Error generating final report: {e}")
            traceback.print_exc()
            next_runtime_config = None

    if next_runtime_config is not None:
        return main(next_runtime_config)


if __name__ == "__main__":
    try:
        main(RUNTIME_CONFIG)
    except KeyboardInterrupt:
        print("\n\nGame interrupted by user (Ctrl+C)")
        print("Please check logs/ directory for session logs.")
    except Exception as e:
        # Last resort error handling if main crashes
        print(f"\n{'='*80}")
        print("CRITICAL ERROR: Game crashed before logging was initialized")
        print(f"{'='*80}")
        print(f"Error: {str(e)}")
        traceback.print_exc()
        print(f"\n{'='*80}")
        print("If logging was initialized, check logs/ directory for detailed crash reports.")
        print(f"Expected location: {os.path.abspath('logs')}")
        print(f"{'='*80}")




