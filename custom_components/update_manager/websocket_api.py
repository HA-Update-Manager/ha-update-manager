"""Exposes Update Manager's computed state over HA's websocket API. This,
not the summary sensor, is the intended data source for Phase 2's panel
(see FUTURE.md) -- the sensor stays around as a cheap debug view, but a
growing update list / install history doesn't belong in an entity's state
machine footprint.

Also the panel's only way to change the staging rules: a config_entry's
options can't be written from a plain custom element, so save_settings
mutates it the same way the (now superseded) options flow did, going
through hass.config_entries.async_update_entry so the existing
update_listener/reload picks up the new rules exactly as before.

Single-instance integration (config_flow enforces this), so there is at
most one entry/coordinator/install log to read from at a time.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_MAJOR_BLOCKED,
    CONF_MAJOR_WAIT_DAYS,
    CONF_MINOR_BLOCKED,
    CONF_MINOR_WAIT_DAYS,
    CONF_PATCH_BLOCKED,
    CONF_PATCH_WAIT_DAYS,
    CONF_UNKNOWN_BLOCKED,
    CONF_UNKNOWN_WAIT_DAYS,
    DOMAIN,
    PROFILE_PRESETS,
)

_WS_REGISTERED = f"{DOMAIN}_ws_registered"


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/updates"})
def _handle_updates(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = hass.data.get(DOMAIN)
    updates = list(data["coordinator"].cache.values()) if data else []
    connection.send_result(msg["id"], {"updates": updates})


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/install_log"})
def _handle_install_log(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = hass.data.get(DOMAIN)
    entries = data["install_log"].entries if data else []
    connection.send_result(msg["id"], {"entries": entries})


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/get_settings"})
def _handle_get_settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    options = dict(entries[0].options) if entries else {}
    connection.send_result(msg["id"], {"options": options, "profiles": PROFILE_PRESETS})


@callback
@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "update_manager/save_settings",
        vol.Required(CONF_PATCH_WAIT_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
        vol.Required(CONF_PATCH_BLOCKED): bool,
        vol.Required(CONF_MINOR_WAIT_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
        vol.Required(CONF_MINOR_BLOCKED): bool,
        vol.Required(CONF_MAJOR_WAIT_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
        vol.Required(CONF_MAJOR_BLOCKED): bool,
        vol.Required(CONF_UNKNOWN_WAIT_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
        vol.Required(CONF_UNKNOWN_BLOCKED): bool,
    }
)
def _handle_save_settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    options = {k: v for k, v in msg.items() if k not in ("type", "id")}
    hass.config_entries.async_update_entry(entries[0], options=options)
    connection.send_result(msg["id"])


def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Registers the commands once. Safe to call again on entry reload
    (e.g. after saving settings) -- HA raises on a duplicate registration,
    so this is guarded rather than relying on callers."""
    if hass.data.get(_WS_REGISTERED):
        return
    hass.data[_WS_REGISTERED] = True
    websocket_api.async_register_command(hass, _handle_updates)
    websocket_api.async_register_command(hass, _handle_install_log)
    websocket_api.async_register_command(hass, _handle_get_settings)
    websocket_api.async_register_command(hass, _handle_save_settings)
