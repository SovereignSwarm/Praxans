import os
from PIL import Image

def make_transparent(img_path, output_path, bg_color=(27, 33, 35), tolerance=40):
    try:
        img = Image.open(img_path).convert("RGBA")
        data = img.getdata()

        new_data = []
        for item in data:
            # Check if color is close to background color
            if (abs(item[0] - bg_color[0]) < tolerance and
                abs(item[1] - bg_color[1]) < tolerance and
                abs(item[2] - bg_color[2]) < tolerance):
                new_data.append((255, 255, 255, 0)) # transparent
            else:
                new_data.append(item)

        img.putdata(new_data)
        
        # Crop transparent edges
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
            
        img.save(output_path, "PNG")
        print(f"Processed {img_path} -> {output_path}")
        return img
    except Exception as e:
        print(f"Error processing {img_path}: {e}")
        return None

def process_assets():
    brain_dir = r"C:\Users\jorqu\.gemini\antigravity\brain\5779f276-d1af-4de6-9f71-f13d28754247"
    project_dir = r"d:\Documents\PerseusXR\Thonglets"
    assets_dir = os.path.join(project_dir, "assets", "ui")
    
    os.makedirs(assets_dir, exist_ok=True)
    
    import glob
    logo_files = glob.glob(os.path.join(brain_dir, "praxans_logo_pixel*.png"))
    icon_files = glob.glob(os.path.join(brain_dir, "praxans_icon*.png"))
    
    if logo_files:
        latest_logo = max(logo_files, key=os.path.getctime)
        logo_img = make_transparent(latest_logo, os.path.join(assets_dir, "logo.png"))
        if logo_img:
            # Scale to reasonable max width/height while preserving aspect ratio
            max_size = (600, 200)
            logo_img.thumbnail(max_size, Image.Resampling.NEAREST) # keep pixel art crisp
            logo_img.save(os.path.join(assets_dir, "logo.png"))
            print("Logo resized.")
            
    if icon_files:
        latest_icon = max(icon_files, key=os.path.getctime)
        icon_img = make_transparent(latest_icon, os.path.join(assets_dir, "icon_raw.png"))
        if icon_img:
            # Make square for icons
            size = max(icon_img.size)
            square = Image.new('RGBA', (size, size), (0,0,0,0))
            square.paste(icon_img, ((size - icon_img.size[0]) // 2, (size - icon_img.size[1]) // 2))
            
            # Save different sizes
            for s in [32, 64]:
                resized = square.resize((s, s), Image.Resampling.NEAREST)
                resized.save(os.path.join(assets_dir, f"icon_{s}.png"))
                print(f"Saved icon_{s}.png")
                
            # Save ICO
            square.save(os.path.join(assets_dir, "icon.ico"), format='ICO', sizes=[(16,16), (32,32), (48,48), (64,64)])
            print("Saved icon.ico")

if __name__ == "__main__":
    process_assets()
