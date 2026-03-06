import time
import math
import logging

logger = logging.getLogger("TickManager")

class TickManager:
    """
    RimWorld-style Staggered Ticking Engine.
    Distributes entity updates across time to prevent performance spikes as scale increases.
    
    Normal Tick: Every frame (smooth movement)
    Rare Tick: Once every 250 ticks (~4.1 seconds at 60 UPS)
    Long Tick: Once every 2000 ticks (~33.3 seconds at 60 UPS)
    """
    RARE_TICK_INTERVAL = 250
    LONG_TICK_INTERVAL = 2000
    SECONDS_PER_TICK = 1.0 / 60.0  # 60 logic ticks per in-game second

    def __init__(self):
        self.ticks = 0
        self.accumulator = 0.0
        
        # We don't bucket normal ticks; they happen every frame with delta_time
        self.normal_entities = set()
        
        # Buckets for staggered ticking
        self.rare_buckets = [set() for _ in range(self.RARE_TICK_INTERVAL)]
        self.long_buckets = [set() for _ in range(self.LONG_TICK_INTERVAL)]
        
        # Tracking to easily remove entities
        self._rare_assignment = {}
        self._long_assignment = {}
        self._next_bucket = 0

    def register(self, entity, needs_normal=True, needs_rare=False, needs_long=False):
        """Register an entity for ticking."""
        if needs_normal:
            self.normal_entities.add(entity)
            
        if needs_rare and entity not in self._rare_assignment:
            bucket_idx = self._next_bucket % self.RARE_TICK_INTERVAL
            self.rare_buckets[bucket_idx].add(entity)
            self._rare_assignment[entity] = bucket_idx
            self._next_bucket += 1
            
        if needs_long and entity not in self._long_assignment:
            bucket_idx = self._next_bucket % self.LONG_TICK_INTERVAL
            self.long_buckets[bucket_idx].add(entity)
            self._long_assignment[entity] = bucket_idx
            self._next_bucket += 1

    def deregister(self, entity):
        """Remove an entity from all tick pools."""
        self.normal_entities.discard(entity)
        
        if entity in self._rare_assignment:
            bucket_idx = self._rare_assignment.pop(entity)
            self.rare_buckets[bucket_idx].discard(entity)
            
        if entity in self._long_assignment:
            bucket_idx = self._long_assignment.pop(entity)
            self.long_buckets[bucket_idx].discard(entity)

    def sync_entities(self, praxans, buildings):
        """Diff incoming lists against registered entities and update pools."""
        current_praxans = set(praxans)
        current_buildings = set(buildings)
        
        # Remove dead praxans
        to_remove = []
        for p in self.normal_entities:
            # We assume normal entities are praxans for now
            if p not in current_praxans:
                to_remove.append(p)
        for dead in to_remove:
            self.deregister(dead)
            
        # Remove destroyed buildings (rarely happens but safe)
        to_remove_b = []
        for b in self._rare_assignment.keys():
            if b not in current_buildings and b not in current_praxans:
                to_remove_b.append(b)
        for dead_b in to_remove_b:
            self.deregister(dead_b)
            
        # Add new praxans
        for p in praxans:
            if hasattr(p, 'tick_rare') and p not in self.normal_entities:
                self.register(p, needs_normal=True, needs_rare=True, needs_long=True)
                
        # Add new buildings
        for b in buildings:
            if hasattr(b, 'tick_rare') and getattr(b, 'building_type', None) == 'farm' and b not in self._rare_assignment:
                self.register(b, needs_normal=False, needs_rare=True, needs_long=False)

    def tick(self, delta_time, game_state=None):
        """
        Advance logical time and run update buckets.
        game_state is an optional dict holding global context to pass to update methods.
        """
        # 1. Normal Tick (Every frame, uses precise delta_time)
        # Needed for smooth movement/rendering
        for entity in self.normal_entities:
            if hasattr(entity, 'tick_normal'):
                entity.tick_normal(delta_time, game_state)

        # Accumulate time for logical ticks
        self.accumulator += delta_time
        
        # 2. Process Logical Ticks (Fixed rate, staggering)
        while self.accumulator >= self.SECONDS_PER_TICK:
            self.accumulator -= self.SECONDS_PER_TICK
            self.ticks += 1
            
            # Fire Rare Tick Bucket
            rare_idx = self.ticks % self.RARE_TICK_INTERVAL
            for entity in self.rare_buckets[rare_idx]:
                if hasattr(entity, 'tick_rare'):
                    # Pass the total time passed between rare ticks
                    entity.tick_rare(self.RARE_TICK_INTERVAL * self.SECONDS_PER_TICK, game_state)
                    
            # Fire Long Tick Bucket
            long_idx = self.ticks % self.LONG_TICK_INTERVAL
            for entity in self.long_buckets[long_idx]:
                if hasattr(entity, 'tick_long'):
                    # Pass the total time passed between long ticks
                    entity.tick_long(self.LONG_TICK_INTERVAL * self.SECONDS_PER_TICK, game_state)
