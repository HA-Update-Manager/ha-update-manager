"""Exposes the master pause switch (const.py's CONF_ENABLED) as a real
switch entity, not only a Settings-panel toggle -- direct user feedback:
wanted to control/automate this from a dashboard or an automation, not
only from the panel. Both stay in sync regardless of which one changes
it: this entity reads/writes the exact same coordinator.master_enabled
and config entry option the panel's own save_settings already does,
through the same async_apply_options every settings change already goes
through (see websocket_api.py's own docstring for why that's shared
rather than reimplemented a third time here).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLED, DOMAIN
from .coordinator import UpdateManagerCoordinator
from .websocket_api import async_apply_options

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([UpdateManagerEnabledSwitch(hass, config_entry, coordinator)])


class UpdateManagerEnabledSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_unique_id = f"{DOMAIN}_enabled"
    _attr_name = "Update Manager Enabled"
    _attr_icon = "mdi:update"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: UpdateManagerCoordinator) -> None:
        self.hass = hass
        self._entry = entry
        self._coordinator = coordinator

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.hass.is_running:
            self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._coordinator.master_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        # Same config-entry option the panel's own Settings tab saves
        # (const.py's CONF_ENABLED), so the panel's toggle and this entity
        # never drift: whichever one changes it, the other reads the exact
        # same coordinator.master_enabled/stored option. Persisted first,
        # not just applied in memory, so it survives a restart the same
        # way the panel's own save does.
        options = {**self._entry.options, CONF_ENABLED: enabled}
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        # Applied directly here, awaited, not just left to the config
        # entry's own update_listener (fired as an unawaited background
        # task): same reasoning as websocket_api.py's own
        # _handle_save_settings, this call should reflect the real,
        # already-applied state by the time it returns, not a stale one.
        # Also what fires this entity's own state update, via the
        # coordinator listener registered in async_added_to_hass -- no
        # separate self.async_write_ha_state() call needed here.
        await async_apply_options(self.hass, options)
