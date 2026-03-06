from __future__ import annotations

from dataclasses import dataclass

import pygame


@dataclass(frozen=True)
class RunLayout:
    top_ribbon: pygame.Rect
    notes_rail: pygame.Rect
    inspect_drawer: pygame.Rect
    transport_bar: pygame.Rect
    minimap: pygame.Rect
    world_view: pygame.Rect
    modal: pygame.Rect
    overlay_chip: pygame.Rect
    pawn_roster: pygame.Rect
    bottom_spine: pygame.Rect


@dataclass(frozen=True)
class ShellLayout:
    hero: pygame.Rect
    nav_column: pygame.Rect
    detail_panel: pygame.Rect
    recent_runs: pygame.Rect
    footer: pygame.Rect


def compute_run_layout(width: int, height: int) -> RunLayout:
    compact = width < 1500
    ribbon_h = 84 if not compact else 76
    transport_h = 76 if not compact else 68
    notes_w = 336 if not compact else 280
    inspect_w = 360 if not compact else 320
    margin = 18 if not compact else 14
    world_left = margin + notes_w + margin
    world_top = margin + ribbon_h + 10
    world_right = width - inspect_w - margin
    world_bottom = height - transport_h - margin - 14
    minimap_w = min(320, max(250, width // 6))
    minimap_h = min(230, max(176, height // 5))
    minimap_rect = pygame.Rect(world_right - minimap_w, world_bottom - minimap_h, minimap_w, minimap_h)
    modal = pygame.Rect(max(28, width // 2 - min(1120, width - 80) // 2), max(24, height // 2 - min(700, height - 80) // 2), min(1120, width - 80), min(700, height - 80))
    return RunLayout(
        top_ribbon=pygame.Rect(margin, margin, width - margin * 2, ribbon_h),
        notes_rail=pygame.Rect(margin, world_top, notes_w, max(300, world_bottom - world_top)),
        inspect_drawer=pygame.Rect(width - inspect_w - margin, world_top, inspect_w, max(300, world_bottom - world_top)),
        transport_bar=pygame.Rect(max(28, width // 2 - min(980, width - 120) // 2), height - transport_h - margin, min(980, width - 120), transport_h),
        minimap=minimap_rect,
        world_view=pygame.Rect(world_left, world_top, max(240, world_right - world_left - margin), max(240, world_bottom - world_top)),
        modal=modal,
        overlay_chip=pygame.Rect(margin + 16, margin + 50, 154, 24),
        pawn_roster=pygame.Rect(world_left, margin, world_right - world_left - margin, 40),
        bottom_spine=pygame.Rect(world_left, world_bottom + 10, world_right - world_left - margin, transport_h),
    )


def compute_shell_layout(width: int, height: int) -> ShellLayout:
    margin = 32 if width >= 1500 else 22
    nav_w = min(320, max(260, width // 5))
    footer_h = 52
    hero_h = min(270, max(220, height // 3))
    recent_h = min(196, max(156, height // 5))
    detail_x = margin + nav_w + 18
    detail_w = width - detail_x - margin
    return ShellLayout(
        hero=pygame.Rect(margin, margin, width - margin * 2, hero_h),
        nav_column=pygame.Rect(margin, margin + hero_h + 18, nav_w, height - hero_h - recent_h - footer_h - margin * 2 - 36),
        detail_panel=pygame.Rect(detail_x, margin + hero_h + 18, detail_w, height - hero_h - recent_h - footer_h - margin * 2 - 36),
        recent_runs=pygame.Rect(margin, height - recent_h - footer_h - margin, width - margin * 2, recent_h),
        footer=pygame.Rect(margin, height - footer_h - margin, width - margin * 2, footer_h),
    )
