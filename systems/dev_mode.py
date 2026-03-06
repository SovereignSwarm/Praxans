"""
DevMode — F12 Developer Tools overlay for rapid testing and debugging.

Provides:
  - Entity spawning (praxan, resource, building) at cursor
  - Force kill / heal selected pawn
  - Trigger specific storyteller incidents
  - Speed override
  - God mode toggle (no needs decay)
"""
from __future__ import annotations

import time


class DevMode:
    """Developer tools for rapid testing and debugging."""

    def __init__(self):
        self.enabled = False
        self.god_mode = False
        self.speed_override = None  # None = use normal, otherwise a float multiplier
        self.last_action_log = []   # [(timestamp, action_text), ...]

    def toggle(self):
        """Toggle dev mode on/off."""
        self.enabled = not self.enabled
        self._log(f"Dev Mode {'ENABLED' if self.enabled else 'DISABLED'}")

    def toggle_god_mode(self):
        """Toggle god mode (no needs decay)."""
        self.god_mode = not self.god_mode
        self._log(f"God Mode {'ON' if self.god_mode else 'OFF'}")

    def set_speed(self, multiplier: float | None):
        """Set a speed override. None reverts to normal."""
        self.speed_override = multiplier
        if multiplier is not None:
            self._log(f"Speed set to {multiplier}x")
        else:
            self._log("Speed reverted to normal")

    def spawn_praxan(self, game_state: dict, world_x: float, world_y: float):
        """Spawn a new praxan at the given world coordinates."""
        if not self.enabled:
            return
        praxans = game_state.get('praxans')
        praxan_class = game_state.get('praxan_class')
        if praxans is None or praxan_class is None:
            return
        new_p = praxan_class(world_x, world_y, len(praxans) + 100)
        praxans.append(new_p)
        self._log(f"Spawned praxan #{new_p.id} at ({world_x:.0f}, {world_y:.0f})")

    def kill_selected(self, game_state: dict):
        """Force kill the currently selected pawn."""
        if not self.enabled:
            return
        selected = game_state.get('selected_entity')
        if selected and hasattr(selected, 'health'):
            selected.health = 0
            selected.alive = False
            self._log(f"Killed praxan #{getattr(selected, 'id', '?')}")

    def heal_selected(self, game_state: dict):
        """Fully heal the currently selected pawn."""
        if not self.enabled:
            return
        selected = game_state.get('selected_entity')
        if selected and hasattr(selected, 'health'):
            selected.health = 100
            selected.needs = {k: 100 for k in getattr(selected, 'needs', {})}
            selected.hediffs = []
            selected.diseased = False
            self._log(f"Healed praxan #{getattr(selected, 'id', '?')}")

    def trigger_incident(self, game_state: dict, incident_id: str):
        """Force-fire a specific storyteller incident."""
        if not self.enabled:
            return
        storyteller = game_state.get('storyteller')
        if storyteller:
            for inc in storyteller.incidents:
                if inc.id == incident_id:
                    inc.execute_fn(game_state)
                    self._log(f"Triggered incident: {incident_id}")
                    return
            self._log(f"Incident '{incident_id}' not found")

    def spawn_resource(self, game_state: dict, world_x: float, world_y: float, res_type: str = "food"):
        """Spawn a resource at the given world coordinates."""
        if not self.enabled:
            return
        resources = game_state.get('resources')
        resource_class = game_state.get('resource_class')
        if resources is None or resource_class is None:
            return
        new_r = resource_class(world_x, world_y, res_type)
        resources.append(new_r)
        self._log(f"Spawned {res_type} at ({world_x:.0f}, {world_y:.0f})")

    def _log(self, text: str):
        self.last_action_log.append((time.time(), text))
        # Keep only last 20 entries
        if len(self.last_action_log) > 20:
            self.last_action_log = self.last_action_log[-20:]
        print(f"[DevMode] {text}")

    def get_speed_multiplier(self, normal_speed: float) -> float:
        """Returns the effective speed multiplier."""
        if self.speed_override is not None:
            return self.speed_override
        return normal_speed
