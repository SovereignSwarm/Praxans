"""
Thronglets - A Black Mirror-style Lemmings simulation game
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
from dataclasses import replace
from datetime import datetime

from advisor_contract import advisory_payload_defaults, parse_advisory_payload
from game_scenarios import DEFAULT_SCENARIO_ID, get_scenario_profile
from graphics import GraphicsConfig, SceneRenderer, build_render_frame
from graphics.content import SNAP_ZOOM_LEVELS
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
THRONGLET_SPEED = 0.75  # Very slow movement for better map scale perception
RESOURCE_COLLISION_DIST = 12  # Adjusted for smaller sprites

# Time speed control
TIME_SPEED_OPTIONS = [1.0, 2.0, 5.0]  # 1x, 2x, 5x

# Visual scale constants
THRONGLET_RADIUS = 6  # Small creatures on big map
BUILDING_SIZE = 16  # Buildings visible but not oversized
RESOURCE_RADIUS_FOOD = 4  # Larger, more visible resources
RESOURCE_RADIUS_WOOD = 5  # Larger, more visible resources
# Map system constants
CHUNK_SIZE = 512  # Pixels per chunk (512x512)
TILE_SIZE = 32  # Size of each tile
INITIAL_CHUNKS_X = 16  # Macro frontier world width in chunks
INITIAL_CHUNKS_Y = 12  # Macro frontier world height in chunks
NOISE_SCALE = 0.1  # For Perlin noise generation

# Territory system constants
TERRITORY_CLAIM_RATE = 2.0  # Claim strength increase per second
TERRITORY_DECAY_RATE = 0.1  # Decay rate for unclaimed tiles
TERRITORY_CLAIM_RADIUS = 40  # Pixels around thronglets to claim
BUILDING_CLAIM_RADIUS = 60  # Pixels around buildings to claim

# Civilization Advisor Configuration
CIVILIZATION_ADVISOR_INTERVAL = 30.0  # Query LLM every 30 seconds

# Day/Night Cycle Configuration
DAY_LENGTH = 60.0  # seconds (full cycle = day + night)
NIGHT_START = DAY_LENGTH / 2  # night starts halfway through day

# Reproduction Configuration
REPRODUCTION_COOLDOWN = 45.0  # 45 seconds between reproductions (faster for growth)
REPRODUCTION_PROXIMITY = 30  # pixels distance for mating (adjusted for smaller sprites)
REPRODUCTION_NEEDS_THRESHOLD = 60  # both hunger and energy must be above this (easier to reproduce)
MAX_POPULATION = 25  # soft cap to maintain performance
INITIAL_POPULATION = 2  # start with 2 thronglets

# Resource Configuration
RESOURCE_RESPAWN_TIME = 30.0  # Food respawns every 30 seconds
RESOURCE_GATHER_TIME_FOOD = 3.0  # Time to gather food (seconds)
RESOURCE_GATHER_TIME_WOOD = 5.0  # Time to chop down tree (seconds)
RESOURCE_GATHER_TIME_STONE = 8.0  # Time to mine stone (seconds)
WOOD_MAX_ON_MAP = 20  # Maximum wood resources at once (increased for larger map)
# FOOD_MAX_ON_MAP removed - food uses respawn timer system instead

# Health & Lifespan
THRONGLET_MAX_AGE = 420.0  # 7 minutes (increased for better survival)
HEALTH_DECAY_BASE = 0.01
DISEASE_CHANCE_BASE = 0.001

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
RESOURCE_SHARING_RADIUS = 50  # Pixels - thronglets within this distance can share resources for building

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
STONE_MAX_ON_MAP = 10
RESOURCE_RADIUS_STONE = 5  # Larger, more visible resources

# Water & Hygiene
WATER_NEED_DECAY = 0.04

# Thronglet State Machine Constants
STATE_IDLE = 'idle'
STATE_SEEK_NEED = 'seek_need'
STATE_EXECUTE_DIRECTIVE = 'execute_directive'
STATE_SOCIALIZE = 'socialize'
STATE_REST = 'rest'
STATE_EXPLORE = 'explore'
STATE_CLAIM_TILE = 'claim_tile'

# Food Spoilage
FOOD_SPOIL_TIME = 120.0  # 2 minutes

# Seasons
SEASON_LENGTH = 90.0  # 90 seconds per season

# AI / simulation tuning
PREFERRED_OLLAMA_MODEL = (RUNTIME_CONFIG.model or "qwen3.5:9b").strip()
MODEL_PRIORITY = [
    PREFERRED_OLLAMA_MODEL,
    "qwen3.5:27b",
    "qwen3-coder:30b",
    "qwen3-coder-next:latest",
    "deepseek-r1:32b",
    "gpt-oss:20b",
]
ROLE_SKILL_MAP = {
    "gatherer": "gathering",
    "builder": "building",
    "explorer": "exploring",
}
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
BIOME_TYPES = ["forest", "plains", "mountains", "desert", "snow", "swamp", "taiga", "tundra"]
SETTLEMENT_AURA_RADIUS = 110
SETTLEMENT_CLUSTER_RADIUS = 140
FAVORITE_BIOME_SPEED_BONUS = 0.08
MORALE_SPEED_BONUS = 0.06
INSPIRATION_SKILL_BONUS = 0.15
OLLAMA_DETECTION_TIMEOUT_SECONDS = 2.5
OLLAMA_REQUEST_TIMEOUT_SECONDS = 20.0
OLLAMA_KEEP_ALIVE = "90s"
LLM_BACKOFF_SECONDS = 90.0
GOAL_ASSIGNMENT_INTERVAL = 60.0
POST_ADVISOR_GOAL_COOLDOWN = 20.0

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
# LLM Model Selection - Auto-detect fastest available model
# ===================================================================

# Cache for selected model (set once at startup)
_selected_llm_model = None
_llm_backoff_until = 0.0
_llm_request_lock = threading.Lock()


def get_ollama_client(timeout_seconds):
    if ollama is None:
        return None
    try:
        return ollama.Client(timeout=timeout_seconds)
    except Exception:
        return None

def get_fastest_available_model():
    """
    Detect and return the preferred Ollama model.
    This repo now explicitly prefers qwen3.5:9b, then falls back through a
    curated priority list before using a size-based heuristic.
    Returns the model name string, or None if no models are available.
    """
    global _selected_llm_model

    if not LLM_ENABLED:
        return None

    # Return cached model if already selected
    if _selected_llm_model:
        return _selected_llm_model

    try:
        client = get_ollama_client(OLLAMA_DETECTION_TIMEOUT_SECONDS)
        models_response = client.list() if client else ollama.list()
        if hasattr(models_response, "get"):
            available_models = models_response.get('models', [])
        else:
            available_models = getattr(models_response, 'models', [])

        if not available_models:
            print(f"[LLM] No models available. Install a model with: ollama pull {PREFERRED_OLLAMA_MODEL}")
            return None

        model_info = []
        for model in available_models:
            if isinstance(model, dict):
                model_name = model.get('name', '')
                size = model.get('size', 0)
                details = model.get('details', {})
                param_size_str = details.get('parameter_size', '') if isinstance(details, dict) else ''
            elif hasattr(model, 'model'):
                model_name = model.model
                size = getattr(model, 'size', 0)
                details = getattr(model, 'details', None)
                if details and hasattr(details, 'parameter_size'):
                    param_size_str = details.parameter_size
                else:
                    param_size_str = ''
            elif isinstance(model, str):
                model_name = model
                size = 0
                param_size_str = ''
            else:
                continue

            if not model_name or not model_name.strip():
                continue

            size_estimate = float('inf')
            if param_size_str:
                try:
                    match = re.search(r'([\d.]+)', param_size_str)
                    if match:
                        size_num = float(match.group(1))
                        if 'B' in param_size_str.upper():
                            size_estimate = size_num
                        elif 'M' in param_size_str.upper():
                            size_estimate = size_num / 1000
                except:
                    pass

            if size_estimate == float('inf') and ':' in model_name:
                try:
                    size_part = model_name.split(':')[1]
                    if 'b' in size_part.lower():
                        size_num = float(size_part.lower().replace('b', ''))
                        size_estimate = size_num
                except:
                    pass

            if size > 0 and size_estimate == float('inf'):
                size_estimate = size / (1024 * 1024 * 1024)

            model_info.append((model_name, size_estimate))

        available_names = [name for name, _ in model_info]
        for preferred in MODEL_PRIORITY:
            if preferred in available_names:
                _selected_llm_model = preferred
                print(f"[LLM] Selected preferred model: {preferred}")
                print(f"[LLM] Available models: {available_names}")
                return preferred

        qwen_family = [name for name in available_names if name.startswith("qwen3.5:")]
        if qwen_family:
            qwen_family.sort(
                key=lambda name: float(re.search(r"([\d.]+)b", name.lower()).group(1)) if re.search(r"([\d.]+)b", name.lower()) else 0.0,
                reverse=True,
            )
            _selected_llm_model = qwen_family[0]
            print(f"[LLM] Selected qwen fallback model: {_selected_llm_model}")
            print(f"[LLM] Available models: {available_names}")
            return _selected_llm_model

        model_info.sort(key=lambda item: item[1])
        _selected_llm_model = model_info[0][0]
        print(f"[LLM] Selected size-based fallback model: {_selected_llm_model}")
        print(f"[LLM] Available models: {available_names}")
        return _selected_llm_model

    except Exception as e:
        print(f"[LLM] Error detecting models: {e}")
        return None


def get_ollama_options(purpose="general"):
    """Return safe generation settings tuned for local Qwen usage via Ollama."""
    options = {
        "temperature": 0.2,
        "top_p": 0.85,
        "repeat_penalty": 1.08,
        "num_ctx": 2048,
        "num_predict": 120,
    }
    if purpose == "advisor":
        options.update(
            {
                "temperature": 0.12,
                "top_p": 0.8,
                "num_ctx": 4096,
                "num_predict": 240,
            }
        )
    elif purpose == "goals":
        options.update(
            {
                "temperature": 0.18,
                "num_ctx": 2048,
                "num_predict": 96,
            }
        )
    elif purpose == "thronglet":
        options.update(
            {
                "temperature": 0.15,
                "num_ctx": 1024,
                "num_predict": 24,
            }
        )
    if RUNTIME_CONFIG.seed is not None:
        options["seed"] = RUNTIME_CONFIG.seed
    return options


def sanitize_llm_response(response_text):
    """Strip Qwen thinking tags and markdown wrappers before parsing."""
    if not response_text:
        return ""

    cleaned = re.sub(r"<think>.*?</think>", "", response_text, flags=re.IGNORECASE | re.DOTALL)
    if re.search(r"</think>", cleaned, flags=re.IGNORECASE):
        cleaned = re.split(r"</think>", cleaned, maxsplit=1, flags=re.IGNORECASE)[-1]

    cleaned = cleaned.strip()
    cleaned = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip("`").strip()
    return cleaned


def generate_ollama_text(prompt, purpose="general"):
    """Generate text with the configured Ollama model and curated fallbacks."""
    global _llm_backoff_until

    if not LLM_ENABLED or ollama is None:
        raise RuntimeError("LLM disabled or Ollama unavailable")

    if time.time() < _llm_backoff_until:
        remaining = max(0.0, _llm_backoff_until - time.time())
        raise RuntimeError(f"LLM cooldown active for {remaining:.0f}s")

    primary_model = get_fastest_available_model()
    if not primary_model:
        raise RuntimeError("No LLM model available")

    options = get_ollama_options(purpose)
    attempted = []
    last_error = None

    if not _llm_request_lock.acquire(blocking=False):
        raise RuntimeError("LLM busy with another request")

    try:
        client = get_ollama_client(OLLAMA_REQUEST_TIMEOUT_SECONDS)
        for model_name in [primary_model] + [model for model in MODEL_PRIORITY if model != primary_model]:
            if not model_name or model_name in attempted:
                continue
            attempted.append(model_name)
            try:
                generate_fn = client.generate if client else ollama.generate
                response = generate_fn(
                    model=model_name,
                    prompt=prompt,
                    options=options,
                    stream=False,
                    think=False,
                    raw=False,
                    keep_alive=OLLAMA_KEEP_ALIVE,
                )
                if isinstance(response, dict):
                    response_text = response.get("response", "")
                else:
                    response_text = getattr(response, "response", "")
                response_text = sanitize_llm_response(response_text)
                if response_text:
                    _llm_backoff_until = 0.0
                    if model_name != primary_model:
                        print(f"[LLM] Fallback model succeeded for {purpose}: {model_name}")
                    return response_text, model_name
            except Exception as exc:
                last_error = exc
    finally:
        _llm_request_lock.release()

    _llm_backoff_until = time.time() + LLM_BACKOFF_SECONDS
    print(f"[LLM] Entering cooldown for {LLM_BACKOFF_SECONDS:.0f}s after {purpose} failure")
    raise last_error or RuntimeError("All LLM models failed")


def start_async_llm_job(prompt, purpose, metadata=None):
    """Run a guarded Ollama request off the main thread."""
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
            response_text, model_used = generate_ollama_text(prompt, purpose=purpose)
            job["response_text"] = response_text
            job["model_used"] = model_used
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


def apply_scenario_startup_conditions(scenario_profile, thronglets, advisor, season, weather_system, current_time):
    favorite_biomes = [biome for biome in scenario_profile.get("favorite_biomes", []) if biome in BIOME_TYPES] or BIOME_TYPES
    morale_bonus = float(scenario_profile.get("morale_bonus", 0.0))
    inspiration_bonus = float(scenario_profile.get("inspiration_bonus", 0.0))
    health_bonus = float(scenario_profile.get("health_bonus", 0.0))
    disease_health_penalty = float(scenario_profile.get("disease_health_penalty", 0.0))

    for thronglet in thronglets:
        thronglet.favorite_biome = random.choice(favorite_biomes)
        thronglet.morale = clamp(thronglet.morale + morale_bonus, 0.0, 100.0)
        thronglet.inspiration = clamp(thronglet.inspiration + inspiration_bonus, 0.0, 100.0)
        thronglet.health = clamp(thronglet.health + health_bonus, 10.0, 100.0)

    diseased_count = min(len(thronglets), max(0, int(scenario_profile.get("starting_diseased", 0))))
    if diseased_count > 0:
        for thronglet in random.sample(thronglets, diseased_count):
            thronglet.diseased = True
            thronglet.disease_start_time = current_time - random.uniform(5.0, 15.0)
            thronglet.health = clamp(thronglet.health - disease_health_penalty, 10.0, 100.0)
            thronglet.happiness = clamp(thronglet.happiness - 12.0, 0.0, 100.0)

    advisor.research_points += max(0, int(scenario_profile.get("starting_research", 0)))
    advisor.last_pop_count = len(thronglets)
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


def summarize_population_evolution(thronglets):
    if not thronglets:
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

    for thronglet in thronglets:
        lineage_id = getattr(thronglet, "lineage_id", thronglet.id)
        lineage_counts[lineage_id] = lineage_counts.get(lineage_id, 0) + 1
        biome_name = getattr(thronglet, "favorite_biome", "plains")
        biome_counts[biome_name] = biome_counts.get(biome_name, 0) + 1
        generation_values.append(getattr(thronglet, "generation", 0))
        total_mutations += int(getattr(thronglet, "mutation_count", 0))
        for trait_name in GENETIC_TRAIT_SPECS:
            avg_traits[trait_name] += getattr(thronglet, "genetics", {}).get(trait_name, 1.0)

    population = len(thronglets)
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
    thronglets,
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
        thronglets=thronglets,
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


def record_population_evolution_sample(advisor, thronglets, current_time, game_start_time, force=False):
    if advisor is None:
        return summarize_population_evolution(thronglets)

    last_sample_time = getattr(advisor, "last_evolution_sample_time", 0.0)
    if not force and current_time - last_sample_time < 20.0:
        return advisor.session_stats.get("current_evolution_summary", summarize_population_evolution(thronglets))

    summary = summarize_population_evolution(thronglets)
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


def compute_settlement_snapshot(thronglets, buildings, world_map=None, season=None, weather_system=None):
    counts = {btype: 0 for btype in ["house", "storage", "farm", "workshop", "shrine", "well"]}
    stored_food = 0
    stored_wood = 0
    stored_stone = 0
    total_inventory_food = sum(t.inventory.get("food", 0) for t in thronglets)

    for building in buildings:
        counts[building.building_type] = counts.get(building.building_type, 0) + 1
        stored_food += building.stored_resources.get("food", 0)
        stored_wood += building.stored_resources.get("wood", 0)
        stored_stone += building.stored_resources.get("stone", 0)

    population = max(1, len(thronglets))
    avg_health = sum(t.health for t in thronglets) / population if thronglets else 100
    avg_happiness = sum(t.happiness for t in thronglets) / population if thronglets else 80
    avg_morale = sum(getattr(t, "morale", 65) for t in thronglets) / population if thronglets else 65

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
    if world_map and thronglets:
        biome_counts = {}
        for thronglet in thronglets:
            biome = world_map.get_biome_at(thronglet.x, thronglet.y)
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

        if thronglets:
            nearby_population = sum(
                1 for thronglet in thronglets if distance_between(building.x, building.y, thronglet.x, thronglet.y) <= SETTLEMENT_AURA_RADIUS
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


def draw_atmospheric_overlay(surface, game_time, season, weather_system, settlement_state):
    """Apply a lightweight cinematic atmosphere pass without obscuring the UI."""
    day_cycle = game_time % DAY_LENGTH
    is_night = day_cycle >= NIGHT_START
    season_tints = {
        "spring": (110, 170, 120),
        "summer": (220, 190, 120),
        "autumn": (210, 145, 95),
        "winter": (130, 165, 220),
    }
    weather_tints = {
        "clear": None,
        "rain": (90, 140, 175),
        "storm": (55, 80, 120),
        "drought": (205, 145, 90),
        "aurora": (120, 220, 190),
    }

    tint = season_tints.get(season.current, (120, 150, 120))
    if weather_tints.get(weather_system.current_weather):
        tint = blend_color(tint, weather_tints[weather_system.current_weather], 0.55)

    overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    overlay_alpha = 18 if not is_night else 62
    if weather_system.current_weather == "storm":
        overlay_alpha += 10
    elif weather_system.current_weather == "drought":
        overlay_alpha += 6

    pygame.draw.rect(overlay, (*tint, overlay_alpha), overlay.get_rect())
    surface.blit(overlay, (0, 0))

    orb_surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    orb_color = (255, 244, 190) if not is_night else (180, 210, 255)
    orb_x = int(WINDOW_WIDTH * 0.82)
    orb_y = 90
    orb_radius = 28 if not is_night else 22
    pygame.draw.circle(orb_surface, (*orb_color, 50), (orb_x, orb_y), orb_radius * 2)
    pygame.draw.circle(orb_surface, (*orb_color, 170), (orb_x, orb_y), orb_radius)
    surface.blit(orb_surface, (0, 0))

    prosperity = settlement_state.get("prosperity_score", 0.0) if settlement_state else 0.0
    if prosperity > 0.9:
        prosperity_overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        accent_alpha = int(18 + (prosperity - 0.9) * 120)
        pygame.draw.rect(prosperity_overlay, (245, 210, 110, accent_alpha), prosperity_overlay.get_rect(), 6)
        surface.blit(prosperity_overlay, (0, 0))

    weather_name = weather_system.current_weather
    if weather_name in ("rain", "storm"):
        rain_surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        drop_count = 16 if weather_name == "rain" else 26
        for index in range(drop_count):
            x = int((index * 91 + game_time * (170 if weather_name == "storm" else 120)) % (WINDOW_WIDTH + 40)) - 20
            y = int((index * 63 + game_time * 260) % (WINDOW_HEIGHT + 40)) - 20
            length = 10 if weather_name == "rain" else 16
            pygame.draw.line(
                rain_surface,
                (190, 220, 255, 90 if weather_name == "rain" else 120),
                (x, y),
                (x - 5, y + length),
                2,
            )
        surface.blit(rain_surface, (0, 0))
    elif weather_name == "drought":
        shimmer_surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        for index in range(8):
            y = int((index * 120 + game_time * 14) % WINDOW_HEIGHT)
            pygame.draw.line(shimmer_surface, (255, 214, 155, 34), (0, y), (WINDOW_WIDTH, y + 14), 2)
        surface.blit(shimmer_surface, (0, 0))
    elif weather_name == "aurora":
        aurora_surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        for index in range(5):
            points = []
            for step in range(0, WINDOW_WIDTH + 1, 80):
                arc_y = 40 + index * 24 + int(math.sin(game_time * 1.2 + index + step * 0.01) * 18)
                points.append((step, arc_y))
            pygame.draw.lines(aurora_surface, (90, 255, 200, 55), False, points, 6)
        surface.blit(aurora_surface, (0, 0))

    if settlement_state and settlement_state.get("festival_active"):
        festival_surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        ribbon_colors = [GOLD, CYAN, RED, GRASS_LIGHT]
        for index in range(10):
            points = []
            for step in range(0, WINDOW_WIDTH + 80, 120):
                ribbon_y = 120 + index * 18 + int(math.sin(game_time * 2.4 + index + step * 0.015) * 12)
                points.append((step - 40, ribbon_y))
            ribbon_color = ribbon_colors[index % len(ribbon_colors)]
            pygame.draw.lines(festival_surface, (*ribbon_color, 52), False, points, 3)
        for index in range(20):
            confetti_color = ribbon_colors[index % len(ribbon_colors)]
            confetti_x = int((index * 87 + game_time * 110) % WINDOW_WIDTH)
            confetti_y = int((index * 53 + game_time * 170) % (WINDOW_HEIGHT - 140)) + 60
            pygame.draw.rect(festival_surface, (*confetti_color, 125), (confetti_x, confetti_y, 4, 7))
        surface.blit(festival_surface, (0, 0))

    if season.current == "winter":
        snow_surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        for index in range(18):
            x = int((index * 73 + game_time * 20) % WINDOW_WIDTH)
            y = int((index * 41 + game_time * 38) % WINDOW_HEIGHT)
            pygame.draw.circle(snow_surface, (255, 255, 255, 110), (x, y), 2)
        surface.blit(snow_surface, (0, 0))
    elif season.current == "autumn":
        leaf_surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        for index in range(12):
            x = int((index * 109 + game_time * 26) % WINDOW_WIDTH)
            y = int((index * 57 + game_time * 20) % WINDOW_HEIGHT)
            pygame.draw.ellipse(leaf_surface, (220, 150, 70, 95), (x, y, 7, 4))
        surface.blit(leaf_surface, (0, 0))


def update_settlement_celebration(
    celebration_state,
    settlement_state,
    thronglets,
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
        if len(thronglets) >= 4 and has_cultural_anchor and readiness >= 0.78:
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
            elif thronglets:
                center = (
                    sum(thronglet.x for thronglet in thronglets) / len(thronglets),
                    sum(thronglet.y for thronglet in thronglets) / len(thronglets),
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

        for thronglet in thronglets:
            bonus_scale = 1.0
            if center and distance_between(thronglet.x, thronglet.y, center[0], center[1]) <= 220:
                bonus_scale = 1.35
            thronglet.morale = clamp(thronglet.morale + 0.9 * delta_time * bonus_scale, 0.0, 100.0)
            thronglet.happiness = clamp(thronglet.happiness + 0.42 * delta_time * bonus_scale, 0.0, 100.0)
            thronglet.inspiration = clamp(thronglet.inspiration + 0.65 * delta_time * bonus_scale, 0.0, 100.0)

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
    
    def detect_hover(self, mouse_world_x, mouse_world_y, camera, thronglets, buildings, resources, encounters, hazards, npcs, world_map):
        """Detect which entity the mouse is hovering over"""
        self.hovered_entity = None
        self.hovered_type = None
        
        # Check entities in priority order
        # Check thronglets
        for thronglet in thronglets:
            distance = math.sqrt((mouse_world_x - thronglet.x)**2 + (mouse_world_y - thronglet.y)**2)
            threshold = THRONGLET_RADIUS * camera.zoom
            if distance < threshold:
                self.hovered_entity = thronglet
                self.hovered_type = 'thronglet'
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
        
        if self.hovered_type == 'thronglet':
            thronglet = self.hovered_entity
            lines.append(f"Thronglet #{thronglet.id}")
            line_colors.append(WHITE)
            
            if thronglet.role:
                lines.append(f"Role: {thronglet.role.title()}")
                line_colors.append((200, 200, 255))
            
            # Health with color coding
            health_val = int(thronglet.health)
            health_color = (100, 255, 100) if health_val > 70 else (255, 200, 100) if health_val > 40 else (255, 100, 100)
            lines.append(f"Health: {health_val}/100")
            line_colors.append(health_color)
            
            # Needs with color coding
            hunger_val = int(thronglet.needs['hunger'])
            hunger_color = (100, 255, 100) if hunger_val > 50 else (255, 100, 100)
            lines.append(f"Hunger: {hunger_val}/100")
            line_colors.append(hunger_color)
            
            energy_val = int(thronglet.needs['energy'])
            energy_color = (100, 255, 100) if energy_val > 50 else (255, 100, 100)
            lines.append(f"Energy: {energy_val}/100")
            line_colors.append(energy_color)
            
            # Happiness
            if hasattr(thronglet, 'happiness'):
                happiness_val = int(thronglet.happiness)
                happiness_color = (100, 255, 100) if happiness_val > 70 else (255, 200, 100) if happiness_val > 40 else (255, 100, 100)
                lines.append(f"Happiness: {happiness_val}/100")
                line_colors.append(happiness_color)

            lines.append(f"Generation: {getattr(thronglet, 'generation', 0)}  Lineage: L{getattr(thronglet, 'lineage_id', thronglet.id)}")
            line_colors.append((255, 220, 150))
            if getattr(thronglet, "parent_ids", None):
                parent_text = ",".join(str(parent_id) for parent_id in thronglet.parent_ids[:2])
                lines.append(f"Parents: {parent_text}")
                line_colors.append((180, 180, 205))
            
            # Faction membership
            if hasattr(thronglet, 'faction_id') and thronglet.faction_id is not None:
                lines.append(f"Faction: {thronglet.faction_id}")
                line_colors.append((200, 100, 255))
                if faction_manager and hasattr(faction_manager, 'factions'):
                    faction = faction_manager.get_faction(thronglet.faction_id)
                    if faction:
                        lines.append(
                            f"Doctrine: {faction.primary_doctrine.title()}  Cohesion: {int(faction.cohesion)}  Schism: {int(faction.schism_pressure)}"
                        )
                        line_colors.append((220, 190, 255))
            elif faction_manager and hasattr(faction_manager, 'factions'):
                # Check if thronglet is in any faction
                for fid, faction in faction_manager.factions.items():
                    if thronglet.id in faction.member_ids:
                        lines.append(f"Faction: {fid}")
                        line_colors.append((200, 100, 255))
                        lines.append(
                            f"Doctrine: {faction.primary_doctrine.title()}  Cohesion: {int(faction.cohesion)}  Schism: {int(faction.schism_pressure)}"
                        )
                        line_colors.append((220, 190, 255))
                        break
            
            # Skills and bonuses
            skill_key = get_role_skill_key(thronglet.role)
            if skill_key and skill_key in thronglet.skills:
                skill_level = thronglet.skills[skill_key]['level']
                lines.append(f"Skill Level: {skill_level}")
                line_colors.append((255, 215, 0))
                if thronglet.role == 'gatherer':
                    bonus = (skill_level - 1) * 10
                    lines.append(f"Gather Bonus: +{bonus}%")
                    line_colors.append((100, 255, 100))
                elif thronglet.role == 'builder':
                    bonus = (skill_level - 1) * 10
                    lines.append(f"Build Efficiency: +{bonus}%")
                    line_colors.append((100, 255, 100))
                elif thronglet.role == 'explorer':
                    bonus = (skill_level - 1) * 15
                    lines.append(f"Visibility: +{bonus}%")
                    line_colors.append((100, 255, 100))
            
            # Q-learning stats
            if hasattr(thronglet, 'q_table'):
                q_entries = len(thronglet.q_table)
                if q_entries > 0:
                    lines.append(f"Learned Actions: {q_entries}")
                    line_colors.append((150, 200, 255))
            
            # State
            if hasattr(thronglet, 'current_state'):
                state_name = thronglet.current_state.replace('STATE_', '').replace('_', ' ').title()
                lines.append(f"State: {state_name}")
                line_colors.append((200, 200, 200))
            
            # Current action
            if hasattr(thronglet, 'current_action') and thronglet.current_action:
                lines.append(f"Task: {thronglet.current_action}")
                line_colors.append((255, 255, 200))
            trait_drift_name = max(
                GENETIC_TRAIT_SPECS,
                key=lambda trait_name: abs(getattr(thronglet, "genetics", {}).get(trait_name, 1.0) - 1.0),
            )
            trait_label = GENETIC_TRAIT_SPECS[trait_drift_name]["label"]
            trait_delta = format_genetic_trait_delta(getattr(thronglet, "genetics", {}).get(trait_drift_name, 1.0))
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
                lines.append(f"Built by: Thronglet #{building.built_by}" if hasattr(building, 'built_by') and building.built_by is not None else "Built by: Unknown")
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
        if entity_type == 'thronglet':
            # Yellow glow
            glow_surface = pygame.Surface((THRONGLET_RADIUS * 2 + 8, THRONGLET_RADIUS * 2 + 8), pygame.SRCALPHA)
            pygame.draw.circle(glow_surface, (*YELLOW, 150), (THRONGLET_RADIUS + 4, THRONGLET_RADIUS + 4), THRONGLET_RADIUS + 4)
            surface.blit(glow_surface, (int(entity.x - THRONGLET_RADIUS - 4), int(entity.y - THRONGLET_RADIUS - 4)))
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


class InfoPanel:
    """Displays detailed information about selected entity"""
    def __init__(self):
        self.panel_x = WINDOW_WIDTH - 320
        self.panel_y = 180  # Moved up to avoid minimap
        self.panel_w = 300
        self.panel_h = 480
    
    def draw(self, surface, selected_entity, selected_type, advisor=None, current_time=0):
        """Draw info panel for selected entity"""
        if not selected_entity or not selected_type:
            return
        
        # Create panel surface
        panel = pygame.Surface((self.panel_w, self.panel_h))
        panel.set_alpha(230)
        panel.fill((30, 30, 50))
        surface.blit(panel, (self.panel_x, self.panel_y))
        
        # Draw border
        pygame.draw.rect(surface, (100, 150, 200), (self.panel_x, self.panel_y, self.panel_w, self.panel_h), 2)
        
        # Title
        title_text = font_small.render("SELECTED ENTITY", True, (150, 200, 255))
        surface.blit(title_text, (self.panel_x + 10, self.panel_y + 10))
        
        y_offset = 40
        
        if selected_type == 'thronglet':
            thronglet = selected_entity
            role_name = thronglet.role.title() if thronglet.role else "Unassigned"
            # Detailed stats
            stats = [
                f"ID: {thronglet.id}",
                f"Role: {role_name}",
                f"Health: {int(thronglet.health)}/100",
                f"Age: {int(current_time - thronglet.birth_time)}s",
                f"Generation: {getattr(thronglet, 'generation', 0)}",
                f"Lineage: L{getattr(thronglet, 'lineage_id', thronglet.id)}",
                "",
                "Needs:",
                f"  Hunger: {int(thronglet.needs['hunger'])}/100",
                f"  Energy: {int(thronglet.needs['energy'])}/100",
                f"  Thirst: {int(thronglet.needs['thirst'])}/100",
                "",
                "Status:",
                f"  Happiness: {int(thronglet.happiness)}/100",
                f"  Morale: {int(getattr(thronglet, 'morale', 0))}/100",
                f"  Inspiration: {int(getattr(thronglet, 'inspiration', 0))}/100",
                f"  Favorite Biome: {getattr(thronglet, 'favorite_biome', 'plains').title()}",
                f"  Disease: {'Yes' if thronglet.diseased else 'No'}",
                f"  Can Reproduce: {'Yes' if thronglet.can_reproduce() else 'No'}",
                f"  Mutations: {int(getattr(thronglet, 'mutation_count', 0))}",
            ]

            if getattr(thronglet, "parent_ids", None):
                stats.append(f"Parents: {', '.join(str(parent_id) for parent_id in thronglet.parent_ids[:2])}")

            stats.extend(
                [
                    "",
                    "Genetics:",
                ]
            )
            stats.extend(build_trait_display_lines(thronglet.genetics))
            
            # Add skills if they exist
            skill_key = get_role_skill_key(thronglet.role)
            if skill_key and skill_key in thronglet.skills:
                skill_level = thronglet.skills[skill_key]['level']
                stats.append(f"Skill Level: {skill_level}")
                
                # Show specific bonuses
                if thronglet.role == 'gatherer':
                    bonus = int((thronglet.get_gathering_bonus() - 1.0) * 100)
                    stats.append(f"  Gather Speed: +{bonus}%")
                elif thronglet.role == 'builder':
                    bonus = int((thronglet.get_building_bonus() - 1.0) * 100)
                    stats.append(f"  Build Discount: {bonus}%")
                elif thronglet.role == 'explorer':
                    bonus = int((thronglet.get_exploration_bonus() - 1.0) * 100)
                    stats.append(f"  Exploration: +{bonus}%")
            
            # Add bonds
            if thronglet.bonds:
                stats.append(f"Bonds: {len(thronglet.bonds)}")
            
            # Add current task
            if thronglet.current_action:
                stats.append(f"Task: {thronglet.current_action}")
            
            # Add inventory
            if sum(thronglet.inventory.values()) > 0:
                inv_str = ", ".join([f"{k}:{v}" for k, v in thronglet.inventory.items() if v > 0])
                stats.append(f"Inventory: {inv_str}")
            
        elif selected_type == 'building':
            building = selected_entity
            stats = [
                f"Type: {building.building_type.title()}",
                f"Level: {getattr(building, 'level', 1)}",
                f"Built by: Thronglet #{building.built_by}" if building.built_by is not None else "Built by: Unknown",
            ]
            
            if building.building_type == 'house':
                stats.extend([
                    f"Occupants: {len(building.occupants)}/2",
                    f"Capacity: {int(2 * (advisor.game_modifiers.get_modifier('house_capacity') if advisor and advisor.game_modifiers else 1.0))}"
                ])
            elif building.stored_resources:
                stored = building.stored_resources
                if sum(stored.values()) > 0:
                    stored_lines = [f"  {k.title()}: {int(v)}" for k, v in stored.items() if v > 0]
                    stats.append("Stored Resources:")
                    stats.extend(stored_lines)
                else:
                    stats.append("Stored: Empty")
        
        elif selected_type == 'resource':
            resource = selected_entity
            stats = [
                f"Type: {resource.resource_type.title()}",
                f"Status: {'Respawning' if resource.collected else 'Available'}",
            ]
            if resource.collected:
                stats.append(f"Respawn in: {int(RESOURCE_RESPAWN_TIME - (current_time - resource.collect_time))}s")
        
        elif selected_type == 'encounter':
            encounter = selected_entity
            encounter_names = {
                'ruins': 'Ancient Ruins',
                'mineral_vein': 'Mineral Vein',
                'oasis': 'Oasis',
                'sacred_grove': 'Sacred Grove'
            }
            stats = [
                f"Type: {encounter_names.get(encounter.encounter_type, 'Unknown')}",
                f"Discovered: {'Yes' if encounter.discovered else 'No'}",
                f"Explored: {'Yes' if encounter.explored else 'No'}",
            ]
        
        elif selected_type == 'hazard':
            hazard = selected_entity
            hazard_names = {
                'quicksand': 'Quicksand',
                'avalanche_zone': 'Avalanche Zone',
                'flood_zone': 'Flood Zone',
                'predator_lair': 'Predator Lair'
            }
            stats = [
                f"Type: {hazard_names.get(hazard.hazard_type, 'Hazard')}",
                f"Active: {'Yes' if hazard.active else 'No'}",
                f"Radius: {hazard.radius}",
                f"Damage Rate: {hazard.damage_rate}/s",
            ]
        
        elif selected_type == 'npc':
            npc = selected_entity
            npc_names = {
                'trader': 'Trader',
                'rival_tribe': 'Rival Tribe',
                'wildlife_herd': 'Wildlife Herd'
            }
            stats = [
                f"Type: {npc_names.get(npc.npc_type, 'NPC')}",
                f"Hostile: {'Yes' if npc.hostile else 'No'}",
            ]
            if npc.inventory and sum(npc.inventory.values()) > 0:
                stats.append("Inventory:")
                for k, v in npc.inventory.items():
                    if v > 0:
                        stats.append(f"  {k.title()}: {v}")
        
        # Draw stats
        for line in stats:
            if line.strip() == "":
                y_offset += 5
                continue
            text = font_small.render(line, True, WHITE)
            # Truncate if too long
            if text.get_width() > self.panel_w - 20:
                # Truncate text
                truncated = line[:35] + "..."
                text = font_small.render(truncated, True, WHITE)
            surface.blit(text, (self.panel_x + 10, self.panel_y + y_offset))
            y_offset += 20


class EvolutionStatsPanel:
    """Observer-facing panel for lineage and trait drift."""

    def __init__(self):
        self.panel_w = 560
        self.panel_h = 440

    def draw(self, surface, thronglets, advisor, current_time):
        panel_x = WINDOW_WIDTH // 2 - self.panel_w // 2
        panel_y = WINDOW_HEIGHT // 2 - self.panel_h // 2
        panel = pygame.Surface((self.panel_w, self.panel_h))
        panel.set_alpha(238)
        panel.fill((24, 24, 42))
        surface.blit(panel, (panel_x, panel_y))
        pygame.draw.rect(surface, (120, 160, 215), (panel_x, panel_y, self.panel_w, self.panel_h), 3)

        title = font.render("EVOLUTION OBSERVER", True, (220, 230, 255))
        surface.blit(title, (panel_x + 20, panel_y + 16))

        summary = advisor.session_stats.get("current_evolution_summary") or summarize_population_evolution(thronglets)
        line_y = panel_y + 62
        overview_lines = [
            f"Population: {summary['population']}  |  Avg generation: {summary['avg_generation']:.1f}  |  Max generation: {summary['max_generation']}",
            f"Founder lines: {summary['founder_lines']}  |  Dominant line: L{summary['dominant_lineage']} ({summary['dominant_lineage_size']})",
            f"Dominant biome affinity: {summary['dominant_biome'].title()}  |  Total mutations: {summary['total_mutations']}",
            f"Births: {advisor.session_stats.get('births_total', 0)}  |  Deaths: {advisor.total_deaths}",
        ]
        for line in overview_lines:
            surface.blit(font_small.render(line[:70], True, WHITE), (panel_x + 20, line_y))
            line_y += 24

        trait_title = font_small.render("Population Trait Drift", True, (160, 220, 255))
        surface.blit(trait_title, (panel_x + 20, line_y + 8))
        line_y += 36
        for trait_name, trait_spec in GENETIC_TRAIT_SPECS.items():
            avg_value = summary["avg_traits"].get(trait_name, 1.0)
            bar_x = panel_x + 20
            bar_y = line_y
            bar_w = 220
            bar_h = 16
            pygame.draw.rect(surface, (55, 60, 82), (bar_x, bar_y, bar_w, bar_h))
            normalized = clamp((avg_value - trait_spec["min"]) / (trait_spec["max"] - trait_spec["min"]), 0.0, 1.0)
            fill_w = max(2, int(bar_w * normalized))
            bar_color = (120, 200, 255) if trait_name != summary["trait_drift"] else (255, 215, 120)
            pygame.draw.rect(surface, bar_color, (bar_x, bar_y, fill_w, bar_h))
            label = f"{trait_spec['label']}: {format_genetic_trait_delta(avg_value)}"
            surface.blit(font_small.render(label, True, WHITE), (bar_x + bar_w + 14, bar_y - 2))
            line_y += 26

        history_title = font_small.render("Recent Evolution Events", True, (255, 220, 170))
        surface.blit(history_title, (panel_x + 20, line_y + 6))
        line_y += 32
        lineage_events = advisor.session_stats.get("lineage_events", [])
        for event in lineage_events[-6:]:
            event_age = max(0.0, current_time - event.get("time", current_time))
            event_text = f"{event.get('label', 'event')} ({event_age:.0f}s ago)"
            surface.blit(font_small.render(event_text[:72], True, (220, 220, 220)), (panel_x + 20, line_y))
            line_y += 22

        trend_x = panel_x + 310
        trend_y = panel_y + 220
        trend_title = font_small.render("Generation Trend", True, (200, 255, 200))
        surface.blit(trend_title, (trend_x, trend_y))
        history = advisor.session_stats.get("evolution_history", [])
        trend_y += 24
        for sample in history[-6:]:
            trend_text = (
                f"t+{int(sample.get('elapsed_seconds', 0))}s  gen {sample.get('avg_generation', 0):.1f}"
                f"  pop {sample.get('population', 0)}  lines {sample.get('founder_lines', 0)}"
            )
            surface.blit(font_small.render(trend_text[:34], True, (210, 210, 235)), (trend_x, trend_y))
            trend_y += 20

        close_hint = font_small.render("[S] to close", True, (180, 200, 230))
        surface.blit(close_hint, (panel_x + self.panel_w - 100, panel_y + self.panel_h - 28))


class ObserverAnalyticsPanel:
    """Observer-facing colony analytics for lineage, mortality, and faction history."""

    def draw(self, surface, thronglets, advisor, current_time, faction_manager=None):
        panel_w = min(860, WINDOW_WIDTH - 40)
        panel_h = min(560, WINDOW_HEIGHT - 70)
        panel_x = max(20, WINDOW_WIDTH // 2 - panel_w // 2)
        panel_y = max(20, WINDOW_HEIGHT // 2 - panel_h // 2)

        panel = pygame.Surface((panel_w, panel_h))
        panel.set_alpha(240)
        panel.fill((20, 24, 38))
        surface.blit(panel, (panel_x, panel_y))
        pygame.draw.rect(surface, (120, 160, 215), (panel_x, panel_y, panel_w, panel_h), 3)

        report = build_observer_report(thronglets, advisor, faction_manager)
        scenario_name = advisor.session_stats.get("scenario_name", ACTIVE_SCENARIO_PROFILE.get("name", "Standard Basin"))
        title = font.render("OBSERVER ANALYTICS", True, (220, 230, 255))
        subtitle = font_small.render(f"{scenario_name}  |  Timeline, mortality, and faction drift", True, (170, 210, 255))
        surface.blit(title, (panel_x + 20, panel_y + 14))
        surface.blit(subtitle, (panel_x + 20, panel_y + 42))

        summary_y = panel_y + 72
        summary_lines = [
            f"Population: {report['population']}  |  Peak: {report['max_population']}  |  Births: {report['births_total']}  |  Deaths: {report['deaths_total']}",
            f"Avg survival: {report['avg_survival_time']:.1f}s  |  Factions: {len(report['active_factions'])} active / {report['peak_factions']} peak",
            f"Faction churn: +{report['factions_formed']} / -{report['factions_dissolved']} / split {report['faction_schisms']} / succession {report['faction_successions']}",
            f"Migration events: {report['migration_events']}  |  Group tasks: {report['active_group_tasks']}",
        ]
        for summary_line in summary_lines:
            surface.blit(font_small.render(summary_line[:92], True, WHITE), (panel_x + 20, summary_y))
            summary_y += 22

        box_y = summary_y + 8
        box_gap = 16
        box_w = (panel_w - 40 - box_gap * 2) // 3
        box_h = 168

        def draw_box(title_text, box_x, box_y, box_w, box_h):
            pygame.draw.rect(surface, (36, 42, 60), (box_x, box_y, box_w, box_h))
            pygame.draw.rect(surface, (90, 120, 170), (box_x, box_y, box_w, box_h), 2)
            title_surface = font_small.render(title_text, True, (210, 225, 255))
            surface.blit(title_surface, (box_x + 12, box_y + 10))
            return box_y + 36

        lineage_x = panel_x + 20
        mortality_x = lineage_x + box_w + box_gap
        faction_x = mortality_x + box_w + box_gap

        line_y = draw_box("Dominant Lineages", lineage_x, box_y, box_w, box_h)
        top_lineages = report["top_lineages"]
        if top_lineages:
            max_lineage_count = max(lineage["count"] for lineage in top_lineages)
            for lineage in top_lineages:
                label = f"L{lineage['lineage_id']}  {lineage['count']}  ({int(lineage['share'] * 100)}%)"
                surface.blit(font_small.render(label, True, (230, 215, 170)), (lineage_x + 12, line_y))
                bar_y = line_y + 16
                pygame.draw.rect(surface, (55, 62, 86), (lineage_x + 12, bar_y, box_w - 24, 10))
                fill_w = int((box_w - 24) * (lineage["count"] / max(1, max_lineage_count)))
                pygame.draw.rect(surface, (255, 205, 120), (lineage_x + 12, bar_y, max(4, fill_w), 10))
                line_y += 28
        else:
            surface.blit(font_small.render("No lineage divergence yet.", True, (180, 190, 215)), (lineage_x + 12, line_y))

        mortality_y = draw_box("Mortality Breakdown", mortality_x, box_y, box_w, box_h)
        if report["mortality"]:
            for cause in report["mortality"]:
                label = f"{cause['label']}: {cause['count']}"
                surface.blit(font_small.render(label[:28], True, (255, 180, 160)), (mortality_x + 12, mortality_y))
                bar_y = mortality_y + 16
                pygame.draw.rect(surface, (55, 62, 86), (mortality_x + 12, bar_y, box_w - 24, 10))
                fill_w = int((box_w - 24) * cause["share"])
                pygame.draw.rect(surface, (255, 110, 110), (mortality_x + 12, bar_y, max(4, fill_w), 10))
                mortality_y += 28
        else:
            surface.blit(font_small.render("No deaths recorded in this run.", True, (180, 190, 215)), (mortality_x + 12, mortality_y))

        faction_y = draw_box("Faction Snapshot", faction_x, box_y, box_w, box_h)
        if report["active_factions"]:
            for faction in report["active_factions"][:4]:
                faction_line = (
                    f"F{faction['id']}  size {faction['members']}  "
                    f"{faction['doctrine'][:5].upper()}  leader #{faction['leader_id']}"
                )
                surface.blit(font_small.render(faction_line[:34], True, (195, 170, 255)), (faction_x + 12, faction_y))
                faction_y += 22
                gen_line = (
                    f"Gen {faction['avg_generation']:.1f}  coh {int(faction['cohesion'])}  "
                    f"sch {int(faction['schism_pressure'])}  mig {int(faction['migration_pressure'])}"
                )
                surface.blit(font_small.render(gen_line, True, (180, 200, 230)), (faction_x + 24, faction_y))
                faction_y += 20
        else:
            surface.blit(font_small.render("No cohesive factions active.", True, (180, 190, 215)), (faction_x + 12, faction_y))

        lower_box_y = box_y + box_h + 18
        lower_right_w = min(240, max(200, panel_w // 4))
        lower_left_w = panel_w - 40 - box_gap - lower_right_w
        lower_h = panel_h - (lower_box_y - panel_y) - 24

        timeline_y = draw_box("Observer Timeline", panel_x + 20, lower_box_y, lower_left_w, lower_h)
        timeline = report["timeline"]
        if timeline:
            for event in timeline[-7:]:
                event_age = max(0.0, current_time - float(event.get("time", current_time) or current_time))
                category = str(event.get("category", "sim"))[:10].upper()
                summary = str(event.get("summary", "Event"))
                line = f"[{category}] {summary} ({event_age:.0f}s ago)"
                surface.blit(font_small.render(line[:84], True, (220, 220, 220)), (panel_x + 32, timeline_y))
                timeline_y += 22
        else:
            surface.blit(font_small.render("Timeline is still forming.", True, (180, 190, 215)), (panel_x + 32, timeline_y))

        trend_x = panel_x + 20 + lower_left_w + box_gap
        trend_y = draw_box("Trait Drift + Checkpoints", trend_x, lower_box_y, lower_right_w, lower_h)
        for trait in report["trait_outliers"][:3]:
            drift_line = f"{trait['trait_name'][:14]} {trait['delta_pct']:+.1f}%"
            surface.blit(font_small.render(drift_line, True, (150, 220, 255)), (trend_x + 12, trend_y))
            trend_y += 22
        if report["generation_history"]:
            trend_y += 8
            for sample in report["generation_history"][-4:]:
                checkpoint = f"t+{int(sample.get('elapsed_seconds', 0))}s  pop {sample.get('population', 0)}  gen {sample.get('avg_generation', 0):.1f}"
                surface.blit(font_small.render(checkpoint[:28], True, (210, 210, 235)), (trend_x + 12, trend_y))
                trend_y += 20
        if report["faction_history"]:
            trend_y += 8
            for faction_event in report["faction_history"][-2:]:
                action = str(faction_event.get("action", "shift")).title()
                details = f"{action} F{faction_event.get('faction_id', '?')} size {faction_event.get('members', 0)}"
                surface.blit(font_small.render(details[:28], True, (210, 185, 255)), (trend_x + 12, trend_y))
                trend_y += 20

        close_hint = font_small.render("[T] to close", True, (180, 200, 230))
        surface.blit(close_hint, (panel_x + panel_w - 104, panel_y + panel_h - 28))


class ArchiveReviewPanel:
    """Run archive and comparison view for observer-side postmortems."""

    def __init__(self):
        self.last_refresh_time = 0.0
        self.cached_log_dir = ""
        self.cached_archive_count = 0
        self.cached_comparisons = []

    def _refresh_cache(self, current_summary, log_dir, current_time):
        if not log_dir:
            self.cached_comparisons = []
            return
        if (
            log_dir != self.cached_log_dir
            or current_time - self.last_refresh_time >= 5.0
        ):
            archive_paths = find_recent_archives(log_dir, limit=3)
            self.cached_comparisons = build_archive_comparison(current_summary, archive_paths) if current_summary else []
            self.cached_archive_count = len(archive_paths)
            self.cached_log_dir = log_dir
            self.last_refresh_time = current_time

    def draw(self, surface, advisor, current_time, log_dir):
        current_summary = dict(advisor.session_stats.get("current_run_summary", {}) or {})
        self._refresh_cache(current_summary, log_dir, current_time)

        panel_w = min(980, WINDOW_WIDTH - 40)
        panel_h = min(620, WINDOW_HEIGHT - 70)
        panel_x = max(20, WINDOW_WIDTH // 2 - panel_w // 2)
        panel_y = max(20, WINDOW_HEIGHT // 2 - panel_h // 2)

        panel = pygame.Surface((panel_w, panel_h))
        panel.set_alpha(242)
        panel.fill((18, 22, 34))
        surface.blit(panel, (panel_x, panel_y))
        pygame.draw.rect(surface, (135, 170, 220), (panel_x, panel_y, panel_w, panel_h), 3)

        scenario_name = current_summary.get("scenario", {}).get("name") or advisor.session_stats.get(
            "scenario_name",
            ACTIVE_SCENARIO_PROFILE.get("name", "Standard Basin"),
        )
        title = font.render("RUN ARCHIVE REVIEW", True, (230, 235, 255))
        subtitle = font_small.render(
            f"{scenario_name}  |  Phase progression, end-state, and recent-run comparison",
            True,
            (170, 210, 255),
        )
        surface.blit(title, (panel_x + 20, panel_y + 14))
        surface.blit(subtitle, (panel_x + 20, panel_y + 42))

        phase = dict(current_summary.get("current_phase", {}) or {})
        phase_id = phase.get("id", "founding")
        end_state = dict(current_summary.get("end_state", {}) or {})
        summary_card = dict(current_summary.get("summary_card", {}) or {})
        settlement = dict(current_summary.get("settlement", {}) or {})
        dominant_lineage = dict(current_summary.get("dominant_lineage", {}) or {})
        dominant_faction = dict(current_summary.get("dominant_faction", {}) or {})
        council = dict(current_summary.get("council", {}) or {})
        doctrine = dict(council.get("doctrine", {}) or {})
        phase_summary = RUN_PHASE_DEFINITIONS.get(phase_id, RUN_PHASE_DEFINITIONS["founding"]).get("summary", "")

        def draw_box(title_text, box_x, box_y, box_w, box_h):
            pygame.draw.rect(surface, (34, 40, 58), (box_x, box_y, box_w, box_h))
            pygame.draw.rect(surface, (90, 120, 170), (box_x, box_y, box_w, box_h), 2)
            title_surface = font_small.render(title_text, True, (215, 228, 255))
            surface.blit(title_surface, (box_x + 12, box_y + 10))
            return box_y + 36

        top_y = panel_y + 78
        gap = 16
        left_w = 360
        mid_w = 270
        right_w = panel_w - 40 - left_w - mid_w - gap * 2

        info_y = draw_box("Current Run", panel_x + 20, top_y, left_w, 176)
        info_lines = [
            f"Phase: {phase.get('label', 'Founding')}",
            f"End-state: {end_state.get('label', 'Brittle Survival')}",
            f"Observer score: {int(end_state.get('score', 0) or 0)}",
            f"Peak population: {int(summary_card.get('population_peak', 0) or 0)}",
            f"Births / deaths: {int(summary_card.get('births_total', 0) or 0)} / {int(summary_card.get('deaths_total', 0) or 0)}",
            f"District: {str(settlement.get('district_identity', 'homestead')).replace('_', ' ').title()}",
            f"Prosperity {float(settlement.get('prosperity_score', 0.0) or 0.0):.2f}  |  Culture {float(settlement.get('culture_score', 0.0) or 0.0):.2f}",
        ]
        for line in info_lines:
            surface.blit(font_small.render(line[:44], True, WHITE), (panel_x + 32, info_y))
            info_y += 22

        phase_x = panel_x + 20 + left_w + gap
        phase_y = draw_box("Phase + Doctrine", phase_x, top_y, mid_w, 176)
        phase_lines = [
            phase_summary[:40] or "The colony is still establishing itself.",
            f"Doctrine: {str(doctrine.get('focus', 'survival')).replace('_', ' ').title()}",
            f"Stance: {str(doctrine.get('stance', 'measured')).title()}",
            f"District priority: {str(doctrine.get('district_priority', 'homestead')).replace('_', ' ').title()}",
            f"Crisis posture: {str(doctrine.get('crisis_posture', 'stabilize')).replace('_', ' ').title()}",
        ]
        for line in phase_lines:
            surface.blit(font_small.render(line[:32], True, (210, 225, 255)), (phase_x + 12, phase_y))
            phase_y += 22

        if doctrine.get("reasoning"):
            surface.blit(
                font_small.render(str(doctrine.get("reasoning", ""))[:32], True, (190, 200, 220)),
                (phase_x + 12, phase_y + 4),
            )

        compare_x = phase_x + mid_w + gap
        compare_y = draw_box("Recent Archives", compare_x, top_y, right_w, 176)
        if self.cached_comparisons:
            for comparison in self.cached_comparisons[:3]:
                header = (
                    f"{comparison.get('scenario_name', 'Unknown')}  "
                    f"{comparison.get('score', 0)} pts"
                )
                surface.blit(font_small.render(header[:28], True, (255, 220, 170)), (compare_x + 12, compare_y))
                compare_y += 20
                detail = (
                    f"{comparison.get('end_state_label', 'Unknown')}  "
                    f"peak {comparison.get('population_peak', 0)}  "
                    f"delta {comparison.get('score_delta', 0):+d}"
                )
                surface.blit(font_small.render(detail[:30], True, (215, 220, 240)), (compare_x + 12, compare_y))
                compare_y += 28
        else:
            surface.blit(font_small.render("No archived runs yet.", True, (180, 190, 215)), (compare_x + 12, compare_y))
            compare_y += 22
        archive_count_line = f"Archive files available: {self.cached_archive_count}"
        surface.blit(font_small.render(archive_count_line, True, (170, 190, 220)), (compare_x + 12, top_y + 144))

        lower_y = top_y + 176 + 18
        lower_h = panel_h - (lower_y - panel_y) - 24
        lower_left_w = panel_w - 40 - 280 - gap
        lower_right_w = 280

        timeline_y = draw_box("Major Moments", panel_x + 20, lower_y, lower_left_w, lower_h)
        timeline = list(current_summary.get("observer_report", {}).get("timeline", []))
        if timeline:
            for event in timeline[-8:]:
                category = str(event.get("category", "sim"))[:10].upper()
                summary = str(event.get("summary", "Event"))
                line = f"[{category}] {summary}"
                surface.blit(font_small.render(line[:80], True, (220, 220, 220)), (panel_x + 32, timeline_y))
                timeline_y += 22
        else:
            surface.blit(font_small.render("The timeline is still sparse.", True, (180, 190, 215)), (panel_x + 32, timeline_y))

        right_y = draw_box("Dominance + Friction", panel_x + 20 + lower_left_w + gap, lower_y, lower_right_w, lower_h)
        right_lines = [
            (
                f"Lineage L{dominant_lineage.get('lineage_id', '?')}  "
                f"{dominant_lineage.get('count', 0)} ({int(float(dominant_lineage.get('share', 0.0) or 0.0) * 100)}%)"
                if dominant_lineage
                else "No dominant lineage yet."
            ),
            (
                f"Faction F{dominant_faction.get('id', '?')}  size {dominant_faction.get('members', 0)}"
                if dominant_faction
                else "No dominant faction yet."
            ),
            f"Festival readiness: {float(settlement.get('festival_readiness', 0.0) or 0.0):.2f}",
        ]
        for line in right_lines:
            surface.blit(font_small.render(line[:30], True, (210, 225, 255)), (panel_x + 20 + lower_left_w + gap + 12, right_y))
            right_y += 22

        event_framing = str(council.get("event_framing", ""))
        if event_framing:
            right_y += 8
            surface.blit(font_small.render("Council framing", True, (255, 220, 170)), (panel_x + 20 + lower_left_w + gap + 12, right_y))
            right_y += 22
            for offset in range(0, min(len(event_framing), 96), 30):
                surface.blit(
                    font_small.render(event_framing[offset : offset + 30], True, (220, 220, 220)),
                    (panel_x + 20 + lower_left_w + gap + 12, right_y),
                )
                right_y += 20

        close_hint = font_small.render("[A] to close", True, (180, 200, 230))
        surface.blit(close_hint, (panel_x + panel_w - 104, panel_y + panel_h - 28))


class FogOfWar:
    """Manages fog of war - areas not yet explored are hidden"""
    def __init__(self, world_width, world_height):
        self.fog_grid = {}  # {(tile_x, tile_y): visibility_level (0-255)}
        self.visibility_radius = 60  # Pixels around each thronglet (much smaller)
        self.world_width = world_width
        self.world_height = world_height
    
    def update(self, thronglets):
        """Update fog based on thronglet positions with small circular visibility"""
        for thronglet in thronglets:
            # Apply exploration skill bonus to visibility radius
            radius = self.visibility_radius
            if thronglet.role == 'explorer':
                radius = int(self.visibility_radius * thronglet.get_exploration_bonus())
            
            # Reveal a small circular area around each thronglet
            # Check tiles in a grid around the thronglet
            tile_radius = int(radius / TILE_SIZE) + 1
            
            # Get the thronglet's tile position
            tile_center_x = int(thronglet.x // TILE_SIZE)
            tile_center_y = int(thronglet.y // TILE_SIZE)
            
            # Reveal tiles in a square grid, but only those within circular radius
            for dx in range(-tile_radius, tile_radius + 1):
                for dy in range(-tile_radius, tile_radius + 1):
                    # Calculate distance from thronglet center
                    tile_x = tile_center_x + dx
                    tile_y = tile_center_y + dy
                    
                    # Check if within circular radius
                    distance = math.sqrt((dx * TILE_SIZE)**2 + (dy * TILE_SIZE)**2)
                    if distance <= radius:
                        key = (tile_x, tile_y)
                        # Mark as fully visible (255)
                        self.fog_grid[key] = 255
    
    def is_visible(self, x, y):
        """Check if a world position is visible"""
        tile_x = int(x // TILE_SIZE)
        tile_y = int(y // TILE_SIZE)
        # Visible if visibility level > 128 (half visible)
        return self.fog_grid.get((tile_x, tile_y), 0) > 128
    
    def draw_fog(self, surface, camera, world_map):
        """Draw dark overlay on unexplored tiles"""
        # Draw fog at tile level for better visual control
        for chunk_key, chunk in world_map.chunks.items():
            # Transform chunk world coords to screen coords
            screen_x, screen_y = camera.world_to_screen(chunk.world_x, chunk.world_y)
            screen_x2, screen_y2 = camera.world_to_screen(chunk.world_x + CHUNK_SIZE, chunk.world_y + CHUNK_SIZE)
            
            # Only draw if on screen
            if screen_x2 > 0 and screen_x < WINDOW_WIDTH and screen_y2 > 0 and screen_y < WINDOW_HEIGHT:
                # Scale by zoom
                zoomed_tile_size = int(TILE_SIZE * camera.zoom)
                tiles_per_chunk = CHUNK_SIZE // TILE_SIZE
                
                # Draw fog at tile level for smoother circular visibility
                for tx in range(tiles_per_chunk):
                    for ty in range(tiles_per_chunk):
                        world_tile_x = int((chunk.world_x // TILE_SIZE) + tx)
                        world_tile_y = int((chunk.world_y // TILE_SIZE) + ty)
                        
                        # Check if this tile is visible
                        if (world_tile_x, world_tile_y) not in self.fog_grid:
                            # Draw dark overlay for this tile
                            tile_screen_x = screen_x + (tx * zoomed_tile_size)
                            tile_screen_y = screen_y + (ty * zoomed_tile_size)
                            
                            if -zoomed_tile_size <= tile_screen_x <= WINDOW_WIDTH and -zoomed_tile_size <= tile_screen_y <= WINDOW_HEIGHT:
                                fog_surface = pygame.Surface((max(1, zoomed_tile_size + 1), max(1, zoomed_tile_size + 1)), pygame.SRCALPHA)
                                fog_color = (0, 0, 0, 220)  # Black with alpha 220
                                fog_surface.fill(fog_color)
                                surface.blit(fog_surface, (int(tile_screen_x), int(tile_screen_y)))


class TerritoryManager:
    """Manages territory claiming based on thronglet presence and buildings using Voronoi diagram"""
    def __init__(self, world_width, world_height):
        self.territory_grid = {}  # {(tile_x, tile_y): {'claim_strength': 0-100, 'claimed_time': timestamp, 'center_type': 'building'|'exploration'}}
        self.world_width = world_width
        self.world_height = world_height
        
        # Voronoi caching
        self.voronoi_cache = {}  # {(tile_x, tile_y): seed_id}
        self.voronoi_seeds = []  # List of (x, y, seed_id, center_type) tuples
        self.last_voronoi_calculation = 0
        self.last_population_count = 0
        self.voronoi_cache_valid = False
        self.VORONOI_RECALC_INTERVAL = 5.0  # Recalculate every 5 seconds max
    
    def update(self, thronglets, buildings):
        """Update territory based on thronglet positions and buildings using Voronoi diagram"""
        current_time = time.time()
        current_population = len(thronglets) + len(buildings)
        
        # Check if we need to recalculate Voronoi diagram
        needs_recalculation = (
            not self.voronoi_cache_valid or
            (current_time - self.last_voronoi_calculation) > self.VORONOI_RECALC_INTERVAL or
            abs(current_population - self.last_population_count) > 3  # Significant population change
        )
        
        if needs_recalculation:
            self._calculate_voronoi_cells(thronglets, buildings)
            self.last_voronoi_calculation = current_time
            self.last_population_count = current_population
            self.voronoi_cache_valid = True
        
        # Update claim strength based on Voronoi assignment
        self._update_claim_strength_from_voronoi(thronglets, buildings)
        
        # Decay unclaimed tiles
        to_remove = []
        for tile_pos, data in self.territory_grid.items():
            data['claim_strength'] -= TERRITORY_DECAY_RATE
            if data['claim_strength'] <= 0:
                to_remove.append(tile_pos)
        
        for tile_pos in to_remove:
            del self.territory_grid[tile_pos]
    
    def _calculate_voronoi_cells(self, thronglets, buildings):
        """Calculate Voronoi diagram using thronglet positions and building centers as seeds"""
        self.voronoi_seeds = []
        self.voronoi_cache = {}
        seed_id = 0
        
        # Collect seeds from thronglets
        for thronglet in thronglets:
            self.voronoi_seeds.append((thronglet.x, thronglet.y, seed_id, 'exploration'))
            seed_id += 1
        
        # Collect seeds from buildings
        for building in buildings:
            self.voronoi_seeds.append((building.x, building.y, seed_id, 'building'))
            seed_id += 1
        
        if not self.voronoi_seeds:
            return
        
        # Calculate Voronoi for relevant area (around claimed territory or all seeds)
        # Use bounding box of seeds with padding
        if self.territory_grid:
            # Use existing territory bounds
            bounds = self.get_territory_bounds()
            if bounds:
                min_tile_x = int((bounds['min_x'] - 200) // TILE_SIZE)
                max_tile_x = int((bounds['max_x'] + 200) // TILE_SIZE)
                min_tile_y = int((bounds['min_y'] - 200) // TILE_SIZE)
                max_tile_y = int((bounds['max_y'] + 200) // TILE_SIZE)
            else:
                # No territory yet, use seed bounding box
                seed_xs = [s[0] for s in self.voronoi_seeds]
                seed_ys = [s[1] for s in self.voronoi_seeds]
                min_tile_x = int((min(seed_xs) - 200) // TILE_SIZE)
                max_tile_x = int((max(seed_xs) + 200) // TILE_SIZE)
                min_tile_y = int((min(seed_ys) - 200) // TILE_SIZE)
                max_tile_y = int((max(seed_ys) + 200) // TILE_SIZE)
        else:
            # No territory, calculate around seeds
            seed_xs = [s[0] for s in self.voronoi_seeds]
            seed_ys = [s[1] for s in self.voronoi_seeds]
            min_tile_x = int((min(seed_xs) - 200) // TILE_SIZE)
            max_tile_x = int((max(seed_xs) + 200) // TILE_SIZE)
            min_tile_y = int((min(seed_ys) - 200) // TILE_SIZE)
            max_tile_y = int((max(seed_ys) + 200) // TILE_SIZE)
        
        # Clamp to world bounds
        max_world_tile_x = int(self.world_width // TILE_SIZE)
        max_world_tile_y = int(self.world_height // TILE_SIZE)
        min_tile_x = max(0, min_tile_x)
        max_tile_x = min(max_world_tile_x, max_tile_x)
        min_tile_y = max(0, min_tile_y)
        max_tile_y = min(max_world_tile_y, max_tile_y)
        
        # Safety: Limit calculation area to prevent hang on first frame
        # Max 200x200 tiles (6400x6400 pixels) to keep calculation fast
        MAX_TILES_PER_DIMENSION = 200
        if (max_tile_x - min_tile_x) > MAX_TILES_PER_DIMENSION:
            center_x = (min_tile_x + max_tile_x) // 2
            min_tile_x = center_x - MAX_TILES_PER_DIMENSION // 2
            max_tile_x = center_x + MAX_TILES_PER_DIMENSION // 2
        if (max_tile_y - min_tile_y) > MAX_TILES_PER_DIMENSION:
            center_y = (min_tile_y + max_tile_y) // 2
            min_tile_y = center_y - MAX_TILES_PER_DIMENSION // 2
            max_tile_y = center_y + MAX_TILES_PER_DIMENSION // 2
        
        # For each tile, find closest seed (Voronoi assignment)
        for tile_x in range(min_tile_x, max_tile_x + 1):
            for tile_y in range(min_tile_y, max_tile_y + 1):
                world_x = tile_x * TILE_SIZE + TILE_SIZE // 2
                world_y = tile_y * TILE_SIZE + TILE_SIZE // 2
                
                # Find closest seed
                closest_seed_id = None
                closest_distance = float('inf')
                closest_center_type = 'exploration'
                
                for seed_x, seed_y, seed_id, center_type in self.voronoi_seeds:
                    distance = math.sqrt((world_x - seed_x)**2 + (world_y - seed_y)**2)
                    if distance < closest_distance:
                        closest_distance = distance
                        closest_seed_id = seed_id
                        closest_center_type = center_type
                
                if closest_seed_id is not None:
                    self.voronoi_cache[(tile_x, tile_y)] = (closest_seed_id, closest_center_type)
    
    def _update_claim_strength_from_voronoi(self, thronglets, buildings):
        """Update claim strength based on Voronoi assignment and seed proximity"""
        current_time = time.time()
        
        # Build seed lookup by ID
        seed_lookup = {}
        seed_id = 0
        for thronglet in thronglets:
            seed_lookup[seed_id] = ('thronglet', thronglet.x, thronglet.y)
            seed_id += 1
        for building in buildings:
            seed_lookup[seed_id] = ('building', building.x, building.y)
            seed_id += 1
        
        # Update territory grid from Voronoi cache
        for (tile_x, tile_y), (seed_id, center_type) in self.voronoi_cache.items():
            if seed_id not in seed_lookup:
                continue  # Seed no longer exists
            
            seed_type, seed_x, seed_y = seed_lookup[seed_id]
            world_x = tile_x * TILE_SIZE + TILE_SIZE // 2
            world_y = tile_y * TILE_SIZE + TILE_SIZE // 2
            
            # Calculate distance from tile center to seed
            distance = math.sqrt((world_x - seed_x)**2 + (world_y - seed_y)**2)
            
            # Claim strength based on distance (closer = stronger)
            max_radius = BUILDING_CLAIM_RADIUS if seed_type == 'building' else TERRITORY_CLAIM_RADIUS
            if distance <= max_radius:
                # Calculate claim strength (inverse distance, normalized)
                strength_factor = 1.0 - (distance / max_radius)
                claim_rate = TERRITORY_CLAIM_RATE * (2.0 if seed_type == 'building' else 1.0)
                new_strength = min(100, strength_factor * claim_rate * 0.1)  # Scale for reasonable growth
                
                key = (tile_x, tile_y)
                if key not in self.territory_grid:
                    self.territory_grid[key] = {
                        'claim_strength': 0,
                        'claimed_time': current_time,
                        'center_type': center_type
                    }
                
                # Increase claim strength, cap at 100
                self.territory_grid[key]['claim_strength'] = min(
                    100,
                    self.territory_grid[key]['claim_strength'] + new_strength
                )
    
    def _claim_area_around_point(self, x, y, radius, claim_rate, center_type):
        """Helper to claim territory around a point (legacy method, kept for backward compatibility)"""
        # This method is now handled by Voronoi calculation, but kept for API compatibility
        # Voronoi-based claiming happens in _update_claim_strength_from_voronoi()
        pass
    
    def is_claimed(self, x, y, threshold=50):
        """Check if a tile is claimed (claim_strength >= threshold)"""
        tile_x = int(x // TILE_SIZE)
        tile_y = int(y // TILE_SIZE)
        key = (tile_x, tile_y)
        
        if key not in self.territory_grid:
            return False
        
        return self.territory_grid[key]['claim_strength'] >= threshold
    
    def get_claim_strength(self, x, y):
        """Return 0-100 claim strength at position"""
        tile_x = int(x // TILE_SIZE)
        tile_y = int(y // TILE_SIZE)
        key = (tile_x, tile_y)
        
        if key not in self.territory_grid:
            return 0
        
        return self.territory_grid[key]['claim_strength']
    
    def get_territory_bounds(self):
        """Return bounding box of claimed territory"""
        if not self.territory_grid:
            return None
        
        # Get all claimed tiles with strength >= 50
        claimed_tiles = [(x, y) for (x, y), data in self.territory_grid.items() 
                        if data['claim_strength'] >= 50]
        
        if not claimed_tiles:
            return None
        
        min_x = min(x for x, y in claimed_tiles) * TILE_SIZE
        max_x = max(x for x, y in claimed_tiles) * TILE_SIZE
        min_y = min(y for x, y in claimed_tiles) * TILE_SIZE
        max_y = max(y for x, y in claimed_tiles) * TILE_SIZE
        
        return {
            'min_x': min_x, 'max_x': max_x,
            'min_y': min_y, 'max_y': max_y,
            'center_x': (min_x + max_x) / 2,
            'center_y': (min_y + max_y) / 2
        }
    
    def draw_territory_overlay(self, surface, camera, fog_of_war):
        """Draw semi-transparent territory overlay with green tint"""
        # Draw territory at tile level for better visual control
        for tile_pos, data in self.territory_grid.items():
            claim_strength = data['claim_strength']
            
            # Only draw if above threshold
            if claim_strength < 20:
                continue
            
            tile_x, tile_y = tile_pos
            world_x = tile_x * TILE_SIZE
            world_y = tile_y * TILE_SIZE
            
            # Check if visible (fog of war)
            if not fog_of_war.is_visible(world_x, world_y):
                continue
            
            # Transform to screen coordinates
            screen_x, screen_y = camera.world_to_screen(world_x, world_y)
            
            # Scale by zoom
            zoomed_tile_size = int(TILE_SIZE * camera.zoom)
            
            # Only draw if on screen
            if -zoomed_tile_size <= screen_x <= WINDOW_WIDTH and -zoomed_tile_size <= screen_y <= WINDOW_HEIGHT:
                # Alpha based on claim strength (20-100 maps to 20-80 alpha)
                alpha = int(20 + (claim_strength / 100.0) * 60)
                
                # Green tint overlay
                territory_surface = pygame.Surface((max(1, zoomed_tile_size), max(1, zoomed_tile_size)), pygame.SRCALPHA)
                territory_color = (50, 200, 50, alpha)  # Green with variable alpha
                territory_surface.fill(territory_color)
                surface.blit(territory_surface, (int(screen_x), int(screen_y)))


class CityPlanner:
    """Manages city planning with zones and smart building placement"""
    def __init__(self, territory_manager, world_map):
        self.territory_manager = territory_manager
        self.world_map = world_map
        self.zones = {}  # {(tile_x, tile_y): zone_type}
        self.current_plan = None
        self.last_plan_update = 0
        self.plan_update_interval = 120  # Update plan every 120 seconds
    
    def update(self, thronglets, buildings, advisor, current_time):
        """Update city planner, check for plan updates"""
        # Generate zones if territory exists
        if self.territory_manager.territory_grid:
            bounds = self.territory_manager.get_territory_bounds()
            if bounds:
                self._generate_zones(bounds['center_x'], bounds['center_y'])
        
        # Check if we need a new city plan
        num_thronglets = len(thronglets)
        if (num_thronglets > 10 and not self.current_plan) or \
           (current_time - self.last_plan_update > self.plan_update_interval):
            self._request_city_plan_from_llm(thronglets, buildings, advisor)
            self.last_plan_update = current_time
    
    def _generate_zones(self, center_x, center_y):
        """Generate city zones using noise-based procedural generation"""
        radius = 300  # Search radius around center
        tile_radius = int(radius / TILE_SIZE) + 1
        
        center_tile_x = int(center_x // TILE_SIZE)
        center_tile_y = int(center_y // TILE_SIZE)
        
        for dx in range(-tile_radius, tile_radius + 1):
            for dy in range(-tile_radius, tile_radius + 1):
                tile_x = center_tile_x + dx
                tile_y = center_tile_y + dy
                
                # Use noise to determine zone type
                noise_value = sample_procedural_noise(
                    tile_x,
                    tile_y,
                    scale=0.1,
                    octaves=4,
                    persistence=0.5,
                    lacunarity=2.0,
                )
                
                # Map noise to zone types
                if noise_value < -0.3:
                    zone_type = 'residential'
                elif noise_value < 0.0:
                    zone_type = 'production'
                elif noise_value < 0.2:
                    zone_type = 'storage'
                elif noise_value < 0.4:
                    zone_type = 'civic'
                else:
                    zone_type = 'mixed'
                
                self.zones[(tile_x, tile_y)] = zone_type
    
    def get_zone_type(self, x, y):
        """Get zone type at position"""
        tile_x = int(x // TILE_SIZE)
        tile_y = int(y // TILE_SIZE)
        return self.zones.get((tile_x, tile_y), 'mixed')
    
    def score_building_location(self, x, y, building_type, buildings, hazards, world_map, thronglets=None):
        """Score a building location 0-100"""
        score = 50  # Base score
        
        # Territory bonus
        if self.territory_manager.is_claimed(x, y, threshold=40):
            score += 30
        else:
            score -= 15  # Soft penalty
        
        # Boids clustering: Check nearby thronglet density (prefer areas with thronglets)
        if thronglets:
            nearby_thronglet_count = 0
            density_radius = 150  # Check within 150px
            for thronglet in thronglets:
                distance = math.sqrt((thronglet.x - x)**2 + (thronglet.y - y)**2)
                if distance < density_radius:
                    nearby_thronglet_count += 1
            
            # Bonus for clustering (2-4 thronglets nearby is ideal)
            if 2 <= nearby_thronglet_count <= 4:
                score += 15  # Good clustering
            elif nearby_thronglet_count >= 5:
                score += 10  # Still good but getting crowded
            elif nearby_thronglet_count == 1:
                score += 5  # Some activity
            elif nearby_thronglet_count == 0:
                score -= 5  # Isolated location (slight penalty)
        
        # Proximity bonuses
        for building in buildings:
            distance = math.sqrt((building.x - x)**2 + (building.y - y)**2)
            
            # Clustering rules
            if building_type == 'house' and building.building_type == 'house':
                # Houses cluster together
                if distance < 80:
                    score += 20
                elif distance > 200:
                    score -= 10
            
            elif building_type == 'farm' and building.building_type == 'storage':
                # Farms near storage
                if distance < 100:
                    score += 15
                elif distance > 250:
                    score -= 10
            
            elif building_type == 'workshop' and building.building_type == 'house':
                # Workshops near houses
                if distance < 120:
                    score += 10
            
            # Avoid too close to any building
            if distance < 30:
                score -= 20
        
        # Hazard avoidance
        for hazard in hazards:
            distance = math.sqrt((hazard.x - x)**2 + (hazard.y - y)**2)
            if distance < hazard.radius:
                score -= 50
        
        # Biome suitability
        biome_type = world_map.get_biome_at(x, y)
        biome_props = world_map.get_biome_properties(biome_type)
        
        if building_type == 'farm':
            # Farms prefer plains and forests
            if biome_type in ['plains', 'forest']:
                score += 15
            elif biome_type in ['mountains', 'desert', 'swamp']:
                score -= 20
        elif building_type == 'house':
            # Houses avoid difficult terrain
            if biome_type in ['swamp', 'desert', 'mountains']:
                score -= 15
        
        # Zone compatibility
        zone_type = self.get_zone_type(x, y)
        if building_type == 'house' and zone_type in ['residential', 'mixed']:
            score += 10
        elif building_type in ['farm', 'workshop'] and zone_type in ['production', 'mixed']:
            score += 10
        elif building_type == 'storage' and zone_type in ['storage', 'mixed']:
            score += 10
        
        return max(0, min(100, score))  # Clamp 0-100
    
    def find_best_location(self, building_type, buildings, hazards, search_center, search_radius=150, thronglets=None):
        """Find best location for a building"""
        best_score = -1
        best_x, best_y = search_center
        
        # Sample 30 candidate positions
        for _ in range(30):
            # Random offset within search radius
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(0, search_radius)
            candidate_x = search_center[0] + distance * math.cos(angle)
            candidate_y = search_center[1] + distance * math.sin(angle)
            
            # Score this location
            score = self.score_building_location(
                candidate_x, candidate_y, building_type, 
                buildings, hazards, self.world_map, thronglets
            )
            
            if score > best_score:
                best_score = score
                best_x, best_y = candidate_x, candidate_y
        
        return best_x, best_y, best_score
    
    def _request_city_plan_from_llm(self, thronglets, buildings, advisor):
        """Request city plan from LLM via advisor"""
        # This will be called from advisor.query_llm to generate plan
        # Store reference for advisor to use
        pass
    
    def get_plan_summary(self):
        """Get human-readable summary of current plan"""
        if not self.current_plan:
            return "No city plan yet"
        
        summary = []
        if 'districts' in self.current_plan:
            for district in self.current_plan['districts']:
                district_text = f"- {district.get('type', 'unknown')} (priority {district.get('priority', 0)}): {district.get('location', 'unknown')}"
                summary.append(district_text)
        
        if 'expansion_direction' in self.current_plan:
            summary.append(f"Expansion: {self.current_plan['expansion_direction']}")
        
        if 'rationale' in self.current_plan:
            summary.append(f"Reason: {self.current_plan['rationale']}")
        
        return "\n".join(summary) if summary else "Plan exists but empty"


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
    """Represents a communal task that requires coordination between multiple thronglets"""
    def __init__(self, task_type, description, required_count=1, target_location=None, target_building_type=None):
        self.task_type = task_type  # 'build', 'gather', 'explore', etc.
        self.description = description
        self.required_count = required_count
        self.assigned_thronglets = []  # List of thronglet IDs
        self.target_location = target_location  # (x, y) for coordinated gathering/building
        self.target_building_type = target_building_type  # For building tasks
        self.created_time = time.time()
        self.active = True
        self.faction_id = None  # Optional: faction this task belongs to
    
    def is_complete(self):
        """Check if task has required number of thronglets assigned"""
        return len(self.assigned_thronglets) >= self.required_count
    
    def add_thronglet(self, thronglet_id):
        """Assign a thronglet to this task"""
        if thronglet_id not in self.assigned_thronglets:
            self.assigned_thronglets.append(thronglet_id)
    
    def remove_thronglet(self, thronglet_id):
        """Remove a thronglet from this task"""
        if thronglet_id in self.assigned_thronglets:
            self.assigned_thronglets.remove(thronglet_id)


class Faction:
    """Represents a group of thronglets with strong bonds"""
    _next_id = 0
    
    def __init__(self, member_ids):
        self.id = Faction._next_id
        Faction._next_id += 1
        self.member_ids = list(member_ids)  # List of thronglet IDs
        self.leader_id = None  # Will be set to highest skill thronglet
        self.shared_goals = []  # Goals assigned by LLM
        self.formed_time = time.time()
        self.ideology = {axis: 0.0 for axis in FACTION_IDEOLOGY_AXES}
        self.cohesion = 50.0
        self.stability = 50.0
        self.primary_doctrine = "growth"
        self.doctrine_profile = dict(FACTION_DOCTRINE_PROFILES[self.primary_doctrine])
        self.rival_faction_ids = []
        self.schism_pressure = 0.0
        self.migration_pressure = 0.0
        self.migration_target = None
        self.preferred_biome = "plains"
        self.succession_count = 0
        self.last_succession_time = 0.0
        self.last_schism_time = 0.0
        self.last_migration_time = 0.0
        self.last_doctrine_goal_time = 0.0
    
    def add_member(self, thronglet_id):
        """Add a member to this faction"""
        if thronglet_id not in self.member_ids:
            self.member_ids.append(thronglet_id)
    
    def remove_member(self, thronglet_id):
        """Remove a member from this faction"""
        if thronglet_id in self.member_ids:
            self.member_ids.remove(thronglet_id)
    
    def update_leader(self, thronglets):
        """Update leader to highest skill thronglet"""
        best_skill = -1.0
        best_id = None
        
        for thronglet_id in self.member_ids:
            thronglet = next((t for t in thronglets if t.id == thronglet_id), None)
            if thronglet:
                total_skill = 0.0
                skill_key = get_role_skill_key(thronglet.role)
                if skill_key and skill_key in thronglet.skills:
                    total_skill = float(thronglet.skills[skill_key]['level']) * 12.0
                total_skill += float(getattr(thronglet, "health", 100.0)) * 0.08
                total_skill += float(getattr(thronglet, "happiness", 70.0)) * 0.06
                total_skill += float(getattr(thronglet, "morale", 65.0)) * 0.07
                total_skill += float(getattr(thronglet, "genetics", {}).get("social_cohesion", 1.0)) * 7.5
                if thronglet.id == self.leader_id:
                    total_skill += 5.0
                
                if total_skill > best_skill:
                    best_skill = total_skill
                    best_id = thronglet_id
        
        self.leader_id = best_id if best_id else (self.member_ids[0] if self.member_ids else None)
    
    def get_bond_strength(self, thronglets):
        """Get average bond strength within faction"""
        if len(self.member_ids) < 2:
            return 0.0
        
        total_bonds = 0.0
        bond_count = 0
        
        for thronglet in thronglets:
            if thronglet.id in self.member_ids:
                for other_id in self.member_ids:
                    if other_id != thronglet.id and other_id in thronglet.bonds:
                        total_bonds += thronglet.bonds[other_id]
                        bond_count += 1
        
        return total_bonds / bond_count if bond_count > 0 else 0.0

    def get_members(self, thronglets):
        return [thronglet for thronglet in thronglets if thronglet.id in self.member_ids]

    def get_centroid(self, thronglets):
        members = self.get_members(thronglets)
        if not members:
            return None
        avg_x = sum(member.x for member in members) / len(members)
        avg_y = sum(member.y for member in members) / len(members)
        return (avg_x, avg_y)

    def refresh_identity(self, thronglets):
        members = self.get_members(thronglets)
        if not members:
            return

        avg_bond = self.get_bond_strength(thronglets)
        member_snapshots = []
        for member in members:
            member_snapshots.append(
                {
                    "id": member.id,
                    "health": member.health,
                    "happiness": member.happiness,
                    "morale": getattr(member, "morale", 65),
                    "curiosity": member.personality.get("curiosity", 0.5),
                    "sociability": member.personality.get("sociability", 0.5),
                    "learning_affinity": member.genetics.get("learning_affinity", 1.0),
                    "immune_strength": member.genetics.get("immune_strength", 1.0),
                    "fertility_drive": member.genetics.get("fertility_drive", 1.0),
                    "social_cohesion": member.genetics.get("social_cohesion", 1.0),
                    "adaptability": member.genetics.get("adaptability", 1.0),
                    "favorite_biome": getattr(member, "favorite_biome", "plains"),
                    "role": member.role,
                    "diseased": bool(member.diseased),
                    "known_resources_count": len(getattr(member, "known_resources", [])),
                    "known_resources": list(getattr(member, "known_resources", [])),
                    "leader_bond": member.bonds.get(self.leader_id, 50.0) if self.leader_id is not None else 50.0,
                }
            )

        metrics = compute_faction_metrics(member_snapshots, avg_bond=avg_bond)
        self.ideology = dict(metrics["ideology"])
        self.primary_doctrine = str(metrics["primary_doctrine"])
        self.doctrine_profile = dict(FACTION_DOCTRINE_PROFILES.get(self.primary_doctrine, FACTION_DOCTRINE_PROFILES["growth"]))
        self.cohesion = clamp(float(metrics["cohesion"]), 0.0, 100.0)
        self.stability = clamp(float(metrics["stability"]), 0.0, 100.0)
        self.schism_pressure = clamp(float(metrics["schism_pressure"]), 0.0, 100.0)
        self.migration_pressure = clamp(float(metrics["migration_pressure"]), 0.0, 100.0)
        self.preferred_biome = str(metrics.get("preferred_biome", "plains"))

    def assign_shared_goal(self, goal_text, reasoning="", doctrine_key=""):
        goal_text = str(goal_text or "").strip()
        if not goal_text:
            return
        goal_entry = {
            "goal": goal_text[:120],
            "reasoning": str(reasoning or "").strip()[:180],
            "doctrine_key": doctrine_key or self.primary_doctrine,
            "assigned_at": round(time.time(), 3),
        }
        append_bounded_history(self.shared_goals, goal_entry, 4)


class FactionManager:
    """Manages faction formation and updates"""
    def __init__(self):
        self.factions = {}  # {faction_id: Faction}
        self.last_update = 0
        self.update_interval = 10.0  # Update every 10 seconds
    
    def update_factions(self, thronglets, advisor=None):
        """Auto-form and update factions based on bonds > 70"""
        current_time = time.time()
        
        # Only update periodically for performance
        if current_time - self.last_update < self.update_interval:
            return
        
        self.last_update = current_time
        
        # Find groups of thronglets with mutual bonds > 70
        bond_groups = []
        processed = set()
        
        for thronglet in thronglets:
            if thronglet.id in processed:
                continue
            
            # Find all thronglets with bonds > 70 to this one
            group = {thronglet.id}
            queue = [thronglet]
            
            while queue:
                current = queue.pop(0)
                if current.id in processed:
                    continue
                processed.add(current.id)
                
                for other in thronglets:
                    if other.id in processed or other.id == current.id:
                        continue
                    
                    # Check mutual bond > 70
                    bond_1 = current.bonds.get(other.id, 0)
                    bond_2 = other.bonds.get(current.id, 0)
                    
                    if bond_1 > 70 and bond_2 > 70:
                        group.add(other.id)
                        queue.append(other)
            
            # Only create faction if min(3, population/4) members (scales with population)
            min_faction_size = min(3, max(2, len(thronglets) // 4))
            if len(group) >= min_faction_size:
                bond_groups.append(group)
        
        # Create or update factions
        used_groups = set()
        
        # Try to match existing factions to groups
        for faction_id, faction in list(self.factions.items()):
            best_match = None
            best_overlap = 0
            
            for group in bond_groups:
                overlap = len(set(faction.member_ids) & group)
                if overlap >= 2 and overlap > best_overlap:  # Need at least 2 members overlap
                    best_match = group
                    best_overlap = overlap
            
            if best_match:
                # Update existing faction
                previous_leader_id = faction.leader_id
                faction.member_ids = list(best_match)
                faction.update_leader(thronglets)
                faction.refresh_identity(thronglets)
                self._register_leadership_change(faction, previous_leader_id, advisor, current_time)
                used_groups.add(id(best_match))
            else:
                # Faction dissolved (not enough bonds), remove it
                dissolved_size = len(faction.member_ids)
                del self.factions[faction_id]
                for thronglet in thronglets:
                    if thronglet.faction_id == faction_id:
                        thronglet.faction_id = None
                if advisor is not None:
                    advisor.session_stats["factions_dissolved"] = advisor.session_stats.get("factions_dissolved", 0) + 1
                    self._record_faction_history(
                        advisor,
                        current_time,
                        "dissolved",
                        faction_id=faction_id,
                        members=dissolved_size,
                    )
                    record_observer_timeline_event(advisor, current_time, "faction", f"Faction {faction_id} dissolved", f"{dissolved_size} members lost cohesion.")
        
        # Create new factions for unmatched groups
        for group in bond_groups:
            if id(group) not in used_groups:
                new_faction = Faction(group)
                new_faction.update_leader(thronglets)
                new_faction.refresh_identity(thronglets)
                self.factions[new_faction.id] = new_faction
                
                # Assign faction_id to members
                for thronglet in thronglets:
                    if thronglet.id in group:
                        thronglet.faction_id = new_faction.id
                if advisor is not None:
                    advisor.session_stats["factions_formed"] = advisor.session_stats.get("factions_formed", 0) + 1
                    self._record_faction_history(
                        advisor,
                        current_time,
                        "formed",
                        faction_id=new_faction.id,
                        members=len(group),
                        leader_id=new_faction.leader_id,
                        doctrine=new_faction.primary_doctrine,
                    )
                    record_observer_timeline_event(
                        advisor,
                        current_time,
                        "faction",
                        f"Faction {new_faction.id} formed",
                        f"{len(group)} members around leader #{new_faction.leader_id}.",
                    )

        if advisor is not None:
            advisor.session_stats["peak_factions"] = max(
                advisor.session_stats.get("peak_factions", 0),
                len(self.factions),
            )

        for faction in self.factions.values():
            faction.refresh_identity(thronglets)
        self._update_rivalries()
        self._evaluate_schisms(thronglets, advisor, current_time)
        self._update_rivalries()

    def _update_rivalries(self):
        factions = list(self.factions.values())
        for faction in factions:
            faction.rival_faction_ids = []

        for faction in factions:
            best_rival_id = None
            best_rival_score = 0.0
            for other in factions:
                if other.id == faction.id:
                    continue
                ideology_gap = sum(abs(faction.ideology.get(axis, 0.0) - other.ideology.get(axis, 0.0)) for axis in FACTION_IDEOLOGY_AXES)
                cohesion_pressure = abs(faction.cohesion - other.cohesion) / 100.0
                rivalry_score = ideology_gap + cohesion_pressure
                if rivalry_score > best_rival_score:
                    best_rival_score = rivalry_score
                    best_rival_id = other.id
            if best_rival_id is not None and best_rival_score >= 0.45:
                faction.rival_faction_ids = [best_rival_id]

    def _record_faction_history(self, advisor, current_time, action, **payload):
        if advisor is None:
            return
        event_payload = {"time": current_time, "action": str(action)}
        event_payload.update(payload)
        append_bounded_history(advisor.session_stats.setdefault("faction_history", []), event_payload, 24)

    def _register_leadership_change(self, faction, previous_leader_id, advisor, current_time):
        if previous_leader_id in (None, faction.leader_id):
            return
        if current_time - getattr(faction, "last_succession_time", 0.0) < FACTION_DYNAMICS["succession_grace_seconds"]:
            return
        faction.succession_count += 1
        faction.last_succession_time = current_time
        if advisor is None:
            return
        advisor.session_stats["faction_successions"] = advisor.session_stats.get("faction_successions", 0) + 1
        self._record_faction_history(
            advisor,
            current_time,
            "succession",
            faction_id=faction.id,
            previous_leader_id=previous_leader_id,
            leader_id=faction.leader_id,
            members=len(faction.member_ids),
            doctrine=faction.primary_doctrine,
        )
        record_observer_timeline_event(
            advisor,
            current_time,
            "faction",
            f"Faction {faction.id} leadership changed",
            f"Leader #{previous_leader_id} replaced by #{faction.leader_id}.",
        )

    def _soften_cross_faction_bonds(self, split_members, remaining_members):
        for member in split_members:
            for other in remaining_members:
                if other.id in member.bonds:
                    member.bonds[other.id] = min(member.bonds[other.id], 42.0)
                if member.id in other.bonds:
                    other.bonds[member.id] = min(other.bonds[member.id], 42.0)

    def _evaluate_schisms(self, thronglets, advisor, current_time):
        for faction in list(self.factions.values()):
            if len(faction.member_ids) < max(4, FACTION_DYNAMICS["minimum_schism_size"] * 2):
                continue
            if faction.schism_pressure < FACTION_DYNAMICS["schism_pressure_threshold"]:
                continue
            if current_time - faction.formed_time < FACTION_DYNAMICS["schism_cooldown_seconds"]:
                continue
            if current_time - getattr(faction, "last_schism_time", 0.0) < FACTION_DYNAMICS["schism_cooldown_seconds"]:
                continue

            members = faction.get_members(thronglets)
            if len(members) < 4:
                continue
            member_snapshots = [
                {
                    "id": member.id,
                    "leader_bond": member.bonds.get(faction.leader_id, 50.0) if faction.leader_id is not None else 50.0,
                    "happiness": member.happiness,
                    "curiosity": member.personality.get("curiosity", 0.5),
                    "social_cohesion": member.genetics.get("social_cohesion", 1.0),
                    "favorite_biome": getattr(member, "favorite_biome", "plains"),
                    "role": member.role,
                }
                for member in members
            ]
            split_ids = choose_schism_members(
                member_snapshots,
                leader_id=faction.leader_id,
                preferred_biome=faction.preferred_biome,
                minimum_size=FACTION_DYNAMICS["minimum_schism_size"],
            )
            if not split_ids:
                continue

            split_members = [member for member in members if member.id in split_ids]
            remaining_members = [member for member in members if member.id not in split_ids]
            if len(split_members) < FACTION_DYNAMICS["minimum_schism_size"] or len(remaining_members) < FACTION_DYNAMICS["minimum_schism_size"]:
                continue

            faction.member_ids = [member.id for member in remaining_members]
            new_faction = Faction(split_ids)
            new_faction.formed_time = current_time
            new_faction.last_schism_time = current_time
            faction.last_schism_time = current_time

            for member in split_members:
                member.faction_id = new_faction.id
            for member in remaining_members:
                member.faction_id = faction.id

            self._soften_cross_faction_bonds(split_members, remaining_members)
            faction.update_leader(thronglets)
            faction.refresh_identity(thronglets)
            new_faction.update_leader(thronglets)
            new_faction.refresh_identity(thronglets)
            new_goal = AUTONOMOUS_DOCTRINE_GOALS.get(new_faction.primary_doctrine)
            if new_goal:
                new_faction.assign_shared_goal(new_goal, "Emergent post-schism doctrine", new_faction.primary_doctrine)
            self.factions[new_faction.id] = new_faction

            if advisor is not None:
                advisor.session_stats["faction_schisms"] = advisor.session_stats.get("faction_schisms", 0) + 1
                advisor.session_stats["peak_factions"] = max(advisor.session_stats.get("peak_factions", 0), len(self.factions))
                self._record_faction_history(
                    advisor,
                    current_time,
                    "schism",
                    faction_id=faction.id,
                    new_faction_id=new_faction.id,
                    members=len(split_members),
                    leader_id=new_faction.leader_id,
                    doctrine=new_faction.primary_doctrine,
                )
                record_observer_timeline_event(
                    advisor,
                    current_time,
                    "faction",
                    f"Faction {faction.id} split into F{new_faction.id}",
                    f"{len(split_members)} members broke away under doctrine {new_faction.primary_doctrine}.",
                )

    def apply_autonomous_pressure(self, thronglets, advisor, world_map, world_width, world_height, current_time):
        for faction in self.factions.values():
            members = faction.get_members(thronglets)
            if len(members) < 2:
                continue

            if (
                not faction.shared_goals
                or current_time - getattr(faction, "last_doctrine_goal_time", 0.0) >= 32.0
            ):
                doctrine_goal = AUTONOMOUS_DOCTRINE_GOALS.get(faction.primary_doctrine)
                if doctrine_goal:
                    faction.assign_shared_goal(doctrine_goal, "Autonomous doctrine pressure", faction.primary_doctrine)
                    faction.last_doctrine_goal_time = current_time

            if faction.migration_pressure < FACTION_DYNAMICS["migration_pressure_threshold"]:
                continue
            if current_time - getattr(faction, "last_migration_time", 0.0) < FACTION_DYNAMICS["migration_cooldown_seconds"]:
                continue

            member_snapshots = [
                {
                    "known_resources": list(getattr(member, "known_resources", [])),
                }
                for member in members
            ]
            target = choose_migration_target(
                faction.get_centroid(thronglets),
                member_snapshots,
                faction.primary_doctrine,
                world_width,
                world_height,
                faction.migration_pressure,
                world_map=world_map,
            )
            if not target:
                continue

            faction.migration_target = target
            faction.last_migration_time = current_time
            eligible_members = [
                member
                for member in members
                if member.needs["hunger"] > 50 and member.needs["energy"] > 50 and not member.diseased
            ]
            eligible_members.sort(
                key=lambda member: (
                    0 if member.role == "explorer" else 1,
                    distance_between(member.x, member.y, target[0], target[1]),
                    member.id,
                )
            )
            assigned = 0
            for member in eligible_members:
                existing_reason = str((member.personal_goal or {}).get("reason", ""))
                if member.personal_goal and "Faction migration" not in existing_reason and current_time - getattr(member, "goal_assigned_time", 0.0) < 18.0:
                    continue
                member.personal_goal = {
                    "type": "migrate",
                    "target": {"x": round(target[0], 2), "y": round(target[1], 2)},
                    "reason": f"Faction migration toward {faction.primary_doctrine} frontier",
                }
                member.goal_assigned_time = current_time
                assigned += 1
                if assigned >= min(3, len(eligible_members)):
                    break

            if assigned and advisor is not None:
                advisor.session_stats["migration_events"] = advisor.session_stats.get("migration_events", 0) + 1
                self._record_faction_history(
                    advisor,
                    current_time,
                    "migration",
                    faction_id=faction.id,
                    members=assigned,
                    doctrine=faction.primary_doctrine,
                    target={"x": round(target[0], 1), "y": round(target[1], 1)},
                )
                record_observer_timeline_event(
                    advisor,
                    current_time,
                    "migration",
                    f"Faction {faction.id} shifted toward a new frontier",
                    f"{assigned} members moving toward ({int(target[0])}, {int(target[1])}).",
                )
    
    def get_faction(self, faction_id):
        """Get faction by ID"""
        return self.factions.get(faction_id)
    
    def get_faction_for_thronglet(self, thronglet_id):
        """Get faction containing this thronglet"""
        for faction in self.factions.values():
            if thronglet_id in faction.member_ids:
                return faction
        return None


class Thronglet:
    """A cute AI-powered creature"""
    _next_id = 0  # Class variable to track unique IDs
    
    def __init__(self, x, y):
        self.id = Thronglet._next_id
        Thronglet._next_id += 1
        self.x = x
        self.y = y
        self.vx = 0
        self.vy = 0
        self.inventory = {'food': 0, 'wood': 0, 'stone': 0}
        
        # Needs system (0-100, decrease over time)
        self.needs = {
            'hunger': random.uniform(60, 100),
            'energy': random.uniform(60, 100),
            'thirst': random.uniform(60, 100),
        }
        
        # Personality traits (0-1, affect behavior)
        self.personality = {
            'curiosity': random.uniform(0, 1),
            'sociability': random.uniform(0, 1),
            'diligence': random.uniform(0, 1),
        }
        self.genetics = random_genetic_profile()
        self.favorite_biome = random.choice(BIOME_TYPES)
        self.resilience = random.uniform(0.85, 1.15)
        self.morale = random.uniform(58, 88)
        self.inspiration = random.uniform(10, 30)
        self.settlement_prosperity = 0.5
        self.generation = 0
        self.parent_ids = []
        self.lineage_id = self.id
        self.mutation_count = 0
        self.birth_origin = "founder"
        
        # Role (assigned by self-selection)
        self.role = None  # Will be assigned: "gatherer", "builder", "explorer"
        
        # Last decision change time for wander behavior
        self.last_action_time = time.time()
        self.action_duration = random.uniform(1, 3)  # Change action every 1-3 seconds (shorter for more responsiveness)
        
        # Reproduction tracking
        self.last_reproduction_time = 0
        self.reproduction_message = None
        self.reproduction_message_time = 0
        
        self.current_action = "wander"
        self.build_message = None
        self.build_message_time = 0
        self.next_build_location = None  # (x, y) for city planner placement
        
        # New: Health & Lifespan
        self.health = 100.0
        self.age = 0.0
        self.birth_time = time.time()
        self.alive = True
        
        # New: Skills
        self.skills = {
            'gathering': {'level': 1, 'xp': 0},
            'building': {'level': 1, 'xp': 0},
            'exploring': {'level': 1, 'xp': 0}
        }
        
        # New: Social
        self.bonds = {}  # {thronglet_id: bond_strength}
        self.faction_id = None  # ID of faction this thronglet belongs to
        self.happiness = random.uniform(70, 100)
        
        # New: Disease
        self.diseased = False
        self.disease_start_time = 0
        
        # New: Memory
        self.known_resources = []  # Positions of discovered resources
        
        # Encounter exploration tracking
        self.exploring_encounter = None
        self.exploration_start_time = 0
        self.exploration_duration = 3.0  # 3 seconds to explore
        
        # NPC interaction tracking
        self.interacting_npc = None
        self.interaction_start_time = 0
        self.interaction_duration = 5.0  # 5 seconds to interact
        
        # Personal goals (assigned by LLM or self-generated)
        self.personal_goal = None  # {'type': 'explore', 'target': (x,y), 'reason': 'LLM guidance'}
        self.goal_progress = 0.0  # 0-1, completion percentage
        self.goal_assigned_time = 0
        
        # Resource gathering timer
        self.gathering_resource = None  # Currently gathering this resource
        self.gathering_start_time = 0  # When gathering started
        
        # Building resource gathering tracking
        self.building_resource_goal = None  # {'wood': 5, 'stone': 0} - how much we need for building directive
        
        # State Machine
        self.state = STATE_IDLE
        self.state_history = []  # Track state transitions for debugging
        self.state_entry_time = time.time()  # When current state was entered
        self.previous_state = None
        
        # Failure learning
        self.failure_memory = {}  # {action_type: failure_count}
        
        # Q-Learning
        self.q_table = {}  # {(state, action): q_value}
        self.last_action = None  # Track last action for Q-learning updates
        self.last_state = None  # Track last state for Q-learning updates
        self.success_memory = {}  # {action_type: success_count}
        
        # Behavior Tree (initialized after all attributes are set)
        self.behavior_tree = None  # Will be initialized after all attributes are ready
        
        # Pathfinding
        self.path = []  # List of waypoints for navigation
        self.current_waypoint_index = 0
        
        # Behavior Tree - lazy initialization in decide_action()
        self.behavior_tree = None
    
    def draw(self, surface):
        """Draw the thronglet with motion, morale, and biome identity."""
        if self.role == 'gatherer':
            body_color = GATHERER_COLOR
        elif self.role == 'builder':
            body_color = BUILDER_COLOR
        elif self.role == 'explorer':
            body_color = EXPLORER_COLOR
        else:
            body_color = YELLOW

        draw_x = self.x
        draw_y = self.y + math.sin(time.time() * (6 if abs(self.vx) + abs(self.vy) > 0.2 else 2) + self.id) * 1.2
        morale_factor = clamp((self.morale - 40) / 60.0, 0.0, 1.0)
        body_color = blend_color(body_color, WHITE, morale_factor * 0.18)
        biome_badge_colors = {
            'forest': GRASS_DARK,
            'plains': GRASS_LIGHT,
            'mountains': ROCK_DARK,
            'desert': DESERT_SAND,
            'snow': SNOW_WHITE,
            'swamp': SWAMP_DARK,
            'taiga': TAIGA_GREEN,
            'tundra': ICE_BLUE,
        }

        if self.inspiration > 45 or self.morale > 72:
            aura_radius = THRONGLET_RADIUS + 5 + int(self.inspiration / 30)
            aura_color = GOLD if self.inspiration > 60 else CYAN
            aura_surface = pygame.Surface((aura_radius * 2 + 8, aura_radius * 2 + 8), pygame.SRCALPHA)
            pygame.draw.circle(
                aura_surface,
                (*aura_color, 45 + int(self.morale)),
                (aura_radius + 4, aura_radius + 4),
                aura_radius,
                2,
            )
            surface.blit(aura_surface, (int(draw_x - aura_radius - 4), int(draw_y - aura_radius - 4)))

        shadow_offset = 3
        shadow_surface = pygame.Surface((THRONGLET_RADIUS * 2 + 4, THRONGLET_RADIUS * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(shadow_surface, (0, 0, 0, 100), (THRONGLET_RADIUS + 2, THRONGLET_RADIUS + 2), THRONGLET_RADIUS)
        surface.blit(shadow_surface, (int(draw_x - THRONGLET_RADIUS - 2 + shadow_offset), int(draw_y - THRONGLET_RADIUS - 1 + shadow_offset)))

        pygame.draw.circle(surface, BLACK, (int(draw_x), int(draw_y)), THRONGLET_RADIUS + 1)
        pygame.draw.circle(surface, body_color, (int(draw_x), int(draw_y)), THRONGLET_RADIUS)
        pygame.draw.circle(surface, blend_color(body_color, WHITE, 0.25), (int(draw_x - 1), int(draw_y - 2)), max(2, THRONGLET_RADIUS - 3))

        pants_width = int(THRONGLET_RADIUS * 0.8)
        pants_height = int(THRONGLET_RADIUS * 0.5)
        pants_rect = pygame.Rect(int(draw_x - pants_width // 2), int(draw_y + THRONGLET_RADIUS // 2), pants_width, pants_height)
        pygame.draw.rect(surface, BLACK, (pants_rect.x - 1, pants_rect.y - 1, pants_rect.width + 2, pants_rect.height + 2))
        pygame.draw.rect(surface, BLUE, pants_rect)

        eye_size = 3
        eye_offset_x = int(THRONGLET_RADIUS * 0.35)
        eye_offset_y = -int(THRONGLET_RADIUS * 0.2)
        pygame.draw.circle(surface, WHITE, (int(draw_x - eye_offset_x), int(draw_y + eye_offset_y)), eye_size + 1)
        pygame.draw.circle(surface, BLACK, (int(draw_x - eye_offset_x), int(draw_y + eye_offset_y)), eye_size)
        pygame.draw.circle(surface, WHITE, (int(draw_x + eye_offset_x), int(draw_y + eye_offset_y)), eye_size + 1)
        pygame.draw.circle(surface, BLACK, (int(draw_x + eye_offset_x), int(draw_y + eye_offset_y)), eye_size)

        smile_color = RED_ACCENT if self.morale < 35 else BLACK
        pygame.draw.arc(surface, smile_color, (int(draw_x - 4), int(draw_y - 1), 8, 6), 0.2, 2.9, 1)

        badge_color = biome_badge_colors.get(self.favorite_biome, WHITE)
        pygame.draw.circle(surface, BLACK, (int(draw_x + THRONGLET_RADIUS + 2), int(draw_y - THRONGLET_RADIUS + 2)), 4)
        pygame.draw.circle(surface, badge_color, (int(draw_x + THRONGLET_RADIUS + 2), int(draw_y - THRONGLET_RADIUS + 2)), 3)
        if self.generation > 0:
            generation_color = GOLD if self.generation >= 3 else (180, 220, 255)
            pygame.draw.circle(surface, generation_color, (int(draw_x - THRONGLET_RADIUS - 2), int(draw_y - THRONGLET_RADIUS + 2)), 4, 1)

        if DEBUG_SHOW_INVENTORY_TEXT:
            total_inv = self.inventory['food'] + self.inventory['wood'] + self.inventory['stone']
            if total_inv > 0:
                inv_text = font_small.render(f"F{self.inventory['food']}W{self.inventory['wood']}S{self.inventory['stone']}", True, BLACK)
                surface.blit(inv_text, (int(draw_x + THRONGLET_RADIUS + 2), int(draw_y - 8)))

        bar_width = 30
        bar_height = 3
        y_offset = -35

        pygame.draw.rect(surface, (150, 150, 150), (int(draw_x - bar_width//2 - 1), int(draw_y + y_offset - 1), bar_width + 2, bar_height + 2))
        pygame.draw.rect(surface, (100, 0, 0), (int(draw_x - bar_width//2), int(draw_y + y_offset), bar_width, bar_height))
        hunger_fill = int(bar_width * self.needs['hunger'] / 100)
        pygame.draw.rect(surface, RED, (int(draw_x - bar_width//2), int(draw_y + y_offset), hunger_fill, bar_height))

        pygame.draw.rect(surface, (150, 150, 150), (int(draw_x - bar_width//2 - 1), int(draw_y + y_offset + 4), bar_width + 2, bar_height + 2))
        pygame.draw.rect(surface, (0, 0, 100), (int(draw_x - bar_width//2), int(draw_y + y_offset + 5), bar_width, bar_height))
        energy_fill = int(bar_width * self.needs['energy'] / 100)
        pygame.draw.rect(surface, BLUE, (int(draw_x - bar_width//2), int(draw_y + y_offset + 5), energy_fill, bar_height))

        pygame.draw.rect(surface, (150, 150, 150), (int(draw_x - bar_width//2 - 1), int(draw_y + y_offset + 9), bar_width + 2, bar_height + 2))
        pygame.draw.rect(surface, (0, 50, 50), (int(draw_x - bar_width//2), int(draw_y + y_offset + 10), bar_width, bar_height))
        thirst_fill = int(bar_width * self.needs['thirst'] / 100)
        pygame.draw.rect(surface, CYAN, (int(draw_x - bar_width//2), int(draw_y + y_offset + 10), thirst_fill, bar_height))

        pygame.draw.rect(surface, (150, 150, 150), (int(draw_x - bar_width//2 - 1), int(draw_y + y_offset + 14), bar_width + 2, bar_height + 2))
        pygame.draw.rect(surface, (100, 100, 100), (int(draw_x - bar_width//2), int(draw_y + y_offset + 15), bar_width, bar_height))
        health_fill = int(bar_width * self.health / 100)
        health_color = GRASS_LIGHT if self.health > 50 else (YELLOW if self.health > 25 else RED)
        pygame.draw.rect(surface, health_color, (int(draw_x - bar_width//2), int(draw_y + y_offset + 15), health_fill, bar_height))

        speed = math.sqrt(self.vx**2 + self.vy**2)
        if speed > 0.5:
            arrow_length = 10
            arrow_angle = math.atan2(self.vy, self.vx)
            arrow_x = int(draw_x + math.cos(arrow_angle) * (THRONGLET_RADIUS + 6))
            arrow_y = int(draw_y + math.sin(arrow_angle) * (THRONGLET_RADIUS + 6))
            arrow_points = [
                (arrow_x, arrow_y),
                (arrow_x - math.cos(arrow_angle - 0.4) * arrow_length, arrow_y - math.sin(arrow_angle - 0.4) * arrow_length),
                (arrow_x - math.cos(arrow_angle + 0.4) * arrow_length, arrow_y - math.sin(arrow_angle + 0.4) * arrow_length)
            ]
            outer_points = [
                (p[0] + (1 if p[0] > arrow_x else -1 if p[0] < arrow_x else 0), 
                 p[1] + (1 if p[1] > arrow_y else -1 if p[1] < arrow_y else 0))
                for p in arrow_points
            ]
            pygame.draw.polygon(surface, (0, 0, 0), outer_points)
            pygame.draw.polygon(surface, (255, 255, 255), arrow_points)

        if self.diseased:
            pulse = int(3 + 2 * math.sin(time.time() * 5))
            pygame.draw.circle(surface, RED, (int(draw_x), int(draw_y)), THRONGLET_RADIUS + pulse, 2)

        if hasattr(self, 'needs_decay_multiplier') and self.needs_decay_multiplier > 1.1:
            stress_surface = pygame.Surface((THRONGLET_RADIUS * 3, THRONGLET_RADIUS * 3), pygame.SRCALPHA)
            alpha = int(50 + 30 * math.sin(time.time() * 3))
            stress_surface.fill((255, 0, 0, alpha))
            surface.blit(stress_surface, (int(draw_x - THRONGLET_RADIUS * 1.5), int(draw_y - THRONGLET_RADIUS * 1.5)))

        skill_key = get_role_skill_key(self.role)
        if skill_key and skill_key in self.skills:
            badge_y = int(draw_y - THRONGLET_RADIUS - 15)
            badge_x = int(draw_x - 10)
            skill_level = self.skills[skill_key]['level']
            if skill_level >= 3:
                star_points = []
                for i in range(5):
                    angle = i * 2 * math.pi / 5 - math.pi / 2
                    if i % 2 == 0:
                        star_points.append((badge_x + 5 + int(8 * math.cos(angle)), badge_y + int(8 * math.sin(angle))))
                    else:
                        star_points.append((badge_x + 5 + int(4 * math.cos(angle)), badge_y + int(4 * math.sin(angle))))
                pygame.draw.polygon(surface, (255, 215, 0), star_points)
            elif skill_level >= 2:
                star_points = []
                for i in range(5):
                    angle = i * 2 * math.pi / 5 - math.pi / 2
                    if i % 2 == 0:
                        star_points.append((badge_x + 5 + int(6 * math.cos(angle)), badge_y + int(6 * math.sin(angle))))
                    else:
                        star_points.append((badge_x + 5 + int(3 * math.cos(angle)), badge_y + int(3 * math.sin(angle))))
                pygame.draw.polygon(surface, (192, 192, 192), star_points)

    def get_morale_focus_bonus(self):
        morale_bonus = max(0.0, self.morale - 50.0) / 50.0 * MORALE_SPEED_BONUS
        inspiration_bonus = (self.inspiration / 100.0) * INSPIRATION_SKILL_BONUS
        return 1.0 + morale_bonus + inspiration_bonus

    def apply_settlement_effects(self, settlement_state, delta_time, world_map=None, weather_effects=None, buildings=None):
        """Apply soft systemic bonuses from prosperity, district coverage, and biome affinity."""
        if not settlement_state:
            return

        current_biome = world_map.get_biome_at(self.x, self.y) if world_map else None
        weather_name = settlement_state.get("weather", "clear")

        nearby_house = False
        nearby_well = False
        nearby_shrine = False
        nearby_workshop = False
        if buildings:
            for building in buildings:
                if distance_between(self.x, self.y, building.x, building.y) > SETTLEMENT_AURA_RADIUS:
                    continue
                if building.building_type == "house":
                    nearby_house = True
                elif building.building_type == "well":
                    nearby_well = True
                elif building.building_type == "shrine":
                    nearby_shrine = True
                elif building.building_type == "workshop":
                    nearby_workshop = True

        morale_delta = (settlement_state.get("prosperity_score", 0.5) - 0.5) * 3.0 * delta_time
        morale_delta += (settlement_state.get("culture_score", 0.4) - 0.4) * 1.5 * delta_time

        if current_biome == self.favorite_biome:
            morale_delta += 1.0 * delta_time
        if nearby_house:
            morale_delta += 0.4 * delta_time
            self.needs["energy"] = min(100, self.needs["energy"] + 0.08 * delta_time)
        if nearby_well:
            morale_delta += 0.25 * delta_time
            self.needs["thirst"] = min(100, self.needs["thirst"] + 0.06 * delta_time)
        if nearby_shrine:
            morale_delta += 0.6 * delta_time
        if weather_name in ("storm", "drought"):
            morale_delta -= 0.9 * delta_time

        self.morale = clamp(self.morale + morale_delta, 0.0, 100.0)

        inspiration_delta = -0.18 * delta_time
        if nearby_shrine:
            inspiration_delta += 0.55 * delta_time
        if nearby_workshop:
            inspiration_delta += 0.35 * delta_time
        if current_biome == self.favorite_biome:
            inspiration_delta += 0.18 * delta_time
        self.inspiration = clamp(self.inspiration + inspiration_delta, 0.0, 100.0)
        self.settlement_prosperity = settlement_state.get("prosperity_score", 0.5)

    def update_position(self, modifiers=None, world_map=None, world_width=None, world_height=None, buildings=None, other_thronglets=None):
        """Move the thronglet and keep it within bounds with obstacle avoidance"""
        # Disease slows movement
        speed_mod = modifiers.get_modifier('thronglet_speed') if modifiers else 1.0
        speed_multiplier = (0.5 if self.diseased else 1.0) * speed_mod
        adaptability = getattr(self, "genetics", {}).get("adaptability", 1.0)
        
        # Apply gatherer speed bonus
        if self.role == 'gatherer':
            speed_multiplier *= GATHERER_SPEED_BONUS
        
        # Apply biome effects
        biome_mod = 1.0
        if world_map:
            biome_type = world_map.get_biome_at(self.x, self.y)
            biome_props = world_map.get_biome_properties(biome_type)
            biome_mod = biome_props.get('movement_speed', 1.0)
            if biome_type == self.favorite_biome:
                biome_mod *= 1.0 + FAVORITE_BIOME_SPEED_BONUS
            else:
                biome_mod = 1.0 + ((biome_mod - 1.0) / max(0.75, adaptability))
        
        speed_multiplier *= biome_mod * self.get_morale_focus_bonus()
        
        # Path following: if we have a path, follow waypoints
        if self.path and self.current_waypoint_index < len(self.path):
            waypoint = self.path[self.current_waypoint_index]
            dx = waypoint[0] - self.x
            dy = waypoint[1] - self.y
            distance = math.sqrt(dx**2 + dy**2)
            
            if distance < 10:  # Reached waypoint
                self.current_waypoint_index += 1
                if self.current_waypoint_index >= len(self.path):
                    self.path = []
                    self.current_waypoint_index = 0
            else:
                # Move toward waypoint
                if distance > 0:
                    self.vx = (dx / distance) * THRONGLET_SPEED
                    self.vy = (dy / distance) * THRONGLET_SPEED
        
        # Obstacle avoidance using steering behaviors
        if buildings or other_thronglets:
            avoidance_force_x, avoidance_force_y = self.avoid_obstacles(buildings or [], other_thronglets or [])
            self.vx += avoidance_force_x * 0.3  # Blend avoidance with desired direction
            self.vy += avoidance_force_y * 0.3
        
        self.x += self.vx * speed_multiplier
        self.y += self.vy * speed_multiplier
        
        # Boundary checking (use world dimensions if provided)
        if world_width and world_height:
            self.x = max(50, min(world_width - 50, self.x))
            self.y = max(50, min(world_height - 50, self.y))
        else:
            self.x = max(20, min(WINDOW_WIDTH - 20, self.x))
            self.y = max(20, min(WINDOW_HEIGHT - 20, self.y))
    
    def get_workshop_bonus(self, buildings, modifiers):
        """Get gathering bonus from nearby workshops"""
        if not modifiers:
            return 1.0
        
        workshop_bonus_modifier = modifiers.get_modifier('workshop_bonus')
        if workshop_bonus_modifier <= 1.0:
            return 1.0
        
        # Count nearby workshops within 150 pixels
        num_workshops = 0
        for building in buildings:
            if building.building_type == 'workshop':
                distance = math.sqrt((building.x - self.x)**2 + (building.y - self.y)**2)
                if distance < 100:  # Adjusted for smaller sprites
                    num_workshops += 1
        
        if num_workshops == 0:
            return 1.0
        
        # Apply diminishing returns: 1.0 + (num_workshops * 0.2 * modifier)
        # With 1 workshop at 1.25 modifier: 1.0 + 1*0.2*1.25 = 1.25x
        # With 2 workshops: 1.0 + 2*0.2*1.25 = 1.5x
        bonus = 1.0 + (num_workshops * 0.2 * workshop_bonus_modifier)
        return bonus
    
    def get_gathering_bonus(self):
        """Get gathering skill bonus based on level"""
        if 'gathering' in self.skills:
            level = self.skills['gathering']['level']
            return (1.0 + (level - 1) * SKILL_BONUS_PER_LEVEL) * self.get_morale_focus_bonus()
        return 1.0
    
    def get_building_bonus(self):
        """Get building skill bonus based on level"""
        if 'building' in self.skills:
            level = self.skills['building']['level']
            return (1.0 + (level - 1) * SKILL_BONUS_PER_LEVEL) * self.get_morale_focus_bonus()
        return 1.0
    
    def get_exploration_bonus(self):
        """Get exploration skill bonus based on level"""
        if 'exploring' in self.skills:
            level = self.skills['exploring']['level']
            return (1.0 + (level - 1) * SKILL_BONUS_PER_LEVEL) * self.get_morale_focus_bonus()
        return 1.0
    
    def calculate_pooled_resources(self, other_thronglets):
        """Calculate available resources from self + nearby thronglets within sharing radius"""
        available_wood = self.inventory.get('wood', 0)
        available_stone = self.inventory.get('stone', 0)
        
        if other_thronglets:
            try:
                for other in other_thronglets:
                    if other is None or not hasattr(other, 'id') or not hasattr(other, 'x') or not hasattr(other, 'y'):
                        continue
                    if other.id == self.id:
                        continue
                    if not hasattr(other, 'inventory'):
                        continue
                    
                    distance = math.sqrt((other.x - self.x)**2 + (other.y - self.y)**2)
                    if distance < RESOURCE_SHARING_RADIUS:
                        available_wood += other.inventory.get('wood', 0)
                        available_stone += other.inventory.get('stone', 0)
            except (AttributeError, TypeError, KeyError) as e:
                # If there's any error, just return self's resources
                pass
        
        return available_wood, available_stone
    
    def consume_pooled_resources(self, required_wood, required_stone, other_thronglets):
        """Consume resources: take from self first, then borrow from nearby thronglets
        Returns True if successfully consumed, False if insufficient"""
        # First calculate if we have enough
        available_wood, available_stone = self.calculate_pooled_resources(other_thronglets)
        
        if available_wood < required_wood or available_stone < required_stone:
            return False
        
        # Take from self first
        self_wood = self.inventory.get('wood', 0)
        self_stone = self.inventory.get('stone', 0)
        wood_taken_from_self = min(required_wood, self_wood)
        stone_taken_from_self = min(required_stone, self_stone)
        
        self.inventory['wood'] = self_wood - wood_taken_from_self
        self.inventory['stone'] = self_stone - stone_taken_from_self
        
        # Calculate remaining needed
        wood_needed = required_wood - wood_taken_from_self
        stone_needed = required_stone - stone_taken_from_self
        
        # Borrow remaining from nearby thronglets (nearest first)
        if wood_needed > 0 or stone_needed > 0:
            # Sort nearby thronglets by distance
            nearby_thronglets = []
            if other_thronglets:
                try:
                    for other in other_thronglets:
                        if other is None or not hasattr(other, 'id') or not hasattr(other, 'x') or not hasattr(other, 'y'):
                            continue
                        if not hasattr(other, 'inventory'):
                            continue
                        if other.id == self.id:
                            continue
                        
                        distance = math.sqrt((other.x - self.x)**2 + (other.y - self.y)**2)
                        if distance < RESOURCE_SHARING_RADIUS:
                            nearby_thronglets.append((distance, other))
                except (AttributeError, TypeError) as e:
                    # If error finding nearby thronglets, just use self's resources
                    pass
            
            # Sort by distance (nearest first)
            nearby_thronglets.sort(key=lambda x: x[0])
            
            # Borrow resources from nearest thronglets
            # Double-check we don't include self and that objects are still valid
            for distance, other in nearby_thronglets:
                # Safety check - make sure this isn't self and object is still valid
                if other is None or other is self:
                    continue
                if not hasattr(other, 'inventory') or not hasattr(other, 'id'):
                    continue
                if other.id == self.id:
                    continue
                try:
                    if wood_needed > 0 and other.inventory.get('wood', 0) > 0:
                        take = min(wood_needed, other.inventory['wood'])
                        other.inventory['wood'] -= take
                        wood_needed -= take
                    
                    if stone_needed > 0 and other.inventory.get('stone', 0) > 0:
                        take = min(stone_needed, other.inventory['stone'])
                        other.inventory['stone'] -= take
                        stone_needed -= take
                    
                    if wood_needed <= 0 and stone_needed <= 0:
                        break
                except (AttributeError, KeyError, TypeError) as e:
                    # Skip this thronglet if there's an error accessing its inventory
                    continue
        
        return True
    
    def find_nearest_resource(self, resources, resource_type=None, max_distance=None):
        """Find the nearest resource matching criteria"""
        closest = None
        min_distance = float('inf')
        
        for resource in resources:
            if not resource.collected:
                # Filter by type if specified
                if resource_type and resource.resource_type != resource_type:
                    continue
                
                distance = math.sqrt((resource.x - self.x)**2 + (resource.y - self.y)**2)
                
                # Check max_distance if specified
                if max_distance and distance > max_distance:
                    continue
                
                if distance < min_distance:
                    min_distance = distance
                    closest = resource
        
        return closest, min_distance if closest else None
    
    def calculate_path(self, target_x, target_y, buildings, world_width, world_height, other_thronglets=None):
        """Simple A* pathfinding to target, avoiding buildings"""
        import heapq
        
        # Grid size: 32x32 pixels per node
        GRID_SIZE = 32
        
        # Convert world coordinates to grid
        start_grid_x = int(self.x / GRID_SIZE)
        start_grid_y = int(self.y / GRID_SIZE)
        target_grid_x = int(target_x / GRID_SIZE)
        target_grid_y = int(target_y / GRID_SIZE)
        
        # Bounds checking
        max_grid_x = int(world_width / GRID_SIZE) if world_width else int(WINDOW_WIDTH / GRID_SIZE)
        max_grid_y = int(world_height / GRID_SIZE) if world_height else int(WINDOW_HEIGHT / GRID_SIZE)
        
        start_grid_x = max(0, min(max_grid_x - 1, start_grid_x))
        start_grid_y = max(0, min(max_grid_y - 1, start_grid_y))
        target_grid_x = max(0, min(max_grid_x - 1, target_grid_x))
        target_grid_y = max(0, min(max_grid_y - 1, target_grid_y))
        
        # Check if target is same as start
        if (start_grid_x, start_grid_y) == (target_grid_x, target_grid_y):
            return [(target_x, target_y)]
        
        # Check for obstacles (buildings) in grid cells
        def is_obstacle(grid_x, grid_y):
            world_x = grid_x * GRID_SIZE + GRID_SIZE // 2
            world_y = grid_y * GRID_SIZE + GRID_SIZE // 2
            for building in buildings:
                # Check if building overlaps with this grid cell
                if abs(building.x - world_x) < BUILDING_SIZE + GRID_SIZE // 2 and \
                   abs(building.y - world_y) < BUILDING_SIZE + GRID_SIZE // 2:
                    return True
            return False
        
        # A* pathfinding
        open_set = [(0, start_grid_x, start_grid_y)]
        came_from = {}
        g_score = {(start_grid_x, start_grid_y): 0}
        f_score = {(start_grid_x, start_grid_y): abs(target_grid_x - start_grid_x) + abs(target_grid_y - start_grid_y)}
        
        # 8-directional movement
        directions = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        
        while open_set:
            current_f, current_x, current_y = heapq.heappop(open_set)
            
            if (current_x, current_y) == (target_grid_x, target_grid_y):
                # Reconstruct path
                path = []
                current = (target_grid_x, target_grid_y)
                while current in came_from:
                    grid_x, grid_y = current
                    world_x = grid_x * GRID_SIZE + GRID_SIZE // 2
                    world_y = grid_y * GRID_SIZE + GRID_SIZE // 2
                    path.append((world_x, world_y))
                    current = came_from[current]
                # Add start position
                path.append((self.x, self.y))
                path.reverse()
                # Add exact target
                path.append((target_x, target_y))
                return path
            
            for dx, dy in directions:
                neighbor_x = current_x + dx
                neighbor_y = current_y + dy
                
                if neighbor_x < 0 or neighbor_x >= max_grid_x or neighbor_y < 0 or neighbor_y >= max_grid_y:
                    continue
                
                if is_obstacle(neighbor_x, neighbor_y):
                    continue
                
                # Distance cost (1 for cardinal, 1.4 for diagonal)
                move_cost = 1.4 if abs(dx) + abs(dy) == 2 else 1.0
                tentative_g = g_score.get((current_x, current_y), float('inf')) + move_cost
                
                if tentative_g < g_score.get((neighbor_x, neighbor_y), float('inf')):
                    came_from[(neighbor_x, neighbor_y)] = (current_x, current_y)
                    g_score[(neighbor_x, neighbor_y)] = tentative_g
                    h_score = abs(target_grid_x - neighbor_x) + abs(target_grid_y - neighbor_y)
                    f_score[(neighbor_x, neighbor_y)] = tentative_g + h_score
                    heapq.heappush(open_set, (f_score[(neighbor_x, neighbor_y)], neighbor_x, neighbor_y))
        
        # No path found, return direct path
        path = [(target_x, target_y)]
        
        # Apply Boids forces to path if other thronglets are nearby (for multi-waypoint paths)
        if other_thronglets and len(path) > 1:
            boids_cohesion, boids_separation = self.get_boids_forces(other_thronglets, cohesion_radius=100)
            if boids_cohesion[0] != 0 or boids_cohesion[1] != 0 or boids_separation[0] != 0 or boids_separation[1] != 0:
                # Blend Boids forces into path (slight adjustment)
                adjusted_path = []
                for i, (px, py) in enumerate(path):
                    if i > 0 and i < len(path) - 1:  # Don't adjust start/end points
                        # Apply small Boids influence (10% strength to avoid oversteering)
                        adjustment_x = (boids_cohesion[0] + boids_separation[0]) * 0.1
                        adjustment_y = (boids_cohesion[1] + boids_separation[1]) * 0.1
                        adjusted_path.append((px + adjustment_x, py + adjustment_y))
                    else:
                        adjusted_path.append((px, py))
                path = adjusted_path
        
        return path
    
    def get_boids_forces(self, other_thronglets, cohesion_radius=100):
        """Calculate Boids forces (cohesion and separation) for group behavior"""
        cohesion_x = 0.0
        cohesion_y = 0.0
        separation_x = 0.0
        separation_y = 0.0
        
        nearby_count = 0
        separation_count = 0
        
        # Spatial partition: only check thronglets within 200px for performance
        for other in other_thronglets:
            if other == self:
                continue
            
            dx = other.x - self.x
            dy = other.y - self.y
            distance = math.sqrt(dx**2 + dy**2)
            
            if distance < 200:  # Performance optimization
                # Cohesion: move toward center of nearby thronglets
                if distance < cohesion_radius and distance > 0:
                    cohesion_x += dx / distance
                    cohesion_y += dy / distance
                    nearby_count += 1
                
                # Separation: avoid crowding (enhanced existing avoid_obstacles logic)
                if distance < THRONGLET_RADIUS * 4 and distance > 0:
                    separation_strength = (THRONGLET_RADIUS * 4 - distance) / (THRONGLET_RADIUS * 4)
                    separation_x -= (dx / distance) * separation_strength
                    separation_y -= (dy / distance) * separation_strength
                    separation_count += 1
        
        # Normalize cohesion (average direction toward nearby thronglets)
        if nearby_count > 0:
            cohesion_x /= nearby_count
            cohesion_y /= nearby_count
            # Normalize
            mag = math.sqrt(cohesion_x**2 + cohesion_y**2)
            if mag > 0:
                cohesion_x /= mag
                cohesion_y /= mag
        
        # Normalize separation
        if separation_count > 0:
            mag = math.sqrt(separation_x**2 + separation_y**2)
            if mag > 0:
                separation_x /= mag
                separation_y /= mag
        
        return (cohesion_x, cohesion_y), (separation_x, separation_y)
    
    def avoid_obstacles(self, buildings, other_thronglets):
        """Calculate steering force to avoid obstacles"""
        avoidance_x = 0.0
        avoidance_y = 0.0
        
        # Avoid buildings
        for building in buildings:
            dx = self.x - building.x
            dy = self.y - building.y
            distance = math.sqrt(dx**2 + dy**2)
            if distance < BUILDING_SIZE + THRONGLET_RADIUS * 3:
                # Separation force (stronger when closer)
                if distance > 0:
                    strength = (BUILDING_SIZE + THRONGLET_RADIUS * 3 - distance) / (BUILDING_SIZE + THRONGLET_RADIUS * 3)
                    avoidance_x += (dx / distance) * strength
                    avoidance_y += (dy / distance) * strength
        
        # Avoid other thronglets
        for other in other_thronglets:
            if other == self:
                continue
            dx = self.x - other.x
            dy = self.y - other.y
            distance = math.sqrt(dx**2 + dy**2)
            if distance < THRONGLET_RADIUS * 4 and distance > 0:
                # Separation force
                strength = (THRONGLET_RADIUS * 4 - distance) / (THRONGLET_RADIUS * 4)
                avoidance_x += (dx / distance) * strength * 0.5
                avoidance_y += (dy / distance) * strength * 0.5
        
        # Normalize avoidance force
        avoidance_mag = math.sqrt(avoidance_x**2 + avoidance_y**2)
        if avoidance_mag > 0:
            avoidance_x /= avoidance_mag
            avoidance_y /= avoidance_mag
        
        return avoidance_x, avoidance_y
    
    def predict_outcome(self, action_type, target, resources, buildings, delta_time):
        """Predict feasibility and outcome of an action"""
        score = 0.0
        
        if action_type == 'gather':
            if target:
                distance = math.sqrt((target.x - self.x)**2 + (target.y - self.y)**2)
                # Score based on distance (closer = better)
                distance_score = max(0, 1.0 - (distance / 200))
                
                # Check if resource still available
                availability = 1.0 if not target.collected else 0.0
                
                # Predict energy/hunger depletion
                travel_time = distance / THRONGLET_SPEED if THRONGLET_SPEED > 0 else 10
                predicted_energy = self.needs['energy'] - (0.021 * travel_time)
                predicted_hunger = self.needs['hunger'] - (0.035 * travel_time)
                
                # Penalize if prediction suggests needs will be too low
                needs_penalty = 0.0
                if predicted_energy < 30:
                    needs_penalty += 0.3
                if predicted_hunger < 30:
                    needs_penalty += 0.3
                
                score = distance_score * availability * (1.0 - needs_penalty)
        
        elif action_type == 'build':
            if target:  # target is building type string
                # Check resource availability
                required_wood = 4  # Default
                required_stone = 0
                if target == 'farm':
                    required_wood = 5
                elif target == 'well':
                    required_stone = 3
                    required_wood = 0
                
                has_resources = 1.0 if (self.inventory['wood'] >= required_wood and self.inventory['stone'] >= required_stone) else 0.0
                
                # Check skill match
                skill_bonus = 1.0
                if self.role == 'builder':
                    skill_bonus = 1.2
                
                score = has_resources * skill_bonus
        
        elif action_type == 'explore':
            # Exploration is always somewhat feasible
            curiosity_bonus = self.personality.get('curiosity', 0.5)
            energy_score = self.needs['energy'] / 100.0
            score = curiosity_bonus * energy_score
        
        return max(0.0, min(1.0, score))
    
    def record_failure(self, action_type):
        """Record a failed action for learning"""
        if action_type not in self.failure_memory:
            self.failure_memory[action_type] = 0
        self.failure_memory[action_type] += 1
        
        # Update Q-learning with negative reward
        if self.last_state and self.last_action:
            reward = -5  # Failure penalty
            current_state = self._get_state_tuple([], [])  # Use empty lists, not None
            self.update_q_value(self.last_state, self.last_action, reward, current_state)
    
    def get_failure_rate(self, action_type):
        """Get failure rate for an action type"""
        if action_type not in self.failure_memory:
            return 0.0
        # Simple rate: failures / (failures + 10) - caps at ~0.5 for high failures
        failures = self.failure_memory[action_type]
        return min(0.5, failures / (failures + 10))
    
    def _get_state_tuple(self, resources, buildings):
        """Convert current state to tuple for Q-table key"""
        # State = (needs_tuple, role, nearby_resources_count)
        needs_tuple = (
            int(self.needs['hunger'] / 20),  # Quantize to 0-5
            int(self.needs['energy'] / 20),  # Quantize to 0-5
            int(self.needs['thirst'] / 20)   # Quantize to 0-5
        )
        role_value = {'gatherer': 0, 'builder': 1, 'explorer': 2}.get(self.role, 3)
        
        # Count nearby resources (within 100px)
        nearby_count = 0
        if resources:
            for resource in resources:
                if not resource.collected:
                    distance = math.sqrt((resource.x - self.x)**2 + (resource.y - self.y)**2)
                    if distance < 100:
                        nearby_count += 1
        nearby_count = min(5, nearby_count)  # Cap at 5
        
        return (needs_tuple, role_value, nearby_count)
    
    def get_q_value(self, state, action):
        """Get Q-value for state-action pair"""
        key = (state, action)
        return self.q_table.get(key, 0.0)
    
    def update_q_value(self, state, action, reward, next_state):
        """Update Q-value using Q-learning formula"""
        # Q(s,a) = Q(s,a) + alpha * (reward + gamma * max_future_Q - Q(s,a))
        current_q = self.get_q_value(state, action)
        
        # Calculate max future Q-value
        max_future_q = 0.0
        if next_state:
            # Get all possible actions and find max Q
            possible_actions = ['gather_food', 'gather_wood', 'gather_stone', 'build_house', 'build_farm', 'build_storage', 'explore', 'rest']
            max_future_q = max([self.get_q_value(next_state, a) for a in possible_actions], default=0.0)
        
        # Q-learning update
        new_q = current_q + Q_LEARNING_ALPHA * (reward + Q_LEARNING_GAMMA * max_future_q - current_q)
        
        # Limit Q-table size (LRU eviction if needed)
        if len(self.q_table) >= Q_TABLE_MAX_SIZE and (state, action) not in self.q_table:
            # Remove lowest value entry
            if self.q_table:
                min_key = min(self.q_table.items(), key=lambda x: x[1])[0]
                del self.q_table[min_key]
        
        self.q_table[(state, action)] = new_q
    
    def get_best_q_action(self, state, possible_actions):
        """Get best action according to Q-table"""
        best_action = None
        best_q = float('-inf')
        
        for action in possible_actions:
            q_value = self.get_q_value(state, action)
            if q_value > best_q:
                best_q = q_value
                best_action = action
        
        return best_action if best_action else (possible_actions[0] if possible_actions else None)
    
    def get_bonded_thronglets_on_directive(self, directive, other_thronglets):
        """Get list of bonded thronglets working on the same directive"""
        if not other_thronglets or not directive:
            return []
        
        bonded_list = []
        directive_action = directive.get('action', '').lower()
        
        for other in other_thronglets:
            if other == self:
                continue
            
            # Check if bond > 50
            bond_strength = self.bonds.get(other.id, 0)
            if bond_strength > 50:
                # Check if other thronglet is working on similar directive
                other_action = other.current_action or ""
                if (directive_action in other_action or 
                    any(keyword in other_action.lower() for keyword in directive_action.split() if len(keyword) > 3)):
                    bonded_list.append(other)
        
        return bonded_list
    
    def record_success(self, action_type):
        """Record a successful action for learning"""
        if action_type not in self.success_memory:
            self.success_memory[action_type] = 0
        self.success_memory[action_type] += 1
        
        # Update Q-learning if we have last state/action
        if self.last_state and self.last_action:
            reward = 10  # Success reward
            current_state = self._get_state_tuple([], [])  # Use empty lists, not None
            self.update_q_value(self.last_state, self.last_action, reward, current_state)
    
    def transition_to_state(self, new_state):
        """Transition to a new state with logging"""
        if new_state != self.state:
            self.previous_state = self.state
            self.state = new_state
            self.state_entry_time = time.time()
            self.state_history.append({
                'state': new_state,
                'time': time.time(),
                'previous': self.previous_state
            })
            # Keep only last 10 state transitions
            if len(self.state_history) > 10:
                self.state_history.pop(0)
            if VERBOSE_LOGGING:
                print(f"[Thronglet {self.id}] State transition: {self.previous_state} -> {new_state}")
    
    def decide_action(self, resources, buildings, delta_time, directives=None, is_night=False, other_thronglets=None, group_tasks=None, conditional_behaviors=None, territory_manager=None, city_planner=None, hazards=None, world_map=None):
        """Autonomous decision-making based on needs and personality using state machine and behavior tree"""
        # If currently gathering, don't decide a new action
        if self.gathering_resource is not None:
            return None
        
        # Lazy initialize behavior tree if needed
        if self.behavior_tree is None:
            try:
                self.behavior_tree = BehaviorTree(self)
            except NameError:
                # BehaviorTree class not available yet, skip BT logic
                pass
        
        # Execute behavior tree if available (provides state suggestions)
        if self.behavior_tree:
            context = {
                'directives': directives,
                'group_tasks': group_tasks,
                'resources': resources,
                'buildings': buildings,
                'other_thronglets': other_thronglets,
                'is_night': is_night,
                'delta_time': delta_time,
                'territory_manager': territory_manager,
                'city_planner': city_planner,
                'hazards': hazards,
                'world_map': world_map
            }
            try:
                self.behavior_tree.tick(context)
                # Behavior tree may have changed state, continue with FSM logic below
            except Exception as e:
                # Graceful degradation on error
                if VERBOSE_LOGGING:
                    print(f"[Thronglet {self.id}] Behavior tree error: {e}")
        
        # Check if we're gathering resources for a building directive and need to continue
        if self.building_resource_goal and self.state == STATE_EXECUTE_DIRECTIVE:
            # Check if we have enough resources now (including pooled)
            available_wood, available_stone = self.calculate_pooled_resources(other_thronglets if other_thronglets else [])
            needed_wood = max(0, self.building_resource_goal['wood'] - available_wood)
            needed_stone = max(0, self.building_resource_goal['stone'] - available_stone)
            
            # If we still need resources, continue gathering (don't exit directive state)
            if needed_wood > 0 or needed_stone > 0:
                # Continue gathering mode - find nearest needed resource
                if resources:
                    target_resource = None
                    target_distance = float('inf')
                    for resource in resources:
                        if not resource.collected:
                            if (needed_wood > 0 and resource.resource_type == 'wood') or \
                               (needed_stone > 0 and resource.resource_type == 'stone'):
                                distance = math.sqrt((resource.x - self.x)**2 + (resource.y - self.y)**2)
                                if distance < target_distance:
                                    target_distance = distance
                                    target_resource = resource
                    
                    if target_resource:
                        dx = target_resource.x - self.x
                        dy = target_resource.y - self.y
                        distance = math.sqrt(dx**2 + dy**2)
                        if distance > 0:
                            if distance > 100:
                                path = self.calculate_path(target_resource.x, target_resource.y, buildings if buildings else [], None, None, other_thronglets)
                                if len(path) > 1:
                                    self.path = path
                                    self.current_waypoint_index = 1
                                    waypoint = path[1]
                                    dx = waypoint[0] - self.x
                                    dy = waypoint[1] - self.y
                                    distance = math.sqrt(dx**2 + dy**2)
                            if distance > 0:
                                self.vx = (dx / distance) * THRONGLET_SPEED
                                self.vy = (dy / distance) * THRONGLET_SPEED
                                self.current_action = f"directive: gathering {target_resource.resource_type} for building ({needed_wood} wood, {needed_stone} stone needed)"
                                return None
            else:
                # We have enough resources, clear the goal so building can proceed
                self.building_resource_goal = None
        
        # Update needs decay (30% slower for better survival)
        decay_multiplier = getattr(self, 'needs_decay_multiplier', 1.0)
        metabolism_efficiency = getattr(self, "genetics", {}).get("metabolism_efficiency", 1.0)
        hunger_decay = 0.035 * decay_multiplier * delta_time  # Was 0.05
        self.needs['hunger'] = max(0, self.needs['hunger'] - (hunger_decay / max(0.75, metabolism_efficiency)))
        # Energy decays faster at night
        energy_decay_rate = 0.042 if is_night else 0.021  # Was 0.06/0.03
        self.needs['energy'] = max(
            0,
            self.needs['energy'] - ((energy_decay_rate * decay_multiplier * delta_time) / max(0.75, metabolism_efficiency)),
        )
        # Thirst decays over time (30% slower)
        thirst_decay = WATER_NEED_DECAY * 0.7  # 0.028 instead of 0.04
        self.needs['thirst'] = max(
            0,
            self.needs['thirst'] - ((thirst_decay * decay_multiplier * delta_time) / max(0.75, metabolism_efficiency)),
        )
        
        # Priority 0: Auto-eat if hungry and carrying food
        if self.needs['hunger'] < 70 and self.inventory['food'] > 0:
            # Consume food to restore hunger
            self.inventory['food'] -= 1
            self.needs['hunger'] = min(100, self.needs['hunger'] + 30)
            self.current_action = "eating"
            if VERBOSE_LOGGING:
                print(f"[Thronglet] Auto-ate food, hunger now: {self.needs['hunger']:.1f}")
        
        # State Machine Decision Logic - Priority Order: Needs > Directives > Traits > Wander
        # Check for critical needs first
        critical_hunger = self.needs['hunger'] < 30
        critical_energy = self.needs['energy'] < 30
        critical_thirst = self.needs['thirst'] < 40
        
        if critical_hunger or critical_energy or critical_thirst:
            self.transition_to_state(STATE_SEEK_NEED)
        
        # State Machine: Handle each state
        if self.state == STATE_SEEK_NEED:
            # Priority 1: Survival needs (hunger critical or moderate)
            if self.needs['hunger'] < 70:  # Extended to 70 from 30 for better farm harvesting
                # Try to find food (gather resources or farms)
                closest_resource = None
                closest_distance = float('inf')
                
                # Check wild food resources ONLY (not wood!)
                for resource in resources:
                    if not resource.collected and resource.resource_type == 'food':
                        distance = math.sqrt((resource.x - self.x)**2 + (resource.y - self.y)**2)
                        if distance < closest_distance:
                            closest_distance = distance
                            closest_resource = resource
                
                # Check farms with available food
                closest_farm = None
                closest_farm_distance = float('inf')
                for building in buildings:
                    if building.building_type == 'farm' and building.stored_resources['food'] > 0:
                        distance = math.sqrt((building.x - self.x)**2 + (building.y - self.y)**2)
                        if distance < closest_farm_distance:
                            closest_farm_distance = distance
                            closest_farm = building
                
                # Choose closest food source (check farms first if hunger < 70, then resources)
                target = None
                if self.needs['hunger'] < 70:
                    # Prioritize farms when moderately hungry for better food production
                    if closest_farm and closest_farm_distance:
                        target = closest_farm
                        closest_distance = closest_farm_distance
                    elif closest_resource:
                        target = closest_resource
                        closest_distance = closest_distance
                else:
                    # Critical hunger: check all sources
                    if closest_resource:
                        target = closest_resource
                        closest_distance = closest_distance
                    if closest_farm and (not target or closest_farm_distance < closest_distance):
                        target = closest_farm
                        closest_distance = closest_farm_distance
                
                # Only seek food if no distance limit OR if critical hunger
                if target and (self.needs['hunger'] < 30 or closest_distance < 200):
                    # Move toward food source
                    dx = target.x - self.x
                    dy = target.y - self.y
                    distance = math.sqrt(dx**2 + dy**2)
                    if distance > 0:
                        # Use pathfinding if target is far
                        if distance > 50:
                            path = self.calculate_path(target.x, target.y, buildings, None, None, other_thronglets)
                            if len(path) > 1:
                                self.path = path
                                self.current_waypoint_index = 1
                                # Move toward first waypoint
                                waypoint = path[1]
                                dx = waypoint[0] - self.x
                                dy = waypoint[1] - self.y
                                distance = math.sqrt(dx**2 + dy**2)
                                if distance > 0:
                                    self.vx = (dx / distance) * THRONGLET_SPEED
                                    self.vy = (dy / distance) * THRONGLET_SPEED
                                    self.current_action = "seeking food (pathfinding)"
                                    return None
                        # Direct movement for close targets
                        self.vx = (dx / distance) * THRONGLET_SPEED
                        self.vy = (dy / distance) * THRONGLET_SPEED
                        self.current_action = "seeking food"
                        return None
            
            # Priority 2: Energy low - seek shelter to rest
            if self.needs['energy'] < 30:
                # Find nearest house
                closest_house = None
                closest_distance = float('inf')
                for building in buildings:
                    if building.building_type == 'house' and building.can_enter(self):
                        distance = math.sqrt((building.x - self.x)**2 + (building.y - self.y)**2)
                        if distance < closest_distance:
                            closest_distance = distance
                            closest_house = building
                
                if closest_house and closest_distance < 100:
                    # Move toward house
                    dx = closest_house.x - self.x
                    dy = closest_house.y - self.y
                    distance = math.sqrt(dx**2 + dy**2)
                    if distance > 0:
                        self.vx = (dx / distance) * THRONGLET_SPEED
                        self.vy = (dy / distance) * THRONGLET_SPEED
                        self.current_action = "seeking shelter"
                        self.transition_to_state(STATE_REST)
                        return None
                else:
                    # No house available, move slower
                    self.vx *= 0.5
                    self.vy *= 0.5
                    self.current_action = "tired"
            
            # Priority 2.1: Thirst - seek water at wells
            if self.needs['thirst'] < 40:
                closest_well = None
                closest_distance = float('inf')
                for building in buildings:
                    if building.building_type == 'well':
                        distance = math.sqrt((building.x - self.x)**2 + (building.y - self.y)**2)
                        if distance < closest_distance:
                            closest_distance = distance
                            closest_well = building
                
                if closest_well and closest_distance < 100:
                    dx = closest_well.x - self.x
                    dy = closest_well.y - self.y
                    distance = math.sqrt(dx**2 + dy**2)
                    if distance > 0:
                        self.vx = (dx / distance) * THRONGLET_SPEED
                        self.vy = (dy / distance) * THRONGLET_SPEED
                        self.current_action = "seeking water"
                        return None
            
            # If needs are met, exit SEEK_NEED state
            if self.needs['hunger'] > 70 and self.needs['energy'] > 50 and self.needs['thirst'] > 60:
                # Transition to next priority state
                if directives and self.needs['hunger'] > 50 and self.needs['energy'] > 50:
                    self.transition_to_state(STATE_EXECUTE_DIRECTIVE)
                elif self.personality.get('sociability', 0) > 0.7 and len(self.bonds) < 3:
                    self.transition_to_state(STATE_SOCIALIZE)
                else:
                    self.transition_to_state(STATE_IDLE)
                return None
        
        # Q-Learning consultation (only when needs are good)
        q_learning_action = None
        if (self.needs['hunger'] > 70 and self.needs['energy'] > 70 and 
            self.needs['thirst'] > 60 and random.random() < Q_LEARNING_EPSILON):
            # 30% chance to use Q-learning when needs are met
            try:
                current_state = self._get_state_tuple(resources, buildings)
                possible_actions = []
                
                # Determine possible actions based on context
                if directives and len(directives) > 0:
                    # Map directive actions to Q-learning actions
                    for directive in directives:
                        action = directive['action'].lower()
                        if 'gather' in action or 'collect' in action:
                            if 'food' in action:
                                possible_actions.append('gather_food')
                            elif 'wood' in action:
                                possible_actions.append('gather_wood')
                            elif 'stone' in action:
                                possible_actions.append('gather_stone')
                            else:
                                possible_actions.append('gather_food')  # Default
                        elif 'build' in action:
                            if 'house' in action:
                                possible_actions.append('build_house')
                            elif 'farm' in action:
                                possible_actions.append('build_farm')
                            elif 'storage' in action:
                                possible_actions.append('build_storage')
                            else:
                                possible_actions.append('build_house')  # Default
                        elif 'explore' in action:
                            possible_actions.append('explore')
                
                # Fallback actions if no directives
                if not possible_actions:
                    possible_actions = ['gather_food', 'gather_wood', 'explore']
                
                # Get best Q-learning action
                best_q_action = self.get_best_q_action(current_state, possible_actions)
                if best_q_action:
                    q_learning_action = best_q_action
                    self.last_state = current_state
                    self.last_action = best_q_action
                    if VERBOSE_LOGGING:
                        print(f"[Thronglet {self.id}] Q-learning selected: {best_q_action}")
                    
                    # CRITICAL FIX: Apply Q-learning to directive priority
                    if directives:
                        q_action_words = best_q_action.replace('_', ' ').split()
                        for directive in directives:
                            action = directive['action'].lower()
                            if any(word in action for word in q_action_words if len(word) > 3):
                                directive['priority'] = directive.get('priority', 5) + 3
                                if VERBOSE_LOGGING:
                                    print(f"[Q-Learning] Boosted directive matching {best_q_action}")
            except Exception as e:
                # Graceful degradation
                if VERBOSE_LOGGING:
                    print(f"[Thronglet {self.id}] Q-learning error: {e}")
        
        # Priority 2: Execute directives if needs are met
        if self.state == STATE_EXECUTE_DIRECTIVE:
            # Only execute directives when explicitly in this state
            if directives and self.needs['hunger'] > 50 and self.needs['energy'] > 50:
                if VERBOSE_LOGGING and time.time() - getattr(self, '_last_directive_log', 0) > 2.0:
                    print(f"[Thronglet {self.id}] In EXECUTE_DIRECTIVE state, processing {len(directives)} directives")
                    self._last_directive_log = time.time()
                # Choose role if we don't have one
                if not self.role:
                    self.choose_role(directives)
                
                # Weight directives by bonds with other thronglets working on same task
                weighted_directives = []
                for directive in directives:
                    priority = directive['priority']
                    
                    # Check for bonded thronglets working on this directive
                    bonded_thronglets = self.get_bonded_thronglets_on_directive(directive, other_thronglets)
                    bond_bonus = 0
                    
                    if bonded_thronglets:
                        # Calculate average bond strength
                        avg_bond = sum(self.bonds.get(t.id, 0) for t in bonded_thronglets) / len(bonded_thronglets)
                        if avg_bond > 50:
                            # Increase priority by 2 for each bonded thronglet (capped at +6)
                            bond_bonus = min(6, len(bonded_thronglets) * 2)
                    
                    # Create weighted directive
                    weighted_directive = directive.copy()
                    weighted_directive['weighted_priority'] = priority + bond_bonus
                    weighted_directives.append(weighted_directive)
                
                # Sort directives by weighted priority
                sorted_directives = sorted(weighted_directives, key=lambda d: d['weighted_priority'], reverse=True)
                
                # Try to follow highest priority directive
                directive_executed = False
                for directive in sorted_directives:
                    # Apply morale/happiness bonus when working with bonded thronglets
                    bonded_thronglets = self.get_bonded_thronglets_on_directive(directive, other_thronglets)
                    if bonded_thronglets:
                        # Cohesion bonus: working with bonded thronglets increases happiness
                        self.happiness = min(100, self.happiness + 0.5)  # Small happiness boost
                    action = directive['action'].lower()
                    priority = directive['priority']
                    
                    # Check if directive matches current role
                    directive_matches_role = False
                    if self.role == 'gatherer' and ('gather' in action or 'collect' in action):
                        directive_matches_role = True
                    elif self.role == 'builder' and 'build' in action:
                        directive_matches_role = True
                    elif self.role == 'explorer' and ('explore' in action or 'scout' in action):
                        directive_matches_role = True
                    elif not self.role or priority >= 8:
                        directive_matches_role = True
                    
                    if not directive_matches_role and priority < 8:
                        continue
                    
                    # Handle gathering directive
                    if 'gather' in action or 'collect' in action:
                        # Check for multiple resource types in directive (e.g., "gather wood and stone")
                        desired_types = []
                        if 'wood' in action:
                            desired_types.append('wood')
                        if 'food' in action:
                            desired_types.append('food')
                        if 'stone' in action:
                            desired_types.append('stone')
                        
                        # If no specific types mentioned, gather any resource
                        if not desired_types:
                            desired_type = None
                        else:
                            desired_type = desired_types[0]  # Start with first mentioned
                        
                        closest_resource = None
                        closest_distance = float('inf')
                        
                        # Try to find closest resource of any desired type
                        for resource in resources:
                            if not resource.collected:
                                # Match any desired type, or any type if none specified
                                if desired_type is None or resource.resource_type in desired_types or resource.resource_type == desired_type:
                                    distance = math.sqrt((resource.x - self.x)**2 + (resource.y - self.y)**2)
                                    if distance < closest_distance:
                                        closest_distance = distance
                                        closest_resource = resource
                        
                        # Execute gathering directive if resource is found (even if far)
                        if closest_resource:
                            dx = closest_resource.x - self.x
                            dy = closest_resource.y - self.y
                            distance = math.sqrt(dx**2 + dy**2)
                            if distance > 0:
                                # Use pathfinding for distant resources, direct movement for close ones
                                if distance > 100:
                                    path = self.calculate_path(closest_resource.x, closest_resource.y, buildings if buildings else [], None, None, other_thronglets)
                                    if len(path) > 1:
                                        self.path = path
                                        self.current_waypoint_index = 1
                                        waypoint = path[1]
                                        dx = waypoint[0] - self.x
                                        dy = waypoint[1] - self.y
                                        distance = math.sqrt(dx**2 + dy**2)
                                        if distance > 0:
                                            self.vx = (dx / distance) * THRONGLET_SPEED
                                            self.vy = (dy / distance) * THRONGLET_SPEED
                                            resource_type_name = closest_resource.resource_type
                                            self.current_action = f"directive: moving to {resource_type_name}"
                                            directive_executed = True
                                            return None
                                # Direct movement for close resources
                                self.vx = (dx / distance) * THRONGLET_SPEED
                                self.vy = (dy / distance) * THRONGLET_SPEED
                                resource_type_name = closest_resource.resource_type if closest_resource else (desired_type if desired_type else 'resources')
                                self.current_action = f"directive: gather {resource_type_name}"
                                directive_executed = True
                                return None
                    
                    # Handle building directive
                    elif 'build' in action:
                        building_type = None
                        if 'farm' in action:
                            building_type = 'farm'
                        elif 'storage' in action:
                            building_type = 'storage'
                        elif 'house' in action:
                            building_type = 'house'
                        elif 'workshop' in action:
                            building_type = 'workshop'
                        elif 'shrine' in action:
                            building_type = 'shrine'
                        elif 'well' in action:
                            building_type = 'well'
                        
                        if building_type:
                            base_wood, base_stone = get_building_cost(building_type)
                            building_bonus = self.get_building_bonus()
                            builder_discount = BUILDER_COST_REDUCTION if self.role == 'builder' else 1.0
                            required_wood = 0 if base_wood <= 0 else max(1, int(base_wood * builder_discount / building_bonus))
                            required_stone = 0 if base_stone <= 0 else max(1, int(base_stone * builder_discount / building_bonus))
                            
                            # Use city planner to find best location if available
                            if city_planner and hazards is not None:
                                best_x, best_y, score = city_planner.find_best_location(
                                    building_type, buildings, hazards, 
                                    (self.x, self.y), search_radius=150
                                )
                                
                                # Apply soft penalty if outside territory
                                if territory_manager and not territory_manager.is_claimed(best_x, best_y, threshold=40):
                                    required_wood = int(required_wood * 1.3)  # 30% cost increase
                                    required_stone = int(required_stone * 1.3)
                                
                                # Check if we have enough resources with potential penalty (using pooled resources)
                                available_wood, available_stone = self.calculate_pooled_resources(other_thronglets)
                                if available_wood >= required_wood and available_stone >= required_stone:
                                    # Move to best location if not already there
                                    distance_to_location = math.sqrt((best_x - self.x)**2 + (best_y - self.y)**2)
                                    if distance_to_location > 10:
                                        # Pathfind to location
                                        path = self.calculate_path(best_x, best_y, buildings, None, None, other_thronglets)
                                        if len(path) > 1:
                                            self.path = path
                                            self.current_waypoint_index = 1
                                            self.current_action = "directive: moving to build location"
                                            return None
                                    
                                    # At location, build (consume pooled resources)
                                    self.vx = 0
                                    self.vy = 0
                                    self.current_action = "directive: build"
                                    if self.consume_pooled_resources(required_wood, required_stone, other_thronglets):
                                        self.build_message = f"Built {building_type}! ({int(best_x)}, {int(best_y)})"
                                        self.build_message_time = time.time()
                                        self.next_build_location = (best_x, best_y)
                                        # Clear building resource goal since we successfully built
                                        self.building_resource_goal = None
                                        directive_executed = True
                                        return building_type
                                else:
                                    # Not enough resources - try to gather what's needed first
                                    wood_needed = max(0, required_wood - available_wood)
                                    stone_needed = max(0, required_stone - available_stone)
                                    
                                    if wood_needed > 0 or stone_needed > 0:
                                        # Find closest resource of needed type
                                        target_resource = None
                                        target_distance = float('inf')
                                        for resource in resources:
                                            if not resource.collected:
                                                if (wood_needed > 0 and resource.resource_type == 'wood') or \
                                                   (stone_needed > 0 and resource.resource_type == 'stone'):
                                                    distance = math.sqrt((resource.x - self.x)**2 + (resource.y - self.y)**2)
                                                    if distance < target_distance:
                                                        target_distance = distance
                                                        target_resource = resource
                                        
                                        if target_resource:
                                            dx = target_resource.x - self.x
                                            dy = target_resource.y - self.y
                                            distance = math.sqrt(dx**2 + dy**2)
                                            if distance > 0:
                                                if distance > 100:
                                                    path = self.calculate_path(target_resource.x, target_resource.y, buildings if buildings else [], None, None, other_thronglets)
                                                    if len(path) > 1:
                                                        self.path = path
                                                        self.current_waypoint_index = 1
                                                        waypoint = path[1]
                                                        dx = waypoint[0] - self.x
                                                        dy = waypoint[1] - self.y
                                                        distance = math.sqrt(dx**2 + dy**2)
                                                if distance > 0:
                                                    self.vx = (dx / distance) * THRONGLET_SPEED
                                                    self.vy = (dy / distance) * THRONGLET_SPEED
                                                    self.current_action = f"directive: gathering {target_resource.resource_type} for building"
                                                    directive_executed = True
                                                    return None
                                    
                                    if VERBOSE_LOGGING:
                                        print(f"[Thronglet {self.id}] Building directive (city planner) requires {required_wood} wood, {required_stone} stone. Available: {available_wood}, {available_stone}")
                            else:
                                # No city planner, use old logic (build at current location)
                                # Check pooled resources instead of individual inventory
                                available_wood, available_stone = self.calculate_pooled_resources(other_thronglets)
                                if available_wood >= required_wood and available_stone >= required_stone:
                                    self.vx = 0
                                    self.vy = 0
                                    self.current_action = "directive: build"
                                    # Consume pooled resources (from self + nearby allies)
                                    if self.consume_pooled_resources(required_wood, required_stone, other_thronglets):
                                        self.build_message = f"Built {building_type}! ({int(self.x)}, {int(self.y)})"
                                        self.build_message_time = time.time()
                                        # Clear building resource goal since we successfully built
                                        self.building_resource_goal = None
                                        directive_executed = True
                                        return building_type
                                else:
                                    # Not enough resources - try to gather what's needed first
                                    # Check what we need to gather
                                    wood_needed = max(0, required_wood - available_wood)
                                    stone_needed = max(0, required_stone - available_stone)
                                    
                                    # Set building resource goal so we persist in gathering mode
                                    self.building_resource_goal = {'wood': required_wood, 'stone': required_stone}
                                    
                                    # If we need resources, temporarily switch to gathering mode
                                    if wood_needed > 0 or stone_needed > 0:
                                        # Find closest resource of needed type
                                        target_resource = None
                                        target_distance = float('inf')
                                        for resource in resources:
                                            if not resource.collected:
                                                # Prioritize wood if we need it more, otherwise stone
                                                resource_priority = 0
                                                if wood_needed > 0 and resource.resource_type == 'wood':
                                                    resource_priority = 10 - (wood_needed - (required_wood - available_wood))
                                                elif stone_needed > 0 and resource.resource_type == 'stone':
                                                    resource_priority = 10 - (stone_needed - (required_stone - available_stone))
                                                
                                                if resource_priority > 0:
                                                    distance = math.sqrt((resource.x - self.x)**2 + (resource.y - self.y)**2)
                                                    # Prefer closer resources, but also consider priority
                                                    adjusted_distance = distance - (resource_priority * 10)
                                                    if adjusted_distance < target_distance:
                                                        target_distance = adjusted_distance
                                                        target_resource = resource
                                        
                                        if target_resource:
                                            # Move toward needed resource
                                            dx = target_resource.x - self.x
                                            dy = target_resource.y - self.y
                                            distance = math.sqrt(dx**2 + dy**2)
                                            if distance > 0:
                                                if distance > 100:
                                                    path = self.calculate_path(target_resource.x, target_resource.y, buildings if buildings else [], None, None, other_thronglets)
                                                    if len(path) > 1:
                                                        self.path = path
                                                        self.current_waypoint_index = 1
                                                        waypoint = path[1]
                                                        dx = waypoint[0] - self.x
                                                        dy = waypoint[1] - self.y
                                                        distance = math.sqrt(dx**2 + dy**2)
                                                if distance > 0:
                                                    self.vx = (dx / distance) * THRONGLET_SPEED
                                                    self.vy = (dy / distance) * THRONGLET_SPEED
                                                    self.current_action = f"directive: gathering {target_resource.resource_type} for building ({required_wood - available_wood} wood, {required_stone - available_stone} stone needed)"
                                                    directive_executed = True
                                                    return None
                                    
                                    if VERBOSE_LOGGING:
                                        print(f"[Thronglet {self.id}] Building directive requires {required_wood} wood, {required_stone} stone. Available: {available_wood}, {available_stone}")
                
                    # Handle explore/scout directive
                    elif 'explore' in action or 'scout' in action:
                        # Determine direction if specified
                        direction = None
                        if 'north' in action or 'up' in action:
                            direction = 'north'
                            # Check if already at boundary (y near 0) - if so, explore perpendicular
                            if self.y < 100:
                                # At north boundary, explore east/west instead
                                direction = 'east' if random.random() > 0.5 else 'west'
                                self.vx = THRONGLET_SPEED if direction == 'east' else -THRONGLET_SPEED
                                self.vy = 0
                            else:
                                self.vy = -THRONGLET_SPEED
                                self.vx = 0
                        elif 'south' in action or 'down' in action:
                            direction = 'south'
                            self.vy = THRONGLET_SPEED
                            self.vx = 0
                        elif 'east' in action or 'right' in action:
                            direction = 'east'
                            self.vx = THRONGLET_SPEED
                            self.vy = 0
                        elif 'west' in action or 'left' in action:
                            direction = 'west'
                            self.vx = -THRONGLET_SPEED
                            self.vy = 0
                        else:
                            # No specific direction, use random exploration
                            self.set_random_direction()
                        
                        self.current_action = f"directive: {direction if direction else 'exploring'}"
                        self.transition_to_state(STATE_EXPLORE)
                        directive_executed = True
                        return None
                
                # If no directive was executed, transition to idle
                if not directive_executed:
                    if VERBOSE_LOGGING:
                        print(f"[Thronglet {self.id}] No directive executed. Directives: {len(directives)}, Role: {self.role}")
                    self.transition_to_state(STATE_IDLE)
        
        # Priority 1.5: Follow personal goal if assigned (only if no directives)
        # Directives take priority over personal goals
        if self.personal_goal and not directives and self.needs['hunger'] > 50 and self.needs['energy'] > 50:
            goal_type = self.personal_goal.get('type', '')

            if goal_type == 'migrate':
                target = self.personal_goal.get('target')
                target_x = target.get('x') if isinstance(target, dict) else (target[0] if isinstance(target, (list, tuple)) and len(target) == 2 else None)
                target_y = target.get('y') if isinstance(target, dict) else (target[1] if isinstance(target, (list, tuple)) and len(target) == 2 else None)
                if target_x is not None and target_y is not None:
                    dx = float(target_x) - self.x
                    dy = float(target_y) - self.y
                    distance = math.sqrt(dx**2 + dy**2)
                    if distance <= 36:
                        self.goal_progress = 1.0
                        self.current_action = "holding migration frontier"
                        self.personal_goal = None
                    elif distance > 0:
                        self.goal_progress = clamp(1.0 - (distance / 400.0), 0.0, 0.95)
                        self.vx = (dx / distance) * THRONGLET_SPEED
                        self.vy = (dy / distance) * THRONGLET_SPEED
                        self.current_action = "goal: migrating"
                        return None
            
            # Handle exploration goals
            if goal_type.startswith('explore_'):
                if 'north' in goal_type:
                    self.vy = -THRONGLET_SPEED
                    self.current_action = "exploring north"
                elif 'east' in goal_type:
                    self.vx = THRONGLET_SPEED
                    self.current_action = "exploring east"
                elif 'south' in goal_type:
                    self.vy = THRONGLET_SPEED
                    self.current_action = "exploring south"
                elif 'west' in goal_type:
                    self.vx = -THRONGLET_SPEED
                    self.current_action = "exploring west"
                return None
            
            # Handle gathering goals
            elif 'gather_' in goal_type:
                target_type = goal_type.replace('gather_', '')
                if target_type in ['food', 'wood', 'stone']:
                    closest, distance = self.find_nearest_resource(resources, target_type, 200)
                    if closest and distance:
                        dx = closest.x - self.x
                        dy = closest.y - self.y
                        if distance > 0:
                            self.vx = (dx / distance) * THRONGLET_SPEED
                            self.vy = (dy / distance) * THRONGLET_SPEED
                            self.current_action = f"goal: gathering {target_type}"
                            return None
            
            # Handle building goals
            elif 'build_' in goal_type:
                # Will be handled by directive system
                pass
            
            # Handle rest goal
            elif goal_type == 'rest':
                closest_house = None
                for building in buildings:
                    if building.building_type == 'house' and building.can_enter(self):
                        distance = math.sqrt((building.x - self.x)**2 + (building.y - self.y)**2)
                        if not closest_house or distance < math.sqrt((closest_house.x - self.x)**2 + (closest_house.y - self.y)**2):
                            closest_house = building
                if closest_house:
                    dx = closest_house.x - self.x
                    dy = closest_house.y - self.y
                    distance = math.sqrt(dx**2 + dy**2)
                    if distance > 0:
                        self.vx = (dx / distance) * THRONGLET_SPEED
                        self.vy = (dy / distance) * THRONGLET_SPEED
                        self.current_action = "goal: resting"
                        return None
            
            # Handle reproduce goal (seeking mate)
            elif goal_type == 'reproduce' and other_thronglets:
                if self.can_reproduce():
                    closest_mate = None
                    closest_distance = float('inf')
                    for other in other_thronglets:
                        if other != self and other.can_reproduce():
                            distance = math.sqrt((other.x - self.x)**2 + (other.y - self.y)**2)
                            if distance < closest_distance:
                                closest_distance = distance
                                closest_mate = other
                    
                    if closest_mate and closest_distance < 200:
                        dx = closest_mate.x - self.x
                        dy = closest_mate.y - self.y
                        if closest_distance > REPRODUCTION_PROXIMITY:
                            distance = math.sqrt(dx**2 + dy**2)
                            if distance > 0:
                                self.vx = (dx / distance) * THRONGLET_SPEED
                                self.vy = (dy / distance) * THRONGLET_SPEED
                                self.current_action = "goal: seeking mate"
                                return None
        # Priority 3: Claim tile state (low priority for explorers)
        if self.state == STATE_CLAIM_TILE:
            # Explorers wander toward unclaimed areas
            if territory_manager:
                bounds = territory_manager.get_territory_bounds()
                if bounds:
                    # Check if we're outside claimed territory
                    if not territory_manager.is_claimed(self.x, self.y, threshold=40):
                        # Wander toward unclaimed tiles
                        wander_time = time.time() - self.state_entry_time
                        if wander_time < 5.0:  # Claim for 5 seconds
                            self.set_random_direction()
                            self.current_action = "claiming territory"
                            return None
                    
            # Done claiming, transition to idle
            self.transition_to_state(STATE_IDLE)
        
        # Priority 3.3: Rest state - exit if directives arrive or energy restored
        if self.state == STATE_REST:
            # Check if we should exit rest for directives
            if directives and self.needs['energy'] > 70 and self.needs['hunger'] > 50:
                self.transition_to_state(STATE_EXECUTE_DIRECTIVE)
                return None
            # Exit rest if energy is fully restored
            if self.needs['energy'] > 90:
                self.transition_to_state(STATE_IDLE)
        
        # Priority 3.5: Socialize state
        if self.state == STATE_SOCIALIZE:
            if self.personality.get('sociability', 0) > 0.7 and len(self.bonds) < 3:
                # Find nearby thronglets to socialize with
                if other_thronglets:
                    closest_friend = None
                    closest_distance = float('inf')
                    for other in other_thronglets:
                        if other != self:
                            distance = math.sqrt((other.x - self.x)**2 + (other.y - self.y)**2)
                            if distance < closest_distance and distance < 100:
                                closest_distance = distance
                                closest_friend = other
                    
                    if closest_friend:
                        dx = closest_friend.x - self.x
                        dy = closest_friend.y - self.y
                        distance = math.sqrt(dx**2 + dy**2)
                        if distance > 0:
                            self.vx = (dx / distance) * THRONGLET_SPEED * 0.5
                            self.vy = (dy / distance) * THRONGLET_SPEED * 0.5
                            self.current_action = "socializing"
                            return None
                # If no friends nearby, transition to idle
                self.transition_to_state(STATE_IDLE)
            else:
                self.transition_to_state(STATE_IDLE)
        
        # Priority 4: Idle state (wander/explore)
        if self.state == STATE_IDLE or self.state == STATE_EXPLORE:
            # Check if we should transition to execute directive when directives are available
            if directives and self.needs['hunger'] > 50 and self.needs['energy'] > 50:
                if VERBOSE_LOGGING:
                    print(f"[Thronglet {self.id}] Transitioning to EXECUTE_DIRECTIVE from {self.state}, {len(directives)} directives available")
                self.transition_to_state(STATE_EXECUTE_DIRECTIVE)
                return None
        
        # Default: Smart exploration or wander
        if time.time() - self.last_action_time > self.action_duration:
            # Check if explorer should claim territory
            if self.role == 'explorer' and territory_manager and self.needs['hunger'] > 50 and self.needs['energy'] > 50:
                bounds = territory_manager.get_territory_bounds()
                if bounds:
                    # Check if we're at territory edge or outside
                    if not territory_manager.is_claimed(self.x, self.y, threshold=40):
                        self.transition_to_state(STATE_CLAIM_TILE)
                        self.last_action_time = time.time()
                        self.action_duration = 5.0  # Will claim for 5 seconds
                        return None
            
            # First check if any resources nearby
            target, distance = self.find_nearest_resource(resources, None, 150)
            if target and distance:
                # Move toward resource instead of random wander
                dx = target.x - self.x
                dy = target.y - self.y
                if distance > 0:
                    self.vx = (dx / distance) * THRONGLET_SPEED
                    self.vy = (dy / distance) * THRONGLET_SPEED
                    self.current_action = f"moving toward {target.resource_type}"
                    self.last_action_time = time.time()
                    self.action_duration = random.uniform(1, 3)
                    return None
            else:
                # No resources nearby, wander randomly
                self.set_random_direction()
                self.last_action_time = time.time()
                self.action_duration = random.uniform(1, 3)
                # Higher curiosity means more frequent direction changes
                if self.personality['curiosity'] > 0.7:
                    self.action_duration *= 0.7
        
        # Apply Boids forces to velocity when not pathfinding (direct movement)
        # This ensures cohesion even when moving directly without A* pathfinding
        # Only apply when needs are met (don't interfere with critical survival)
        if (self.needs['hunger'] > 50 and self.needs['energy'] > 50) and \
           (not hasattr(self, 'path') or not self.path or len(self.path) <= 1) and \
           other_thronglets:
            try:
                boids_cohesion, boids_separation = self.get_boids_forces(other_thronglets, cohesion_radius=100)
                # Apply as steering force (5% influence to avoid oversteering)
                if abs(boids_cohesion[0]) > 0.1 or abs(boids_cohesion[1]) > 0.1 or \
                   abs(boids_separation[0]) > 0.1 or abs(boids_separation[1]) > 0.1:
                    steering_x = (boids_cohesion[0] + boids_separation[0]) * 0.05
                    steering_y = (boids_cohesion[1] + boids_separation[1]) * 0.05
                    # Blend with existing velocity (normalize to maintain speed)
                    total_vx = self.vx + steering_x
                    total_vy = self.vy + steering_y
                    speed = math.sqrt(total_vx**2 + total_vy**2)
                    if speed > 0:
                        # Maintain original speed, apply Boids as direction adjustment
                        self.vx = (total_vx / speed) * abs(self.vx) if self.vx != 0 else steering_x * 0.5
                        self.vy = (total_vy / speed) * abs(self.vy) if self.vy != 0 else steering_y * 0.5
            except Exception as e:
                # Graceful degradation
                if VERBOSE_LOGGING:
                    print(f"[Thronglet {self.id}] Boids error: {e}")
        
        return None
    
    def choose_role(self, directives):
        """Self-select role based on personality, skills, and civilization needs"""
        if self.role:  # Already have a role
            return
        
        # Determine best role based on personality
        scores = {
            'gatherer': self.personality['diligence'],
            'builder': self.personality['diligence'] * 0.7 + self.personality['sociability'] * 0.3,
            'explorer': self.personality['curiosity']
        }
        
        # Boost scores based on skill levels
        if 'gathering' in self.skills:
            scores['gatherer'] += self.skills['gathering']['level'] * 0.2
        if 'building' in self.skills:
            scores['builder'] += self.skills['building']['level'] * 0.2
        if 'exploring' in self.skills:
            scores['explorer'] += self.skills['exploring']['level'] * 0.2
        
        # Adjust scores based on directives
        for directive in directives:
            action = directive['action'].lower()
            priority = directive['priority'] / 10.0
            
            if 'gather' in action or 'collect' in action:
                scores['gatherer'] += priority
            elif 'build' in action:
                scores['builder'] += priority
            elif 'explore' in action:
                scores['explorer'] += priority
        
        # Penalize roles with high failure rates
        for role in ['gatherer', 'builder', 'explorer']:
            failure_rate = self.get_failure_rate(role)
            scores[role] *= (1.0 - failure_rate * 0.3)  # Up to 30% penalty
        
        # Choose role with highest score
        self.role = max(scores, key=scores.get)
        print(f"Thronglet {self.id} chose role: {self.role} (scores: {scores})")
    
    def can_reproduce(self):
        """Check if this thronglet can reproduce"""
        # Check cooldown
        fertility_drive = getattr(self, "genetics", {}).get("fertility_drive", 1.0)
        effective_cooldown = REPRODUCTION_COOLDOWN / max(0.75, fertility_drive)
        if time.time() - self.last_reproduction_time < effective_cooldown:
            return False
        # Check needs threshold
        if self.needs['hunger'] < REPRODUCTION_NEEDS_THRESHOLD or self.needs['energy'] < REPRODUCTION_NEEDS_THRESHOLD or self.needs['thirst'] < REPRODUCTION_NEEDS_THRESHOLD:
            return False
        # Diseased thronglets can't reproduce
        if self.diseased:
            return False
        # Unhappy thronglets won't reproduce
        if self.happiness < 50:
            return False
        return True
    
    @staticmethod
    def create_offspring(parent1, parent2, x, y):
        """Create a new thronglet with inherited traits from both parents"""
        child = Thronglet(x, y)
        
        # Inherit averaged personality traits with mutation
        child.personality = {
            'curiosity': max(0, min(1, (parent1.personality['curiosity'] + parent2.personality['curiosity']) / 2 + random.uniform(-0.1, 0.1))),
            'sociability': max(0, min(1, (parent1.personality['sociability'] + parent2.personality['sociability']) / 2 + random.uniform(-0.1, 0.1))),
            'diligence': max(0, min(1, (parent1.personality['diligence'] + parent2.personality['diligence']) / 2 + random.uniform(-0.1, 0.1))),
        }
        child.genetics, inherited_mutations = inherit_genetic_profile(parent1, parent2)
        
        # Set high initial needs
        child.needs = {
            'hunger': random.uniform(80, 100),
            'energy': random.uniform(80, 100),
            'thirst': random.uniform(80, 100),
        }
        child.favorite_biome = random.choice([parent1.favorite_biome, parent2.favorite_biome])
        child.resilience = clamp((parent1.resilience + parent2.resilience) / 2 + random.uniform(-0.05, 0.05), 0.8, 1.2)
        child.morale = clamp((parent1.morale + parent2.morale) / 2 + random.uniform(-8, 8), 45, 95)
        child.inspiration = clamp((parent1.inspiration + parent2.inspiration) / 2 + random.uniform(-6, 6), 5, 70)
        child.generation = max(getattr(parent1, "generation", 0), getattr(parent2, "generation", 0)) + 1
        child.parent_ids = [parent1.id, parent2.id]
        child.lineage_id = min(getattr(parent1, "lineage_id", parent1.id), getattr(parent2, "lineage_id", parent2.id))
        child.mutation_count = inherited_mutations
        child.birth_origin = "offspring"
        
        return child
    
    def update_age_and_health(self, delta_time, modifiers=None):
        """Age thronglet and decay health from unmet needs"""
        # Age the thronglet
        self.age = time.time() - self.birth_time
        decay_scale = 1.0 / max(0.75, self.resilience)
        
        # Check for natural death from age
        if self.age >= THRONGLET_MAX_AGE:
            return False  # Should die
        
        # Decay health based on unmet needs
        if self.needs['hunger'] < 30:
            self.health -= HEALTH_DECAY_BASE * 3 * delta_time * decay_scale
        elif self.needs['hunger'] < 50:
            self.health -= HEALTH_DECAY_BASE * 1.5 * delta_time * decay_scale
        
        if self.needs['energy'] < 30:
            self.health -= HEALTH_DECAY_BASE * 2 * delta_time * decay_scale
        
        if self.needs['thirst'] < 30:
            self.health -= HEALTH_DECAY_BASE * 2.5 * delta_time * decay_scale
        
        # Disease causes health loss
        if self.diseased:
            self.health -= HEALTH_DECAY_BASE * 5 * delta_time * decay_scale
        
        # Health regeneration from medicine techs
        health_regen = modifiers.get_modifier('health_regen') if modifiers else 0
        if health_regen > 0 and self.health < 100 and not self.diseased:
            self.health += health_regen * delta_time * 0.1
        if self.morale > 70 and not self.diseased:
            self.health += 0.015 * delta_time * self.resilience
        
        # Clamp health
        self.health = max(0, min(100, self.health))
        
        # Die if health reaches 0
        if self.health <= 0:
            return False
        
        return True  # Still alive
    
    def gain_skill_xp(self, skill_type, amount):
        """Level up skills"""
        if skill_type in self.skills:
            learning_affinity = getattr(self, "genetics", {}).get("learning_affinity", 1.0)
            self.skills[skill_type]['xp'] += amount * learning_affinity
            
            # Check for level up
            if self.skills[skill_type]['xp'] >= SKILL_LEVEL_THRESHOLD * self.skills[skill_type]['level']:
                self.skills[skill_type]['level'] += 1
                self.skills[skill_type]['xp'] = 0
                print(f"Thronglet leveled up {skill_type} to level {self.skills[skill_type]['level']}!")
    
    def update_bonds(self, other_thronglets, delta_time, modifiers=None):
        """Build/decay relationships"""
        # Create a set of alive thronglet IDs for reference checking
        alive_ids = {t.id for t in other_thronglets}
        social_cohesion = getattr(self, "genetics", {}).get("social_cohesion", 1.0)
        
        # Decay all existing bonds
        bond_decay_mod = modifiers.get_modifier('bond_decay') if modifiers else 1.0
        for thronglet_id in list(self.bonds.keys()):
            # Remove bonds to dead thronglets
            if thronglet_id not in alive_ids:
                del self.bonds[thronglet_id]
                continue
            self.bonds[thronglet_id] -= (BOND_DECAY_RATE * bond_decay_mod * delta_time) / max(0.75, social_cohesion)
            if self.bonds[thronglet_id] <= 0:
                del self.bonds[thronglet_id]
        
        # Build bonds with nearby thronglets
        for other in other_thronglets:
            if other == self:
                continue
            
            distance = math.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)
            if distance < 30:  # Within bonding range (adjusted for smaller sprites)
                if other.id not in self.bonds:
                    self.bonds[other.id] = 0
                other_social = getattr(other, "genetics", {}).get("social_cohesion", 1.0)
                bond_gain = BOND_INCREASE_RATE * delta_time * ((social_cohesion + other_social) / 2.0)
                self.bonds[other.id] += bond_gain
                self.bonds[other.id] = min(100, self.bonds[other.id])  # Cap at 100
    
    def update_happiness(self, buildings, other_thronglets, modifiers=None, world_map=None):
        """Calculate happiness based on various factors"""
        base_happiness = 40
        if modifiers:
            base_happiness = int(40 * modifiers.get_modifier('happiness_base'))
        happiness = base_happiness
        
        # Social bonds boost happiness
        if self.bonds:
            avg_bond = sum(self.bonds.values()) / len(self.bonds)
            happiness += avg_bond * 0.2
        happiness += (getattr(self, "genetics", {}).get("social_cohesion", 1.0) - 1.0) * 18
        
        # Good health boosts happiness (capped contribution)
        health_bonus = min(30, self.health / 2)
        happiness += health_bonus
        
        # Needs met boosts happiness
        if self.needs['hunger'] > 70 and self.needs['energy'] > 70 and self.needs['thirst'] > 70:
            happiness += 10
        
        # Nearby friends boost happiness
        alive_ids = {t.id for t in other_thronglets}
        friend_count = sum(1 for friend_id in self.bonds if friend_id in alive_ids and self.bonds[friend_id] > 50)
        happiness += friend_count * 5
        
        # Disease reduces happiness
        if self.diseased:
            happiness -= 30

        happiness += (self.morale - 50) * 0.32
        happiness += self.inspiration * 0.08
        happiness += (self.settlement_prosperity - 0.5) * 18
        
        # Access to shrine boosts happiness
        for building in buildings:
            distance = math.sqrt((building.x - self.x)**2 + (building.y - self.y)**2)
            if distance >= 60:
                continue
            if building.building_type == 'shrine':
                happiness += 6 + getattr(building, 'level', 1)
                break
            if building.building_type == 'house':
                happiness += 4
            elif building.building_type == 'well':
                happiness += 3
            elif building.building_type == 'workshop' and self.role == 'builder':
                happiness += 4
        
        # Apply biome comfort bonus
        if world_map:
            biome_type = world_map.get_biome_at(self.x, self.y)
            biome_props = world_map.get_biome_properties(biome_type)
            comfort_bonus = biome_props.get('comfort_bonus', 1.0)
            happiness *= comfort_bonus
            if biome_type == self.favorite_biome:
                happiness += 8
        
        # Clamp happiness
        self.happiness = max(0, min(100, happiness))
    
    def contract_disease(self, chance):
        """Disease mechanics"""
        immune_strength = getattr(self, "genetics", {}).get("immune_strength", 1.0)
        if not self.diseased and random.random() < (chance / max(0.65, immune_strength)):
            self.diseased = True
            self.disease_start_time = time.time()
            print("Thronglet contracted disease!")
    
    def share_knowledge(self, other_thronglet):
        """Share discovered resources"""
        # Share resource knowledge
        for resource_pos in self.known_resources:
            if resource_pos not in other_thronglet.known_resources:
                other_thronglet.known_resources.append(resource_pos)
        
        # Territory system removed
    
    def query_llm(self, num_resources, thronglet_id, num_buildings):
        """Query the LLM for decision making"""
        total_inv = self.inventory['food'] + self.inventory['wood'] + self.inventory['stone']
        prompt = f"""You are controlling one thronglet in a local simulation.

Respond with exactly one short action phrase only.
Do not use markdown, quotes, JSON, or <think> tags.

STATE:
- Position: ({int(self.x)}, {int(self.y)})
- Map resources remaining: {num_resources}
- Inventory total: {total_inv} (food={self.inventory['food']}, wood={self.inventory['wood']}, stone={self.inventory['stone']})
- Buildings total: {num_buildings}
- Role: {self.role or 'unassigned'}
- Favorite biome: {self.favorite_biome}

VALID ACTIONS:
- move left
- move right
- move up
- move down
- gather
- build house
- build storage
- build farm
- build workshop
- build shrine
- build well

Best next action:"""
        
        try:
            if VERBOSE_LOGGING:
                print(f"[Thronglet {thronglet_id}] Querying LLM at ({int(self.x)}, {int(self.y)}), inv={self.inventory}, resources={num_resources}")
            action_text, _ = generate_ollama_text(prompt, purpose="thronglet")
            action_text = action_text.lower()
            if VERBOSE_LOGGING:
                print(f"[Thronglet {thronglet_id}] LLM raw response: {action_text[:100]}...")  # First 100 chars
            return self.parse_llm_response(action_text, thronglet_id)
        except Exception as e:
            if VERBOSE_LOGGING:
                print(f"[Thronglet {thronglet_id}] LLM query error: {e}")
            # Fallback to random movement
            self.set_random_direction()
            return None
    
    def parse_llm_response(self, response_text, thronglet_id):
        """Parse LLM response and determine action. Returns building_type if building."""
        response_lower = response_text.lower()
        
        # Check for movement directions
        if any(word in response_lower for word in ['left', 'west']):
            self.vx = -THRONGLET_SPEED
            self.vy = 0
            self.current_action = "moving left"
            if VERBOSE_LOGGING:
                print(f"[Thronglet {thronglet_id}] -> Moving LEFT")
            return None
        elif any(word in response_lower for word in ['right', 'east']):
            self.vx = THRONGLET_SPEED
            self.vy = 0
            self.current_action = "moving right"
            if VERBOSE_LOGGING:
                print(f"[Thronglet {thronglet_id}] -> Moving RIGHT")
            return None
        elif any(word in response_lower for word in ['up', 'north']):
            self.vx = 0
            self.vy = -THRONGLET_SPEED
            self.current_action = "moving up"
            if VERBOSE_LOGGING:
                print(f"[Thronglet {thronglet_id}] -> Moving UP")
            return None
        elif any(word in response_lower for word in ['down', 'south']):
            self.vx = 0
            self.vy = THRONGLET_SPEED
            self.current_action = "moving down"
            if VERBOSE_LOGGING:
                print(f"[Thronglet {thronglet_id}] -> Moving DOWN")
            return None
        elif any(word in response_lower for word in ['gather', 'collect', 'pickup']):
            self.vx = 0
            self.vy = 0
            self.current_action = "gathering"
            if VERBOSE_LOGGING:
                print(f"[Thronglet {thronglet_id}] -> GATHERING resources")
            return None
        elif any(word in response_lower for word in ['build house', 'construct house']):
            wood_cost, stone_cost = get_building_cost('house')
            if self.inventory['wood'] >= wood_cost and self.inventory['stone'] >= stone_cost:
                self.vx = 0
                self.vy = 0
                self.current_action = "building"
                self.inventory['wood'] -= wood_cost
                self.inventory['stone'] -= stone_cost
                building_type = 'house'
                self.build_message = f"Built {building_type}! ({int(self.x)}, {int(self.y)})"
                self.build_message_time = time.time()
                print(f"[Thronglet {thronglet_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
                return building_type
            else:
                if VERBOSE_LOGGING:
                    print(f"[Thronglet {thronglet_id}] -> Wanted to build but no resources, using random direction")
                self.set_random_direction()
                return None
        elif any(word in response_lower for word in ['build storage', 'construct storage']):
            wood_cost, stone_cost = get_building_cost('storage')
            if self.inventory['wood'] >= wood_cost and self.inventory['stone'] >= stone_cost:
                self.vx = 0
                self.vy = 0
                self.current_action = "building"
                self.inventory['wood'] -= wood_cost
                self.inventory['stone'] -= stone_cost
                building_type = 'storage'
                self.build_message = f"Built {building_type}! ({int(self.x)}, {int(self.y)})"
                self.build_message_time = time.time()
                print(f"[Thronglet {thronglet_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
                return building_type
            else:
                if VERBOSE_LOGGING:
                    print(f"[Thronglet {thronglet_id}] -> Wanted to build but no resources, using random direction")
                self.set_random_direction()
                return None
        elif any(word in response_lower for word in ['build farm', 'construct farm']):
            wood_cost, stone_cost = get_building_cost('farm')
            if self.inventory['wood'] >= wood_cost and self.inventory['stone'] >= stone_cost:
                self.vx = 0
                self.vy = 0
                self.current_action = "building"
                self.inventory['wood'] -= wood_cost
                self.inventory['stone'] -= stone_cost
                building_type = 'farm'
                self.build_message = f"Built {building_type}! ({int(self.x)}, {int(self.y)})"
                self.build_message_time = time.time()
                print(f"[Thronglet {thronglet_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
                return building_type
            else:
                if VERBOSE_LOGGING:
                    print(f"[Thronglet {thronglet_id}] -> Wanted to build but no resources, using random direction")
                self.set_random_direction()
                return None
        elif any(word in response_lower for word in ['build workshop', 'construct workshop']):
            wood_cost, stone_cost = get_building_cost('workshop')
            if self.inventory['wood'] >= wood_cost and self.inventory['stone'] >= stone_cost:
                self.vx = 0
                self.vy = 0
                self.current_action = "building"
                self.inventory['wood'] -= wood_cost
                self.inventory['stone'] -= stone_cost
                building_type = 'workshop'
                self.build_message = f"Built {building_type}! ({int(self.x)}, {int(self.y)})"
                self.build_message_time = time.time()
                print(f"[Thronglet {thronglet_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
                return building_type
            self.set_random_direction()
            return None
        elif any(word in response_lower for word in ['build shrine', 'construct shrine']):
            wood_cost, stone_cost = get_building_cost('shrine')
            if self.inventory['wood'] >= wood_cost and self.inventory['stone'] >= stone_cost:
                self.vx = 0
                self.vy = 0
                self.current_action = "building"
                self.inventory['wood'] -= wood_cost
                self.inventory['stone'] -= stone_cost
                building_type = 'shrine'
                self.build_message = f"Built {building_type}! ({int(self.x)}, {int(self.y)})"
                self.build_message_time = time.time()
                print(f"[Thronglet {thronglet_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
                return building_type
            self.set_random_direction()
            return None
        elif any(word in response_lower for word in ['build well', 'construct well']):
            wood_cost, stone_cost = get_building_cost('well')
            if self.inventory['wood'] >= wood_cost and self.inventory['stone'] >= stone_cost:
                self.vx = 0
                self.vy = 0
                self.current_action = "building"
                self.inventory['wood'] -= wood_cost
                self.inventory['stone'] -= stone_cost
                building_type = 'well'
                self.build_message = f"Built {building_type}! ({int(self.x)}, {int(self.y)})"
                self.build_message_time = time.time()
                print(f"[Thronglet {thronglet_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
                return building_type
            self.set_random_direction()
            return None
        else:
            # Unclear response, fallback to random movement
            if VERBOSE_LOGGING:
                print(f"[Thronglet {thronglet_id}] -> Unclear response, using random direction")
            self.set_random_direction()
            return None
    
    def set_random_direction(self):
        """Set a random direction"""
        direction = random.choice(['left', 'right', 'up', 'down'])
        if direction == 'left':
            self.vx = -THRONGLET_SPEED
            self.vy = 0
        elif direction == 'right':
            self.vx = THRONGLET_SPEED
            self.vy = 0
        elif direction == 'up':
            self.vx = 0
            self.vy = -THRONGLET_SPEED
        else:  # down
            self.vx = 0
            self.vy = THRONGLET_SPEED
        self.current_action = f"random {direction}"


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
    
    def tick(self, thronglet, context):
        """Execute this node and return result (SUCCESS, FAILURE, RUNNING)"""
        if self.node_type == BT_NODE_SELECTOR:
            # Selector: Returns SUCCESS if any child succeeds, FAILURE if all fail
            for child in self.children:
                result = child.tick(thronglet, context)
                if result == 'SUCCESS':
                    return 'SUCCESS'
            return 'FAILURE'
        
        elif self.node_type == BT_NODE_SEQUENCE:
            # Sequence: Returns FAILURE if any child fails, SUCCESS if all succeed
            for child in self.children:
                result = child.tick(thronglet, context)
                if result == 'FAILURE':
                    return 'FAILURE'
                if result == 'RUNNING':
                    return 'RUNNING'
            return 'SUCCESS'
        
        elif self.node_type == BT_NODE_CONDITION:
            # Condition: Returns SUCCESS if condition is true
            if self.condition_func:
                if self.condition_func(thronglet, context):
                    return 'SUCCESS'
            return 'FAILURE'
        
        elif self.node_type == BT_NODE_ACTION:
            # Action: Executes action and returns result
            if self.action_func:
                return self.action_func(thronglet, context)
            return 'FAILURE'
        
        return 'FAILURE'


class BehaviorTree:
    """Behavior tree for thronglet decision making - hybrid with FSM"""
    def __init__(self, thronglet):
        self.thronglet = thronglet
        self.root = None
        self.last_successful_path = []  # Cache last successful path
        self.max_depth = 5
        self._build_tree()
    
    def _build_tree(self):
        """Build the behavior tree structure"""
        # Survival Check (Priority) - maps to STATE_SEEK_NEED
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
        
        # Directive Execution - maps to STATE_EXECUTE_DIRECTIVE
        has_directives = BehaviorTreeNode(
            BT_NODE_CONDITION,
            'has_directives',
            condition_func=lambda t, ctx: (
                ctx.get('directives') and 
                len(ctx['directives']) > 0 and
                t.needs['hunger'] > 50 and 
                t.needs['energy'] > 50
            )
        )
        directive_action = BehaviorTreeNode(
            BT_NODE_ACTION,
            'execute_directive',
            action_func=lambda t, ctx: self._transition_to_state(t, 'STATE_EXECUTE_DIRECTIVE')
        )
        directive_node = BehaviorTreeNode(
            BT_NODE_SEQUENCE,
            'directive_execution',
            children=[has_directives, directive_action]
        )
        
        # Group Task Check (Parallel)
        has_group_task = BehaviorTreeNode(
            BT_NODE_CONDITION,
            'has_group_task',
            condition_func=lambda t, ctx: (
                ctx.get('group_tasks') and
                any(t.id in task.assigned_thronglets for task in ctx['group_tasks'])
            )
        )
        group_task_action = BehaviorTreeNode(
            BT_NODE_ACTION,
            'join_group_task',
            action_func=lambda t, ctx: self._transition_to_state(t, 'STATE_EXECUTE_DIRECTIVE')
        )
        group_task_node = BehaviorTreeNode(
            BT_NODE_SEQUENCE,
            'group_task_execution',
            children=[has_group_task, group_task_action]
        )
        
        # Socialization - maps to STATE_SOCIALIZE
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
        
        # Idle Behavior - maps to STATE_IDLE
        idle_action = BehaviorTreeNode(
            BT_NODE_ACTION,
            'idle',
            action_func=lambda t, ctx: self._transition_to_state(t, 'STATE_IDLE')
        )
        
        # Root selector: Try each behavior in priority order
        self.root = BehaviorTreeNode(
            BT_NODE_SELECTOR,
            'root',
            children=[survival_node, directive_node, group_task_node, socialize_node, idle_action]
        )
    
    def _transition_to_state(self, thronglet, state_name):
        """Helper to transition FSM state"""
        # Map string to actual state constants
        state_map = {
            'STATE_SEEK_NEED': STATE_SEEK_NEED,
            'STATE_EXECUTE_DIRECTIVE': STATE_EXECUTE_DIRECTIVE,
            'STATE_SOCIALIZE': STATE_SOCIALIZE,
            'STATE_IDLE': STATE_IDLE,
            'STATE_REST': STATE_REST
        }
        if state_name in state_map:
            thronglet.transition_to_state(state_map[state_name])
        return 'SUCCESS'
    
    def tick(self, context):
        """Execute behavior tree with given context"""
        if not self.root:
            return 'FAILURE'
        
        try:
            result = self.root.tick(self.thronglet, context)
            
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


class CivilizationAdvisor:
    """LLM-powered strategic advisor for civilization-level decisions"""
    def __init__(self):
        self.directives = []  # List of current directives
        self.last_query_time = time.time()  # Initialize to current time to prevent immediate query on first frame
        self.last_goal_assignment = time.time()  # Prevent immediate heavy LLM goal assignment on startup
        self.history = []  # Store last 5 queries with context
        self.strategic_goals = {'short': [], 'medium': [], 'long': []}
        self.events_history = []  # Major events (births, builds, shortages)
        
        # Enhanced directive system
        self.json_directives = {
            'individual': {},  # {thronglet_id: instruction}
            'communal': '',    # Group task description
            'conditions': {}   # {condition: behavior}
        }
        self.group_tasks = []  # List of active GroupTask objects
        
        # Long-term goals tracking
        self.long_term_goals = {
            'survival': {'target_population': 10, 'progress': 0, 'priority': 10},
            'development': {'target_workshops': 1, 'progress': 0, 'priority': 8},
            'expansion': {'territories_explored': 0, 'target': 3, 'priority': 6},
            'social': {'target_happiness': 75, 'progress': 0, 'priority': 7}
        }
        self.civilization_age = 0  # In-game days survived
        self.total_deaths = 0
        self.achievements = []  # Milestones reached
        
        # Evolution system
        self.research_points = 0
        self.points_spent = 0
        self.game_modifiers = GameModifiers()
        
        # Challenge difficulty tracking
        self.challenge_difficulty = 1.0
        self.last_scaling_check = 0
        
        # Tech tree and abilities are content-driven so balancing stays centralized.
        self.tech_tree = clone_tech_tree()
        self.abilities = clone_abilities()
        
        # Challenge tracking
        self.active_challenges = []
        self.challenge_cooldown = 0
        
        # Legacy bonuses
        self.legacy_bonuses = clone_legacy_bonuses()
        
        # Meta learning
        self.session_stats = {
            'buildings_built': {},
            'deaths_by_cause': {},
            'avg_survival_time': 0,
            'successful_strategies': [],
            'births_total': 0,
            'highest_generation': 0,
            'peak_founder_lines': 0,
            'peak_factions': 0,
            'factions_formed': 0,
            'factions_dissolved': 0,
            'faction_schisms': 0,
            'faction_successions': 0,
            'migration_events': 0,
            'lineage_events': [],
            'evolution_history': [],
            'current_evolution_summary': {},
            'timeline_events': [],
            'faction_history': [],
            'current_run_summary': {},
        }
        
        # Smart LLM integration tracking
        self.query_count = 0
        self.focus_areas = ['resources', 'infrastructure', 'territory', 'population']
        self.current_focus = 'resources'
        self.stability_counter = 0  # Tracks consecutive stable assessments
        self.last_pop_count = INITIAL_POPULATION
        self.intervention_stats = {
            'total_queries': 0,
            'interventions': 0,
            'no_changes': 0,
            'crisis_interventions': 0
        }
        self.current_settlement_state = {}
        self.pending_strategy_job = None
        self.pending_goal_job = None
        self.last_model_used = None
        self.last_llm_error = None
        self.council_state = advisory_payload_defaults()
        self.advisory_history = []
        self.last_job_completed_at = 0.0
        self.last_evolution_sample_time = 0.0
        self.last_run_summary_refresh = 0.0
    
    def _generate_state_summary(self, thronglets, resources, buildings, territory_manager, world_map):
        """Generate concise state summary with health indicators"""
        
        # Population metrics
        pop_status = "stable" if len(thronglets) >= self.last_pop_count * 0.9 else "declining"
        pop_summary = f"Pop: {len(thronglets)} ({pop_status})"
        
        # Resource availability (% metric)
        total_food = sum(t.inventory['food'] for t in thronglets) + sum(b.stored_resources.get('food', 0) for b in buildings if b.building_type in ['storage', 'farm'])
        food_per_capita = total_food / max(1, len(thronglets))
        food_status = "abundant" if food_per_capita > 3 else "adequate" if food_per_capita > 1.5 else "scarce"
        food_pct = min(100, int(food_per_capita / 3 * 100))
        resource_summary = f"Resources: Food {food_pct}% ({food_status})"
        
        # Need satisfaction
        avg_hunger = sum(t.needs['hunger'] for t in thronglets) / max(1, len(thronglets))
        avg_energy = sum(t.needs['energy'] for t in thronglets) / max(1, len(thronglets))
        needs_status = "healthy" if avg_hunger > 70 and avg_energy > 70 else "stressed"
        needs_summary = f"Needs: Hunger {avg_hunger:.0f}%, Energy {avg_energy:.0f}% ({needs_status})"
        
        # Territory control
        if territory_manager:
            territory_tiles = sum(1 for v in territory_manager.territory_grid.values() if v['claim_strength'] >= 50)
            territory_pct = min(100, territory_tiles // 2)  # Rough percentage
            territory_summary = f"Territory: {territory_pct}% claimed"
        else:
            territory_summary = "Territory: N/A"
            territory_pct = 0
        
        # Infrastructure
        houses = sum(1 for b in buildings if b.building_type == 'house')
        farms = sum(1 for b in buildings if b.building_type == 'farm')
        wells = sum(1 for b in buildings if b.building_type == 'well')
        shrines = sum(1 for b in buildings if b.building_type == 'shrine')
        workshops = sum(1 for b in buildings if b.building_type == 'workshop')
        avg_happiness = sum(t.happiness for t in thronglets) / max(1, len(thronglets))
        avg_morale = sum(getattr(t, 'morale', 65) for t in thronglets) / max(1, len(thronglets))
        infrastructure_status = "adequate" if houses >= len(thronglets) // 2 and farms >= len(thronglets) // 3 else "insufficient"
        infrastructure_summary = f"Infrastructure: {houses} houses, {farms} farms, {wells} wells, {workshops} workshops ({infrastructure_status})"
        culture_summary = f"Culture: Happiness {avg_happiness:.0f}%, Morale {avg_morale:.0f}%, Shrines {shrines}"
        
        # Crisis indicators
        crisis_flags = []
        if avg_hunger < 50:
            crisis_flags.append("HUNGER_CRISIS")
        if len(thronglets) < 3:
            crisis_flags.append("POPULATION_CRITICAL")
        if food_pct < 30:
            crisis_flags.append("FOOD_SHORTAGE")
        if avg_happiness < 45:
            crisis_flags.append("MORALE_COLLAPSE")
        
        return {
            'summary_text': f"{pop_summary} | {resource_summary} | {needs_summary} | {territory_summary} | {infrastructure_summary} | {culture_summary}",
            'crisis_flags': crisis_flags,
            'metrics': {
                'population': len(thronglets),
                'food_pct': food_pct,
                'avg_hunger': avg_hunger,
                'avg_energy': avg_energy,
                'avg_happiness': avg_happiness,
                'avg_morale': avg_morale,
                'territory_pct': territory_pct,
                'houses': houses,
                'farms': farms,
                'wells': wells,
                'workshops': workshops,
                'shrines': shrines,
            }
        }
    
    def _check_milestones(self, metrics):
        """Check if any population milestones have been reached"""
        # Track milestones to avoid repeated triggers
        if not hasattr(self, 'achieved_milestones'):
            self.achieved_milestones = set()
        
        # Population milestones (every 5 thronglets)
        if metrics['population'] > 0 and metrics['population'] % 5 == 0:
            pop_milestone = (metrics['population'] // 5) * 5
            pop_key = f"pop_{pop_milestone}"
            if pop_key not in self.achieved_milestones:
                self.achieved_milestones.add(pop_key)
                return True
        
        # First building of each type - only trigger once per type
        if metrics['houses'] == 1:
            milestone_key = "houses_1"
            if milestone_key not in self.achieved_milestones:
                self.achieved_milestones.add(milestone_key)
                return True
        if metrics['farms'] == 1:
            milestone_key = "farms_1"
            if milestone_key not in self.achieved_milestones:
                self.achieved_milestones.add(milestone_key)
                return True
        
        return False
    
    def _should_intervene(self, state_summary, current_time):
        """Decide if LLM should provide guidance or stay silent"""
        
        # Always intervene if crisis
        if state_summary['crisis_flags']:
            return True, "crisis", state_summary['crisis_flags']
        
        # Check milestone triggers (population milestones, first building, etc.)
        if self._check_milestones(state_summary['metrics']):
            return True, "milestone", []
        
        # Check if metrics below thresholds
        metrics = state_summary['metrics']
        if (metrics['food_pct'] < 50 or 
            metrics['avg_hunger'] < 60 or 
            metrics['avg_energy'] < 60 or
            metrics['avg_happiness'] < 55 or
            metrics['avg_morale'] < 55):
            return True, "imbalance", []
        
        # Variable interval - extend if stable
        time_since_last = current_time - self.last_query_time
        if self.stability_counter > 3:  # 3+ stable checks in a row
            required_interval = CIVILIZATION_ADVISOR_INTERVAL * 2  # Double interval when stable
        else:
            required_interval = CIVILIZATION_ADVISOR_INTERVAL
        
        if time_since_last < required_interval:
            return False, "stable", []
        
        # Rotate focus areas every 2 queries
        focus_rotation = ['resources', 'infrastructure', 'territory', 'population']
        current_focus = focus_rotation[self.query_count % len(focus_rotation)]
        
        # Only intervene if current focus area needs attention
        if current_focus == 'resources' and metrics['food_pct'] >= 70:
            return False, "focus_stable", []
        elif current_focus == 'infrastructure' and metrics['houses'] >= metrics['population'] // 2:
            return False, "focus_stable", []
        
        return True, "routine", []
    
    def query_llm(self, thronglets, resources, buildings, narrative_panel=None, player_suggestion=None, territory_manager=None, city_planner=None, world_map=None, hazards=None, state_summary=None, intervention_reason=None, faction_manager=None):
        """Query LLM for strategic guidance"""
        # Calculate civilization statistics
        num_thronglets = len(thronglets)
        num_resources = sum(1 for r in resources if not r.collected)
        num_food = sum(1 for r in resources if r.resource_type == 'food' and not r.collected)
        num_wood = sum(1 for r in resources if r.resource_type == 'wood' and not r.collected)
        num_stone = sum(1 for r in resources if r.resource_type == 'stone' and not r.collected)
        total_food_inv = sum(t.inventory['food'] for t in thronglets)
        total_wood_inv = sum(t.inventory['wood'] for t in thronglets)
        total_stone_inv = sum(t.inventory['stone'] for t in thronglets)
        avg_hunger = sum(t.needs['hunger'] for t in thronglets) / len(thronglets) if thronglets else 0
        avg_energy = sum(t.needs['energy'] for t in thronglets) / len(thronglets) if thronglets else 0
        
        # Count buildings by type and aggregate storage/production
        building_counts = {'house': 0, 'storage': 0, 'farm': 0, 'workshop': 0, 'shrine': 0, 'well': 0}
        total_food_in_storage = 0
        total_wood_in_storage = 0
        total_food_in_farms = 0
        total_carrying_food = 0
        total_carrying_wood = 0
        
        for building in buildings:
            building_counts[building.building_type] = building_counts.get(building.building_type, 0) + 1
            if building.building_type == 'storage':
                total_food_in_storage += building.stored_resources['food']
                total_wood_in_storage += building.stored_resources['wood']
            elif building.building_type == 'farm':
                total_food_in_farms += building.stored_resources['food']
        
        # Thronglet behavioral analysis
        role_distribution = {'gatherer': 0, 'builder': 0, 'explorer': 0}
        hungry_count = sum(1 for t in thronglets if t.needs['hunger'] < 50)
        energy_low_count = sum(1 for t in thronglets if t.needs['energy'] < 50)
        can_reproduce_count = sum(1 for t in thronglets if t.can_reproduce())
        
        # New metrics: Health, skills, social, disease
        avg_health = sum(t.health for t in thronglets) / len(thronglets) if thronglets else 100
        avg_happiness = sum(t.happiness for t in thronglets) / len(thronglets) if thronglets else 100
        diseased_count = sum(1 for t in thronglets if t.diseased)
        
        # Faction analysis
        faction_info = ""
        num_factions = 0
        if faction_manager and faction_manager.factions:
            num_factions = len(faction_manager.factions)
            faction_details = []
            for faction_id, faction in faction_manager.factions.items():
                avg_bond = faction.get_bond_strength(thronglets) if len(faction.member_ids) >= 2 else 0
                faction_details.append(f"Faction {faction_id}: {len(faction.member_ids)} members, avg bond {avg_bond:.0f}")
            faction_info = f"\n- Active Factions: {num_factions}\n" + "\n".join([f"  {fd}" for fd in faction_details[:5]])  # Limit to 5 for brevity
        
        # Social bonds analysis
        avg_bonds_per_thronglet = sum(len(t.bonds) for t in thronglets) / len(thronglets) if thronglets else 0
        strong_bonds = sum(1 for t in thronglets for bond_val in t.bonds.values() if bond_val > 70)
        
        # AI Learning metrics (Q-learning success tracking)
        q_learning_stats = ""
        if thronglets:
            total_q_entries = sum(len(t.q_table) for t in thronglets)
            avg_q_entries = total_q_entries / len(thronglets)
            if avg_q_entries > 0:
                # Calculate success rates
                successful_actions = sum(sum(t.success_memory.values()) for t in thronglets if hasattr(t, 'success_memory'))
                failed_actions = sum(sum(t.failure_memory.values()) for t in thronglets if hasattr(t, 'failure_memory'))
                total_actions = successful_actions + failed_actions
                success_rate = (successful_actions / total_actions * 100) if total_actions > 0 else 0
                q_learning_stats = f"\n- AI Learning: {avg_q_entries:.0f} learned actions per thronglet, {success_rate:.0f}% success rate"
        
        # Skill distribution
        skill_levels = {'novice': 0, 'intermediate': 0, 'expert': 0}
        for t in thronglets:
            skill_key = get_role_skill_key(t.role)
            if t.role and skill_key and skill_key in t.skills:
                # Count role
                if t.role in role_distribution:
                    role_distribution[t.role] += 1
                # Count skill level
                level = t.skills[skill_key]['level']
                if level >= 3:
                    skill_levels['expert'] += 1
                elif level >= 2:
                    skill_levels['intermediate'] += 1
                else:
                    skill_levels['novice'] += 1
        
        # Build context section
        recent_events_text = ""
        if self.events_history:
            recent_events = [e for e in self.events_history if time.time() - e['time'] < 60]
            if recent_events:
                recent_events_text = "\nRecent Events (last 60s):\n" + "\n".join([f"- {e['description']}" for e in recent_events[-5:]])
        
        # Previous strategy
        previous_strategy_text = ""
        if self.history:
            last_query = self.history[-1]
            previous_strategy_text = f"\nPrevious Strategy (30s ago):\n{last_query.get('summary', 'No previous strategy')}"
        
        # Build evolution system text
        active_mods_text = "\n".join([f"- {k}: {v:.2f}x" for k, v in self.game_modifiers.permanent.items()]) if self.game_modifiers.permanent else "- None"
        unlocked_techs_text = ', '.join([self.tech_tree[t]['name'] for t in self.game_modifiers.tech_unlocked]) if self.game_modifiers.tech_unlocked else 'None'
        
        # Available techs
        available_techs = []
        for tech_id, data in self.tech_tree.items():
            if tech_id not in self.game_modifiers.tech_unlocked:
                if all(req in self.game_modifiers.tech_unlocked for req in data.get('requires', [])):
                    available_techs.append(f"- {tech_id}: {data['name']} (cost: {data['cost']} points) - Effect: {data['effect']}")
        available_techs_text = "\n".join(available_techs[:8])
        
        # Meta insights
        buildings_built_text = ', '.join([f"{k}: {v}" for k, v in self.session_stats['buildings_built'].items()]) if self.session_stats['buildings_built'] else 'None yet'
        deaths_text = ', '.join([f"{k}: {v}" for k, v in self.session_stats['deaths_by_cause'].items()]) if self.session_stats['deaths_by_cause'] else 'No deaths yet'
        settlement = self.current_settlement_state or {}
        settlement_summary_text = f"""
Settlement Identity:
- Prosperity: {int(settlement.get('prosperity_score', 0.0) * 100)}%
- Culture: {int(settlement.get('culture_score', 0.0) * 100)}%
- District focus: {settlement.get('district_identity', 'homestead')}
- Dominant biome: {settlement.get('dominant_biome', 'plains')}
- Festival readiness: {int(settlement.get('festival_readiness', 0.0) * 100)}%
- Landmark tier: {settlement.get('landmark_level', 1)}
- Festival active: {'yes' if settlement.get('festival_active') else 'no'}"""
        
        prompt = f"""You are a strategic advisor for a civilization of {num_thronglets} thronglets.

=== RESPONSE CONTRACT ===
- Primary Ollama model target: {PREFERRED_OLLAMA_MODEL}
- You are running locally through Ollama with Qwen.
- Respond with either the exact text `No changes` OR one raw JSON object.
- Do not include markdown fences, prose preambles, or <think> tags.

=== GAME SCALE & LIMITS ===
- World Size: 2048x1536 pixels (64x48 tiles)
- Population Cap: {MAX_POPULATION} thronglets (soft limit for performance)
- Initial Population: {INITIAL_POPULATION} thronglets
- Territory System: Voronoi-based, expands dynamically from thronglet/building positions
- Movement Speed: 0.75 px/frame (slow, deliberate expansion)
- Resource Spawn: Food respawns every 30s, wood/stone are finite (biome-specific)

=== GAME MECHANICS ===
Buildings:
{chr(10).join(format_building_prompt_lines())}
- Buildings level up automatically when clustered into stronger districts.

Thronglet Behavior:
- Hunger decreases over time and increases when eating food
- Energy decreases over time, faster at night (0.042 vs 0.021)
- Thirst decreases over time, must drink from wells to survive
- Health decreases from unmet needs, age, and disease
- Thronglets can die from old age (7 minute lifespan) or health failure
- Thronglets gain skills and level up with experience
- Social bonds form between thronglets working together (bonds >70 form factions)
- Disease outbreaks occur based on population density and hygiene
- Thronglets automatically eat food when near resources/farms
- Thronglets rest in houses when energy < 30
- Thronglets can reproduce when needs met, with a 45s cooldown
- Morale, inspiration, favorite biome, and settlement prosperity all influence output

AI Decision Systems:
- Behavior Trees: Thronglets use hierarchical decision trees that prioritize survival, then directives, then group tasks
- Q-Learning: Thronglets learn from success/failure, adapting actions over time (30% exploration rate)
- Factions: Groups of 2-3+ thronglets with bonds >70 can work together on coordinated tasks
- Boids Clustering: Thronglets naturally cluster when working on same tasks (cohesion/separation forces)
- Territory: Voronoi-based dynamic territory expansion from thronglet/building positions

Building Efficiency Guidelines:
- Build 1 storage per 5 thronglets MAX (avoid overbuilding)
- Build houses to support population (1 house per 2 thronglets)
- Farms should roughly match population for sustainable food
- Wells are CRITICAL for thirst needs and disease prevention (aim for 1 well per 10 population)

=== CURRENT CIVILIZATION STATUS ===
Population: {num_thronglets} thronglets
- Roles: {role_distribution['gatherer']} gatherers, {role_distribution['builder']} builders, {role_distribution['explorer']} explorers
- Skills: {skill_levels['novice']} novice, {skill_levels['intermediate']} intermediate, {skill_levels['expert']} expert
- Needs: {hungry_count} hungry (<50), {energy_low_count} low energy (<50), {can_reproduce_count} ready to reproduce
- Health: {diseased_count} diseased thronglets, avg health: {avg_health:.1f}/100
- Social Bonds: {avg_bonds_per_thronglet:.1f} bonds per thronglet, {strong_bonds} strong bonds (>70){faction_info}{q_learning_stats}

Resources:
- On map: {num_food} wild food, {num_wood} wild wood, {num_stone} stone
- Carried: {total_food_inv} food, {total_wood_inv} wood, {total_stone_inv} stone
- In storage: {total_food_in_storage} food, {total_wood_in_storage} wood
- In farms: {total_food_in_farms} ready-to-harvest food

Building Infrastructure:
- {building_counts['house']} houses (capacity: {building_counts['house'] * 2} thronglets)
- {building_counts['storage']} storage (recommended: {max(1, num_thronglets // 5)})
- {building_counts['farm']} farms (producing ~{building_counts['farm'] / 10:.1f} food/sec)
- {building_counts['workshop']} workshops, {building_counts['shrine']} shrines, {building_counts['well']} wells
{settlement_summary_text}"""
        
        # Calculate territory stats (Voronoi-based dynamic territory)
        territory_text = ""
        if territory_manager:
            territory_tiles = sum(1 for v in territory_manager.territory_grid.values() if v['claim_strength'] >= 50)
            if territory_tiles > 0:
                avg_claim_strength = sum(v['claim_strength'] for v in territory_manager.territory_grid.values()) / max(1, len(territory_manager.territory_grid))
                bounds = territory_manager.get_territory_bounds()
                voronoi_seeds = len(territory_manager.voronoi_seeds) if hasattr(territory_manager, 'voronoi_seeds') else 0
                if bounds:
                    territory_text = f"""
Territory Status (Voronoi-based dynamic expansion):
- Claimed tiles: {territory_tiles} (~{territory_tiles * 0.4:.1f} tiles²)
- Average claim strength: {avg_claim_strength:.1f}%
- Territory center: ({bounds['center_x']:.0f}, {bounds['center_y']:.0f})
- Active territory seeds: {voronoi_seeds} (thronglets + buildings)"""
        
        # Get city plan summary
        city_plan_text = ""
        if city_planner and city_planner.current_plan:
            city_plan_text = f"""
Current City Plan:
{city_planner.get_plan_summary()}"""
        
        # Biome distribution
        biome_dist_text = ""
        if world_map and buildings:
            biome_counts = {}
            for building in buildings:
                biome_type = world_map.get_biome_at(building.x, building.y)
                biome_counts[biome_type] = biome_counts.get(biome_type, 0) + 1
            if biome_counts:
                biome_dist = ', '.join([f"{count} in {biome}" for biome, count in biome_counts.items()])
                biome_dist_text = f"\nBiomes: {biome_dist}"
        
        prompt += f"""
{territory_text}
{city_plan_text}
{biome_dist_text}

Civilization Health:
- Average hunger: {avg_hunger:.1f}/100 (target: >70)
- Average energy: {avg_energy:.1f}/100 (target: >70)
- Average health: {avg_health:.1f}/100
- Average happiness: {avg_happiness:.1f}/100
- Total deaths: {self.total_deaths}
- Population cap: {MAX_POPULATION} (current: {num_thronglets}/{MAX_POPULATION})
{previous_strategy_text}
{recent_events_text}

=== EVOLUTION & RESEARCH SYSTEM ===
Available Research Points: {self.research_points} (spent: {self.points_spent})

Active Modifiers:
{active_mods_text}

Unlocked Technologies: {unlocked_techs_text}

Available Technologies to Unlock:
{available_techs_text}

You can issue EVOLUTION COMMANDS:
1. TECH|tech_id|reasoning - Unlock permanent technology
2. EVOLVE|mechanic|multiplier|reasoning - Temporary modifier (2 min, cost scales)
3. ABILITY|ability_name|reasoning - Trigger instant ability
4. CHALLENGE|type|reasoning - Spawn challenge for bonus points

Available mechanics to evolve temporarily:
- farm_production_rate, house_capacity, thronglet_speed
- reproduction_cooldown, skill_xp_gain, happiness_modifier
- gather_efficiency, build_speed, disease_resistance

Available Abilities:
- speed_burst (50 pts, 30s, +100% speed)
- workers_focus (75 pts, 60s, +50% gather, +30% build)
- heal_wave (100 pts, instant, +50 health all)
- resource_blessing (80 pts, instant, spawn 5 resources)

Cost formula: base_cost * (1.5 ^ times_used), capped at 2.0x modifier range

=== META INSIGHTS (Historical Data) ===
Buildings Built This Session:
{buildings_built_text}

Death Analysis:
{deaths_text}

Average Survival Time: {self.session_stats['avg_survival_time']:.1f} seconds
"""
        
        # Add restraint and focus guidance if state_summary provided
        if state_summary:
            # Rotate focus every 2 queries
            if self.query_count % 2 == 0:
                focus_idx = (self.query_count // 2) % len(self.focus_areas)
                self.current_focus = self.focus_areas[focus_idx]
            
            crisis_flags_str = ', '.join(state_summary['crisis_flags']) if state_summary['crisis_flags'] else "None"
            intervention_reason_str = intervention_reason if intervention_reason else "routine"
            
            focus_guidance = {
                'resources': "Focus: Assess food/wood/stone availability. Intervene only if shortages detected.",
                'infrastructure': "Focus: Assess housing/farms/storage adequacy. Intervene only if capacity insufficient.",
                'territory': "Focus: Assess territorial expansion. Intervene only if stagnant or hazardous areas unclaimed.",
                'population': "Focus: Assess population health/growth. Intervene only if declining or overcrowded."
            }
            
            prompt += f"""

=== ASSESSMENT DIRECTIVE ===
Your PRIMARY role is to observe and assess. Intervene ONLY when necessary.

State Summary: {state_summary['summary_text']}
Crisis Flags: {crisis_flags_str}
Intervention Reason: {intervention_reason_str}
Current Focus: {self.current_focus}

RESTRAINT GUIDELINES:
1. If all metrics >60% and no crisis flags: Output 'No changes' or minimal observation
2. Propose changes ONLY if:
   - Any metric <50% (critical)
   - Crisis flags present
   - Major milestone reached (e.g., pop doubled, new territory)
3. When stable, acknowledge with: "Civilization progressing well. Monitoring." then NO directives
4. When intervening, be SPECIFIC and MINIMAL (1-3 directives max)

INTERVENTION SCALE:
- Stable (metrics >70%): "No changes needed"
- Mild concern (metrics 50-70%): 1 conditional directive
- Crisis (metrics <50%): 2-3 targeted directives

CURRENT FOCUS AREA: {focus_guidance.get(self.current_focus, '')}

EXAMPLE 1 - Stable Civilization:
State: Pop 12 (stable) | Food 85% (abundant) | Needs: Hunger 78%, Energy 82% (healthy) | Territory: 65% claimed
Assessment: "Civilization thriving. Thronglets managing resources autonomously. No intervention required."
Output: 'No changes'

EXAMPLE 2 - Mild Concern:
State: Pop 15 (stable) | Food 55% (adequate) | Needs: Hunger 62%, Energy 71% (stressed) | Territory: 70% claimed
Assessment: "Food reserves declining but not critical. Preemptive farming recommended."
Output:
{{
  "individual": {{}},
  "communal": "If food drops below 50%, prioritize farm construction",
  "conditions": {{"hunger<60": "Focus 2 gatherers on food collection"}}
}}

EXAMPLE 3 - Crisis:
State: Pop 8 (declining) | Food 25% (scarce) | Needs: Hunger 42%, Energy 38% (stressed) | Territory: 45% claimed
Assessment: "FOOD CRISIS detected. Immediate action required."
Output:
{{
  "individual": {{"0": "Build farm immediately if 5 wood available", "1": "Gather food urgently"}},
  "communal": "All gatherers prioritize food - survival mode",
  "conditions": {{"hunger<50": "Drop all tasks, gather food from any source"}}
}}

=== YOUR STRATEGIC MISSION ===
Provide strategic directives in JSON format for autonomous thronglet AI. You can issue both individual instructions (for specific thronglets) and communal tasks (for groups).

**REQUIRED JSON FORMAT:**
{{
  "individual": {{
    "0": "Scout north, then gather if safe",
    "1": "Focus on farming skills - gather food from farms",
    "2": "Build farm when wood available"
  }},
  "communal": "Form party of 3 for building if pop>5",
  "team_task": {{
    "faction_id": 0,
    "task": "build workshop",
    "count": 3,
    "reasoning": "Faction 0 has strong bonds, assign coordinated building task"
  }},
  "conditions": {{
    "hunger<50": "Prioritize farm else explore in pairs",
    "population>5": "Assign 2 explorers to scout east"
  }}
}}

**Field Definitions:**
- "individual": Object mapping thronglet IDs (as strings) to specific instructions. Use IDs 0-{num_thronglets-1}.
- "communal": String describing group tasks (e.g., "Form party of 3 for building", "Coordinate gathering party of 2")
- "team_task": Object for faction-based coordinated tasks. Format: {{"faction_id": 0, "task": "build workshop", "count": 3, "reasoning": "reason"}}. Only use if factions exist ({num_factions} active). Faction IDs are 0-{num_factions-1}.
- "conditions": Object mapping game state conditions to adaptive behaviors. Conditions use format: "metric<value" or "metric>value" (e.g., "hunger<50", "population>5")

**Few-Shot Examples:**

Example 1 - Individual Focus:
{{
  "individual": {{
    "0": "Gather wood for upcoming construction",
    "1": "Explore north territory for new resources"
  }},
  "communal": "",
  "conditions": {{}}
}}

Example 2 - Communal Task:
{{
  "individual": {{}},
  "communal": "Form building party: assign 3 thronglets to construct farm together",
  "conditions": {{
    "population>5": "If pop>5, form exploration party of 2"
  }}
}}

Example 2b - Faction Team Task (use when factions exist):
{{
  "individual": {{}},
  "communal": "",
  "team_task": {{
    "faction_id": 0,
    "task": "build workshop near houses",
    "count": 3,
    "reasoning": "Faction 0 members work well together, assign coordinated workshop construction"
  }},
  "conditions": {{}}
}}

Example 3 - Conditional Behavior:
{{
  "individual": {{
    "0": "Focus on gathering skills development"
  }},
  "communal": "",
  "conditions": {{
    "hunger<50": "All gatherers prioritize food collection",
    "energy<30": "Direct builders to rest in houses"
  }}
}}

**LEGACY FORMAT (still supported):**
Legacy fallback only if you absolutely cannot produce JSON:
priority|action|reasoning
Examples:
9|build 2 farms immediately|population hungry (avg {avg_hunger:.1f}/100), farms produce food automatically
7|gather wood|need 4 wood for 2 farms to sustain population

CRITICAL RULES:
- Avoid building excessive storage! Build only 1 per 5 population maximum.
- Wells are essential for survival - prioritize when population > {building_counts['well'] * 10}
- Build farms when average hunger < 70
- Workshops boost nearby gathering - consider strategic placement
- Individual directives override default behavior for specific thronglets
- Communal tasks automatically form coordinated groups
- Team tasks assign to specific factions (factions form from bonds >70, {num_factions} active now)
- Conditions adapt behavior based on current game state
- Thronglets learn from experience (Q-learning) - repeated failures indicate need for intervention
- Behavior trees prioritize survival over directives - don't issue directives during critical needs

STRATEGIC CITY PLANNING:
- Territory grows via Voronoi diagram from thronglet/building positions. Dynamic expansion.
- Thronglets cluster naturally via Boids algorithm when working together - leverage this
- Cluster related buildings: farms->storage, houses->wells, workshops->civic buildings
- Consider biomes: farms in plains/forest, houses avoid swamps/deserts
- Avoid hazards and difficult terrain (mountains, swamps)
- Factions work better together - use team_task for coordinated builds when factions exist
- If population > 10, you can provide city plan in JSON format:

CITY PLAN JSON FORMAT (optional, for major development):
{{
  "districts": [
    {{"type": "residential", "priority": 8, "location": "center", "buildings": ["house", "well"]}},
    {{"type": "production", "priority": 7, "location": "north", "buildings": ["farm", "storage"]}}
  ],
  "expansion_direction": "east|west|north|south",
  "rationale": "Brief reason for plan"
}}

{f'''
=== PLAYER SUGGESTION ===
The observer has suggested: "{player_suggestion}"

Evaluate this suggestion against current needs and resources:
1. Is it feasible given current resources/population?
2. Does it align with survival priorities?
3. Should it be accepted (add as directive), modified, or politely declined?

If accepting/modifying, include appropriate directives in your response.
If declining, return `No changes` or JSON with minimal cautionary directives only.
''' if player_suggestion else ''}
Your response MUST be either:
1. The exact text `No changes`
2. One raw JSON object following the schema above
3. Legacy directive lines only if JSON truly fails

Do not add prose before the JSON or directive lines.

Directives:"""
        
        try:
            print("\n[Civilization Advisor] Querying LLM for strategic guidance...")
            print(f"[Civilization Advisor] Population: {num_thronglets}, Resources: {num_resources}, Buildings: {sum(building_counts.values())}")

            response_text, model_used = generate_ollama_text(prompt, purpose="advisor")
            print(f"[Civilization Advisor] Successfully queried {model_used}")
            
            print(f"[Civilization Advisor] LLM Response ({len(response_text)} chars):\n{response_text[:300]}...\n")
            
            # Try to parse JSON directives first, fall back to legacy format
            json_parsed = self.parse_json_directives(response_text)
            if json_parsed is None:
                # LLM returned "No changes" - already handled in parse_json_directives
                print("[Advisor] No intervention from LLM - civilization stable")
                # Clear all directives when no intervention needed
                self.directives = []
                # Calculate and report intervention rate
                intervention_rate = self.intervention_stats['interventions'] / max(1, self.intervention_stats['total_queries'])
                print(f"[Advisor Stats] Intervention Rate: {intervention_rate:.1%} (Target: <30%)")
            elif json_parsed and (json_parsed.get('individual') or json_parsed.get('communal') or json_parsed.get('conditions')):
                print(f"[Civilization Advisor] Parsed JSON directives: {len(json_parsed.get('individual', {}))} individual, communal: {bool(json_parsed.get('communal'))}, conditions: {len(json_parsed.get('conditions', {}))}")
                
                # Clear legacy directives when using JSON directives
                self.directives = []
                
                # Validate individual directives
                for thronglet_id, instruction in list(json_parsed.get('individual', {}).items()):
                    directive = {'action': instruction, 'priority': 8}
                    is_valid, errors = self.validate_directive(directive, thronglets, buildings, resources)
                    if not is_valid:
                        print(f"[Directive Validation] Invalid directive for thronglet {thronglet_id}: {', '.join(errors)}")
                        # Remove invalid directive
                        if thronglet_id in self.json_directives['individual']:
                            del self.json_directives['individual'][thronglet_id]
            else:
                # Fall back to legacy parse_directives
                parsed_data = self.parse_directives(response_text)
                print(f"[Civilization Advisor] Parsed {len(self.directives)} legacy directives")
                
                # Validate legacy directives
                validated_directives = []
                for directive in self.directives:
                    is_valid, errors = self.validate_directive(directive, thronglets, buildings, resources)
                    if is_valid:
                        validated_directives.append(directive)
                    else:
                        print(f"[Directive Validation] Vetoed directive: {directive['action']} - {', '.join(errors)}")
                self.directives = validated_directives
            
            # Only warn if we have neither JSON directives nor legacy directives
            has_json_directives = (json_parsed and 
                                 (json_parsed.get('individual') or 
                                  json_parsed.get('communal') or 
                                  json_parsed.get('conditions')))
            has_legacy_directives = len(self.directives) > 0
            
            if not has_json_directives and not has_legacy_directives:
                print("[Civilization Advisor] WARNING: No directives parsed! LLM may not have followed format.")
                # Try to extract any actionable text as a single directive
                if 'build' in response_text.lower() or 'gather' in response_text.lower():
                    self.directives = [
                        {'priority': 5, 'action': response_text[:50], 'reasoning': 'LLM response (format may be incorrect)'}
                    ]
            
            # Parse evolution commands if narrative panel available
            if narrative_panel:
                self.parse_evolution_commands(response_text, narrative_panel, thronglets, resources, buildings)
            
            # Store in history (keep last 5)
            history_entry = {
                'time': time.time(),
                'summary': response_text[:200],  # First 200 chars
                'directives': self.directives.copy(),
                'directive_count': len(self.directives)
            }
            self.history.append(history_entry)
            if len(self.history) > 5:
                self.history.pop(0)
        except Exception as e:
            print(f"[Civilization Advisor] ERROR: LLM query failed: {e}")
            print(f"[Civilization Advisor] Make sure Ollama is running: 'ollama serve'")
            print(f"[Civilization Advisor] Install a model: 'ollama pull {PREFERRED_OLLAMA_MODEL}'")
            # Fallback to smart directive based on game state
            if len(thronglets) < 3:
                fallback_action = "gather food and wood to build first house"
            elif building_counts.get('well', 0) < len(thronglets) // 10:
                fallback_action = "build 1 well immediately"
            elif building_counts.get('farm', 0) < len(thronglets) / 2:
                fallback_action = "build farms for food production"
            else:
                fallback_action = "continue gathering resources"
            self.directives = [
                {'priority': 5, 'action': fallback_action, 'reasoning': f'LLM unavailable - {fallback_action}'}
            ]

    def has_pending_llm_jobs(self):
        return self.pending_strategy_job is not None or self.pending_goal_job is not None

    def get_llm_status_label(self, fallback_model=None):
        if self.pending_strategy_job:
            elapsed = time.time() - self.pending_strategy_job.get("queued_at", time.time())
            return f"advisor {elapsed:.0f}s"
        if self.pending_goal_job:
            elapsed = time.time() - self.pending_goal_job.get("queued_at", time.time())
            return f"goals {elapsed:.0f}s"
        if self.last_llm_error and time.time() - self.last_job_completed_at < LLM_BACKOFF_SECONDS:
            return "cooldown"
        return self.last_model_used or fallback_model or PREFERRED_OLLAMA_MODEL

    def _build_compact_strategy_request(
        self,
        thronglets,
        resources,
        buildings,
        state_summary=None,
        intervention_reason=None,
        faction_manager=None,
    ):
        building_counts = {btype: 0 for btype in BUILDING_DEFINITIONS}
        for building in buildings:
            building_counts[building.building_type] = building_counts.get(building.building_type, 0) + 1

        settlement = self.current_settlement_state or {}
        avg_hunger = sum(t.needs["hunger"] for t in thronglets) / max(1, len(thronglets))
        avg_energy = sum(t.needs["energy"] for t in thronglets) / max(1, len(thronglets))
        avg_health = sum(t.health for t in thronglets) / max(1, len(thronglets)) if thronglets else 100
        avg_happiness = sum(t.happiness for t in thronglets) / max(1, len(thronglets)) if thronglets else 100
        avg_morale = sum(getattr(t, "morale", 65) for t in thronglets) / max(1, len(thronglets)) if thronglets else 65
        diseased_count = sum(1 for t in thronglets if t.diseased)
        total_food_inv = sum(t.inventory["food"] for t in thronglets)
        total_wood_inv = sum(t.inventory["wood"] for t in thronglets)
        total_stone_inv = sum(t.inventory["stone"] for t in thronglets)
        map_food = sum(1 for r in resources if r.resource_type == "food" and not r.collected)
        map_wood = sum(1 for r in resources if r.resource_type == "wood" and not r.collected)
        map_stone = sum(1 for r in resources if r.resource_type == "stone" and not r.collected)
        faction_count = len(getattr(faction_manager, "factions", {})) if faction_manager else 0

        thronglet_lines = "\n".join(
            [
                f"- {t.id}: role={t.role or 'unassigned'}, hunger={int(t.needs['hunger'])}, energy={int(t.needs['energy'])}, health={int(t.health)}, morale={int(getattr(t, 'morale', 65))}, carrying={t.inventory}"
                for t in thronglets[:8]
            ]
        ) or "- none"
        crisis_flags = ", ".join(state_summary.get("crisis_flags", [])) if state_summary else "none"
        summary_text = state_summary.get("summary_text", "No state summary available.") if state_summary else "No state summary available."
        available_buildings = ", ".join(
            [
                f"{building_type}:{building_counts.get(building_type, 0)}"
                for building_type in ("house", "farm", "storage", "well", "workshop", "shrine")
            ]
        )
        faction_lines = []
        if faction_manager and getattr(faction_manager, "factions", {}):
            for faction in list(faction_manager.factions.values())[:4]:
                faction_lines.append(
                    f"- F{faction.id}: doctrine={faction.primary_doctrine}, cohesion={int(faction.cohesion)}, members={len(faction.member_ids)}, rivals={faction.rival_faction_ids}"
                )
        faction_text = "\n".join(faction_lines) or "- none"

        prompt = f"""You are the strategic council for a local autonomous colony sim.
Target model: {PREFERRED_OLLAMA_MODEL}
Return either the exact text No changes or one raw JSON object.
No markdown fences. No prose preamble. No <think> tags.

Mission:
- Co-govern the colony without changing rules directly.
- Suggest doctrine, priorities, faction goals, and a small set of directives.
- Never invent technologies, abilities, modifiers, or raw rule mutations.

Current review trigger: {intervention_reason or 'routine'}
State summary: {summary_text}
Crisis flags: {crisis_flags}
Current focus: {self.current_focus}

Colony:
- Population: {len(thronglets)}
- Buildings: {available_buildings}
- Resources on map: food={map_food}, wood={map_wood}, stone={map_stone}
- Carrying: food={total_food_inv}, wood={total_wood_inv}, stone={total_stone_inv}
- Avg needs: hunger={avg_hunger:.0f}, energy={avg_energy:.0f}, health={avg_health:.0f}, happiness={avg_happiness:.0f}, morale={avg_morale:.0f}
- Diseased thronglets: {diseased_count}
- District: {settlement.get('district_identity', 'homestead')}
- Prosperity: {int(settlement.get('prosperity_score', 0.0) * 100)}%
- Culture: {int(settlement.get('culture_score', 0.0) * 100)}%
- Festival readiness: {int(settlement.get('festival_readiness', 0.0) * 100)}%
- Factions: {faction_count}

Faction snapshot:
{faction_text}

Thronglet snapshot:
{thronglet_lines}

Building rules:
{chr(10).join(format_building_prompt_lines())}

Constraints:
- Max 2 individual directives.
- Max 1 communal directive.
- Use team_task only if factions > 0.
- Keep event_framing to one sentence.
- If stable, return No changes.

JSON schema:
{{
  "doctrine": {{
    "focus": "survival|growth|industry|territory|culture|health|stability",
    "stance": "measured|urgent|expansive|defensive|restorative",
    "district_priority": "homestead|agrarian|industrial|frontier|civic|sanctuary",
    "crisis_posture": "stabilize|expand|recover|fortify|consolidate",
    "reasoning": "brief"
  }},
  "strategic_priorities": [
    {{"key": "food_security", "weight": 0.9, "reasoning": "brief"}}
  ],
  "individual": {{"0": "short instruction"}},
  "communal": "short group instruction",
  "team_task": {{"faction_id": 0, "task": "build workshop", "count": 3, "reasoning": "brief"}},
  "conditions": {{"hunger<50": "prioritize food"}},
  "faction_goals": [
    {{"faction_id": 0, "goal": "secure water access", "reasoning": "brief", "doctrine_key": "security"}}
  ],
  "event_framing": "One short council sentence for the observer log."
}}"""
        prompt += "\n\nDirectives:"
        return {
            "prompt": prompt,
            "reason": intervention_reason or "routine",
            "population": len(thronglets),
            "resource_count": sum(1 for resource in resources if not resource.collected),
            "building_count": len(buildings),
        }

    def queue_strategy_query(
        self,
        thronglets,
        resources,
        buildings,
        state_summary=None,
        intervention_reason=None,
        faction_manager=None,
    ):
        if not LLM_ENABLED or self.has_pending_llm_jobs():
            return False

        request = self._build_compact_strategy_request(
            thronglets,
            resources,
            buildings,
            state_summary=state_summary,
            intervention_reason=intervention_reason,
            faction_manager=faction_manager,
        )
        self.pending_strategy_job = start_async_llm_job(request["prompt"], "advisor", request)
        self.last_query_time = time.time()
        self.last_pop_count = len(thronglets)
        self.last_llm_error = None
        print(
            f"[Advisor] Queued async strategy review: pop={request['population']}, resources={request['resource_count']}, buildings={request['building_count']}"
        )
        return True

    def _apply_bounded_advisory_payload(self, advisory_payload, faction_manager=None):
        self.council_state = advisory_payload or advisory_payload_defaults()
        doctrine = dict(self.council_state.get("doctrine", {}))
        focus_mapping = {
            "survival": "population",
            "growth": "population",
            "industry": "infrastructure",
            "territory": "territory",
            "culture": "population",
            "health": "resources",
            "stability": "resources",
        }
        self.current_focus = focus_mapping.get(doctrine.get("focus"), self.current_focus)
        self.json_directives = {
            "individual": dict(self.council_state.get("individual", {})),
            "communal": str(self.council_state.get("communal", "")),
            "conditions": dict(self.council_state.get("conditions", {})),
        }
        if self.council_state.get("team_task"):
            self.json_directives["team_task"] = dict(self.council_state.get("team_task", {}))

        if faction_manager is not None:
            for faction in faction_manager.factions.values():
                faction.shared_goals = []
            for goal in self.council_state.get("faction_goals", []):
                faction = faction_manager.get_faction(goal.get("faction_id"))
                if faction is None:
                    continue
                doctrine_key = goal.get("doctrine_key") or faction.primary_doctrine
                faction.assign_shared_goal(goal.get("goal", ""), goal.get("reasoning", ""), doctrine_key)

        append_bounded_history(
            self.advisory_history,
            {
                "time": time.time(),
                "doctrine": doctrine,
                "strategic_priorities": list(self.council_state.get("strategic_priorities", [])),
                "event_framing": str(self.council_state.get("event_framing", "")),
            },
            10,
        )
        self.session_stats["current_doctrine"] = doctrine
        self.session_stats["current_advisory_priorities"] = list(self.council_state.get("strategic_priorities", []))

    def _apply_strategy_response(self, response_text, model_used, thronglets, resources, buildings, narrative_panel=None, faction_manager=None):
        self.last_model_used = model_used or self.last_model_used
        self.last_llm_error = None

        print(f"[Civilization Advisor] Async response from {model_used}: {response_text[:300]}...")

        advisory_payload = parse_advisory_payload(response_text)
        if advisory_payload is None:
            print("[Advisor] No intervention from LLM - civilization stable")
            self.council_state = advisory_payload_defaults()
            self.json_directives = {"individual": {}, "communal": "", "conditions": {}}
            self.directives = []
            intervened = False
        else:
            self._apply_bounded_advisory_payload(advisory_payload, faction_manager=faction_manager)
            validated_individual = {}
            for thronglet_id, instruction in list(self.json_directives.get("individual", {}).items()):
                directive = {"action": instruction, "priority": 8}
                is_valid, errors = self.validate_directive(directive, thronglets, buildings, resources)
                if is_valid:
                    validated_individual[thronglet_id] = instruction
                else:
                    print(f"[Directive Validation] Invalid directive for thronglet {thronglet_id}: {', '.join(errors)}")
            self.json_directives["individual"] = validated_individual
            self.directives = [
                {
                    "priority": max(1, min(10, int(round(priority.get("weight", 0.5) * 10)))),
                    "action": str(priority.get("key", "monitor")),
                    "reasoning": str(priority.get("reasoning", "Council priority")),
                }
                for priority in self.council_state.get("strategic_priorities", [])[:3]
                if isinstance(priority, dict)
            ]
            intervened = bool(
                self.json_directives.get("individual")
                or self.json_directives.get("communal")
                or self.json_directives.get("conditions")
                or self.json_directives.get("team_task")
                or self.council_state.get("faction_goals")
                or self.directives
            )

        if not intervened and response_text and ("build" in response_text.lower() or "gather" in response_text.lower()):
            self.directives = [
                {
                    "priority": 5,
                    "action": response_text[:50],
                    "reasoning": "LLM response (format may be incorrect)",
                }
            ]
            intervened = True

        if narrative_panel and self.council_state.get("event_framing"):
            narrative_panel.add_message(self.council_state["event_framing"], "Strategy")

        history_entry = {
            "time": time.time(),
            "summary": response_text[:200],
            "directives": self.directives.copy(),
            "directive_count": len(self.directives),
        }
        self.history.append(history_entry)
        if len(self.history) > 5:
            self.history.pop(0)

        return {"intervened": intervened}

    def _apply_strategy_failure(self, error, thronglets, buildings):
        self.last_llm_error = str(error)
        print(f"[Civilization Advisor] Async query failed: {error}")
        print(f"[Civilization Advisor] Make sure Ollama is running: 'ollama serve'")
        print(f"[Civilization Advisor] Install a model: 'ollama pull {PREFERRED_OLLAMA_MODEL}'")

        building_counts = {btype: 0 for btype in BUILDING_DEFINITIONS}
        for building in buildings:
            building_counts[building.building_type] = building_counts.get(building.building_type, 0) + 1

        if len(thronglets) < 3:
            fallback_action = "gather food and wood to build first house"
        elif building_counts.get("well", 0) < len(thronglets) // 10:
            fallback_action = "build 1 well immediately"
        elif building_counts.get("farm", 0) < len(thronglets) / 2:
            fallback_action = "build farms for food production"
        else:
            fallback_action = "continue gathering resources"

        self.council_state = advisory_payload_defaults()
        self.json_directives = {"individual": {}, "communal": "", "conditions": {}}
        self.directives = [
            {"priority": 5, "action": fallback_action, "reasoning": f"LLM unavailable - {fallback_action}"}
        ]
        return {"intervened": True}

    def _build_goal_assignment_request(self, thronglets, buildings):
        settlement = self.current_settlement_state or {}
        avg_hunger = sum(t.needs["hunger"] for t in thronglets) / max(1, len(thronglets))
        thronglet_snapshot = "\n".join(
            [
                f"- {t.id}: role={t.role or 'unassigned'}, hunger={int(t.needs['hunger'])}, energy={int(t.needs['energy'])}, morale={int(getattr(t, 'morale', 65))}, biome={t.favorite_biome}"
                for t in thronglets[:8]
            ]
        ) or "- none"

        prompt = f"""Assign at most 3 personal goals to specific thronglets.
Respond with plain lines only.
No markdown. No JSON. No <think> tags.

Colony:
- Population: {len(thronglets)}
- Buildings: {len(buildings)}
- Avg hunger: {avg_hunger:.0f}
- Research points: {self.research_points}
- District: {settlement.get('district_identity', 'homestead')}
- Prosperity: {int(settlement.get('prosperity_score', 0.0) * 100)}%
- Culture: {int(settlement.get('culture_score', 0.0) * 100)}%

Thronglets:
{thronglet_snapshot}

Format:
thronglet_id|goal_type|target|reasoning

Goal types:
{chr(10).join(format_goal_type_lines())}

Directives:"""
        return {"prompt": prompt, "assigned_at": time.time()}

    def _apply_goal_assignments(self, response_text, thronglets, assigned_at):
        assignments = 0
        for line in sanitize_llm_response(response_text).split("\n"):
            line = line.strip()
            if "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            try:
                thronglet_id = int(parts[0].strip())
            except ValueError:
                continue

            goal_type = parts[1].strip()
            target = parts[2].strip() if len(parts) > 2 else "auto"
            reason = parts[3].strip() if len(parts) > 3 else "LLM assigned"
            for thronglet in thronglets:
                if thronglet.id == thronglet_id:
                    thronglet.personal_goal = {"type": goal_type, "target": target, "reason": reason}
                    thronglet.goal_assigned_time = assigned_at
                    assignments += 1
                    print(f"[Goal] Thronglet {thronglet_id} assigned: {goal_type}")
                    break
        return assignments

    def poll_async_jobs(self, thronglets, resources, buildings, narrative_panel=None, faction_manager=None):
        if self.pending_strategy_job and self.pending_strategy_job["done"].is_set():
            job = self.pending_strategy_job
            self.pending_strategy_job = None
            self.last_job_completed_at = time.time()
            self.intervention_stats["total_queries"] += 1

            if job.get("error") is not None:
                result = self._apply_strategy_failure(job["error"], thronglets, buildings)
            else:
                result = self._apply_strategy_response(
                    job.get("response_text", ""),
                    job.get("model_used"),
                    thronglets,
                    resources,
                    buildings,
                    narrative_panel=narrative_panel,
                    faction_manager=faction_manager,
                )
                self.query_count += 1

            self.process_communal_tasks(thronglets, buildings, resources, faction_manager)
            if result.get("intervened"):
                self.intervention_stats["interventions"] += 1
                if job.get("metadata", {}).get("reason") == "crisis":
                    self.intervention_stats["crisis_interventions"] += 1
                if self.directives and narrative_panel:
                    top_directive = max(self.directives, key=lambda directive: directive["priority"])
                    narrative_panel.add_message(f"The Advisor: {top_directive['reasoning']}", "Strategy")
            else:
                self.intervention_stats["no_changes"] += 1

        if self.pending_goal_job and self.pending_goal_job["done"].is_set():
            job = self.pending_goal_job
            self.pending_goal_job = None
            self.last_job_completed_at = time.time()
            if job.get("error") is not None:
                self.last_llm_error = str(job["error"])
                print(f"[Goal Assignment] Error: {job['error']}")
            else:
                self.last_model_used = job.get("model_used") or self.last_model_used
                self.last_llm_error = None
                self._apply_goal_assignments(
                    job.get("response_text", ""),
                    thronglets,
                    job.get("metadata", {}).get("assigned_at", time.time()),
                )
    
    def parse_directives(self, response_text):
        """Parse LLM response into structured directives"""
        self.directives = []
        lines = sanitize_llm_response(response_text).split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Look for format: priority|action|reasoning
            if '|' in line:
                parts = line.split('|')
                if len(parts) >= 2:  # At least priority and action
                    try:
                        priority_str = parts[0].strip()
                        # Extract number from priority (handle "9" or "priority: 9" or "9.")
                        priority = int(''.join(filter(str.isdigit, priority_str))) if priority_str else 5
                        priority = max(1, min(10, priority))  # Clamp to 1-10
                        
                        action = parts[1].strip()
                        reasoning = parts[2].strip() if len(parts) >= 3 else "No reasoning provided"
                        
                        self.directives.append({
                            'priority': priority,
                            'action': action,
                            'reasoning': reasoning
                        })
                        print(f"[Directive] Priority {priority}: {action} - {reasoning}")
                    except (ValueError, IndexError) as e:
                        # Try alternative parsing - look for numbers followed by action words
                        if any(word in line.lower() for word in ['build', 'gather', 'explore', 'assign']):
                            # Extract a priority number if present
                            numbers = [int(s) for s in line.split() if s.isdigit() and 1 <= int(s) <= 10]
                            priority = numbers[0] if numbers else 5
                            action = line
                            self.directives.append({
                                'priority': priority,
                                'action': action,
                                'reasoning': 'Parsed from alternative format'
                            })
                            print(f"[Directive] Priority {priority} (alt format): {action}")
                        continue
        
        # Sort by priority (highest first)
        self.directives.sort(key=lambda d: d['priority'], reverse=True)
        
        return {'directives': self.directives}
    
    def parse_json_directives(self, response_text):
        """Parse LLM JSON response into structured directives"""
        import json
        import re
        response_text = sanitize_llm_response(response_text)
        
        # Check for explicit no-intervention responses
        if any(phrase in response_text.lower() for phrase in ['no changes', 'no intervention', 'monitoring', 'progressing well']):
            print("[Advisor] LLM Assessment: No intervention needed")
            self.stability_counter += 1
            # Reset JSON directives to empty
            self.json_directives = {
                'individual': {},
                'communal': '',
                'conditions': {}
            }
            return None  # Return None to skip directive processing
        
        # Reset stability counter if intervening
        self.stability_counter = 0
        
        # Reset JSON directives
        self.json_directives = {
            'individual': {},
            'communal': '',
            'conditions': {}
        }
        
        # Try to extract JSON from response
        # Look for JSON block (between ```json and ``` or between { and })
        json_pattern = r'```json\s*(\{.*?\})\s*```'
        match = re.search(json_pattern, response_text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Look for JSON object directly
            json_match = re.search(r'\{[^{}]*"individual"[^{}]*\{[^{}]*\}[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                # Try to find any JSON-like structure
                brace_start = response_text.find('{')
                if brace_start != -1:
                    brace_end = response_text.rfind('}')
                    if brace_end > brace_start:
                        json_str = response_text[brace_start:brace_end+1]
                    else:
                        return self.json_directives
                else:
                    return self.json_directives
        
        try:
            # Parse JSON
            parsed = json.loads(json_str)
            
            # Extract individual directives
            if 'individual' in parsed and isinstance(parsed['individual'], dict):
                for thronglet_id_str, instruction in parsed['individual'].items():
                    try:
                        thronglet_id = int(thronglet_id_str)
                        self.json_directives['individual'][thronglet_id] = str(instruction)
                        print(f"[JSON Directive] Assigned to thronglet {thronglet_id}: {instruction}")
                    except (ValueError, TypeError):
                        print(f"[JSON Directive] Warning: Invalid thronglet ID: {thronglet_id_str}")
            
            # Extract communal task
            if 'communal' in parsed and parsed['communal']:
                self.json_directives['communal'] = str(parsed['communal'])
                print(f"[JSON Directive] Communal task: {parsed['communal']}")
            
            # Extract conditions
            if 'conditions' in parsed and isinstance(parsed['conditions'], dict):
                for condition, behavior in parsed['conditions'].items():
                    self.json_directives['conditions'][condition] = str(behavior)
                    print(f"[JSON Directive] Condition: {condition} -> {behavior}")
            
            # Extract team_task (for faction-based team assignments)
            if 'team_task' in parsed and isinstance(parsed['team_task'], dict):
                team_task_data = parsed['team_task']
                self.json_directives['team_task'] = team_task_data
                print(f"[JSON Directive] Team task: {team_task_data}")
            
        except json.JSONDecodeError as e:
            print(f"[JSON Directive] Failed to parse JSON: {e}")
            print(f"[JSON Directive] Attempted to parse: {json_str[:200]}...")
            # Fall back to legacy parse_directives if JSON fails
            self.parse_directives(response_text)
        
        return self.json_directives
    
    def process_communal_tasks(self, thronglets, buildings, resources, faction_manager=None):
        """Process communal task descriptions and create GroupTask objects"""
        import re
        
        # Clear old inactive tasks
        self.group_tasks = [task for task in self.group_tasks if task.active]
        
        # Process team_task (faction-based team assignments)
        if 'team_task' in self.json_directives and isinstance(self.json_directives['team_task'], dict):
            team_task_data = self.json_directives['team_task']
            faction_id = team_task_data.get('faction_id')
            task_description = team_task_data.get('task', '')
            required_count = team_task_data.get('count', 3)
            
            if faction_manager and faction_id is not None:
                faction = faction_manager.get_faction(faction_id)
                if faction:
                    # Determine task type from description
                    task_type = 'build'
                    target_building_type = None
                    if 'gather' in task_description.lower():
                        task_type = 'gather'
                    elif 'explore' in task_description.lower():
                        task_type = 'explore'
                    elif 'build' in task_description.lower():
                        task_type = 'build'
                        for btype in ['farm', 'house', 'storage', 'workshop', 'shrine', 'well']:
                            if btype in task_description.lower():
                                target_building_type = btype
                                break
                        if target_building_type is None:
                            preferred = faction.doctrine_profile.get("preferred_buildings", [])
                            target_building_type = preferred[0] if preferred else None
                    
                    # Create GroupTask with faction pre-assigned members
                    new_task = GroupTask(
                        task_type=task_type,
                        description=task_description,
                        required_count=required_count,
                        target_building_type=target_building_type
                    )
                    new_task.faction_id = faction_id
                    
                    # Pre-assign faction members to task
                    for member_id in faction.member_ids[:required_count]:  # Assign up to required_count
                        new_task.add_thronglet(member_id)
                    
                    self.group_tasks.append(new_task)
                    print(f"[Group Task] Created faction task: {task_type} for faction {faction_id} ({len(new_task.assigned_thronglets)}/{required_count} assigned)")

        if faction_manager:
            existing_signatures = {
                (task.faction_id, task.description.strip().lower())
                for task in self.group_tasks
                if getattr(task, "faction_id", None) is not None
            }
            for faction in faction_manager.factions.values():
                if not faction.shared_goals:
                    continue
                latest_goal = faction.shared_goals[-1]
                goal_text = str(latest_goal.get("goal", "")).strip()
                if not goal_text:
                    continue
                signature = (faction.id, goal_text.lower())
                if signature in existing_signatures:
                    continue
                task_type = "build"
                target_building_type = None
                lowered_goal = goal_text.lower()
                if "gather" in lowered_goal or "secure" in lowered_goal:
                    task_type = "gather"
                elif "explore" in lowered_goal or "scout" in lowered_goal:
                    task_type = "explore"
                elif "build" in lowered_goal or "raise" in lowered_goal:
                    task_type = "build"
                for btype in BUILDING_DEFINITIONS:
                    if btype in lowered_goal:
                        target_building_type = btype
                        break
                if task_type == "build" and target_building_type is None:
                    preferred = faction.doctrine_profile.get("preferred_buildings", [])
                    target_building_type = preferred[0] if preferred else None
                new_task = GroupTask(
                    task_type=task_type,
                    description=goal_text,
                    required_count=max(2, min(4, len(faction.member_ids))),
                    target_building_type=target_building_type,
                )
                new_task.faction_id = faction.id
                for member_id in faction.member_ids[: new_task.required_count]:
                    new_task.add_thronglet(member_id)
                self.group_tasks.append(new_task)
                existing_signatures.add(signature)
                print(f"[Group Task] Doctrine task: {task_type} for faction {faction.id}")
        
        communal_str = self.json_directives.get('communal', '')
        if not communal_str:
            return
        
        # Parse communal task descriptions
        # Examples: "Form party of 3 for building", "Coordinate gathering party of 2"
        party_match = re.search(r'party of (\d+)', communal_str.lower())
        if party_match:
            required_count = int(party_match.group(1))
        else:
            required_count = 3  # Default
        
        # Determine task type
        task_type = 'build'
        target_building_type = None
        if 'gather' in communal_str.lower():
            task_type = 'gather'
        elif 'explore' in communal_str.lower():
            task_type = 'explore'
        elif 'build' in communal_str.lower():
            task_type = 'build'
            # Extract building type
            for btype in ['farm', 'house', 'storage', 'workshop', 'shrine', 'well']:
                if btype in communal_str.lower():
                    target_building_type = btype
                    break
        
        # Create or update group task
        existing_task = None
        for task in self.group_tasks:
            if task.task_type == task_type and task.target_building_type == target_building_type:
                existing_task = task
                break
        
        if not existing_task:
            new_task = GroupTask(
                task_type=task_type,
                description=communal_str,
                required_count=required_count,
                target_building_type=target_building_type
            )
            self.group_tasks.append(new_task)
            print(f"[Group Task] Created: {task_type} party of {required_count}")
        else:
            existing_task.required_count = max(existing_task.required_count, required_count)
    
    def evaluate_condition(self, condition_str, thronglets, buildings, resources):
        """Evaluate a condition string (e.g., "hunger<50", "population>5")"""
        import re
        
        # Parse condition: metric<value or metric>value
        match = re.match(r'(\w+)([<>]=?)(\d+)', condition_str.strip())
        if not match:
            return False
        
        metric = match.group(1).lower()
        operator = match.group(2)
        value = int(match.group(3))
        
        num_thronglets = len(thronglets)
        
        # Evaluate metrics
        if metric == 'hunger':
            if thronglets:
                avg_hunger = sum(t.needs['hunger'] for t in thronglets) / len(thronglets)
                if operator == '<':
                    return avg_hunger < value
                elif operator == '<=':
                    return avg_hunger <= value
                elif operator == '>':
                    return avg_hunger > value
                elif operator == '>=':
                    return avg_hunger >= value
        elif metric == 'population':
            if operator == '>':
                return num_thronglets > value
            elif operator == '>=':
                return num_thronglets >= value
            elif operator == '<':
                return num_thronglets < value
            elif operator == '<=':
                return num_thronglets <= value
        elif metric == 'energy':
            if thronglets:
                avg_energy = sum(t.needs['energy'] for t in thronglets) / len(thronglets)
                if operator == '<':
                    return avg_energy < value
                elif operator == '<=':
                    return avg_energy <= value
                elif operator == '>':
                    return avg_energy > value
                elif operator == '>=':
                    return avg_energy >= value
        
        return False
    
    def get_individual_directive(self, thronglet_id):
        """Get individual directive for a specific thronglet"""
        return self.json_directives.get('individual', {}).get(thronglet_id, None)
    
    def get_conditional_behaviors(self, thronglets, buildings, resources):
        """Evaluate conditions and return active behaviors"""
        active_behaviors = []
        conditions = self.json_directives.get('conditions', {})
        
        for condition, behavior in conditions.items():
            if self.evaluate_condition(condition, thronglets, buildings, resources):
                active_behaviors.append(behavior)
                print(f"[Conditional] Active: {condition} -> {behavior}")
                
                # Parse conditional behavior into directive format
                # Example: "All gatherers prioritize food" -> directive
                if 'prioritize' in behavior.lower():
                    if 'gatherer' in behavior.lower() or 'all' in behavior.lower():
                        # Add as high-priority directive
                        active_behaviors.append({
                            'priority': 7,
                            'action': behavior,
                            'reasoning': f'Conditional: {condition}'
                        })
        
        return active_behaviors
    
    def validate_directive(self, directive, thronglets, buildings, resources):
        """Validate if a directive is feasible given current game state"""
        action = directive.get('action', '').lower()
        errors = []
        
        # Check building directives
        if 'build' in action:
            required_wood = 0
            required_stone = 0
            building_type = None
            
            if 'farm' in action:
                building_type = 'farm'
                required_wood = 5
            elif 'storage' in action:
                building_type = 'storage'
                required_wood = 3
            elif 'house' in action:
                building_type = 'house'
                required_wood = 4
            elif 'workshop' in action:
                building_type = 'workshop'
                required_wood = 6
                required_stone = 4
            elif 'shrine' in action:
                building_type = 'shrine'
                required_wood = 8
                required_stone = 5
            elif 'well' in action:
                building_type = 'well'
                required_stone = 3
            
            if building_type:
                # Check if directive is conditional (e.g., "when wood available")
                # Conditional directives are valid even if resources aren't available yet
                is_conditional = any(phrase in action for phrase in ['when', 'if available', 'once', 'after'])
                
                if not is_conditional:
                    # Only validate resource availability for non-conditional directives
                    # Check if any thronglet has resources (using pooled resources)
                    total_wood = sum(t.inventory['wood'] for t in thronglets)
                    total_stone = sum(t.inventory['stone'] for t in thronglets)
                    
                    if total_wood < required_wood:
                        errors.append(f"Insufficient wood: need {required_wood}, have {total_wood}")
                    if total_stone < required_stone:
                        errors.append(f"Insufficient stone: need {required_stone}, have {total_stone}")
        
        # Check gathering directives
        elif 'gather' in action or 'collect' in action:
            resource_type = None
            if 'wood' in action:
                resource_type = 'wood'
            elif 'food' in action:
                resource_type = 'food'
            elif 'stone' in action:
                resource_type = 'stone'
            
            if resource_type:
                available = sum(1 for r in resources if r.resource_type == resource_type and not r.collected)
                if available == 0:
                    errors.append(f"No {resource_type} resources available on map")
        
        # Check population requirements for communal tasks
        if 'party' in action or 'group' in action:
            # Extract number from "party of 3" etc.
            import re
            party_match = re.search(r'(\d+)', action)
            if party_match:
                required_pop = int(party_match.group(1))
                if len(thronglets) < required_pop:
                    errors.append(f"Insufficient population: need {required_pop}, have {len(thronglets)}")
        
        return len(errors) == 0, errors
    
    def parse_evolution_commands(self, response_text, narrative_panel, thronglets, resources, buildings):
        """Parse and execute evolution commands from LLM"""
        lines = sanitize_llm_response(response_text).split('\n')
        
        for line in lines:
            if line.startswith('TECH|'):
                parts = line.split('|')
                if len(parts) >= 2:
                    tech_id = parts[1].strip()
                    if tech_id in self.tech_tree and tech_id not in self.game_modifiers.tech_unlocked:
                        tech = self.tech_tree[tech_id]
                        if self.research_points >= tech['cost']:
                            # Check prerequisites
                            if all(req in self.game_modifiers.tech_unlocked for req in tech.get('requires', [])):
                                self.research_points -= tech['cost']
                                self.points_spent += tech['cost']
                                self.game_modifiers.tech_unlocked.add(tech_id)
                                # Apply permanent effects
                                for mechanic, value in tech['effect'].items():
                                    self.game_modifiers.permanent[mechanic] = value
                                narrative_panel.add_message(f"TECH UNLOCKED: {tech['name']}!", 'Achievement')
                                print(f"[Evolution] Unlocked tech: {tech['name']}")
            
            elif line.startswith('EVOLVE|'):
                parts = line.split('|')
                if len(parts) >= 3:
                    mechanic = parts[1].strip()
                    try:
                        multiplier = float(parts[2].strip())
                        multiplier = max(0.5, min(2.0, multiplier))  # Clamp to range
                        
                        # Calculate cost (scales with usage)
                        times_used = self.game_modifiers.temporary.get(mechanic + '_count', 0)
                        cost = int(50 * (1.5 ** times_used))
                        
                        if self.research_points >= cost:
                            self.research_points -= cost
                            self.points_spent += cost
                            end_time = time.time() + 120  # 2 minutes
                            self.game_modifiers.temporary[mechanic] = (multiplier, end_time)
                            self.game_modifiers.temporary[mechanic + '_count'] = times_used + 1
                            narrative_panel.add_message(f"EVOLVE: {mechanic} -> {multiplier:.1f}x for 2min", 'Strategy')
                            print(f"[Evolution] Applied modifier: {mechanic} = {multiplier}x")
                    except ValueError:
                        pass
            
            elif line.startswith('ABILITY|'):
                parts = line.split('|')
                if len(parts) >= 2:
                    ability_name = parts[1].strip()
                    if ability_name in self.abilities:
                        ability = self.abilities[ability_name]
                        if self.research_points >= ability['cost']:
                            self.research_points -= ability['cost']
                            self.points_spent += ability['cost']
                            
                            if ability.get('instant'):
                                if ability_name == 'heal_wave':
                                    for t in thronglets:
                                        t.health = min(100, t.health + 50)
                                    narrative_panel.add_message("HEAL WAVE: All thronglets +50 health!", 'Achievement')
                                elif ability_name == 'resource_blessing':
                                    for _ in range(5):
                                        x = random.randint(50, WINDOW_WIDTH - 50)
                                        y = random.randint(50, WINDOW_HEIGHT - 50)
                                        rtype = random.choice(['food', 'wood', 'stone'])
                                        resources.append(Resource(x, y, rtype))
                                    narrative_panel.add_message("RESOURCE BLESSING: 5 resources spawned!", 'Achievement')
                            else:
                                # Apply temporary modifier
                                end_time = time.time() + ability['duration']
                                for mechanic, value in ability['effect'].items():
                                    self.game_modifiers.temporary[mechanic] = (value, end_time)
                                narrative_panel.add_message(f"ABILITY: {ability_name} active!", 'Strategy')
            
            elif line.startswith('CHALLENGE|'):
                if time.time() > self.challenge_cooldown:
                    parts = line.split('|')
                    if len(parts) >= 2:
                        challenge_type = parts[1].strip().lower()
                        self.spawn_challenge(challenge_type, thronglets, resources, buildings, narrative_panel)
                        self.challenge_cooldown = time.time() + 180  # 3 min cooldown
    
    def spawn_challenge(self, challenge_type, thronglets, resources, buildings, narrative_panel):
        """Spawn emergent challenges"""
        if challenge_type == 'drought':
            challenge = {
                'type': 'drought',
                'start_time': time.time(),
                'duration': 90,
                'reward': 150,
                'active': True
            }
            self.active_challenges.append(challenge)
            narrative_panel.add_message("CHALLENGE: Drought! Wells disabled for 90s", 'Crisis')
        elif challenge_type == 'plague':
            challenge = {
                'type': 'plague',
                'start_time': time.time(),
                'duration': 60,
                'reward': 200,
                'active': True
            }
            self.active_challenges.append(challenge)
            narrative_panel.add_message("CHALLENGE: Plague outbreak! Disease risk 5x", 'Crisis')
        elif challenge_type == 'bounty':
            # Spawn bonus resources
            for _ in range(10):
                x = random.randint(50, WINDOW_WIDTH - 50)
                y = random.randint(50, WINDOW_HEIGHT - 50)
                resources.append(Resource(x, y, random.choice(['food', 'wood', 'stone'])))
            challenge = {
                'type': 'bounty',
                'start_time': time.time(),
                'duration': 60,
                'reward': 100,
                'collected': 0,
                'target': 10,
                'active': True
            }
            self.active_challenges.append(challenge)
            narrative_panel.add_message("CHALLENGE: Resource bounty! Collect 10 in 60s", 'Achievement')
    
    def assign_individual_goals(self, thronglets, buildings, resources, world_map):
        """Queue personal goal generation without blocking the main loop."""
        current_time = time.time()

        # Only assign goals every 60 seconds to avoid spam
        if current_time - getattr(self, 'last_goal_assignment', current_time) < GOAL_ASSIGNMENT_INTERVAL:
            return

        # Avoid back-to-back advisor + goals LLM requests in the same moment.
        if current_time - getattr(self, 'last_query_time', 0) < POST_ADVISOR_GOAL_COOLDOWN:
            return
        
        self.last_goal_assignment = current_time
        
        # Skip if no thronglets
        if not thronglets:
            return
        
        # Skip quietly if LLM support is disabled or unavailable
        if not LLM_ENABLED:
            return

        if self.has_pending_llm_jobs():
            return

        request = self._build_goal_assignment_request(thronglets, buildings)
        self.pending_goal_job = start_async_llm_job(request["prompt"], "goals", request)
        self.last_goal_assignment = current_time
        self.last_llm_error = None
        print(f"[Goal Assignment] Queued async personal goals for {len(thronglets)} thronglets")
    
    def calculate_difficulty(self, thronglets, buildings):
        """Calculate challenge difficulty based on progress"""
        building_score = sum(1 for b in buildings)
        tech_score = len(self.game_modifiers.tech_unlocked) * 2
        total_score = building_score + tech_score
        
        # Scale: 1.0 at 0, 2.0 at 20, 3.0 at 50
        return 1.0 + (total_score / DIFFICULTY_SCALING_FACTOR)


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
    """Environmental hazards that affect thronglets"""
    def __init__(self, x, y, hazard_type, radius=100):
        self.x = x
        self.y = y
        self.hazard_type = hazard_type  # 'quicksand', 'avalanche_zone', 'flood_zone', 'predator_lair'
        self.radius = radius
        self.active = True
        self.damage_rate = 0.5  # Health loss per second
        
    def check_affect(self, thronglet):
        """Check if thronglet is in range and apply effects"""
        if not self.active:
            return
        
        distance = math.sqrt((self.x - thronglet.x)**2 + (self.y - thronglet.y)**2)
        if distance < self.radius:
            # Apply hazard effects
            if self.hazard_type == 'quicksand':
                # Slow movement
                thronglet.needs['energy'] = max(0, thronglet.needs['energy'] - 0.3)
            elif self.hazard_type == 'avalanche_zone':
                # Chance to take damage
                if random.random() < 0.1:
                    thronglet.health = max(0, thronglet.health - 20)
            elif self.hazard_type == 'flood_zone':
                # Increase disease risk
                thronglet.contract_disease(DISEASE_CHANCE_BASE * 10)
            elif self.hazard_type == 'predator_lair':
                # Chance of attack
                if random.random() < 0.15:
                    thronglet.health = max(0, thronglet.health - 30)
    
    def draw(self, surface):
        """Draw hazard marker"""
        if self.active:
            # Pulsing warning circle
            pulse = int(5 + 3 * math.sin(time.time() * 4))
            
            hazard_colors = {
                'quicksand': (139, 90, 43),
                'avalanche_zone': (255, 255, 255),
                'flood_zone': (64, 164, 223),
                'predator_lair': (255, 0, 0)
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
    
    def draw(self, surface, thronglets=None):
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
            
            # Check if any thronglet is nearby for glow effect
            nearby = False
            if thronglets:
                for thronglet in thronglets:
                    distance = math.sqrt((self.x - thronglet.x)**2 + (self.y - thronglet.y)**2)
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
    
    def check_collision(self, thronglet):
        """Check if thronglet is within collection distance"""
        if self.collected:
            return False
        distance = math.sqrt((self.x - thronglet.x)**2 + (self.y - thronglet.y)**2)
        return distance < RESOURCE_COLLISION_DIST


class Season:
    """Manages seasonal cycles"""
    def __init__(self):
        self.current = 'spring'  # spring, summer, autumn, winter
        self.start_time = time.time()
    
    def update(self, game_time):
        """Cycle through seasons"""
        # Calculate season based on elapsed game time
        elapsed = game_time % (SEASON_LENGTH * 4)  # Full cycle = 4 seasons
        season_index = int(elapsed / SEASON_LENGTH)
        
        seasons = ['spring', 'summer', 'autumn', 'winter']
        self.current = seasons[season_index]
    
    def get_resource_modifier(self):
        """Return resource spawn modifiers for current season"""
        modifiers = {
            'spring': {'food': 1.2, 'wood': 1.0, 'stone': 1.0},
            'summer': {'food': 1.0, 'wood': 1.0, 'stone': 1.0},
            'autumn': {'food': 1.3, 'wood': 1.1, 'stone': 1.0},
            'winter': {'food': 0.5, 'wood': 0.8, 'stone': 1.2}
        }
        return modifiers.get(self.current, modifiers['summer'])


class WeatherSystem:
    """Random weather events"""
    def __init__(self):
        self.current_weather = 'clear'
        self.next_event_time = time.time() + random.uniform(45, 90)  # First event in 45-90 seconds
    
    def check_event(self, current_time, difficulty=1.0, season_name='summer'):
        """Check for weather events"""
        if current_time >= self.next_event_time:
            weights = {
                'clear': 0.44,
                'rain': 0.24,
                'storm': 0.14,
                'drought': 0.12,
                'aurora': 0.06,
            }

            if season_name == 'winter':
                weights['aurora'] += 0.08
                weights['rain'] -= 0.08
            elif season_name == 'summer':
                weights['drought'] += 0.07
            elif season_name == 'spring':
                weights['rain'] += 0.10
                weights['drought'] -= 0.04
            elif season_name == 'autumn':
                weights['storm'] += 0.06

            if difficulty > 1.0:
                weights['storm'] += 0.04 * difficulty
                weights['drought'] += 0.03 * difficulty
                weights['clear'] = max(0.18, weights['clear'] - 0.05 * difficulty)

            total_weight = sum(max(0.0, weight) for weight in weights.values())
            roll = random.random() * total_weight
            cumulative = 0.0
            event_type = 'clear'
            for weather_name, weight in weights.items():
                cumulative += max(0.0, weight)
                if roll <= cumulative:
                    event_type = weather_name
                    break
            self.current_weather = event_type
            self.next_event_time = current_time + random.uniform(30, 60)  # Next event in 30-60 seconds
            return {'type': event_type, 'duration': 20}  # Event lasts 20 seconds
        return None
    
    def get_effects(self):
        """Return current weather effects"""
        effects = {
            'clear': {},
            'rain': {'food': 0.15, 'thirst': 0.04, 'happiness': 4},
            'storm': {'energy': -0.05, 'happiness': -10},
            'drought': {'thirst': -0.1, 'food': -0.5, 'happiness': -6},
            'aurora': {'happiness': 8, 'energy': 0.02},
        }
        return effects.get(self.current_weather, {})


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
    """Camera system for viewing the world"""
    def __init__(self, world_width, world_height):
        self.x = 0
        self.y = 0
        self.zoom_levels = tuple(float(level) for level in SNAP_ZOOM_LEVELS)
        self.zoom = 1.5
        self.min_zoom = min(self.zoom_levels)
        self.max_zoom = 3.0
        self.world_width = world_width
        self.world_height = world_height
        self.panning = False
        self.last_pan_pos = (0, 0)
        self.key_pan_speed = 200  # pixels per second at zoom 1.0
        self.smooth_factor = 0.15  # lerp interpolation
        self.follow_mode = False  # Auto-follow enabled
        self.follow_target_x = 0
        self.follow_target_y = 0
    
    def world_to_screen(self, world_x, world_y):
        """Transform world coordinates to screen coordinates"""
        screen_x = (world_x - self.x) * self.zoom
        screen_y = (world_y - self.y) * self.zoom
        return (screen_x, screen_y)
    
    def screen_to_world(self, screen_x, screen_y):
        """Transform screen coordinates to world coordinates"""
        world_x = (screen_x / self.zoom) + self.x
        world_y = (screen_y / self.zoom) + self.y
        return (world_x, world_y)
    
    def start_pan(self, screen_x, screen_y):
        """Start camera panning"""
        self.follow_mode = False  # Disable follow on manual control
        self.panning = True
        self.last_pan_pos = (screen_x, screen_y)
    
    def update_pan(self, screen_x, screen_y):
        """Update camera position during pan"""
        if self.panning:
            dx = (screen_x - self.last_pan_pos[0]) / self.zoom
            dy = (screen_y - self.last_pan_pos[1]) / self.zoom
            self.x -= dx
            self.y -= dy
            self.last_pan_pos = (screen_x, screen_y)
            self.clamp_camera()
    
    def stop_pan(self):
        """Stop camera panning"""
        self.panning = False
    
    def clamp_camera(self):
        """Keep camera within world bounds"""
        # Calculate max camera position based on zoom and world size
        if self.world_width <= WINDOW_WIDTH / self.zoom:
            max_x = 0
        else:
            max_x = self.world_width - WINDOW_WIDTH / self.zoom
        
        if self.world_height <= WINDOW_HEIGHT / self.zoom:
            max_y = 0
        else:
            max_y = self.world_height - WINDOW_HEIGHT / self.zoom
        
        self.x = max(0, min(self.x, max_x))
        self.y = max(0, min(self.y, max_y))

    def _snap_zoom(self, zoom):
        zoom = max(self.min_zoom, min(self.max_zoom, float(zoom)))
        return min(self.zoom_levels, key=lambda candidate: abs(candidate - zoom))

    def set_zoom(self, zoom):
        """Set zoom level"""
        self.zoom = self._snap_zoom(zoom)
        self.clamp_camera()

    def adjust_zoom(self, delta):
        """Adjust zoom by delta"""
        levels = [level for level in self.zoom_levels if self.min_zoom <= level <= self.max_zoom]
        current = self._snap_zoom(self.zoom)
        if delta > 0:
            for level in levels:
                if level > current:
                    self.zoom = level
                    self.clamp_camera()
                    return
        elif delta < 0:
            for level in reversed(levels):
                if level < current:
                    self.zoom = level
                    self.clamp_camera()
                    return
        self.zoom = current
        self.clamp_camera()
    
    def update_key_pan(self, keys_pressed, delta_time):
        """Smooth continuous panning with held keys"""
        if self.follow_mode:
            return  # Don't pan manually when in follow mode
        speed = self.key_pan_speed / self.zoom * delta_time
        if keys_pressed[pygame.K_w] or keys_pressed[pygame.K_UP]:
            self.y -= speed
        if keys_pressed[pygame.K_s] or keys_pressed[pygame.K_DOWN]:
            self.y += speed
        if keys_pressed[pygame.K_a] or keys_pressed[pygame.K_LEFT]:
            self.x -= speed
        if keys_pressed[pygame.K_d] or keys_pressed[pygame.K_RIGHT]:
            self.x += speed
        self.clamp_camera()
    
    def update_follow(self, thronglets):
        """Update camera to follow civilization center"""
        if not self.follow_mode or not thronglets:
            return
        
        # Calculate mean position
        mean_x = sum(t.x for t in thronglets) / len(thronglets)
        mean_y = sum(t.y for t in thronglets) / len(thronglets)
        
        # Smooth follow (lerp)
        self.follow_target_x = mean_x
        self.follow_target_y = mean_y
        
        target_cam_x = mean_x - WINDOW_WIDTH / (2 * self.zoom)
        target_cam_y = mean_y - WINDOW_HEIGHT / (2 * self.zoom)
        
        # Smooth interpolation
        self.x += (target_cam_x - self.x) * 0.05
        self.y += (target_cam_y - self.y) * 0.05
        self.clamp_camera()


class MapChunk:
    """A chunk of the world map"""
    def __init__(self, chunk_x, chunk_y, asset_manager=None, lazy_render=True, chunk_state=None):
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
        else:
            self.generate_biomes()
        self.surface = None  # Cached pre-rendered surface
        self.asset_manager = asset_manager
        self.surface_rendered = False
        
        # Lazy rendering: only render surface when first needed (much faster startup)
        if not lazy_render and asset_manager:
            self.render_surface()
    
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
    def __init__(self, asset_manager=None, scenario_profile=None, seed=None, snapshot_world=None):
        self.chunks = {}  # {(chunk_x, chunk_y): MapChunk}
        self.asset_manager = asset_manager
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
            self.chunks[(cx, cy)] = MapChunk(cx, cy, self.asset_manager, lazy_render=True, chunk_state=chunk_state)

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
    """A structure built by thronglets"""
    def __init__(self, x, y, building_type):
        self.x = x
        self.y = y
        self.building_type = building_type  # 'house', 'storage', 'farm', 'workshop', 'shrine', 'well'
        self.built_by = None  # Will store thronglet ID who built it
        self.occupants = []  # Thronglets currently using this building
        self.last_production_time = time.time()  # For farms
        self.stored_resources = {'food': 0, 'wood': 0, 'stone': 0}  # For storage/farms
        self.level = 1
        self.aura_strength = 0.0
    
    def update(self, delta_time, modifiers=None, weather_effects=None):
        """Update building state (production, etc.)"""
        # Farms produce food over time
        if self.building_type == 'farm':
            current_time = time.time()
            mod = modifiers.get_modifier('farm_production_rate') if modifiers else 1.0
            mod *= 1.0 + (self.level - 1) * 0.18
            
            # Apply weather drought effect (reduces production rate)
            if weather_effects and 'food' in weather_effects:
                # drought effect is -0.5, so multiply production time by (1 + abs(effect))
                # -0.5 makes production 1.5x slower
                mod *= (1.0 + abs(weather_effects['food']))
            
            production_time = 10.0 / mod
            if current_time - self.last_production_time >= production_time:
                self.stored_resources['food'] += 1
                # Optional: Consume wood for production (0.1 wood per production cycle)
                if self.stored_resources['wood'] > 0 and self.stored_resources['wood'] >= 0.1:
                    self.stored_resources['wood'] -= 0.1
                self.last_production_time = current_time
    
    def can_enter(self, thronglet, modifiers=None):
        """Check if thronglet can use this building"""
        if self.building_type == 'house':
            capacity = int((2 + max(0, self.level - 1)) * (modifiers.get_modifier('house_capacity') if modifiers else 1.0))
            return len(self.occupants) < capacity
        return True  # Other buildings have no capacity limit
    
    def enter(self, thronglet, modifiers=None):
        """Thronglet enters building"""
        if thronglet not in self.occupants and self.can_enter(thronglet, modifiers):
            self.occupants.append(thronglet)
            return True
        return False
    
    def leave(self, thronglet):
        """Thronglet leaves building"""
        if thronglet in self.occupants:
            self.occupants.remove(thronglet)
    
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
        status = font_small.render(
            f"Advisor: {llm_status}  |  Phase: {phase_label}  |  Score: {observer_score}  |  Follow: {follow_state}",
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
    def __init__(self, log_dir=None, log_level=None):
        self.session_start_time = datetime.now()
        self.session_id = f"{self.session_start_time.strftime('%Y%m%d_%H%M%S_%f')}_{os.getpid()}"
        self.log_dir = log_dir or RUNTIME_CONFIG.log_dir
        self.crash_count = 0
        self.error_log = []
        self.game_events = []
        self.log_level_name = (log_level or RUNTIME_CONFIG.log_level).upper()
        self.log_level = getattr(logging, self.log_level_name, logging.INFO)
        
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
        
        # Log session start
        self.logger.info(f"Game session started: {self.session_id}")
        self.logger.info(f"Log file location: {os.path.abspath(log_file)}")
        self.flush_logs()  # Ensure it's written
    
    def flush_logs(self):
        """Force flush all log handlers to ensure data is written"""
        if hasattr(self, 'file_handler'):
            self.file_handler.flush()
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
            'crash_count': self.crash_count,
            'total_events': len(self.game_events),
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


def center_camera_on_colony(camera, thronglets, buildings):
    anchors = [(thronglet.x, thronglet.y) for thronglet in thronglets]
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

    restored_thronglets = []
    max_thronglet_id = -1
    for thronglet_data in snapshot.get("thronglets", []):
        x = clamp(float(thronglet_data.get("x", world_width / 2)), 50.0, world_width - 50.0)
        y = clamp(float(thronglet_data.get("y", world_height / 2)), 50.0, world_height - 50.0)
        thronglet = Thronglet(x, y)

        saved_id = int(thronglet_data.get("id", thronglet.id))
        thronglet.id = saved_id
        max_thronglet_id = max(max_thronglet_id, saved_id)

        thronglet.role = thronglet_data.get("role")
        thronglet.health = clamp(float(thronglet_data.get("health", 100.0)), 0.0, 100.0)
        thronglet.happiness = clamp(float(thronglet_data.get("happiness", thronglet.happiness)), 0.0, 100.0)
        thronglet.morale = clamp(float(thronglet_data.get("morale", thronglet.morale)), 0.0, 100.0)
        thronglet.inspiration = clamp(float(thronglet_data.get("inspiration", thronglet.inspiration)), 0.0, 100.0)
        thronglet.favorite_biome = thronglet_data.get("favorite_biome") if thronglet_data.get("favorite_biome") in BIOME_TYPES else thronglet.favorite_biome
        thronglet.diseased = bool(thronglet_data.get("diseased", False))
        thronglet.resilience = float(thronglet_data.get("resilience", thronglet.resilience))
        thronglet.settlement_prosperity = float(thronglet_data.get("settlement_prosperity", thronglet.settlement_prosperity))
        thronglet.generation = max(0, int(thronglet_data.get("generation", getattr(thronglet, "generation", 0))))
        thronglet.parent_ids = [
            parsed_parent_id
            for parsed_parent_id in (_parse_optional_int(parent_id) for parent_id in thronglet_data.get("parent_ids", []))
            if parsed_parent_id is not None
        ]
        thronglet.lineage_id = _parse_optional_int(thronglet_data.get("lineage_id"), saved_id) or saved_id
        thronglet.mutation_count = max(0, int(thronglet_data.get("mutation_count", 0)))
        thronglet.birth_origin = str(thronglet_data.get("birth_origin", getattr(thronglet, "birth_origin", "founder")))

        personality_data = thronglet_data.get("personality", {})
        if isinstance(personality_data, dict):
            for trait_name in thronglet.personality:
                trait_value = personality_data.get(trait_name, thronglet.personality[trait_name])
                try:
                    thronglet.personality[trait_name] = clamp(float(trait_value), 0.0, 1.0)
                except (TypeError, ValueError):
                    continue

        genetics_data = thronglet_data.get("genetics", {})
        if isinstance(genetics_data, dict):
            for trait_name, trait_spec in GENETIC_TRAIT_SPECS.items():
                trait_value = genetics_data.get(trait_name, thronglet.genetics.get(trait_name, 1.0))
                try:
                    thronglet.genetics[trait_name] = clamp(float(trait_value), trait_spec["min"], trait_spec["max"])
                except (TypeError, ValueError):
                    continue

        skills_data = thronglet_data.get("skills", {})
        if isinstance(skills_data, dict):
            for skill_name, skill_state in skills_data.items():
                if skill_name not in thronglet.skills or not isinstance(skill_state, dict):
                    continue
                thronglet.skills[skill_name]["level"] = max(
                    1,
                    min(MAX_SKILL_LEVEL, int(skill_state.get("level", thronglet.skills[skill_name]["level"]))),
                )
                thronglet.skills[skill_name]["xp"] = max(
                    0.0,
                    float(skill_state.get("xp", thronglet.skills[skill_name]["xp"])),
                )

        bonds_data = thronglet_data.get("bonds", {})
        thronglet.bonds = {}
        if isinstance(bonds_data, dict):
            for other_id, bond_strength in bonds_data.items():
                parsed_other_id = _parse_optional_int(other_id)
                if parsed_other_id is None:
                    continue
                try:
                    thronglet.bonds[parsed_other_id] = max(0.0, float(bond_strength))
                except (TypeError, ValueError):
                    continue

        thronglet.faction_id = _parse_optional_int(thronglet_data.get("faction_id"))
        thronglet.known_resources = []
        for resource_entry in thronglet_data.get("known_resources", []):
            parsed_resource = _parse_coordinate_entry(resource_entry)
            if not parsed_resource:
                continue
            resource_x = clamp(parsed_resource[0], 0.0, world_width)
            resource_y = clamp(parsed_resource[1], 0.0, world_height)
            thronglet.known_resources.append((resource_x, resource_y))

        inventory = thronglet_data.get("inventory", {})
        for resource_name in thronglet.inventory:
            thronglet.inventory[resource_name] = max(0, int(inventory.get(resource_name, 0)))

        needs = thronglet_data.get("needs", {})
        for need_name in thronglet.needs:
            thronglet.needs[need_name] = clamp(float(needs.get(need_name, thronglet.needs[need_name])), 0.0, 100.0)

        thronglet.state = thronglet_data.get("state") or STATE_IDLE
        thronglet.current_action = thronglet_data.get("current_action") or "wander"
        thronglet.personal_goal = thronglet_data.get("personal_goal")
        thronglet.goal_progress = clamp(float(thronglet_data.get("goal_progress", 0.0)), 0.0, 1.0)

        age_seconds = max(0.0, float(thronglet_data.get("age_seconds", elapsed_seconds)))
        thronglet.birth_time = now - age_seconds
        thronglet.age = age_seconds
        disease_elapsed = max(0.0, float(thronglet_data.get("disease_elapsed", 0.0)))
        thronglet.disease_start_time = now - disease_elapsed if thronglet.diseased and disease_elapsed > 0 else 0.0
        reproduction_elapsed = max(0.0, float(thronglet_data.get("last_reproduction_elapsed", 0.0)))
        thronglet.last_reproduction_time = now - reproduction_elapsed if reproduction_elapsed > 0 else 0.0
        goal_assigned_elapsed = max(0.0, float(thronglet_data.get("goal_assigned_elapsed", 0.0)))
        thronglet.goal_assigned_time = now - goal_assigned_elapsed if goal_assigned_elapsed > 0 else 0.0
        thronglet.alive = thronglet.health > 0
        restored_thronglets.append(thronglet)

    if max_thronglet_id >= 0:
        Thronglet._next_id = max_thronglet_id + 1

    thronglet_lookup = {thronglet.id: thronglet for thronglet in restored_thronglets}
    restored_buildings = []
    building_occupancy_refs = []
    for building_data in snapshot.get("buildings", []):
        building_type = building_data.get("type")
        if building_type not in BUILDING_DEFINITIONS:
            continue

        x = clamp(float(building_data.get("x", world_width / 2)), 50.0, world_width - 50.0)
        y = clamp(float(building_data.get("y", world_height / 2)), 50.0, world_height - 50.0)
        building = Building(x, y, building_type)
        building.level = max(1, int(building_data.get("level", 1)))
        building.built_by = building_data.get("built_by")
        building.aura_strength = clamp(float(building_data.get("aura_strength", 0.0)), 0.0, 1.0)

        stored_resources = building_data.get("stored_resources", {})
        for resource_name in building.stored_resources:
            building.stored_resources[resource_name] = max(0.0, float(stored_resources.get(resource_name, 0.0)))

        restored_buildings.append(building)
        building_occupancy_refs.append((building, building_data.get("occupant_ids", [])))

    for building, occupant_ids in building_occupancy_refs:
        building.occupants = [
            thronglet_lookup[occupant_id]
            for occupant_id in (_parse_optional_int(saved_id) for saved_id in occupant_ids)
            if occupant_id in thronglet_lookup
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
        restored_task.assigned_thronglets = [
            parsed_id
            for parsed_id in (_parse_optional_int(thronglet_id) for thronglet_id in task_data.get("assigned_thronglets", []))
            if parsed_id is not None and parsed_id in thronglet_lookup
        ]
        restored_task.active = bool(task_data.get("active", True))
        restored_task.faction_id = _parse_optional_int(task_data.get("faction_id"))
        created_elapsed = max(0.0, float(task_data.get("created_elapsed", 0.0)))
        restored_task.created_time = now - created_elapsed if created_elapsed > 0 else now
        advisor.group_tasks.append(restored_task)
    advisor.last_query_time = now
    advisor.last_goal_assignment = now
    advisor.last_pop_count = len(restored_thronglets)
    advisor.last_llm_error = None

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
        territory_manager.last_population_count = len(restored_thronglets) + len(restored_buildings)
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
        for thronglet in restored_thronglets:
            thronglet.faction_id = None
        for faction_data in snapshot.get("factions", []):
            if not isinstance(faction_data, dict):
                continue
            member_ids = [
                member_id
                for member_id in (_parse_optional_int(raw_id) for raw_id in faction_data.get("member_ids", []))
                if member_id is not None and member_id in thronglet_lookup
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
            formed_elapsed = max(0.0, float(faction_data.get("formed_elapsed", 0.0)))
            restored_faction.formed_time = now - formed_elapsed if formed_elapsed > 0 else now
            faction_manager.factions[saved_faction_id] = restored_faction
            max_faction_id = max(max_faction_id, saved_faction_id)
            for member_id in member_ids:
                thronglet_lookup[member_id].faction_id = saved_faction_id
        if max_faction_id >= 0:
            Faction._next_id = max(Faction._next_id, max_faction_id + 1)
        for restored_faction in faction_manager.factions.values():
            restored_faction.refresh_identity(restored_thronglets)
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
    elif restored_thronglets:
        celebration_center = (
            sum(thronglet.x for thronglet in restored_thronglets) / len(restored_thronglets),
            sum(thronglet.y for thronglet in restored_thronglets) / len(restored_thronglets),
        )

    settlement_state = compute_settlement_snapshot(restored_thronglets, restored_buildings, None, season, weather_system)
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
        "thronglets": restored_thronglets,
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
            
            # Set window caption
            pygame.display.set_caption("Thronglets - AI Civilization Simulator")
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
    selected_scenario_id = str(shell_choice.get("scenario_id") or selected_scenario_id)
    scenario_profile = set_active_scenario(selected_scenario_id)

    # Initialize logging and crash tracking
    game_logger = GameLogger(log_dir=runtime_config.log_dir, log_level=runtime_config.log_level)
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
            if 'game_logger' in locals():
                game_logger.flush_logs()
                game_logger.logger.debug("Emergency exit flush completed")
                game_logger.flush_logs()
        except:
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
    print(f"[Scenario] {scenario_profile['name']} ({scenario_profile['id']})")
    
    print("Starting Thronglets...")
    
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
    _draw_loading("Loading Thronglets... Assets")
    asset_manager = AssetManager()
    print("Asset manager created")
    print(f"[DEBUG] Asset manager type: {type(asset_manager)}")
    _draw_loading("Loading Thronglets... World")
    world_map = WorldMap(
        asset_manager,
        scenario_profile=scenario_profile,
        seed=runtime_config.seed,
        snapshot_world=(snapshot_payload or {}).get("world"),
    )
    print(f"World map created with {len(world_map.chunks)} chunks")
    
    # Chunks use lazy rendering now - surfaces will be created when first rendered
    print(f"[DEBUG] Chunks created: {len(world_map.chunks)} (surfaces will be created on first render)")
    world_width = int(getattr(world_map, "world_width", INITIAL_CHUNKS_X * CHUNK_SIZE))
    world_height = int(getattr(world_map, "world_height", INITIAL_CHUNKS_Y * CHUNK_SIZE))
    _draw_loading("Loading Thronglets... Camera")
    camera = Camera(world_width, world_height)
    # Center camera on world initially to ensure chunks are visible
    camera.x = max(0, (world_width - WINDOW_WIDTH) / 2)
    camera.y = max(0, (world_height - WINDOW_HEIGHT) / 2)
    print(f"Camera initialized at ({camera.x:.1f}, {camera.y:.1f})")
    
    # Initialize thronglets - CLUSTERED SPAWN
    thronglets = []
    # Find safe spawn location (plains or forest biome preferred)
    safe_biomes = list(scenario_profile.get("spawn_biomes", ['plains', 'forest']))
    spawn_center_x, spawn_center_y = world_map.get_spawn_point(safe_biomes)
    
    print(f"Spawn center: ({spawn_center_x}, {spawn_center_y}) - Biome: {world_map.get_biome_at(spawn_center_x, spawn_center_y)}")
    
    # Center camera on spawn point and zoom in
    camera.x = max(0, min(spawn_center_x - WINDOW_WIDTH / 2, world_width - WINDOW_WIDTH))
    camera.y = max(0, min(spawn_center_y - WINDOW_HEIGHT / 2, world_height - WINDOW_HEIGHT))
    camera.set_zoom(1.5)
    
    # Validate camera position and zoom
    if not (0 <= camera.x <= world_width) or not (0 <= camera.y <= world_height):
        print(f"[WARNING] Invalid camera position ({camera.x}, {camera.y}), resetting to center")
        camera.x = max(0, min(world_width / 2 - WINDOW_WIDTH / 2, world_width - WINDOW_WIDTH))
        camera.y = max(0, min(world_height / 2 - WINDOW_HEIGHT / 2, world_height - WINDOW_HEIGHT))
    
    if camera.zoom <= 0 or camera.zoom > camera.max_zoom:
        print(f"[WARNING] Invalid zoom {camera.zoom}, resetting to 1.5")
        camera.set_zoom(1.5)

    # Ensure zoom is within bounds
    camera.set_zoom(camera.zoom)
    camera.follow_mode = True
    
    print(f"Camera positioned at ({camera.x:.0f}, {camera.y:.0f}) with zoom {camera.zoom}")
    print(f"[DEBUG] Camera world size: {camera.world_width}x{camera.world_height}")
    print(f"[DEBUG] Window size: {WINDOW_WIDTH}x{WINDOW_HEIGHT}")
    
    _draw_loading("Loading Thronglets... Spawning")
    # Spawn all thronglets clustered around center
    initial_population = max(1, int(scenario_profile.get("initial_population", INITIAL_POPULATION)))
    for _ in range(initial_population):
        angle = random.uniform(0, 2 * math.pi)
        distance = random.uniform(10, 30)  # 10-30 pixels from center
        x = spawn_center_x + distance * math.cos(angle)
        y = spawn_center_y + distance * math.sin(angle)
        # Ensure within bounds
        x = max(50, min(world_width - 50, x))
        y = max(50, min(world_height - 50, y))
        thronglets.append(Thronglet(x, y))
    
    _draw_loading("Loading Thronglets... Resources")
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
    
    _draw_loading("Loading Thronglets... Resources")
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
    
    _draw_loading("Loading Thronglets... Resources")
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
    
    # Initialize tooltip system
    tooltip_system = TooltipSystem()
    
    # Initialize selection manager
    selection_manager = SelectionManager()
    
    # Initialize info panel
    info_panel = InfoPanel()
    evolution_stats_panel = EvolutionStatsPanel()
    observer_analytics_panel = ObserverAnalyticsPanel()
    archive_review_panel = ArchiveReviewPanel()
    
    # Initialize read-only observer HUD
    observer_overlay = ObserverOverlay()
    
    # Initialize fog of war system
    fog_of_war = FogOfWar(world_width, world_height)
    
    # Initialize territory manager
    territory_manager = TerritoryManager(world_width, world_height)
    
    # Initialize faction manager
    faction_manager = FactionManager()
    
    # Initialize city planner
    city_planner = CityPlanner(territory_manager, world_map)
    
    # Initialize season and weather systems
    season = Season()
    weather_system = WeatherSystem()
    apply_scenario_startup_conditions(scenario_profile, thronglets, advisor, season, weather_system, time.time())
    settlement_state = compute_settlement_snapshot(thronglets, buildings, world_map, season, weather_system)
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
    record_population_evolution_sample(advisor, thronglets, time.time(), time.time(), force=True)
    refresh_run_summary_cache(
        advisor,
        thronglets,
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
            )
            thronglets = restored_state["thronglets"]
            buildings = restored_state["buildings"]
            resources = restored_state["resources"]
            settlement_state = compute_settlement_snapshot(thronglets, buildings, world_map, season, weather_system)
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
            pending_resource_spawns = {}
            if restored_state.get("selected_model") and not selected_model:
                selected_model = restored_state["selected_model"]
            if restored_state.get("camera_state"):
                restored_camera = restored_state["camera_state"]
                camera.set_zoom(restored_camera.get("zoom", camera.zoom))
                camera.x = restored_camera.get("x", camera.x)
                camera.y = restored_camera.get("y", camera.y)
                camera.follow_mode = bool(restored_camera.get("follow_mode", True))
                camera.clamp_camera()
            else:
                center_camera_on_colony(camera, thronglets, buildings)
                camera.follow_mode = True
            fog_of_war.update(thronglets)
            territory_manager.update(thronglets, buildings)
            record_population_evolution_sample(advisor, thronglets, time.time(), time.time() - restored_elapsed_seconds, force=True)
            refresh_run_summary_cache(
                advisor,
                thronglets,
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
        if action_name == "end_resume":
            post_run_action = "resume_latest"
            running = False
            return
        if action_name == "end_new_run":
            post_run_action = "new_run"
            running = False
            return
    
    game_start_time = time.time() - restored_elapsed_seconds
    last_status_time = game_start_time
    render_diag_until = game_start_time  # Disable diag overlay
    record_population_evolution_sample(advisor, thronglets, time.time(), game_start_time, force=True)
    refresh_run_summary_cache(
        advisor,
        thronglets,
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
    print("Thronglets game started! Observer mode is active - the colony evolves without player commands.")
    print(f"[DEBUG] Entering main game loop...")
    
    # #region agent log
    debug_log("main:before_loop", "About to enter main game loop", {"running": running, "screen_is_none": screen is None}, "H1")
    # #endregion
    
    # Main game loop - wrapped in try-finally for crash safety
    try:
        frame_count = 0
        # #region agent log
        debug_log("main:loop_start", "Main loop started", {"frame_count": frame_count, "running": running}, "H1")
        # #endregion
        while running:
            frame_count += 1
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
                        camera.adjust_zoom(-0.1)
                    elif event.key == pygame.K_EQUALS or event.key == pygame.K_KP_PLUS:
                        camera.adjust_zoom(0.1)
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
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:  # Left mouse
                        run_layout = compute_run_layout(WINDOW_WIDTH, WINDOW_HEIGHT)
                        ui_hit = ui_registry.hit_test(event.pos)
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
                                    camera.x = max(0, min(world_click_x - WINDOW_WIDTH / (2 * max(0.01, camera.zoom)), camera.world_width - WINDOW_WIDTH / max(0.01, camera.zoom)))
                                    camera.y = max(0, min(world_click_y - WINDOW_HEIGHT / (2 * max(0.01, camera.zoom)), camera.world_height - WINDOW_HEIGHT / max(0.01, camera.zoom)))
                                    camera.clamp_camera()
                            else:
                                _handle_ui_action(ui_hit.action or ui_hit.id, ui_hit.payload)
                        else:
                            keys = pygame.key.get_pressed()
                            shift_pressed = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
                            entity, entity_type = pick_world_entity(
                                event.pos,
                                camera,
                                thronglets,
                                buildings,
                                resources,
                                world_map.encounters,
                                world_map.hazards,
                                world_map.npcs,
                                thronglet_radius=THRONGLET_RADIUS,
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
                                camera.start_pan(event.pos[0], event.pos[1])
                    elif event.button == 2:  # Middle mouse button - always pan
                        camera.start_pan(event.pos[0], event.pos[1])
                    elif event.button == 4:  # Scroll up
                        scroll_target = ui_registry.scroll_target(mouse_screen_pos)
                        if scroll_target and scroll_target.id == "inspect_drawer":
                            ui_state.inspect_scroll = max(0, ui_state.inspect_scroll - 28)
                        elif scroll_target and scroll_target.id == "modal_frame" and ui_state.active_modal == "archive":
                            ui_state.archive_scroll = max(0, ui_state.archive_scroll - 32)
                        else:
                            camera.adjust_zoom(0.1)
                    elif event.button == 5:  # Scroll down
                        scroll_target = ui_registry.scroll_target(mouse_screen_pos)
                        if scroll_target and scroll_target.id == "inspect_drawer":
                            ui_state.inspect_scroll += 28
                        elif scroll_target and scroll_target.id == "modal_frame" and ui_state.active_modal == "archive":
                            ui_state.archive_scroll += 32
                        else:
                            camera.adjust_zoom(-0.1)
                elif event.type == pygame.MOUSEMOTION:
                    camera.update_pan(event.pos[0], event.pos[1])
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
            camera.update_key_pan(keys, delta_time)
            
            # Update camera follow
            camera.update_follow(thronglets)
            
            # Skip heavy updates on first frame to ensure immediate rendering
            if frame_count > 1:
                # Update fog of war
                try:
                    fog_of_war.update(thronglets)
                except Exception as e:
                    print(f"[ERROR] Fog of war update failed: {e}")
                    game_logger.log_error(f"Fog of war update error: {e}")
                
                # Update territory manager (can be expensive - skip first frame)
                try:
                    territory_manager.update(thronglets, buildings)
                except Exception as e:
                    print(f"[ERROR] Territory manager update failed: {e}")
                    game_logger.log_error(f"Territory manager update error: {e}")
                
                # Update city planner
                try:
                    city_planner.update(thronglets, buildings, advisor, current_time)
                except Exception as e:
                    print(f"[ERROR] City planner update failed: {e}")
                    game_logger.log_error(f"City planner update error: {e}")
            else:
                print("[DEBUG] Skipping heavy updates on first frame for faster initial render")
            
            # Update thronglets
            num_active_resources = sum(1 for r in resources if not r.collected)
            num_buildings = len(buildings)
            
            # Calculate population pressure
            population_ratio = len(thronglets) / MAX_POPULATION
            overpopulation_penalty = 0
            if population_ratio >= OVERPOPULATION_THRESHOLD:
                overpopulation_penalty = (population_ratio - OVERPOPULATION_THRESHOLD) * 10  # 0-100% penalty
                # Apply to needs decay
                for thronglet in thronglets:
                    thronglet.needs_decay_multiplier = 1.0 + overpopulation_penalty
            
            # Calculate day/night cycle
            day_cycle = (current_time - game_start_time) % DAY_LENGTH
            is_night = day_cycle >= NIGHT_START
            time_of_day = "NIGHT" if is_night else "DAY"
            
            # Periodic status updates every 10 seconds
            if current_time - last_status_time >= 10:
                elapsed = int(current_time - game_start_time)
                total_food_inv = sum(t.inventory['food'] for t in thronglets)
                total_wood_inv = sum(t.inventory['wood'] for t in thronglets)
                print(f"\n[STATUS {elapsed}s] {num_active_resources} resources left, Total inventory: {total_food_inv} food, {total_wood_inv} wood, Buildings: {num_buildings}")
                for idx, t in enumerate(thronglets):
                    print(f"   Thronglet {idx}: pos=({int(t.x)}, {int(t.y)}), inv={t.inventory}")
                print()
                last_status_time = current_time

            advisor.poll_async_jobs(
                thronglets,
                resources,
                buildings,
                narrative_panel=narrative_panel,
                faction_manager=faction_manager,
            )
            if advisor.last_model_used:
                selected_model = advisor.last_model_used
            record_population_evolution_sample(advisor, thronglets, current_time, game_start_time, force=False)
            
            # Award research points (time-based and milestones)
            days_survived = int((current_time - game_start_time) / DAY_LENGTH)
            if days_survived > advisor.civilization_age:
                advisor.research_points += 25
                advisor.civilization_age = days_survived
                narrative_panel.add_message(f"Day {days_survived} survived! +25 research points", 'Achievement')
            
            # Population milestones (every 5 thronglets)
            pop_milestone = (len(thronglets) // 5) * 5
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
                len(thronglets)
            )
            
            # Building milestones (one-time per building)
            for building in buildings:
                if not hasattr(building, 'awarded_points'):
                    advisor.research_points += 10
                    building.awarded_points = True
            
            # Civilization advisor query with smart intervals and intervention assessment
            # Generate state summary
            state_summary = advisor._generate_state_summary(thronglets, resources, buildings, territory_manager, world_map)
            
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
                        thronglets,
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
            
            # Assign individual goals every 60 seconds
            advisor.assign_individual_goals(thronglets, buildings, resources, world_map)
            
            # Update resources (respawn logic)
            for resource in resources:
                resource.update(delta_time)
            
            # Update particle system
            particle_system.update()
            
            # Update narrative panel
            narrative_panel.update()
            
            # Update tooltip system - detect hover
            mouse_world_x, mouse_world_y = camera.screen_to_world(mouse_screen_pos[0], mouse_screen_pos[1])
            tooltip_system.detect_hover(mouse_world_x, mouse_world_y, camera, thronglets, buildings, resources, 
                                         world_map.encounters, world_map.hazards, world_map.npcs, world_map)
            
            # Update season and weather
            season.update(current_time - game_start_time)
            advisor.challenge_difficulty = advisor.calculate_difficulty(thronglets, buildings)
            weather_event = weather_system.check_event(current_time, advisor.challenge_difficulty, season.current)
            if weather_event and weather_event['type'] != 'clear':
                narrative_panel.add_message(f"Weather Alert: {weather_event['type']}!", 'Crisis')
            
            # Get weather effects for building and thronglet updates
            weather_effects = weather_system.get_effects()
            
            # Update buildings (production, etc.) - now with weather effects
            for building in buildings:
                building.update(delta_time, advisor.game_modifiers, weather_effects)

            settlement_state = compute_settlement_snapshot(thronglets, buildings, world_map, season, weather_system)
            update_settlement_celebration(
                celebration_state,
                settlement_state,
                thronglets,
                buildings,
                particle_system,
                narrative_panel,
                current_time,
                delta_time,
            )
            advisor.current_settlement_state = settlement_state
            refresh_run_summary_cache(
                advisor,
                thronglets,
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
            
            # Apply weather effects to thronglets (per second)
            for thronglet in thronglets:
                if 'energy' in weather_effects:
                    thronglet.needs['energy'] = max(0, min(100, thronglet.needs['energy'] + weather_effects['energy'] * delta_time))
                if 'thirst' in weather_effects:
                    thronglet.needs['thirst'] = max(0, min(100, thronglet.needs['thirst'] + weather_effects['thirst'] * delta_time))
                if 'happiness' in weather_effects:
                    thronglet.morale = clamp(thronglet.morale + weather_effects['happiness'] * 0.12 * delta_time, 0.0, 100.0)
                thronglet.apply_settlement_effects(settlement_state, delta_time, world_map, weather_effects, buildings)
            
            # Maintain resource counts by respawning resources if needed
            num_food_active = sum(1 for r in resources if r.resource_type == 'food' and not r.collected)
            num_wood_active = sum(1 for r in resources if r.resource_type == 'wood' and not r.collected)
            num_stone_active = sum(1 for r in resources if r.resource_type == 'stone' and not r.collected)
            
            # Apply seasonal modifiers
            season_modifiers = season.get_resource_modifier()
            
            if num_wood_active < WOOD_MAX_ON_MAP * season_modifiers['wood']:
                # Spawn a new wood resource with biome bonus consideration
                x = random.randint(100, camera.world_width - 100)
                y = random.randint(100, camera.world_height - 100)
                
                # Get biome at spawn location and apply bonus to spawn chance
                if world_map:
                    biome_type = world_map.get_biome_at(x, y)
                    biome_props = world_map.get_biome_properties(biome_type)
                    wood_bonus = biome_props.get('wood_bonus', 1.0)
                    # Higher wood_bonus = higher spawn chance
                    if random.random() < wood_bonus * 0.5:
                        resources.append(Resource(x, y, 'wood'))
                else:
                    resources.append(Resource(x, y, 'wood'))
            
            if num_stone_active < STONE_MAX_ON_MAP:
                # Spawn a new stone resource (rare) with biome bonus consideration
                x = random.randint(100, camera.world_width - 100)
                y = random.randint(100, camera.world_height - 100)
                
                # Get biome at spawn location and apply bonus to spawn chance
                if world_map:
                    biome_type = world_map.get_biome_at(x, y)
                    biome_props = world_map.get_biome_properties(biome_type)
                    stone_bonus = biome_props.get('stone_bonus', 1.0)
                    # Higher stone_bonus = higher spawn chance
                    if random.random() < stone_bonus * 0.5:
                        resources.append(Resource(x, y, 'stone'))
                else:
                    resources.append(Resource(x, y, 'stone'))
            
            # First pass: update health, age, bonds, happiness for all thronglets
            thronglets_to_remove = []
            for idx, thronglet in enumerate(thronglets):
                # Safety check - skip invalid thronglets
                if thronglet is None or not hasattr(thronglet, 'id'):
                    continue
                try:
                    # Update age and health - check for death
                    if not thronglet.update_age_and_health(delta_time, advisor.game_modifiers):
                        # Create death particle effect
                        particle_system.create_particles(thronglet.x, thronglet.y, 'death', 10)
                        thronglets_to_remove.append(idx)
                        narrative_panel.add_message(f"A thronglet has passed away...", 'Crisis')
                        advisor.total_deaths = getattr(advisor, 'total_deaths', 0) + 1
                        # Track death cause
                        if thronglet.age >= THRONGLET_MAX_AGE:
                            cause = 'old_age'
                        elif thronglet.health <= 0:
                            cause = 'health_failure'
                        else:
                            cause = 'unknown'
                        advisor.session_stats['deaths_by_cause'][cause] = advisor.session_stats['deaths_by_cause'].get(cause, 0) + 1
                        previous_average = advisor.session_stats.get('avg_survival_time', 0.0)
                        death_count = max(1, advisor.total_deaths)
                        advisor.session_stats['avg_survival_time'] = (
                            ((previous_average * max(0, death_count - 1)) + thronglet.age) / death_count
                        )
                        append_bounded_history(
                            advisor.session_stats.setdefault('lineage_events', []),
                            {
                                "time": current_time,
                                "label": (
                                    f"Death: #{thronglet.id} G{getattr(thronglet, 'generation', 0)} "
                                    f"L{getattr(thronglet, 'lineage_id', thronglet.id)} ({cause})"
                                ),
                            },
                            16,
                        )
                        record_observer_timeline_event(
                            advisor,
                            current_time,
                            "death",
                            f"Lineage loss: #{thronglet.id} from L{getattr(thronglet, 'lineage_id', thronglet.id)}",
                            f"Cause: {cause.replace('_', ' ')}.",
                        )
                    
                    # Update social bonds
                    thronglet.update_bonds(thronglets, delta_time, advisor.game_modifiers)
                except Exception as e:
                    # Log error but don't crash - skip this thronglet for this frame
                    game_logger.log_error(f"Error updating thronglet {thronglet.id if hasattr(thronglet, 'id') else idx}: {str(e)}", exc_info=True)
                    continue
            
            # Update factions after bonds are updated (outside the loop for efficiency)
            faction_manager.update_factions(thronglets, advisor)
            faction_manager.apply_autonomous_pressure(
                thronglets,
                advisor,
                world_map,
                world_width,
                world_height,
                current_time,
            )
            
            # Update happiness (move outside loop for efficiency)
            for thronglet in thronglets:
                try:
                    # Update happiness
                    thronglet.update_happiness(buildings, thronglets, advisor.game_modifiers, world_map)
                    
                    # Store knowledge when discovering resources
                    for resource in resources:
                        if not resource.collected:
                            distance = math.sqrt((resource.x - thronglet.x)**2 + (resource.y - thronglet.y)**2)
                            if distance < 30 and (resource.x, resource.y) not in thronglet.known_resources:
                                thronglet.known_resources.append((resource.x, resource.y))
                                
                                # Explorer luck mechanic - chance to find bonus resources
                                if thronglet.role == 'explorer' and random.random() < EXPLORER_LUCK_CHANCE * thronglet.get_exploration_bonus():
                                    bonus_type = random.choice(['food', 'wood', 'stone'])
                                    resources.append(Resource(thronglet.x + random.randint(-30, 30), 
                                                             thronglet.y + random.randint(-30, 30), 
                                                             bonus_type))
                                    narrative_panel.add_message(f"Explorer discovered bonus {bonus_type}!", 'Achievement')
                except Exception as e:
                    # Log error but don't crash - skip this thronglet for this frame
                    game_logger.log_error(f"Error updating thronglet {thronglet.id if hasattr(thronglet, 'id') else 'unknown'}: {str(e)}", exc_info=True)
                    continue
            
            # Remove dead thronglets (in reverse order to maintain indices)
            for idx in reversed(thronglets_to_remove):
                thronglets.pop(idx)
                print(f"A thronglet has died. Population: {len(thronglets)}")
            
            # Check for extinction
            if len(thronglets) == 0 and not game_over:
                game_over = True
                ui_state.end_summary_open = True
                ui_state.active_modal = None
                extinction_summary = refresh_run_summary_cache(
                    advisor,
                    thronglets,
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
            conditional_behaviors = advisor.get_conditional_behaviors(thronglets, buildings, resources)
            
            # Process group tasks: assign thronglets to group tasks
            for group_task in advisor.group_tasks:
                if not group_task.is_complete():
                    # Find suitable thronglets for this task
                    available_thronglets = [t for t in thronglets if 
                                           t.id not in group_task.assigned_thronglets and
                                           t.needs['hunger'] > 50 and t.needs['energy'] > 50]
                    
                    # Assign based on role match
                    for thronglet in available_thronglets:
                        if len(group_task.assigned_thronglets) >= group_task.required_count:
                            break
                        if group_task.task_type == 'build' and thronglet.role == 'builder':
                            group_task.add_thronglet(thronglet.id)
                        elif group_task.task_type == 'gather' and thronglet.role == 'gatherer':
                            group_task.add_thronglet(thronglet.id)
                        elif group_task.task_type == 'explore' and thronglet.role == 'explorer':
                            group_task.add_thronglet(thronglet.id)
                        elif not thronglet.role:  # No role yet, assign anyway
                            group_task.add_thronglet(thronglet.id)
            
            for idx, thronglet in enumerate(thronglets):
                # Safety check - skip invalid thronglets
                if thronglet is None or not hasattr(thronglet, 'id'):
                    continue
                try:
                    # Get individual directive for this thronglet
                    individual_directive = advisor.get_individual_directive(thronglet.id)
                    
                    # Check if thronglet is assigned to a group task
                    group_task = None
                    for task in advisor.group_tasks:
                        if thronglet.id in task.assigned_thronglets:
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
                    
                    # Autonomous decision-making (no per-thronglet LLM)
                    # Pass is_night to influence energy decay, and thronglets list for mate-seeking
                    # Create a safe copy of thronglets list to avoid iteration issues
                    try:
                        # Filter out None or invalid thronglets for safety
                        safe_thronglets = [t for t in thronglets if t is not None and hasattr(t, 'id') and hasattr(t, 'inventory')]
                        building_type = thronglet.decide_action(resources, buildings, delta_time, combined_directives, is_night, safe_thronglets, advisor.group_tasks, conditional_behaviors, territory_manager, city_planner, world_map.hazards if world_map else [], world_map)
                    except Exception as e:
                        game_logger.log_error(f"Error in thronglet {thronglet.id if hasattr(thronglet, 'id') else 'unknown'} decide_action: {str(e)}", exc_info=True)
                        building_type = None  # Skip this thronglet for this frame
                    
                    # Handle building from directive
                    if building_type:
                        # Use city planner location if set, otherwise use thronglet position
                        build_x = thronglet.next_build_location[0] if thronglet.next_build_location else thronglet.x
                        build_y = thronglet.next_build_location[1] if thronglet.next_build_location else thronglet.y
                        thronglet.next_build_location = None  # Clear for next build
                        
                        new_building = Building(build_x, build_y, building_type)
                        new_building.built_by = thronglet.id
                        buildings.append(new_building)
                        # Create particle effect
                        particle_system.create_particles(build_x, build_y, 'build', 12)
                        # Gain building skill XP
                        thronglet.gain_skill_xp('building', SKILL_XP_BUILDING)
                        # Record success for Q-learning
                        thronglet.record_success('build_' + building_type)
                        record_observer_timeline_event(
                            advisor,
                            current_time,
                            "build",
                            f"Built {building_type}",
                            f"Builder #{thronglet.id} completed new infrastructure.",
                        )
                        # Track building statistics
                        advisor.session_stats['buildings_built'][building_type] = advisor.session_stats['buildings_built'].get(building_type, 0) + 1
                    
                    # Check collision with resources - now requires gathering time
                    for resource in resources:
                        if resource.check_collision(thronglet):
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
                            skill_bonus = thronglet.get_gathering_bonus() if thronglet.role == 'gatherer' else 1.0
                            required_time = required_time / (gather_rate * skill_bonus)
                            
                            # Start gathering if not already gathering this resource
                            if thronglet.gathering_resource != resource:
                                thronglet.gathering_resource = resource
                                thronglet.gathering_start_time = current_time
                                thronglet.current_action = f"gathering {resource.resource_type}"
                                thronglet.vx = 0  # Stop moving while gathering
                                thronglet.vy = 0
                            
                            # Check if gathering is complete
                            elapsed_time = current_time - thronglet.gathering_start_time
                            if elapsed_time >= required_time:
                                resource.collected = True
                                resource.collect_time = current_time
                                
                                # Get workshop bonus, skill bonus, and role bonus for gathering
                                workshop_bonus = thronglet.get_workshop_bonus(buildings, advisor.game_modifiers)
                                skill_bonus = thronglet.get_gathering_bonus() if thronglet.role == 'gatherer' else 1.0
                                role_bonus = GATHERER_SPEED_BONUS if thronglet.role == 'gatherer' else 1.0
                                efficiency = 1.0 - (overpopulation_penalty * 0.01)  # Max -10% at full penalty
                                resources_gained = workshop_bonus * skill_bonus * role_bonus * efficiency
                                
                                if resource.resource_type == 'food':
                                    thronglet.inventory['food'] += int(resources_gained)
                                    # Handle fractional gathering (store in float)
                                    if not hasattr(thronglet, 'fractional_inventory'):
                                        thronglet.fractional_inventory = {'food': 0.0, 'wood': 0.0, 'stone': 0.0}
                                    thronglet.fractional_inventory['food'] += (resources_gained - int(resources_gained))
                                    if thronglet.fractional_inventory['food'] >= 1.0:
                                        thronglet.inventory['food'] += 1
                                        thronglet.fractional_inventory['food'] -= 1.0
                                    
                                    thronglet.needs['hunger'] = min(100, thronglet.needs['hunger'] + 20)  # Eating restores hunger
                                    # Create particle effect
                                    particle_system.create_particles(resource.x, resource.y, 'sparkle', 8)
                                    # Record success for Q-learning
                                    thronglet.record_success('gather_food')
                                elif resource.resource_type == 'wood':
                                    thronglet.inventory['wood'] += int(resources_gained)
                                    if not hasattr(thronglet, 'fractional_inventory'):
                                        thronglet.fractional_inventory = {'food': 0.0, 'wood': 0.0, 'stone': 0.0}
                                    thronglet.fractional_inventory['wood'] += (resources_gained - int(resources_gained))
                                    if thronglet.fractional_inventory['wood'] >= 1.0:
                                        thronglet.inventory['wood'] += 1
                                        thronglet.fractional_inventory['wood'] -= 1.0
                                    
                                    # Create particle effect
                                    particle_system.create_particles(resource.x, resource.y, 'dust', 6)
                                    # Record success for Q-learning
                                    thronglet.record_success('gather_wood')
                                elif resource.resource_type == 'stone':
                                    thronglet.inventory['stone'] += int(resources_gained)
                                    if not hasattr(thronglet, 'fractional_inventory'):
                                        thronglet.fractional_inventory = {'food': 0.0, 'wood': 0.0, 'stone': 0.0}
                                    thronglet.fractional_inventory['stone'] += (resources_gained - int(resources_gained))
                                    if thronglet.fractional_inventory['stone'] >= 1.0:
                                        thronglet.inventory['stone'] += 1
                                        thronglet.fractional_inventory['stone'] -= 1.0
                                    
                                    # Create particle effect
                                    particle_system.create_particles(resource.x, resource.y, 'dust', 6)
                                    # Record success for Q-learning
                                    thronglet.record_success('gather_stone')
                                
                                if VERBOSE_LOGGING:
                                    print(f"[Thronglet {idx}] *** Gathered {resource.resource_type}! Inventory now: {thronglet.inventory}")
                                
                                # Gain skill XP for gathering
                                thronglet.gain_skill_xp('gathering', SKILL_XP_GATHERING)
                                
                                # Track bounty challenge progress
                                for challenge in advisor.active_challenges:
                                    if challenge['type'] == 'bounty':
                                        challenge['collected'] = challenge.get('collected', 0) + 1
                                
                                # Clear gathering state
                                thronglet.gathering_resource = None
                                thronglet.gathering_start_time = 0
                            # Continue gathering in next frame
                            break
                    else:
                        # Not near any resource, clear gathering state if was gathering
                        if thronglet.gathering_resource:
                            thronglet.gathering_resource = None
                            thronglet.gathering_start_time = 0
                    
                    # Check building interaction
                    for building in buildings:
                        distance = math.sqrt((building.x - thronglet.x)**2 + (building.y - thronglet.y)**2)
                        if distance < 15:  # Within interaction range (adjusted for smaller sprites)
                            if building.building_type == 'house' and building.enter(thronglet, advisor.game_modifiers):
                                # Restoring energy in house
                                thronglet.needs['energy'] = min(100, thronglet.needs['energy'] + 0.5)
                                thronglet.current_action = "resting"
                            elif building.building_type == 'farm' and building.stored_resources['food'] > 0:
                                # Collect food from farm
                                building.stored_resources['food'] -= 1
                                thronglet.inventory['food'] += 1
                                thronglet.needs['hunger'] = min(100, thronglet.needs['hunger'] + 30)
                                if VERBOSE_LOGGING:
                                    print(f"[Thronglet {idx}] *** Collected food from farm! Hunger: {thronglet.needs['hunger']}")
                            elif building.building_type == 'storage':
                                # Deposit resources in storage
                                total_deposited = 0
                                if thronglet.inventory['food'] > 0:
                                    building.stored_resources['food'] += thronglet.inventory['food']
                                    total_deposited += thronglet.inventory['food']
                                    thronglet.inventory['food'] = 0
                                if thronglet.inventory['wood'] > 0:
                                    building.stored_resources['wood'] += thronglet.inventory['wood']
                                    total_deposited += thronglet.inventory['wood']
                                    thronglet.inventory['wood'] = 0
                                if thronglet.inventory['stone'] > 0:
                                    building.stored_resources['stone'] = building.stored_resources.get('stone', 0) + thronglet.inventory['stone']
                                    total_deposited += thronglet.inventory['stone']
                                    thronglet.inventory['stone'] = 0
                                if total_deposited > 0 and VERBOSE_LOGGING:
                                    print(f"[Thronglet {idx}] *** Deposited {total_deposited} resources in storage!")
                            elif building.building_type == 'well':
                                # Drink from well to restore thirst (if not disabled by challenge)
                                if not getattr(building, 'challenge_disabled', False):
                                    thronglet.needs['thirst'] = min(100, thronglet.needs['thirst'] + 0.5)
                        else:
                            # Too far away, leave building if inside
                            building.leave(thronglet)
                    
                    # Update position
                    try:
                        safe_thronglets_for_update = [t for t in thronglets if t is not None and hasattr(t, 'id') and hasattr(t, 'inventory')]
                        thronglet.update_position(advisor.game_modifiers, world_map, world_width, world_height, buildings, safe_thronglets_for_update)
                    except Exception as e:
                        game_logger.log_error(f"Error updating position for thronglet {thronglet.id if hasattr(thronglet, 'id') else 'unknown'}: {str(e)}", exc_info=True)
                except Exception as e:
                    # Catch any other unexpected errors in thronglet update loop
                    game_logger.log_error(f"Unexpected error processing thronglet {thronglet.id if hasattr(thronglet, 'id') else 'unknown'}: {str(e)}", exc_info=True)
                    continue
            
            # Check for encounter discovery and exploration
            for encounter in world_map.encounters:
                if not encounter.discovered:
                    # Check if any thronglet is nearby
                    for thronglet in thronglets:
                        distance = math.sqrt((encounter.x - thronglet.x)**2 + (encounter.y - thronglet.y)**2)
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
                    for thronglet in thronglets:
                        distance = math.sqrt((encounter.x - thronglet.x)**2 + (encounter.y - thronglet.y)**2)
                        if distance < 40:  # Within exploration range
                            # Start or continue exploration
                            if thronglet.exploring_encounter == encounter:
                                # Continue exploring
                                if current_time - thronglet.exploration_start_time >= thronglet.exploration_duration:
                                    # Exploration complete! Give rewards
                                    encounter.explored = True
                                    encounter.reward_given = True
                                    thronglet.exploring_encounter = None
                                    
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
                                        # Heal all thronglets and restore thirst
                                        for t in thronglets:
                                            t.health = min(100, t.health + 30)
                                            t.needs['thirst'] = 100
                                            # Temporary disease immunity
                                            t.disease_immunity_until = current_time + 60
                                        narrative_panel.add_message("EXPLORED: Oasis! All thronglets healed and hydrated", 'Achievement')
                                    elif encounter.encounter_type == 'sacred_grove':
                                        # Increase happiness for all and strengthen bonds
                                        for t in thronglets:
                                            t.happiness = min(100, t.happiness + 20)
                                            # Strengthen all bonds
                                            for other in thronglets:
                                                if other.id != t.id:
                                                    key = tuple(sorted([t.id, other.id]))
                                                    t.bonds[key] = min(100, t.bonds.get(key, 0) + 20)
                                        advisor.research_points += 30
                                        narrative_panel.add_message("EXPLORED: Sacred Grove! +20 happiness +30 research", 'Achievement')
                            else:
                                # Start new exploration
                                thronglet.exploring_encounter = encounter
                                thronglet.exploration_start_time = current_time
                        else:
                            # Too far away, cancel exploration if we're exploring this encounter
                            if thronglet.exploring_encounter == encounter:
                                thronglet.exploring_encounter = None
            
            # Check for disease outbreaks and recovery
            for thronglet in thronglets:
                # Chance to contract disease based on population density, hygiene, health, and biome
                population_density = len(thronglets) / (WINDOW_WIDTH * WINDOW_HEIGHT / 10000)  # Normalized density
                num_wells = sum(1 for b in buildings if b.building_type == 'well')
                hygiene_factor = max(0.5, num_wells / max(1, len(thronglets) / 5))  # More wells = better hygiene
                
                # Biome risk modifier
                biome_risk_mod = 1.0
                if world_map:
                    biome_type = world_map.get_biome_at(thronglet.x, thronglet.y)
                    biome_props = world_map.get_biome_properties(biome_type)
                    biome_risk_mod = biome_props.get('disease_risk', 1.0)
                
                overpopulation_stress = 1.0 + (population_ratio - 0.9) * 2 if population_ratio >= 0.9 else 1.0
                adaptability = getattr(thronglet, "genetics", {}).get("adaptability", 1.0)
                disease_chance = (
                    DISEASE_CHANCE_BASE
                    * population_density
                    * (2 - hygiene_factor)
                    * (100 - thronglet.health)
                    / 100
                    * (biome_risk_mod / max(0.75, adaptability))
                    * overpopulation_stress
                )
                thronglet.contract_disease(disease_chance)
                
                # Disease recovery (slow healing with rest)
                if thronglet.diseased and current_time - thronglet.disease_start_time > 30:
                    # Check if in house or good health
                    in_house = any(b.occupants.count(thronglet) > 0 for b in buildings if b.building_type == 'house')
                    if in_house and thronglet.needs['energy'] > 70:
                        recovery_mod = advisor.game_modifiers.get_modifier('disease_recovery_rate')
                        immune_strength = getattr(thronglet, "genetics", {}).get("immune_strength", 1.0)
                        recovery_chance = 0.1 * recovery_mod * immune_strength * delta_time
                        if random.random() < recovery_chance:
                            thronglet.diseased = False
                            thronglet.disease_start_time = 0
                            print("Thronglet recovered from disease!")
            
            # Check for NPC interactions
            for npc in world_map.npcs:
                if npc.visible:
                    for thronglet in thronglets:
                        distance = math.sqrt((npc.x - thronglet.x)**2 + (npc.y - thronglet.y)**2)
                        if distance < 30:  # Within interaction range (adjusted for smaller sprites)
                            # Start or continue interaction
                            if thronglet.interacting_npc == npc:
                                # Continue interacting
                                if current_time - thronglet.interaction_start_time >= thronglet.interaction_duration:
                                    # Interaction complete! Process based on NPC type
                                    thronglet.interacting_npc = None
                                    
                                    if npc.npc_type == 'trader':
                                        # Multiple trade options
                                        trades_available = []
                                        if thronglet.inventory['food'] >= 2 and npc.inventory.get('wood', 0) >= 1:
                                            trades_available.append(('food_for_wood', 'food', 2, 'wood', 1))
                                        if thronglet.inventory['wood'] >= 2 and npc.inventory.get('stone', 0) >= 1:
                                            trades_available.append(('wood_for_stone', 'wood', 2, 'stone', 1))
                                        if thronglet.inventory['wood'] >= 1 and npc.inventory.get('food', 0) >= 2:
                                            trades_available.append(('wood_for_food', 'wood', 1, 'food', 2))
                                        
                                        if trades_available:
                                            trade = random.choice(trades_available)
                                            trade_name, give_res, give_amt, get_res, get_amt = trade
                                            thronglet.inventory[give_res] -= give_amt
                                            npc.inventory[give_res] = npc.inventory.get(give_res, 0) + give_amt
                                            thronglet.inventory[get_res] += get_amt
                                            npc.inventory[get_res] = npc.inventory.get(get_res, 0) - get_amt
                                            narrative_panel.add_message(f"Trade: {give_amt} {give_res} -> {get_amt} {get_res}", 'Achievement')
                                    elif npc.npc_type == 'rival_tribe':
                                        # Hostile encounter
                                        if random.random() < 0.5:  # 50% chance of negative encounter
                                            thronglet.health = max(0, thronglet.health - 15)
                                            narrative_panel.add_message("Thronglet encountered hostile tribe! -15 health", 'Crisis')
                                    elif npc.npc_type == 'wildlife_herd':
                                        # Friendly encounter, chance to gain food
                                        if random.random() < 0.3:  # 30% chance
                                            thronglet.inventory['food'] += 1
                                            narrative_panel.add_message("Wildlife shared food! +1 food", 'Achievement')
                            else:
                                # Start new interaction
                                thronglet.interacting_npc = npc
                                thronglet.interaction_start_time = current_time
                        else:
                            # Too far away, cancel interaction
                            if thronglet.interacting_npc == npc:
                                thronglet.interacting_npc = None
            
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
                        for thronglet in thronglets:
                            disease_chance = DISEASE_CHANCE_BASE * 5
                            thronglet.contract_disease(disease_chance)
            
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
            for hazard in world_map.hazards:
                if hazard.active:
                    for thronglet in thronglets:
                        # Scale damage by difficulty for hazards that deal damage
                        old_health = thronglet.health
                        hazard.check_affect(thronglet)
                        # Check if health changed, apply difficulty scaling
                        if thronglet.health < old_health and advisor.challenge_difficulty > 1.0:
                            damage_scale = advisor.challenge_difficulty
                            additional_damage = (old_health - thronglet.health) * (damage_scale - 1.0)
                            thronglet.health = max(0, thronglet.health - additional_damage)
            
            # Check for reproduction opportunities
            if len(thronglets) < MAX_POPULATION:
                for i in range(len(thronglets)):
                    for j in range(i + 1, len(thronglets)):
                        thronglet1 = thronglets[i]
                        thronglet2 = thronglets[j]
                        
                        # Check if both can reproduce
                        if not thronglet1.can_reproduce() or not thronglet2.can_reproduce():
                            continue
                        
                        # Check proximity
                        distance = math.sqrt((thronglet1.x - thronglet2.x)**2 + (thronglet1.y - thronglet2.y)**2)
                        if distance > REPRODUCTION_PROXIMITY:
                            continue
                        
                        # Reproduction successful!
                        # Create offspring near the parents
                        mid_x = (thronglet1.x + thronglet2.x) / 2
                        mid_y = (thronglet1.y + thronglet2.y) / 2
                        offset_x = random.uniform(-20, 20)
                        offset_y = random.uniform(-20, 20)
                        child = Thronglet.create_offspring(
                            thronglet1,
                            thronglet2,
                            max(20, min(world_width - 20, mid_x + offset_x)),
                            max(20, min(world_height - 20, mid_y + offset_y)),
                        )
                        thronglets.append(child)
                        
                        # Share knowledge between parents
                        thronglet1.share_knowledge(thronglet2)
                        thronglet2.share_knowledge(thronglet1)
                        # Create knowledge particle effect
                        if random.random() < 0.3:  # 30% chance per reproduction
                            particle_system.create_particles(mid_x, mid_y, 'knowledge', 5)
                        
                        # Update cooldowns
                        thronglet1.last_reproduction_time = current_time
                        thronglet2.last_reproduction_time = current_time
                        
                        # Visual feedback
                        thronglet1.reproduction_message = "♥"
                        thronglet1.reproduction_message_time = current_time
                        thronglet2.reproduction_message = "♥"
                        thronglet2.reproduction_message_time = current_time
                        
                        # Create particle effects (hearts)
                        particle_system.create_particles(thronglet1.x, thronglet1.y, 'heart', 15)
                        particle_system.create_particles(thronglet2.x, thronglet2.y, 'heart', 15)
                        
                        # Add narrative message
                        narrative_panel.add_message(
                            f"New thronglet born: Gen {child.generation} from L{child.lineage_id}. Population: {len(thronglets)}",
                            'Achievement',
                        )
                        
                        record_observer_timeline_event(
                            advisor,
                            current_time,
                            "birth",
                            f"Birth: #{child.id} joins lineage {child.lineage_id}",
                            f"Population now {len(thronglets)}.",
                        )
                        advisor.session_stats['births_total'] = advisor.session_stats.get('births_total', 0) + 1
                        append_bounded_history(
                            advisor.session_stats.setdefault('lineage_events', []),
                            {
                                "time": current_time,
                                "label": (
                                    f"Birth: #{child.id} G{child.generation} L{child.lineage_id} "
                                    f"from {thronglet1.id}/{thronglet2.id} mut {child.mutation_count}"
                                ),
                            },
                            16,
                        )
                        record_population_evolution_sample(advisor, thronglets, current_time, game_start_time, force=True)
                        
                        print(f"New thronglet born! Population: {len(thronglets)}")
                        break
                    else:
                        continue
                        break
                
                record_population_evolution_sample(advisor, thronglets, current_time, game_start_time, force=False)

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
                    thronglets=thronglets,
                    encounters=world_map.encounters,
                    hazards=world_map.hazards,
                    npcs=world_map.npcs,
                    selected_entity=selection_manager.selected_entity,
                    particle_system=particle_system,
                    effect_cues=camera_director.to_payload(),
                    active_overlay=ui_state.map_overlay,
                    camera_bookmarks=camera_director.to_payload(),
                )
                scene_renderer.render(screen, render_frame)
            
            current_summary = dict(advisor.session_stats.get("current_run_summary", {}) or {})
            evolution_summary = advisor.session_stats.get("current_evolution_summary") or summarize_population_evolution(thronglets)
            llm_status = advisor.get_llm_status_label(
                selected_model
                or _selected_llm_model
                or ("Disabled" if runtime_config.disable_llm or not LLM_ENABLED else PREFERRED_OLLAMA_MODEL)
            )
            scenario_name = advisor.session_stats.get("scenario_name", scenario_profile["name"])
            doctrine = dict((getattr(advisor, "council_state", {}) or {}).get("doctrine", {}) or {})
            doctrine_label = str(doctrine.get("focus") or doctrine.get("stance") or "Autonomous").replace("_", " ").title()
            phase_label = current_summary.get("current_phase", {}).get("label", "Founding")
            observer_score = int(current_summary.get("end_state", {}).get("score", 0) or 0)
            if thronglets:
                colony_center = (
                    sum(thronglet.x for thronglet in thronglets) / len(thronglets),
                    sum(thronglet.y for thronglet in thronglets) / len(thronglets),
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
            )
            field_notes = build_field_notes(advisor.session_stats.get("timeline_events", []), current_time, limit=6)
            minimap_context = {
                "world_map": world_map,
                "camera": camera,
                "city_planner": city_planner,
                "faction_manager": faction_manager,
                "thronglets": thronglets,
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
            )
            inspect_model = build_inspect_view_model(
                selection_manager.selected_entity,
                selection_manager.selected_type,
                advisor,
                current_time,
                settlement_state,
                faction_manager=faction_manager,
                active_tab=ui_state.inspect_tab,
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
            
            # Quick on-screen debug watermark for the first 3 seconds after start
            if current_time - game_start_time < 3.0:
                try:
                    debug_text = font_small.render("DEBUG: RENDER OK", True, (255, 255, 0))
                    screen.blit(debug_text, (10, 5))
                except Exception:
                    pass
            
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
                except:
                    pass  # Can't even show error, give up
            
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
        except:
            pass
        
        try:
            game_logger.save_quick_report()
            snapshot_file = None
            archive_file = None
            next_runtime_config = None
            local_names = locals()
            required_snapshot_names = ("thronglets", "buildings", "resources", "advisor", "season", "weather_system", "game_start_time")
            if all(name in local_names for name in required_snapshot_names):
                camera_bookmarks = camera_director.to_payload() if "camera_director" in local_names else []
                scene_thumbnail_key = os.path.basename(thumbnail_path) if thumbnail_path else None
                run_summary = build_run_summary(
                    thronglets=thronglets,
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
                    thronglets=thronglets,
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
                    thronglets,
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
                )
                snapshot_file = write_run_snapshot(game_logger.log_dir, game_logger.session_id, snapshot)
            game_state = {
                'population': len(thronglets),
                'buildings': len(buildings),
                'duration': time.time() - game_start_time
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

