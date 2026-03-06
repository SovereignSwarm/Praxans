from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pygame


@dataclass
class UIState:
    active_screen: str = "run"
    active_modal: str | None = None
    inspect_target: dict[str, Any] | None = None
    hover_target: dict[str, Any] | None = None
    selected_run: str | None = None
    compare_run: str | None = None
    camera_cue: str | None = None
    inspect_tab: str = "overview"
    inspect_scroll: int = 0
    archive_scroll: int = 0
    archive_filter_scenario: str = "all"
    archive_filter_end_state: str = "all"
    analytics_section: str = "population"
    map_overlay: str = "biome"
    camera_mode: str = "follow"
    shell_notice: str = ""
    selected_scenario_id: str | None = None
    show_quit_prompt: bool = False
    end_summary_open: bool = False


@dataclass(frozen=True)
class RegisteredRect:
    id: str
    rect: pygame.Rect
    action: str | None = None
    payload: Any = None
    layer: int = 0
    scrollable: bool = False


@dataclass
class UIRectRegistry:
    _entries: list[RegisteredRect] = field(default_factory=list)

    def reset(self) -> None:
        self._entries.clear()

    def register(
        self,
        rect_id: str,
        rect: pygame.Rect,
        *,
        action: str | None = None,
        payload: Any = None,
        layer: int = 0,
        scrollable: bool = False,
    ) -> None:
        self._entries.append(
            RegisteredRect(
                id=str(rect_id),
                rect=pygame.Rect(rect),
                action=action,
                payload=payload,
                layer=int(layer),
                scrollable=bool(scrollable),
            )
        )

    def hit_test(self, pos: tuple[int, int]) -> RegisteredRect | None:
        candidates = [entry for entry in self._entries if entry.rect.collidepoint(pos)]
        if not candidates:
            return None
        candidates.sort(key=lambda entry: entry.layer, reverse=True)
        return candidates[0]

    def contains_ui(self, pos: tuple[int, int]) -> bool:
        return self.hit_test(pos) is not None

    def scroll_target(self, pos: tuple[int, int]) -> RegisteredRect | None:
        candidates = [entry for entry in self._entries if entry.scrollable and entry.rect.collidepoint(pos)]
        if not candidates:
            return None
        candidates.sort(key=lambda entry: entry.layer, reverse=True)
        return candidates[0]


def handle_escape(ui_state: UIState, selection_manager=None) -> bool:
    if ui_state.active_modal:
        ui_state.active_modal = None
        return False
    if ui_state.end_summary_open:
        ui_state.end_summary_open = False
        return False
    if selection_manager is not None and getattr(selection_manager, "selected_entity", None) is not None:
        selection_manager.deselect()
        ui_state.inspect_target = None
        ui_state.inspect_tab = "overview"
        ui_state.inspect_scroll = 0
        return False
    if ui_state.show_quit_prompt:
        return True
    ui_state.show_quit_prompt = True
    return False


def _screen_distance(camera, pos: tuple[int, int], world_x: float, world_y: float) -> float:
    screen_x, screen_y = camera.world_to_screen(world_x, world_y)
    return math.hypot(pos[0] - screen_x, pos[1] - screen_y)


def pick_world_entity(
    screen_pos: tuple[int, int],
    camera,
    thronglets,
    buildings,
    resources,
    encounters,
    hazards,
    npcs,
    *,
    thronglet_radius: float,
    building_size: float,
    resource_radii: dict[str, float],
) -> tuple[Any | None, str | None]:
    candidates: list[tuple[int, float, Any, str]] = []

    for thronglet in thronglets:
        distance = _screen_distance(camera, screen_pos, thronglet.x, thronglet.y)
        threshold = max(14.0, float(thronglet_radius) + 6.0)
        if distance <= threshold:
            candidates.append((0, distance, thronglet, "thronglet"))

    for building in buildings:
        distance = _screen_distance(camera, screen_pos, building.x, building.y)
        threshold = max(18.0, float(building_size) + 10.0)
        if distance <= threshold:
            candidates.append((1, distance, building, "building"))

    for resource in resources:
        if getattr(resource, "collected", False):
            continue
        distance = _screen_distance(camera, screen_pos, resource.x, resource.y)
        threshold = max(12.0, float(resource_radii.get(getattr(resource, "resource_type", "wood"), 10.0)) + 4.0)
        if distance <= threshold:
            candidates.append((2, distance, resource, "resource"))

    for encounter in encounters:
        if not getattr(encounter, "discovered", False):
            continue
        distance = _screen_distance(camera, screen_pos, encounter.x, encounter.y)
        if distance <= 24.0:
            candidates.append((3, distance, encounter, "encounter"))

    for hazard in hazards:
        if not getattr(hazard, "active", False):
            continue
        distance = _screen_distance(camera, screen_pos, hazard.x, hazard.y)
        threshold = max(20.0, min(72.0, float(getattr(hazard, "radius", 36.0)) * 0.2))
        if distance <= threshold:
            candidates.append((4, distance, hazard, "hazard"))

    for npc in npcs:
        if not getattr(npc, "visible", False):
            continue
        distance = _screen_distance(camera, screen_pos, npc.x, npc.y)
        if distance <= 22.0:
            candidates.append((5, distance, npc, "npc"))

    if not candidates:
        return None, None
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, _, entity, entity_type = candidates[0]
    return entity, entity_type
