import os
import pygame

pygame.init()
# We don't need a display window to generate surfaces, but we need to init display to use Surface.convert()
# However, we can just use SRCALPHA surfaces without convert.
# We'll use SRCALPHA and pygame.image.save()

ASSET_ROOT = os.path.join(os.path.dirname(__file__), "assets", "sprites")

def ensure_dir(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def create_sprite(path, size, draw_func):
    ensure_dir(path)
    if os.path.exists(path):
        return  # Skip if exists to avoid overwriting user edits
    surface = pygame.Surface(size, pygame.SRCALPHA)
    draw_func(surface)
    pygame.image.save(surface, path)

def draw_thronglet_base(surface):
    w, h = surface.get_size()
    pygame.draw.ellipse(surface, (236, 198, 172), (w//4, h//4, w//2, h//2))
    pygame.draw.rect(surface, (66, 62, 56), (w//3, h//2, w//3, h//3))

def main():
    print(f"Generating sprite assets in {ASSET_ROOT} ...")
    os.makedirs(os.path.join(ASSET_ROOT, "thronglets"), exist_ok=True)
    os.makedirs(os.path.join(ASSET_ROOT, "buildings"), exist_ok=True)
    os.makedirs(os.path.join(ASSET_ROOT, "resources"), exist_ok=True)
    os.makedirs(os.path.join(ASSET_ROOT, "npcs"), exist_ok=True)
    os.makedirs(os.path.join(ASSET_ROOT, "hazards"), exist_ok=True)

    # We rely on the game's procedural SpriteLibrary for now to do the heavy lifting,
    # because SpriteLibrary natively reads PNGs if they exist, but falls back to procedural.
    # So we're creating the directory structure and a few placeholder PNGs just so the user 
    # has a concrete place to put their own externally generated PNG static assets!
    
    # We will generate a clear 64x64 PNG for 'food' and 'wood'
    def draw_food(s):
        pygame.draw.circle(s, (171, 72, 88), (32, 32), 16)
        pygame.draw.circle(s, (96, 132, 77), (36, 20), 8)
    
    create_sprite(os.path.join(ASSET_ROOT, "resources", "food.png"), (64, 64), draw_food)

    print("Success. Folder structure created and sample static PNGs generated.")

if __name__ == "__main__":
    main()
