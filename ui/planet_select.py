import pygame
from map.planet import PlanetGrid
from ui.theme import build_ui_theme, UITheme, draw_panel, wrap_text

class PlanetSelectUI:
    def __init__(self, screen, runtime_config, seed):
        self.screen = screen
        self.clock = pygame.time.Clock()
        self.config = runtime_config
        self.theme = build_ui_theme(*screen.get_size())
        print("Generating Planet Macro-Map...")
        self.planet = PlanetGrid(cols=100, rows=60, seed=seed)
        self.hex_radius = 12
        self.camera_x = 0
        self.camera_y = 0
        self.selected_tile = None
        self.running = True
        self.result = {"action": "quit", "planet_tile": None, "ai_world_seed": None}
        self._land_button_rect = None  # Stores the "LAND HERE" button rect for click detection
        self._ai_button_rect = None
        self.generating_ai = False

    def _get_biome_color(self, biome: str) -> tuple[int, int, int]:
        colors = {
            "ocean": (30, 60, 100),
            "ice_sheet": (200, 220, 255),
            "desert": (220, 200, 150),
            "plains": (150, 180, 100),
            "forest": (60, 120, 60),
            "swamp": (50, 80, 50),
            "taiga": (80, 100, 90),
            "tundra": (180, 190, 190),
            "snow": (240, 250, 255)
        }
        return colors.get(biome, (255, 0, 255))

    def _world_to_screen(self, cx: int, cy: int) -> tuple[float, float]:
        width, height = self.screen.get_size()
        # Simple isometric-like stagger or just grid squares for now
        # Let's do simple hex-like staggering
        x = (cx * self.hex_radius * 1.5) - self.camera_x + (width / 2) - (self.planet.cols * self.hex_radius * 0.75)
        offset = self.hex_radius * 0.866 if cx % 2 == 1 else 0
        y = (cy * self.hex_radius * 1.732) + offset - self.camera_y + (height / 2) - (self.planet.rows * self.hex_radius * 0.866)
        return x, y

    def run(self) -> dict:
        while self.running:
            self.screen.fill((10, 10, 15))  # Deep space background
            
            # Draw planet tiles
            mx, my = pygame.mouse.get_pos()
            hovered_tile = None
            
            for (cx, cy), tile in self.planet.tiles.items():
                sx, sy = self._world_to_screen(cx, cy)
                
                # Culling
                if sx < -50 or sx > self.screen.get_width() + 50 or sy < -50 or sy > self.screen.get_height() + 50:
                    continue
                
                color = self._get_biome_color(tile.biome)
                rect = pygame.Rect(sx, sy, self.hex_radius * 1.5, self.hex_radius * 1.732)
                
                # Hover detection
                if rect.collidepoint(mx, my):
                    hovered_tile = tile
                    color = (min(255, color[0] + 40), min(255, color[1] + 40), min(255, color[2] + 40))
                
                if self.selected_tile == tile:
                    pygame.draw.rect(self.screen, (255, 200, 0), rect.inflate(4, 4))
                    
                pygame.draw.rect(self.screen, color, rect)

            # Draw UI Overlay
            self._draw_overlay(hovered_tile)
            
            if self.generating_ai:
                dim_overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
                dim_overlay.fill((0, 0, 0, 180))
                self.screen.blit(dim_overlay, (0, 0))
                text = self.theme.fonts.display.render("Dreaming up local world mechanics...", True, self.theme.palette.parchment)
                self.screen.blit(text, (self.screen.get_width()//2 - text.get_width()//2, self.screen.get_height()//2 - text.get_height()//2))

            pygame.display.flip()
            
            if self.generating_ai:
                self._generate_ai_world()
                
            self._handle_events(hovered_tile)
            self.clock.tick(30)
            
        return self.result
        
    def _generate_ai_world(self):
        try:
            from llm.client import get_global_ollama_client
            from llm.prompts import build_world_seed_prompt
            from llm.contracts import parse_world_seed_payload
            client = get_global_ollama_client()
            if client and client.available():
                prompt = build_world_seed_prompt()
                raw, _ = client.generate(prompt=prompt, channel="council")
                parsed = parse_world_seed_payload(raw)
                print(f"[LLM] World Seed Parsed: {parsed}")
                self.result = {"action": "start", "planet_tile": self.selected_tile, "ai_world_seed": parsed}
            else:
                print("[LLM] Ollama unavailable. Falling back to normal landing.")
                self.result = {"action": "start", "planet_tile": self.selected_tile, "ai_world_seed": None}
        except Exception as e:
            print(f"[LLM] Error generating world seed: {e}")
            self.result = {"action": "start", "planet_tile": self.selected_tile, "ai_world_seed": None}
        
        self.generating_ai = False
        self.running = False

    def _draw_overlay(self, hovered_tile):
        panel_rect = pygame.Rect(20, 20, 300, 400)
        draw_panel(self.screen, panel_rect, self.theme, fill=(24, 31, 33), alpha=238)
        
        title = self.theme.fonts.display.render("Planet Selector", True, self.theme.palette.parchment)
        self.screen.blit(title, (40, 40))
        
        info = "Select a landing site for the colony. The climate here will dictate the local simulation."
        y = 90
        for line in wrap_text(self.theme.fonts.body, info, 260):
            self.screen.blit(self.theme.fonts.body.render(line, True, self.theme.palette.bright_text), (40, y))
            y += 24
            
        if self.selected_tile or hovered_tile:
            active_tile = self.selected_tile or hovered_tile
            y += 20
            pygame.draw.line(self.screen, self.theme.palette.moss, (40, y), (280, y))
            y += 20
            
            self.screen.blit(self.theme.fonts.heading.render(active_tile.biome.upper().replace("_", " "), True, self._get_biome_color(active_tile.biome)), (40, y))
            y += 30
            self.screen.blit(self.theme.fonts.body.render(f"Temperature: {active_tile.temperature:.2f}", True, self.theme.palette.frost), (40, y))
            y += 24
            self.screen.blit(self.theme.fonts.body.render(f"Moisture: {active_tile.moisture:.2f}", True, self.theme.palette.frost), (40, y))
            y += 24
            self.screen.blit(self.theme.fonts.body.render(f"Elevation: {active_tile.elevation:.2f}", True, self.theme.palette.frost), (40, y))
            
            if self.selected_tile and self.selected_tile.is_land:
                y += 50
                btn = pygame.Rect(40, y, 220, 36)
                self._land_button_rect = btn
                pygame.draw.rect(self.screen, self.theme.palette.ochre, btn, border_radius=4)
                text = self.theme.fonts.label.render("LAND HERE (Enter)", True, (20, 20, 20))
                self.screen.blit(text, (btn.centerx - text.get_width()//2, btn.centery - text.get_height()//2))
                
                y += 46
                aibtn = pygame.Rect(40, y, 220, 36)
                self._ai_button_rect = aibtn
                pygame.draw.rect(self.screen, self.theme.palette.moss, aibtn, border_radius=4)
                aitext = self.theme.fonts.label.render("DREAM LOCAL WORLD (AI)", True, (20, 20, 20))
                self.screen.blit(aitext, (aibtn.centerx - aitext.get_width()//2, aibtn.centery - aitext.get_height()//2))
            else:
                self._land_button_rect = None
                self._ai_button_rect = None

    def _handle_events(self, hovered_tile):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_RETURN and self.selected_tile and self.selected_tile.is_land:
                    self.result = {"action": "start", "planet_tile": self.selected_tile}
                    self.running = False
                # Simple camera pan
                elif event.key == pygame.K_w: self.camera_y -= 50
                elif event.key == pygame.K_s: self.camera_y += 50
                elif event.key == pygame.K_a: self.camera_x -= 50
                elif event.key == pygame.K_d: self.camera_x += 50
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    # Check if clicking the Land button
                    if self._land_button_rect and self._land_button_rect.collidepoint(event.pos):
                        self.result = {"action": "start", "planet_tile": self.selected_tile}
                        self.running = False
                        return
                    if self._ai_button_rect and self._ai_button_rect.collidepoint(event.pos):
                        self.generating_ai = True
                        return
                    if hovered_tile:
                        self.selected_tile = hovered_tile
