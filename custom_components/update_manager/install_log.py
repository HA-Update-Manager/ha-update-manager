"""Persists a history of completed updates -- entity, old version, new
version, when, and release notes -- so Phase 2's panel has something to show
under its "History" tab (see FUTURE.md). This is genuinely new data only
Update Manager creates, unlike coordinator.py's ready/waiting/blocked status
(a live recomputation of HA's own update-entity state, never stored), so
unlike that one this does need real persistent storage. No entity: a
growing, unbounded history list doesn't belong in an entity's state/attribute
footprint, and the intended reader is the future panel's websocket_api call,
not the state machine.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_install_log"

# Keeps the store from growing forever on an instance with a lot of update
# churn -- generous enough that the future panel will have plenty of history
# to show without needing to worry about pruning itself.
MAX_ENTRIES = 1000


async def _async_release_notes(hass: HomeAssistant, entity_id: str, supported_features: int) -> str | None:
    """Best-effort: the entity's full release notes, if it supports fetching
    them. Unlike release_url/release_summary, the long-form (often markdown)
    notes aren't a plain state attribute -- they're fetched on demand, the
    same way HA's own more-info dialog and its `update/release_notes`
    websocket command do, via the update entity's own async_release_notes()."""
    if not supported_features & UpdateEntityFeature.RELEASE_NOTES:
        return None
    try:
        component = hass.data.get("update")
        if component is None:
            return None
        entity = component.get_entity(entity_id)
        if entity is None:
            return None
        return await entity.async_release_notes()
    except Exception:
        _LOGGER.debug("Couldn't fetch release notes for %s", entity_id, exc_info=True)
        return None


class InstallLog:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store[list[dict[str, Any]]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._entries: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        self._entries = await self._store.async_load() or []

    @property
    def entries(self) -> list[dict[str, Any]]:
        return self._entries

    async def async_log_install(
        self,
        entity_id: str,
        from_version: str,
        to_version: str,
        *,
        release_url: str | None,
        release_summary: str | None,
        supported_features: int,
        auto_installed: bool,
        auto_install_reason: str | None = None,
        trusted_voter_usernames: list[str] | None = None,
        announced_at: str | None = None,
        available_since: str | None = None,
    ) -> None:
        release_notes = await _async_release_notes(self._hass, entity_id, supported_features)
        self._entries.append(
            {
                "entity_id": entity_id,
                "from_version": from_version,
                "to_version": to_version,
                "installed_at": dt_util.utcnow().isoformat(),
                "release_url": release_url,
                "release_summary": release_summary,
                "release_notes": release_notes,
                "auto_installed": auto_installed,
                # None on a manual install, or on any entry logged before
                # this field existed at all -- the panel hides these facts
                # entirely rather than showing "unknown" when they're None
                # (see FUTURE.md's own note on this, added alongside
                # CONF_TRUSTED_VOTERS/effective_auto_install_state).
                "auto_install_reason": auto_install_reason,
                "trusted_voter_usernames": trusted_voter_usernames or [],
                "announced_at": announced_at,
                "available_since": available_since,
            }
        )
        if len(self._entries) > MAX_ENTRIES:
            del self._entries[: len(self._entries) - MAX_ENTRIES]
        await self._store.async_save(self._entries)
