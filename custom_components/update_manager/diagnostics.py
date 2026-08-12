"""Config entry diagnostics -- lets you check the coordinator's current
per-update status and the install log with a click in the UI (Settings ->
Devices & Services -> Update Manager -> the three-dot menu -> Download
diagnostics), instead of needing the browser console/websocket_api directly.
A modest, low-effort way to inspect the install log that predates the
panel's own History tab, still useful for support/debugging today.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .runtime_data import UpdateManagerConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: UpdateManagerConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data
    # None-guarded, found by code review, 2026-07-29: runtime_data is None
    # both before setup completes and (see __init__.py's own
    # async_unload_entry) after a clean unload -- HA's own UI normally only
    # offers "Download diagnostics" for a currently-loaded entry, but this
    # degrades gracefully instead of raising AttributeError on the narrower
    # race windows around that (a reload's unload-then-setup gap, for one).
    if data is None:
        return {"options": dict(entry.options)}
    # One shared instant for the whole export, not one dt_util.utcnow() call
    # per entity inside export_entry -- see websocket_api.py's own matching
    # comment in _handle_updates.
    now = dt_util.utcnow()
    return {
        # The raw, actually-persisted settings -- added 2026-07-16 to check
        # a save without needing the browser console/websocket_api either.
        "options": dict(entry.options),
        # export_entry, not the raw cache entry -- same reasoning
        # websocket_api.py's own _handle_updates has: status/remaining_seconds/
        # ready_at computed fresh at export time, not whatever a periodic
        # recompute last happened to store.
        "updates": [
            data.coordinator.export_entry(cached, now) for cached in data.coordinator.cache.values()
        ],
        "install_log": data.install_log.entries,
        "pending_installs": [
            {
                "entity_id": p.entity_id,
                "to_version": p.to_version,
                "announced_at": p.announced_at.isoformat(),
                "execute_at": p.execute_at.isoformat(),
            }
            for p in data.install_manager.all_pending
        ],
    }
