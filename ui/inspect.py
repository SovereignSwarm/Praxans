from __future__ import annotations

import pygame

from ui.models import InspectSection, InspectViewModel
from ui.theme import draw_button, draw_divider, draw_panel, wrap_text


def _section(title: str, *lines: str) -> InspectSection:
    return InspectSection(title=title, lines=[line for line in lines if str(line).strip()])


def build_inspect_view_model(
    selected_entity,
    selected_type: str | None,
    advisor,
    current_time: float,
    settlement_state: dict,
    faction_manager=None,
    active_tab: str = "overview",
) -> InspectViewModel:
    if not selected_entity or not selected_type:
        tabs = [("overview", "Overview"), ("evolution", "Evolution"), ("risks", "Risks")]
        sections = [
            _section(
                "Settlement",
                f"District  {str(settlement_state.get('district_identity', 'homestead')).replace('_', ' ').title()}",
                f"Prosperity  {int(float(settlement_state.get('prosperity_score', 0.0) or 0.0) * 100)}%",
                f"Culture  {int(float(settlement_state.get('culture_score', 0.0) or 0.0) * 100)}%",
                f"Festival Readiness  {int(float(settlement_state.get('festival_readiness', 0.0) or 0.0) * 100)}%",
                f"Stores  F{int(settlement_state.get('stored_food', 0) or 0)}  W{int(settlement_state.get('stored_wood', 0) or 0)}  S{int(settlement_state.get('stored_stone', 0) or 0)}",
            )
        ]
        if active_tab == "evolution":
            evo = dict((getattr(advisor, "session_stats", {}) or {}).get("current_evolution_summary", {}) or {})
            sections = [
                _section(
                    "Evolution",
                    f"Average Generation  {float(evo.get('avg_generation', 0.0) or 0.0):.1f}",
                    f"Max Generation  {int(evo.get('max_generation', 0) or 0)}",
                    f"Founder Lines  {int(evo.get('founder_lines', 0) or 0)}",
                    f"Dominant Lineage  L{evo.get('dominant_lineage', '?')}",
                )
            ]
        elif active_tab == "risks":
            sections = [
                _section(
                    "Risks",
                    f"Challenges Active  {len(getattr(advisor, 'active_challenges', []) or [])}",
                    f"Deaths Recorded  {int(getattr(advisor, 'total_deaths', 0) or 0)}",
                    f"Research Points  {int(getattr(advisor, 'research_points', 0) or 0)}",
                )
            ]
        return InspectViewModel(
            title="Settlement",
            subtitle="Colony state and observer context",
            entity_type="settlement",
            accent=(153, 194, 196),
            tabs=tabs,
            active_tab=active_tab if active_tab in {tab_id for tab_id, _ in tabs} else "overview",
            sections=sections,
        )

    if selected_type == "thronglet":
        thronglet = selected_entity
        tabs = [("overview", "Overview"), ("traits", "Traits"), ("social", "Social")]
        active_tab = active_tab if active_tab in {tab_id for tab_id, _ in tabs} else "overview"
        subtitle = f"#{thronglet.id}  |  {str(getattr(thronglet, 'role', 'unassigned')).replace('_', ' ').title()}"
        if active_tab == "traits":
            sections = [
                _section(
                    "Genetics",
                    *[
                        f"{str(trait_name).replace('_', ' ').title()}  {float(trait_value):.2f}x"
                        for trait_name, trait_value in list(getattr(thronglet, "genetics", {}).items())[:8]
                    ],
                ),
                _section(
                    "Skills",
                    *[
                        f"{str(skill_name).replace('_', ' ').title()}  L{int(skill_data.get('level', 1) or 1)}"
                        for skill_name, skill_data in getattr(thronglet, "skills", {}).items()
                        if isinstance(skill_data, dict)
                    ],
                ),
            ]
        elif active_tab == "social":
            faction_lines = []
            faction_id = getattr(thronglet, "faction_id", None)
            if faction_manager is not None and faction_id is not None:
                faction = getattr(faction_manager, "factions", {}).get(faction_id)
                if faction is not None:
                    faction_lines = [
                        f"Faction  F{int(faction_id)}",
                        f"Doctrine  {str(getattr(faction, 'primary_doctrine', 'survival')).title()}",
                        f"Cohesion  {int(float(getattr(faction, 'cohesion', 0.0) or 0.0) * 100)}%",
                        f"Schism Pressure  {int(getattr(faction, 'schism_pressure', 0) or 0)}",
                        f"Migration Pressure  {int(getattr(faction, 'migration_pressure', 0) or 0)}",
                        f"Members  {len(getattr(faction, 'member_ids', []))}",
                        f"Rivals  {len(getattr(faction, 'rival_faction_ids', []))}",
                    ]
            sections = [
                _section(
                    "Lineage",
                    f"Generation  {int(getattr(thronglet, 'generation', 0) or 0)}",
                    f"Lineage  L{int(getattr(thronglet, 'lineage_id', getattr(thronglet, 'id', 0)))}",
                    f"Parents  {', '.join(str(parent_id) for parent_id in getattr(thronglet, 'parent_ids', [])[:2]) or 'Founder'}",
                    f"Mutations  {int(getattr(thronglet, 'mutation_count', 0) or 0)}",
                ),
                _section("Faction", *faction_lines) if faction_lines else _section("Faction", "Unaffiliated"),
            ]
        else:
            sections = [
                _section(
                    "Vitals",
                    f"Health  {int(getattr(thronglet, 'health', 0) or 0)}/100",
                    f"Hunger  {int(getattr(thronglet, 'hunger', 0) or 0)}/100",
                    f"Energy  {int(getattr(thronglet, 'needs', {}).get('energy', 0) or 0)}/100",
                    f"Thirst  {int(getattr(thronglet, 'needs', {}).get('thirst', 0) or 0)}/100",
                    f"Happiness  {int(getattr(thronglet, 'happiness', 0) or 0)}/100",
                    f"Morale  {int(getattr(thronglet, 'morale', 0) or 0)}/100",
                    f"Inspiration  {int(getattr(thronglet, 'inspiration', 0) or 0)}/100",
                ),
                _section(
                    "Activity",
                    f"Current Task  {str(getattr(thronglet, 'current_action', 'idle')).replace('_', ' ').title()}",
                    f"Favorite Biome  {str(getattr(thronglet, 'favorite_biome', 'plains')).title()}",
                    f"Diseased  {'Yes' if bool(getattr(thronglet, 'diseased', False)) else 'No'}",
                    f"Can Reproduce  {'Yes' if hasattr(thronglet, 'can_reproduce') and thronglet.can_reproduce() else 'No'}",
                    f"Age  {int(max(0.0, current_time - float(getattr(thronglet, 'birth_time', current_time) or current_time)))}s",
                ),
            ]
        return InspectViewModel(
            title="Thronglet",
            subtitle=subtitle,
            entity_type="thronglet",
            accent=(187, 147, 88),
            tabs=tabs,
            active_tab=active_tab,
            sections=sections,
        )

    if selected_type == "building":
        building = selected_entity
        tabs = [("overview", "Overview"), ("economy", "Stores")]
        active_tab = active_tab if active_tab in {tab_id for tab_id, _ in tabs} else "overview"
        stored_resources = dict(getattr(building, "stored_resources", {}) or {})
        if active_tab == "economy":
            sections = [_section("Stores", *[f"{name.title()}  {int(value)}" for name, value in stored_resources.items()])]
        else:
            sections = [
                _section(
                    "Building",
                    f"Type  {str(getattr(building, 'building_type', 'structure')).title()}",
                    f"Level  {int(getattr(building, 'level', 1) or 1)}",
                    f"Built By  #{getattr(building, 'built_by', 'Unknown')}",
                    f"Occupants  {len(getattr(building, 'occupants', []))}",
                )
            ]
        return InspectViewModel(
            title=str(getattr(building, "building_type", "Building")).title(),
            subtitle="Structure and operational status",
            entity_type="building",
            accent=(166, 181, 116),
            tabs=tabs,
            active_tab=active_tab,
            sections=sections,
        )

    if selected_type == "resource":
        resource = selected_entity
        sections = [
            _section(
                "Resource",
                f"Type  {str(getattr(resource, 'resource_type', 'resource')).title()}",
                f"Status  {'Respawning' if getattr(resource, 'collected', False) else 'Available'}",
            )
        ]
        return InspectViewModel(
            title=f"{str(getattr(resource, 'resource_type', 'resource')).title()} Resource",
            subtitle="Map resource node",
            entity_type="resource",
            accent=(153, 194, 196),
            tabs=[("overview", "Overview")],
            active_tab="overview",
            sections=sections,
        )

    subject_name = selected_type.replace("_", " ").title()
    sections = [
        _section(
            subject_name,
            f"Type  {subject_name}",
            f"X  {round(float(getattr(selected_entity, 'x', 0.0)), 1)}",
            f"Y  {round(float(getattr(selected_entity, 'y', 0.0)), 1)}",
        )
    ]
    return InspectViewModel(
        title=subject_name,
        subtitle="Observed world entity",
        entity_type=selected_type,
        accent=(171, 110, 79),
        tabs=[("overview", "Overview")],
        active_tab="overview",
        sections=sections,
    )


def draw_inspect_drawer(surface: pygame.Surface, theme, layout, registry, model: InspectViewModel, scroll_offset: int = 0) -> None:
    rect = layout.inspect_drawer
    draw_panel(surface, rect, theme, fill=(21, 26, 28), alpha=230, radius=theme.radius_large)
    registry.register("inspect_drawer", rect, layer=5, scrollable=True)
    surface.blit(theme.fonts.heading.render(model.title, True, theme.palette.parchment), (rect.x + 18, rect.y + 14))
    surface.blit(theme.fonts.caption.render(model.subtitle, True, theme.palette.parchment_soft), (rect.x + 18, rect.y + 42))

    tab_x = rect.x + 18
    tab_y = rect.y + 72
    for tab_id, label in model.tabs:
        tab_rect = pygame.Rect(tab_x, tab_y, max(82, theme.fonts.caption.size(label)[0] + 24), 28)
        registry.register(f"inspect_tab:{tab_id}", tab_rect, action="inspect_tab", payload=tab_id, layer=6)
        draw_button(surface, tab_rect, theme, label, active=tab_id == model.active_tab, accent=model.accent, subtle=True)
        tab_x += tab_rect.w + 8
    draw_divider(surface, theme, (rect.x + 18, tab_y + 40), (rect.right - 18, tab_y + 40))

    clip_rect = pygame.Rect(rect.x + 12, tab_y + 50, rect.w - 24, rect.h - (tab_y - rect.y) - 64)
    content = pygame.Surface((clip_rect.w, max(clip_rect.h, 600)), pygame.SRCALPHA)
    y = 8 - max(0, scroll_offset)
    for section in model.sections:
        content.blit(theme.fonts.label.render(section.title, True, model.accent), (8, y))
        y += 26
        for line in section.lines:
            for wrapped in wrap_text(theme.fonts.caption, line, clip_rect.w - 24):
                content.blit(theme.fonts.caption.render(wrapped, True, theme.palette.bright_text), (16, y))
                y += 18
        y += 16
        pygame.draw.line(content, theme.palette.panel_border, (8, y), (clip_rect.w - 8, y), 1)
        y += 14
    surface.set_clip(clip_rect)
    surface.blit(content, clip_rect.topleft)
    surface.set_clip(None)
    footer = theme.fonts.caption.render("Mouse wheel scrolls the drawer", True, theme.palette.muted_text)
    surface.blit(footer, (rect.x + 18, rect.bottom - 24))
