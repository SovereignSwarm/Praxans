from __future__ import annotations

import time
import random
from typing import Any, Callable

# Storyteller Phases
PHASE_BUILD_UP = "build_up"
PHASE_CLIMAX = "climax"
PHASE_RECOVERY = "recovery"

# Incident Categories
INCIDENT_GOOD = "good"
INCIDENT_NEUTRAL = "neutral"
INCIDENT_BAD = "bad"

class IncidentDef:
    def __init__(self, id: str, category: str, base_cost: float, execute_fn: Callable):
        self.id = id
        self.category = category
        self.base_cost = base_cost
        self.execute_fn = execute_fn

class Storyteller:
    """
    The RimWorld-style director that paces the game based on colony wealth.
    Manages phases (Build Up -> Climax -> Recovery) and spends Threat Points on incidents.
    """
    def __init__(self):
        self.current_phase = PHASE_BUILD_UP
        self.phase_start_time = time.time()
        
        # Pacing durations in seconds
        self.durations = {
            PHASE_BUILD_UP: 300.0,   # 5 mins of peace/minor incidents
            PHASE_CLIMAX: 180.0,     # 3 mins of intense threats
            PHASE_RECOVERY: 240.0    # 4 mins of no bad events
        }
        
        # Time tracking
        self.last_update_time = time.time()
        self.last_incident_time = 0.0
        self.min_time_between_incidents = 45.0
        
        # Wealth & Threat
        self.colony_wealth = 0.0
        self.threat_points = 0.0
        self.accumulated_points = 0.0
        
        # Registry
        self.incidents: list[IncidentDef] = []
        self._register_default_incidents()
        
        # History for UI
        self.recent_incidents = []

    def _register_default_incidents(self):
        """Register the built-in incidents. The execute functions are defined in praxans_game.py and injected later if needed, or we just emit them over an event bus."""
        # We will map these to actual game functions later
        pass

    def add_incident(self, id: str, category: str, base_cost: float, execute_fn: Callable):
        self.incidents.append(IncidentDef(id, category, base_cost, execute_fn))

    def calculate_wealth(self, praxans: list, buildings: list, resources: list) -> float:
        """Calculate the total wealth of the settlement."""
        wealth = 0.0
        
        # Base value per pawn
        wealth += len(praxans) * 800.0
        
        # Value of buildings (based on type/level)
        for b in buildings:
            base = 100.0
            if getattr(b, 'building_type', '') == 'house': base = 250.0
            elif getattr(b, 'building_type', '') == 'farm': base = 300.0
            elif getattr(b, 'building_type', '') == 'workshop': base = 500.0
            elif getattr(b, 'building_type', '') == 'shrine': base = 800.0
            wealth += base * getattr(b, 'level', 1)
            
            # Value of stored items
            stores = getattr(b, 'stored_resources', {})
            wealth += stores.get('food', 0) * 2.0
            wealth += stores.get('wood', 0) * 1.5
            wealth += stores.get('stone', 0) * 2.5
            
        # Value of items carried by pawns
        for p in praxans:
            inv = getattr(p, 'inventory', {})
            wealth += inv.get('food', 0) * 2.0
            wealth += inv.get('wood', 0) * 1.5
            wealth += inv.get('stone', 0) * 2.5
            
        return wealth

    def calculate_threat_points(self, wealth: float) -> float:
        """Convert wealth into a threat point budget for incidents."""
        # Base curve: 10 points + 1 point per 1000 wealth, curving down at high wealth
        points = 10.0 + (wealth / 1000.0)
        # Apply gentle diminishing returns
        if points > 100:
            points = 100 + (points - 100) * 0.5
        return points

    def update(self, current_time: float, game_state: dict):
        """Called periodically (e.g. every 1-5 seconds) to update pacing and trigger events."""
        dt = current_time - self.last_update_time
        self.last_update_time = current_time
        
        # 1. Update Wealth
        praxans = game_state.get('praxans', [])
        buildings = game_state.get('buildings', [])
        resources = game_state.get('resources', [])
        self.colony_wealth = self.calculate_wealth(praxans, buildings, resources)
        
        # 2. Update Threat Points
        self.threat_points = self.calculate_threat_points(self.colony_wealth)
        
        # 3. Phase Transitions
        phase_elapsed = current_time - self.phase_start_time
        if phase_elapsed >= self.durations[self.current_phase]:
            self._advance_phase(current_time)
            
        # Accumulate available points to 'spend' on incidents
        # Only accumulate aggressive points during Build Up and Climax
        if self.current_phase in [PHASE_BUILD_UP, PHASE_CLIMAX]:
             point_generation_rate = self.threat_points / self.durations[PHASE_CLIMAX] # Generate total budget over climax duration
             self.accumulated_points += point_generation_rate * dt
             
        # 4. Attempt Incident Generation
        time_since_last = current_time - self.last_incident_time
        if time_since_last >= self.min_time_between_incidents:
            self._try_fire_incident(current_time, game_state)

    def _advance_phase(self, current_time: float):
        if self.current_phase == PHASE_BUILD_UP:
            self.current_phase = PHASE_CLIMAX
            # Bonus points entering climax
            self.accumulated_points += self.threat_points * 0.5 
        elif self.current_phase == PHASE_CLIMAX:
            self.current_phase = PHASE_RECOVERY
            self.accumulated_points = 0.0 # Clear budget
        elif self.current_phase == PHASE_RECOVERY:
            self.current_phase = PHASE_BUILD_UP
            
        self.phase_start_time = current_time
        print(f"[Storyteller] Advanced to phase: {self.current_phase}")

    def _try_fire_incident(self, current_time: float, game_state: dict):
        if not self.incidents:
            return
            
        # Filter eligible incidents based on phase
        allowed_categories = [INCIDENT_NEUTRAL, INCIDENT_GOOD]
        if self.current_phase == PHASE_BUILD_UP:
            if random.random() < 0.3: allowed_categories.append(INCIDENT_BAD) # Rare bad events
        elif self.current_phase == PHASE_CLIMAX:
            allowed_categories.append(INCIDENT_BAD) # Frequent bad events
            
        candidates = [inc for inc in self.incidents if inc.category in allowed_categories]
        if not candidates:
            return
            
        # Weight by cost vs available points (for bad events) or pure random for good
        weighted_candidates = []
        for inc in candidates:
            if inc.category == INCIDENT_BAD:
                if inc.base_cost <= self.accumulated_points:
                    weighted_candidates.append(inc)
            else:
                weighted_candidates.append(inc)
                
        if not weighted_candidates:
            return
            
        # Select and fire
        selected = random.choice(weighted_candidates)
        
        # Deduct cost if bad
        if selected.category == INCIDENT_BAD:
            self.accumulated_points -= selected.base_cost
            
        self.last_incident_time = current_time
        self.recent_incidents.append((current_time, selected.id))
        
        print(f"[Storyteller] Firing incident: {selected.id} (Cost: {selected.base_cost})")
        selected.execute_fn(game_state)
