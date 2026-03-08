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
    "trade": "note_trade",
    "diplomacy": "note_diplomacy",
    "cultural_shift": "note_cultural",
    "disaster": "note_disaster",
    "doctrine_change": "note_faction",
    "building": "note_strategy",
    "milestone": "note_discovery",
    "death": "note_crisis",
    "schism": "note_faction",
    "order": "note_discovery",
}

_ARCHITECT_MENU_ITEMS = [
    ("Orders", "architect_sub:orders"),
    ("Zone", "architect_sub:zone"),
    ("Structure", "architect_sub:structure"),
    ("Production", "architect_sub:production"),
]

_OVERLAYS = ("biome", "elevation", "water", "claims", "hazards", "routes", "fog", "bookmarks", "districts", "migration")


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
    # Build subtitle with environment context when available
    _subtitle_parts = [model.phase_label, model.doctrine_label, f"Score {model.observer_score}"]
    if model.season_label:
        _subtitle_parts.append(model.season_label)
    if model.climate_epoch:
        _subtitle_parts.append(model.climate_epoch)
    subtitle = theme.fonts.caption.render(
        "  |  ".join(_subtitle_parts),
        True,
        theme.palette.parchment_soft,
    )
    surface.blit(subtitle, (layout.top_ribbon.x + 18, layout.top_ribbon.y + 42))
    chip_x = layout.top_ribbon.right - 94
    # Build chip labels — include weather and ecology when available
    labels = [
        (model.crisis_label, theme.palette.copper),
        (model.follow_label, theme.palette.moss),
        (model.speed_label, theme.palette.ochre),
        (model.llm_status, theme.palette.frost),
    ]
    if model.weather_label and model.weather_label.lower() != "clear":
        labels.insert(0, (model.weather_label, theme.palette.note_disaster))
    if model.ecology_label and ("Barren" in model.ecology_label or "Degraded" in model.ecology_label):
        labels.insert(0, (model.ecology_label, theme.palette.note_crisis))
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


def _draw_pawn_roster(surface: pygame.Surface, theme: UITheme, layout, registry, praxans: list[Any]) -> None:
    if not praxans:
        return
    x = layout.pawn_roster.x
    y = layout.pawn_roster.y
    badge_w = 120
    badge_h = 46  # Taller to fit mood bar

    for praxan in praxans[:10]:
        rect = pygame.Rect(x, y, badge_w, badge_h)
        registry.register(f"jump_to_pawn:{praxan.id}", rect, action="jump_to_pawn", payload=praxan.id, layer=6)

        # Determine fill based on health
        health = float(getattr(praxan, "health", 100))
        fill = theme.palette.panel_fill_alt
        if health < 30:
            fill = theme.palette.danger
        elif health < 60:
            fill = (120, 90, 30)  # Dark amber

        draw_panel(surface, rect, theme, fill=fill, alpha=240, radius=theme.radius_small)

        # Border color based on mental state
        mental = getattr(praxan, "mental_state", None)
        if mental:
            border_color = (220, 50, 50)  # Red for breaking
        elif float(getattr(praxan, "happiness", 50)) < 25:
            border_color = (200, 180, 50)  # Yellow for stressed
        else:
            border_color = theme.palette.panel_border
        pygame.draw.rect(surface, border_color, rect, 2, border_radius=theme.radius_small)

        # Pawn label
        label = f"P#{praxan.id}"
        role = getattr(praxan, "role", None)
        if role:
            label += f" {role[0].upper()}"
        text_surf = theme.fonts.caption.render(label, True, theme.palette.bright_text)
        surface.blit(text_surf, (rect.x + 6, rect.y + 4))

        # Hediff indicator
        hediffs = list(getattr(praxan, "hediffs", []))
        if hediffs:
            icon_surf = theme.fonts.caption.render("⚕", True, (220, 100, 80))
            surface.blit(icon_surf, (rect.right - icon_surf.get_width() - 6, rect.y + 4))

        # Downed indicator
        if getattr(praxan, "downed", False):
            down_surf = theme.fonts.caption.render("▼", True, (220, 50, 50))
            surface.blit(down_surf, (rect.right - down_surf.get_width() - 6, rect.y + 4))

        # Mood bar (tiny horizontal bar at bottom of badge)
        bar_y = rect.y + badge_h - 12
        bar_x = rect.x + 6
        bar_w = badge_w - 12
        bar_h = 6
        bg_bar = pygame.Rect(bar_x, bar_y, bar_w, bar_h)
        pygame.draw.rect(surface, (30, 35, 37), bg_bar, border_radius=2)
        happiness = float(getattr(praxan, "happiness", 50))
        ratio = max(0.0, min(1.0, happiness / 100.0))
        fill_w = int(bar_w * ratio)
        if fill_w > 0:
            if ratio > 0.6:
                bar_color = (80, 180, 90)
            elif ratio > 0.3:
                bar_color = (200, 180, 60)
            else:
                bar_color = (200, 70, 60)
            pygame.draw.rect(surface, bar_color, pygame.Rect(bar_x, bar_y, fill_w, bar_h), border_radius=2)

        x += badge_w + 6
        if x + badge_w > surface.get_width() - 20:
            break


def _draw_bottom_spine(surface: pygame.Surface, theme: UITheme, layout, registry, ui_state) -> None:
    draw_panel(surface, layout.bottom_spine, theme, fill=(22, 27, 29), alpha=236, radius=theme.radius_large)
    buttons = [
        ("architect", "Architect", "B"),
        ("work", "Work", "W"),
        ("schedule", "Schedule", "H"),
        ("research", "Research", "R"),
    ]
    button_w = 140
    button_h = 42
    x = layout.bottom_spine.x + 14
    y = layout.bottom_spine.y + 14
    for action, label, hotkey in buttons:
        rect = pygame.Rect(x, y, button_w, button_h)
        registry.register(f"spine_{action}", rect, action=action, layer=6)
        active = (action == "architect" and ui_state.architect_mode is not None)
        draw_button(surface, rect, theme, label, hotkey=hotkey, active=active, accent=theme.palette.ochre if active else theme.palette.slate_soft)
        x += button_w + 10
    
    # Draw sub-menu if architect is active
    if ui_state.architect_mode:
        sub_x = layout.bottom_spine.x + 14
        sub_y = layout.bottom_spine.y - 48
        for label, action in _ARCHITECT_MENU_ITEMS:
            rect = pygame.Rect(sub_x, sub_y, 110, 36)
            registry.register(action, rect, action=action, layer=7)
            draw_button(surface, rect, theme, label, active=ui_state.architect_mode == action.split(":")[1], accent=theme.palette.moss, subtle=True)
            sub_x += 120


def _draw_context_menu(surface: pygame.Surface, theme: UITheme, registry, ui_state) -> None:
    if not ui_state.context_menu_pos or not ui_state.context_menu_items:
        return
    
    pos = ui_state.context_menu_pos
    items = ui_state.context_menu_items
    item_h = 32
    menu_w = 180
    menu_h = len(items) * item_h + 10
    
    rect = pygame.Rect(pos[0], pos[1], menu_w, menu_h)
    # Ensure menu stays on screen
    if rect.right > surface.get_width() - 20: rect.x -= rect.w
    if rect.bottom > surface.get_height() - 20: rect.y -= rect.h
    
    draw_panel(surface, rect, theme, fill=theme.palette.ink, alpha=250, radius=theme.radius_small)
    
    y = rect.y + 5
    for item in items:
        item_rect = pygame.Rect(rect.x + 5, y, menu_w - 10, item_h - 4)
        registry.register(f"context_item:{item['id']}", item_rect, action="context_action", payload=item, layer=100)
        
        # Hover effect if possible? Input router doesn't track hover for context items yet, but we can draw simple
        pygame.draw.rect(surface, theme.palette.slate, item_rect, border_radius=theme.radius_small)
        text = theme.fonts.caption.render(item["label"], True, theme.palette.bright_text)
        surface.blit(text, (item_rect.x + 8, item_rect.y + item_rect.h // 2 - text.get_height() // 2))
        y += item_h


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


def _faction_centroid(faction, praxans_by_id: dict[int, object]) -> tuple[float, float] | None:
    members = [praxans_by_id.get(int(member_id)) for member_id in getattr(faction, "member_ids", [])]
    members = [member for member in members if member is not None]
    if not members:
        return None
    return (
        sum(member.x for member in members) / len(members),
        sum(member.y for member in members) / len(members),
    )


def _region_overlay_lookup(world_map) -> dict[str, dict]:
    return {
        str(region.get("region_id")): region
        for region in getattr(world_map, "region_overlay", [])
        if isinstance(region, dict) and region.get("region_id") is not None
    }


def _draw_minimap(surface: pygame.Surface, theme: UITheme, layout, registry, ui_state, context: dict) -> None:
    rect = layout.minimap
def _draw_minimap_background(surface: pygame.Surface, theme: UITheme, rect: pygame.Rect, registry, ui_state) -> None:
    draw_panel(surface, rect, theme, fill=(17, 21, 23), alpha=238, radius=theme.radius_large)
    registry.register("minimap_jump", rect, action="minimap_jump", layer=6)
    title = theme.fonts.label.render(f"Observer Map  |  {ui_state.map_overlay.title()}", True, theme.palette.parchment)
    surface.blit(title, (rect.x + 14, rect.y + 10))
    legend_rect = pygame.Rect(rect.x + 14, rect.y + rect.h - 28, rect.w - 28, 18)
    registry.register("cycle_overlay_legend", legend_rect, action="cycle_overlay", layer=7)
    surface.blit(theme.fonts.caption.render("Click map to jump  |  Click legend to cycle overlay", True, theme.palette.muted_text), legend_rect.topleft)

def _draw_minimap_chunks(surface: pygame.Surface, theme: UITheme, context: dict, map_x: int, map_y: int, scale_x: float, scale_y: float) -> None:
    world_map = context.get("world_map")
    biome_colors = context.get("biome_colors", {})
    for chunk in getattr(world_map, "chunks", {}).values():
        mini_x = int(map_x + getattr(chunk, "world_x", 0.0) * scale_x)
        mini_y = int(map_y + getattr(chunk, "world_y", 0.0) * scale_y)
        mini_w = max(1, int(context.get("chunk_size", 1) * scale_x))
        mini_h = max(1, int(context.get("chunk_size", 1) * scale_y))
        center_tile = getattr(chunk, "tiles", {}).get((8, 8), "plains")
        pygame.draw.rect(surface, biome_colors.get(center_tile, theme.palette.slate_soft), (mini_x, mini_y, mini_w, mini_h))

def _draw_minimap_overlay(surface: pygame.Surface, theme: UITheme, context: dict, ui_state, map_x: int, map_y: int, scale_x: float, scale_y: float) -> None:
    overlay = ui_state.map_overlay
    world_map = context.get("world_map")
    biome_colors = context.get("biome_colors", {})
    region_lookup = _region_overlay_lookup(world_map)

    if overlay == "biome":
        for region in region_lookup.values():
            rect_data = region.get("world_rect")
            if not isinstance(rect_data, (list, tuple)) or len(rect_data) != 4:
                continue
            rx, ry, rw, rh = rect_data
            pygame.draw.rect(
                surface,
                biome_colors.get(str(region.get("biome", "plains")), theme.palette.slate_soft),
                (map_x + int(rx * scale_x), map_y + int(ry * scale_y), max(2, int(rw * scale_x)), max(2, int(rh * scale_y))),
                0,
            )
    elif overlay == "elevation":
        for region in region_lookup.values():
            rect_data = region.get("world_rect")
            if not isinstance(rect_data, (list, tuple)) or len(rect_data) != 4:
                continue
            rx, ry, rw, rh = rect_data
            elevation = max(0.0, min(1.0, float(region.get("elevation", 0.5) or 0.5)))
            shade = int(40 + (elevation * 180))
            pygame.draw.rect(
                surface,
                (shade, shade, shade + 12),
                (map_x + int(rx * scale_x), map_y + int(ry * scale_y), max(2, int(rw * scale_x)), max(2, int(rh * scale_y))),
                0,
            )
    elif overlay == "water":
        for segment in getattr(world_map, "water_network", []):
            points = []
            for point in segment.get("points", []):
                try:
                    points.append((int(map_x + float(point.get("x", 0.0)) * scale_x), int(map_y + float(point.get("y", 0.0)) * scale_y)))
                except (AttributeError, TypeError, ValueError):
                    continue
            if len(points) >= 2:
                pygame.draw.lines(surface, theme.palette.frost, False, points, 2)
    elif overlay == "claims":
        for polity in getattr(world_map, "polity_overlay", []):
            accent = tuple(polity.get("accent_color", (196, 174, 140)))
            for region_id in polity.get("claimed_region_ids", []):
                region = region_lookup.get(str(region_id))
                if region is None:
                    continue
                rect_data = region.get("world_rect")
                if not isinstance(rect_data, (list, tuple)) or len(rect_data) != 4:
                    continue
                rx, ry, rw, rh = rect_data
                overlay_surface = pygame.Surface((max(2, int(rw * scale_x)), max(2, int(rh * scale_y))), pygame.SRCALPHA)
                overlay_surface.fill((*accent[:3], 84))
                surface.blit(overlay_surface, (map_x + int(rx * scale_x), map_y + int(ry * scale_y)))
    elif overlay == "districts":
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
    elif overlay == "hazards":
        for hazard in getattr(world_map, "hazards", []):
            hx = int(map_x + getattr(hazard, "x", 0.0) * scale_x)
            hy = int(map_y + getattr(hazard, "y", 0.0) * scale_y)
            radius = max(3, int(float(getattr(hazard, "radius", 20.0)) * max(scale_x, scale_y)))
            pygame.draw.circle(surface, theme.palette.danger, (hx, hy), radius, 1)
    elif overlay == "routes":
        for route in getattr(world_map, "route_network", []):
            points = []
            for point in route.get("points", []):
                try:
                    points.append((int(map_x + float(point.get("x", 0.0)) * scale_x), int(map_y + float(point.get("y", 0.0)) * scale_y)))
                except (AttributeError, TypeError, ValueError):
                    continue
            if len(points) >= 2:
                pygame.draw.lines(surface, theme.palette.copper, False, points, 2)
    elif overlay == "migration":
        faction_manager = context.get("faction_manager")
        praxans_by_id = {int(getattr(praxan, "id", 0)): praxan for praxan in context.get("praxans", [])}
        for faction in getattr(faction_manager, "factions", {}).values():
            centroid = _faction_centroid(faction, praxans_by_id)
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

def _draw_minimap_entities(surface: pygame.Surface, theme: UITheme, context: dict, map_x: int, map_y: int, scale_x: float, scale_y: float) -> None:
    camera = context.get("camera")
    for praxan in context.get("praxans", []):
        mini_x = int(map_x + praxan.x * scale_x)
        mini_y = int(map_y + praxan.y * scale_y)
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

def _draw_minimap(surface: pygame.Surface, theme: UITheme, layout, registry, ui_state, context: dict) -> None:
    rect = layout.minimap
    _draw_minimap_background(surface, theme, rect, registry, ui_state)

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

    _draw_minimap_chunks(surface, theme, context, map_x, map_y, scale_x, scale_y)
    _draw_minimap_overlay(surface, theme, context, ui_state, map_x, map_y, scale_x, scale_y)
    _draw_minimap_entities(surface, theme, context, map_x, map_y, scale_x, scale_y)



def _build_alerts(praxans, buildings, advisor) -> list[dict]:
    """Auto-generate severity-colored alerts from game state."""
    alerts = []

    # Red alerts
    for p in praxans:
        if getattr(p, "mental_state", None):
            alerts.append({"text": f"P#{p.id} mental break!", "severity": "red"})
        if getattr(p, "downed", False):
            alerts.append({"text": f"P#{p.id} downed!", "severity": "red"})
    if len(praxans) <= 2 and len(praxans) > 0:
        alerts.append({"text": "Extinction threat!", "severity": "red"})

    # Yellow alerts
    total_food = sum(p.inventory.get("food", 0) for p in praxans) + sum(
        getattr(b, "stored_resources", {}).get("food", 0) for b in buildings if hasattr(b, "stored_resources")
    )
    if total_food < len(praxans) * 2 and len(praxans) > 0:
        alerts.append({"text": "Low food stores", "severity": "yellow"})

    diseased_count = sum(1 for p in praxans if getattr(p, "diseased", False))
    if diseased_count > 0:
        alerts.append({"text": f"{diseased_count} praxan(s) diseased", "severity": "yellow"})

    hungry_count = sum(1 for p in praxans if p.needs.get("hunger", 100) < 20)
    if hungry_count > 0:
        alerts.append({"text": f"{hungry_count} praxan(s) starving", "severity": "yellow"})

    return alerts[:6]  # Cap at 6 for screen space


def _draw_alert_stack(surface: pygame.Surface, theme: UITheme, layout, alerts: list[dict]) -> None:
    if not alerts:
        return

    # Position in top-right corner below the top ribbon
    x = surface.get_width() - 220
    y = layout.top_ribbon.bottom + 8

    severity_colors = {
        "red": (180, 45, 45),
        "yellow": (180, 150, 30),
        "blue": (50, 120, 180),
    }

    for alert in alerts:
        color = severity_colors.get(alert.get("severity", "blue"), (50, 120, 180))
        text = alert.get("text", "Alert")

        alert_rect = pygame.Rect(x, y, 210, 28)
        draw_panel(surface, alert_rect, theme, fill=color, alpha=220, radius=theme.radius_small)
        text_surf = theme.fonts.caption.render(text[:30], True, (255, 255, 255))
        surface.blit(text_surf, (alert_rect.x + 8, alert_rect.y + 6))

        y += 32


def _draw_hotkeys(surface: pygame.Surface, theme: UITheme) -> None:
    hotkeys = [
        ("Space", "Pause/Play"),
        ("/", "Search"),
        ("H", "History Graph"),
        ("LClick", "Select"),
        ("RClick", "Context Menu"),
    ]
    x = 20
    y = surface.get_height() - 30
    for key, action in hotkeys:
        key_surf = theme.fonts.caption.render(f"[{key}]", True, theme.palette.copper)
        act_surf = theme.fonts.caption.render(action, True, theme.palette.muted_text)
        surface.blit(key_surf, (x, y))
        surface.blit(act_surf, (x + key_surf.get_width() + 4, y))
        x += key_surf.get_width() + act_surf.get_width() + 16


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
    advisor=None,
) -> None:
    _draw_top_ribbon(surface, theme, layout, registry, hud_model)
    _draw_notes(surface, theme, layout, registry, field_notes)
    _draw_transport_bar(surface, theme, layout, registry, ui_state, current_speed_index)
    _draw_minimap(surface, theme, layout, registry, ui_state, minimap_context)
    _draw_hotkeys(surface, theme)

    # New Layers
    praxans = minimap_context.get("praxans", [])
    buildings = minimap_context.get("buildings", [])
    _draw_pawn_roster(surface, theme, layout, registry, praxans)
    _draw_bottom_spine(surface, theme, layout, registry, ui_state)
    _draw_context_menu(surface, theme, registry, ui_state)

    # Alert stack
    alerts = _build_alerts(praxans, buildings, advisor)
    _draw_alert_stack(surface, theme, layout, alerts)

