import pygame
import pygame.gfxdraw
import math
from datetime import datetime
from thronglets_game import *
from ui.theme import wrap_text

class InfoPanel:
    """Displays detailed information about selected entity"""
    def __init__(self):
        self.panel_x = WINDOW_WIDTH - 320
        self.panel_y = 180  # Moved up to avoid minimap
        self.panel_w = 300
        self.panel_h = 480
    
    def draw(self, surface, selected_entity, selected_type, advisor=None, current_time=0):
        """Draw info panel for selected entity"""
        if not selected_entity or not selected_type:
            return
        
        # Create panel surface
        panel = pygame.Surface((self.panel_w, self.panel_h))
        panel.set_alpha(230)
        panel.fill((30, 30, 50))
        surface.blit(panel, (self.panel_x, self.panel_y))
        
        # Draw border
        pygame.draw.rect(surface, (100, 150, 200), (self.panel_x, self.panel_y, self.panel_w, self.panel_h), 2)
        
        # Title
        title_text = font_small.render("SELECTED ENTITY", True, (150, 200, 255))
        surface.blit(title_text, (self.panel_x + 10, self.panel_y + 10))
        
        y_offset = 40
        
        if selected_type == 'thronglet':
            thronglet = selected_entity
            role_name = thronglet.role.title() if thronglet.role else "Unassigned"
            # Detailed stats
            stats = [
                f"ID: {thronglet.id}",
                f"Role: {role_name}",
                f"Health: {int(thronglet.health)}/100",
                f"Age: {int(current_time - thronglet.birth_time)}s",
                f"Generation: {getattr(thronglet, 'generation', 0)}",
                f"Lineage: L{getattr(thronglet, 'lineage_id', thronglet.id)}",
                "",
                "Needs:",
                f"  Hunger: {int(thronglet.needs['hunger'])}/100",
                f"  Energy: {int(thronglet.needs['energy'])}/100",
                f"  Thirst: {int(thronglet.needs['thirst'])}/100",
                "",
                "Status:",
                f"  Happiness: {int(thronglet.happiness)}/100",
                f"  Morale: {int(getattr(thronglet, 'morale', 0))}/100",
                f"  Inspiration: {int(getattr(thronglet, 'inspiration', 0))}/100",
                f"  Favorite Biome: {getattr(thronglet, 'favorite_biome', 'plains').title()}",
                f"  Disease: {'Yes' if thronglet.diseased else 'No'}",
                f"  Can Reproduce: {'Yes' if thronglet.can_reproduce() else 'No'}",
                f"  Mutations: {int(getattr(thronglet, 'mutation_count', 0))}",
            ]

            if getattr(thronglet, "parent_ids", None):
                stats.append(f"Parents: {', '.join(str(parent_id) for parent_id in thronglet.parent_ids[:2])}")

            stats.extend(
                [
                    "",
                    "Genetics:",
                ]
            )
            stats.extend(build_trait_display_lines(thronglet.genetics))
            
            # Add skills if they exist
            skill_key = get_role_skill_key(thronglet.role)
            if skill_key and skill_key in thronglet.skills:
                skill_level = thronglet.skills[skill_key]['level']
                stats.append(f"Skill Level: {skill_level}")
                
                # Show specific bonuses
                if thronglet.role == 'gatherer':
                    bonus = int((thronglet.get_gathering_bonus() - 1.0) * 100)
                    stats.append(f"  Gather Speed: +{bonus}%")
                elif thronglet.role == 'builder':
                    bonus = int((thronglet.get_building_bonus() - 1.0) * 100)
                    stats.append(f"  Build Discount: {bonus}%")
                elif thronglet.role == 'explorer':
                    bonus = int((thronglet.get_exploration_bonus() - 1.0) * 100)
                    stats.append(f"  Exploration: +{bonus}%")
            
            # Add bonds
            if thronglet.bonds:
                stats.append(f"Bonds: {len(thronglet.bonds)}")
            
            # Add current task
            if thronglet.current_action:
                stats.append(f"Task: {thronglet.current_action}")
            
            # Add inventory
            if sum(thronglet.inventory.values()) > 0:
                inv_str = ", ".join([f"{k}:{v}" for k, v in thronglet.inventory.items() if v > 0])
                stats.append(f"Inventory: {inv_str}")
            
        elif selected_type == 'building':
            building = selected_entity
            stats = [
                f"Type: {building.building_type.title()}",
                f"Level: {getattr(building, 'level', 1)}",
                f"Built by: Thronglet #{building.built_by}" if building.built_by is not None else "Built by: Unknown",
            ]
            
            if building.building_type == 'house':
                stats.extend([
                    f"Occupants: {len(building.occupants)}/2",
                    f"Capacity: {int(2 * (advisor.game_modifiers.get_modifier('house_capacity') if advisor and advisor.game_modifiers else 1.0))}"
                ])
            elif building.stored_resources:
                stored = building.stored_resources
                if sum(stored.values()) > 0:
                    stored_lines = [f"  {k.title()}: {int(v)}" for k, v in stored.items() if v > 0]
                    stats.append("Stored Resources:")
                    stats.extend(stored_lines)
                else:
                    stats.append("Stored: Empty")
        
        elif selected_type == 'resource':
            resource = selected_entity
            stats = [
                f"Type: {resource.resource_type.title()}",
                f"Status: {'Respawning' if resource.collected else 'Available'}",
            ]
            if resource.collected:
                stats.append(f"Respawn in: {int(RESOURCE_RESPAWN_TIME - (current_time - resource.collect_time))}s")
        
        elif selected_type == 'encounter':
            encounter = selected_entity
            encounter_names = {
                'ruins': 'Ancient Ruins',
                'mineral_vein': 'Mineral Vein',
                'oasis': 'Oasis',
                'sacred_grove': 'Sacred Grove'
            }
            stats = [
                f"Type: {encounter_names.get(encounter.encounter_type, 'Unknown')}",
                f"Discovered: {'Yes' if encounter.discovered else 'No'}",
                f"Explored: {'Yes' if encounter.explored else 'No'}",
            ]
        
        elif selected_type == 'hazard':
            hazard = selected_entity
            hazard_names = {
                'quicksand': 'Quicksand',
                'avalanche_zone': 'Avalanche Zone',
                'flood_zone': 'Flood Zone',
                'predator_lair': 'Predator Lair'
            }
            stats = [
                f"Type: {hazard_names.get(hazard.hazard_type, 'Hazard')}",
                f"Active: {'Yes' if hazard.active else 'No'}",
                f"Radius: {hazard.radius}",
                f"Damage Rate: {hazard.damage_rate}/s",
            ]
        
        elif selected_type == 'npc':
            npc = selected_entity
            npc_names = {
                'trader': 'Trader',
                'rival_tribe': 'Rival Tribe',
                'wildlife_herd': 'Wildlife Herd'
            }
            stats = [
                f"Type: {npc_names.get(npc.npc_type, 'NPC')}",
                f"Hostile: {'Yes' if npc.hostile else 'No'}",
            ]
            if npc.inventory and sum(npc.inventory.values()) > 0:
                stats.append("Inventory:")
                for k, v in npc.inventory.items():
                    if v > 0:
                        stats.append(f"  {k.title()}: {v}")
        
        # Draw stats
        for line in stats:
            if line.strip() == "":
                y_offset += 5
                continue
            text = font_small.render(line, True, WHITE)
            # Truncate if too long
            if text.get_width() > self.panel_w - 20:
                # Truncate text
                truncated = line[:35] + "..."
                text = font_small.render(truncated, True, WHITE)
            surface.blit(text, (self.panel_x + 10, self.panel_y + y_offset))
            y_offset += 20


class EvolutionStatsPanel:
    """Observer-facing panel for lineage and trait drift."""

    def __init__(self):
        self.panel_w = 560
        self.panel_h = 440

    def draw(self, surface, thronglets, advisor, current_time):
        panel_x = WINDOW_WIDTH // 2 - self.panel_w // 2
        panel_y = WINDOW_HEIGHT // 2 - self.panel_h // 2
        panel = pygame.Surface((self.panel_w, self.panel_h))
        panel.set_alpha(238)
        panel.fill((24, 24, 42))
        surface.blit(panel, (panel_x, panel_y))
        pygame.draw.rect(surface, (120, 160, 215), (panel_x, panel_y, self.panel_w, self.panel_h), 3)

        title = font.render("EVOLUTION OBSERVER", True, (220, 230, 255))
        surface.blit(title, (panel_x + 20, panel_y + 16))

        summary = advisor.session_stats.get("current_evolution_summary") or summarize_population_evolution(thronglets)
        line_y = panel_y + 62
        overview_lines = [
            f"Population: {summary['population']}  |  Avg generation: {summary['avg_generation']:.1f}  |  Max generation: {summary['max_generation']}",
            f"Founder lines: {summary['founder_lines']}  |  Dominant line: L{summary['dominant_lineage']} ({summary['dominant_lineage_size']})",
            f"Dominant biome affinity: {summary['dominant_biome'].title()}  |  Total mutations: {summary['total_mutations']}",
            f"Births: {advisor.session_stats.get('births_total', 0)}  |  Deaths: {advisor.total_deaths}",
        ]
        for line in overview_lines:
            surface.blit(font_small.render(line[:70], True, WHITE), (panel_x + 20, line_y))
            line_y += 24

        trait_title = font_small.render("Population Trait Drift", True, (160, 220, 255))
        surface.blit(trait_title, (panel_x + 20, line_y + 8))
        line_y += 36
        for trait_name, trait_spec in GENETIC_TRAIT_SPECS.items():
            avg_value = summary["avg_traits"].get(trait_name, 1.0)
            bar_x = panel_x + 20
            bar_y = line_y
            bar_w = 220
            bar_h = 16
            pygame.draw.rect(surface, (55, 60, 82), (bar_x, bar_y, bar_w, bar_h))
            normalized = clamp((avg_value - trait_spec["min"]) / (trait_spec["max"] - trait_spec["min"]), 0.0, 1.0)
            fill_w = max(2, int(bar_w * normalized))
            bar_color = (120, 200, 255) if trait_name != summary["trait_drift"] else (255, 215, 120)
            pygame.draw.rect(surface, bar_color, (bar_x, bar_y, fill_w, bar_h))
            label = f"{trait_spec['label']}: {format_genetic_trait_delta(avg_value)}"
            surface.blit(font_small.render(label, True, WHITE), (bar_x + bar_w + 14, bar_y - 2))
            line_y += 26

        history_title = font_small.render("Recent Evolution Events", True, (255, 220, 170))
        surface.blit(history_title, (panel_x + 20, line_y + 6))
        line_y += 32
        lineage_events = advisor.session_stats.get("lineage_events", [])
        for event in lineage_events[-6:]:
            event_age = max(0.0, current_time - event.get("time", current_time))
            event_text = f"{event.get('label', 'event')} ({event_age:.0f}s ago)"
            surface.blit(font_small.render(event_text[:72], True, (220, 220, 220)), (panel_x + 20, line_y))
            line_y += 22

        trend_x = panel_x + 310
        trend_y = panel_y + 220
        trend_title = font_small.render("Generation Trend", True, (200, 255, 200))
        surface.blit(trend_title, (trend_x, trend_y))
        history = advisor.session_stats.get("evolution_history", [])
        trend_y += 24
        for sample in history[-6:]:
            trend_text = (
                f"t+{int(sample.get('elapsed_seconds', 0))}s  gen {sample.get('avg_generation', 0):.1f}"
                f"  pop {sample.get('population', 0)}  lines {sample.get('founder_lines', 0)}"
            )
            surface.blit(font_small.render(trend_text[:34], True, (210, 210, 235)), (trend_x, trend_y))
            trend_y += 20

        close_hint = font_small.render("[S] to close", True, (180, 200, 230))
        surface.blit(close_hint, (panel_x + self.panel_w - 100, panel_y + self.panel_h - 28))


class ObserverAnalyticsPanel:
    """Observer-facing colony analytics for lineage, mortality, and faction history."""

    def draw(self, surface, thronglets, advisor, current_time, faction_manager=None):
        panel_w = min(860, WINDOW_WIDTH - 40)
        panel_h = min(560, WINDOW_HEIGHT - 70)
        panel_x = max(20, WINDOW_WIDTH // 2 - panel_w // 2)
        panel_y = max(20, WINDOW_HEIGHT // 2 - panel_h // 2)

        panel = pygame.Surface((panel_w, panel_h))
        panel.set_alpha(240)
        panel.fill((20, 24, 38))
        surface.blit(panel, (panel_x, panel_y))
        pygame.draw.rect(surface, (120, 160, 215), (panel_x, panel_y, panel_w, panel_h), 3)

        report = build_observer_report(thronglets, advisor, faction_manager)
        scenario_name = advisor.session_stats.get("scenario_name", ACTIVE_SCENARIO_PROFILE.get("name", "Standard Basin"))
        title = font.render("OBSERVER ANALYTICS", True, (220, 230, 255))
        subtitle = font_small.render(f"{scenario_name}  |  Timeline, mortality, and faction drift", True, (170, 210, 255))
        surface.blit(title, (panel_x + 20, panel_y + 14))
        surface.blit(subtitle, (panel_x + 20, panel_y + 42))

        summary_y = panel_y + 72
        summary_lines = [
            f"Population: {report['population']}  |  Peak: {report['max_population']}  |  Births: {report['births_total']}  |  Deaths: {report['deaths_total']}",
            f"Avg survival: {report['avg_survival_time']:.1f}s  |  Factions: {len(report['active_factions'])} active / {report['peak_factions']} peak",
            f"Faction churn: +{report['factions_formed']} / -{report['factions_dissolved']} / split {report['faction_schisms']} / succession {report['faction_successions']}",
            f"Migration events: {report['migration_events']}  |  Group tasks: {report['active_group_tasks']}",
        ]
        for summary_line in summary_lines:
            surface.blit(font_small.render(summary_line[:92], True, WHITE), (panel_x + 20, summary_y))
            summary_y += 22

        box_y = summary_y + 8
        box_gap = 16
        box_w = (panel_w - 40 - box_gap * 2) // 3
        box_h = 168

        def draw_box(title_text, box_x, box_y, box_w, box_h):
            pygame.draw.rect(surface, (36, 42, 60), (box_x, box_y, box_w, box_h))
            pygame.draw.rect(surface, (90, 120, 170), (box_x, box_y, box_w, box_h), 2)
            title_surface = font_small.render(title_text, True, (210, 225, 255))
            surface.blit(title_surface, (box_x + 12, box_y + 10))
            return box_y + 36

        lineage_x = panel_x + 20
        mortality_x = lineage_x + box_w + box_gap
        faction_x = mortality_x + box_w + box_gap

        line_y = draw_box("Dominant Lineages", lineage_x, box_y, box_w, box_h)
        top_lineages = report["top_lineages"]
        if top_lineages:
            max_lineage_count = max(lineage["count"] for lineage in top_lineages)
            for lineage in top_lineages:
                label = f"L{lineage['lineage_id']}  {lineage['count']}  ({int(lineage['share'] * 100)}%)"
                surface.blit(font_small.render(label, True, (230, 215, 170)), (lineage_x + 12, line_y))
                bar_y = line_y + 16
                pygame.draw.rect(surface, (55, 62, 86), (lineage_x + 12, bar_y, box_w - 24, 10))
                fill_w = int((box_w - 24) * (lineage["count"] / max(1, max_lineage_count)))
                pygame.draw.rect(surface, (255, 205, 120), (lineage_x + 12, bar_y, max(4, fill_w), 10))
                line_y += 28
        else:
            surface.blit(font_small.render("No lineage divergence yet.", True, (180, 190, 215)), (lineage_x + 12, line_y))

        mortality_y = draw_box("Mortality Breakdown", mortality_x, box_y, box_w, box_h)
        if report["mortality"]:
            for cause in report["mortality"]:
                label = f"{cause['label']}: {cause['count']}"
                surface.blit(font_small.render(label[:28], True, (255, 180, 160)), (mortality_x + 12, mortality_y))
                bar_y = mortality_y + 16
                pygame.draw.rect(surface, (55, 62, 86), (mortality_x + 12, bar_y, box_w - 24, 10))
                fill_w = int((box_w - 24) * cause["share"])
                pygame.draw.rect(surface, (255, 110, 110), (mortality_x + 12, bar_y, max(4, fill_w), 10))
                mortality_y += 28
        else:
            surface.blit(font_small.render("No deaths recorded in this run.", True, (180, 190, 215)), (mortality_x + 12, mortality_y))

        faction_y = draw_box("Faction Snapshot", faction_x, box_y, box_w, box_h)
        if report["active_factions"]:
            for faction in report["active_factions"][:4]:
                faction_line = (
                    f"F{faction['id']}  size {faction['members']}  "
                    f"{faction['doctrine'][:5].upper()}  leader #{faction['leader_id']}"
                )
                surface.blit(font_small.render(faction_line[:34], True, (195, 170, 255)), (faction_x + 12, faction_y))
                faction_y += 22
                gen_line = (
                    f"Gen {faction['avg_generation']:.1f}  coh {int(faction['cohesion'])}  "
                    f"sch {int(faction['schism_pressure'])}  mig {int(faction['migration_pressure'])}"
                )
                surface.blit(font_small.render(gen_line, True, (180, 200, 230)), (faction_x + 24, faction_y))
                faction_y += 20
        else:
            surface.blit(font_small.render("No cohesive factions active.", True, (180, 190, 215)), (faction_x + 12, faction_y))

        lower_box_y = box_y + box_h + 18
        lower_right_w = min(240, max(200, panel_w // 4))
        lower_left_w = panel_w - 40 - box_gap - lower_right_w
        lower_h = panel_h - (lower_box_y - panel_y) - 24

        timeline_y = draw_box("Observer Timeline", panel_x + 20, lower_box_y, lower_left_w, lower_h)
        timeline = report["timeline"]
        if timeline:
            for event in timeline[-7:]:
                event_age = max(0.0, current_time - float(event.get("time", current_time) or current_time))
                category = str(event.get("category", "sim"))[:10].upper()
                summary = str(event.get("summary", "Event"))
                line = f"[{category}] {summary} ({event_age:.0f}s ago)"
                surface.blit(font_small.render(line[:84], True, (220, 220, 220)), (panel_x + 32, timeline_y))
                timeline_y += 22
        else:
            surface.blit(font_small.render("Timeline is still forming.", True, (180, 190, 215)), (panel_x + 32, timeline_y))

        trend_x = panel_x + 20 + lower_left_w + box_gap
        trend_y = draw_box("Trait Drift + Checkpoints", trend_x, lower_box_y, lower_right_w, lower_h)
        for trait in report["trait_outliers"][:3]:
            drift_line = f"{trait['trait_name'][:14]} {trait['delta_pct']:+.1f}%"
            surface.blit(font_small.render(drift_line, True, (150, 220, 255)), (trend_x + 12, trend_y))
            trend_y += 22
        if report["generation_history"]:
            trend_y += 8
            for sample in report["generation_history"][-4:]:
                checkpoint = f"t+{int(sample.get('elapsed_seconds', 0))}s  pop {sample.get('population', 0)}  gen {sample.get('avg_generation', 0):.1f}"
                surface.blit(font_small.render(checkpoint[:28], True, (210, 210, 235)), (trend_x + 12, trend_y))
                trend_y += 20
        if report["faction_history"]:
            trend_y += 8
            for faction_event in report["faction_history"][-2:]:
                action = str(faction_event.get("action", "shift")).title()
                details = f"{action} F{faction_event.get('faction_id', '?')} size {faction_event.get('members', 0)}"
                surface.blit(font_small.render(details[:28], True, (210, 185, 255)), (trend_x + 12, trend_y))
                trend_y += 20

        close_hint = font_small.render("[T] to close", True, (180, 200, 230))
        surface.blit(close_hint, (panel_x + panel_w - 104, panel_y + panel_h - 28))


class ArchiveReviewPanel:
    """Run archive and comparison view for observer-side postmortems."""

    def __init__(self):
        self.last_refresh_time = 0.0
        self.cached_log_dir = ""
        self.cached_archive_count = 0
        self.cached_comparisons = []

    def _refresh_cache(self, current_summary, log_dir, current_time):
        if not log_dir:
            self.cached_comparisons = []
            return
        if (
            log_dir != self.cached_log_dir
            or current_time - self.last_refresh_time >= 5.0
        ):
            archive_paths = find_recent_archives(log_dir, limit=3)
            self.cached_comparisons = build_archive_comparison(current_summary, archive_paths) if current_summary else []
            self.cached_archive_count = len(archive_paths)
            self.cached_log_dir = log_dir
            self.last_refresh_time = current_time

    def draw(self, surface, advisor, current_time, log_dir):
        current_summary = dict(advisor.session_stats.get("current_run_summary", {}) or {})
        self._refresh_cache(current_summary, log_dir, current_time)

        panel_w = min(980, WINDOW_WIDTH - 40)
        panel_h = min(620, WINDOW_HEIGHT - 70)
        panel_x = max(20, WINDOW_WIDTH // 2 - panel_w // 2)
        panel_y = max(20, WINDOW_HEIGHT // 2 - panel_h // 2)

        panel = pygame.Surface((panel_w, panel_h))
        panel.set_alpha(242)
        panel.fill((18, 22, 34))
        surface.blit(panel, (panel_x, panel_y))
        pygame.draw.rect(surface, (135, 170, 220), (panel_x, panel_y, panel_w, panel_h), 3)

        scenario_name = current_summary.get("scenario", {}).get("name") or advisor.session_stats.get(
            "scenario_name",
            ACTIVE_SCENARIO_PROFILE.get("name", "Standard Basin"),
        )
        title = font.render("RUN ARCHIVE REVIEW", True, (230, 235, 255))
        subtitle = font_small.render(
            f"{scenario_name}  |  Phase progression, end-state, and recent-run comparison",
            True,
            (170, 210, 255),
        )
        surface.blit(title, (panel_x + 20, panel_y + 14))
        surface.blit(subtitle, (panel_x + 20, panel_y + 42))

        phase = dict(current_summary.get("current_phase", {}) or {})
        phase_id = phase.get("id", "founding")
        end_state = dict(current_summary.get("end_state", {}) or {})
        summary_card = dict(current_summary.get("summary_card", {}) or {})
        settlement = dict(current_summary.get("settlement", {}) or {})
        dominant_lineage = dict(current_summary.get("dominant_lineage", {}) or {})
        dominant_faction = dict(current_summary.get("dominant_faction", {}) or {})
        council = dict(current_summary.get("council", {}) or {})
        doctrine = dict(council.get("doctrine", {}) or {})
        phase_summary = RUN_PHASE_DEFINITIONS.get(phase_id, RUN_PHASE_DEFINITIONS["founding"]).get("summary", "")

        def draw_box(title_text, box_x, box_y, box_w, box_h):
            pygame.draw.rect(surface, (34, 40, 58), (box_x, box_y, box_w, box_h))
            pygame.draw.rect(surface, (90, 120, 170), (box_x, box_y, box_w, box_h), 2)
            title_surface = font_small.render(title_text, True, (215, 228, 255))
            surface.blit(title_surface, (box_x + 12, box_y + 10))
            return box_y + 36

        top_y = panel_y + 78
        gap = 16
        left_w = 360
        mid_w = 270
        right_w = panel_w - 40 - left_w - mid_w - gap * 2

        info_y = draw_box("Current Run", panel_x + 20, top_y, left_w, 176)
        info_lines = [
            f"Phase: {phase.get('label', 'Founding')}",
            f"End-state: {end_state.get('label', 'Brittle Survival')}",
            f"Observer score: {int(end_state.get('score', 0) or 0)}",
            f"Peak population: {int(summary_card.get('population_peak', 0) or 0)}",
            f"Births / deaths: {int(summary_card.get('births_total', 0) or 0)} / {int(summary_card.get('deaths_total', 0) or 0)}",
            f"District: {str(settlement.get('district_identity', 'homestead')).replace('_', ' ').title()}",
            f"Prosperity {float(settlement.get('prosperity_score', 0.0) or 0.0):.2f}  |  Culture {float(settlement.get('culture_score', 0.0) or 0.0):.2f}",
        ]
        for line in info_lines:
            surface.blit(font_small.render(line[:44], True, WHITE), (panel_x + 32, info_y))
            info_y += 22

        phase_x = panel_x + 20 + left_w + gap
        phase_y = draw_box("Phase + Doctrine", phase_x, top_y, mid_w, 176)
        phase_lines = [
            phase_summary[:40] or "The colony is still establishing itself.",
            f"Doctrine: {str(doctrine.get('focus', 'survival')).replace('_', ' ').title()}",
            f"Stance: {str(doctrine.get('stance', 'measured')).title()}",
            f"District priority: {str(doctrine.get('district_priority', 'homestead')).replace('_', ' ').title()}",
            f"Crisis posture: {str(doctrine.get('crisis_posture', 'stabilize')).replace('_', ' ').title()}",
        ]
        for line in phase_lines:
            surface.blit(font_small.render(line[:32], True, (210, 225, 255)), (phase_x + 12, phase_y))
            phase_y += 22

        if doctrine.get("reasoning"):
            surface.blit(
                font_small.render(str(doctrine.get("reasoning", ""))[:32], True, (190, 200, 220)),
                (phase_x + 12, phase_y + 4),
            )

        compare_x = phase_x + mid_w + gap
        compare_y = draw_box("Recent Archives", compare_x, top_y, right_w, 176)
        if self.cached_comparisons:
            for comparison in self.cached_comparisons[:3]:
                header = (
                    f"{comparison.get('scenario_name', 'Unknown')}  "
                    f"{comparison.get('score', 0)} pts"
                )
                surface.blit(font_small.render(header[:28], True, (255, 220, 170)), (compare_x + 12, compare_y))
                compare_y += 20
                detail = (
                    f"{comparison.get('end_state_label', 'Unknown')}  "
                    f"peak {comparison.get('population_peak', 0)}  "
                    f"delta {comparison.get('score_delta', 0):+d}"
                )
                surface.blit(font_small.render(detail[:30], True, (215, 220, 240)), (compare_x + 12, compare_y))
                compare_y += 28
        else:
            surface.blit(font_small.render("No archived runs yet.", True, (180, 190, 215)), (compare_x + 12, compare_y))
            compare_y += 22
        archive_count_line = f"Archive files available: {self.cached_archive_count}"
        surface.blit(font_small.render(archive_count_line, True, (170, 190, 220)), (compare_x + 12, top_y + 144))

        lower_y = top_y + 176 + 18
        lower_h = panel_h - (lower_y - panel_y) - 24
        lower_left_w = panel_w - 40 - 280 - gap
        lower_right_w = 280

        timeline_y = draw_box("Major Moments", panel_x + 20, lower_y, lower_left_w, lower_h)
        timeline = list(current_summary.get("observer_report", {}).get("timeline", []))
        if timeline:
            for event in timeline[-8:]:
                category = str(event.get("category", "sim"))[:10].upper()
                summary = str(event.get("summary", "Event"))
                line = f"[{category}] {summary}"
                surface.blit(font_small.render(line[:80], True, (220, 220, 220)), (panel_x + 32, timeline_y))
                timeline_y += 22
        else:
            surface.blit(font_small.render("The timeline is still sparse.", True, (180, 190, 215)), (panel_x + 32, timeline_y))

        right_y = draw_box("Dominance + Friction", panel_x + 20 + lower_left_w + gap, lower_y, lower_right_w, lower_h)
        right_lines = [
            (
                f"Lineage L{dominant_lineage.get('lineage_id', '?')}  "
                f"{dominant_lineage.get('count', 0)} ({int(float(dominant_lineage.get('share', 0.0) or 0.0) * 100)}%)"
                if dominant_lineage
                else "No dominant lineage yet."
            ),
            (
                f"Faction F{dominant_faction.get('id', '?')}  size {dominant_faction.get('members', 0)}"
                if dominant_faction
                else "No dominant faction yet."
            ),
            f"Festival readiness: {float(settlement.get('festival_readiness', 0.0) or 0.0):.2f}",
        ]
        for line in right_lines:
            surface.blit(font_small.render(line[:30], True, (210, 225, 255)), (panel_x + 20 + lower_left_w + gap + 12, right_y))
            right_y += 22

        event_framing = str(council.get("event_framing", ""))
        if event_framing:
            right_y += 8
            surface.blit(font_small.render("Council framing", True, (255, 220, 170)), (panel_x + 20 + lower_left_w + gap + 12, right_y))
            right_y += 22
            for offset in range(0, min(len(event_framing), 96), 30):
                surface.blit(
                    font_small.render(event_framing[offset : offset + 30], True, (220, 220, 220)),
                    (panel_x + 20 + lower_left_w + gap + 12, right_y),
                )
                right_y += 20

        close_hint = font_small.render("[A] to close", True, (180, 200, 230))
        surface.blit(close_hint, (panel_x + panel_w - 104, panel_y + panel_h - 28))


