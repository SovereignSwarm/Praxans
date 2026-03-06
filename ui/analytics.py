from __future__ import annotations

import time as _time

import pygame

from run_archive import find_recent_archives, load_run_archive
from ui.models import ArchiveCard, build_archive_card
from ui.theme import draw_button, draw_divider, draw_panel, wrap_text

_archive_cache: dict[str, tuple[float, list[ArchiveCard]]] = {}


def load_archive_cards(log_dir: str, limit: int = 18) -> list[ArchiveCard]:
    now = _time.monotonic()
    cached = _archive_cache.get(log_dir)
    if cached is not None and now - cached[0] < 10.0:
        return cached[1]
    cards: list[ArchiveCard] = []
    for archive_path in find_recent_archives(log_dir, limit=limit):
        try:
            cards.append(build_archive_card(load_run_archive(archive_path)))
        except Exception:
            continue
    _archive_cache[log_dir] = (now, cards)
    return cards


def _draw_modal_frame(surface: pygame.Surface, theme, rect: pygame.Rect, title: str, subtitle: str) -> None:
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((10, 12, 14, 120))
    surface.blit(overlay, (0, 0))
    draw_panel(surface, rect, theme, fill=(18, 22, 24), alpha=242, radius=theme.radius_large)
    surface.blit(theme.fonts.display.render(title, True, theme.palette.parchment), (rect.x + 20, rect.y + 14))
    surface.blit(theme.fonts.caption.render(subtitle, True, theme.palette.parchment_soft), (rect.x + 24, rect.y + 58))
    draw_divider(surface, theme, (rect.x + 20, rect.y + 88), (rect.right - 20, rect.y + 88))


def _draw_research_modal(surface: pygame.Surface, theme, rect: pygame.Rect, advisor) -> None:
    unlocked = sorted(getattr(getattr(advisor, "game_modifiers", None), "tech_unlocked", set()))
    available = []
    for tech_id, tech_data in getattr(advisor, "tech_tree", {}).items():
        if tech_id in unlocked:
            continue
        requires = tech_data.get("requires", [])
        if all(requirement in unlocked for requirement in requires):
            available.append((tech_id, tech_data))
    sections = [
        ("Research Points", [f"{int(getattr(advisor, 'research_points', 0) or 0)} points available"]),
        ("Unlocked Technologies", [str(getattr(advisor, "tech_tree", {}).get(tech_id, {}).get("name", tech_id)) for tech_id in unlocked[:8]] or ["None yet"]),
        (
            "Available Technologies",
            [f"{data.get('name', tech_id)}  |  Cost {int(data.get('cost', 0) or 0)}" for tech_id, data in available[:6]] or ["No available unlocks"],
        ),
        (
            "Abilities",
            [f"{ability_name}  |  Cost {int(ability_data.get('cost', 0) or 0)}" for ability_name, ability_data in getattr(advisor, "abilities", {}).items()]
            or ["No abilities configured"],
        ),
    ]
    x = rect.x + 24
    y = rect.y + 108
    col_w = (rect.w - 64) // 2
    for index, (title, lines) in enumerate(sections):
        col = index % 2
        row = index // 2
        box = pygame.Rect(x + col * (col_w + 16), y + row * 214, col_w, 190)
        draw_panel(surface, box, theme, fill=(28, 34, 36), alpha=238)
        surface.blit(theme.fonts.label.render(title, True, theme.palette.ochre), (box.x + 12, box.y + 12))
        line_y = box.y + 42
        for line in lines[:6]:
            for wrapped in wrap_text(theme.fonts.caption, line, box.w - 24):
                surface.blit(theme.fonts.caption.render(wrapped, True, theme.palette.bright_text), (box.x + 12, line_y))
                line_y += 18


def _draw_evolution_modal(surface: pygame.Surface, theme, rect: pygame.Rect, evolution_summary: dict, session_stats: dict) -> None:
    sections = [
        (
            "Generation Drift",
            [
                f"Average Generation  {float(evolution_summary.get('avg_generation', 0.0) or 0.0):.1f}",
                f"Max Generation  {int(evolution_summary.get('max_generation', 0) or 0)}",
                f"Founder Lines  {int(evolution_summary.get('founder_lines', 0) or 0)}",
            ],
        ),
        (
            "Trait Outliers",
            [
                f"{str(item.get('trait_name', 'trait')).replace('_', ' ').title()}  {float(item.get('delta_pct', 0.0) or 0.0):+.1f}%"
                for item in list((session_stats.get("current_run_summary", {}) or {}).get("observer_report", {}).get("trait_outliers", []))[:6]
            ]
            or ["No major drift yet"],
        ),
        (
            "Generation Checkpoints",
            [
                f"t+{int(sample.get('elapsed_seconds', 0) or 0)}s  |  pop {int(sample.get('population', 0) or 0)}  |  gen {float(sample.get('avg_generation', 0.0) or 0.0):.1f}"
                for sample in list(session_stats.get("generation_history", []))[-6:]
            ]
            or ["No checkpoints yet"],
        ),
        (
            "Lineage History",
            [str(event.get("summary") or event.get("label") or "Lineage event") for event in list(session_stats.get("lineage_events", []))[-6:]]
            or ["No lineage events yet"],
        ),
    ]
    x = rect.x + 24
    y = rect.y + 108
    col_w = (rect.w - 64) // 2
    for index, (title, lines) in enumerate(sections):
        col = index % 2
        row = index // 2
        box = pygame.Rect(x + col * (col_w + 16), y + row * 214, col_w, 190)
        draw_panel(surface, box, theme, fill=(28, 34, 36), alpha=238)
        surface.blit(theme.fonts.label.render(title, True, theme.palette.frost), (box.x + 12, box.y + 12))
        line_y = box.y + 42
        for line in lines[:7]:
            for wrapped in wrap_text(theme.fonts.caption, line, box.w - 24):
                surface.blit(theme.fonts.caption.render(wrapped, True, theme.palette.bright_text), (box.x + 12, line_y))
                line_y += 18


def _draw_analytics_modal(surface: pygame.Surface, theme, rect: pygame.Rect, registry, ui_state, current_summary: dict) -> None:
    observer_report = dict(current_summary.get("observer_report", {}) or {})
    sections = {
        "population": [
            f"Population  {int(observer_report.get('population', 0) or 0)}",
            f"Peak Population  {int(observer_report.get('max_population', 0) or 0)}",
            f"Births / Deaths  {int(observer_report.get('births_total', 0) or 0)} / {int(observer_report.get('deaths_total', 0) or 0)}",
            f"Average Survival  {float(observer_report.get('avg_survival_time', 0.0) or 0.0):.1f}s",
        ],
        "lineage": [
            f"L{int(item.get('lineage_id', 0) or 0)}  {int(item.get('count', 0) or 0)}  ({int(float(item.get('share', 0.0) or 0.0) * 100)}%)"
            for item in observer_report.get("top_lineages", [])[:8]
        ]
        or ["No lineage divergence yet"],
        "factions": [
            f"F{int(item.get('id', 0) or 0)}  size {int(item.get('members', 0) or 0)}  coh {int(item.get('cohesion', 0) or 0)}"
            for item in observer_report.get("active_factions", [])[:8]
        ]
        or ["No active factions"],
        "pressure": [
            f"Phase  {current_summary.get('current_phase', {}).get('label', 'Founding')}",
            f"End-state  {current_summary.get('end_state', {}).get('label', 'Brittle Survival')}",
            f"Prosperity  {float(current_summary.get('settlement', {}).get('prosperity_score', 0.0) or 0.0):.2f}",
            f"Culture  {float(current_summary.get('settlement', {}).get('culture_score', 0.0) or 0.0):.2f}",
        ],
    }
    tabs = [("population", "Population"), ("lineage", "Lineage"), ("factions", "Factions"), ("pressure", "Pressure")]
    x = rect.x + 24
    tab_y = rect.y + 104
    for tab_id, label in tabs:
        tab_rect = pygame.Rect(x, tab_y, 120, 32)
        registry.register(f"analytics_tab:{tab_id}", tab_rect, action="analytics_tab", payload=tab_id, layer=21)
        draw_button(surface, tab_rect, theme, label, active=ui_state.analytics_section == tab_id, accent=theme.palette.note_faction, subtle=True)
        x += 130
    content_rect = pygame.Rect(rect.x + 24, rect.y + 154, rect.w - 48, rect.h - 178)
    draw_panel(surface, content_rect, theme, fill=(28, 34, 36), alpha=238)
    line_y = rect.y + 174
    for line in sections.get(ui_state.analytics_section, sections["population"]):
        for wrapped in wrap_text(theme.fonts.body, line, rect.w - 84):
            surface.blit(theme.fonts.body.render(wrapped, True, theme.palette.bright_text), (rect.x + 42, line_y))
            line_y += 28
        line_y += 6

    # Population sparkline (bar chart of generation checkpoints)
    if ui_state.analytics_section == "population":
        pop_history = list(observer_report.get("population_history", []))[-8:]
        if not pop_history:
            pop_history = [int(observer_report.get("population", 0) or 0)]
        peak = max(max(pop_history), 1)
        sparkline_y = line_y + 12
        sparkline_x = rect.x + 42
        bar_max_w = content_rect.w - 56
        bar_h = 12
        surface.blit(theme.fonts.caption.render("Population Trend", True, theme.palette.ochre), (sparkline_x, sparkline_y))
        sparkline_y += 22
        for i, pop_val in enumerate(pop_history):
            bar_w = max(4, int((pop_val / peak) * bar_max_w))
            bar_color = theme.palette.moss if pop_val > peak * 0.5 else theme.palette.warning
            pygame.draw.rect(surface, bar_color, (sparkline_x, sparkline_y, bar_w, bar_h), border_radius=3)
            label_text = theme.fonts.caption.render(str(pop_val), True, theme.palette.bright_text)
            surface.blit(label_text, (sparkline_x + bar_w + 6, sparkline_y - 1))
            sparkline_y += bar_h + 6


def _draw_archive_modal(surface: pygame.Surface, theme, rect: pygame.Rect, registry, ui_state, current_summary: dict, archive_cards: list[ArchiveCard]) -> None:
    left_w = 300
    list_rect = pygame.Rect(rect.x + 24, rect.y + 104, left_w, rect.h - 132)
    detail_rect = pygame.Rect(list_rect.right + 18, list_rect.y, rect.w - left_w - 66, list_rect.h)
    draw_panel(surface, list_rect, theme, fill=(28, 34, 36), alpha=238)
    draw_panel(surface, detail_rect, theme, fill=(28, 34, 36), alpha=238)
    y = list_rect.y + 12 - max(0, ui_state.archive_scroll)
    selected = None
    compare = None
    for card in archive_cards:
        entry_rect = pygame.Rect(list_rect.x + 10, y, list_rect.w - 20, 64)
        registry.register(f"archive_select:{card.session_id}", entry_rect, action="archive_select", payload=card.session_id, layer=21)
        state = card.session_id in {ui_state.selected_run, ui_state.compare_run}
        draw_button(surface, entry_rect, theme, card.scenario_name[:18], hotkey=str(card.score), active=state, accent=theme.palette.note_discovery, subtle=True)
        if y >= list_rect.y - 70 and y <= list_rect.bottom:
            surface.blit(theme.fonts.caption.render(card.end_state_label[:22], True, theme.palette.parchment_soft), (entry_rect.x + 12, entry_rect.y + 38))
        if card.session_id == ui_state.selected_run:
            selected = card
        if card.session_id == ui_state.compare_run:
            compare = card
        y += 74
    if selected is None and archive_cards:
        selected = archive_cards[0]
    source = selected.payload if selected else current_summary
    headline = str(source.get("summary_card", {}).get("headline", "Current run"))
    surface.blit(theme.fonts.heading.render(headline[:42], True, theme.palette.parchment), (detail_rect.x + 18, detail_rect.y + 14))
    lines = [
        f"Scenario  {source.get('scenario', {}).get('name', 'Unknown')}",
        f"End-state  {source.get('end_state', {}).get('label', 'Unknown')}",
        f"Score  {int(source.get('end_state', {}).get('score', 0) or 0)}",
        f"Peak Population  {int(source.get('summary_card', {}).get('population_peak', 0) or 0)}",
    ]
    line_y = detail_rect.y + 54
    for line in lines:
        surface.blit(theme.fonts.body.render(line, True, theme.palette.bright_text), (detail_rect.x + 18, line_y))
        line_y += 28
    surface.blit(theme.fonts.label.render("Key Moments", True, theme.palette.ochre), (detail_rect.x + 18, line_y + 10))
    line_y += 40
    for moment in list(source.get("key_moments", []))[:8]:
        event_line = f"[{str(moment.get('category', 'sim')).upper()}] {str(moment.get('summary', 'Event'))}"
        for wrapped in wrap_text(theme.fonts.caption, event_line, detail_rect.w - 36):
            surface.blit(theme.fonts.caption.render(wrapped, True, theme.palette.bright_text), (detail_rect.x + 18, line_y))
            line_y += 18
    if compare:
        compare_y = detail_rect.y + 54
        compare_x = detail_rect.x + detail_rect.w // 2
        surface.blit(theme.fonts.label.render("Compare", True, theme.palette.frost), (compare_x, detail_rect.y + 14))
        compare_lines = [
            compare.scenario_name,
            compare.end_state_label,
            f"Score {compare.score}",
            f"Peak {compare.population_peak}",
        ]
        for line in compare_lines:
            surface.blit(theme.fonts.caption.render(line[:26], True, theme.palette.parchment_soft), (compare_x, compare_y))
            compare_y += 22


def draw_modal_layer(
    surface: pygame.Surface,
    theme,
    layout,
    registry,
    ui_state,
    *,
    advisor,
    current_summary: dict,
    current_time: float,
    log_dir: str,
    evolution_summary: dict,
) -> None:
    if not ui_state.active_modal:
        return
    rect = layout.modal
    registry.register("modal_frame", rect, layer=20, scrollable=ui_state.active_modal == "archive")
    modal = ui_state.active_modal
    if modal == "research":
        _draw_modal_frame(surface, theme, rect, "Research Ledger", "Unlocked technologies, available research, and active abilities")
        _draw_research_modal(surface, theme, rect, advisor)
    elif modal == "evolution":
        _draw_modal_frame(surface, theme, rect, "Evolution Workbook", "Generation drift, lineages, and mutation checkpoints")
        _draw_evolution_modal(surface, theme, rect, evolution_summary, getattr(advisor, "session_stats", {}) or {})
    elif modal == "analytics":
        _draw_modal_frame(surface, theme, rect, "Observer Analytics", "Population, lineages, factions, and run pressure")
        _draw_analytics_modal(surface, theme, rect, registry, ui_state, current_summary)
    elif modal == "archive":
        _draw_modal_frame(surface, theme, rect, "Archive Browser", "Completed runs, comparisons, and field-ready summaries")
        _draw_archive_modal(surface, theme, rect, registry, ui_state, current_summary, load_archive_cards(log_dir, limit=18))
    close_rect = pygame.Rect(rect.right - 124, rect.y + 18, 96, 34)
    registry.register("close_modal", close_rect, action="close_modal", layer=22)
    draw_button(surface, close_rect, theme, "Close", hotkey="Esc", accent=theme.palette.slate_soft, subtle=True)


def draw_end_summary(
    surface: pygame.Surface,
    theme,
    layout,
    registry,
    current_summary: dict,
    latest_snapshot_path: str | None,
) -> None:
    rect = layout.modal
    _draw_modal_frame(surface, theme, rect, str(current_summary.get("end_state", {}).get("label", "Run Complete")), "Observer summary of the completed civilization run")
    headline = current_summary.get("summary_card", {}).get("headline", "Observer run")
    surface.blit(theme.fonts.heading.render(str(headline)[:48], True, theme.palette.parchment), (rect.x + 24, rect.y + 108))
    details = [
        f"Score  {int(current_summary.get('end_state', {}).get('score', 0) or 0)}",
        f"Phase  {current_summary.get('current_phase', {}).get('label', 'Founding')}",
        f"Lineage Winner  L{current_summary.get('dominant_lineage', {}).get('lineage_id', '?')}",
        f"Dominant Faction  F{current_summary.get('dominant_faction', {}).get('id', '?')}",
    ]
    line_y = rect.y + 146
    for detail in details:
        surface.blit(theme.fonts.body.render(detail, True, theme.palette.bright_text), (rect.x + 28, line_y))
        line_y += 30
    badges = [
        ("Archive Review", "end_archive", theme.palette.note_discovery),
        ("Compare", "end_compare", theme.palette.note_faction),
        ("Resume Snapshot", "end_resume", theme.palette.moss if latest_snapshot_path else theme.palette.slate_soft),
        ("New Run", "end_new_run", theme.palette.ochre),
    ]
    button_x = rect.x + 24
    button_y = rect.bottom - 74
    for label, action, accent in badges:
        button_rect = pygame.Rect(button_x, button_y, 170, 42)
        registry.register(action, button_rect, action=action, layer=24)
        draw_button(surface, button_rect, theme, label, accent=accent, subtle=True)
        button_x += 182
    right_rect = pygame.Rect(rect.x + rect.w // 2, rect.y + 108, rect.w // 2 - 26, rect.h - 196)
    draw_panel(surface, right_rect, theme, fill=(28, 34, 36), alpha=238)
    surface.blit(theme.fonts.label.render("Major Moments", True, theme.palette.ochre), (right_rect.x + 16, right_rect.y + 12))
    line_y = right_rect.y + 42
    for moment in list(current_summary.get("key_moments", []))[:10]:
        line = f"[{str(moment.get('category', 'sim')).upper()}] {str(moment.get('summary', 'Event'))}"
        for wrapped in wrap_text(theme.fonts.caption, line, right_rect.w - 32):
            surface.blit(theme.fonts.caption.render(wrapped, True, theme.palette.bright_text), (right_rect.x + 16, line_y))
            line_y += 18
