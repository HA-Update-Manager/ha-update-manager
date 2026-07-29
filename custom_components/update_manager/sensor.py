"""A single "Update Manager" summary sensor, not one entity per `update.*`
entity -- a large instance can easily have 100+ update entities, which
would otherwise mean 100+ near-useless extra entities, pure clutter for
what's fundamentally one overview. State is the number of updates ready to
install now; the per-update breakdown (version jump, status, remaining
wait) lives in this one entity's attributes.

Reads from the shared UpdateManagerCoordinator (coordinator.py) rather than
computing anything itself -- this entity is a cheap debug view (Developer
Tools -> States) on top of that shared computation, not its source (see
FUTURE.md): Phase 2's future panel is meant to read the coordinator via
websocket_api.py instead, so it never depends on this entity existing.

Deliberately minimal so far: read-only, no auto-install/rollout-pacing
wired up yet.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import UpdateManagerCoordinator
from .runtime_data import UpdateManagerConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: UpdateManagerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([UpdateManagerSummarySensor(config_entry.runtime_data.coordinator)])


class UpdateManagerSummarySensor(SensorEntity):
    _attr_should_poll = False
    _attr_unique_id = f"{DOMAIN}_summary"
    # has_entity_name + translation_key, not a bare _attr_name -- quality-scale
    # has-entity-name/entity-translations. No device_info exists on this
    # entity, so friendly_name is just entity.name unchanged (confirmed
    # against HA's own entity-naming docs): this is a pure compliance change,
    # not a visible rename. Name/icon now come from translations/en.json and
    # icons.json respectively, not hardcoded here.
    _attr_has_entity_name = True
    _attr_translation_key = "summary"

    def __init__(self, coordinator: UpdateManagerCoordinator) -> None:
        self._coordinator = coordinator
        self._refresh_from_coordinator()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh_from_coordinator()
        if self.hass.is_running:
            self.async_write_ha_state()

    def _refresh_from_coordinator(self) -> None:
        updates = list(self._coordinator.cache.values())
        ready = sum(1 for u in updates if u["status"] == "ready")
        waiting = sum(1 for u in updates if u["status"] == "waiting")
        blocked = sum(1 for u in updates if u["status"] == "blocked")

        self._attr_native_value = ready
        self._attr_extra_state_attributes = {
            "updates": updates,
            "ready_count": ready,
            "waiting_count": waiting,
            "blocked_count": blocked,
        }
