"""
ModLoader — Simple mod support that merges external content directories over base game defs.

Mods are directories placed in a `mods/` folder at the project root.
Each mod directory can contain its own `defs/` subdirectory with JSON files
that follow the same format as the base game's `defs/core/` files.

Loading order:
  1. Base game defs are loaded first (via DefDatabase.initialize)
  2. ModLoader scans `mods/` for enabled mod directories
  3. Each mod's JSON defs are merged over the base defs (overwrite by ID)

This allows mods to add new items, modify existing ones, or extend content.
"""
from __future__ import annotations

import os
import json
import logging
from typing import Optional

logger = logging.getLogger("ModLoader")


class ModInfo:
    """Metadata about a single mod."""
    def __init__(self, mod_id: str, name: str, path: str, version: str = "1.0.0",
                 author: str = "Unknown", description: str = "", load_order: int = 100):
        self.mod_id = mod_id
        self.name = name
        self.path = path
        self.version = version
        self.author = author
        self.description = description
        self.load_order = load_order
        self.enabled = True
        self.loaded = False
        self.def_count = 0

    def __repr__(self):
        return f"Mod({self.mod_id}, v{self.version}, {'enabled' if self.enabled else 'disabled'})"


class ModLoader:
    """
    Scans a mods directory, reads mod metadata, and merges mod defs
    into the DefDatabase.
    """

    def __init__(self, mods_dir: str = "mods"):
        self.mods_dir = mods_dir
        self.discovered_mods: list[ModInfo] = []
        self.load_errors: list[str] = []

    def discover(self) -> list[ModInfo]:
        """Scan the mods directory for mod folders and read their metadata."""
        self.discovered_mods.clear()
        self.load_errors.clear()

        if not os.path.isdir(self.mods_dir):
            logger.info(f"No mods directory found at '{self.mods_dir}'. Skipping mod discovery.")
            return self.discovered_mods

        for entry in sorted(os.listdir(self.mods_dir)):
            mod_path = os.path.join(self.mods_dir, entry)
            if not os.path.isdir(mod_path):
                continue

            # Look for mod_info.json
            info_path = os.path.join(mod_path, "mod_info.json")
            if os.path.isfile(info_path):
                try:
                    with open(info_path, "r", encoding="utf-8") as f:
                        info_data = json.load(f)
                    mod = ModInfo(
                        mod_id=info_data.get("id", entry),
                        name=info_data.get("name", entry),
                        path=mod_path,
                        version=info_data.get("version", "1.0.0"),
                        author=info_data.get("author", "Unknown"),
                        description=info_data.get("description", ""),
                        load_order=info_data.get("load_order", 100),
                    )
                    self.discovered_mods.append(mod)
                    logger.info(f"Discovered mod: {mod.name} v{mod.version} by {mod.author}")
                except Exception as e:
                    err = f"Failed to read mod_info.json in '{entry}': {e}"
                    self.load_errors.append(err)
                    logger.warning(err)
            else:
                # Auto-detect: treat any folder with a defs/ subdirectory as a mod
                defs_path = os.path.join(mod_path, "defs")
                if os.path.isdir(defs_path):
                    mod = ModInfo(
                        mod_id=entry,
                        name=entry,
                        path=mod_path,
                    )
                    self.discovered_mods.append(mod)
                    logger.info(f"Auto-discovered mod folder: {entry}")

        # Sort by load_order
        self.discovered_mods.sort(key=lambda m: m.load_order)
        return self.discovered_mods

    def load_all(self, def_database_cls) -> int:
        """
        Load all enabled mods by merging their defs into DefDatabase.
        
        Args:
            def_database_cls: The DefDatabase class (passed to avoid circular imports)
            
        Returns:
            Total number of definitions loaded across all mods.
        """
        total_loaded = 0

        for mod in self.discovered_mods:
            if not mod.enabled:
                logger.info(f"Skipping disabled mod: {mod.name}")
                continue

            count = self._load_mod(mod, def_database_cls)
            mod.loaded = True
            mod.def_count = count
            total_loaded += count

        if total_loaded > 0:
            logger.info(f"ModLoader: Loaded {total_loaded} definitions from {len([m for m in self.discovered_mods if m.loaded])} mod(s)")
        return total_loaded

    def _load_mod(self, mod: ModInfo, def_database_cls) -> int:
        """Load a single mod's defs into DefDatabase."""
        defs_path = os.path.join(mod.path, "defs")
        if not os.path.isdir(defs_path):
            return 0

        loaded = 0
        for dirpath, _, filenames in os.walk(defs_path):
            for filename in filenames:
                if not filename.endswith(".json"):
                    continue
                filepath = os.path.join(dirpath, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        for def_type, def_list in data.items():
                            if isinstance(def_list, list):
                                for item in def_list:
                                    if isinstance(item, dict) and "id" in item:
                                        def_database_cls._register(def_type, item)
                                        loaded += 1
                except json.JSONDecodeError as e:
                    err = f"[{mod.name}] JSON parse error in {filepath}: {e}"
                    self.load_errors.append(err)
                    logger.warning(err)
                except Exception as e:
                    err = f"[{mod.name}] Error loading {filepath}: {e}"
                    self.load_errors.append(err)
                    logger.warning(err)

        if loaded > 0:
            logger.info(f"  [{mod.name}] Loaded {loaded} defs")
        return loaded

    def get_enabled_mods(self) -> list[ModInfo]:
        return [m for m in self.discovered_mods if m.enabled]

    def get_mod_by_id(self, mod_id: str) -> Optional[ModInfo]:
        for m in self.discovered_mods:
            return m if m.mod_id == mod_id else None
        return None

    def enable_mod(self, mod_id: str):
        mod = self.get_mod_by_id(mod_id)
        if mod:
            mod.enabled = True

    def disable_mod(self, mod_id: str):
        mod = self.get_mod_by_id(mod_id)
        if mod:
            mod.enabled = False

    def to_dict(self) -> dict:
        """Serialize mod state for save files."""
        return {
            "enabled_mods": [m.mod_id for m in self.discovered_mods if m.enabled],
            "disabled_mods": [m.mod_id for m in self.discovered_mods if not m.enabled],
        }
