"""Botany System.

Simulates plant life cycles, growth, competition, and decay over time.
Plants duck-type the `Resource` class from `praxans_game.py` so that Praxans
can harvest 'wood' and 'food' from them seamlessly.
"""

import math
import random
import time
import pygame

# We duplicate some constants from praxans_game for isolated rendering
RESOURCE_RADIUS_FOOD = 7
RESOURCE_RADIUS_WOOD = 12
RESOURCE_COLLISION_DIST = 24
RED = (220, 50, 50)
BROWN = (139, 69, 19)
GRAY = (128, 128, 128)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRASS_DARK = (34, 139, 34)
GRASS_LIGHT = (144, 238, 144)
DIRT_MID = (160, 82, 45)

def blend_color(c1, c2, factor):
    return (
        int(c1[0] + (c2[0] - c1[0]) * factor),
        int(c1[1] + (c2[1] - c1[1]) * factor),
        int(c1[2] + (c2[2] - c1[2]) * factor)
    )

class Plant:
    """A living, breathing plant that Praxans can harvest as a Resource."""
    def __init__(self, x, y, species='oak_tree', starting_age=0.0, custom_name=None, color_override=None):
        self.x = x
        self.y = y
        self.species = species  # e.g., 'oak_tree', 'berry_bush'
        self.custom_name = custom_name
        self.color_override = color_override
        self.resource_type = 'wood' if 'tree' in species else 'food'
        
        # Resource Duck-typing
        self.collected = False
        self.collect_time = 0
        
        # Botany specifics
        self.age = starting_age
        self.max_age = random.uniform(2000, 5000) if 'tree' in species else random.uniform(800, 2000)
        self.health = 100.0
        self.is_dead = False
        
        # 0.1 (seedling) to 1.0 (fully grown)
        self.size = min(1.0, 0.1 + (self.age / self.max_age) * 1.5)
        
        # Reproduction
        self.reproduction_cooldown = random.uniform(200, 600)
        
        self.last_update = time.time()
        
    def update(self, current_time, dt, temperature, moisture, chunk_fertility, crowding_factor):
        """Grow, suffer, or die based on conditions."""
        if self.collected or self.is_dead:
            return
            
        self.age += dt
        
        if self.age >= self.max_age:
            self.die()
            return

        # Simple environmental constraints
        # Optimal temps: 15-25C. Optimal moisture: > 0.3
        temp_stress = 0.0
        if temperature < 0:
            temp_stress = 10.0 * dt
        elif temperature > 38:
            temp_stress = 5.0 * dt
            
        moist_stress = 0.0
        if moisture < 0.2:
            moist_stress = 3.0 * dt
            
        total_stress = temp_stress + moist_stress
        
        if total_stress > 0:
            self.health -= total_stress
        else:
            self.health = min(100.0, self.health + 2.0 * dt)
            
        # Competition stress
        if crowding_factor > 1.0:
            self.health -= (crowding_factor - 1.0) * 2.0 * dt
            
        if self.health <= 0:
            self.die()
            return
            
        # Growth
        target_size = min(1.0, 0.1 + (self.age / (self.max_age * 0.5)))
        growth_rate = 0.01 * dt * (chunk_fertility / 100.0)
        
        # Slower growth if crowded
        if crowding_factor > 0.5:
            growth_rate *= max(0.1, 1.0 - crowding_factor * 0.2)
            
        self.size = min(target_size, self.size + growth_rate)
        
        # Reproduction (only if mature and healthy)
        new_seed = None
        if self.size > 0.8 and self.health > 80:
            self.reproduction_cooldown -= dt
            if self.reproduction_cooldown <= 0:
                self.reproduction_cooldown = random.uniform(300, 800)
                # Give birth to a seed if not too crowded locally
                if crowding_factor < 1.5:
                    angle = random.uniform(0, math.pi * 2)
                    dist = random.uniform(40, 150)
                    new_seed = Plant(self.x + math.cos(angle)*dist, self.y + math.sin(angle)*dist, species=self.species, starting_age=0.0)
        
        return new_seed

    def die(self):
        """Plant dies naturally and is removed from harvestable pool."""
        self.is_dead = True
        self.collected = True
        self.collect_time = time.time()
    
    def check_collision(self, praxan):
        """Check if praxan is within collection distance"""
        if self.collected or self.is_dead:
            return False
        # Seedlings can't be harvested
        if self.size < 0.3:
            return False
            
        distance = math.sqrt((self.x - praxan.x)**2 + (self.y - praxan.y)**2)
        return distance < RESOURCE_COLLISION_DIST

    def draw(self, surface, praxans=None):
        if self.collected or self.is_dead:
            # Draw dead stump or withered bush if dead naturally
            if self.is_dead and not self.collected:
                pass # Optional: draw dead sprite
            return

        if self.resource_type == 'food':
            color = self.color_override or RED
            base_radius = RESOURCE_RADIUS_FOOD * self.size
        else:
            color = self.color_override or BROWN
            base_radius = RESOURCE_RADIUS_WOOD * self.size
        
        nearby = False
        if praxans:
            for praxan in praxans:
                distance = math.sqrt((self.x - praxan.x)**2 + (self.y - praxan.y)**2)
                if distance < 60:
                    nearby = True
                    break
        
        if nearby:
            glow_radius = int(base_radius + 8)
            glow_color = tuple(min(255, c + 100) for c in color)
            glow_surface = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(glow_surface, (*glow_color, 80), (glow_radius, glow_radius), glow_radius)
            surface.blit(glow_surface, (int(self.x - glow_radius), int(self.y - glow_radius)))

        shimmer = math.sin(time.time() * 4 + self.x * 0.05 + self.y * 0.03)
        highlight_color = blend_color(color, WHITE, 0.25 + 0.15 * max(0, shimmer))

        if self.resource_type == 'food':
            berry_offsets = [(-4*self.size, 1*self.size), (0, -2*self.size), (4*self.size, 1*self.size)]
            for off_x, off_y in berry_offsets:
                pygame.draw.circle(surface, BLACK, (int(self.x + off_x), int(self.y + off_y)), int(base_radius + 2))
                pygame.draw.circle(surface, color, (int(self.x + off_x), int(self.y + off_y)), max(1, int(base_radius + 1)))
            pygame.draw.line(surface, GRASS_DARK, (int(self.x), int(self.y - 7*self.size)), (int(self.x), int(self.y - 2*self.size)), 2)
            pygame.draw.circle(surface, highlight_color, (int(self.x), int(self.y - 1*self.size)), max(2, int(base_radius - 1)))
        
        elif self.resource_type == 'wood':
            trunk_w = max(2, int(6 * self.size))
            trunk_h = max(4, int(10 * self.size))
            trunk = pygame.Rect(int(self.x - trunk_w/2), int(self.y - trunk_h/2), trunk_w, trunk_h)
            foliage_center = (int(self.x), int(self.y - 6 * self.size))
            
            pygame.draw.rect(surface, BLACK, (trunk.x - 1, trunk.y - 1, trunk.width + 2, trunk.height + 2))
            pygame.draw.rect(surface, DIRT_MID, trunk)
            pygame.draw.circle(surface, BLACK, foliage_center, int(base_radius + 5*self.size))
            pygame.draw.circle(surface, GRASS_DARK, foliage_center, int(base_radius + 4*self.size))
            pygame.draw.circle(surface, GRASS_LIGHT, (foliage_center[0] - int(2*self.size), foliage_center[1] - int(2*self.size)), max(3, int(base_radius + 1*self.size)))


class BotanyManager:
    """Manages the lifecycle of all plants in the world."""
    def __init__(self, rng_seed=42):
        self.plants = []
        self.rng = random.Random(rng_seed)
        self.last_update = 0.0
        
    def spawn_initial_flora(self, chunk, tile_size):
        """Called by MapChunk instead of static generic resource gen."""
        # Use chunk coordinates to get a deterministic seed for flora generation
        seed_val = int(chunk.world_x * 73856093 + chunk.world_y * 19349663)
        rng = random.Random(seed_val)
        
        # Parse AI traits if present
        ai_ideas = getattr(self, 'ai_botany_ideas', [])
        ai_trees = [i for i in ai_ideas if 'tree' in str(i.get('description', '')).lower() or 'wood' in str(i.get('description', '')).lower()]
        ai_bushes = [i for i in ai_ideas if i not in ai_trees]
        
        def dict_to_color(hint: str) -> tuple[int, int, int] | None:
            if not hint: return None
            h = hint.lower()
            if 'red' in h: return (220, 50, 50)
            if 'blue' in h: return (50, 50, 220)
            if 'purple' in h: return (180, 50, 180)
            if 'yellow' in h: return (220, 220, 50)
            if 'white' in h: return (240, 240, 240)
            if 'cyan' in h: return (50, 220, 220)
            if 'orange' in h: return (220, 140, 50)
            if 'black' in h: return (30, 30, 30)
            if 'pink' in h: return (255, 105, 180)
            return None
        
        # Determine base density based on dominant biomes in the chunk
        densities = {
            'forest': {'wood': 0.65, 'food': 0.15},
            'taiga': {'wood': 0.50, 'food': 0.05},
            'swamp': {'wood': 0.35, 'food': 0.10},
            'plains': {'wood': 0.10, 'food': 0.08},
            'mountains': {'wood': 0.02, 'food': 0.01},
            'tundra': {'wood': 0.05, 'food': 0.02},
            'desert': {'wood': 0.01, 'food': 0.01},
            'snow': {'wood': 0.01, 'food': 0.00},
        }

        tile_plants = []
        for (tx, ty), biome in chunk.tiles.items():
            if (tx, ty) in chunk.water_tiles or (tx, ty) in chunk.river_tiles:
                continue
                
            rates = densities.get(biome, densities['plains'])
            
            # Trees (Wood)
            if rng.random() < rates['wood']:
                count = rng.randint(1, 3) if rates['wood'] > 0.4 else 1
                for _ in range(count):
                    px = chunk.world_x + (tx * tile_size) + rng.uniform(4, tile_size - 4)
                    py = chunk.world_y + (ty * tile_size) + rng.uniform(4, tile_size - 4)
                    # Start with random age so the forest isn't uniformly young
                    age = rng.uniform(500, 3000)
                    custom_name = None
                    color_override = None
                    if ai_trees:
                        idea = rng.choice(ai_trees)
                        custom_name = idea.get('name')
                        color_override = dict_to_color(idea.get('color_hint'))
                        
                    p = Plant(px, py, species='oak_tree' if biome != 'taiga' else 'pine_tree', starting_age=age, custom_name=custom_name, color_override=color_override)
                    tile_plants.append(p)
                    self.plants.append(p)
                    
            # Forage (Food)
            elif rng.random() < rates['food']:
                px = chunk.world_x + (tx * tile_size) + rng.uniform(4, tile_size - 4)
                py = chunk.world_y + (ty * tile_size) + rng.uniform(4, tile_size - 4)
                age = rng.uniform(100, 1000)
                
                custom_name = None
                color_override = None
                if ai_bushes:
                    idea = rng.choice(ai_bushes)
                    custom_name = idea.get('name')
                    color_override = dict_to_color(idea.get('color_hint'))
                    
                p = Plant(px, py, species='berry_bush', starting_age=age, custom_name=custom_name, color_override=color_override)
                tile_plants.append(p)
                self.plants.append(p)
                
        # To maintain interface with praxans_game, chunk needs a list of its resources.
        # We will extend the chunk's resources with these plants.
        chunk.resources.extend(tile_plants)

    def update(self, current_time: float, temperature_grid, ecology_manager):
        if self.last_update == 0:
            self.last_update = current_time
            return
            
        dt = current_time - self.last_update
        if dt < 2.0:  # Update botany every 2 seconds roughly
            return
            
        self.last_update = current_time
        
        # We only update a fraction of plants each tick for performance (time-slicing)
        # However, for simplicity today, we will update all that aren't collected.
        # Build a spatial hash for competition (Grid size 64x64)
        spatial_hash = {}
        for p in self.plants:
            if not p.is_dead and not p.collected:
                cell_x = int(p.x / 64)
                cell_y = int(p.y / 64)
                if (cell_x, cell_y) not in spatial_hash:
                    spatial_hash[(cell_x, cell_y)] = []
                spatial_hash[(cell_x, cell_y)].append(p)
        
        dead_plants = []
        new_plants = []
        for p in self.plants:
            if p.is_dead or p.collected:
                if p.is_dead:
                    # Return fertility to soil via EcologyManager
                    # EcologyManager API: requires a bit of parsing or we can just ignore for now
                    pass
                dead_plants.append(p)
                continue
                
            # Get local conditions
            temp = temperature_grid.get_temperature_at(p.x, p.y)
            moist = temperature_grid.get_moisture_at(p.x, p.y)
            
            # Get local fertility
            fert = 80.0
            if ecology_manager:
                try:
                    cell = ecology_manager._get_cell(p.x, p.y)
                    fert = cell.fertility
                except:
                    pass
            
            # Calculate crowding
            # Look at own cell and 8 neighbors
            cell_x = int(p.x / 64)
            cell_y = int(p.y / 64)
            crowding = 0.0
            
            for nx in (cell_x-1, cell_x, cell_x+1):
                for ny in (cell_y-1, cell_y, cell_y+1):
                    for neighbor in spatial_hash.get((nx, ny), []):
                        if neighbor is not p:
                            dist = math.sqrt((p.x - neighbor.x)**2 + (p.y - neighbor.y)**2)
                            if dist < 60:
                                # Taller neighbors cast shadow/steal roots more
                                relative_size = neighbor.size / max(0.1, p.size)
                                crowding += (60 - dist) / 30.0 * relative_size

            seed = p.update(current_time, dt, temp, moist, fert, crowding)
            if seed:
                new_plants.append(seed)
            
        # Clean up dead plants from our active tracking
        for dp in dead_plants:
            self.plants.remove(dp)
            
        # Add newborns
        for np in new_plants:
            self.plants.append(np)
