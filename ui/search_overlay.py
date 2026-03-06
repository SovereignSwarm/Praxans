"""
SearchOverlay — Map-wide search and highlight for pawns, buildings, and resources.

Provides a text-based search overlay that highlights matching entities on the map
with glowing outlines and auto-pans the camera to the first result.
"""
from __future__ import annotations

import pygame
import math


class SearchOverlay:
    """Search and highlight entities across the game world."""

    COLOR_BG = (20, 20, 30, 220)
    COLOR_INPUT_BG = (40, 40, 55)
    COLOR_INPUT_BORDER = (100, 140, 255)
    COLOR_TEXT = (220, 220, 240)
    COLOR_HIGHLIGHT = (255, 200, 60)
    COLOR_RESULT = (180, 220, 255)

    def __init__(self):
        self.active = False
        self.query = ""
        self.results: list[dict] = []  # [{"entity": obj, "type": str, "label": str, "x": float, "y": float}]
        self.selected_index = 0

    def toggle(self):
        self.active = not self.active
        if self.active:
            self.query = ""
            self.results.clear()
            self.selected_index = 0

    def handle_key(self, event: pygame.event.Event, game_state: dict, camera=None):
        """Handle keyboard input while search is active."""
        if not self.active:
            return

        if event.key == pygame.K_ESCAPE:
            self.active = False
            return

        if event.key == pygame.K_RETURN:
            # Jump to selected result
            if self.results and camera:
                r = self.results[self.selected_index % len(self.results)]
                camera.target_x = r["x"] - 960 / max(0.1, camera.target_zoom)
                camera.target_y = r["y"] - 540 / max(0.1, camera.target_zoom)
            return

        if event.key == pygame.K_DOWN:
            if self.results:
                self.selected_index = (self.selected_index + 1) % len(self.results)
            return

        if event.key == pygame.K_UP:
            if self.results:
                self.selected_index = (self.selected_index - 1) % len(self.results)
            return

        if event.key == pygame.K_BACKSPACE:
            self.query = self.query[:-1]
        elif event.unicode and event.unicode.isprintable():
            self.query += event.unicode

        # Re-search
        self._search(game_state)

    def _search(self, game_state: dict):
        """Search for entities matching the query."""
        self.results.clear()
        self.selected_index = 0

        if not self.query.strip():
            return

        q = self.query.lower().strip()

        # Search praxans
        for p in game_state.get('praxans', []):
            label = f"Praxan #{getattr(p, 'id', '?')}"
            role = getattr(p, 'role', '')
            searchable = f"{label} {role}".lower()
            if q in searchable:
                self.results.append({
                    "entity": p, "type": "praxan", "label": label,
                    "x": getattr(p, 'x', 0), "y": getattr(p, 'y', 0),
                })

        # Search buildings
        for b in game_state.get('buildings', []):
            btype = getattr(b, 'building_type', 'building')
            label = f"{btype.title()}"
            if q in btype.lower() or q in label.lower():
                self.results.append({
                    "entity": b, "type": "building", "label": label,
                    "x": getattr(b, 'x', 0), "y": getattr(b, 'y', 0),
                })

        # Search resources
        for r in game_state.get('resources', []):
            if getattr(r, 'collected', False):
                continue
            rtype = getattr(r, 'resource_type', 'resource')
            if q in rtype.lower():
                self.results.append({
                    "entity": r, "type": "resource", "label": rtype.title(),
                    "x": getattr(r, 'x', 0), "y": getattr(r, 'y', 0),
                })

        # Cap results
        self.results = self.results[:50]

    def draw(self, surface: pygame.Surface, font: pygame.font.Font, camera=None):
        """Draw the search overlay."""
        if not self.active:
            return

        sw, sh = surface.get_size()

        # Search bar at top center
        bar_w = min(400, sw - 40)
        bar_h = 36
        bar_x = (sw - bar_w) // 2
        bar_y = 12

        # Background
        bg = pygame.Surface((bar_w + 20, bar_h + 10 + len(self.results[:8]) * 24 + 10), pygame.SRCALPHA)
        bg.fill(self.COLOR_BG)
        surface.blit(bg, (bar_x - 10, bar_y - 5))

        # Input field
        pygame.draw.rect(surface, self.COLOR_INPUT_BG, (bar_x, bar_y, bar_w, bar_h))
        pygame.draw.rect(surface, self.COLOR_INPUT_BORDER, (bar_x, bar_y, bar_w, bar_h), 2)

        # Search icon + text
        prompt = f"🔍 {self.query}_" if self.query else "🔍 Search praxans, buildings, resources..."
        text_surf = font.render(prompt, True, self.COLOR_TEXT)
        surface.blit(text_surf, (bar_x + 8, bar_y + 8))

        # Results dropdown
        result_y = bar_y + bar_h + 6
        for i, r in enumerate(self.results[:8]):
            color = self.COLOR_HIGHLIGHT if i == self.selected_index else self.COLOR_RESULT
            prefix = "►" if i == self.selected_index else " "
            line = f"{prefix} [{r['type'][:3].upper()}] {r['label']} ({int(r['x'])}, {int(r['y'])})"
            text = font.render(line, True, color)
            surface.blit(text, (bar_x + 4, result_y))
            result_y += 22

        if len(self.results) > 8:
            more = font.render(f"  ... and {len(self.results) - 8} more", True, (140, 140, 160))
            surface.blit(more, (bar_x + 4, result_y))

    def draw_world_highlights(self, surface: pygame.Surface, camera):
        """Draw highlight rings around matching entities in world space."""
        if not self.active or not self.results:
            return

        current_time = pygame.time.get_ticks() / 1000.0

        for i, r in enumerate(self.results[:20]):
            sx, sy = camera.world_to_screen(r["x"], r["y"])

            # Pulsing ring
            pulse = 0.5 + 0.5 * math.sin(current_time * 4 + i * 0.5)
            radius = int(12 + pulse * 6)
            alpha = int(150 + pulse * 105)

            color = (255, 200, 60) if i == self.selected_index else (120, 180, 255)

            # Draw circle with anti-aliasing
            pygame.draw.circle(surface, color, (int(sx), int(sy)), radius, 2)
            if i == self.selected_index:
                pygame.draw.circle(surface, (255, 255, 200), (int(sx), int(sy)), radius + 3, 1)
