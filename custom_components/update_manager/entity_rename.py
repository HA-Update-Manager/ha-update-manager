"""The one mechanical step every manager's own async_rename_entity method
needs (see __init__.py's own EVENT_ENTITY_REGISTRY_UPDATED listener):
moving a plain dict entry from one key to another. Kept separate from each
manager's own save-timing (immediate/delayed/shared _async_save) and
nested-field decisions (e.g. a cache entry's own "entity_id" field, or a
NamedTuple needing _replace) -- those differ per manager and stay in each
manager's own method, only the pop/reinsert boilerplate is shared.
"""
from __future__ import annotations

from typing import Any


def relabel_key(mapping: dict[str, Any], old_key: str, new_key: str) -> Any | None:
    """Pops old_key and reinserts its value at new_key. Returns the value
    (so a caller can patch a nested field on it before persisting) if
    old_key existed, None if there was nothing to rename."""
    value = mapping.pop(old_key, None)
    if value is None:
        return None
    mapping[new_key] = value
    return value
