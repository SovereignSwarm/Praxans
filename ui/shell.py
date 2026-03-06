from __future__ import annotations

from typing import Any

import pygame

from game_scenarios import get_scenario_profile, list_scenario_ids
from run_archive import find_recent_archives, load_run_archive
from run_snapshot import resolve_snapshot_path
from ui.input_router import UIState, UIRectRegistry
from ui.layout import compute_shell_layout
from ui.models import ArchiveCard, build_archive_card
from ui.theme import UITheme, build_ui_theme, draw_button, draw_divider, draw_panel, wrap_text


def _load_archive_cards(log_dir: str, limit: int = 12) -> list[ArchiveCard]:
    cards: list[ArchiveCard] = []
    for archive_path in find_recent_archives(log_dir, limit=limit):
        try:
            cards.append(build_archive_card(load_run_archive(archive_path)))
        except Exception:
            continue
    return cards


def _draw_background(surface: pygame.Surface, theme: UITheme) -> None:
    width, height = surface.get_size()
    surface.fill((15, 19, 21))
    for index in range(0, width + 120, 120):
        color = theme.palette.panel_fill if (index // 120) % 2 == 0 else theme.palette.panel_fill_alt
        pygame.draw.polygon(
            surface,
            color,
            [(index - 40, 0), (index + 60, 0), (index + 20, height), (index - 80, height)],
        )
    wash = pygame.Surface((width, height), pygame.SRCALPHA)
    wash.fill((178, 148, 92, 18))
    surface.blit(wash, (0, 0))


def _draw_home(
    surface: pygame.Surface,
    theme: UITheme,
    layout,
    registry: UIRectRegistry,
    ui_state: UIState,
    archive_cards: list[ArchiveCard],
    latest_snapshot_path: str | None,
) -> None:
    draw_panel(surface, layout.hero, theme, fill=(27, 33, 35), alpha=242, radius=theme.radius_large)
    title = theme.fonts.display.render("THRONGLETS", True, theme.palette.parchment)
    surface.blit(title, (layout.hero.x + 22, layout.hero.y + 20))
    strap = theme.fonts.heading.render("Living Atlas Observer Interface", True, theme.palette.frost)
    surface.blit(strap, (layout.hero.x + 24, layout.hero.y + 78))
    summary = (
        "Watch an autonomous colony mutate, split into factions, survive disasters, "
        "and leave behind a readable social history."
    )
    summary_lines = wrap_text(theme.fonts.body, summary, layout.hero.w - 280)
    y = layout.hero.y + 122
    for line in summary_lines:
        surface.blit(theme.fonts.body.render(line, True, theme.palette.bright_text), (layout.hero.x + 24, y))
        y += 28
    scenario_profile = get_scenario_profile(ui_state.selected_scenario_id or "standard")
    meta = theme.fonts.data.render(
        f"Selected Scenario  {scenario_profile['name']}  |  Observer-only autonomous run",
        True,
        theme.palette.parchment_soft,
    )
    surface.blit(meta, (layout.hero.x + 24, layout.hero.bottom - 42))
    accent_rect = pygame.Rect(layout.hero.right - 250, layout.hero.y + 24, 210, layout.hero.h - 48)
    draw_panel(surface, accent_rect, theme, fill=(40, 46, 44), alpha=232)
    accent_title = theme.fonts.label.render("Field Brief", True, theme.palette.ochre)
    surface.blit(accent_title, (accent_rect.x + 16, accent_rect.y + 16))
    brief_lines = wrap_text(theme.fonts.caption, scenario_profile.get("description", ""), accent_rect.w - 32)
    y = accent_rect.y + 48
    for line in brief_lines[:6]:
        surface.blit(theme.fonts.caption.render(line, True, theme.palette.bright_text), (accent_rect.x + 16, y))
        y += 20
    status_line = "Latest snapshot ready" if latest_snapshot_path else "No resumable snapshot found"
    status_color = theme.palette.success if latest_snapshot_path else theme.palette.warning
    surface.blit(theme.fonts.caption.render(status_line, True, status_color), (accent_rect.x + 16, accent_rect.bottom - 28))

    nav_items = [
        ("shell_start", "Start New Run", "Enter"),
        ("shell_resume", "Resume Latest", "R"),
        ("shell_nav_scenarios", "Scenarios", "S"),
        ("shell_nav_archives", "Archives", "A"),
        ("shell_nav_settings", "Settings", ","),
        ("shell_quit", "Quit", "Esc"),
    ]
    y = layout.nav_column.y + 16
    for action, label, hotkey in nav_items:
        rect = pygame.Rect(layout.nav_column.x + 12, y, layout.nav_column.w - 24, 46)
        registry.register(action, rect, action=action, layer=4)
        active = ui_state.active_screen == {
            "shell_nav_scenarios": "scenario_browser",
            "shell_nav_archives": "archive_browser",
            "shell_nav_settings": "settings",
        }.get(action, "command_center")
        draw_button(
            surface,
            rect,
            theme,
            label,
            hotkey=hotkey,
            active=active and action not in {"shell_start", "shell_resume", "shell_quit"},
            accent=theme.palette.ochre if action == "shell_start" else theme.palette.slate_soft,
        )
        y += 56
    detail_rect = layout.detail_panel
    draw_panel(surface, detail_rect, theme, fill=(24, 31, 33), alpha=238)
    heading = theme.fonts.heading.render("Current Vision", True, theme.palette.parchment)
    surface.blit(heading, (detail_rect.x + 18, detail_rect.y + 18))
    bullets = [
        "Observer-first: no live command channel into the colony AI.",
        "Mouse-first navigation, archive browsing, and modal workbooks.",
        "Bounded local LLM council with deterministic simulation authority.",
        "Scenario-led runs with archival summaries and comparison.",
    ]
    y = detail_rect.y + 58
    for bullet in bullets:
        bullet_lines = wrap_text(theme.fonts.body, bullet, detail_rect.w - 36)
        for line in bullet_lines:
            surface.blit(theme.fonts.body.render(line, True, theme.palette.bright_text), (detail_rect.x + 22, y))
            y += 24
        y += 10
    if ui_state.shell_notice:
        notice = theme.fonts.caption.render(ui_state.shell_notice, True, theme.palette.warning)
        surface.blit(notice, (detail_rect.x + 18, detail_rect.bottom - 30))

    draw_panel(surface, layout.recent_runs, theme, fill=(22, 27, 29), alpha=236)
    title = theme.fonts.heading.render("Recent Observer Archives", True, theme.palette.parchment)
    surface.blit(title, (layout.recent_runs.x + 18, layout.recent_runs.y + 16))
    if not archive_cards:
        empty = theme.fonts.body.render("No archive cards yet. Start a run to populate the atlas.", True, theme.palette.muted_text)
        surface.blit(empty, (layout.recent_runs.x + 18, layout.recent_runs.y + 60))
        return
    card_w = max(210, (layout.recent_runs.w - 36 - 18 * 3) // 4)
    for index, card in enumerate(archive_cards[:4]):
        rect = pygame.Rect(layout.recent_runs.x + 18 + index * (card_w + 18), layout.recent_runs.y + 52, card_w, layout.recent_runs.h - 70)
        registry.register(f"archive_select:{card.session_id}", rect, action="archive_select", payload=card.session_id, layer=3)
        draw_panel(surface, rect, theme, fill=(30, 36, 37), alpha=238)
        surface.blit(theme.fonts.label.render(card.scenario_name[:20], True, theme.palette.frost), (rect.x + 12, rect.y + 12))
        surface.blit(theme.fonts.heading.render(str(card.score), True, theme.palette.ochre), (rect.x + 12, rect.y + 40))
        surface.blit(theme.fonts.caption.render(card.end_state_label[:24], True, theme.palette.bright_text), (rect.x + 58, rect.y + 46))
        meta = f"Peak {card.population_peak}  |  {int(card.duration_seconds)}s"
        surface.blit(theme.fonts.caption.render(meta, True, theme.palette.muted_text), (rect.x + 12, rect.bottom - 28))


def _draw_scenario_browser(surface: pygame.Surface, theme: UITheme, layout, registry: UIRectRegistry, ui_state: UIState) -> None:
    draw_panel(surface, layout.nav_column, theme, fill=(22, 27, 29), alpha=236)
    title = theme.fonts.heading.render("Scenario Catalog", True, theme.palette.parchment)
    surface.blit(title, (layout.nav_column.x + 16, layout.nav_column.y + 16))
    y = layout.nav_column.y + 56
    for scenario_id in list_scenario_ids():
        profile = get_scenario_profile(scenario_id)
        rect = pygame.Rect(layout.nav_column.x + 12, y, layout.nav_column.w - 24, 42)
        registry.register(f"scenario:{scenario_id}", rect, action="scenario_select", payload=scenario_id, layer=4)
        draw_button(surface, rect, theme, profile["name"], active=scenario_id == ui_state.selected_scenario_id, accent=theme.palette.moss)
        y += 50

    draw_panel(surface, layout.detail_panel, theme, fill=(24, 31, 33), alpha=238)
    profile = get_scenario_profile(ui_state.selected_scenario_id or "standard")
    title = theme.fonts.display.render(profile["name"], True, theme.palette.parchment)
    surface.blit(title, (layout.detail_panel.x + 20, layout.detail_panel.y + 18))
    subtitle = theme.fonts.label.render(profile["id"], True, theme.palette.frost)
    surface.blit(subtitle, (layout.detail_panel.x + 24, layout.detail_panel.y + 74))
    lines = wrap_text(theme.fonts.body, profile.get("description", ""), layout.detail_panel.w - 40)
    y = layout.detail_panel.y + 118
    for line in lines[:5]:
        surface.blit(theme.fonts.body.render(line, True, theme.palette.bright_text), (layout.detail_panel.x + 24, y))
        y += 28
    modifiers = [
        f"Spawn Biomes: {', '.join(profile.get('spawn_biomes', [])) or 'varied'}",
        f"Initial Population: {int(profile.get('initial_population', 2) or 2)}",
        f"Mutation Scale: {float(profile.get('mutation_scale', 1.0) or 1.0):.2f}x",
        f"Starting Weather: {str(profile.get('starting_weather', 'clear')).title()}",
    ]
    y += 18
    for modifier in modifiers:
        surface.blit(theme.fonts.caption.render(modifier, True, theme.palette.parchment_soft), (layout.detail_panel.x + 24, y))
        y += 24
    start_rect = pygame.Rect(layout.detail_panel.x + 24, layout.detail_panel.bottom - 64, 220, 44)
    registry.register("shell_start", start_rect, action="shell_start", layer=5)
    draw_button(surface, start_rect, theme, "Start Selected Run", hotkey="Enter", active=True, accent=theme.palette.ochre)
    back_rect = pygame.Rect(start_rect.right + 12, start_rect.y, 140, 44)
    registry.register("shell_nav_home", back_rect, action="shell_nav_home", layer=5)
    draw_button(surface, back_rect, theme, "Back", hotkey="Esc", accent=theme.palette.slate_soft)


def _draw_archive_browser(
    surface: pygame.Surface,
    theme: UITheme,
    layout,
    registry: UIRectRegistry,
    ui_state: UIState,
    archive_cards: list[ArchiveCard],
) -> None:
    draw_panel(surface, layout.detail_panel, theme, fill=(24, 31, 33), alpha=238)
    draw_panel(surface, layout.nav_column, theme, fill=(22, 27, 29), alpha=236)
    title = theme.fonts.heading.render("Archive Browser", True, theme.palette.parchment)
    surface.blit(title, (layout.detail_panel.x + 18, layout.detail_panel.y + 16))
    back_rect = pygame.Rect(layout.nav_column.x + 12, layout.nav_column.y + 16, layout.nav_column.w - 24, 42)
    registry.register("shell_nav_home", back_rect, action="shell_nav_home", layer=4)
    draw_button(surface, back_rect, theme, "Back to Dashboard", hotkey="Esc", accent=theme.palette.slate_soft)
    y = layout.nav_column.y + 74
    selected_payload = None
    compare_payload = None
    for card in archive_cards[:8]:
        rect = pygame.Rect(layout.nav_column.x + 12, y, layout.nav_column.w - 24, 52)
        registry.register(f"archive_select:{card.session_id}", rect, action="archive_select", payload=card.session_id, layer=4)
        active = card.session_id in {ui_state.selected_run, ui_state.compare_run}
        draw_button(surface, rect, theme, card.scenario_name[:18], hotkey=str(card.score), active=active, accent=theme.palette.moss)
        if card.session_id == ui_state.selected_run:
            selected_payload = card.payload
        if card.session_id == ui_state.compare_run:
            compare_payload = card.payload
        y += 60
    if selected_payload is None and archive_cards:
        selected_payload = archive_cards[0].payload
        ui_state.selected_run = archive_cards[0].session_id
    if selected_payload:
        headline = theme.fonts.display.render(str(selected_payload.get("summary_card", {}).get("headline", "Observer run"))[:38], True, theme.palette.parchment)
        surface.blit(headline, (layout.detail_panel.x + 18, layout.detail_panel.y + 54))
        details = [
            f"Scenario: {selected_payload.get('scenario', {}).get('name', 'Unknown')}",
            f"End-state: {selected_payload.get('end_state', {}).get('label', 'Unknown')}",
            f"Score: {int(selected_payload.get('end_state', {}).get('score', 0) or 0)}",
            f"Peak Population: {int(selected_payload.get('summary_card', {}).get('population_peak', 0) or 0)}",
        ]
        y = layout.detail_panel.y + 110
        for detail in details:
            surface.blit(theme.fonts.body.render(detail, True, theme.palette.bright_text), (layout.detail_panel.x + 22, y))
            y += 28
        surface.blit(theme.fonts.label.render("Key Moments", True, theme.palette.ochre), (layout.detail_panel.x + 22, y + 10))
        y += 40
        for moment in list(selected_payload.get("key_moments", []))[:6]:
            line = f"[{str(moment.get('category', 'sim')).upper()}] {str(moment.get('summary', 'Event'))}"
            for wrapped in wrap_text(theme.fonts.caption, line, layout.detail_panel.w - 44):
                surface.blit(theme.fonts.caption.render(wrapped, True, theme.palette.parchment_soft), (layout.detail_panel.x + 22, y))
                y += 20
        if compare_payload:
            compare_title = theme.fonts.label.render("Comparison", True, theme.palette.frost)
            surface.blit(compare_title, (layout.detail_panel.x + layout.detail_panel.w // 2, layout.detail_panel.y + 54))
            compare_lines = [
                f"{compare_payload.get('scenario', {}).get('name', 'Unknown')}",
                f"Score {int(compare_payload.get('end_state', {}).get('score', 0) or 0)}",
                f"Peak {int(compare_payload.get('summary_card', {}).get('population_peak', 0) or 0)}",
            ]
            y = layout.detail_panel.y + 94
            for line in compare_lines:
                surface.blit(theme.fonts.caption.render(line, True, theme.palette.bright_text), (layout.detail_panel.x + layout.detail_panel.w // 2, y))
                y += 24


def _draw_settings(surface: pygame.Surface, theme: UITheme, layout, registry: UIRectRegistry, runtime_config) -> None:
    draw_panel(surface, layout.detail_panel, theme, fill=(24, 31, 33), alpha=238)
    draw_panel(surface, layout.nav_column, theme, fill=(22, 27, 29), alpha=236)
    back_rect = pygame.Rect(layout.nav_column.x + 12, layout.nav_column.y + 16, layout.nav_column.w - 24, 42)
    registry.register("shell_nav_home", back_rect, action="shell_nav_home", layer=4)
    draw_button(surface, back_rect, theme, "Back to Dashboard", hotkey="Esc", accent=theme.palette.slate_soft)
    title = theme.fonts.display.render("Observer Settings", True, theme.palette.parchment)
    surface.blit(title, (layout.detail_panel.x + 20, layout.detail_panel.y + 18))
    items = [
        f"Resolution  {runtime_config.width}x{runtime_config.height}",
        f"Preferred Model  {runtime_config.model}",
        f"Simulation FPS  {runtime_config.fps}",
        "Controls  Mouse inspect / pan, F follow, 1/2/5 speed, R/S/T/A modal workbooks",
        "Observer Principle  The colony remains autonomous at all times.",
    ]
    y = layout.detail_panel.y + 88
    for item in items:
        for wrapped in wrap_text(theme.fonts.body, item, layout.detail_panel.w - 40):
            surface.blit(theme.fonts.body.render(wrapped, True, theme.palette.bright_text), (layout.detail_panel.x + 24, y))
            y += 28
        y += 6


def run_command_center(screen: pygame.Surface, clock: pygame.time.Clock, runtime_config, initial_scenario_id: str) -> tuple[pygame.Surface, dict[str, Any]]:
    ui_state = UIState(active_screen="command_center", selected_scenario_id=initial_scenario_id)
    registry = UIRectRegistry()
    archive_cards = _load_archive_cards(runtime_config.log_dir, limit=12)
    latest_snapshot_path = resolve_snapshot_path(runtime_config.log_dir, load_latest=True)
    while True:
        theme = build_ui_theme(*screen.get_size())
        layout = compute_shell_layout(*screen.get_size())
        registry.reset()
        _draw_background(screen, theme)
        if ui_state.active_screen == "command_center":
            _draw_home(screen, theme, layout, registry, ui_state, archive_cards, latest_snapshot_path)
        elif ui_state.active_screen == "scenario_browser":
            _draw_scenario_browser(screen, theme, layout, registry, ui_state)
        elif ui_state.active_screen == "archive_browser":
            _draw_archive_browser(screen, theme, layout, registry, ui_state, archive_cards)
        else:
            _draw_settings(screen, theme, layout, registry, runtime_config)

        footer = layout.footer
        draw_divider(screen, theme, (footer.x, footer.y), (footer.right, footer.y))
        footer_text = theme.fonts.caption.render(
            "Observer-only command center  |  Naturalist atlas mode  |  Click a control or press Enter to begin",
            True,
            theme.palette.muted_text,
        )
        screen.blit(footer_text, (footer.x + 8, footer.y + 18))
        pygame.display.flip()
        clock.tick(30)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return screen, {"action": "quit"}
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode(event.size, pygame.SCALED | pygame.RESIZABLE)
                continue
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    return screen, {
                        "action": "start",
                        "scenario_id": ui_state.selected_scenario_id or initial_scenario_id,
                        "snapshot_path": None,
                    }
                if event.key == pygame.K_ESCAPE:
                    if ui_state.active_screen == "command_center":
                        return screen, {"action": "quit"}
                    ui_state.active_screen = "command_center"
                    continue
                if event.key == pygame.K_r and latest_snapshot_path:
                    return screen, {
                        "action": "resume",
                        "scenario_id": ui_state.selected_scenario_id or initial_scenario_id,
                        "snapshot_path": latest_snapshot_path,
                    }
                if event.key == pygame.K_a:
                    ui_state.active_screen = "archive_browser"
                elif event.key == pygame.K_s:
                    ui_state.active_screen = "scenario_browser"
                continue
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                hit = registry.hit_test(event.pos)
                if hit is None:
                    continue
                action = hit.action or hit.id
                if action == "shell_start":
                    return screen, {
                        "action": "start",
                        "scenario_id": ui_state.selected_scenario_id or initial_scenario_id,
                        "snapshot_path": None,
                    }
                if action == "shell_resume":
                    if latest_snapshot_path:
                        return screen, {
                            "action": "resume",
                            "scenario_id": ui_state.selected_scenario_id or initial_scenario_id,
                            "snapshot_path": latest_snapshot_path,
                        }
                    ui_state.shell_notice = "No latest snapshot is available yet."
                elif action == "shell_nav_scenarios":
                    ui_state.active_screen = "scenario_browser"
                elif action == "shell_nav_archives":
                    ui_state.active_screen = "archive_browser"
                elif action == "shell_nav_settings":
                    ui_state.active_screen = "settings"
                elif action == "shell_nav_home":
                    ui_state.active_screen = "command_center"
                elif action == "scenario_select":
                    ui_state.selected_scenario_id = str(hit.payload)
                elif action == "archive_select":
                    session_id = str(hit.payload)
                    if ui_state.selected_run is None or ui_state.selected_run == session_id:
                        ui_state.selected_run = session_id
                    elif ui_state.compare_run == session_id:
                        ui_state.compare_run = None
                    elif ui_state.compare_run is None:
                        ui_state.compare_run = session_id
                    else:
                        ui_state.selected_run = session_id
                        ui_state.compare_run = None
                    ui_state.active_screen = "archive_browser"
                elif action == "shell_quit":
                    return screen, {"action": "quit"}
