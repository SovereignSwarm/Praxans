"""
HistoryGraph — Time-series data recording and rendering.

Records population, wealth, and average mood samples over time,
then renders them as a line graph overlay using pygame draw calls.
"""
from __future__ import annotations

import time
from collections import deque

import pygame


# Maximum samples to keep (at ~30s intervals, 200 = ~100 minutes of play)
MAX_SAMPLES = 200


class HistoryTracker:
    """Records time-series samples of colony vital signs."""

    def __init__(self):
        self.samples: deque = deque(maxlen=MAX_SAMPLES)
        self.last_sample_time = 0.0
        self.sample_interval = 30.0  # seconds

    def update(self, current_time: float, praxans: list, buildings: list, storyteller=None):
        """Record a sample if enough time has elapsed."""
        if current_time - self.last_sample_time < self.sample_interval:
            return

        population = len(praxans)
        avg_mood = 0.0
        if population > 0:
            avg_mood = sum(getattr(p, 'happiness', 50) for p in praxans) / population

        wealth = 0.0
        if storyteller:
            wealth = getattr(storyteller, 'colony_wealth', 0.0)

        self.samples.append({
            'time': current_time,
            'population': population,
            'wealth': wealth,
            'avg_mood': avg_mood,
        })
        self.last_sample_time = current_time

    def get_samples(self) -> list:
        return list(self.samples)


class HistoryGraphRenderer:
    """Renders a line graph overlay of colony history."""

    # Graph colors
    COLOR_POP = (120, 220, 120)   # Green for population
    COLOR_WEALTH = (255, 215, 80) # Gold for wealth
    COLOR_MOOD = (120, 180, 255)  # Blue for mood
    COLOR_BG = (20, 20, 30, 200)  # Dark translucent background
    COLOR_GRID = (60, 60, 80)     # Grid lines
    COLOR_TEXT = (200, 200, 220)   # Label text

    def __init__(self):
        self.visible = False

    def toggle(self):
        self.visible = not self.visible

    def draw(self, surface: pygame.Surface, tracker: HistoryTracker, font: pygame.font.Font):
        """Draw the history graph overlay."""
        if not self.visible:
            return

        samples = tracker.get_samples()
        if len(samples) < 2:
            return

        sw, sh = surface.get_size()

        # Graph dimensions
        margin = 40
        graph_w = min(600, sw - 80)
        graph_h = min(300, sh - 200)
        graph_x = sw - graph_w - margin
        graph_y = margin + 40

        # Background
        bg_surface = pygame.Surface((graph_w + 20, graph_h + 60), pygame.SRCALPHA)
        bg_surface.fill(self.COLOR_BG)
        surface.blit(bg_surface, (graph_x - 10, graph_y - 30))

        # Title
        title = font.render("Colony History", True, self.COLOR_TEXT)
        surface.blit(title, (graph_x + graph_w // 2 - title.get_width() // 2, graph_y - 25))

        # Grid lines
        for i in range(5):
            y = graph_y + int(graph_h * i / 4)
            pygame.draw.line(surface, self.COLOR_GRID, (graph_x, y), (graph_x + graph_w, y), 1)

        # Extract series
        populations = [s['population'] for s in samples]
        wealths = [s['wealth'] for s in samples]
        moods = [s['avg_mood'] for s in samples]

        # Normalize each series to 0..1
        def normalize(values):
            mn, mx = min(values), max(values)
            rng = mx - mn if mx != mn else 1.0
            return [(v - mn) / rng for v in values]

        norm_pop = normalize(populations)
        norm_wealth = normalize(wealths)
        norm_mood = normalize(moods)

        n = len(samples)
        x_step = graph_w / max(1, n - 1)

        def series_points(norm_values):
            pts = []
            for i, v in enumerate(norm_values):
                px = graph_x + int(i * x_step)
                py = graph_y + graph_h - int(v * graph_h)
                pts.append((px, py))
            return pts

        # Draw lines
        pop_pts = series_points(norm_pop)
        wealth_pts = series_points(norm_wealth)
        mood_pts = series_points(norm_mood)

        if len(pop_pts) > 1:
            pygame.draw.lines(surface, self.COLOR_POP, False, pop_pts, 2)
        if len(wealth_pts) > 1:
            pygame.draw.lines(surface, self.COLOR_WEALTH, False, wealth_pts, 2)
        if len(mood_pts) > 1:
            pygame.draw.lines(surface, self.COLOR_MOOD, False, mood_pts, 2)

        # Legend
        legend_y = graph_y + graph_h + 8
        legend_items = [
            (self.COLOR_POP, f"Pop: {populations[-1]}"),
            (self.COLOR_WEALTH, f"Wealth: {int(wealths[-1])}"),
            (self.COLOR_MOOD, f"Mood: {moods[-1]:.0f}"),
        ]
        lx = graph_x
        for color, label in legend_items:
            pygame.draw.rect(surface, color, (lx, legend_y, 12, 12))
            text_surf = font.render(label, True, self.COLOR_TEXT)
            surface.blit(text_surf, (lx + 16, legend_y - 2))
            lx += text_surf.get_width() + 30
