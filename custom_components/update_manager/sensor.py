"""One sensor per status the Updates tab itself groups by -- Ready to
update, Postponed, Discouraged, Skipped, Not installable -- replacing the
single UpdateManagerSummarySensor (direct user feedback, 2026-08-07: "State
1 zegt niks" -- a lone summary sensor's state was just a bare "ready" count
with everything else buried in attributes, not something you could point an
automation's numeric_state trigger at for, say, "notify me when something's
Discouraged"). update_status.categorize_updates does the actual grouping,
mirroring the panel JS's own groupUpdates() exactly (see that module's own
docstring for the shared precedence rule).

Still one entity per *status*, not one per `update.*` entity -- a large
instance can easily have 100+ update entities, which would otherwise mean
100+ near-useless extra entities for what's fundamentally 5 overviews (see
the original summary sensor's own reasoning, carried over unchanged). State
is each bucket's own count; the per-update breakdown (entity_id, version
jump) lives in that one sensor's own attributes.

Reads from the shared UpdateManagerCoordinator (coordinator.py) rather than
computing anything itself -- these are a cheap, read-only view on top of
that shared computation, not its source (see FUTURE.md).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import UpdateManagerCoordinator
from .device import device_info
from .runtime_data import UpdateManagerConfigEntry
from .update_status import STATUSES, categorize_updates, icon_for_status

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UpdateManagerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data.coordinator
    async_add_entities(
        [UpdateManagerStatusSensor(config_entry, coordinator, status) for status in STATUSES]
    )


class UpdateManagerStatusSensor(SensorEntity):
    _attr_should_poll = False
    _attr_native_unit_of_measurement = "updates"
    # has_entity_name + translation_key -- quality-scale has-entity-name/
    # entity-translations. Combined with device_info below, each entity's
    # own friendly name (e.g. "Ready to update", from translations/en.json)
    # reads as "Update Manager Ready to update" wherever HA shows the full
    # device+entity name, and just "Ready to update" on the device's own
    # page -- no hand-written "Update Manager " prefix needed here.
    _attr_has_entity_name = True

    def __init__(self, entry: UpdateManagerConfigEntry, coordinator: UpdateManagerCoordinator, status: str) -> None:
        self._entry = entry
        self._coordinator = coordinator
        self._status = status
        self._attr_unique_id = f"{DOMAIN}_{status}"
        self._attr_translation_key = status
        self._attr_device_info = device_info(entry)
        self._refresh_from_coordinator()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh_from_coordinator()
        if self.hass.is_running:
            self.async_write_ha_state()

    @property
    def icon(self) -> str | None:
        """None for every status except blocked/not_installable (see
        update_status.py's own icon_for_status docstring) -- returning None
        here falls straight back to icons.json's own translated default,
        exactly the icon this entity would show without this property
        existing at all."""
        return icon_for_status(self._status, self._attr_native_value)

    def _refresh_from_coordinator(self) -> None:
        bucket = categorize_updates(list(self._coordinator.cache.values())).get(self._status, [])
        self._attr_native_value = len(bucket)
        self._attr_extra_state_attributes = {
            "entities": [
                {
                    "entity_id": u.get("entity_id"),
                    "installed_version": u.get("installed_version"),
                    "latest_version": u.get("latest_version"),
                }
                for u in bucket
            ]
        }
