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
    dirs[:] = [d for d in dirs if d not in ['.git', '.venv', '__pycache__', 'assets']]
    for name in files:
        if name.endswith(('.pyc', '.png', '.jpg', '.mp4', '.sqlite3', '.db', '.log', '.wav')):
            continue
        rename_content(os.path.join(root, name))

# Rename files and directories bottom-up
for root, dirs, files in os.walk('.', topdown=False):
    # Skip excluded directories
    if any(excl in root for excl in ['.git', '.venv', '__pycache__', 'assets']):
        continue
        
    for name in files + dirs:
        new_name = name
        for old, new in replacements.items():
            new_name = new_name.replace(old, new)
        
        if new_name != name:
            old_path = os.path.join(root, name)
            new_path = os.path.join(root, new_name)
            os.rename(old_path, new_path)
            print(f"Renamed {old_path} to {new_path}")

print("Rename complete.")
