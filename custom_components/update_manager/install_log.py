"""Persists a history of completed updates -- entity, old version, new
version, when, and a release-notes link -- so Phase 2's panel has something
to show under its "History" tab (see FUTURE.md). This is genuinely new data
only Update Manager creates, unlike coordinator.py's ready/waiting/blocked
status (a live recomputation of HA's own update-entity state, never stored),
so unlike that one this does need real persistent storage. No entity: a
growing, unbounded history list doesn't belong in an entity's state/attribute
footprint, and the intended reader is the future panel's websocket_api call,
not the state machine.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_install_log"

# Keeps the store from growing forever on an instance with a lot of update
# churn -- generous enough that the future panel will have plenty of history
# to show without needing to worry about pruning itself.
MAX_ENTRIES = 1000


class InstallLog:
    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[list[dict[str, Any]]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._entries: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        self._entries = await self._store.async_load() or []

    @property
    def entries(self) -> list[dict[str, Any]]:
        return self._entries

    async def async_log_install(
        self, entity_id: str, from_version: str, to_version: str, *, release_url: str | None
    ) -> None:
        self._entries.append(
            {
                "entity_id": entity_id,
                "from_version": from_version,
                "to_version": to_version,
                "installed_at": dt_util.utcnow().isoformat(),
                "release_url": release_url,
            }
        )
        if len(self._entries) > MAX_ENTRIES:
            del self._entries[: len(self._entries) - MAX_ENTRIES]
        await self._store.async_save(self._entries)
