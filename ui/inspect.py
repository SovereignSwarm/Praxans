from __future__ import annotations

import pygame
import time

from ui.models import InspectCommand, InspectSection, InspectViewModel, NeedBar
from ui.theme import draw_button, draw_divider, draw_panel, wrap_text
from game_content import JOB_DEFS


def _section(title: str, *lines: str) -> InspectSection:
    return InspectSection(title=title, lines=[line for line in lines if str(line).strip()])


def _need_bar(label: str, value: float, max_val: float = 100.0, color: tuple[int, int, int] | None = None) -> NeedBar:
    """Create a need bar with auto-color based on value if no explicit color."""
    if color is None:
        ratio = max(0.0, min(1.0, value / max(1.0, max_val)))
        if ratio > 0.6:
            color = (80, 180, 90)   # Green
        elif ratio > 0.3:
            color = (200, 180, 60)  # Yellow
        else:
            color = (200, 70, 60)   # Red
    return NeedBar(label=label, value=value, max_value=max_val, color=color)


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

    if selected_type == "praxan":
        praxan = selected_entity
        tabs = [("overview", "Overview"), ("needs", "Needs"), ("health", "Health"), ("traits", "Traits"), ("social", "Social")]
        active_tab = active_tab if active_tab in {tab_id for tab_id, _ in tabs} else "overview"
        subtitle = f"#{praxan.id}  |  {str(getattr(praxan, 'role', 'unassigned')).replace('_', ' ').title()}"

        # Commands always available for praxans
        commands = [
            InspectCommand(id="force_rest", label="Force Rest", action="force_rest", payload=praxan.id),
            InspectCommand(id="force_haul", label="Prioritize Haul", action="force_haul", payload=praxan.id),
        ]

        if active_tab == "needs":
            # Mood breakdown tab
            needs = getattr(praxan, "needs", {})
            need_bars = [
                _need_bar("Hunger", float(needs.get("hunger", 0))),
                _need_bar("Energy", float(needs.get("energy", 0))),
                _need_bar("Thirst", float(needs.get("thirst", 0))),
                _need_bar("Beauty", float(needs.get("beauty", 50))),
                _need_bar("Comfort", float(needs.get("comfort", 50))),
                _need_bar("Social", float(needs.get("social", 50))),
                _need_bar("Outdoors", float(needs.get("outdoors", 50))),
            ]
            # Build moodlet lines
            base_mood = float(getattr(praxan, "base_mood", 50))
            happiness = float(getattr(praxan, "happiness", 50))
            moodlets = list(getattr(praxan, "moodlets", []) or [])
            mood_lines = [f"Base Mood  {int(base_mood)}"]
            for m in moodlets[:8]:
                val = float(m.get("value", 0))
                sign = "+" if val >= 0 else ""
                mood_lines.append(f"  {sign}{int(val)}  {m.get('name', '?')}")
            mood_lines.append(f"Final Happiness  {int(happiness)}")
            mental = getattr(praxan, "mental_state", None)
            if mental:
                mood_lines.append(f"⚠ Mental State  {str(mental).replace('_', ' ').title()}")
            sections = [_section("Mood Breakdown", *mood_lines)]
            return InspectViewModel(
                title="Praxan", subtitle=subtitle, entity_type="praxan",
                accent=(187, 147, 88), tabs=tabs, active_tab=active_tab,
                sections=sections, need_bars=need_bars, commands=commands,
            )

        elif active_tab == "health":
            # Body parts and hediffs
            body_parts = dict(getattr(praxan, "body_parts", {}))
            hediffs = list(getattr(praxan, "hediffs", []))
            pain = float(getattr(praxan, "pain", 0))
            caps = dict(getattr(praxan, "capacities", {}))

            need_bars = []
            for part_name, part_data in body_parts.items():
                hp = float(part_data.get("health", 0))
                max_hp = float(part_data.get("max", 100))
                status = part_data.get("status", "intact")
                label = f"{part_name.replace('_', ' ').title()} [{status}]"
                color = (80, 180, 90) if status == "intact" else (200, 100, 60)
                need_bars.append(_need_bar(label, hp, max_hp, color))

            hediff_lines = []
            if hediffs:
                for h in hediffs[:6]:
                    sev = f"Sev {float(h.get('severity', 0)):.1f}"
                    tended = "✓ Tended" if h.get("tended") else "✗ Untended"
                    hediff_lines.append(f"  {h.get('type', '?')} on {h.get('part', '?')}  {sev}  {tended}")
            else:
                hediff_lines.append("  No active conditions")

            cap_lines = [f"  {cap.replace('_', ' ').title()}  {int(float(val) * 100)}%" for cap, val in caps.items()]

            sections = [
                _section("Pain", f"Pain Level  {int(pain * 100)}%"),
                _section("Conditions", *hediff_lines),
                _section("Capacities", *cap_lines),
            ]
            return InspectViewModel(
                title="Praxan", subtitle=subtitle, entity_type="praxan",
                accent=(187, 147, 88), tabs=tabs, active_tab=active_tab,
                sections=sections, need_bars=need_bars, commands=commands,
            )

        elif active_tab == "traits":
            sections = [
                _section(
                    "Genetics",
                    *[
                        f"{str(trait_name).replace('_', ' ').title()}  {float(trait_value):.2f}x"
                        for trait_name, trait_value in list(getattr(praxan, "genetics", {}).items())[:8]
                    ],
                ),
                _section(
                    "Deep Traits",
                    *[str(t) for t in getattr(praxan, "traits", [])],
                ),
                _section(
                    "Skills",
                    *[
                        f"{str(skill_name).replace('_', ' ').title()}  L{int(skill_data.get('level', 1) or 1)}"
                        for skill_name, skill_data in getattr(praxan, "skills", {}).items()
                        if isinstance(skill_data, dict)
                    ],
                ),
            ]
            return InspectViewModel(
                title="Praxan", subtitle=subtitle, entity_type="praxan",
                accent=(187, 147, 88), tabs=tabs, active_tab=active_tab,
                sections=sections, commands=commands,
            )

        elif active_tab == "social":
            faction_lines = []
            faction_id = getattr(praxan, "faction_id", None)
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

            # Opinions
            opinions = dict(getattr(praxan, "opinions", {}))
            opinion_lines = []
            for pid, score in sorted(opinions.items(), key=lambda x: -abs(x[1]))[:5]:
                sign = "+" if score >= 0 else ""
                label = getattr(praxan, "get_relationship_label", lambda x: "Known")(pid)
                opinion_lines.append(f"  P#{pid}  {sign}{int(score)} ({label})")

            # Social Needs
            needs = getattr(praxan, "needs", {})
            need_bars = [
                _need_bar("Social", float(needs.get("social", 100))),
                _need_bar("Comfort", float(needs.get("comfort", 100))),
                _need_bar("Beauty", float(needs.get("beauty", 100))),
            ]

            sections = [
                _section(
                    "Lineage",
                    f"Generation  {int(getattr(praxan, 'generation', 0) or 0)}",
                    f"Lineage  L{int(getattr(praxan, 'lineage_id', getattr(praxan, 'id', 0)))}",
                    f"Parents  {', '.join(str(parent_id) for parent_id in getattr(praxan, 'parent_ids', [])[:2]) or 'Founder'}",
                    f"Mutations  {int(getattr(praxan, 'mutation_count', 0) or 0)}",
                ),
                _section("Faction", *faction_lines) if faction_lines else _section("Faction", "Unaffiliated"),
                _section("Relationships", *opinion_lines) if opinion_lines else _section("Relationships", "  No strong opinions"),
            ]
            return InspectViewModel(
                title="Praxan", subtitle=subtitle, entity_type="praxan",
                accent=(187, 147, 88), tabs=tabs, active_tab=active_tab,
                sections=sections, need_bars=need_bars, commands=commands,
            )

        else:
            # Overview — use bars for vitals
            needs = getattr(praxan, "needs", {})
            need_bars = [
                _need_bar("Health", float(getattr(praxan, "health", 0))),
                _need_bar("Hunger", float(needs.get("hunger", 0))),
                _need_bar("Energy", float(needs.get("energy", 0))),
                _need_bar("Thirst", float(needs.get("thirst", 0))),
                _need_bar("Happiness", float(getattr(praxan, "happiness", 0))),
                _need_bar("Morale", float(getattr(praxan, "morale", 0))),
            ]
            sections = [
                _section(
                    "Activity",
                    f"Current Task  {str(getattr(praxan, 'current_action', 'idle')).replace('_', ' ').title()}",
                    f"Favorite Biome  {str(getattr(praxan, 'favorite_biome', 'plains')).title()}",
                    f"Diseased  {'Yes' if bool(getattr(praxan, 'diseased', False)) else 'No'}",
                    f"Can Reproduce  {'Yes' if hasattr(praxan, 'can_reproduce') and praxan.can_reproduce() else 'No'}",
                    f"Age  {int(max(0.0, current_time - float(getattr(praxan, 'birth_time', current_time) or current_time)))}s",
                ),
            ]
            return InspectViewModel(
                title="Praxan", subtitle=subtitle, entity_type="praxan",
                accent=(187, 147, 88), tabs=tabs, active_tab=active_tab,
                sections=sections, need_bars=need_bars, commands=commands,
            )

    if selected_type == "building":
        building = selected_entity
        tabs = [("overview", "Overview"), ("economy", "Stores")]
        
        # Add Production tab for crafting stations
        if getattr(building, 'building_type', '') in ['farm', 'workshop']:
            tabs.append(("production", "Production"))
            
        active_tab = active_tab if active_tab in {tab_id for tab_id, _ in tabs} else "overview"
        stored_resources = dict(getattr(building, "stored_resources", {}) or {})
        commands = [
            InspectCommand(id="deconstruct", label="Deconstruct", action="deconstruct_building", payload=building),
        ]
        
        if active_tab == "economy":
            sections = [_section("Stores", *[f"{name.title()}  {int(value)}" for name, value in stored_resources.items()])]
        elif active_tab == "production":
            bills = getattr(building, 'bills', [])
            bill_lines = []
            if bills:
                for idx, bill_id in enumerate(bills):
                    job = JOB_DEFS.get(bill_id, {})
                    label = bill_id.replace('Craft', '').replace('Smith', '').replace('Cook', '')
                    bill_lines.append(f"{idx+1}. {label} ({job.get('skill_factor', 'unknown').title()})")
            else:
                bill_lines.append("No active bills")
                
            sections = [_section("Bills Queue", *bill_lines)]
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
            commands=commands,
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


def _draw_need_bar(surface: pygame.Surface, theme, x: int, y: int, width: int, bar: NeedBar) -> int:
    """Draw a single need bar. Returns the height consumed."""
    bar_h = 14
    label_surf = theme.fonts.caption.render(bar.label, True, theme.palette.bright_text)
    surface.blit(label_surf, (x, y))

    val_text = theme.fonts.caption.render(f"{int(bar.value)}", True, theme.palette.muted_text)
    surface.blit(val_text, (x + width - val_text.get_width(), y))

    bar_y = y + label_surf.get_height() + 2
    bg_rect = pygame.Rect(x, bar_y, width, bar_h)
    pygame.draw.rect(surface, (35, 40, 42), bg_rect, border_radius=3)

    ratio = max(0.0, min(1.0, bar.value / max(1.0, bar.max_value)))
    fill_w = int(width * ratio)
    if fill_w > 0:
        fill_rect = pygame.Rect(x, bar_y, fill_w, bar_h)
        pygame.draw.rect(surface, bar.color, fill_rect, border_radius=3)

    return label_surf.get_height() + bar_h + 6


def draw_inspect_drawer(surface: pygame.Surface, theme, layout, registry, model: InspectViewModel, scroll_offset: int = 0) -> None:
    rect = layout.inspect_drawer
    draw_panel(surface, rect, theme, fill=(21, 26, 28), alpha=230, radius=theme.radius_large)
    registry.register("inspect_drawer", rect, layer=5, scrollable=True)
    surface.blit(theme.fonts.heading.render(model.title, True, theme.palette.parchment), (rect.x + 18, rect.y + 14))
    surface.blit(theme.fonts.caption.render(model.subtitle, True, theme.palette.parchment_soft), (rect.x + 18, rect.y + 42))

    tab_x = rect.x + 18
    tab_y = rect.y + 72
    for tab_id, label in model.tabs:
        tab_rect = pygame.Rect(tab_x, tab_y, max(58, theme.fonts.caption.size(label)[0] + 16), 26)
        registry.register(f"inspect_tab:{tab_id}", tab_rect, action="inspect_tab", payload=tab_id, layer=6)
        draw_button(surface, tab_rect, theme, label, active=tab_id == model.active_tab, accent=model.accent, subtle=True)
        tab_x += tab_rect.w + 4
    draw_divider(surface, theme, (rect.x + 18, tab_y + 36), (rect.right - 18, tab_y + 36))

    clip_rect = pygame.Rect(rect.x + 12, tab_y + 44, rect.w - 24, rect.h - (tab_y - rect.y) - 70)
    content = pygame.Surface((clip_rect.w, max(clip_rect.h, 1200)), pygame.SRCALPHA)
    y = 8 - max(0, scroll_offset)

    # Draw need bars first
    if model.need_bars:
        for bar in model.need_bars:
            h = _draw_need_bar(content, theme, 8, y, clip_rect.w - 16, bar)
            y += h
        y += 6
        pygame.draw.line(content, theme.palette.panel_border, (8, y), (clip_rect.w - 8, y), 1)
        y += 10

    # Draw text sections
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

    # Draw command buttons at the bottom
    if model.commands:
        cmd_y = rect.bottom - 50
        cmd_x = rect.x + 18
        for cmd in model.commands:
            cmd_w = max(90, theme.fonts.caption.size(cmd.label)[0] + 20)
            cmd_rect = pygame.Rect(cmd_x, cmd_y, cmd_w, 28)
            registry.register(f"inspect_cmd:{cmd.id}", cmd_rect, action=cmd.action, payload=cmd.payload, layer=7)
            draw_button(surface, cmd_rect, theme, cmd.label, accent=theme.palette.copper, subtle=True)
            cmd_x += cmd_w + 8

    footer = theme.fonts.caption.render("Mouse wheel scrolls", True, theme.palette.muted_text)
    surface.blit(footer, (rect.x + 18, rect.bottom - 20))
