"""
ExposeData — Defensive serialization pattern for version-safe save/load.

Provides a mixin class and utility functions that ensure loading old saves
into newer code versions never crashes. Each field is read with a fallback
default, and unknown fields are silently ignored.

Inspired by RimWorld's ExposeData() pattern.
"""
from __future__ import annotations

import logging
from typing import Any, TypeVar, Type

logger = logging.getLogger("ExposeData")

T = TypeVar("T")


class Exposable:
    """
    Mixin class that provides defensive serialization.
    
    Subclasses define `expose_fields()` returning a dict of
    {field_name: default_value}. The to_dict/from_dict methods
    automatically handle missing fields, type coercion, and
    backward compatibility.
    """

    def expose_fields(self) -> dict[str, Any]:
        """
        Override this to define serializable fields and their defaults.
        
        Returns:
            dict mapping field_name -> default_value
        """
        return {}

    def expose_to_dict(self) -> dict:
        """Serialize this object to a dict using the exposed fields."""
        data = {}
        for field, default in self.expose_fields().items():
            value = getattr(self, field, default)
            # Recursively serialize nested Exposables
            if isinstance(value, Exposable):
                data[field] = value.expose_to_dict()
            elif isinstance(value, list):
                data[field] = [
                    item.expose_to_dict() if isinstance(item, Exposable) else item
                    for item in value
                ]
            elif isinstance(value, dict):
                data[field] = {
                    k: v.expose_to_dict() if isinstance(v, Exposable) else v
                    for k, v in value.items()
                }
            else:
                data[field] = value
        # Store a version tag for future migrations
        data["__version__"] = getattr(self, "__schema_version__", 1)
        return data

    def expose_from_dict(self, data: dict):
        """
        Load this object from a dict, applying defaults for missing fields.
        Unknown fields in the data are silently ignored.
        """
        if not isinstance(data, dict):
            logger.warning(f"Expected dict for {type(self).__name__}, got {type(data).__name__}")
            return

        saved_version = data.get("__version__", 1)
        current_version = getattr(self, "__schema_version__", 1)

        for field, default in self.expose_fields().items():
            if field in data:
                try:
                    value = data[field]
                    # Type coercion for common cases
                    if isinstance(default, float) and isinstance(value, int):
                        value = float(value)
                    elif isinstance(default, int) and isinstance(value, float):
                        value = int(value)
                    elif isinstance(default, list) and not isinstance(value, list):
                        value = default
                    elif isinstance(default, dict) and not isinstance(value, dict):
                        value = default
                    setattr(self, field, value)
                except Exception as e:
                    logger.warning(
                        f"Failed to load field '{field}' for {type(self).__name__}: {e}. "
                        f"Using default: {default}"
                    )
                    setattr(self, field, default)
            else:
                # Field missing in save data — apply default (new field added in newer version)
                setattr(self, field, default)
                if saved_version < current_version:
                    logger.debug(
                        f"Field '{field}' not in save (v{saved_version}), "
                        f"using default for v{current_version}"
                    )

        # Run any post-load migrations
        if saved_version < current_version:
            self._migrate(saved_version, current_version, data)

    def _migrate(self, from_version: int, to_version: int, raw_data: dict):
        """
        Override this to handle migrations between schema versions.
        Called automatically when loading data from an older version.
        """
        pass


def safe_load(cls: Type[T], data: dict) -> T:
    """
    Safely instantiate and load an Exposable object from save data.
    Returns a fresh instance with defaults if data is None or invalid.
    """
    obj = cls()
    if data and isinstance(data, dict):
        obj.expose_from_dict(data)
    return obj


def safe_get(data: dict, key: str, default: Any = None, cast_type: type = None) -> Any:
    """
    Safely get a value from a save dict with optional type casting.
    Never crashes, always returns a usable value.
    """
    try:
        value = data.get(key, default) if isinstance(data, dict) else default
        if cast_type is not None and value is not None:
            value = cast_type(value)
        return value
    except (ValueError, TypeError, KeyError):
        return default
