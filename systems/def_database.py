import os
import json
import logging

logger = logging.getLogger("DefDatabase")

class DefDatabase:
    """
    A RimWorld-style centralized registry for all authored game content.
    Loads JSON files from a 'defs/' directory, separating game logic from content.
    """
    _defs = {}  # Format: {def_type: {def_id: def_data}}
    _initialized = False

    @classmethod
    def initialize(cls, root_dir="defs"):
        if cls._initialized:
            return
            
        cls.clear()
        if not os.path.exists(root_dir):
            logger.warning(f"Def directory '{root_dir}' not found. No external content loaded.")
            return

        # Scan for all JSON files recursively
        loaded_count = 0
        for dirpath, _, filenames in os.walk(root_dir):
            for filename in filenames:
                if filename.endswith(".json"):
                    filepath = os.path.join(dirpath, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            # Expecting a list of Defs or a dict wrapping lists
                            if isinstance(data, dict):
                                for def_type, def_list in data.items():
                                    if isinstance(def_list, list):
                                        for item in def_list:
                                            cls._register(def_type, item)
                                            loaded_count += 1
                            elif isinstance(data, list):
                                logger.warning(f"File {filepath} contains a top-level list. Expected a dict mapping def_type to a list of objects.")
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON def file {filepath}: {e}")
                    except Exception as e:
                        logger.error(f"Error loading def file {filepath}: {e}")
                        
        logger.info(f"DefDatabase initialized. Loaded {loaded_count} definitions.")
        cls._initialized = True

    @classmethod
    def _register(cls, def_type: str, def_data: dict):
        if "id" not in def_data:
            logger.warning(f"A {def_type} definition is missing a unique 'id' field. Skipping: {def_data}")
            return
            
        def_id = def_data["id"]
        
        if def_type not in cls._defs:
            cls._defs[def_type] = {}
            
        if def_id in cls._defs[def_type]:
            logger.warning(f"Overwriting existing {def_type} with id '{def_id}'")
            
        cls._defs[def_type][def_id] = def_data

    @classmethod
    def get(cls, def_type: str, def_id: str, default=None) -> dict:
        """Get a specific definition by type and ID."""
        return cls._defs.get(def_type, {}).get(def_id, default)

    @classmethod
    def get_all(cls, def_type: str) -> dict:
        """Get all definitions of a specific type. Returns {id: data}."""
        return cls._defs.get(def_type, {})

    @classmethod
    def clear(cls):
        cls._defs.clear()
        cls._initialized = False
