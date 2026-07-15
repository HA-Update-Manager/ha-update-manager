"""Config entry diagnostics -- lets you check the coordinator's current
per-update status and the install log with a click in the UI (Settings ->
Devices & Services -> Update Manager -> the three-dot menu -> Download
diagnostics), instead of needing the browser console/websocket_api directly.
Exactly the "bescheiden eerste versie" FUTURE.md describes for the install
log before Phase 2's panel exists.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    data = hass.data.get(DOMAIN, {})
    coordinator = data.get("coordinator")
    install_log = data.get("install_log")
    return {
        "updates": list(coordinator.cache.values()) if coordinator else [],
        "install_log": install_log.entries if install_log else [],
    }
