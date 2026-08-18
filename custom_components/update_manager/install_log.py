"""Persists a history of completed updates -- entity, old version, new
version, when, and release notes -- so the panel has something to show
under its "History" tab. This is genuinely new data only
Update Manager creates, unlike coordinator.py's ready/waiting/blocked status
(a live recomputation of HA's own update-entity state, never stored), so
unlike that one this does need real persistent storage. No entity: a
growing, unbounded history list doesn't belong in an entity's state/attribute
footprint, and the intended reader is the panel's own websocket_api call,
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
from .install_log_retention import DEFAULT_POLICY, apply_release_notes_retention, enforce_byte_backstop

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_install_log"

# Keeps the store from growing forever on an instance with a lot of update
# churn -- generous enough that the future panel will have plenty of history
# to show without needing to worry about pruning itself.
MAX_ENTRIES = 1000

# Absolute backstop on the store's own serialized size, on top of the
# release-notes retention policy (install_log_retention.py) that normally
# keeps this file well under 2 MB even on a busy instance -- see that
# module's own DEGRADED_POLICIES for what happens if this is ever reached.
_MAX_STORE_BYTES = 8 * 1024 * 1024


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
        supported_features: int,
        install_method: str,
        auto_install_reason: str | None = None,
        trusted_voter_usernames: list[str] | None = None,
        announced_at: str | None = None,
        available_since: str | None = None,
    ) -> None:
        # "auto_installed" kept as its own bool key too (derived, not a
        # second independent input) -- existing readers (sensor.py,
        # diagnostics.py, the panel, the EVENT_INSTALLED event) already
        # depend on it, and backup_used's own gate right below needs a
        # plain bool anyway. install_method is the new, more specific
        # source of truth callers pass in -- see __init__.py's own
        # _on_install for how "auto"/"manual"/"external" gets decided.
        auto_installed = install_method == "auto"
        release_notes = await _async_release_notes(self._hass, entity_id, supported_features)
        self._entries.append(
            {
                "entity_id": entity_id,
                "from_version": from_version,
                "to_version": to_version,
                "installed_at": dt_util.utcnow().isoformat(),
                "release_url": release_url,
                "release_notes": release_notes,
                "auto_installed": auto_installed,
                "install_method": install_method,
                # Only ever set for an auto-install: install_manager.py's own
                # _async_execute unconditionally sets `backup: True` on the
                # dispatched update.install call whenever the entity's
                # supported_features includes UpdateEntityFeature.BACKUP, no
                # other condition -- so for an auto-installed entry this is a
                # sure fact, not a guess. A manual install has no such
                # guarantee: it might go through HA's own native dialog
                # (its own separate backup checkbox, entirely invisible to
                # us) as easily as our own panel's Install button, so this
                # stays None there -- same "hide the fact entirely rather
                # than show an unreliable guess" treatment as
                # auto_install_reason below. Direct user feedback, 2026-08-01:
                # nowhere did the panel actually show whether that backup
                # succeeded
                # (following up on an earlier request to verify this
                # actually happens at all) -- this is what makes that
                # already-verified behaviour visible per install, not just
                # true in the code.
                "backup_used": bool(supported_features & UpdateEntityFeature.BACKUP) if auto_installed else None,
                # None on a manual install, or on any entry logged before
                # this field existed at all -- the panel hides these facts
                # entirely rather than showing "unknown" when they're None,
                # added alongside CONF_TRUSTED_VOTERS/effective_auto_install_state.
                "auto_install_reason": auto_install_reason,
                "trusted_voter_usernames": trusted_voter_usernames or [],
                "announced_at": announced_at,
                "available_since": available_since,
            }
        )
        if len(self._entries) > MAX_ENTRIES:
            del self._entries[: len(self._entries) - MAX_ENTRIES]
        now = dt_util.utcnow()
        apply_release_notes_retention(self._entries, DEFAULT_POLICY, now)
        enforce_byte_backstop(self._entries, now, _MAX_STORE_BYTES)
        await self._store.async_save(self._entries)

    async def async_rename_entity(self, old_entity_id: str, new_entity_id: str) -> None:
        """Relabels every existing entry's entity_id after a live HA entity
        registry rename, so this entity's history doesn't silently split in
        two -- see __init__.py's own EVENT_ENTITY_REGISTRY_UPDATED listener."""
        changed = False
        for entry in self._entries:
            if entry.get("entity_id") == old_entity_id:
                entry["entity_id"] = new_entity_id
                changed = True
        if changed:
            await self._store.async_save(self._entries)
