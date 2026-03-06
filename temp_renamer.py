import os

replacements = {
    "thonglets": "praxans",
    "Thonglets": "Praxans",
    "THONGLETS": "PRAXANS",
    
    "thronglets": "praxans",
    "Thronglets": "Praxans",
    "THRONGLETS": "PRAXANS",
    
    "thronglet": "praxan",
    "Thronglet": "Praxan",
    "THRONGLET": "PRAXAN",
    
    "thonglet": "praxan",
    "Thonglet": "Praxan",
    "THONGLET": "PRAXAN",
}

def rename_content(file_path):
    if file_path.endswith("temp_renamer.py"):
        return
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        new_content = content
        for old, new in replacements.items():
            new_content = new_content.replace(old, new)
            
        if new_content != content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
    except Exception as e:
        pass

# Update contents
for root, dirs, files in os.walk('.'):
    # Exclude venv, .git, logging folders and assets (images)
    dirs[:] = [d for d in dirs if d not in ['.git', '.venv', '__pycache__', 'assets', 'logs']]
    for name in files:
        if name.endswith(('.pyc', '.png', '.jpg', '.mp4', '.sqlite3', '.db', '.log', '.wav')):
            continue
        rename_content(os.path.join(root, name))

# Rename files and directories bottom-up
for root, dirs, files in os.walk('.', topdown=False):
    # Skip excluded directories
    if any(excl in root for excl in ['.git', '.venv', '__pycache__', 'assets', 'logs']):
        continue
        
    for name in files + dirs:
        if name == "temp_renamer.py":
            continue
            
        new_name = name
        for old, new in replacements.items():
            new_name = new_name.replace(old, new)
        
        if new_name != name and new_name.lower() != name.lower() and not os.path.exists(os.path.join(root, new_name)):
            old_path = os.path.join(root, name)
            new_path = os.path.join(root, new_name)
            try:
                os.rename(old_path, new_path)
                print(f"Renamed {old_path} to {new_path}")
            except Exception as e:
                print(f"Failed to rename {old_path}: {e}")

print("Rename complete.")
