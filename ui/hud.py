from __future__ import annotations

import pygame

from ui.models import FieldNote, RunHudModel
from ui.theme import UITheme, draw_badge, draw_button, draw_panel, wrap_text


_NOTE_COLOR_MAP = {
    "strategy": "note_strategy",
    "crisis": "note_crisis",
    "birth": "note_birth",
    "faction": "note_faction",
    "migration": "note_faction",
    "discovery": "note_discovery",
    "scenario": "note_strategy",
    "extinction": "note_crisis",
}

_OVERLAYS = ("districts", "factions", "hazards", "migration", "fog", "bookmarks")


def next_overlay(current_overlay: str) -> str:
    try:
        index = _OVERLAYS.index(current_overlay)
    except ValueError:
        return _OVERLAYS[0]
    return _OVERLAYS[(index + 1) % len(_OVERLAYS)]


def _note_color(theme: UITheme, category: str) -> tuple[int, int, int]:
    return getattr(theme.palette, _NOTE_COLOR_MAP.get(category, "note_strategy"))


def _draw_top_ribbon(surface: pygame.Surface, theme: UITheme, layout, registry, model: RunHudModel) -> None:
    draw_panel(surface, layout.top_ribbon, theme, fill=(20, 25, 27), alpha=236, radius=theme.radius_large)
    title = theme.fonts.heading.render(model.scenario_name.upper(), True, theme.palette.parchment)
    surface.blit(title, (layout.top_ribbon.x + 18, layout.top_ribbon.y + 14))
    subtitle = theme.fonts.caption.render(
        f"{model.phase_label}  |  {model.doctrine_label}  |  Score {model.observer_score}",
        True,
        theme.palette.parchment_soft,
    )
    surface.blit(subtitle, (layout.top_ribbon.x + 18, layout.top_ribbon.y + 42))
    chip_x = layout.top_ribbon.right - 94
    labels = [
        (model.crisis_label, theme.palette.copper),
        (model.follow_label, theme.palette.moss),
        (model.speed_label, theme.palette.ochre),
        (model.llm_status, theme.palette.frost),
    ]
    for label, color in labels:
        chip_w = max(88, theme.fonts.caption.size(label)[0] + 22)
        rect = pygame.Rect(chip_x - chip_w, layout.top_ribbon.y + 18, chip_w, 24)
        draw_badge(surface, theme, rect, label, fill=color, text_color=theme.palette.ink)
        chip_x -= chip_w + 10
    overlay_rect = pygame.Rect(layout.top_ribbon.x + 18, layout.top_ribbon.bottom - 30, 160, 20)
    registry.register("cycle_overlay", overlay_rect, action="cycle_overlay", layer=6)
    overlay_text = theme.fonts.caption.render(f"Map Overlay  {model.overlay_label}", True, theme.palette.frost)
    surface.blit(overlay_text, overlay_rect.topleft)
    if model.cue_label:
        cue_text = theme.fonts.caption.render(f"Camera cue  {model.cue_label[:36]}", True, theme.palette.warning)
        surface.blit(cue_text, (overlay_rect.right + 20, overlay_rect.y))


def _draw_transport_bar(surface: pygame.Surface, theme: UITheme, layout, registry, ui_state, current_speed_index: int) -> None:
    draw_panel(surface, layout.transport_bar, theme, fill=(22, 27, 29), alpha=236, radius=theme.radius_large)
    buttons = [
        ("toggle_follow", "Follow", "F", ui_state.camera_mode == "follow", theme.palette.moss),
        ("speed_1", "1x", "1", current_speed_index == 0, theme.palette.ochre),
        ("speed_2", "2x", "2", current_speed_index == 1, theme.palette.ochre),
        ("speed_5", "5x", "5", current_speed_index == 2, theme.palette.ochre),
        ("toggle_modal_research", "Research", "R", ui_state.active_modal == "research", theme.palette.frost),
        ("toggle_modal_evolution", "Evolution", "S", ui_state.active_modal == "evolution", theme.palette.ochre),
        ("toggle_modal_analytics", "Analytics", "T", ui_state.active_modal == "analytics", theme.palette.note_faction),
        ("toggle_modal_archive", "Archive", "A", ui_state.active_modal == "archive", theme.palette.note_discovery),
        ("focus_latest_event", "Focus", "Space", ui_state.camera_mode == "event", theme.palette.copper),
    ]
    button_w = max(88, (layout.transport_bar.w - 28 - (len(buttons) - 1) * 10) // len(buttons))
    x = layout.transport_bar.x + 14
    y = layout.transport_bar.y + 14
    for action, label, hotkey, active, accent in buttons:
        rect = pygame.Rect(x, y, button_w, 42)
        registry.register(action, rect, action=action, layer=6)
        draw_button(surface, rect, theme, label, hotkey=hotkey, active=active, accent=accent, subtle=True)
        x += button_w + 10


def _draw_notes(surface: pygame.Surface, theme: UITheme, layout, registry, field_notes: list[FieldNote]) -> None:
    draw_panel(surface, layout.notes_rail, theme, fill=(21, 26, 28), alpha=228, radius=theme.radius_large)
    registry.register("notes_rail", layout.notes_rail, layer=5, scrollable=True)
    title = theme.fonts.heading.render("Field Notes", True, theme.palette.parchment)
    surface.blit(title, (layout.notes_rail.x + 18, layout.notes_rail.y + 14))
    hint = theme.fonts.caption.render("Curated major moments from the living colony", True, theme.palette.muted_text)
    surface.blit(hint, (layout.notes_rail.x + 18, layout.notes_rail.y + 42))
    y = layout.notes_rail.y + 74
    for note in field_notes:
        card_h = 84
        rect = pygame.Rect(layout.notes_rail.x + 12, y, layout.notes_rail.w - 24, card_h)
        draw_panel(surface, rect, theme, fill=(29, 36, 38), alpha=236)
        accent_color = _note_color(theme, note.category)
        pygame.draw.rect(surface, accent_color, (rect.x + 8, rect.y + 10, 6, rect.h - 20), border_radius=3)
        surface.blit(theme.fonts.label.render(note.title, True, accent_color), (rect.x + 24, rect.y + 12))
        age_text = theme.fonts.caption.render(f"{int(note.age_seconds)}s ago", True, theme.palette.muted_text)
        surface.blit(age_text, (rect.right - age_text.get_width() - 12, rect.y + 14))
        line_y = rect.y + 40
        for wrapped in wrap_text(theme.fonts.caption, note.body, rect.w - 44)[:2]:
            surface.blit(theme.fonts.caption.render(wrapped, True, theme.palette.bright_text), (rect.x + 24, line_y))
            line_y += 18
        y += card_h + 10
        if y > layout.notes_rail.bottom - 90:
            break


def _faction_centroid(faction, thronglets_by_id: dict[int, object]) -> tuple[float, float] | None:
    members = [thronglets_by_id.get(int(member_id)) for member_id in getattr(faction, "member_ids", [])]
    members = [member for member in members if member is not None]
    if not members:
        return None
    return (
        sum(member.x for member in members) / len(members),
        sum(member.y for member in members) / len(members),
    )


def _draw_minimap(surface: pygame.Surface, theme: UITheme, layout, registry, ui_state, context: dict) -> None:
    rect = layout.minimap
    draw_panel(surface, rect, theme, fill=(17, 21, 23), alpha=238, radius=theme.radius_large)
    registry.register("minimap_jump", rect, action="minimap_jump", layer=6)
    title = theme.fonts.label.render(f"Observer Map  |  {ui_state.map_overlay.title()}", True, theme.palette.parchment)
    surface.blit(title, (rect.x + 14, rect.y + 10))
    legend_rect = pygame.Rect(rect.x + 14, rect.y + rect.h - 28, rect.w - 28, 18)
    registry.register("cycle_overlay", legend_rect, action="cycle_overlay", layer=7)
    surface.blit(theme.fonts.caption.render("Click map to jump  |  Click legend to cycle overlay", True, theme.palette.muted_text), legend_rect.topleft)

    map_x = rect.x + 10
    map_y = rect.y + 34
    map_w = rect.w - 20
    map_h = rect.h - 66
    world_map = context.get("world_map")
    camera = context.get("camera")
    if world_map is None or camera is None or camera.world_width <= 0 or camera.world_height <= 0:
        return
    scale_x = map_w / camera.world_width
    scale_y = map_h / camera.world_height
    biome_colors = context.get("biome_colors", {})
    for chunk in getattr(world_map, "chunks", {}).values():
        mini_x = int(map_x + getattr(chunk, "world_x", 0.0) * scale_x)
        mini_y = int(map_y + getattr(chunk, "world_y", 0.0) * scale_y)
        mini_w = max(1, int(context.get("chunk_size", 1) * scale_x))
        mini_h = max(1, int(context.get("chunk_size", 1) * scale_y))
        center_tile = getattr(chunk, "tiles", {}).get((8, 8), "plains")
        pygame.draw.rect(surface, biome_colors.get(center_tile, theme.palette.slate_soft), (mini_x, mini_y, mini_w, mini_h))

    overlay = ui_state.map_overlay
    if overlay == "districts":
        city_planner = context.get("city_planner")
        zone_colors = {
            "residential": theme.palette.parchment_soft,
            "agricultural": theme.palette.moss,
            "industrial": theme.palette.copper,
            "spiritual": theme.palette.frost,
        }
        for zone_pos, zone_type in getattr(city_planner, "zones", {}).items():
            if not isinstance(zone_pos, tuple) or len(zone_pos) != 2:
                continue
            zx = map_x + int(zone_pos[0] * context.get("tile_size", 1) * scale_x)
            zy = map_y + int(zone_pos[1] * context.get("tile_size", 1) * scale_y)
            pygame.draw.rect(surface, zone_colors.get(str(zone_type), theme.palette.ochre), (zx, zy, 4, 4))
    elif overlay == "factions":
        faction_manager = context.get("faction_manager")
        thronglets_by_id = {int(getattr(thronglet, "id", 0)): thronglet for thronglet in context.get("thronglets", [])}
        colors = [theme.palette.note_faction, theme.palette.note_strategy, theme.palette.ochre, theme.palette.moss]
        for index, faction in enumerate(getattr(faction_manager, "factions", {}).values()):
            centroid = _faction_centroid(faction, thronglets_by_id)
            if centroid is None:
                continue
            fx = int(map_x + centroid[0] * scale_x)
            fy = int(map_y + centroid[1] * scale_y)
            pygame.draw.circle(surface, colors[index % len(colors)], (fx, fy), 5)
    elif overlay == "hazards":
        for hazard in getattr(world_map, "hazards", []):
            hx = int(map_x + getattr(hazard, "x", 0.0) * scale_x)
            hy = int(map_y + getattr(hazard, "y", 0.0) * scale_y)
            radius = max(3, int(float(getattr(hazard, "radius", 20.0)) * max(scale_x, scale_y)))
            pygame.draw.circle(surface, theme.palette.danger, (hx, hy), radius, 1)
    elif overlay == "migration":
        faction_manager = context.get("faction_manager")
        thronglets_by_id = {int(getattr(thronglet, "id", 0)): thronglet for thronglet in context.get("thronglets", [])}
        for faction in getattr(faction_manager, "factions", {}).values():
            centroid = _faction_centroid(faction, thronglets_by_id)
            target = getattr(faction, "migration_target", None)
            if centroid is None or not isinstance(target, (tuple, list)) or len(target) != 2:
                continue
            start = (int(map_x + centroid[0] * scale_x), int(map_y + centroid[1] * scale_y))
            end = (int(map_x + target[0] * scale_x), int(map_y + target[1] * scale_y))
            pygame.draw.line(surface, theme.palette.ochre, start, end, 2)
            pygame.draw.circle(surface, theme.palette.ochre, end, 3)
    elif overlay == "fog":
        fog_of_war = context.get("fog_of_war")
        for tile_pos, visibility in getattr(fog_of_war, "fog_grid", {}).items():
            if not isinstance(tile_pos, tuple) or len(tile_pos) != 2:
                continue
            alpha = max(0, 180 - int(visibility))
            overlay_surface = pygame.Surface((3, 3), pygame.SRCALPHA)
            overlay_surface.fill((0, 0, 0, alpha))
            surface.blit(
                overlay_surface,
                (map_x + int(tile_pos[0] * context.get("tile_size", 1) * scale_x), map_y + int(tile_pos[1] * context.get("tile_size", 1) * scale_y)),
            )
    elif overlay == "bookmarks":
        for bookmark in context.get("camera_bookmarks", []):
            bx = int(map_x + float(bookmark.get("x", 0.0)) * scale_x)
            by = int(map_y + float(bookmark.get("y", 0.0)) * scale_y)
            pygame.draw.circle(surface, theme.palette.frost, (bx, by), 4, 1)

    for thronglet in context.get("thronglets", []):
        mini_x = int(map_x + thronglet.x * scale_x)
        mini_y = int(map_y + thronglet.y * scale_y)
        pygame.draw.circle(surface, theme.palette.parchment, (mini_x, mini_y), 2)
    for building in context.get("buildings", []):
        mini_x = int(map_x + building.x * scale_x)
        mini_y = int(map_y + building.y * scale_y)
        pygame.draw.rect(surface, theme.palette.ochre, (mini_x - 1, mini_y - 1, 3, 3))
    viewport = pygame.Rect(
        int(map_x + camera.x * scale_x),
        int(map_y + camera.y * scale_y),
        max(2, int(context.get("window_size", (1, 1))[0] * scale_x / max(0.01, camera.zoom))),
        max(2, int(context.get("window_size", (1, 1))[1] * scale_y / max(0.01, camera.zoom))),
    )
    pygame.draw.rect(surface, theme.palette.parchment, viewport, 2)


def draw_run_hud(
    surface: pygame.Surface,
    theme: UITheme,
    layout,
    registry,
    hud_model: RunHudModel,
    field_notes: list[FieldNote],
    ui_state,
    current_speed_index: int,
    minimap_context: dict,
) -> None:
    _draw_top_ribbon(surface, theme, layout, registry, hud_model)
    _draw_notes(surface, theme, layout, registry, field_notes)
    _draw_transport_bar(surface, theme, layout, registry, ui_state, current_speed_index)
    _draw_minimap(surface, theme, layout, registry, ui_state, minimap_context)
