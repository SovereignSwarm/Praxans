from __future__ import annotations
import pygame
import pygame.gfxdraw
import math
from datetime import datetime
import random
from collections import deque
from praxans_game import *
from graphics.palette import *

class Praxan:
    """A cute AI-powered creature"""
    _next_id = 0  # Class variable to track unique IDs
    
    def __init__(self, x, y):
        self.id = Praxan._next_id
        Praxan._next_id += 1
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
        
        # Determine specific Deep Traits (1-2)
        num_traits = random.choices([1, 2], weights=[70, 30])[0]
        self.traits = random.sample(list(TRAIT_DEFINITIONS.keys()), k=num_traits)
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
        self.target_building = None  # Building currently interacting with
        self.next_build_location = None  # (x, y) for city planner placement
        self.body_temp = 37.0  # Celsius
        
        # New: Health & Lifespan
        self.body_parts = {
            'torso': {'health': 100, 'max': 100, 'status': 'intact', 'efficiency': 1.0},
            'head': {'health': 50, 'max': 50, 'status': 'intact', 'efficiency': 1.0},
            'left_arm': {'health': 40, 'max': 40, 'status': 'intact', 'efficiency': 1.0},
            'right_arm': {'health': 40, 'max': 40, 'status': 'intact', 'efficiency': 1.0},
            'left_leg': {'health': 40, 'max': 40, 'status': 'intact', 'efficiency': 1.0},
            'right_leg': {'health': 40, 'max': 40, 'status': 'intact', 'efficiency': 1.0},
            'eyes': {'health': 20, 'max': 20, 'status': 'intact', 'efficiency': 1.0},
        }
        self.pain = 0.0 # 0.0 to 1.0
        self.capacities = {
            'consciousness': 1.0,
            'moving': 1.0,
            'manipulation': 1.0,
            'sight': 1.0
        }
        self.downed = False
        self.health = 100.0  # Kept for compatibility, updated dynamically
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
        self.bonds = {}  # {praxan_id: bond_strength}
        self.faction_id = None  # ID of faction this praxan belongs to
        self.base_mood = random.uniform(40, 60)
        self.moodlets = []  # List of dicts: {'name': str, 'value': float, 'duration': float|None, 'start_time': float}
        self.happiness = self.base_mood  # Will be dynamically calculated from base_mood and moodlets
        self.mental_state = None  # 'STATE_BINGE', 'STATE_SAD_WANDER', etc.
        self.mental_break_cooldown = 0
        
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
        self.game_ref = None     # Reference to main game object/loop
        self.schedule = ["Anything"] * 24  # 24-hour schedule slots
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

        # Work Priorities (1: Highest, 4: Lowest, 0: Disabled)
        self.work_priorities = {work_type: 3 for work_type in WORK_TYPES}
        self.hauling_target_resource = None
        self.hauling_target_storage = None
    
    def add_moodlet(self, name, value, duration, current_time):
        for m in self.moodlets:
            if m['name'] == name:
                m['duration'] = duration
                m['start_time'] = current_time
                return
        self.moodlets.append({
            'name': name,
            'value': value,
            'duration': duration,
            'start_time': current_time
        })

    def update_mood(self, current_time, delta_time):
        self.moodlets = [m for m in self.moodlets if m['duration'] is None or (current_time - m['start_time'] < m['duration'])]
        total_modifier = sum(m['value'] for m in self.moodlets)
        trait_mood = 0
        trait_threshold_mod = 0
        for trait in getattr(self, 'traits', []):
            trait_mood += TRAIT_DEFINITIONS[trait].get('mood_offset', 0)
            trait_threshold_mod += TRAIT_DEFINITIONS[trait].get('mental_break_threshold', 0)

        # Calculate dynamic happiness
        current_happiness = self.base_mood + total_modifier + trait_mood
        self.happiness = max(0.0, min(100.0, current_happiness))
        
        # Check for mental breaks
        break_threshold = 20 + trait_threshold_mod
        if self.mental_break_cooldown > 0:
            self.mental_break_cooldown = max(0, self.mental_break_cooldown - delta_time)
            if self.mental_state and self.mental_break_cooldown <= 240:
                self.mental_state = None
                self.state = STATE_IDLE
                self.current_action = "wander"
        elif self.mental_state is None:
            if self.happiness < 5.0:
                self.trigger_mental_break('extreme', current_time)
            elif self.happiness < 20.0:
                self.trigger_mental_break('major', current_time)
            elif self.happiness < 35.0:
                self.trigger_mental_break('minor', current_time)

    def trigger_mental_break(self, severity, current_time):
        if severity == 'extreme':
            self.mental_state = random.choice([STATE_CATATONIC, STATE_GIVE_UP])
        elif severity == 'major':
            self.mental_state = random.choice([STATE_TANTRUM, STATE_INSULTING])
        else:
            self.mental_state = random.choice([STATE_SAD_WANDER, STATE_BINGE])
            
        self.state = self.mental_state
        self.current_action = f"Mental Break: {self.mental_state}"
        self.mental_break_cooldown = 300  # 5 minutes before another break
        self.add_moodlet("Catharsis", 30, 300, current_time)
        print(f"[Mental Break] Praxan {self.id} suffered a {severity} break: {self.mental_state}")

    def execute_mental_break(self, resources, buildings, delta_time, current_time):
        if self.mental_state == STATE_SAD_WANDER:
            if random.random() < 0.1:
                self.vx += random.uniform(-1.0, 1.0)
                self.vy += random.uniform(-1.0, 1.0)
            self.current_action = "Wandering in sadness"
        elif self.mental_state == STATE_BINGE:
            if resources:
                target, _ = self.find_nearest_resource(resources, 'food')
                if target:
                    dx, dy = target.x - self.x, target.y - self.y
                    dist = math.sqrt(dx**2 + dy**2)
                    if dist < 10:
                        target.collected = True
                        self.needs['hunger'] = 100
                    elif dist > 0:
                        self.vx = (dx/dist) * PRAXAN_SPEED
                        self.vy = (dy/dist) * PRAXAN_SPEED
            self.current_action = "Binge eating"
        elif self.mental_state == STATE_TANTRUM:
            if buildings:
                target = min(buildings, key=lambda b: math.sqrt((b.x - self.x)**2 + (b.y - self.y)**2))
                dx, dy = target.x - self.x, target.y - self.y
                dist = math.sqrt(dx**2 + dy**2)
                if dist < 20:
                    self.vx, self.vy = 0, 0
                    # Later: damage building
                elif dist > 0:
                    self.vx = (dx/dist) * PRAXAN_SPEED
                    self.vy = (dy/dist) * PRAXAN_SPEED
            self.current_action = "Throwing a tantrum"
        elif self.mental_state == STATE_CATATONIC:
            self.vx, self.vy = 0, 0
            self.current_action = "Catatonic state"
        elif self.mental_state == STATE_GIVE_UP:
            self.vx, self.vy = PRAXAN_SPEED, 0
            self.current_action = "Giving up and leaving"
        
        return None

    def find_nearest_haulable(self, resources):
        """Find the nearest uncollected resource."""
        best_dist = float('inf')
        best_res = None
        for res in resources:
            if not res.collected:
                dist = math.sqrt((res.x - self.x)**2 + (res.y - self.y)**2)
                if dist < best_dist:
                    best_dist = dist
                    best_res = res
        return best_res

    def find_best_storage(self, buildings, stockpile_zones, resource_type):
        """Find the nearest valid storage for a resource type."""
        best_dist = float('inf')
        best_storage = None
        
        # Check storage buildings
        for b in buildings:
            if b.building_type == 'storage':
                dist = math.sqrt((b.x - self.x)**2 + (b.y - self.y)**2)
                if dist < best_dist:
                    best_dist = dist
                    best_storage = b
        
        # Check stockpile zones
        for z in stockpile_zones:
            if z.is_valid_for(resource_type):
                dist = math.sqrt((z.rect.centerx - self.x)**2 + (z.rect.centery - self.y)**2)
                if dist < best_dist:
                    best_dist = dist
                    best_storage = z
        
        return best_storage

    def haul_resources(self, resources, buildings, stockpile_zones):
        """Logic for hauling task."""
        # 1. If carrying nothing, find a resource to pick up
        if sum(self.inventory.values()) == 0:
            if not self.hauling_target_resource or self.hauling_target_resource.collected:
                self.hauling_target_resource = self.find_nearest_haulable(resources)
            
            if self.hauling_target_resource:
                self.current_action = f"Hauling: Going to {self.hauling_target_resource.resource_type}"
                dx, dy = self.hauling_target_resource.x - self.x, self.hauling_target_resource.y - self.y
                dist = math.sqrt(dx**2 + dy**2)
                if dist < 10:
                    # Pick up
                    self.hauling_target_resource.collected = True
                    self.inventory[self.hauling_target_resource.resource_type] += 1
                    self.hauling_target_resource = None
                else:
                    self.vx = (dx/dist) * PRAXAN_SPEED
                    self.vy = (dy/dist) * PRAXAN_SPEED
            else:
                self.current_action = "Hauling: No resources found"
                self.state = STATE_IDLE
        
        # 2. If carrying something, find storage to drop off
        else:
            res_type = next(k for k, v in self.inventory.items() if v > 0)
            if not self.hauling_target_storage:
                self.hauling_target_storage = self.find_best_storage(buildings, stockpile_zones, res_type)
            
            if self.hauling_target_storage:
                self.current_action = f"Hauling: Dropping off {res_type}"
                tx, ty = (self.hauling_target_storage.x, self.hauling_target_storage.y) if hasattr(self.hauling_target_storage, 'x') else self.hauling_target_storage.get_center()
                dx, dy = tx - self.x, ty - self.y
                dist = math.sqrt(dx**2 + dy**2)
                if dist < 20:
                    # Drop off
                    self.hauling_target_storage.stored_resources[res_type] += self.inventory[res_type]
                    self.inventory[res_type] = 0
                    self.hauling_target_storage = None
                else:
                    self.vx = (dx/dist) * PRAXAN_SPEED
                    self.vy = (dy/dist) * PRAXAN_SPEED
            else:
                self.current_action = "Hauling: No storage found"
                # If no storage, wander or drop on ground? For now just idle
                self.state = STATE_IDLE
        
        return None

    def gather_resources(self, resources):
        """Logic for gathering task (priority based)."""
        target, dist = self.find_nearest_resource(resources)
        if target:
            self.current_action = f"Gathering: Going to {target.resource_type}"
            dx, dy = target.x - self.x, target.y - self.y
            if dist < 10:
                # Start gathering
                self.gathering_resource = target
                self.gathering_start_time = time.time()
                self.vx, self.vy = 0, 0
            else:
                self.vx = (dx/dist) * PRAXAN_SPEED
                self.vy = (dy/dist) * PRAXAN_SPEED
        else:
            self.current_action = "Gathering: No resources"
            self.state = STATE_IDLE
        return None

    def build_structure(self, buildings, resources, other_praxans, city_planner, territory_manager, hazards):
        """Logic for building task (priority based)."""
        # For now, simplistic building logic: find a building type we can afford and build it nearby
        # (In a real scenario, this would check pending blueprints if we had them)
        
        # Check if we have a target building type to work on
        building_type = getattr(self, 'building_target_type', 'house') 
        
        base_wood, base_stone = get_building_cost(building_type)
        building_bonus = self.get_building_bonus()
        required_wood = max(1, int(base_wood / building_bonus))
        required_stone = max(1, int(base_stone / building_bonus))
        
        available_wood, available_stone = self.calculate_pooled_resources(other_praxans)
        
        if available_wood >= required_wood and available_stone >= required_stone:
            # Find location and build
            if city_planner:
                best_x, best_y, _ = city_planner.find_best_location(building_type, buildings, hazards, (self.x, self.y))
                dist = math.sqrt((best_x - self.x)**2 + (best_y - self.y)**2)
                if dist < 20:
                    if self.consume_pooled_resources(required_wood, required_stone, other_praxans):
                        self.build_message = f"Built {building_type}!"
                        self.build_message_time = time.time()
                        self.next_build_location = (best_x, best_y)
                        return building_type
                else:
                    dx, dy = best_x - self.x, best_y - self.y
                    self.vx = (dx/dist) * PRAXAN_SPEED
                    self.vy = (dy/dist) * PRAXAN_SPEED
                    self.current_action = f"Building: Moving to {building_type} site"
        else:
            # Not enough resources, maybe switch to gathering? 
            # For now, just idle or let the priority grid handle it
            self.current_action = "Building: Insufficient resources"
            self.state = STATE_IDLE
        return None



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
        nearby_hospital = False
        nearby_school = False
        nearby_market = False
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
                elif building.building_type == "hospital":
                    nearby_hospital = True
                elif building.building_type == "school":
                    nearby_school = True
                elif building.building_type == "market":
                    nearby_market = True

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
        if nearby_hospital:
            self.heal_damage(5.0 * delta_time)
            if self.diseased and random.random() < 0.2 * delta_time:
                self.diseased = False
        if nearby_school:
            for s in self.skills.values():
                if isinstance(s, dict) and 'xp' in s and 'level' in s:
                    s['xp'] += 1.0 * delta_time
                    if s['xp'] >= s['level'] * 100:
                        s['level'] += 1
                        s['xp'] = 0
        if nearby_market:
            morale_delta += 0.5 * delta_time
            self.base_mood = min(100.0, self.base_mood + 1.0 * delta_time)
            
        if weather_name in ("storm", "drought"):
            morale_delta -= 0.9 * delta_time

        self.morale = clamp(self.morale + morale_delta, 0.0, 100.0)

        inspiration_delta = -0.18 * delta_time
        if nearby_shrine:
            inspiration_delta += 0.55 * delta_time
        if nearby_workshop:
            inspiration_delta += 0.35 * delta_time
        if nearby_school:
            inspiration_delta += 0.80 * delta_time
        if current_biome == self.favorite_biome:
            inspiration_delta += 0.18 * delta_time
        self.inspiration = clamp(self.inspiration + inspiration_delta, 0.0, 100.0)
        self.settlement_prosperity = settlement_state.get("prosperity_score", 0.5)

    def update_position(self, modifiers=None, world_map=None, world_width=None, world_height=None, buildings=None, other_praxans=None):
        """Move the praxan and keep it within bounds with obstacle avoidance"""
        if self.downed:
            self.vx = 0
            self.vy = 0
            return
            
        # Disease and body parts slow movement
        speed_mod = modifiers.get_modifier('praxan_speed') if modifiers else 1.0
        
        trait_speed_mult = 1.0
        for trait in getattr(self, 'traits', []):
            trait_speed_mult *= TRAIT_DEFINITIONS[trait].get('speed_mult', 1.0)
            
        speed_multiplier = self.capacities.get('moving', 1.0) * speed_mod * trait_speed_mult
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
                    self.vx = (dx / distance) * PRAXAN_SPEED
                    self.vy = (dy / distance) * PRAXAN_SPEED
        
        # Obstacle avoidance using steering behaviors
        if buildings or other_praxans:
            avoidance_force_x, avoidance_force_y = self.avoid_obstacles(buildings or [], other_praxans or [])
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
    
    def calculate_pooled_resources(self, other_praxans):
        """Calculate available resources from self + nearby praxans within sharing radius"""
        available_wood = self.inventory.get('wood', 0)
        available_stone = self.inventory.get('stone', 0)
        
        if other_praxans:
            try:
                for other in other_praxans:
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
    
    def consume_pooled_resources(self, required_wood, required_stone, other_praxans):
        """Consume resources: take from self first, then borrow from nearby praxans
        Returns True if successfully consumed, False if insufficient"""
        # First calculate if we have enough
        available_wood, available_stone = self.calculate_pooled_resources(other_praxans)
        
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
        
        # Borrow remaining from nearby praxans (nearest first)
        if wood_needed > 0 or stone_needed > 0:
            # Sort nearby praxans by distance
            nearby_praxans = []
            if other_praxans:
                try:
                    for other in other_praxans:
                        if other is None or not hasattr(other, 'id') or not hasattr(other, 'x') or not hasattr(other, 'y'):
                            continue
                        if not hasattr(other, 'inventory'):
                            continue
                        if other.id == self.id:
                            continue
                        
                        distance = math.sqrt((other.x - self.x)**2 + (other.y - self.y)**2)
                        if distance < RESOURCE_SHARING_RADIUS:
                            nearby_praxans.append((distance, other))
                except (AttributeError, TypeError) as e:
                    # If error finding nearby praxans, just use self's resources
                    pass
            
            # Sort by distance (nearest first)
            nearby_praxans.sort(key=lambda x: x[0])
            
            # Borrow resources from nearest praxans
            # Double-check we don't include self and that objects are still valid
            for distance, other in nearby_praxans:
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
                    # Skip this praxan if there's an error accessing its inventory
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
    
    def calculate_path(self, target_x, target_y, buildings, world_width, world_height, other_praxans=None):
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
        
        # Apply Boids forces to path if other praxans are nearby (for multi-waypoint paths)
        if other_praxans and len(path) > 1:
            boids_cohesion, boids_separation = self.get_boids_forces(other_praxans, cohesion_radius=100)
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
    
    def get_boids_forces(self, other_praxans, cohesion_radius=100):
        """Calculate Boids forces (cohesion and separation) for group behavior"""
        cohesion_x = 0.0
        cohesion_y = 0.0
        separation_x = 0.0
        separation_y = 0.0
        
        nearby_count = 0
        separation_count = 0
        
        # Spatial partition: only check praxans within 200px for performance
        for other in other_praxans:
            if other == self:
                continue
            
            dx = other.x - self.x
            dy = other.y - self.y
            distance = math.sqrt(dx**2 + dy**2)
            
            if distance < 200:  # Performance optimization
                # Cohesion: move toward center of nearby praxans
                if distance < cohesion_radius and distance > 0:
                    cohesion_x += dx / distance
                    cohesion_y += dy / distance
                    nearby_count += 1
                
                # Separation: avoid crowding (enhanced existing avoid_obstacles logic)
                if distance < PRAXAN_RADIUS * 4 and distance > 0:
                    separation_strength = (PRAXAN_RADIUS * 4 - distance) / (PRAXAN_RADIUS * 4)
                    separation_x -= (dx / distance) * separation_strength
                    separation_y -= (dy / distance) * separation_strength
                    separation_count += 1
        
        # Normalize cohesion (average direction toward nearby praxans)
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
    
    def avoid_obstacles(self, buildings, other_praxans):
        """Calculate steering force to avoid obstacles"""
        avoidance_x = 0.0
        avoidance_y = 0.0
        
        # Avoid buildings
        for building in buildings:
            dx = self.x - building.x
            dy = self.y - building.y
            distance = math.sqrt(dx**2 + dy**2)
            if distance < BUILDING_SIZE + PRAXAN_RADIUS * 3:
                # Separation force (stronger when closer)
                if distance > 0:
                    strength = (BUILDING_SIZE + PRAXAN_RADIUS * 3 - distance) / (BUILDING_SIZE + PRAXAN_RADIUS * 3)
                    avoidance_x += (dx / distance) * strength
                    avoidance_y += (dy / distance) * strength
        
        # Avoid other praxans
        for other in other_praxans:
            if other == self:
                continue
            dx = self.x - other.x
            dy = self.y - other.y
            distance = math.sqrt(dx**2 + dy**2)
            if distance < PRAXAN_RADIUS * 4 and distance > 0:
                # Separation force
                strength = (PRAXAN_RADIUS * 4 - distance) / (PRAXAN_RADIUS * 4)
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
                travel_time = distance / PRAXAN_SPEED if PRAXAN_SPEED > 0 else 10
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
                try:
                    required_wood, required_stone = get_building_cost(target)
                except Exception:
                    pass
                
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
    
    def get_bonded_praxans_on_directive(self, directive, other_praxans):
        """Get list of bonded praxans working on the same directive"""
        if not other_praxans or not directive:
            return []
        
        bonded_list = []
        directive_action = directive.get('action', '').lower()
        
        for other in other_praxans:
            if other == self:
                continue
            
            # Check if bond > 50
            bond_strength = self.bonds.get(other.id, 0)
            if bond_strength > 50:
                # Check if other praxan is working on similar directive
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
                print(f"[Praxan {self.id}] State transition: {self.previous_state} -> {new_state}")
    
    def decide_action(self, resources, buildings, delta_time, directives=None, is_night=False, other_praxans=None, group_tasks=None, conditional_behaviors=None, territory_manager=None, city_planner=None, hazards=None, world_map=None, game_hour=0, rooms=None):
        """AI decision making for the praxan needs and personality using state machine and behavior tree"""
        current_time = time.time()
        self.update_mood(current_time, delta_time)
        
        if self.downed:
            return None
            
        if self.mental_state:
            return self.execute_mental_break(resources, buildings, delta_time, current_time)
            
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
                'other_praxans': other_praxans,
                'is_night': is_night,
                'delta_time': delta_time,
                'territory_manager': territory_manager,
                'city_planner': city_planner,
                'hazards': hazards,
                'world_map': world_map,
                'game_hour': game_hour
            }
            try:
                self.behavior_tree.tick(context)
                # Behavior tree may have changed state, continue with FSM logic below
            except Exception as e:
                # Graceful degradation on error
                if VERBOSE_LOGGING:
                    print(f"[Praxan {self.id}] Behavior tree error: {e}")
        
        # Check if we're gathering resources for a building directive and need to continue
        if self.building_resource_goal and self.state == STATE_EXECUTE_DIRECTIVE:
            # Check if we have enough resources now (including pooled)
            available_wood, available_stone = self.calculate_pooled_resources(other_praxans if other_praxans else [])
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
                                path = self.calculate_path(target_resource.x, target_resource.y, buildings if buildings else [], None, None, other_praxans)
                                if len(path) > 1:
                                    self.path = path
                                    self.current_waypoint_index = 1
                                    waypoint = path[1]
                                    dx = waypoint[0] - self.x
                                    dy = waypoint[1] - self.y
                                    distance = math.sqrt(dx**2 + dy**2)
                            if distance > 0:
                                self.vx = (dx / distance) * PRAXAN_SPEED
                                self.vy = (dy / distance) * PRAXAN_SPEED
                                self.current_action = f"directive: gathering {target_resource.resource_type} for building ({needed_wood} wood, {needed_stone} stone needed)"
                                return None
            else:
                # We have enough resources, clear the goal so building can proceed
                self.building_resource_goal = None
        
        # Update needs decay (30% slower for better survival)
        decay_multiplier = getattr(self, 'needs_decay_multiplier', 1.0)
        
        trait_hunger_mult = 1.0
        for trait in getattr(self, 'traits', []):
            trait_hunger_mult *= TRAIT_DEFINITIONS[trait].get('hunger_rate', 1.0)
            
        metabolism_efficiency = getattr(self, "genetics", {}).get("metabolism_efficiency", 1.0)
        hunger_decay = 0.035 * decay_multiplier * trait_hunger_mult * delta_time  # Was 0.05
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

        # Environment: Outdoors & Beauty
        current_room = None
        if rooms:
            tx, ty = int(self.x // TILE_SIZE), int(self.y // TILE_SIZE)
            for room in rooms:
                if (tx, ty) in room.tiles:
                    current_room = room
                    break
        
        if current_room:
            # Outdoors need
            if current_room.is_outdoors:
                self.needs['outdoors'] = min(100, self.needs['outdoors'] + 2.0 * delta_time)
            else:
                self.needs['outdoors'] = max(0, self.needs['outdoors'] - 0.5 * delta_time)
            
            # Beauty restoration from room itself (size/layout) + decay
            # Spacious rooms give a small beauty boost
            room_beauty_bonus = (current_room.beauty / 10.0) + (min(50, current_room.size) / 50.0)
            self.needs['beauty'] = clamp(self.needs['beauty'] + (room_beauty_bonus - 0.2) * delta_time, 0.0, 100.0)
        else:
            # Fallback for no room detected (should be rare)
            self.needs['outdoors'] = min(100, self.needs['outdoors'] + 1.0 * delta_time)
            self.needs['beauty'] = max(0, self.needs['beauty'] - 0.1 * delta_time)
        
        # Priority 0: Auto-eat if hungry and carrying food
        if self.needs['hunger'] < 70 and self.inventory['food'] > 0:
            # Consume food to restore hunger
            self.inventory['food'] -= 1
            self.needs['hunger'] = min(100, self.needs['hunger'] + 30)
            self.current_action = "eating"
            if VERBOSE_LOGGING:
                print(f"[Praxan] Auto-ate food, hunger now: {self.needs['hunger']:.1f}")
        
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
                            path = self.calculate_path(target.x, target.y, buildings, None, None, other_praxans)
                            if len(path) > 1:
                                self.path = path
                                self.current_waypoint_index = 1
                                # Move toward first waypoint
                                waypoint = path[1]
                                dx = waypoint[0] - self.x
                                dy = waypoint[1] - self.y
                                distance = math.sqrt(dx**2 + dy**2)
                                if distance > 0:
                                    self.vx = (dx / distance) * PRAXAN_SPEED
                                    self.vy = (dy / distance) * PRAXAN_SPEED
                                    self.current_action = "seeking food (pathfinding)"
                                    return None
                        # Direct movement for close targets
                        self.vx = (dx / distance) * PRAXAN_SPEED
                        self.vy = (dy / distance) * PRAXAN_SPEED
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
                        self.vx = (dx / distance) * PRAXAN_SPEED
                        self.vy = (dy / distance) * PRAXAN_SPEED
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
                        self.vx = (dx / distance) * PRAXAN_SPEED
                        self.vy = (dy / distance) * PRAXAN_SPEED
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
                            elif 'hospital' in action:
                                possible_actions.append('build_hospital')
                            elif 'school' in action:
                                possible_actions.append('build_school')
                            elif 'watchtower' in action:
                                possible_actions.append('build_watchtower')
                            elif 'market' in action:
                                possible_actions.append('build_market')
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
                        print(f"[Praxan {self.id}] Q-learning selected: {best_q_action}")
                    
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
                    print(f"[Praxan {self.id}] Q-learning error: {e}")
        
        # Priority 2: Execute directives if needs are met
        if self.state == STATE_EXECUTE_DIRECTIVE:
            # Only execute directives when explicitly in this state
            if directives and self.needs['hunger'] > 50 and self.needs['energy'] > 50:
                if VERBOSE_LOGGING and time.time() - getattr(self, '_last_directive_log', 0) > 2.0:
                    print(f"[Praxan {self.id}] In EXECUTE_DIRECTIVE state, processing {len(directives)} directives")
                    self._last_directive_log = time.time()
                # Choose role if we don't have one
                if not self.role:
                    self.choose_role(directives)
                
                # Weight directives by bonds with other praxans working on same task
                weighted_directives = []
                for directive in directives:
                    priority = directive['priority']
                    
                    # Check for bonded praxans working on this directive
                    bonded_praxans = self.get_bonded_praxans_on_directive(directive, other_praxans)
                    bond_bonus = 0
                    
                    if bonded_praxans:
                        # Calculate average bond strength
                        avg_bond = sum(self.bonds.get(t.id, 0) for t in bonded_praxans) / len(bonded_praxans)
                        if avg_bond > 50:
                            # Increase priority by 2 for each bonded praxan (capped at +6)
                            bond_bonus = min(6, len(bonded_praxans) * 2)
                    
                    # Create weighted directive
                    weighted_directive = directive.copy()
                    weighted_directive['weighted_priority'] = priority + bond_bonus
                    weighted_directives.append(weighted_directive)
                
                # Sort directives by weighted priority
                sorted_directives = sorted(weighted_directives, key=lambda d: d['weighted_priority'], reverse=True)
                
                # Try to follow highest priority directive
                directive_executed = False
                for directive in sorted_directives:
                    # Apply morale/happiness bonus when working with bonded praxans
                    bonded_praxans = self.get_bonded_praxans_on_directive(directive, other_praxans)
                    if bonded_praxans:
                        # Cohesion bonus: working with bonded praxans increases happiness
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
                        self.gather_resources(resources)
                        directive_executed = True
                        return None
                    
                    # Handle building directive
                    elif 'build' in action:
                        # Extract building type from action string if possible
                        building_type = 'house'
                        for b_type in ['farm', 'storage', 'house', 'workshop', 'shrine', 'well', 'hospital', 'school', 'watchtower', 'market']:
                            if b_type in action:
                                building_type = b_type
                                break
                        self.building_target_type = building_type
                        res = self.build_structure(buildings, resources, other_praxans, city_planner, territory_manager, hazards)
                        if res: # Successfully built or started building
                            directive_executed = True
                            return res
                        directive_executed = True
                        return None
                # If no directive was executed, transition to idle
                if not directive_executed:
                    if VERBOSE_LOGGING:
                        print(f"[Praxan {self.id}] No directive executed. Directives: {len(directives)}, Role: {self.role}")
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
                        self.vx = (dx / distance) * PRAXAN_SPEED
                        self.vy = (dy / distance) * PRAXAN_SPEED
                        self.current_action = "goal: migrating"
                        return None
            
            # Handle exploration goals
            if goal_type.startswith('explore_'):
                if 'north' in goal_type:
                    self.vy = -PRAXAN_SPEED
                    self.current_action = "exploring north"
                elif 'east' in goal_type:
                    self.vx = PRAXAN_SPEED
                    self.current_action = "exploring east"
                elif 'south' in goal_type:
                    self.vy = PRAXAN_SPEED
                    self.current_action = "exploring south"
                elif 'west' in goal_type:
                    self.vx = -PRAXAN_SPEED
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
                            self.vx = (dx / distance) * PRAXAN_SPEED
                            self.vy = (dy / distance) * PRAXAN_SPEED
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
                        self.vx = (dx / distance) * PRAXAN_SPEED
                        self.vy = (dy / distance) * PRAXAN_SPEED
                        self.current_action = "goal: resting"
                        return None
            
            # Handle reproduce goal (seeking mate)
            elif goal_type == 'reproduce' and other_praxans:
                if self.can_reproduce():
                    closest_mate = None
                    closest_distance = float('inf')
                    for other in other_praxans:
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
                                self.vx = (dx / distance) * PRAXAN_SPEED
                                self.vy = (dy / distance) * PRAXAN_SPEED
                                self.current_action = "goal: seeking mate"
                                return None
        # Priority 3: Manual Work Tasks (RimWorld style)
        if self.state == STATE_HAUL:
            # Need to pass stockpile_zones. We'll assume they are in context or buildings
            stockpile_zones = [] # Fallback
            if hasattr(self, 'game_ref'):
                stockpile_zones = getattr(self.game_ref, 'stockpile_zones', [])
            return self.haul_resources(resources, buildings, stockpile_zones)
            
        elif self.state == STATE_GATHER:
            return self.gather_resources(resources)
            
        elif self.state == STATE_BUILD:
            return self.build_structure(buildings, resources, other_praxans, city_planner, territory_manager, hazards)

        # Priority 3.2: Claim tile state (low priority for explorers)
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
                # Find nearby praxans to socialize with
                if other_praxans:
                    closest_friend = None
                    closest_distance = float('inf')
                    for other in other_praxans:
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
                            self.vx = (dx / distance) * PRAXAN_SPEED * 0.5
                            self.vy = (dy / distance) * PRAXAN_SPEED * 0.5
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
                    print(f"[Praxan {self.id}] Transitioning to EXECUTE_DIRECTIVE from {self.state}, {len(directives)} directives available")
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
                    self.vx = (dx / distance) * PRAXAN_SPEED
                    self.vy = (dy / distance) * PRAXAN_SPEED
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
           other_praxans:
            try:
                boids_cohesion, boids_separation = self.get_boids_forces(other_praxans, cohesion_radius=100)
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
                    print(f"[Praxan {self.id}] Boids error: {e}")
        
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
        print(f"Praxan {self.id} chose role: {self.role} (scores: {scores})")
    
    def can_reproduce(self):
        """Check if this praxan can reproduce"""
        # Check cooldown
        fertility_drive = getattr(self, "genetics", {}).get("fertility_drive", 1.0)
        effective_cooldown = REPRODUCTION_COOLDOWN / max(0.75, fertility_drive)
        if time.time() - self.last_reproduction_time < effective_cooldown:
            return False
        # Check needs threshold
        if self.needs['hunger'] < REPRODUCTION_NEEDS_THRESHOLD or self.needs['energy'] < REPRODUCTION_NEEDS_THRESHOLD or self.needs['thirst'] < REPRODUCTION_NEEDS_THRESHOLD:
            return False
        # Diseased praxans can't reproduce
        if self.diseased:
            return False
        # Unhappy praxans won't reproduce
        if self.happiness < 50:
            return False
        return True
    
    @staticmethod
    def create_offspring(parent1, parent2, x, y):
        """Create a new praxan with inherited traits from both parents"""
        child = Praxan(x, y)
        
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
        """Age praxan and decay health from unmet needs"""
        self.age = time.time() - self.birth_time
        decay_scale = 1.0 / max(0.75, self.resilience)
        
        if self.age >= PRAXAN_MAX_AGE:
            return False  # Should die
            
        damage_taken = 0.0
        
        if self.needs['hunger'] < 30:
            damage_taken += HEALTH_DECAY_BASE * 3 * delta_time * decay_scale
        elif self.needs['hunger'] < 50:
            damage_taken += HEALTH_DECAY_BASE * 1.5 * delta_time * decay_scale
            
        if self.needs['energy'] < 30:
            damage_taken += HEALTH_DECAY_BASE * 2 * delta_time * decay_scale
            
        if self.needs['thirst'] < 30:
            damage_taken += HEALTH_DECAY_BASE * 2.5 * delta_time * decay_scale
            
        if self.diseased:
            damage_taken += HEALTH_DECAY_BASE * 5 * delta_time * decay_scale
            
        if damage_taken > 0:
            self.take_damage(damage_taken, 'decay')
            
        health_regen = modifiers.get_modifier('health_regen') if modifiers else 0
        if health_regen > 0 and self.health < 100 and not self.diseased:
            self.heal_damage(health_regen * delta_time * 0.1)
            
        if self.morale > 70 and not self.diseased:
            self.heal_damage(0.015 * delta_time * self.resilience)
            
        return self.alive
        
    def update_temperature(self, delta_time, temp_grid):
        """Update body temperature based on ambient temperature and apply effects"""
        ambient_temp = temp_grid.get_temperature_at(self.x, self.y)
        
        # Thermoregulation efficiency based on health
        efficiency = self.health / 100.0
        
        # Pull body temp towards ambient
        temp_diff = ambient_temp - self.body_temp
        
        # Faster to get cold/hot than to return to normal if efficiency is low
        rate = 0.05 * delta_time
        if abs(temp_diff) > 10:
            rate *= 2.0
            
        # Tending towards 37.0 if ambient is comfortable (15-28)
        if 15.0 <= ambient_temp <= 28.0:
            self.body_temp += (37.0 - self.body_temp) * 0.1 * delta_time
        else:
            self.body_temp += temp_diff * rate

        # Apply thermal effects
        if self.body_temp < 35.0:
            # Hypothermia
            severity = (35.0 - self.body_temp) / 5.0  # e.g. 30.0 -> severity 1.0
            self.take_damage(severity * 5.0 * delta_time, 'cold')
            if random.random() < 0.1 * delta_time:
                self.add_moodlet("Freezing", -20, 30, time.time())
        elif self.body_temp > 38.5:
            # Heatstroke
            severity = (self.body_temp - 38.5) / 3.0  # e.g. 41.5 -> severity 1.0
            self.take_damage(severity * 5.0 * delta_time, 'heat')
            if random.random() < 0.1 * delta_time:
                self.add_moodlet("Overheating", -15, 30, time.time())
    
    def gain_skill_xp(self, skill_type, amount):
        """Level up skills"""
        if skill_type in self.skills:
            learning_affinity = getattr(self, "genetics", {}).get("learning_affinity", 1.0)
            self.skills[skill_type]['xp'] += amount * learning_affinity
            
            # Check for level up
            if self.skills[skill_type]['xp'] >= SKILL_LEVEL_THRESHOLD * self.skills[skill_type]['level']:
                self.skills[skill_type]['level'] += 1
                self.skills[skill_type]['xp'] = 0
                print(f"Praxan leveled up {skill_type} to level {self.skills[skill_type]['level']}!")
    
    def update_bonds(self, other_praxans, delta_time, modifiers=None):
        """Build/decay relationships"""
        # Create a set of alive praxan IDs for reference checking
        alive_ids = {t.id for t in other_praxans}
        social_cohesion = getattr(self, "genetics", {}).get("social_cohesion", 1.0)
        
        # Decay all existing bonds
        bond_decay_mod = modifiers.get_modifier('bond_decay') if modifiers else 1.0
        for praxan_id in list(self.bonds.keys()):
            # Remove bonds to dead praxans
            if praxan_id not in alive_ids:
                del self.bonds[praxan_id]
                continue
            self.bonds[praxan_id] -= (BOND_DECAY_RATE * bond_decay_mod * delta_time) / max(0.75, social_cohesion)
            if self.bonds[praxan_id] <= 0:
                del self.bonds[praxan_id]
        
        # Build bonds with nearby praxans
        for other in other_praxans:
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
    
    def update_happiness(self, buildings, other_praxans, modifiers=None, world_map=None):
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
        alive_ids = {t.id for t in other_praxans}
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
        self.base_mood = max(0, min(100, happiness))
    
    def contract_disease(self, chance):
        """Disease mechanics"""
        immune_strength = getattr(self, "genetics", {}).get("immune_strength", 1.0)
        if not self.diseased and random.random() < (chance / max(0.65, immune_strength)):
            self.diseased = True
            self.disease_start_time = time.time()
            print("Praxan contracted disease!")
    
    def share_knowledge(self, other_praxan):
        """Share discovered resources"""
        # Share resource knowledge
        for resource_pos in self.known_resources:
            if resource_pos not in other_praxan.known_resources:
                other_praxan.known_resources.append(resource_pos)
        
        # Territory system removed
    
    def query_llm(self, num_resources, praxan_id, num_buildings):
        """Query the LLM for decision making"""
        total_inv = self.inventory['food'] + self.inventory['wood'] + self.inventory['stone']
        prompt = f"""You are controlling one praxan in a local simulation.

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
                print(f"[Praxan {praxan_id}] Querying LLM at ({int(self.x)}, {int(self.y)}), inv={self.inventory}, resources={num_resources}")
            action_text, _ = generate_ollama_text(prompt, purpose="praxan")
            action_text = action_text.lower()
            if VERBOSE_LOGGING:
                print(f"[Praxan {praxan_id}] LLM raw response: {action_text[:100]}...")  # First 100 chars
            return self.parse_llm_response(action_text, praxan_id)
        except Exception as e:
            if VERBOSE_LOGGING:
                print(f"[Praxan {praxan_id}] LLM query error: {e}")
            # Fallback to random movement
            self.set_random_direction()
            return None
    
    def parse_llm_response(self, response_text, praxan_id):
        """Parse LLM response and determine action. Returns building_type if building."""
        response_lower = response_text.lower()
        
        # Check for movement directions
        if any(word in response_lower for word in ['left', 'west']):
            self.vx = -PRAXAN_SPEED
            self.vy = 0
            self.current_action = "moving left"
            if VERBOSE_LOGGING:
                print(f"[Praxan {praxan_id}] -> Moving LEFT")
            return None
        elif any(word in response_lower for word in ['right', 'east']):
            self.vx = PRAXAN_SPEED
            self.vy = 0
            self.current_action = "moving right"
            if VERBOSE_LOGGING:
                print(f"[Praxan {praxan_id}] -> Moving RIGHT")
            return None
        elif any(word in response_lower for word in ['up', 'north']):
            self.vx = 0
            self.vy = -PRAXAN_SPEED
            self.current_action = "moving up"
            if VERBOSE_LOGGING:
                print(f"[Praxan {praxan_id}] -> Moving UP")
            return None
        elif any(word in response_lower for word in ['down', 'south']):
            self.vx = 0
            self.vy = PRAXAN_SPEED
            self.current_action = "moving down"
            if VERBOSE_LOGGING:
                print(f"[Praxan {praxan_id}] -> Moving DOWN")
            return None
        elif any(word in response_lower for word in ['gather', 'collect', 'pickup']):
            self.vx = 0
            self.vy = 0
            self.current_action = "gathering"
            if VERBOSE_LOGGING:
                print(f"[Praxan {praxan_id}] -> GATHERING resources")
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
                print(f"[Praxan {praxan_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
                return building_type
            else:
                if VERBOSE_LOGGING:
                    print(f"[Praxan {praxan_id}] -> Wanted to build but no resources, using random direction")
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
                print(f"[Praxan {praxan_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
                return building_type
            else:
                if VERBOSE_LOGGING:
                    print(f"[Praxan {praxan_id}] -> Wanted to build but no resources, using random direction")
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
                print(f"[Praxan {praxan_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
                return building_type
            else:
                if VERBOSE_LOGGING:
                    print(f"[Praxan {praxan_id}] -> Wanted to build but no resources, using random direction")
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
                print(f"[Praxan {praxan_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
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
                print(f"[Praxan {praxan_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
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
                print(f"[Praxan {praxan_id}] -> BUILDING {building_type}! Inventory now: {self.inventory}")
                return building_type
            self.set_random_direction()
            return None
        else:
            # Unclear response, fallback to random movement
            if VERBOSE_LOGGING:
                print(f"[Praxan {praxan_id}] -> Unclear response, using random direction")
            self.set_random_direction()
            return None
    
    def set_random_direction(self):
        """Set a random direction"""
        direction = random.choice(['left', 'right', 'up', 'down'])
        if direction == 'left':
            self.vx = -PRAXAN_SPEED
            self.vy = 0
        elif direction == 'right':
            self.vx = PRAXAN_SPEED
            self.vy = 0
        elif direction == 'up':
            self.vx = 0
            self.vy = -PRAXAN_SPEED
        else:  # down
            self.vx = 0
            self.vy = PRAXAN_SPEED
        self.current_action = f"random {direction}"

    def calculate_capacities(self):
        for name, part in self.body_parts.items():
            if part['health'] <= 0:
                part['status'] = 'missing'
                part['efficiency'] = 0.0
            else:
                part['efficiency'] = part['health'] / part['max']
                if part['efficiency'] < 1.0:
                    part['status'] = 'injured'
                else:
                    part['status'] = 'intact'
                    
        total_pain = sum((part['max'] - part['health']) * 0.5 for part in self.body_parts.values())
        self.pain = min(1.0, total_pain / 100.0)
        
        consciousness = 1.0 - (self.pain * 0.5)
        consciousness *= self.body_parts['head']['efficiency']
        if self.needs.get('energy', 100) < 10:
            consciousness *= 0.5
        self.capacities['consciousness'] = max(0.0, min(1.0, consciousness))
        
        moving = (self.body_parts['left_leg']['efficiency'] + self.body_parts['right_leg']['efficiency']) / 2.0
        moving *= self.capacities['consciousness']
        self.capacities['moving'] = max(0.0, min(1.0, moving))
        
        manipulation = (self.body_parts['left_arm']['efficiency'] + self.body_parts['right_arm']['efficiency']) / 2.0
        manipulation *= self.capacities['consciousness']
        self.capacities['manipulation'] = max(0.0, min(1.0, manipulation))
        
        self.capacities['sight'] = self.body_parts['eyes']['efficiency'] * self.capacities['consciousness']
        
        total_hp = sum(p['health'] for p in self.body_parts.values())
        max_hp = sum(p['max'] for p in self.body_parts.values())
        self.health = (total_hp / max_hp) * 100.0
        
        if self.capacities['consciousness'] < 0.3 or self.capacities['moving'] < 0.15:
            self.downed = True
            self.state = 'downed'  # Defined in praxans_game.py as STATE_DOWNED
            self.current_action = "Downed (incapacitated)"
        else:
            self.downed = False
            if self.state == 'downed':
                self.state = STATE_IDLE
        
        if self.body_parts['torso']['health'] <= 0 or self.body_parts['head']['health'] <= 0 or self.capacities['consciousness'] <= 0:
            self.alive = False

    def take_damage(self, amount, damage_type='blunt', current_time=None):
        if not self.alive: return
        if current_time is None: current_time = time.time()
        
        parts = list(self.body_parts.keys())
        weights = [40, 10, 15, 15, 15, 15, 5] # Torso, head, arms, legs, eyes
        target_part = random.choices(parts, weights=weights, k=1)[0]
        
        self.body_parts[target_part]['health'] -= amount
        self.body_parts[target_part]['health'] = max(0, self.body_parts[target_part]['health'])
        
        if amount > 15:
            self.add_moodlet("In extreme pain", -15, 120, current_time)
            
        self.calculate_capacities()
        if VERBOSE_LOGGING:
            print(f"[Anatomy] Praxan {self.id} took {amount} {damage_type} damage to {target_part}. Health: {self.health:.1f}%")

    def heal_damage(self, amount):
        if not self.alive: return
        injured_parts = [name for name, part in self.body_parts.items() if part['status'] in ['injured', 'missing']]
        if not injured_parts: return
        target_part = random.choice(injured_parts)
        self.body_parts[target_part]['health'] = min(self.body_parts[target_part]['max'], self.body_parts[target_part]['health'] + amount)
        self.calculate_capacities()


