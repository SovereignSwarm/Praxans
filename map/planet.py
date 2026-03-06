from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from map.generation import _fractal_noise

@dataclass
class PlanetTile:
    grid_x: int
    grid_y: int
    elevation: float
    temperature: float
    moisture: float
    biome: str
    is_land: bool

class PlanetGrid:
    """
    A massive abstract planetary map.
    This dictates global climate bands and continents.
    """
    def __init__(self, cols: int = 100, rows: int = 60, seed: int = 42):
        self.cols = cols
        self.rows = rows
        self.seed = seed
        self.tiles = {}
        
        self.sea_level = 0.2
        self._generate()
        
    def _generate(self):
        """Builds the planet surface."""
        for cy in range(self.rows):
            # Calculate latitude: 0.0 at equator, 1.0 at poles
            equator_y = self.rows / 2.0
            dist_from_equator = abs(cy - equator_y) / equator_y
            
            # Base temperature is highest at equator, lowest at poles
            base_temp = 1.0 - (dist_from_equator * 1.5) 
            
            for cx in range(self.cols):
                # Elevation noise for continents
                elevation = _fractal_noise(cx * 0.05, cy * 0.05, self.seed, octaves=4)
                # Compress elevation range slightly and lift
                elevation = (elevation + 1.0) / 2.0
                
                is_land = elevation > self.sea_level
                
                # Temperature jitter based on elevation
                lat_temp = base_temp - (elevation * 0.4 if is_land else 0.0)
                temp_noise = _fractal_noise(cx * 0.1, cy * 0.1, self.seed + 1) * 0.3
                final_temp = max(-1.0, min(1.0, lat_temp + temp_noise))
                
                # Moisture Noise
                moist_noise = _fractal_noise(cx * 0.08, cy * 0.08, self.seed + 2)
                moisture = (moist_noise + 1.0) / 2.0
                
                # Determine macro biome
                biome = self._determine_macro_biome(is_land, final_temp, moisture)
                
                self.tiles[(cx, cy)] = PlanetTile(
                    grid_x=cx,
                    grid_y=cy,
                    elevation=elevation,
                    temperature=final_temp,
                    moisture=moisture,
                    biome=biome,
                    is_land=is_land
                )
                
    def _determine_macro_biome(self, is_land: bool, temp: float, moisture: float) -> str:
        if not is_land:
            if temp < -0.6:
                return "ice_sheet" # Frozen ocean
            return "ocean"
            
        if temp < -0.4:
            return "tundra" if moisture > 0.3 else "snow"
        if temp < 0.0:
            return "taiga"
        if temp > 0.6:
            return "swamp" if moisture > 0.6 else "desert"
            
        # Temperate bands
        if moisture > 0.6:
            return "forest"
        if moisture < 0.3:
            return "desert"
        return "plains"
        
    def get_tile(self, x: int, y: int) -> PlanetTile | None:
        return self.tiles.get((x, y))
