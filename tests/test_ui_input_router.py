import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from ui.input_router import UIState, handle_escape, pick_world_entity


class _SelectionManager:
    def __init__(self):
        self.selected_entity = object()

    def deselect(self):
        self.selected_entity = None


class _Camera:
    def __init__(self, zoom):
        self.zoom = zoom

    def world_to_screen(self, world_x, world_y):
        return (100.0, 100.0)


class UIInputRouterTests(unittest.TestCase):
    def test_handle_escape_closes_layers_before_quit(self):
        ui_state = UIState(active_modal="archive", end_summary_open=True)
        selection_manager = _SelectionManager()

        self.assertFalse(handle_escape(ui_state, selection_manager))
        self.assertIsNone(ui_state.active_modal)
        self.assertTrue(ui_state.end_summary_open)

        self.assertFalse(handle_escape(ui_state, selection_manager))
        self.assertFalse(ui_state.end_summary_open)

        self.assertFalse(handle_escape(ui_state, selection_manager))
        self.assertIsNone(selection_manager.selected_entity)
        self.assertIsNone(ui_state.inspect_target)

        self.assertFalse(handle_escape(ui_state, selection_manager))
        self.assertTrue(ui_state.show_quit_prompt)

        self.assertTrue(handle_escape(ui_state, selection_manager))

    def test_pick_world_entity_is_zoom_invariant_for_hover_thresholds(self):
        npc = SimpleNamespace(x=0.0, y=0.0, visible=True)
        base_args = {
            "screen_pos": (130, 100),
            "praxans": [],
            "buildings": [],
            "resources": [],
            "encounters": [],
            "hazards": [],
            "npcs": [npc],
            "praxan_radius": 10.0,
            "building_size": 16.0,
            "resource_radii": {"food": 8.0, "wood": 10.0, "stone": 10.0},
        }

        picked_zoom_one = pick_world_entity(camera=_Camera(1.0), **base_args)
        picked_zoom_three = pick_world_entity(camera=_Camera(3.0), **base_args)

        self.assertEqual((None, None), picked_zoom_one)
        self.assertEqual(picked_zoom_one, picked_zoom_three)


if __name__ == "__main__":
    unittest.main()
