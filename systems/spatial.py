import pygame
import pygame.gfxdraw
import math
import random
from datetime import datetime
from praxans_game import *

class FogOfWar:
    """Manages fog of war - areas not yet explored are hidden"""
    def __init__(self, world_width, world_height):
        self.fog_grid = {}  # {(tile_x, tile_y): visibility_level (0-255)}
        self.visibility_radius = 60  # Pixels around each praxan (much smaller)
        self.world_width = world_width
        self.world_height = world_height
    
    def update(self, praxans, buildings=None, world_map=None):
        """Update fog using Line of Sight (Raycasting)"""
        # Precompute vision-blocking tiles from buildings securely
        blocking_tiles = set()
        if buildings:
            for b in buildings:
                if getattr(b, 'building_type', '') not in ['watchtower', 'well', 'farm']:
                    tx = int(b.x // TILE_SIZE)
                    ty = int(b.y // TILE_SIZE)
                    blocking_tiles.add((tx, ty))

        def _blocks_vision(tx, ty):
            if (tx, ty) in blocking_tiles:
                return True
            if world_map is not None:
                wx = tx * TILE_SIZE
                wy = ty * TILE_SIZE
                try:
                    biome = world_map.get_biome_at(wx, wy)
                    if biome in ['mountains']: 
                        return True
                except Exception:
                    pass
            return False

        def _reveal_los(center_x, center_y, tile_radius, ignore_blocks=False):
            # Reveal center
            self.fog_grid[(center_x, center_y)] = 255
            
            # Midpoint circle algorithm to get perimeter points
            perimeter = set()
            x = tile_radius
            y = 0
            err = 0

            while x >= y:
                perimeter.add((center_x + x, center_y + y))
                perimeter.add((center_x + y, center_y + x))
                perimeter.add((center_x - y, center_y + x))
                perimeter.add((center_x - x, center_y + y))
                perimeter.add((center_x - x, center_y - y))
                perimeter.add((center_x - y, center_y - x))
                perimeter.add((center_x + y, center_y - x))
                perimeter.add((center_x + x, center_y - y))
                
                y += 1
                if err <= 0:
                    err += 2 * y + 1
                if err > 0:
                    x -= 1
                    err -= 2 * x + 1
                    
            # Cast ray to each perimeter point using Bresenham's line algorithm
            for px, py in perimeter:
                x0, y0 = center_x, center_y
                x1, y1 = px, py
                dx = abs(x1 - x0)
                dy = -abs(y1 - y0)
                sx = 1 if x0 < x1 else -1
                sy = 1 if y0 < y1 else -1
                err = dx + dy
                
                cx, cy = x0, y0
                while True:
                    # Reveal current tile
                    self.fog_grid[(cx, cy)] = 255
                    
                    if cx == x1 and cy == y1:
                        break
                        
                    # If this tile blocks vision, stop this ray
                    if not ignore_blocks and (cx != center_x or cy != center_y) and _blocks_vision(cx, cy):
                        break
                        
                    e2 = 2 * err
                    if e2 >= dy:
                        err += dy
                        cx += sx
                    if e2 <= dx:
                        err += dx
                        cy += sy

        for praxan in praxans:
            # Apply exploration skill bonus to visibility radius
            radius = self.visibility_radius
            if praxan.role == 'explorer':
                radius = int(self.visibility_radius * praxan.get_exploration_bonus())
            
            tile_radius = int(radius / TILE_SIZE) + 1
            tile_center_x = int(praxan.x // TILE_SIZE)
            tile_center_y = int(praxan.y // TILE_SIZE)
            
            _reveal_los(tile_center_x, tile_center_y, tile_radius)
            
        if buildings:
            for building in buildings:
                if building.building_type == 'watchtower':
                    # Massive visibility radius for watchtower
                    radius = self.visibility_radius * 4.0
                    tile_radius = int(radius / TILE_SIZE) + 1
                    tile_center_x = int(building.x // TILE_SIZE)
                    tile_center_y = int(building.y // TILE_SIZE)
                    
                    # Watchtowers see over obstacles
                    _reveal_los(tile_center_x, tile_center_y, tile_radius, ignore_blocks=True)
    
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
    """Manages territory claiming based on praxan presence and buildings using Voronoi diagram"""
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
    
    def update(self, praxans, buildings):
        """Update territory based on praxan positions and buildings using Voronoi diagram"""
        current_time = time.time()
        current_population = len(praxans) + len(buildings)
        
        # Check if we need to recalculate Voronoi diagram
        needs_recalculation = (
            not self.voronoi_cache_valid or
            (current_time - self.last_voronoi_calculation) > self.VORONOI_RECALC_INTERVAL or
            abs(current_population - self.last_population_count) > 3  # Significant population change
        )
        
        if needs_recalculation:
            self._calculate_voronoi_cells(praxans, buildings)
            self.last_voronoi_calculation = current_time
            self.last_population_count = current_population
            self.voronoi_cache_valid = True
        
        # Update claim strength based on Voronoi assignment
        self._update_claim_strength_from_voronoi(praxans, buildings)
        
        # Decay unclaimed tiles
        to_remove = []
        for tile_pos, data in self.territory_grid.items():
            data['claim_strength'] -= TERRITORY_DECAY_RATE
            if data['claim_strength'] <= 0:
                to_remove.append(tile_pos)
        
        for tile_pos in to_remove:
            del self.territory_grid[tile_pos]
    
    def _calculate_voronoi_cells(self, praxans, buildings):
        """Calculate Voronoi diagram using praxan positions and building centers as seeds"""
        self.voronoi_seeds = []
        self.voronoi_cache = {}
        seed_id = 0
        
        # Collect seeds from praxans
        for praxan in praxans:
            self.voronoi_seeds.append((praxan.x, praxan.y, seed_id, 'exploration'))
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
    
    def _update_claim_strength_from_voronoi(self, praxans, buildings):
        """Update claim strength based on Voronoi assignment and seed proximity"""
        current_time = time.time()
        
        # Build seed lookup by ID
        seed_lookup = {}
        seed_id = 0
        for praxan in praxans:
            seed_lookup[seed_id] = ('praxan', praxan.x, praxan.y)
            seed_id += 1
        for building in buildings:
            seed_lookup[seed_id] = ('building', building.x, building.y, building.building_type)
            seed_id += 1
        
        # Update territory grid from Voronoi cache
        for (tile_x, tile_y), (seed_id, center_type) in self.voronoi_cache.items():
            if seed_id not in seed_lookup:
                continue  # Seed no longer exists
            
            seed_type = seed_lookup[seed_id][0]
            seed_x = seed_lookup[seed_id][1]
            seed_y = seed_lookup[seed_id][2]
            building_type = seed_lookup[seed_id][3] if seed_type == 'building' else None
            
            world_x = tile_x * TILE_SIZE + TILE_SIZE // 2
            world_y = tile_y * TILE_SIZE + TILE_SIZE // 2
            
            # Calculate distance from tile center to seed
            distance = math.sqrt((world_x - seed_x)**2 + (world_y - seed_y)**2)
            
            # Claim strength based on distance (closer = stronger)
            max_radius = BUILDING_CLAIM_RADIUS if seed_type == 'building' else TERRITORY_CLAIM_RADIUS
            if building_type == 'watchtower':
                max_radius = TERRITORY_CLAIM_RADIUS * 3.0
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
        self.building_priority = []  # LLM-recommended building types
        self.proposed_sites = []  # [(x, y, building_type)] for ghost markers
    
    def update(self, praxans, buildings, advisor, current_time):
        """Update city planner, check for plan updates"""
        # Generate zones if territory exists
        if self.territory_manager.territory_grid:
            bounds = self.territory_manager.get_territory_bounds()
            if bounds:
                self._generate_zones(bounds['center_x'], bounds['center_y'])
        
        # Check if we need a new city plan
        num_praxans = len(praxans)
        if (num_praxans > 10 and not self.current_plan) or \
           (current_time - self.last_plan_update > self.plan_update_interval):
            self._request_city_plan_from_llm(praxans, buildings, advisor)
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
    
    def score_building_location(self, x, y, building_type, buildings, hazards, world_map, praxans=None):
        """Score a building location 0-100, checking strict grid footprints for collision."""
        score = 50  # Base score
        
        # Pull footprint sizes
        from graphics.content import BUILDING_FOOTPRINT_ART
        from praxans_game import TILE_SIZE
        # Default to 1x1 if unknown
        recipe = BUILDING_FOOTPRINT_ART.get(building_type)
        gw = recipe.grid_width if recipe else 1
        gh = recipe.grid_height if recipe else 1
        
        # Define the proposed bounding box in world pixels
        prop_rect = (x, y, x + gw * TILE_SIZE, y + gh * TILE_SIZE)
        
        # Territory bonus
        if self.territory_manager.is_claimed(x, y, threshold=40):
            score += 30
        else:
            score -= 15  # Soft penalty
        
        # Boids clustering: Check nearby praxan density (prefer areas with praxans)
        if praxans:
            nearby_praxan_count = 0
            density_radius = 150  # Check within 150px
            for praxan in praxans:
                distance = math.sqrt((praxan.x - x)**2 + (praxan.y - y)**2)
                if distance < density_radius:
                    nearby_praxan_count += 1
            
            # Bonus for clustering (2-4 praxans nearby is ideal)
            if 2 <= nearby_praxan_count <= 4:
                score += 15  # Good clustering
            elif nearby_praxan_count >= 5:
                score += 10  # Still good but getting crowded
            elif nearby_praxan_count == 1:
                score += 5  # Some activity
            elif nearby_praxan_count == 0:
                score -= 5  # Isolated location (slight penalty)
        
        # Proximity and COLLISION bonuses/penalties
        for building in buildings:
            b_recipe = BUILDING_FOOTPRINT_ART.get(getattr(building, "building_type", "house"))
            b_gw = b_recipe.grid_width if b_recipe else 1
            b_gh = b_recipe.grid_height if b_recipe else 1
            
            # Existing building bounding box
            bx, by = building.x, building.y
            b_rect = (bx, by, bx + b_gw * TILE_SIZE, by + b_gh * TILE_SIZE)
            
            # Strict AABB overlap check - NEVER allow overlapping buildings!
            if not (prop_rect[2] <= b_rect[0] or prop_rect[0] >= b_rect[2] or prop_rect[3] <= b_rect[1] or prop_rect[1] >= b_rect[3]):
                return 0  # Fatal collision! Location invalid.
            
            # Center-to-center distance for adjacency calculations
            prop_cx = x + (gw * TILE_SIZE) / 2
            prop_cy = y + (gh * TILE_SIZE) / 2
            b_cx = bx + (b_gw * TILE_SIZE) / 2
            b_cy = by + (b_gh * TILE_SIZE) / 2
            distance = math.sqrt((b_cx - prop_cx)**2 + (b_cy - prop_cy)**2)
            
            # Clustering rules
            btype = str(getattr(building, "building_type", ""))
            if building_type == 'house' and btype == 'house':
                if distance < 120:  # Scaled for larger tiles
                    score += 20
                elif distance > 300:
                    score -= 10
            
            elif building_type == 'farm' and btype == 'storage':
                if distance < 150:
                    score += 15
                elif distance > 350:
                    score -= 10
            
            elif building_type == 'workshop' and btype == 'house':
                if distance < 150:
                    score += 10
            
            # Avoid placing directly touching (provide a small 1 tile buffer if possible)
            if distance < TILE_SIZE * 1.5:
                score -= 10
        
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
        
        # LLM building priority bonus — council-recommended buildings score higher
        if self.building_priority:
            if building_type == self.building_priority[0]:
                score += 25  # Top priority
            elif building_type in self.building_priority:
                score += 15  # Lower priority
        
        return max(0, min(100, score))  # Clamp 0-100
    
    def find_best_location(self, building_type, buildings, hazards, search_center, search_radius=150, praxans=None):
        """Find best location for a building"""
        best_score = -1
        best_x, best_y = search_center
        
        # Sample 30 candidate positions
        from praxans_game import TILE_SIZE
        for _ in range(30):
            # Random offset within search radius
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(0, search_radius)
            candidate_x = search_center[0] + distance * math.cos(angle)
            candidate_y = search_center[1] + distance * math.sin(angle)
            
            # Snap rigidly to TILE_SIZE grid to create perfectly aligned Rimworld-style rooms
            candidate_x = round(candidate_x / TILE_SIZE) * TILE_SIZE
            candidate_y = round(candidate_y / TILE_SIZE) * TILE_SIZE
            
            # Score this location
            score = self.score_building_location(
                candidate_x, candidate_y, building_type, 
                buildings, hazards, self.world_map, praxans
            )
            
            if score > best_score:
                best_score = score
                best_x, best_y = candidate_x, candidate_y
        
        return best_x, best_y, best_score
    
    def _request_city_plan_from_llm(self, praxans, buildings, advisor):
        """Read the LLM council's building_priority and compute proposed sites."""
        # Pull building priority from the advisor's latest council output
        bp = list(getattr(advisor, 'session_stats', {}).get('building_priority', []))
        if not bp:
            bp = list((getattr(advisor, 'json_directives', {}) or {}).get('building_priority', []))
        self.building_priority = bp[:3]

        # Generate proposed sites for the top-priority building
        self.proposed_sites = []
        if self.building_priority and buildings:
            target_type = self.building_priority[0]
            bounds = self.territory_manager.get_territory_bounds()
            if bounds:
                search_center = (bounds['center_x'], bounds['center_y'])
                bx, by, bscore = self.find_best_location(
                    target_type, buildings, [], search_center,
                    search_radius=200, praxans=praxans,
                )
                if bscore > 40:
                    self.proposed_sites.append((bx, by, target_type))

        if self.building_priority:
            self.current_plan = {
                'building_priority': list(self.building_priority),
                'proposed_sites': list(self.proposed_sites),
                'rationale': f'Council recommends: {", ".join(self.building_priority)}',
            }

    def zone_summary(self) -> str:
        """Compact zone distribution summary for LLM state views."""
        from collections import Counter
        counts = Counter(self.zones.values())
        if not counts:
            return "(no zones defined yet)"
        parts = [f"{zt}:{ct}" for zt, ct in counts.most_common()]
        bp_text = f" | Priority: {', '.join(self.building_priority)}" if self.building_priority else ""
        return f"Zones: {', '.join(parts)}{bp_text}"
    
    def get_plan_summary(self):
        """Get human-readable summary of current plan"""
        if not self.current_plan:
            return "No city plan yet"
        
        summary = []
        if self.building_priority:
            summary.append(f"Build priority: {', '.join(self.building_priority)}")
        if self.proposed_sites:
            for sx, sy, stype in self.proposed_sites:
                summary.append(f"- Proposed {stype} at ({int(sx)}, {int(sy)})")
        if 'districts' in self.current_plan:
            for district in self.current_plan['districts']:
                district_text = f"- {district.get('type', 'unknown')} (priority {district.get('priority', 0)}): {district.get('location', 'unknown')}"
                summary.append(district_text)
        
        if 'expansion_direction' in self.current_plan:
            summary.append(f"Expansion: {self.current_plan['expansion_direction']}")
        
        if 'rationale' in self.current_plan:
            summary.append(f"Reason: {self.current_plan['rationale']}")
        
        return "\n".join(summary) if summary else "Plan exists but empty"


