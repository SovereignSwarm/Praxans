import json
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from test_tempdir import workspace_tempdir

from ui.analytics import draw_end_summary, draw_modal_layer
from ui.hud import draw_run_hud
from ui.input_router import UIState, UIRectRegistry
from ui.inspect import build_inspect_view_model, draw_inspect_drawer
from ui.layout import compute_run_layout
from ui.models import FieldNote, RunHudModel
from ui.theme import build_ui_theme


class UIRenderSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_living_atlas_layers_render_to_surface(self):
        surface = pygame.Surface((1366, 768), pygame.SRCALPHA)
        theme = build_ui_theme(1366, 768)
        layout = compute_run_layout(1366, 768)
        registry = UIRectRegistry()
        ui_state = UIState(active_modal="archive", selected_run="session-alpha")
        hud_model = RunHudModel(
            scenario_name="High Mutation",
            phase_label="Societal Divergence",
            doctrine_label="Growth",
            llm_status="Qwen Ready",
            speed_label="1.0x",
            follow_label="Follow",
            camera_mode_label="Follow",
            crisis_label="Stable",
            overlay_label="Districts",
            observer_score=73,
            cue_label="Faction schism forming",
        )
        field_notes = [
            FieldNote(category="birth", title="Birth", body="A new founder branch emerged.", age_seconds=8.0),
            FieldNote(category="faction", title="Faction", body="Faction 2 formed around a migration doctrine.", age_seconds=14.0),
        ]
        minimap_context = {
            "world_map": SimpleNamespace(chunks={}, hazards=[]),
            "camera": SimpleNamespace(x=0.0, y=0.0, zoom=1.0, world_width=1200.0, world_height=900.0),
            "city_planner": SimpleNamespace(zones={(1, 1): "residential"}),
            "faction_manager": SimpleNamespace(factions={}),
            "praxans": [],
            "buildings": [],
            "fog_of_war": SimpleNamespace(fog_grid={}),
            "camera_bookmarks": [{"x": 30.0, "y": 50.0, "label": "Cue", "category": "birth", "time": 100.0}],
            "biome_colors": {"plains": (100, 120, 80)},
            "chunk_size": 32,
            "tile_size": 8,
            "window_size": (1366, 768),
        }
        advisor = SimpleNamespace(
            research_points=120,
            tech_tree={
                "agriculture_1": {"name": "Agriculture", "cost": 40, "requires": [], "effect": {"food": 1.2}},
                "storage_1": {"name": "Granaries", "cost": 55, "requires": ["agriculture_1"], "effect": {"storage": 1.3}},
            },
            abilities={"festival": {"cost": 60}},
            game_modifiers=SimpleNamespace(tech_unlocked={"agriculture_1"}),
            session_stats={
                "current_evolution_summary": {"avg_generation": 2.4, "max_generation": 5, "founder_lines": 3},
                "generation_history": [{"elapsed_seconds": 80, "population": 9, "avg_generation": 2.0}],
                "lineage_events": [{"summary": "Lineage 1 stabilized"}],
            },
        )
        current_summary = {
            "summary_card": {"headline": "Societal Divergence -> Brittle Survival", "population_peak": 14},
            "scenario": {"name": "High Mutation"},
            "current_phase": {"label": "Societal Divergence"},
            "end_state": {"label": "Brittle Survival", "score": 63},
            "observer_report": {
                "population": 11,
                "max_population": 14,
                "births_total": 9,
                "deaths_total": 2,
                "avg_survival_time": 95.0,
                "top_lineages": [{"lineage_id": 1, "count": 6, "share": 0.54}],
                "active_factions": [{"id": 2, "members": 5, "cohesion": 74}],
            },
            "dominant_lineage": {"lineage_id": 1},
            "dominant_faction": {"id": 2},
            "key_moments": [{"category": "faction", "summary": "Faction 2 migrated east"}],
            "settlement": {"prosperity_score": 0.61, "culture_score": 0.57},
        }
        settlement_state = {
            "district_identity": "agrarian",
            "prosperity_score": 0.61,
            "culture_score": 0.57,
            "festival_readiness": 0.44,
            "stored_food": 12,
            "stored_wood": 7,
            "stored_stone": 4,
        }

        with workspace_tempdir() as temp_dir:
            archive_payload = {
                "session_id": "session-alpha",
                "scenario": {"name": "High Mutation"},
                "end_state": {"label": "Brittle Survival", "score": 63},
                "summary_card": {"headline": "Societal Divergence -> Brittle Survival", "score": 63, "population_peak": 14},
                "key_moments": [{"category": "faction", "summary": "Faction 2 migrated east"}],
            }
            archive_path = os.path.join(temp_dir, "archive_session-alpha.json")
            with open(archive_path, "w", encoding="utf-8") as archive_file:
                json.dump(archive_payload, archive_file)

            draw_run_hud(surface, theme, layout, registry, hud_model, field_notes, ui_state, 0, minimap_context)
            inspect_model = build_inspect_view_model(None, None, advisor, 100.0, settlement_state, active_tab="overview")
            draw_inspect_drawer(surface, theme, layout, registry, inspect_model, scroll_offset=0)
            draw_modal_layer(
                surface,
                theme,
                layout,
                registry,
                ui_state,
                advisor=advisor,
                current_summary=current_summary,
                current_time=100.0,
                log_dir=temp_dir,
                evolution_summary=advisor.session_stats["current_evolution_summary"],
            )
            draw_end_summary(surface, theme, layout, registry, current_summary, "logs/snapshot_session-alpha.json")

        self.assertTrue(registry.contains_ui(layout.transport_bar.center))
        self.assertTrue(registry.contains_ui(layout.inspect_drawer.center))


if __name__ == "__main__":
    unittest.main()

