"""Climate & Weather System for the Deep Ecological Simulation.

This module handles:
1. Advanced Seasonal Drift (smooth transitions rather than harsh snapping)
2. Global Climate (long-term epoch shifts like ice ages or global warming)
3. Dynamic Weather (with lasting ecological consequences)
4. Continuous ClimateGrid (tracking temperature and moisture locally)
"""

import math
import random
import time

# --- Constants ---
SEASON_LENGTH = 300  # seconds per season
YEAR_LENGTH = SEASON_LENGTH * 4

class Season:
    """Manages continuous seasonal cycles and smooth transitions."""
    def __init__(self):
        self.seasons = ['spring', 'summer', 'autumn', 'winter']
        self.current = 'spring'
        self.progress = 0.0  # 0.0 to 1.0 through the current season
        self.year = 1

    def update(self, game_time: float):
        total_time = game_time
        self.year = int(total_time // YEAR_LENGTH) + 1
        
        elapsed_in_year = total_time % YEAR_LENGTH
        season_index = int(elapsed_in_year // SEASON_LENGTH)
        
        self.current = self.seasons[season_index]
        self.progress = (elapsed_in_year % SEASON_LENGTH) / SEASON_LENGTH

    def get_temperature_modifier(self) -> float:
        """Returns a smooth sine-wave modifier for temperature throughout the year."""
        # 0.0 is start of spring, 0.25 is mid summer, 0.5 is start of autumn, 0.75 is mid winter
        # We want peak heat in mid-summer, peak cold in mid-winter.
        season_idx = self.seasons.index(self.current)
        yearly_progress = (season_idx + self.progress) / 4.0
        
        # Spring starts at 0, Summer peaks at +15, Autumn back to 0, Winter troughs at -20
        # A simple shifted sine wave: 
        # sin(yearly_progress * 2PI - PI/2) goes from -1 (winter) to +1 (summer)
        # We map this to a range roughly [-25, +20]
        angle = yearly_progress * 2 * math.pi - (math.pi / 2.0)
        sine_val = math.sin(angle)
        
        if sine_val > 0:
            return sine_val * 20.0  # Summer heat
        else:
            return sine_val * 25.0  # Winter freeze

    def get_resource_modifier(self) -> dict[str, float]:
        """Return base resource spawn modifiers for current season."""
        # Smooth interpolation between seasons could be done, but for gameplay
        # static thresholds may be better suited.
        modifiers = {
            'spring': {'food': 1.2, 'wood': 1.0, 'stone': 1.0},
            'summer': {'food': 1.0, 'wood': 1.0, 'stone': 1.0},
            'autumn': {'food': 1.3, 'wood': 1.1, 'stone': 1.0},
            'winter': {'food': 0.5, 'wood': 0.8, 'stone': 1.2}
        }
        return modifiers.get(self.current, modifiers['summer'])


class GlobalClimate:
    """Tracks huge, world-spanning phenomena like global dimming or warming."""
    def __init__(self, seed=int(time.time())):
        self.rng = random.Random(seed)
        self.global_temp_offset = 0.0
        self.global_moisture_offset = 0.0
        
        self.epoch = "Holocene"  # Flavour text
        self.target_temp_offset = 0.0
        self.target_moisture_offset = 0.0
        self.shift_speed = 0.001
        
        self.last_shift_time = time.time()

    def update(self, current_time: float):
        if current_time - self.last_shift_time > 600: # Every 10 real minutes, shift epoch goals
            self.last_shift_time = current_time
            # Drift targets unpredictably to simulate chaotic macro-climate
            self.target_temp_offset += self.rng.uniform(-3.0, 3.0)
            self.target_temp_offset = max(-15.0, min(15.0, self.target_temp_offset))
            
            self.target_moisture_offset += self.rng.uniform(-0.15, 0.15)
            self.target_moisture_offset = max(-0.4, min(0.4, self.target_moisture_offset))
            
            if self.target_temp_offset < -8.0:
                self.epoch = "Ice Age"
            elif self.target_temp_offset > 8.0:
                self.epoch = "Global Warming"
            else:
                self.epoch = "Temperate Holocene"

        # Smoothly lerp towards targets
        self.global_temp_offset += (self.target_temp_offset - self.global_temp_offset) * self.shift_speed
        self.global_moisture_offset += (self.target_moisture_offset - self.global_moisture_offset) * self.shift_speed


class WeatherSystem:
    def __init__(self):
        self.current_weather = 'clear'
        self.next_event_time = time.time() + random.uniform(45, 90)
        self.active_event_end = 0.0

    def update(self, current_time: float, season_name: str, difficulty: float = 1.0) -> dict | None:
        """Check for and trigger weather events. Returns event info if a new one just started."""
        
        # If an event is happening and it ends, clear it
        if self.current_weather != 'clear' and current_time >= self.active_event_end:
            self.current_weather = 'clear'
            self.next_event_time = current_time + random.uniform(30, 60)
            return None

        # If it's time for a new event
        if self.current_weather == 'clear' and current_time >= self.next_event_time:
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
                    
            if event_type != 'clear':
                self.current_weather = event_type
                duration = random.uniform(20.0, 45.0)
                self.active_event_end = current_time + duration
                return {'type': event_type, 'duration': duration}
            else:
                self.next_event_time = current_time + random.uniform(20, 40)
                
        return None

    def get_effects(self) -> dict:
        """Return current weather effects for Praxans."""
        effects = {
            'clear': {},
            'rain': {'food': 0.15, 'thirst': 0.04, 'happiness': 0},
            'storm': {'energy': -0.05, 'happiness': -10},
            'drought': {'thirst': -0.1, 'food': -0.5, 'happiness': -6},
            'aurora': {'happiness': 8, 'energy': 0.02},
        }
        return effects.get(self.current_weather, {})


class TemperatureGrid:
    """Manages continuous temperature and moisture per chunk region."""
    def __init__(self, world_width: float, world_height: float, cell_size: int = 512):
        self.cell_size = cell_size
        self.cols = int(world_width / cell_size) + 1
        self.rows = int(world_height / cell_size) + 1
        
        # We store (temperature_C, moisture_0_to_1) per cell
        self.grid = [[(21.0, 0.5) for _ in range(self.rows)] for _ in range(self.cols)]
        self.last_update = 0

    def update(self, current_time: float, world_map, season: Season, weather_system: WeatherSystem, buildings: list, global_climate: GlobalClimate):
        if current_time - self.last_update < 5.0:  # Update every 5 seconds
            return
        dt = current_time - self.last_update
        self.last_update = current_time

        season_offset = season.get_temperature_modifier()
        
        weather_temp_offsets = {
            'clear': 0.0,
            'rain': -5.0,
            'storm': -10.0,
            'drought': 10.0,
            'aurora': -15.0
        }
        weather_moist_offsets = {
            'clear': 0.0,
            'rain': 0.3,
            'storm': 0.5,
            'drought': -0.4,
            'aurora': 0.0
        }
        
        weather_name = weather_system.current_weather
        w_temp_off = weather_temp_offsets.get(weather_name, 0.0)
        w_moist_off = weather_moist_offsets.get(weather_name, 0.0)

        for col in range(self.cols):
            for row in range(self.rows):
                world_x = col * self.cell_size + self.cell_size / 2
                world_y = row * self.cell_size + self.cell_size / 2

                ambient_temp = 21.0
                base_moisture = 0.5
                
                if world_map:
                    biome = world_map.get_biome_at(world_x, world_y)
                    biome_base_temp = {
                        'desert': 35.0,
                        'tundra': -15.0,
                        'snow': -5.0,
                        'taiga': 5.0,
                        'jungle': 30.0,    # Alias for lush
                        'swamp': 25.0,
                        'forest': 18.0,
                        'plains': 20.0,
                        'mountains': 10.0
                    }.get(biome, 21.0)
                    
                    biome_base_moist = {
                        'desert': 0.05,
                        'tundra': 0.2,
                        'snow': 0.4,
                        'taiga': 0.5,
                        'jungle': 0.9,
                        'swamp': 0.95,
                        'forest': 0.6,
                        'plains': 0.4,
                        'mountains': 0.3
                    }.get(biome, 0.5)
                    
                    ambient_temp = biome_base_temp + season_offset + w_temp_off + global_climate.global_temp_offset
                    base_moisture = max(0.0, min(1.0, biome_base_moist + w_moist_off + global_climate.global_moisture_offset))

                # Check if indoors (Insulation pulls temp towards 21C)
                nearby_buildings = sum(1 for b in buildings if math.sqrt((b.x - world_x)**2 + (b.y - world_y)**2) < 150)
                insulation_factor = min(1.0, nearby_buildings * 0.3)
                if insulation_factor > 0:
                    ambient_temp = ambient_temp * (1.0 - insulation_factor) + (21.0 * insulation_factor)
                
                # Add heat sources
                heat_sources = sum(1 for b in buildings if getattr(b, 'building_type', '') in ['workshop', 'shrine'] and math.sqrt((b.x - world_x)**2 + (b.y - world_y)**2) < 100)
                ambient_temp += heat_sources * 10.0
                
                # Smooth transition of moisture and temp
                old_temp, old_moist = self.grid[col][row]
                
                # Temperature changes relatively fast (air), moisture takes time (ground)
                new_temp = old_temp + (ambient_temp - old_temp) * 0.1  # lerp
                new_moist = old_moist + (base_moisture - old_moist) * 0.02 # slow lerp
                
                self.grid[col][row] = (new_temp, new_moist)

    def get_temperature_at(self, x: float, y: float) -> float:
        col = max(0, min(self.cols - 1, int(x / self.cell_size)))
        row = max(0, min(self.rows - 1, int(y / self.cell_size)))
        return self.grid[col][row][0]
        
    def get_moisture_at(self, x: float, y: float) -> float:
        col = max(0, min(self.cols - 1, int(x / self.cell_size)))
        row = max(0, min(self.rows - 1, int(y / self.cell_size)))
        return self.grid[col][row][1]
