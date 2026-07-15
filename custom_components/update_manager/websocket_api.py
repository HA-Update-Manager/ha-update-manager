"""Exposes Update Manager's computed state over HA's websocket API. This,
not the summary sensor, is the intended data source for Phase 2's future
panel (see FUTURE.md) -- the sensor stays around as a cheap debug view, but
a growing update list / install history doesn't belong in an entity's state
machine footprint.

Single-instance integration (config_flow enforces this), so there is at
most one coordinator/install log to read from at a time.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_WS_REGISTERED = f"{DOMAIN}_ws_registered"


@callback
@websocket_api.websocket_command({vol.Required("type"): "update_manager/updates"})
def _handle_updates(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = hass.data.get(DOMAIN)
    updates = list(data["coordinator"].cache.values()) if data else []
    connection.send_result(msg["id"], {"updates": updates})


@callback
@websocket_api.websocket_command({vol.Required("type"): "update_manager/install_log"})
def _handle_install_log(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = hass.data.get(DOMAIN)
    entries = data["install_log"].entries if data else []
    connection.send_result(msg["id"], {"entries": entries})


def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Registers the commands once. Safe to call again on entry reload
    (e.g. after saving the options flow) -- HA raises on a duplicate
    registration, so this is guarded rather than relying on callers."""
    if hass.data.get(_WS_REGISTERED):
        return
    hass.data[_WS_REGISTERED] = True
    websocket_api.async_register_command(hass, _handle_updates)
    websocket_api.async_register_command(hass, _handle_install_log)
