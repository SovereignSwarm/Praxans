"""Zoology System for Fauna simulation.

Manages animals with specific traits, diets, habitats, needs-driven AI, 
and population dynamics (predator/prey balancing).
"""

import math
import random
import time
import pygame

# Colors
ANIMAL_COLORS = {
    'herbivore': (100, 200, 100),
    'carnivore': (200, 80, 80),
    'omnivore': (180, 150, 100)
}

# Animal Species Definitions
# Contains base stats for different animal types
SPECIES_DEFS = {
    'muffalo': {
        'diet': 'herbivore',
        'speed': 15.0,
        'size': 1.5,
        'max_health': 150.0,
        'max_age': 3000,
        'preferred_biomes': ['plains', 'forest', 'tundra'],
        'food_value': 20, # How much food they drop
    },
    'warg': {
        'diet': 'carnivore',
        'speed': 35.0,
        'size': 1.0,
        'max_health': 80.0,
        'max_age': 2000,
        'preferred_biomes': ['forest', 'taiga', 'mountains'],
        'food_value': 10,
    },
    'hare': {
        'diet': 'herbivore',
        'speed': 40.0,
        'size': 0.4,
        'max_health': 15.0,
        'max_age': 500,
        'preferred_biomes': ['plains', 'forest', 'desert'],
        'food_value': 5,
    }
}

class Animal:
    """A living, breathing animal driven by needs and instincts."""
    _next_id = 0

    def __init__(self, x, y, species='hare'):
        self.id = Animal._next_id
        Animal._next_id += 1
        
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        
        self.species = species
        self.def_data = SPECIES_DEFS.get(species, SPECIES_DEFS['hare'])
        
        self.diet = self.def_data['diet']
        self.speed = self.def_data['speed']
        self.size = self.def_data['size']
        
        self.max_health = self.def_data['max_health']
        self.health = self.max_health
        self.age = 0.0
        self.max_age = self.def_data['max_age']
        
        self.is_dead = False
        
        # Needs (0-100, decrease over time)
        self.needs = {
            'hunger': random.uniform(50, 100),
            'thirst': random.uniform(50, 100),
            'sleep': random.uniform(50, 100),
            'mating': 0.0  # Increases over time
        }
        
        # State machine
        self.state = 'wander'
        self.target = None # Can be a plant, water tile, another animal, or (x, y) coordinates
        
        self.last_update = time.time()
        self.reproduction_cooldown = random.uniform(100, 300)
        
    def update(self, current_time, dt, temperature_grid, world_map, all_animals, botany_manager):
        if self.is_dead:
            return None
            
        self.age += dt
        if self.age >= self.max_age:
            self.die()
            return None
            
        # Drain needs
        self.needs['hunger'] -= 1.0 * dt
        self.needs['thirst'] -= 1.5 * dt
        self.needs['sleep'] -= 0.5 * dt
        self.needs['mating'] += 0.2 * dt
        
        # Check death by starvation/dehydration
        if self.needs['hunger'] <= 0 or self.needs['thirst'] <= 0:
            self.health -= 5.0 * dt
            
        if self.health <= 0:
            self.die()
            return None
            
        # Needs-driven AI
        self.think(current_time, dt, world_map, all_animals, botany_manager)
        self.act(dt)
        
        # Reproduction returns a new animal
        return self.try_reproduce(dt, all_animals)

    def think(self, current_time, dt, world_map, all_animals, botany_manager):
        """Determine what to do based on the lowest/most pressing need."""
        # Check threats first (fleeing overrides everything)
        threat = self.find_threat(all_animals)
        if threat:
            self.state = 'flee'
            self.target = threat
            return
            
        # If sleeping, keep sleeping until rested unless attacked
        if self.state == 'sleeping':
            if self.needs['sleep'] >= 100:
                self.state = 'wander'
                self.target = None
            else:
                self.needs['sleep'] += 5.0 * dt # Restore sleep
            return

        # Prioritize needs
        urgent_need = None
        min_val = 40.0 # Threshold for urgency
        
        if self.needs['thirst'] < min_val:
            urgent_need = 'thirst'
            min_val = self.needs['thirst']
            
        if self.needs['hunger'] < min_val:
            urgent_need = 'hunger'
            min_val = self.needs['hunger']
            
        if self.needs['sleep'] < 20.0 and not urgent_need:
            urgent_need = 'sleep'
            
        if self.needs['mating'] > 80.0 and self.needs['hunger'] > 60 and self.needs['thirst'] > 60:
            urgent_need = 'mating'

        if urgent_need == 'thirst':
            if self.state != 'seek_water':
                self.state = 'seek_water'
                self.target = self.find_water(world_map)
        elif urgent_need == 'hunger':
            if self.state != 'seek_food':
                self.state = 'seek_food'
                self.target = self.find_food(all_animals, botany_manager)
        elif urgent_need == 'sleep':
            self.state = 'sleeping'
            self.target = None
        elif urgent_need == 'mating':
            if self.state != 'seek_mate':
                self.state = 'seek_mate'
                self.target = self.find_mate(all_animals)
        else:
            # Wander randomly if all needs are met
            if self.state not in ['wander', 'sleeping']:
                self.state = 'wander'
                self.target = (self.x + random.uniform(-100, 100), self.y + random.uniform(-100, 100))
            elif self.state == 'wander' and random.random() < 0.05 * dt:
                self.target = (self.x + random.uniform(-100, 100), self.y + random.uniform(-100, 100))

    def act(self, dt):
        """Execute the current state."""
        if self.state == 'sleeping' or self.is_dead:
            self.vx, self.vy = 0, 0
            return
            
        speed_mult = 1.0
        
        if self.state == 'flee' and self.target:
            # Run away from target
            dx = self.x - self.target.x
            dy = self.y - self.target.y
            dist = math.sqrt(dx**2 + dy**2)
            if dist < 300: # Flee radius
                if dist > 0:
                    self.vx = (dx/dist) * self.speed * 1.5
                    self.vy = (dy/dist) * self.speed * 1.5
            else:
                self.state = 'wander'
                self.target = None
                
        elif self.state == 'seek_food' and self.target:
            dx = self.target.x - self.x
            dy = self.target.y - self.y
            dist = math.sqrt(dx**2 + dy**2)
            
            if dist < 15: # Reach threshold
                self.eat()
            elif dist > 0:
                self.vx = (dx/dist) * self.speed
                self.vy = (dy/dist) * self.speed
                
        elif self.state in ['wander', 'seek_water', 'seek_mate'] and self.target:
            tx, ty = self.target if isinstance(self.target, tuple) else (self.target.x, self.target.y)
            dx = tx - self.x
            dy = ty - self.y
            dist = math.sqrt(dx**2 + dy**2)
            
            if dist < 15:
                if self.state == 'seek_water':
                    self.drink()
                elif self.state == 'seek_mate':
                    self.mate(self.target)
                else:
                    self.state = 'wander'
                    self.target = None
                    self.vx, self.vy = 0, 0
            elif dist > 0:
                self.vx = (dx/dist) * self.speed * (0.5 if self.state == 'wander' else 1.0)
                self.vy = (dy/dist) * self.speed * (0.5 if self.state == 'wander' else 1.0)
                
        # Apply movement
        self.x += self.vx * dt
        self.y += self.vy * dt
        
    def eat(self):
        """Consume the target."""
        if not self.target:
            return
            
        if self.diet == 'herbivore':
            # Target is a plant
            if hasattr(self.target, 'is_dead') and not self.target.is_dead:
                self.target.die() # Consume plant
                self.needs['hunger'] = 100
        elif self.diet == 'carnivore':
            # Target is an animal
            if hasattr(self.target, 'is_dead') and not self.target.is_dead:
                self.target.health -= 20 # Deal damage
                if self.target.health <= 0:
                    self.target.die()
                    self.needs['hunger'] = 100
                    
        self.state = 'wander'
        self.target = None

    def drink(self):
        """Drink water."""
        self.needs['thirst'] = 100
        self.state = 'wander'
        self.target = None
        
    def mate(self, partner):
        """Initiate mating."""
        if isinstance(partner, Animal) and not partner.is_dead:
            self.needs['mating'] = 0
            partner.needs['mating'] = 0 # Fulfill partner's need too
            self.reproduction_cooldown = 0 # Ready to spawn
        self.state = 'wander'
        self.target = None
        
    def try_reproduce(self, dt, all_animals):
        self.reproduction_cooldown -= dt
        if self.reproduction_cooldown <= 0 and self.needs['mating'] == 0:
            self.reproduction_cooldown = random.uniform(300, 600)
            
            # Limit population locally
            nearby_kin = sum(1 for a in all_animals if a.species == self.species and not a.is_dead and math.sqrt((a.x-self.x)**2 + (a.y-self.y)**2) < 400)
            if nearby_kin < 10:
                angle = random.uniform(0, math.pi * 2)
                return Animal(self.x + math.cos(angle)*30, self.y + math.sin(angle)*30, species=self.species)
        return None

    def find_threat(self, all_animals):
        if self.diet != 'herbivore':
            return None # Apex predators don't flee for now
            
        for a in all_animals:
            if a.diet == 'carnivore' and not a.is_dead:
                dist = math.sqrt((a.x - self.x)**2 + (a.y - self.y)**2)
                if dist < 250:
                    return a
        return None

    def find_food(self, all_animals, botany_manager):
        best_target = None
        best_dist = 600 # View radius
        
        if self.diet == 'herbivore':
            if botany_manager:
                for p in botany_manager.plants:
                    if not p.is_dead and p.resource_type == 'food':
                        dist = math.sqrt((p.x - self.x)**2 + (p.y - self.y)**2)
                        if dist < best_dist:
                            best_dist = dist
                            best_target = p
        elif self.diet == 'carnivore':
            for a in all_animals:
                if a.species != self.species and not a.is_dead:
                    dist = math.sqrt((a.x - self.x)**2 + (a.y - self.y)**2)
                    if dist < best_dist:
                        best_dist = dist
                        best_target = a
                        
        return best_target

    def find_water(self, world_map):
        # Simplified: target nearest river or water tile center
        # We sample a few points around to find water
        for dx in [-200, 0, 200]:
            for dy in [-200, 0, 200]:
                tx, ty = self.x + dx, self.y + dy
                biome = world_map.get_biome_at(tx, ty) if world_map else None
                if biome == 'swamp' or (world_map and world_map._is_water_world_coord(tx, ty)):
                    return (tx, ty)
        return (self.x + random.uniform(-100, 100), self.y + random.uniform(-100, 100)) # Default random wandering if no water found

    def find_mate(self, all_animals):
        for a in all_animals:
            if a is not self and a.species == self.species and not a.is_dead and a.needs['mating'] > 60:
                dist = math.sqrt((a.x - self.x)**2 + (a.y - self.y)**2)
                if dist < 400:
                    return a
        return None

    def die(self):
        self.is_dead = True
        
    def draw(self, surface, camera):
        if self.is_dead:
            return
            
        color = ANIMAL_COLORS.get(self.diet, (255, 255, 255))
        radius = max(3, int(6 * self.size))
        
        # Draw body
        pygame.draw.circle(surface, (0, 0, 0), (int(self.x), int(self.y)), radius + 1)
        pygame.draw.circle(surface, color, (int(self.x), int(self.y)), radius)
        
        # Draw "head" indicating direction
        if self.vx != 0 or self.vy != 0:
            angle = math.atan2(self.vy, self.vx)
            hx = self.x + math.cos(angle) * radius
            hy = self.y + math.sin(angle) * radius
            pygame.draw.circle(surface, (0, 0, 0), (int(hx), int(hy)), max(2, int(radius * 0.5)))
            
        # Optional: draw sleep indicator
        if self.state == 'sleeping':
            # Zzz
            pass

class ZoologyManager:
    """Manages all wildlife across the simulation."""
    def __init__(self, rng_seed=42):
        self.animals = []
        self.rng = random.Random(rng_seed)
        self.last_update = 0.0
        
    def spawn_initial_fauna(self, chunk, tile_size):
        """Called by MapChunk for initial population."""
        seed_val = int(chunk.world_x * 93856093 + chunk.world_y * 29349663)
        rng = random.Random(seed_val)
        
        for (tx, ty), biome in chunk.tiles.items():
            if (tx, ty) in chunk.water_tiles or (tx, ty) in chunk.river_tiles:
                continue
                
            px = chunk.world_x + (tx * tile_size) + rng.uniform(4, tile_size - 4)
            py = chunk.world_y + (ty * tile_size) + rng.uniform(4, tile_size - 4)
            
            # Spawn based on biome
            for species, def_data in SPECIES_DEFS.items():
                if biome in def_data['preferred_biomes']:
                    if rng.random() < 0.02: # 2% chance per tile per matched species
                        self.animals.append(Animal(px, py, species))
                        
    def update(self, current_time: float, temperature_grid, world_map, botany_manager):
        if self.last_update == 0:
            self.last_update = current_time
            return
            
        dt = current_time - self.last_update
        if dt < 0.5: # Update fairly frequently for smooth movement
            return
            
        self.last_update = current_time
        
        dead_animals = []
        new_animals = []
        
        for a in self.animals:
            if a.is_dead:
                dead_animals.append(a)
                continue
                
            offspring = a.update(current_time, dt, temperature_grid, world_map, self.animals, botany_manager)
            if offspring:
                new_animals.append(offspring)
                
        for da in dead_animals:
            self.animals.remove(da)
            
        self.animals.extend(new_animals)
        return dead_animals

    def draw(self, surface, camera):
        for a in self.animals:
            if not a.is_dead:
                a.draw(surface, camera)
