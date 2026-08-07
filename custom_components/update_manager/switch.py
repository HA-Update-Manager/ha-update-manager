"""Exposes the master pause switch (const.py's CONF_ENABLED) as a real
switch entity, not only a Settings-panel toggle, direct user feedback:
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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLED, DOMAIN
from .coordinator import UpdateManagerCoordinator
from .device import device_info
from .runtime_data import UpdateManagerConfigEntry
from .websocket_api import async_apply_options

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UpdateManagerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [UpdateManagerEnabledSwitch(hass, config_entry, config_entry.runtime_data.coordinator)]
    )


class UpdateManagerEnabledSwitch(SwitchEntity):
    _attr_should_poll = False
    # unique_id intentionally unchanged (was already f"{DOMAIN}_enabled"
    # before this entity got a device) -- only entity_id/name are changing
    # here, and unique_id is the one thing that must never move, or this
    # would look like a brand-new entity to HA instead of the same one
    # being renamed, orphaning history/customizations tied to the old id.
    # __init__.py's own _migrate_enabled_switch_entity_id renames the
    # *entity_id* in place (switch.update_manager_enabled ->
    # switch.update_manager) for anyone upgrading from before this device
    # existed.
    _attr_unique_id = f"{DOMAIN}_enabled"
    # has_entity_name True + _attr_name None (not a translated name) --
    # this is now the device's own unnamed "main feature" entity (direct
    # user feedback, 2026-08-07, questioning why "Enabled" was even part of
    # the entity_id at all, given the state itself could just as easily be
    # "disabled"): its friendly
    # name is just the device's own name, "Update Manager", the on/off
    # state itself already says everything "Enabled"/"State" would have
    # tried to add on top. translation_key is kept (not removed) purely
    # for icon-translations lookup (icons.json's own state-aware icon) --
    # confirmed against Entity._name_internal's real source: it returns
    # _attr_name immediately whenever the attribute is set at all (even to
    # None), before ever consulting translation_key's own name, so this
    # combination is safe and does exactly what it looks like.
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "enabled"
    # Deliberately no entity_category (was EntityCategory.CONFIG until
    # direct user feedback, 2026-08-07, expecting the main switch under
    # "Controls" rather than "Configuration"). Confirmed against
    # developers.home-assistant.io's own entity docs: CONFIG is for an
    # entity that changes a *secondary* aspect of a device (its own
    # example: a switch's background-illumination toggle), not the
    # device's own main function -- and this virtual device's entire
    # reason to exist *is* this switch (has_entity_name=True + name=None
    # above already marks it as the device's own unnamed main feature
    # entity, see that combination's own comment), so it belongs among
    # primary controls like any other device's main on/off switch, not
    # tucked into Configuration alongside secondary settings.

    def __init__(self, hass: HomeAssistant, entry: UpdateManagerConfigEntry, coordinator: UpdateManagerCoordinator) -> None:
        self.hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._attr_device_info = device_info(entry)

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
        # coordinator listener registered in async_added_to_hass, no
        # separate self.async_write_ha_state() call needed here.
        await async_apply_options(self.hass, options)
